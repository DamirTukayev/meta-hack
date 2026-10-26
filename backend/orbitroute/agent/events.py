"""Structured events the agent emits; the UI and the demo log are rendered from them."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Event:
    type: str  # start | matrix | solve | verify | decision | repair | relaxation | final
    message: str
    data: dict = field(default_factory=dict)
    t: float = field(default_factory=time.time)


Emit = Callable[[Event], None]


def silent(_: Event) -> None:
    pass
