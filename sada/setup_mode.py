"""Setup mode of the orchestrator: the programme the destinations *would* get, seen before any live.

An operator setting up the screens (scenes, QR code, banner, logo) wants to see the real composition, with the
mosque's templates and texts, not an approximation drawn on the client. In setup the orchestrator therefore
composes the programme as usual (same renderer, same templates, same overlays) but into a **rehearsal stage**:
its own state machine and its own encoder, whose only output is the monitoring copy (`preview_url`). There is
no destination, no recording, no camera: nothing a setup does can reach the public.

The mode is a **lease**: the caller renews it every few seconds; when it lapses (application closed, network
lost) the rehearsal stops by itself, and the orchestrator is free to be put back to sleep by the platform. A
live that starts while the lease is held (schedule, OBS, Studio) takes over: the rehearsal stage steps aside,
commands go to the real machine again, and the monitoring copy becomes the real programme.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: Lease length when the caller does not ask for one, and the longest it may ask for (seconds).
TTL_DEFAULT_S = 90.0
TTL_MAX_S = 300.0
#: Scene shown when a setup opens: what the audience sees first.
FIRST_SCENE = "avant"


class SetupInactive(ValueError):
    """A command sent from the setup view reached an orchestrator whose setup lease has lapsed."""


def clamp_ttl(value: Any) -> float:
    """A lease length from untrusted input: default when unusable, bounded to 5..TTL_MAX_S."""
    try:
        ttl = float(value)
    except (TypeError, ValueError):
        return TTL_DEFAULT_S
    if ttl != ttl:  # NaN
        return TTL_DEFAULT_S
    return min(max(ttl, 5.0), TTL_MAX_S)


class SetupLease:
    """A lease on the setup mode. Pure bookkeeping: the clock is injected so tests need no sleep."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._until = 0.0

    def open(self, ttl: float) -> bool:
        """Takes or renews the lease. True when it was not held (a new setup session starts)."""
        fresh = not self.active()
        self._until = self._clock() + ttl
        return fresh

    def close(self) -> bool:
        """Releases the lease. True when it was held."""
        held = self.active()
        self._until = 0.0
        return held

    def active(self) -> bool:
        return self._clock() < self._until

    def remaining(self) -> float:
        return max(0.0, self._until - self._clock())


@dataclass
class Stage:
    """What drives one output: a state machine and the encoder it is aligned on, with the keys of the last
    picture and overlay written (so an unchanged one is not rewritten). The live stage and the rehearsal stage
    are two of these; the orchestrator never mixes their fields."""

    machine: Any
    encoder: Any
    shown_key: Any = None
    overlay_key: Any = None
    rehearsal: bool = field(default=False)
