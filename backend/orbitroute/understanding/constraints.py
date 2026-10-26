"""Formal routing problem: what the model extracts from a request, and the defaults we add."""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ZoneKind = Literal["industrial", "commercial", "residential", "park_forest"]

DEFAULT_SHIFT_START = "08:00"
DEFAULT_DEADLINE = "18:00"
DEFAULT_SERVICE_MIN = 4.0
CAPACITY_SLACK = 1.5  # default capacity = ceil(orders / trucks * slack)

# JSON schema sent to the model (non-strict, so nullable types are fine).
PARSED_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "n_orders": {"type": "integer", "description": "number of deliveries / orders / stops"},
        "n_vehicles": {"type": "integer", "description": "number of trucks / vehicles"},
        "vehicle_capacity": {"type": ["integer", "null"], "description": "max orders (units) per truck, null if not stated"},
        "shift_start": {"type": ["string", "null"], "description": "24h HH:MM when trucks leave, null if not stated"},
        "deadline": {"type": ["string", "null"], "description": "24h HH:MM by which all work must be done, null if not stated"},
        "service_minutes": {"type": ["number", "null"], "description": "minutes spent at each stop, null if not stated"},
        "avoid_zone_kinds": {
            "type": "array",
            "items": {"type": "string", "enum": ["industrial", "commercial", "residential", "park_forest"]},
            "description": "land-use zones the trucks must not drive through",
        },
        "objective": {"type": "string", "enum": ["min_time", "min_distance"]},
        "notes": {"type": "array", "items": {"type": "string"}, "description": "ambiguities in the request"},
    },
    "required": ["n_orders", "n_vehicles", "vehicle_capacity", "shift_start", "deadline", "service_minutes", "avoid_zone_kinds", "objective", "notes"],
}

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def hhmm_to_seconds(value: str) -> int:
    m = _HHMM.match(value.strip())
    if not m:
        raise ValueError(f"expected HH:MM (24h), got {value!r}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60


def seconds_to_hhmm(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"


class ParsedRequest(BaseModel):
    """What the language model returns. Fields it could not find in the text are None."""

    n_orders: int = Field(ge=1, le=300)
    n_vehicles: int = Field(ge=1, le=30)
    vehicle_capacity: int | None = Field(default=None, ge=1)
    shift_start: str | None = None
    deadline: str | None = None
    service_minutes: float | None = Field(default=None, ge=0, le=120)
    avoid_zone_kinds: list[ZoneKind] = []
    objective: Literal["min_time", "min_distance"] = "min_time"
    notes: list[str] = []

    @field_validator("shift_start", "deadline")
    @classmethod
    def _valid_time(cls, v: str | None) -> str | None:
        if v is not None:
            hhmm_to_seconds(v)
        return v


class Problem(BaseModel):
    """The fully specified CVRP-with-time-windows problem. Every default is listed in `assumptions`."""

    n_orders: int
    n_vehicles: int
    capacity: int
    shift_start_s: int
    deadline_s: int
    service_s: int
    avoid_zone_kinds: list[ZoneKind]
    objective: Literal["min_time", "min_distance"]
    assumptions: list[str]
    notes: list[str] = []


def resolve(parsed: ParsedRequest) -> Problem:
    assumptions: list[str] = []

    shift = parsed.shift_start
    if shift is None:
        shift = DEFAULT_SHIFT_START
        assumptions.append(f"Trucks leave the depot at {shift} (not stated).")
    deadline = parsed.deadline
    if deadline is None:
        deadline = DEFAULT_DEADLINE
        assumptions.append(f"Everything must be finished by {deadline} (not stated).")
    shift_s, deadline_s = hhmm_to_seconds(shift), hhmm_to_seconds(deadline)
    if deadline_s <= shift_s:
        raise ValueError(f"deadline {deadline} is not after the start {shift}")

    service_min = parsed.service_minutes
    if service_min is None:
        service_min = DEFAULT_SERVICE_MIN
        assumptions.append(f"Each stop takes {service_min:g} minutes (not stated).")

    capacity = parsed.vehicle_capacity
    if capacity is None:
        capacity = math.ceil(parsed.n_orders / parsed.n_vehicles * CAPACITY_SLACK)
        assumptions.append(f"Each order is 1 unit; a truck carries {capacity} units (not stated).")
    if capacity * parsed.n_vehicles < parsed.n_orders:
        assumptions.append(
            f"Total capacity ({capacity * parsed.n_vehicles}) is below the number of orders ({parsed.n_orders}): infeasible as stated."
        )

    return Problem(
        n_orders=parsed.n_orders,
        n_vehicles=parsed.n_vehicles,
        capacity=capacity,
        shift_start_s=shift_s,
        deadline_s=deadline_s,
        service_s=int(round(service_min * 60)),
        avoid_zone_kinds=list(dict.fromkeys(parsed.avoid_zone_kinds)),
        objective=parsed.objective,
        assumptions=assumptions,
        notes=parsed.notes,
    )
