"""Natural-language request -> Problem, via Muse Spark with schema-constrained output."""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import ValidationError

from orbitroute import prompts
from orbitroute.config import CACHE_DIR, resolve_cached
from orbitroute.llm.budget import RunBudget
from orbitroute.llm.client import MetaClient
from orbitroute.understanding.constraints import PARSED_REQUEST_SCHEMA, ParsedRequest, Problem, resolve

MAX_ATTEMPTS = 2


def parse_request_raw(
    client: MetaClient,
    text: str,
    *,
    run: RunBudget | None = None,
    max_completion_tokens: int = 2500,
    prompt_version: str | None = None,
) -> ParsedRequest:
    """What the model understood, validated; asks again when the answer is empty or invalid."""
    _, system = prompts.load("request", prompt_version)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    last_error = ""
    for _ in range(MAX_ATTEMPTS):
        try:
            raw, _ = client.chat_json(
                messages,
                "DeliveryRequest",
                PARSED_REQUEST_SCHEMA,
                max_completion_tokens=max_completion_tokens,
                reasoning_effort="low",
                run=run,
                label="parse_request",
            )
        except json.JSONDecodeError as exc:  # an empty or truncated answer (seen from open-weight models): just ask again
            last_error = f"the answer was not valid JSON ({exc.msg})"
            continue
        try:
            return _validated(raw)
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)
            messages = messages + [
                {"role": "assistant", "content": str(raw)},
                {"role": "user", "content": f"That output is invalid: {last_error}. Return corrected JSON."},
            ]
    raise ValueError(f"could not parse the request: {last_error}")


def _validated(raw: dict) -> ParsedRequest:
    parsed = ParsedRequest.model_validate(raw)
    resolve(parsed)  # raises ValueError for an impossible deadline, so the model is asked again
    return parsed


def parse_request(client: MetaClient, text: str, **kw) -> Problem:
    return resolve(parse_request_raw(client, text, **kw))


def _sentence_key(sentence: str) -> str:
    return re.sub(r"\s+", " ", sentence.strip().lower())


def _cache_file(sentence: str, version: str):
    digest = hashlib.sha256(f"{version}|{_sentence_key(sentence)}".encode()).hexdigest()[:16]
    return resolve_cached(CACHE_DIR, f"request_{digest}.json")


def request_cache_name(sentence: str, prompt_version: str | None = None) -> str:
    version, _ = prompts.load("request", prompt_version)
    return _cache_file(sentence, version).name


def parse_request_cached(
    client: MetaClient,
    sentence: str,
    full_text: str,
    *,
    n_orders: int | None = None,
    n_vehicles: int | None = None,
    run: RunBudget | None = None,
    prompt_version: str | None = None,
) -> Problem:
    """parse_request for the sentence the user wrote (the time and what to avoid), remembering the answer on disk.

    `full_text` is what the model sees on a miss (the sentence with the order and truck counts in front). The counts come
    from the fields of the interface, so a remembered answer is reused with the counts of this run: a bundled sample with one
    of its example sentences then runs without any model call, whatever the counts are. A count the sentence itself stated
    differs from the one in front of it and is kept as the model read it.
    """
    version, _ = prompts.load("request", prompt_version)
    path = _cache_file(sentence, version)
    if path.exists():
        entry = json.loads(path.read_text())
        parsed = ParsedRequest.model_validate(entry["parsed"])
        head = entry.get("head", {})
    else:
        parsed = parse_request_raw(client, full_text, run=run, prompt_version=prompt_version)
        head = {"n_orders": n_orders, "n_vehicles": n_vehicles}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / path.name).write_text(json.dumps({"sentence": sentence, "parsed": parsed.model_dump(), "head": head}))
    updates = {}
    if n_orders is not None and (head.get("n_orders") is None or parsed.n_orders == head["n_orders"]):
        updates["n_orders"] = n_orders
    if n_vehicles is not None and (head.get("n_vehicles") is None or parsed.n_vehicles == head["n_vehicles"]):
        updates["n_vehicles"] = n_vehicles
    return resolve(parsed.model_copy(update=updates))
