"""The media of a session, whole, whatever the number of recordings it spans.

The encoder opens a new recording at each (re)launch: after a crash, and after a signal loss (the reconnection screen
is not recorded, the programme resumes in a new file). A session that was on air across such a boundary therefore
spans recordings `recording` .. `end_recording` (see `state.SessionRec`): the first one from `start_pos`, the ones in
between whole, the last one up to `end_file_pos`.

Everything downstream (transcription, verses, clips, the back office's khutba, its clips and replays) reads ONE
recording and two positions. So a session on several recordings is assembled once into one file: the whole files,
concatenated without re-encoding (the live one and the clean one the same way, so they stay aligned), and the
positions become `start_pos` and `end` in that file. The gap (the reconnection screen) is not in any file, hence not in
the assembled one: the times of the transcript are those of what was recorded, one after the other.

`session_media` is cheap and pure when nothing needs assembling (one recording, or a run recorded before this
existed); the pipeline builds the assembled files, the back office only reads what the pipeline left (`build=False`).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import runs
from .i18n import _

log = logging.getLogger("sada")

SIDECAR = "media.json"  # what the assembly left in the session's output folder
LIVE_ALL = "recording_all.mkv"
CLEAN_ALL = "recording_all_clean.mkv"


@dataclass(frozen=True)
class Media:
    live: str | None
    clean: str | None
    start: float | None
    end: float | None  # None: to the end of the file


def indexes(data: dict, s: dict) -> list[int]:
    """Numbers of the recordings the session spans, in order (one for a run recorded before the range existed)."""
    recs = data.get("recordings") or []
    first = s.get("recording")
    if first is None:
        first = len(recs) - 1
    last = s.get("end_recording")
    if last is None or not 0 <= first <= last < len(recs):
        return [first] if 0 <= first < len(recs) else []
    return list(range(first, last + 1))


def _legacy(data: dict, s: dict) -> Media:
    live, clean = runs.sources(data, s)
    return Media(live, clean, s.get("start_pos"), s.get("end_pos"))


def _duration(path: str) -> float | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        ).stdout.strip()
        value = float(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return value if value > 0 else None


def _concat(paths: list[str], dest: Path) -> bool:
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    listing = dest.with_suffix(".txt")
    listing.write_text("".join("file '{}'\n".format(p.replace("'", "'\\''")) for p in paths), encoding="utf-8")
    tmp = dest.with_name(dest.stem + ".tmp.mkv")
    try:
        subprocess.run(
            [exe, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(tmp)],
            check=True,
            capture_output=True,
            timeout=3600,
        )
        os.replace(tmp, dest)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        listing.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)


def _usable(path: str | None) -> bool:
    return bool(path) and Path(path).exists() and Path(path).stat().st_size > 0


def session_media(data: dict, s: dict, outdir: Path, build: bool = False) -> Media:
    """Recording(s) of the session as ONE live file, one clean file (or None) and the positions in them.

    `outdir`: the session's output folder, where the assembled files and the sidecar are kept. `build`: assemble now
    if it was not done (pipeline); otherwise (back office) the answer is the assembled files if they exist, else the
    first recording as before."""
    nums = indexes(data, s)
    if len(nums) <= 1:
        return _legacy(data, s)
    side = outdir / SIDECAR
    if side.exists():
        try:
            m = json.loads(side.read_text(encoding="utf-8"))
            if _usable(m.get("live")):
                return Media(m["live"], m.get("clean") if _usable(m.get("clean")) else None, m["start"], m["end"])
        except (OSError, ValueError, KeyError):
            pass
    if not build:
        return _legacy(data, s)
    built = _assemble(data, s, nums, Path(outdir))
    return built or _legacy(data, s)


def _assemble(data: dict, s: dict, nums: list[int], outdir: Path) -> Media | None:
    recs, cleans = data.get("recordings") or [], data.get("recordings_clean") or []
    lives = [recs[i] for i in nums]
    if not all(_usable(p) for p in lives):
        log.warning(
            _("session {index}: a recording of its range is missing, only the first one is used", index=s.get("index"))
        )
        return None
    before = [_duration(p) for p in lives[:-1]]
    if any(d is None for d in before):
        log.warning(
            _("session {index}: duration of a recording unknown, only the first one is used", index=s.get("index"))
        )
        return None
    outdir.mkdir(parents=True, exist_ok=True)
    live_all = outdir / LIVE_ALL
    if not _concat(lives, live_all):
        log.warning(
            _("session {index}: the recordings could not be joined, only the first one is used", index=s.get("index"))
        )
        return None
    clean_all = None
    if len(cleans) == len(recs):
        parts = [cleans[i] for i in nums]
        if all(_usable(p) for p in parts) and _concat(parts, outdir / CLEAN_ALL):
            clean_all = str(outdir / CLEAN_ALL)
    last = s.get("end_file_pos")
    end = None if last is None else round(sum(before) + float(last), 3)
    media = Media(str(live_all), clean_all, s.get("start_pos"), end)
    (outdir / SIDECAR).write_text(
        json.dumps({"live": media.live, "clean": media.clean, "start": media.start, "end": media.end}, indent=1),
        encoding="utf-8",
    )
    log.info(_("session {index}: {count} recordings joined", index=s.get("index"), count=len(nums)))
    return media
