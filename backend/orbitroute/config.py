"""Runtime settings, read from the environment (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    budget_hard_cap_usd: float
    run_cap_usd: float
    paid_calls_enabled: bool
    budget_state_path: Path

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        return cls(
            api_key=os.environ.get("MODEL_API_KEY", ""),
            base_url=os.environ.get("META_BASE_URL", "https://api.meta.ai/v1"),
            budget_hard_cap_usd=float(os.environ.get("BUDGET_HARD_CAP_USD", "100")),
            run_cap_usd=float(os.environ.get("RUN_CAP_USD", "0.50")),
            paid_calls_enabled=os.environ.get("DEMO_PAID_CALLS_ENABLED", "true").lower() == "true",
            budget_state_path=Path(os.environ.get("BUDGET_STATE_PATH", ROOT / "budget_state.json")),
        )
