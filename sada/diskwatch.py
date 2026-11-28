"""Free space of the recording folder: the broadcast comes before the recording.

A night of hours at the configured bit rate takes gigabytes, every night of a month. A full disk must never cut a live:
the recording output of the encoder is allowed to fail on its own (`onfail=ignore`, see `Encoder._tee_targets`), and
this probe warns the mosque early, then stops new recordings from being opened when too little is left. Nothing is
ever deleted here: freeing space is the mosque's decision.

Two thresholds, estimated from the bit rate (`bytes_per_second`):

* `low`: less than two nights of 3 hours: an alert goes to the mosque (the notifier, once per episode);
* `critical`: less than one hour of recording: the encoder opens no new recording (the live goes on without one).
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path

from .i18n import _

NIGHT_S = 3 * 3600.0  # a long tarawih night
LOW_NIGHTS = 2  # alert below this many nights of recording
CRITICAL_S = 3600.0  # no new recording below this much recording time
HYSTERESIS = 1.1  # an episode ends once free space is this much above the low threshold
EVERY_S = 30.0
GB = 1e9
AUDIO_KBPS = 128

OK, LOW, CRITICAL = "ok", "low", "critical"


def kbps(video_bitrate: str) -> float:
    digits = "".join(ch for ch in str(video_bitrate) if ch.isdigit())
    value = float(digits) if digits else 2500.0
    return value * 1000 if str(video_bitrate).strip().lower().endswith("m") else value


def bytes_per_second(cfg) -> float:
    """Disk written per second of live: the programme recording, plus the clean copy when it is kept (a tarawih night
    has none, but the estimate stays on the safe side)."""
    rate = (kbps(getattr(cfg, "video_bitrate", "2500k")) + AUDIO_KBPS) * 1000 / 8
    return rate * (2 if getattr(cfg, "record_clean", True) else 1)


def thresholds(cfg) -> tuple[float, float]:
    """(low, critical) in bytes."""
    rate = bytes_per_second(cfg)
    return rate * NIGHT_S * LOW_NIGHTS, rate * CRITICAL_S


def _existing(path: str | Path) -> Path:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


class DiskWatch:
    """Looks at the free space of the recording folder every `EVERY_S`, and speaks once per episode."""

    def __init__(
        self,
        cfg,
        notify: Callable[[str], object] = lambda _t: None,
        log: Callable[[str], None] = print,
        usage: Callable[[str], object] = shutil.disk_usage,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.cfg, self.notify, self.log, self.usage, self.clock = cfg, notify, log, usage, clock
        self.level = OK
        self.free: int | None = None
        self._next = 0.0

    @property
    def critical(self) -> bool:
        return self.level == CRITICAL

    def poll(self, force: bool = False) -> str:
        """One look (throttled). Returns the level."""
        now = self.clock()
        if not force and now < self._next:
            return self.level
        self._next = now + EVERY_S
        try:
            free = int(self.usage(str(_existing(self.cfg.record_dir))).free)
        except Exception:  # noqa: BLE001 — no answer: nothing is claimed, nothing is blocked
            return self.level
        self.free = free
        low, critical = thresholds(self.cfg)
        if free < critical:
            level = CRITICAL
        elif free < low or (self.level != OK and free < low * HYSTERESIS):
            level = LOW  # an episode lasts until the space is clearly back
        else:
            level = OK
        before, self.level = self.level, level
        if level != before:
            self._speak(before, level, free, low)
        return level

    def _speak(self, before: str, level: str, free: int, low: float) -> None:
        nights = free / max(bytes_per_second(self.cfg) * NIGHT_S, 1.0)
        if level == CRITICAL:
            text = _(
                "Disk space critical on the recording folder: {free:.1f} GB left. New recordings are suspended; "
                "the live stream goes on without a local recording. Free some space.",
                free=free / GB,
            )
        elif level == LOW and before == OK:
            text = _(
                "Disk space is running low on the recording folder: {free:.1f} GB left, about {nights:.1f} night(s) "
                "of 3 hours. Free some space; the live stream is not affected.",
                free=free / GB,
                nights=nights,
            )
        else:
            self.log(_("Disk space back to normal: {free:.1f} GB free", free=free / GB))
            return  # recovery (or critical -> low): logged, not announced again
        self.log(text)
        try:
            self.notify(text)
        except Exception:  # noqa: BLE001 — an alert that cannot be sent never touches the live
            pass

    def status(self) -> dict:
        low, critical = thresholds(self.cfg)
        return {
            "level": self.level,
            "free_gb": round(self.free / GB, 1) if self.free is not None else None,
            "low_gb": round(low / GB, 1),
            "critical_gb": round(critical / GB, 1),
        }
