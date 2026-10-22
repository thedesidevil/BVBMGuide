import json
from typing import Optional

from pydantic import BaseModel, Field

from src.aigv2.models import Answers, Finding, TripPlan
from src.aigv2.qc.reader import DocModel
from src.aigv2.qc.rules import _f

_PROSE_SYSTEM = (
    "You fact-check descriptions in a travel guide. Flag only sentences stating a specific verifiable fact "
    "(dates, numbers, history, prices, named people) that is likely wrong. Do not flag opinions or style. "
    "Copy each flagged sentence verbatim into 'quote'. Answer in JSON: "
    '{"issues": [{"quote": "...", "problem": "...", "day": null}]}. Return {"issues": []} when nothing is wrong.'
)
_SENSE_SYSTEM = (
    "You are the final reviewer of a finished travel guide before it goes to a client. Given the guide text, the trip "
    "plan and the planner's answers, list anything that does not make sense or that a human should double-check: "
    "contradictions, impossible timings, wrong cities, advice that does not fit the travellers. Do not rewrite "
    "anything and do not flag style. For each item copy a short phrase verbatim from the guide into 'quote'. "
    'Answer in JSON: {"issues": [{"quote": "...", "problem": "...", "day": 2}]}, where day is the guide day number '
    'it concerns or null. Return {"issues": []} when all is fine.'
)


class _Issue(BaseModel):
    quote: str = ""
    problem: str
    day: Optional[int] = None


class _Issues(BaseModel):
    issues: list[_Issue] = Field(default_factory=list)


def _day_of(doc: DocModel, quote: str) -> Optional[int]:
    q = " ".join(quote.split())
    if not q:
        return None
    for p in doc.paragraphs:
        if q in " ".join(p.text.split()):
            return p.day
    return None


def prose_fact_check(doc: DocModel, llm) -> list[Finding]:
    items = [(v.name, v.body) for d in doc.days for s in d.slots for v in s.venues if v.body] + \
            [(v.name, v.body) for v in doc.section_venues if v.body]
    if not items:
        return []
    prompt = "Descriptions:\n" + "\n".join(f"{i}. {name}: {body}" for i, (name, body) in enumerate(items, 1))
    out = llm.run_json("qc_prose", _PROSE_SYSTEM, prompt, _Issues)
    return [_f("prose_fact", i.problem, i.quote, _day_of(doc, i.quote) or i.day) for i in out.issues if i.problem]


def sense_check(doc: DocModel, trip: TripPlan, llm, answers: Optional[Answers] = None) -> list[Finding]:
    if hasattr(answers, "model_dump"):
        answers = answers.model_dump(mode="json")
    prompt = (f"Guide text:\n{doc.text}\n\nTrip plan JSON:\n{trip.model_dump_json()}\n\n"
              f"Pre-flight answers:\n{json.dumps(answers or {}, ensure_ascii=False)}")
    out = llm.run_json("qc_sense", _SENSE_SYSTEM, prompt, _Issues)
    return [_f("sense", i.problem, i.quote, _day_of(doc, i.quote) or i.day) for i in out.issues if i.problem]
