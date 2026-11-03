"""Request parsing in six languages on 40 requests per language instead of 10.

The ten requests of `eval/PARSING_LANGUAGES.md` are kept and thirty more are added. The thirty are written in English by the author with the
constraints each one must give (fields not stated must stay empty); Muse Spark 1.3 translates them into Russian, Spanish, French, German and
Portuguese in everyday phrasing, and a translation that drops the order count or the truck count (as digits) is thrown out and counted. Then every
model that is set up parses all of them. The translations are saved in eval/parse_languages_more.json so that a rerun is free and a reader can judge them.
Caveat printed in the report: the translator is a Muse Spark model too, so a systematic habit of the family could make its translations easier for it.
Writes eval/PARSING_LANGUAGES_MORE.md. Usage: uv run python scripts/eval_parse_languages_more.py
"""

from __future__ import annotations

import json
import re

import orbitroute.api as api
import orbitroute.eval.runner as runner
from orbitroute.config import ROOT
from orbitroute.eval.parse_languages import EXPECTED, TEXTS
from orbitroute.llm.client import MetaClient, guard_for

LANGS = ["Russian", "Spanish", "French", "German", "Portuguese"]
NEW: list[tuple[str, dict]] = [
    ("25 orders, 3 trucks, be done by 16:30, stay out of the residential area", dict(n_orders=25, n_vehicles=3, deadline="16:30", avoid={"residential"})),
    ("8 drops with 2 vans, finish before 10:00", dict(n_orders=8, n_vehicles=2, deadline="10:00")),
    ("35 orders, 4 trucks, avoid the industrial zone, by 20:00", dict(n_orders=35, n_vehicles=4, deadline="20:00", avoid={"industrial"})),
    ("flood response: 22 deliveries, 3 trucks, keep out of flooded areas, deadline 14:00", dict(n_orders=22, n_vehicles=3, deadline="14:00", avoid={"flooded"})),
    ("14 orders, 2 trucks, 6 minutes per stop, by 13:00", dict(n_orders=14, n_vehicles=2, service_minutes=6, deadline="13:00")),
    ("45 orders, 5 trucks, start at 06:30, finish by 15:00", dict(n_orders=45, n_vehicles=5, shift_start="06:30", deadline="15:00")),
    ("12 orders, 1 truck, avoid the parks, back by 12:30", dict(n_orders=12, n_vehicles=1, deadline="12:30", avoid={"park_forest"})),
    ("60 orders, 6 trucks, no deadline", dict(n_orders=60, n_vehicles=6)),
    ("16 deliveries, 2 trucks, avoid commercial areas, before 19:00", dict(n_orders=16, n_vehicles=2, deadline="19:00", avoid={"commercial"})),
    ("9 orders, 3 trucks, 3 minutes per stop, start at 9:00, end by 11:30", dict(n_orders=9, n_vehicles=3, service_minutes=3, shift_start="09:00", deadline="11:30")),
    ("32 orders, 4 trucks, avoid the industrial and residential zones, by 17:00", dict(n_orders=32, n_vehicles=4, deadline="17:00", avoid={"industrial", "residential"})),
    ("26 orders, 3 trucks, deadline 4 pm, do not enter the flooded streets", dict(n_orders=26, n_vehicles=3, deadline="16:00", avoid={"flooded"})),
    ("11 orders, 2 trucks, leave at 8, done by 1 pm", dict(n_orders=11, n_vehicles=2, shift_start="08:00", deadline="13:00")),
    ("18 orders, 2 trucks, avoid parks and forest, by 12:00", dict(n_orders=18, n_vehicles=2, deadline="12:00", avoid={"park_forest"})),
    ("40 orders, 8 trucks, 5 minutes per stop, deadline 18:30", dict(n_orders=40, n_vehicles=8, service_minutes=5, deadline="18:30")),
    ("7 orders, 1 van, before 10:15", dict(n_orders=7, n_vehicles=1, deadline="10:15")),
    ("24 orders, 3 trucks, avoid the commercial zone, until 15:45", dict(n_orders=24, n_vehicles=3, deadline="15:45", avoid={"commercial"})),
    ("55 orders, 5 trucks, avoid residential areas, by 21:00", dict(n_orders=55, n_vehicles=5, deadline="21:00", avoid={"residential"})),
    ("13 orders, 2 trucks, start at 7:15, deadline 11:45", dict(n_orders=13, n_vehicles=2, shift_start="07:15", deadline="11:45")),
    ("38 orders, 4 trucks, avoid flooded areas and the industrial zone, by 16:00", dict(n_orders=38, n_vehicles=4, deadline="16:00", avoid={"flooded", "industrial"})),
    ("5 orders, 1 truck, 10 minutes per stop, by 9:30", dict(n_orders=5, n_vehicles=1, service_minutes=10, deadline="09:30")),
    ("30 orders, 3 trucks, avoid the industrial zone, no later than 5:30 pm", dict(n_orders=30, n_vehicles=3, deadline="17:30", avoid={"industrial"})),
    ("21 orders, 3 trucks, start at 06:00, back at 12:00, avoid parks", dict(n_orders=21, n_vehicles=3, shift_start="06:00", deadline="12:00", avoid={"park_forest"})),
    ("48 orders, 6 trucks, by 19:45", dict(n_orders=48, n_vehicles=6, deadline="19:45")),
    ("17 orders, 2 trucks, avoid commercial and residential areas, by 14:30", dict(n_orders=17, n_vehicles=2, deadline="14:30", avoid={"commercial", "residential"})),
    ("29 orders, 4 trucks, 4 minutes per stop, avoid the industrial zone, by 13:15", dict(n_orders=29, n_vehicles=4, service_minutes=4, deadline="13:15", avoid={"industrial"})),
    ("20 orders, 5 trucks, begin at 10:00, finish by 16:00", dict(n_orders=20, n_vehicles=5, shift_start="10:00", deadline="16:00")),
    ("33 orders, 3 trucks, hurricane relief, avoid flooded streets, by 12:45", dict(n_orders=33, n_vehicles=3, deadline="12:45", avoid={"flooded"})),
    ("15 orders, 3 trucks, avoid the parks, by 11:30, 2 minutes per stop", dict(n_orders=15, n_vehicles=3, service_minutes=2, deadline="11:30", avoid={"park_forest"})),
    ("42 orders, 7 trucks, avoid industrial and commercial zones, by 18:15", dict(n_orders=42, n_vehicles=7, deadline="18:15", avoid={"industrial", "commercial"})),
]
SAVED = ROOT / "eval" / "parse_languages_more.json"


