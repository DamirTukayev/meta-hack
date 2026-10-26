"""Natural-language request -> Problem, via Muse Spark with schema-constrained output."""

from __future__ import annotations

from pydantic import ValidationError

from orbitroute import prompts
from orbitroute.llm.budget import RunBudget
from orbitroute.llm.client import MetaClient
from orbitroute.understanding.constraints import PARSED_REQUEST_SCHEMA, ParsedRequest, Problem, resolve

MAX_ATTEMPTS = 2


def parse_request(
    client: MetaClient,
    text: str,
    *,
    run: RunBudget | None = None,
    max_completion_tokens: int = 2500,
) -> Problem:
    _, system = prompts.load("request")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    last_error = ""
    for _ in range(MAX_ATTEMPTS):
        raw, _ = client.chat_json(
            messages,
            "DeliveryRequest",
            PARSED_REQUEST_SCHEMA,
            max_completion_tokens=max_completion_tokens,
            reasoning_effort="low",
            run=run,
            label="parse_request",
        )
        try:
            return resolve(ParsedRequest.model_validate(raw))
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)
            messages = messages + [
                {"role": "assistant", "content": str(raw)},
                {"role": "user", "content": f"That output is invalid: {last_error}. Return corrected JSON."},
            ]
    raise ValueError(f"could not parse the request: {last_error}")
