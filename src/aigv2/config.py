import os
import re
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

STEPS = ["extract", "rank", "write_days", "write_sections", "title", "qc_prose", "qc_sense"]
# Unconfirmed estimates (Places API (New) Enterprise SKUs incl. Place Details with opening hours, Routes Essentials
# per element) — confirm against Google's price list before relying on them.
_BANNED_MODEL = re.compile(r"(?:^|[/:])gpt-6(?:\.0)?-sol(?:$|[^.\d])", re.I)
GOOGLE_USD_PER_CALL = {"text_search": 0.035, "nearby": 0.035, "details": 0.020, "route_element": 0.005}


class Settings(BaseModel):
    models: dict[str, str]
    fallback_model: str = "gpt-6.1-sol"
    walk_max_min: int = 10
    lunch_max_min: int = 15
    dinner_max_min: int = 20
    cache_days: int = 30
    inr_round: int = 50
    slot_windows: dict[str, tuple[str, str]] = Field(default_factory=lambda: {
        "morning": ("09:00", "12:00"),
        "lunch": ("12:30", "14:00"),
        "afternoon": ("14:00", "17:30"),
        "evening": ("17:30", "20:00"),
        "dinner": ("19:30", "21:00"),
    })
    country_meal_windows: dict[str, dict[str, tuple[str, str]]] = Field(default_factory=lambda: {
        "Spain": {"lunch": ("13:30", "16:00"), "dinner": ("20:30", "22:30")},
        "Greece": {"dinner": ("20:00", "22:30")},
    })
    data_root: Path = Path("aigv2_data")
    google_usd_per_call: dict[str, float] = Field(default_factory=lambda: dict(GOOGLE_USD_PER_CALL))

    @model_validator(mode="after")
    def _no_gpt_6_sol(self) -> "Settings":
        bad = [f"{k}={m}" for k, m in [*self.models.items(), ("fallback", self.fallback_model)] if _BANNED_MODEL.search(m)]
        if bad:
            raise ValueError(f"gpt-6-sol (6.0) must never be used; use gpt-6.1-sol ({', '.join(bad)})")
        return self


def load_settings() -> Settings:
    fast = os.environ.get("AI_MODEL_FAST") or "gpt-6-luna"
    strong = os.environ.get("AI_MODEL") or "gpt-6.1-sol"
    models = {}
    for step in STEPS:
        base = strong if step == "qc_sense" else fast
        models[step] = os.environ.get(f"AIGV2_MODEL_{step.upper()}") or base
    return Settings(models=models)
