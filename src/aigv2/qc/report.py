import re
from collections import Counter, defaultdict

from pydantic import BaseModel, Field

from src.aigv2.models import Finding
from src.aigv2.planning.meals import Exclusion
from src.aigv2.qc.facts import FactRow

GOOGLE_UNIT_USD = {"text_search": 0.035, "nearby": 0.035, "matrix_elements": 0.005, "directions": 0.005}
GOOGLE_LABELS = {"text_search": "Places text search", "nearby": "Places nearby search",
                 "matrix_elements": "Routes matrix elements", "directions": "Routes directions"}
_MARKER_KIND = re.compile(r"⚠ ([A-Z ]*[A-Z])")


class QCResult(BaseModel):
    passed: bool
    findings: list[Finding]
    marker_count: int
    fact_rows: list[FactRow] = Field(default_factory=list)
    marker_kinds: dict[str, int] = Field(default_factory=dict)
    cost: dict = Field(default_factory=dict)

    @classmethod
    def build(cls, findings: list[Finding], marker_count: int, fact_rows: list[FactRow],
              marker_kinds: dict[str, int] | None = None, cost: dict | None = None) -> "QCResult":
        return cls(passed=not findings and marker_count == 0, findings=findings, marker_count=marker_count,
                   fact_rows=fact_rows, marker_kinds=marker_kinds or {}, cost=cost or {})


def marker_kinds(markers: list[str]) -> dict[str, int]:
    return dict(Counter(m.group(1) if (m := _MARKER_KIND.match(t)) else t for t in markers))


def build_cost(llm_log: list[dict], google_calls: dict[str, int]) -> dict:
    steps: dict[tuple[str, str], dict] = {}
    for e in llm_log:
        row = steps.setdefault((e["step"], e["model"]), {"step": e["step"], "model": e["model"], "calls": 0, "usd": 0.0})
        row["calls"] += 1
        row["usd"] += e["usd"]
    ai = {"steps": list(steps.values()), "usd": sum(r["usd"] for r in steps.values())}
    apis = [{"api": k, "label": GOOGLE_LABELS.get(k, k), "calls": n, "unit_usd": GOOGLE_UNIT_USD.get(k, 0.0),
             "usd": n * GOOGLE_UNIT_USD.get(k, 0.0)} for k, n in google_calls.items() if n]
    google = {"apis": apis, "usd": sum(a["usd"] for a in apis)}
    return {"ai": ai, "google": google, "total_usd": ai["usd"] + google["usd"]}


def write_report(result: QCResult, exclusions: list[Exclusion], cost: dict) -> tuple[str, dict]:
    status = "PASS" if result.passed else "FAIL"
    lines = ["# QC report", "", "## Summary", "",
             f"**{status}** — {len(result.findings)} findings, {result.marker_count} markers remaining, "
             f"{len(result.fact_rows)} venues fact-checked", "", "## Markers by type", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(result.marker_kinds.items())] or ["None."]
    lines += ["", "## Findings by day", ""]
    by_day: dict = defaultdict(list)
    for f in result.findings:
        by_day[f.day].append(f)
    for day in sorted(by_day, key=lambda d: (d is None, d or 0)):
        lines.append(f"### {'General' if day is None else f'Day {day}'}")
        lines += [f"- [{f.severity}] {f.rule}: {f.message}" for f in by_day[day]]
        lines.append("")
    if not by_day:
        lines += ["None.", ""]
    lines += ["## Restaurants excluded", "",
              "Differences between the library and Google, for the team to fix via the library tool.", ""]
    lines += [f"- {e.name} ({e.reason}): {e.detail}" for e in exclusions] or ["None."]
    lines += ["", "## Cost", "", "### AI", ""]
    ai, google = cost.get("ai", {}), cost.get("google", {})
    lines += [f"- {s['step']} · {s['model']}: {s['calls']} calls, ${s['usd']:.4f}" for s in ai.get("steps", [])]
    lines += [f"AI total: ${ai.get('usd', 0.0):.4f}", "", "### Google", ""]
    lines += [f"- {a['label']}: {a['calls']} × ${a['unit_usd']:.3f} = ${a['usd']:.3f}" for a in google.get("apis", [])]
    lines += [f"Google total: ${google.get('usd', 0.0):.3f}", "", f"**Total: ${cost.get('total_usd', 0.0):.3f}**", ""]
    data = {"passed": result.passed, "marker_count": result.marker_count, "marker_kinds": result.marker_kinds,
            "findings": [f.model_dump() for f in result.findings],
            "fact_rows": [r.model_dump() for r in result.fact_rows],
            "exclusions": [e.model_dump() for e in exclusions], "cost": cost}
    return "\n".join(lines), data
