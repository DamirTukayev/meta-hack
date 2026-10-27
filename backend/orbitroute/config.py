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
    baseten_api_key: str
    baseten_base_url: str
    baseten_model: str
    reasoning_provider: str  # "meta" or "baseten": which endpoint serves the text-reasoning steps
    baseten_budget_cap_usd: float
    baseten_state_path: Path

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
            baseten_api_key=os.environ.get("BASETEN_API_KEY", ""),
            baseten_base_url=os.environ.get("BASETEN_BASE_URL", "https://inference.baseten.co/v1"),
            baseten_model=os.environ.get("BASETEN_MODEL", "meta-models/muse-spark-open-1026"),
            reasoning_provider=os.environ.get("REASONING_PROVIDER", "meta").lower(),
            # Baseten credits ($100) are a separate pot from the Meta credits; our estimate of their price is conservative
            baseten_budget_cap_usd=float(os.environ.get("BASETEN_BUDGET_CAP_USD", "60")),
            baseten_state_path=Path(os.environ.get("BASETEN_BUDGET_STATE_PATH", ROOT / "budget_state_baseten.json")),
        )
