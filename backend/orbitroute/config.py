"""Runtime settings, read from the environment (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
# Where the app writes what it learns (model answers, downloaded map areas). Locally that is data/; on a host with a
# read-only image it points to a persistent volume (ORBITROUTE_STATE_DIR).
STATE_DIR = Path(os.environ.get("ORBITROUTE_STATE_DIR", ROOT / "data"))
CACHE_DIR = STATE_DIR / "cache"
AREAS_DIR = STATE_DIR / "areas"
PREWARMED_DIR = ROOT / "data" / "prewarmed"  # committed model answers for the bundled samples, so a fresh deployment pays nothing


def resolve_cached(cache_dir: Path, name: str) -> Path:
    """The cache file to read or write: the live cache first, then the committed pre-warmed copy."""
    live = cache_dir / name
    if live.exists():
        return live
    shipped = PREWARMED_DIR / name
    return shipped if shipped.exists() else live


def _utc(text: str) -> datetime | None:
    """An ISO date-time such as 2026-11-04T12:00:00Z (no zone = UTC); empty means no limit. A typo stops the app at start-up."""
    if not text:
        return None
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


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
    reasoning_provider: str  # "meta", "baseten" or "modal": which endpoint serves the text-reasoning steps first
    baseten_budget_cap_usd: float
    baseten_state_path: Path
    modal_endpoint_url: str = ""  # a Modal shared Endpoint serving Muse Spark Open (OpenAI-compatible)
    modal_endpoint_token: str = ""  # proxy token "wk-...ws-..."
    modal_model: str = "meta-models/Muse-Spark-Open-816B-A42B"
    modal_budget_cap_usd: float = 60.0
    modal_state_path: Path = Path("budget_state_modal.json")
    run_limit_per_ip_hour: int = 20
    run_limit_per_day: int = 300
    max_concurrent_runs: int = 3
    trust_proxy: bool = False
    trusted_proxy_hops: int = 1  # proxies in front of the app; the client is that many entries from the right of X-Forwarded-For
    access_code: str = ""  # when set, only callers sending it (X-Access-Code) get live model calls; everyone else gets the recorded demo
    paid_calls_until: datetime | None = None  # after this moment (UTC) nobody gets live model calls: the recorded demo only

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        return cls(
            api_key=os.environ.get("MODEL_API_KEY", ""),
            base_url=os.environ.get("META_BASE_URL", "https://api.meta.ai/v1"),
            budget_hard_cap_usd=float(os.environ.get("BUDGET_HARD_CAP_USD", "100")),
            run_cap_usd=float(os.environ.get("RUN_CAP_USD", "1.00")),
            paid_calls_enabled=os.environ.get("DEMO_PAID_CALLS_ENABLED", "true").lower() == "true",
            budget_state_path=Path(os.environ.get("BUDGET_STATE_PATH", ROOT / "budget_state.json")),
            baseten_api_key=os.environ.get("BASETEN_API_KEY", ""),
            baseten_base_url=os.environ.get("BASETEN_BASE_URL", "https://inference.baseten.co/v1"),
            baseten_model=os.environ.get("BASETEN_MODEL", "meta-models/muse-spark-open-1026"),
            reasoning_provider=os.environ.get("REASONING_PROVIDER", "meta").lower(),
            # Baseten credits ($100) are a separate pot from the Meta credits; our estimate of their price is conservative
            baseten_budget_cap_usd=float(os.environ.get("BASETEN_BUDGET_CAP_USD", "60")),
            baseten_state_path=Path(os.environ.get("BASETEN_BUDGET_STATE_PATH", ROOT / "budget_state_baseten.json")),
            modal_endpoint_url=os.environ.get("MODAL_ENDPOINT_URL", "").rstrip("/"),
            modal_endpoint_token=os.environ.get("MODAL_ENDPOINT_TOKEN", ""),
            modal_model=os.environ.get("MODAL_MODEL", "meta-models/Muse-Spark-Open-816B-A42B"),
            modal_budget_cap_usd=float(os.environ.get("MODAL_BUDGET_CAP_USD", "60")),
            modal_state_path=Path(os.environ.get("MODAL_BUDGET_STATE_PATH", ROOT / "budget_state_modal.json")),
            run_limit_per_ip_hour=int(os.environ.get("RUN_LIMIT_PER_IP_HOUR", "20")),
            run_limit_per_day=int(os.environ.get("RUN_LIMIT_PER_DAY", "300")),
            max_concurrent_runs=int(os.environ.get("MAX_CONCURRENT_RUNS", "3")),
            trust_proxy=os.environ.get("TRUST_PROXY", "").lower() in ("1", "true"),
            trusted_proxy_hops=max(int(os.environ.get("TRUSTED_PROXY_HOPS", "1")), 1),
            access_code=os.environ.get("ACCESS_CODE", "").strip(),
            paid_calls_until=_utc(os.environ.get("PAID_CALLS_UNTIL", "").strip()),
        )