def translate(client, language: str) -> list[str]:
    english = [t for t, _ in NEW]
    prompt = (
        f"Translate each of these {len(english)} short delivery requests into {language}, the way a dispatcher would write them in a message: everyday phrasing, "
        "keep every number, every time and the meaning of every constraint (how many orders, how many vehicles, deadline, start time, minutes per stop, what to avoid). "
        "Answer as JSON {\"translations\": [...]} with exactly one string per request, in the same order.\n\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(english))
    )
    schema = {"type": "object", "properties": {"translations": {"type": "array", "items": {"type": "string"}}}, "required": ["translations"]}
    for attempt in range(3):
        answer, _ = client.chat_json([{"role": "user", "content": prompt}], "Translations", schema, max_completion_tokens=6000, reasoning_effort="low", run=None, label="translate-eval")
        if len(answer["translations"]) == len(english):
            return answer["translations"]
    raise RuntimeError(f"{language}: translator did not return {len(english)} lines")


def main() -> None:
    s = api.settings
    meta = api.get_client()
    saved = json.loads(SAVED.read_text()) if SAVED.exists() else {}
    for language in LANGS:
        if language not in saved:
            saved[language] = translate(meta, language)
            SAVED.write_text(json.dumps(saved, ensure_ascii=False, indent=1))
    SAVED.write_text(json.dumps(saved, ensure_ascii=False, indent=1))
    cases: dict[str, list[tuple[str, dict]]] = {"English": list(zip(TEXTS["English"], EXPECTED)) + NEW}
    dropped: dict[str, int] = {}
    for language in LANGS:
        kept = list(zip(TEXTS[language], EXPECTED))
        dropped[language] = 0
        for (en, expected), tr in zip(NEW, saved[language]):
            if str(expected["n_orders"]) in re.findall(r"\d+", tr) and str(expected["n_vehicles"]) in re.findall(r"\d+", tr) or (str(expected["n_orders"]) in re.findall(r"\d+", tr) and expected["n_vehicles"] == 1):
                kept.append((tr, expected))
            else:
                dropped[language] += 1
        cases[language] = kept
    clients = {"Muse Spark 1.3 (Meta API)": (meta, api.guard)}
    for p, label in (("baseten", "Muse Spark Open (Baseten)"), ("modal", "Muse Spark Open (Modal)")):
        if p in api.text_provider_order():
            g = guard_for(s, p)
            clients[label] = (MetaClient(s, g, provider=p), g)
    rows, misses, spent = {}, [], 0.0
    for label, (client, guard) in clients.items():
        for language, cs in cases.items():
            runner.CASES = cs
            res = runner.run_parse_eval(client, guard, log=lambda *_: None)
            rows[(label, language)] = res
            spent += res["cost_usd"]
            misses += [f"- {label}, {language}: `{f['text']}` — {f['wrong']}" for f in res.get("failures", [])]
            print(label, language, res["exact_match_cases"], "/", res["cases"], flush=True)
    lines = [
        "# Request parsing in six languages, 40 requests each", "",
        "Generated by `scripts/eval_parse_languages_more.py`: the ten requests of `eval/PARSING_LANGUAGES.md` plus thirty more written in English by the author, each with the constraints it must give "
        "(a field not stated must stay empty). Muse Spark 1.3 translated the thirty into Russian, Spanish, French, German and Portuguese (`eval/parse_languages_more.json`); "
        "a translation without the order count or the truck count as digits would have been dropped (dropped: " + ", ".join(f"{k} {v}" for k, v in dropped.items()) + "). "
        "An exact match means every field was read as expected.", "",
        "| Model | " + " | ".join(cases) + " |", "|---|" + "---|" * len(cases),
    ]
    for label in clients:
        lines.append(f"| {label} | " + " | ".join(f"{rows[(label, lang)]['exact_match_cases']}/{rows[(label, lang)]['cases']}" for lang in cases) + " |")
    lines += ["", *(["Misses:", "", *misses] if misses else ["No misses."]), "",
              f"Cost of this run: about ${spent:.2f} by the local counter. Limits: requests written by the project author; the translator is a Muse Spark model too, so a habit of the family could make its translations easier for it to read; "
              "one expected reading per request (for example a time of day given as 4 pm must come out as 16:00)."]
    (ROOT / "eval" / "PARSING_LANGUAGES_MORE.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
