from __future__ import annotations
import io
import re

import openpyxl

from src.hotel_options.decoder import decode_col_h
from src.hotel_options.models import (
    HotelRow, PlanPricing, Plan, UnknownCode, ParseResult,
)

_PLAN_RE = re.compile(r'^PLAN\s+[A-Z]$', re.IGNORECASE)
_FILENAME_RE = re.compile(
    r'(?:DO NOT SHARE_\s*)?([^_]+)_Accommodation Options_([^_.]+)\.xlsx$',
    re.IGNORECASE,
)


def extract_filename_meta(filename: str) -> tuple[str, str]:
    m = _FILENAME_RE.search(filename)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    stem = filename.rsplit(".", 1)[0]
    parts = stem.split("_")
    return "", parts[-1].strip() if parts else ""


def _numeric(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _make_dummy_row(length: int = 14) -> tuple:
    """Create a synthetic row with all None values for flushing without a real summary."""
    class NoneCell:
        value = None
    return tuple(NoneCell() for _ in range(length))


def parse_excel(xlsx_bytes: bytes, codes: dict[str, str]) -> ParseResult:
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb.active

    plans: list[Plan] = []
    unknown_codes: list[UnknownCode] = []

    current_label: str | None = None
    current_hotels: list[HotelRow] = []
    running_online = 0.0
    running_b2b = 0.0

    def _flush(summary_row) -> None:
        nonlocal current_label, current_hotels, running_online, running_b2b
        if current_label is None:
            return
        col_i = _numeric(summary_row[8].value) if len(summary_row) > 8 else None
        col_j = _numeric(summary_row[9].value) if len(summary_row) > 9 else None
        col_l = _numeric(summary_row[11].value) if len(summary_row) > 11 else None
        col_m = _numeric(summary_row[12].value) if len(summary_row) > 12 else None
        col_n = _numeric(summary_row[13].value) if len(summary_row) > 13 else None

        total_online = col_i if col_i is not None else running_online
        total_b2b = col_j if col_j is not None else running_b2b
        discount = col_l or 0.0
        discounted = col_m if col_m is not None else (total_online - discount)
        pct = col_n if col_n is not None else (discount / total_online * 100 if total_online else 0.0)

        plans.append(Plan(
            label=current_label,
            hotels=list(current_hotels),
            pricing=PlanPricing(
                total_online_price=total_online,
                total_b2b_price=total_b2b,
                customer_discount=discount,
                discounted_price=discounted,
                discount_pct=pct,
            ),
        ))
        current_label = None
        current_hotels = []
        running_online = 0.0
        running_b2b = 0.0

    past_first_plan = False

    for row in ws.iter_rows():
        cell_a = row[0]
        val_a = cell_a.value
        str_a = str(val_a).strip() if val_a is not None else ""

        if val_a and _PLAN_RE.match(str_a):
            past_first_plan = True
            # Flush previous plan before starting new one (handles missing summary row)
            if current_label is not None:
                _flush(_make_dummy_row())
            current_label = str_a.title()  # "PLAN A" → "Plan A"
            current_hotels = []
            running_online = 0.0
            running_b2b = 0.0
            continue

        if not past_first_plan:
            continue

        col_i_val = row[8].value if len(row) > 8 else None
        col_l_val = row[11].value if len(row) > 11 else None

        # Plan summary: col A blank, col I or col L numeric
        if not val_a and (_numeric(col_i_val) is not None or _numeric(col_l_val) is not None):
            _flush(row)
            continue

        # Hotel row: col A non-empty, col I numeric, no strikethrough
        if val_a and _numeric(col_i_val) is not None:
            if cell_a.font and cell_a.font.strike:
                continue

            col_h_val = row[7].value if len(row) > 7 else None
            decoded = decode_col_h(str(col_h_val) if col_h_val is not None else None, codes)

            for unk in decoded.unknowns:
                unknown_codes.append(UnknownCode(
                    code=unk,
                    hotel_name=str_a,
                    plan_label=current_label or "",
                ))

            online_raw = _numeric(col_i_val)
            online = online_raw if online_raw is not None else 0.0
            b2b_raw = _numeric(row[9].value) if len(row) > 9 else None
            b2b = b2b_raw if b2b_raw is not None else 0.0
            running_online += online
            running_b2b += b2b

            current_hotels.append(HotelRow(
                name=str_a,
                category=str(row[1].value).strip() if row[1].value else "",
                room_type=str(row[2].value).strip() if row[2].value else "",
                cancellation=decoded.cancellation,
                meal_type=decoded.meal_type,
                online_price=online,
            ))

    return ParseResult(plans=plans, unknown_codes=unknown_codes, not_found=[])
