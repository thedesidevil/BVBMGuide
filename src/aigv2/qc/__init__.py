from src.aigv2.llm import LLMStepError
from src.aigv2.qc.annotate import annotate
from src.aigv2.qc.facts import check_facts
from src.aigv2.qc.llm_checks import prose_fact_check, sense_check
from src.aigv2.qc.reader import read_docx
from src.aigv2.qc.report import QCResult, build_cost, marker_kinds, write_report
from src.aigv2.qc.rules import _f, check_rules


def run_qc(docx_bytes, trip, answers, library, places, routes, llm, exclusions, unit_usd=None, countries=None,
           settings=None):
    log_start = len(llm.cost_log)
    google_start = {**places.calls, **routes.calls}
    doc = read_docx(docx_bytes)
    findings = check_rules(doc, trip, library)
    fact_findings, rows = check_facts(doc, trip, places, routes, countries=countries, settings=settings)
    findings += fact_findings
    for name, check in (("prose_fact", lambda: prose_fact_check(doc, llm)),
                        ("sense", lambda: sense_check(doc, trip, llm, answers))):
        try:
            findings += check()
        except LLMStepError as e:
            findings.append(_f("qc_llm_failed", f"AI check '{name}' could not complete: {e}"))
    google_now = {**places.calls, **routes.calls}
    cost = build_cost(llm.cost_log[log_start:], {k: v - google_start.get(k, 0) for k, v in google_now.items()},
                      unit_usd)
    result = QCResult.build(findings, len(doc.markers), rows, marker_kinds(doc.markers), cost)
    report, _ = write_report(result, exclusions, cost)
    return annotate(docx_bytes, findings), result, report
