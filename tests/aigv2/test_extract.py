from datetime import date
from pathlib import Path
from types import SimpleNamespace

from src.aigv2.config import Settings
from src.aigv2.intake.attachments import Attachment
from src.aigv2.intake.extract import SYSTEM_PROMPT, dedupe_legs, extract_trip, validate_trip
from src.aigv2.intake.template import IntakeFields
from src.aigv2.llm import StepLLM
from src.aigv2.models import TripPlan

FIX = Path(__file__).parent / "fixtures" / "nyc_trip"


def expected() -> TripPlan:
    return TripPlan.model_validate_json((FIX / "expected_trip_plan.json").read_text())


class FakeClient:
    def __init__(self, model, replies, calls):
        self.model = model
        self._replies = replies
        self._calls = calls
        self._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self._create)))

    def _create(self, **kw):
        self._calls.append((self.model, kw))
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        msg = SimpleNamespace(content=self._replies[self.model])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def make_llm(replies):
    calls = []
    llm = StepLLM(Settings(models={"extract": "gpt-6-luna"}),
                  client_factory=lambda m: FakeClient(m, replies, calls))
    return llm, calls


def attachments():
    return [
        Attachment(name="hotel_voucher.txt", kind="other", text=(FIX / "hotel_voucher.txt").read_text(),
                   image_only=False, has_images=False),
        Attachment(name="flight_ticket.txt", kind="other", text=(FIX / "flight_ticket.txt").read_text(),
                   image_only=False, has_images=False),
        Attachment(name="dup.txt", kind="other", text="DUPLICATE BODY", image_only=False,
                   has_images=False, duplicate_of="hotel_voucher.txt"),
        Attachment(name="broken.pdf", kind="pdf", text="BROKEN BODY", image_only=False,
                   has_images=False, error="unreadable"),
        Attachment(name="scan.png", kind="image", text="", image_only=True, has_images=True),
    ]


def test_extract_passes_inputs_to_llm():
    exp = expected()
    llm, calls = make_llm({"gpt-6-luna": exp.model_dump_json()})
    intake = IntakeFields(values={"Client name": "Test Client", "Notes": (FIX / "notes.txt").read_text()},
                          see_attachments={"Hotels"})
    plan = extract_trip(intake, attachments(), llm)
    assert plan == exp
    msgs = calls[0][1]["messages"]
    assert msgs[0]["content"] == SYSTEM_PROMPT and "JSON" in SYSTEM_PROMPT
    prompt = msgs[1]["content"]
    assert "HP-48213" in prompt and "ZQ7K2P" in prompt
    assert "Client name: Test Client" in prompt and "Choose your day trip" in prompt
    assert "scan.png" in prompt
    assert "DUPLICATE BODY" not in prompt and "BROKEN BODY" not in prompt


def test_validate_trip_flags_out_of_range_day():
    plan = expected()
    plan.days[0] = plan.days[0].model_copy(update={"date": date(2027, 3, 20)})
    problems = validate_trip(plan)
    assert any("2027-03-20" in p and "outside" in p for p in problems)


def test_validate_trip_flags_bad_stay_zero_days_and_duplicates():
    plan = expected()
    plan.hotels[0] = plan.hotels[0].model_copy(update={"check_out": plan.hotels[0].check_in})
    assert any("check_out" in p for p in validate_trip(plan))
    assert validate_trip(expected().model_copy(update={"days": []})) == ["no days extracted"]
    dup = expected()
    dup.days.append(dup.days[0])
    assert any("duplicate" in p for p in validate_trip(dup))
    assert validate_trip(expected()) == []


def test_invalid_extraction_triggers_fallback():
    bad = expected().model_copy(update={"days": []})
    llm, calls = make_llm({"gpt-6-luna": bad.model_dump_json(), "gpt-6.1-sol": expected().model_dump_json()})
    plan = extract_trip(None, attachments(), llm)
    assert plan == expected()
    assert [c[0] for c in calls] == ["gpt-6-luna", "gpt-6.1-sol"]
    assert "no days extracted" in calls[1][1]["messages"][-1]["content"]


def test_dedupe_legs_merges_per_passenger_tickets():
    plan = expected()
    leg = plan.transport[0]
    other_dep = leg.model_copy(update={"depart": leg.depart.replace(hour=21), "pax_label": "TEST/GUEST MS"})
    same = leg.model_copy(update={"pax_label": "TEST/GUEST MS", "seat": "14B"})
    plan.transport = [leg, same, other_dep]
    out = dedupe_legs(plan)
    assert len(out.transport) == 2
    assert out.transport[0].pax_label == "TEST/CLIENT MR, TEST/GUEST MS"
    assert out.transport[0].seat == "14A, 14B"
    assert out.transport[1].depart.hour == 21
    third = leg.model_copy(update={"pax_label": "TEST/KID MSTR", "seat": "14A"})
    blank = leg.model_copy(update={"pax_label": "TEST/BABY", "seat": ""})
    plan.transport = [leg, same, third, blank]
    assert dedupe_legs(plan).transport[0].seat == "14A, 14B"


def test_extract_dedupes_llm_output():
    exp = expected()
    exp.transport = [exp.transport[0], exp.transport[0].model_copy(update={"pax_label": "TEST/GUEST MS"})]
    llm, _ = make_llm({"gpt-6-luna": exp.model_dump_json()})
    assert len(extract_trip(None, attachments(), llm).transport) == 1
