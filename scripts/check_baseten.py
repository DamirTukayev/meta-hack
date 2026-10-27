"""Smoke-test the open-weight endpoint (Muse Spark Open on Baseten): a plain call, then a schema-constrained call.

Usage: uv run python scripts/check_baseten.py     (needs BASETEN_API_KEY in .env)
"""

from __future__ import annotations

import json

from orbitroute.config import Settings
from orbitroute.llm.client import MetaClient, guard_for


def main() -> None:
    s = Settings.load()
    guard = guard_for(s, "baseten")
    client = MetaClient(s, guard, provider="baseten")
    print("model:", client.default_model)

    r = client.chat([{"role": "user", "content": "Reply with the single word: ok"}], max_completion_tokens=400, label="baseten_check")
    print(f"plain call -> {r.text!r} | tokens in {r.input_tokens}, out {r.output_tokens} (reasoning {r.reasoning_tokens}) | est. ${r.cost_usd:.5f}")
    msg = r.raw["choices"][0]["message"]
    print("message fields:", sorted(msg))

    schema = {"type": "object", "properties": {"n_orders": {"type": "integer"}, "deadline": {"type": ["string", "null"]}}, "required": ["n_orders", "deadline"]}
    try:
        data, r2 = client.chat_json([{"role": "user", "content": "Extract: 12 orders by 17:30"}], "Probe", schema, max_completion_tokens=800, label="baseten_check")
        print("schema call ->", json.dumps(data), f"| tokens out {r2.output_tokens}")
    except Exception as exc:  # report, do not hide: this tells us whether json_schema is supported
        print("schema call FAILED:", type(exc).__name__, str(exc)[:300])


if __name__ == "__main__":
    main()
