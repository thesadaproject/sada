"""Orchestrator: schedule + signals + state machine + encoder + API.

python -m sada.orchestrator --sim-start 12:12 --sim-speed 40
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import logging
import signal
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path

from PIL import Image

from . import (
    destinations,
    gabarit_antenne,
    mawaqit,
    notify,
    prayers,
    runs,
    screens,
    setup_mode,
    source,
    stream_quality,
    studio_link,
    telemetry,
    upload,
)
from . import events as events_mod
from .api import make_server
from .clock import SimClock, parse_hhmm
from .config import Config
from .encoder import Encoder, setup_zmq_port
from .faces import FaceGate, FaceMonitor, yunet_detector
from .i18n import _
from .presence import MotionGate, PresenceMonitor
from .scenes import SCENES, Moment, SceneRenderer, render_custom_scene
from .state import CUSTOM_SCENE_PREFIX, STATE_OF_SCENE, Machine, SessionParams, Signals, State
from .vad import VadMonitor

#: Scene key the encoder shows while a Sada Studio composes the picture itself: nothing over its stream.
PASSTHROUGH_SCENE = "studio:passthrough"
MAX_CUSTOM_IMAGES = 24  # custom scene images kept in memory (a mosque holds at most 12, see custom_scenes.MAX_SCENES)

log = logging.getLogger("sada")

# Back office unreachable at start (default times, no programme): the times and the programme are
# fetched again, with a bounded backoff, so the day does not stay on the fallback until tomorrow.
RETRY_DELAY_S = 30.0
RETRY_MAX_S = 300.0


def backoffice_up(url: str) -> bool:  # pragma: no cover (network)
    """True when the back office answers its /health."""
    import urllib.request

    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=3) as r:  # noqa: S310 — configured back office
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def wait_for_backoffice(url: str, limit_s: float, probe=None, sleep=time.sleep, clock=time.monotonic) -> bool:
    """Wait (bounded) until the back office answers its /health, so the day is not opened on fallbacks.

    True when it answers; False after `limit_s` — then the start goes on, and the background retry
    takes over (see Orchestrator._retry_plan).
    """
    if not url or limit_s <= 0:
        return False

    probe = probe or (lambda: backoffice_up(url))
    end, delay, said = clock() + limit_s, 1.0, False
    while True:
        if probe():
            if said:
                log.info(_("Back office ready"))
            return True
        if clock() >= end:
            log.warning(_("Back office still unreachable after {limit:g} s: start on the caches", limit=limit_s))
            return False
        if not said:
            log.info(_("Waiting for the back office (at most {limit:g} s)", limit=limit_s))
            said = True
        sleep(min(delay, max(0.0, end - clock())))
        delay = min(delay * 2, 10.0)


class Orchestrator:
    #: Who composes the rehearsal stage: said by whoever takes the setup lease (see set_setup).
    _setup_compositing = "server"
    #: Scene picked off air from the control room: only the picture shown (Studio, preview), never a live.
    offair_scene: str | None = None

    def __init__(self, cfg: Config):
        self.cfg = cfg
        start = parse_hhmm(cfg.sim_start, dt.date.today()) if cfg.sim_start else None
        self.clock = SimClock(start)
        self.accel = cfg.sim_speed if cfg.sim_start else 1.0
        self.run_id = runs.new_run_id()
        self.run_dir = Path(cfg.state_dir) / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._setup_logging()
        reached = wait_for_backoffice(cfg.backoffice_url, 0.0 if cfg.sim_start else cfg.backoffice_wait_s)
        # (a wait of 0 s answers False without asking: ask once)
        reached = reached or bool(cfg.backoffice_url and not cfg.sim_start and backoffice_up(cfg.backoffice_url))
        self.times = self._load_times()
        day = self.clock.now().date()
        # today's programme: dars and conferences are added to the khutbas, on the same footing
        # programme of the mosque: kept by the back office, the local file only as fallback
        remote_program = events_mod.from_backoffice(cfg.backoffice_url, cfg.api_port, log=log.info)
        self._program_remote = remote_program is not None
        if remote_program is not None:
            self.program = remote_program
        else:
            self.program, ev_err = events_mod.load(cfg.events_file)
            if ev_err:
                log.warning(ev_err)
        self.instances = events_mod.instances_on(self.program, day, self.prayer_times)
        sessions, extras = self.day_plan(day)
        log.info(_("Sessions of the day (mosque clock): {times}", times=[s.strftime("%H:%M") for s in sessions]))
        for i in self.instances:
            log.info(
                _(
                    "Programme: {label} at {time} — {speaker}",
                    label=i.label,
                    time=i.starts.strftime("%H:%M"),
                    speaker=i.speaker or _("speaker to be confirmed"),
                )
            )
        # Live destinations, video input and screen texts come from the back office when an
        # administrator saved some there; the replays bucket too (read again if it is late).
        self._apply_live_config(
            None if cfg.backoffice_url and not cfg.sim_start and not reached else self._read_live_config()
        )
        # Le gabarit importé par la mosquée est ce qui s'affiche : le dessin du moteur ne sert plus
        # que de repli quand aucun fichier n'a été importé, ou quand le navigateur de rendu manque.
        self.gabarit = gabarit_antenne.depuis_backoffice(cfg, cfg.backoffice_url, cfg.api_port, log_fn=log.info)
        self.renderer = SceneRenderer(cfg)
        self.encoder = Encoder(cfg, self.run_dir, log=log.info)
        self.encoder.source_ready = lambda: source.relay_ready(self.cfg.camera_url)
        self.encoder.reload_background = self._template_active()
        self.encoder.prepare(self.renderer.background())
        self.machine = Machine(sessions, cfg, log=log.info, pos_fn=self.encoder.position, extras=extras)
        # The live stage is the machine and the encoder above; the setup (rehearsal) stage exists only while an
        # operator holds the setup lease (see setup_mode.py).
        self.live_stage = setup_mode.Stage(self.machine, self.encoder)
        self.setup = setup_mode.SetupLease()
        self.rehearsal: setup_mode.Stage | None = None
        # A live ordered from the Sada Studio application (manual or scheduled): read from the back office.
        self.studio = studio_link.Follower()
        self.studio_poll = studio_link.Poller(cfg.backoffice_url if not cfg.sim_start else "", cfg.api_port)
        self.notifier = notify.from_config(cfg, log=log.info)
        self._notified_state = None
        if self.notifier.enabled:
            log.info(_("Notifications to the imam: {destination}", destination=self.notifier.destination))
        else:
            log.info(_("Notifications to the imam: no destination configured (messages in the log)"))
        self.vad = VadMonitor(cfg.camera_url, cfg.vad_aggressiveness, cfg.vad_ratio, log=log.info)
        self.presence = None
        if cfg.presence == "motion":
            gate = MotionGate(
                width=cfg.presence_width,
                height=cfg.presence_height,
                roi=tuple(cfg.presence_roi),
                threshold=cfg.presence_threshold,
                pixel_delta=cfg.presence_pixel_delta,
                hold_s=cfg.presence_hold_s,
            )
            self.presence = PresenceMonitor(cfg.camera_url, gate, fps=cfg.presence_fps, log=log.info)
            log.info(
                _(
                    "Presence: motion in zone {zone} (threshold {threshold:.3f})",
                    zone=tuple(cfg.presence_roi),
                    threshold=cfg.presence_threshold,
                )
            )
        self.faces = None
        if cfg.face == "yunet":
            gate = FaceGate(
                detect=yunet_detector(cfg.face_threshold, (cfg.face_width, cfg.face_height)),
                roi=tuple(cfg.face_roi),
                threshold=cfg.face_threshold,
                hold_s=cfg.face_hold_s,
            )
            self.faces = FaceMonitor(
                cfg.camera_url, gate, width=cfg.face_width, height=cfg.face_height, fps=cfg.face_fps, log=log.info
            )
            log.info(
                _(
                    "Face: YuNet, zone {zone}, threshold {threshold:.2f}",
                    zone=tuple(cfg.face_roi),
                    threshold=cfg.face_threshold,
                )
            )
        self.lock = threading.RLock()
        self._setup_gate = threading.Lock()  # one setup lease change at a time (see set_setup)
        self._stream_since: float | None = None  # monotonic time the stream started, None while it is off
        self.telemetry = telemetry.start("sada-orchestrator", cfg.mosque_slug)
        self.telemetry.watch_orchestrator(self.telemetry_snapshot)
        # Images of the custom scenes the engine holds, least recently used first; bounded (see _remember_custom).
        self._custom_scenes: OrderedDict[str, Image.Image] = OrderedDict()
        self.machine.custom_known = self._custom_scenes.__contains__
        self._saved = None
        self._stop = threading.Event()
        self.api = None
        # a day opened on the fallback (back office down) is retried in the background: the live
        # must not wait on the network, but the plan must not stay wrong until tomorrow either.
        self._plan_day = day
        self._rolled = False
        self._stale = bool(cfg.backoffice_url) and (self._times_fallback or not self._program_remote)
        self._retry_delay = RETRY_DELAY_S
        self._retry_at = 0.0
        self._retry_thread: threading.Thread | None = None
        self._fetched: tuple[dict | None, list | None] | None = None
        # Same for the live config (destinations, video input, screen texts, upload bucket, template):
        # read once at start, so a back office that was down leaves the live without any of it.
        self._live_stale = bool(cfg.backoffice_url) and not cfg.sim_start and not reached
        self._live_delay = RETRY_DELAY_S
        self._live_at = 0.0
        self._live_thread: threading.Thread | None = None
        self._live_ready = False
        self._live_fetched: dict | None = None
        if self._live_stale:
            log.warning(
                _(
                    "Back office unreachable at start: live destinations and video input are fetched again every {delay:g} s",
                    delay=RETRY_DELAY_S,
                )
            )
        if self._stale:
            log.warning(
                _(
                    "Back office unreachable at start: the times and the programme are fetched again every {delay:g} s",
                    delay=RETRY_DELAY_S,
                )
            )

    # -------------------------------------------------------------- initialisation
    def _setup_logging(self):
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
        root = logging.getLogger("sada")
        root.setLevel(logging.INFO)
        for h in (
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(self.run_dir / "orchestrator.log", encoding="utf-8"),
        ):
            h.setFormatter(fmt)
            root.addHandler(h)

    @property
    def prayer_times(self) -> dict:
        """Today's times ("after Isha" etc.); empty if the source is silent."""
        return prayers.prayer_times(self.times_data or {})

    def _load_times(self) -> list[str]:
        self.times_data = None
        self._times_fallback = False
        if self.cfg.jumua_times_override:
            log.info(_("Times forced by the config: {times}", times=self.cfg.jumua_times_override))
            return list(self.cfg.jumua_times_override)
        try:
            # the back office keeps each mosque's cache; the local file only if it is unreachable
            d = prayers.from_backoffice(self.cfg.backoffice_url, self.cfg.api_port, log=log.info)
            if d is None:
                d = mawaqit.get_jumua(self.cfg.mawaqit_url, self.cfg.mawaqit_cache)
            self.times_data = d
            log.info(
                _(
                    "Times ({name}): jumua={jumua} — origin: {origin}",
                    name=d.get("name"),
                    jumua=d["jumua_list"],
                    origin=d.get("origin"),
                )
            )
            if d["jumua_list"]:
                return d["jumua_list"]
        except Exception as e:
            log.error(_("Prayer times unavailable and no cache: {error}", error=e))
        self._times_fallback = True
        log.warning(_("Fallback: default times 12:30 / 13:30"))
        return ["12:30", "13:30"]

    def day_plan(self, day: dt.date) -> tuple[list[dt.datetime], list[dict]]:
        """(sessions, events) of a day: the jumua times, then the programme, on the same footing."""
        # the khutbas only on Friday; times forced by hand (--times, simulation) apply to any day
        forced = bool(self.cfg.jumua_times_override or self.cfg.sim_start)
        jumua = [parse_hhmm(t, day) for t in self.times] if forced or day.weekday() == 4 else []
        instances = events_mod.instances_on(self.program, day, self.prayer_times)
        return jumua + [i.starts for i in instances], [{} for _ in jumua] + [i.as_event() for i in instances]

    # --- late live config -----------------------------------------------------
    def _read_live_config(self) -> dict:
        """Destinations, video input, screen texts and upload bucket as the back office has them."""
        cfg = self.cfg
        return {
            "rtmp_urls": destinations.from_backoffice(cfg.backoffice_url, cfg.api_port, log=log.info),
            "camera_url": source.from_backoffice(cfg.backoffice_url, cfg.api_port, log=log.info),
            "screen_texts": screens.from_backoffice(cfg.backoffice_url, cfg.api_port, log=log.info),
            "storage": upload.from_backoffice(cfg.backoffice_url, cfg.api_port, log=log.info),
            "quality": stream_quality.from_backoffice(cfg.backoffice_url, cfg.api_port, log=log.info),
        }

    def _apply_live_config(self, live: dict | None):
        """Applies what the back office saved; an empty value keeps the local setting."""
        live = live or {}
        cfg = self.cfg
        if live.get("rtmp_urls"):
            cfg.rtmp_urls = live["rtmp_urls"]
        if live.get("camera_url"):
            cfg.camera_url = live["camera_url"]
            for monitor in (getattr(self, "vad", None), getattr(self, "presence", None), getattr(self, "faces", None)):
                if monitor is not None:
                    monitor.url = cfg.camera_url  # picked up when the monitor's ffmpeg is launched again
        if live.get("quality"):
            if hasattr(self, "encoder"):
                # the renderer and the encoder were built at the previous size: applied at the next start
                log.warning(_("Broadcast quality reached after the start: applied at the next restart"))
            else:
                for k, v in live["quality"].items():
                    setattr(cfg, k, v)
        if live.get("screen_texts"):
            cfg.screen_texts = live["screen_texts"]
        if hasattr(self, "uploader"):
            if live.get("storage"):
                self.uploader = upload.Uploader(live["storage"], log=log.info)
        else:
            self.uploader = upload.Uploader(live.get("storage"), log=log.info)

    def _retry_live_config(self):
        """Back office down at start: fetch the live config in the background until it answers.

        Backoff is bounded (30 s, doubling up to 5 min); one log line when it fails and one
        when it is reached, not one per attempt. Without a back office (no URL, simulation) it
        never runs: the local setting is the config.
        """
        if not self._live_stale:
            return
        if self._live_ready:
            self._live_ready = False
            self._live_stale = False
            self._apply_live_config(self._live_fetched)
            self.gabarit = self.gabarit or gabarit_antenne.depuis_backoffice(
                self.cfg, self.cfg.backoffice_url, self.cfg.api_port, log_fn=log.info
            )
            if self._template_active():
                self.encoder.reload_background = True  # read by the next ffmpeg launch
            log.info(
                _(
                    "Back office reached: {count} destination(s), video input {input}",
                    count=len(self.cfg.rtmp_urls),
                    input=self.cfg.camera_url.split("://")[0],
                )
            )
            return
        if (self._live_thread and self._live_thread.is_alive()) or time.monotonic() < self._live_at:
            return
        self._live_at = time.monotonic() + self._live_delay
        self._live_delay = min(self._live_delay * 2, RETRY_MAX_S)
        self._live_thread = threading.Thread(target=self._fetch_live_config, name="sada-live-config", daemon=True)
        self._live_thread.start()

    def _fetch_live_config(self):
        if not backoffice_up(self.cfg.backoffice_url):
            return  # still down: already said so at start
        self._live_fetched = self._read_live_config()
        self._live_ready = True

    # --- late back office -----------------------------------------------------
    def _roll_day(self, sig: Signals):
        """Midnight: plan the new day at once with what is known, then fetch its times again.

        The process runs for days: without this, the plan of the day it started on would stay.
        """
        day = sig.now.date()
        if day == self._plan_day:
            return
        self.instances = events_mod.instances_on(self.program, day, self.prayer_times)
        sessions, extras = self.day_plan(day)
        if not self.machine.new_day(sessions, extras, sig):
            return  # a session runs over midnight: retried on the next tick
        self._plan_day = day
        log.info(_("Sessions of the day (mosque clock): {times}", times=[s.strftime("%H:%M") for s in sessions]))
        if self.cfg.backoffice_url and not self.cfg.jumua_times_override:
            # today's prayer times (and programme) from the back office: applied by _retry_plan
            self._stale, self._rolled = True, True
            self._retry_delay, self._retry_at = RETRY_DELAY_S, 0.0

    def _retry_plan(self, sig: Signals):
        """Back office down at start: get the times and the programme again, then replan today.

        The fetch runs in a background thread — the live never waits on the network — and its
        result is applied here, under the loop lock. Backoff is bounded (30 s, then 5 min), and
        only the day that was opened on the fallback is retried.
        """
        if not self._stale or sig.now.date() != self._plan_day:
            return
        if self._fetched is not None:
            times, program = self._fetched
            self._fetched = None
            self._apply_plan(times, program, sig)
            return
        if (self._retry_thread and self._retry_thread.is_alive()) or time.monotonic() < self._retry_at:
            return
        self._retry_at = time.monotonic() + self._retry_delay
        self._retry_delay = min(self._retry_delay * 2, RETRY_MAX_S)
        self._retry_thread = threading.Thread(target=self._fetch_plan, name="sada-backoffice", daemon=True)
        self._retry_thread.start()

    def _fetch_plan(self):
        """(times, programme) from the back office, None where it is still unreachable."""
        times = prayers.from_backoffice(self.cfg.backoffice_url, self.cfg.api_port, log=log.info)
        program = events_mod.from_backoffice(self.cfg.backoffice_url, self.cfg.api_port, log=log.info)
        if times is None and program is None:
            delay = max(0.0, self._retry_at - time.monotonic())
            log.info(_("Back office still unreachable: next try in {delay:.0f} s", delay=delay))
            return
        self._fetched = (times, program)

    def _apply_plan(self, times: dict | None, program: list | None, sig: Signals):
        """Times / programme received late: today's sessions are replanned where they stand."""
        if times is not None and times.get("jumua_list"):
            self.times_data, self.times = times, list(times["jumua_list"])
            self._times_fallback = False
            log.info(
                _(
                    "Times ({name}): jumua={jumua} — origin: {origin}",
                    name=times.get("name"),
                    jumua=times["jumua_list"],
                    origin=times.get("origin"),
                )
            )
        if program is not None:
            self.program, self._program_remote = program, True
        self._stale = self._times_fallback or not self._program_remote
        day = sig.now.date()
        self.instances = events_mod.instances_on(self.program, day, self.prayer_times)
        sessions, extras = self.day_plan(day)
        if self._rolled and not any(rec.status != "pending" for rec in self.machine.records):
            # fresh times right after midnight, nothing played yet: the day is planned again whole
            self._rolled = False
            if self.machine.new_day(sessions, extras, sig):
                log.info(
                    _("Sessions of the day (mosque clock): {times}", times=[s.strftime("%H:%M") for s in sessions])
                )
                return
        added = self.machine.replan(sessions, extras, sig)
        log.info(
            _(
                "Back office reached again: {count} session(s) added to today's plan ({times})",
                count=added,
                times=[s.strftime("%H:%M") for s in self.machine.sessions],
            )
        )

    # --- events ---------------------------------------------------------------
    def _next_event(self, now: dt.datetime):
        """Next class, announced on the end screen and during the interlude."""
        classes = [e for e in self.program if e.kind != "tarawih"]  # a prayer is not a class to announce
        found = events_mod.next_instances(classes, now, count=1, days=21, times_for=lambda d: self.prayer_times)
        return found[0] if found else None

    # --- broadcast -----------------------------------------------------------
    def _sync(self):
        """Aligns the live stage on its machine, then the notifications and the stream start/stop."""
        m, enc = self.machine, self.encoder
        enc.hold = m.state == State.ENDED  # end screen: the stream is about to stop, never relaunch it
        # a live being ended on purpose (end screen) never gets the reconnection screen, and one that is up is cut
        enc.no_fallback = m.state in (State.ENDED, State.DARS_END)
        self._show(self.live_stage)
        self._follow_signal(m, enc)
        if m.state != self._notified_state:
            if self._notified_state is not None:
                self.telemetry.state_changed(self._notified_state.value, m.state.value)
            self._notified_state = m.state
            if notify.should_send(m.state, m, self.clock.now()):
                self.notifier.notify_state(m.state, m)
        if m.stream_on and not enc.wanted:
            self._stop_rehearsal()  # the live takes the monitoring copy: the setup steps aside first
            enc.start()
            self._stream_since = time.monotonic()
        elif not m.stream_on and enc.wanted:
            enc.stop()
            self._stream_since = None
            log.info(_("Stream stopped. Recordings: {files}", files=[r for r, _x in enc.recordings]))
            self._envoyer_rediffusions()
        self._save_sessions()

    def _follow_signal(self, m, enc) -> None:
        """The input of the live is gone (the encoder sends the reconnection screen): a state change for the readers
        (new `rev`), and the live ends like a normal stop once the grace is over, unless the input came back."""
        lost_for = enc.signal_lost_for()
        if (lost_for is not None) != self._signal_lost:
            self._signal_lost = lost_for is not None
            m.touch()
            if self._signal_lost:
                log.warning(
                    _(
                        "Signal lost: the reconnection screen is on air, the live ends in {grace:g} s unless it comes back",
                        grace=studio_link.SIGNAL_GRACE_S,
                    )
                )
            else:
                log.info(_("Signal back: the live resumes"))
        if lost_for is not None and lost_for >= studio_link.SIGNAL_GRACE_S and m.stream_on:
            log.info(
                _("Signal lost for {grace:g} s: {msg}", grace=lost_for, msg=m.end_lost(self.signals(), "signal perdu"))
            )

    def _set_compositing(self, stage: setup_mode.Stage | None, mode) -> None:
        """Who composes this stage's picture (see Stage.compositing). A change redraws the stage at the next pass
        and is a mutation of the state (new `rev`): the studio reads it to start or stop composing."""
        mode = setup_mode.compositing_of(mode)
        if stage is None or stage.compositing == mode:
            return
        stage.compositing = mode
        stage.shown_key = stage.overlay_key = None
        stage.machine.touch()
        log.info(
            _(
                "Compositing ({stage}): {mode}",
                stage="setup" if stage.rehearsal else "live",
                mode=_("by the Sada Studio, the stream is relayed as is") if mode == "studio" else _("by the server"),
            )
        )

    #: the Studio's stream may drop for a few seconds (WHIP reconnection, relay not ready yet): the server only takes
    #: the picture back after this long without any publisher, never on a blip that would flash its slate on air.
    STUDIO_GONE_S = 20.0
    _studio_gone_since: float | None = None
    _signal_lost = False  # the encoder is on the reconnection screen (see _follow_signal)

    def _follow_editor(self, ann, now: float | None = None) -> None:
        """The back office says who feeds the relay: a Sada Studio device composes its own picture.

        Another editor that is clearly there (OBS, the control room) takes over at once. Nobody, or a publisher the
        back office cannot name, takes over from the Studio only once it lasted `STUDIO_GONE_S`."""
        mode = getattr(ann, "compositing", None) if ann is not None else None
        if mode is None:
            return
        now = time.monotonic() if now is None else now
        stage = self.live_stage
        named = getattr(ann, "publisher", None) in ("obs", "regie")
        if stage is not None and stage.compositing == "studio" and mode == "server" and not named:
            if self._signal_lost:
                return  # the reconnection screen is on air: the server composing instead would only hide the return
            if self._studio_gone_since is None:
                self._studio_gone_since = now
            if now - self._studio_gone_since < self.STUDIO_GONE_S:
                return
        self._studio_gone_since = None
        self._set_compositing(stage, mode)

    def _blank(self) -> Image.Image:
        return Image.new("RGBA", (int(self.cfg.width), int(self.cfg.height)), (0, 0, 0, 0))

    def _show_passthrough(self, stage: setup_mode.Stage) -> None:
        """The Sada Studio composes the scenes, the overlays and the mute itself: the encoder lays nothing over its
        stream (no slate, no banner, no overlay) and never cuts its sound. The machine keeps running as usual."""
        m, enc = stage.machine, stage.encoder
        if m.scene is not None and stage.shown_key != PASSTHROUGH_SCENE:
            stage.shown_key = PASSTHROUGH_SCENE
            enc.show(PASSTHROUGH_SCENE, False, self._blank(), transition=m.transition)
        if m.scene is not None and not enc.mic_on:
            enc.mic(True)
        if stage.overlay_key != PASSTHROUGH_SCENE:
            stage.overlay_key = PASSTHROUGH_SCENE
            enc.set_overlay(self._blank())

    def _show(self, stage: setup_mode.Stage):
        """Aligns one stage's encoder on its machine: displayed scene, overlays, mic (not the stream start/stop)."""
        if stage.compositing == "studio":
            self._show_passthrough(stage)
            return
        m, enc = stage.machine, stage.encoder
        if m.scene is not None:
            now = self.clock.now()
            if m.scene.startswith("custom:"):
                custom_img = self._custom_image(m.scene)
                key = (m.scene, id(custom_img))
                if key != stage.shown_key and custom_img is not None:
                    stage.shown_key = key
                    enc.show(
                        m.scene,
                        True,
                        render_custom_scene(custom_img, self.cfg),
                        transition=m.transition,
                    )
                if enc.mic_on:
                    enc.mic(False)
            else:
                spec = SCENES[m.scene]
                ev = (
                    m.playing.event()
                    if m.scene in ("dars", "tarawih", "tarawih_video") and m.playing is not None
                    else None
                )
                nxt = self._next_event(now) if m.scene in ("dars_fin", "entracte") else None
                key = (
                    m.scene,
                    m.session,
                    m.janaza_name,
                    m.janaza_info,
                    (ev or {}).get("title"),
                    (ev or {}).get("reciter"),
                    getattr(nxt, "starts", None),
                    now.strftime("%H:%M:%S") if spec.ticking else None,
                )
                if key != stage.shown_key:
                    stage.shown_key = key
                    moment = Moment(now, m.session, m.janaza_name, m.janaza_info, event=ev, next_event=nxt)
                    if not self._afficher_gabarit(m.scene, spec.full, moment, enc):
                        enc.show(m.scene, spec.full, self.renderer.content(m.scene, moment), transition=m.transition)
                want_mic = spec.mic and not m.mic_muted
                if want_mic != enc.mic_on:
                    enc.mic(want_mic)
        ov_key = json.dumps(m.overlays, sort_keys=True)
        if ov_key != stage.overlay_key:
            stage.overlay_key = ov_key
            enc.set_overlay(self.renderer.render_overlays(m.overlays))

    def _template_active(self) -> bool:
        """The mosque imported a template: its screens replace the background during a run (see Encoder)."""
        return bool(getattr(self.gabarit, "actif", False))

    def _afficher_gabarit(self, scene: str, full: bool, moment, encoder=None) -> bool:
        """Le fichier de la mosquée pour cet écran ; ``False`` s'il n'en fournit pas.

        Une image déjà rendue pour cet état n'est pas réécrite : le direct n'a rien à changer.
        Les écrans pleins passent en fond opaque ; le bandeau (khutba, dars) reste transparent hors
        de son panneau et passe en calque de contenu, la caméra restant visible autour.
        """
        if self.gabarit is None or not self.gabarit.actif:
            return False
        from .gabarit_antenne import BANDEAUX, ECRANS

        if scene not in ECRANS and scene not in BANDEAUX:
            return False
        png = self.gabarit.image(scene, moment)
        if png is None:
            return False
        cle = f"{scene}|{self.gabarit.variable_de_l_instant(scene)}"
        try:
            image = Image.open(io.BytesIO(png)).convert("RGBA")
        except Exception as e:  # noqa: BLE001 — image illisible : on dessine
            log.warning(
                _("Template: image of screen {screen} unreadable ({error}) — engine drawing", screen=scene, error=e)
            )
            return False
        enc = encoder or self.encoder
        if scene in BANDEAUX:
            enc.show(scene, full, image)
        else:
            enc.show_image(scene, full, image, cle)
        return True

    def _envoyer_rediffusions(self):
        """Les fichiers du direct partent en tâche de fond : le moteur n'attend pas le réseau."""
        fichiers = [f for paire in self.encoder.recordings for f in paire if f]
        fil = self.uploader.envoyer(fichiers)
        if fil:
            log.info(_("Upload: {count} file(s) being sent", count=len(fichiers)))

    def _save_sessions(self):
        recs = self.encoder.recordings
        data = {
            "run_id": self.run_id,
            "recordings": [r for r, _ in recs],
            "recordings_clean": [c for _, c in recs],
            "clock_sim": self.cfg.sim_start,
            "sessions": self.machine.sessions_dicts(),
            "mosque": self.cfg.mosque_name,
        }
        if data != self._saved:
            runs.write(self.run_dir, data)
            self._saved = data

    # ------------------------------------------------------------------ API
    def signals(self) -> Signals:
        v, s = self.vad.runs()
        pres = self.presence.present() if self.presence else None
        face_run = self.faces.absence_run() if self.faces else None
        return Signals(
            now=self.clock.now(), t=time.monotonic(), voice_run=v, silence_run=s, presence=pres, face_run=face_run
        )

    def telemetry_snapshot(self) -> telemetry.OrchestratorSnapshot:
        """Numbers only (no title, name or address), read without the lock: a stale value is harmless."""
        since = self._stream_since
        return telemetry.OrchestratorSnapshot(
            state=self.machine.state.value,
            stream_on=self.encoder.wanted,
            stream_live_s=time.monotonic() - since if since is not None else 0.0,
            encoder_alive=self.encoder.alive(),
            encoder_restarts=self.encoder.restarts,
            ingest_connected=self.vad.connected,
        )

    # --- setup mode (rehearsal stage) ---------------------------------------
    def _stage_for(self, setup: bool) -> setup_mode.Stage:
        """Where a command lands. A live on air always takes it (setup never gets in its way); a command
        sent from the setup view lands on the rehearsal stage, and is refused once the setup lapsed, so a
        scene picked there can never start a real stream by accident; any other command is the live's."""
        if self.machine.stream_on or not setup:
            return self.live_stage
        if self.rehearsal is None or not self.setup.active():
            raise setup_mode.SetupInactive(_("setup mode is not active"))
        return self.rehearsal

    def _sync_stage(self, stage: setup_mode.Stage) -> None:
        if stage.rehearsal:
            self._sync_setup()
        else:
            self._sync()

    def _take_offair_scene(self, scene: str, setup: bool) -> bool:
        """A known scene taken while nothing is on air (and not from the setup view): it only becomes the picture
        shown. The state, the encoder and the recording stay as they are. Under `self.lock`."""
        if setup or self.machine.stream_on:
            return False
        sc = str(scene or "").strip().lower()
        if sc.startswith(CUSTOM_SCENE_PREFIX):
            if not self.machine.custom_known(sc):
                return False
        elif sc not in STATE_OF_SCENE:
            return False  # unknown: the machine answers it, changing nothing
        self.offair_scene = sc
        return True

    def manual(self, cmd: str, arg=None, transition: str | None = None, setup: bool = False) -> dict:
        with self.lock:
            st = self._stage_for(setup)
            m = st.machine
            if transition is not None:
                m.set_transition(transition)
            if cmd == "scene" and st is self.live_stage and self._take_offair_scene(arg, setup):
                m.touch()
                msg = _("scene {scene} (off air: picture only)", scene=self.offair_scene)
                return {"message": msg, "state": m.state.value, "transition": m.transition, **self._fresh(st)}
            msg = m.command(cmd, self.signals(), arg)
            self._sync_stage(st)
            return {"message": msg, "state": m.state.value, "transition": m.transition, **self._fresh(st)}

    def _fresh(self, st: setup_mode.Stage) -> dict:
        """What a command answers besides its own fields: the stage's revision and the whole status after it, so
        the caller shows the consequence without asking again (and can order it against its polls by `rev`)."""
        return {"rev": st.machine.rev, "compositing": st.compositing, "status": self.status()}

    def set_transition(self, mode: str, setup: bool = False) -> dict:
        with self.lock:
            st = self._stage_for(setup)
            m = st.machine
            mode = m.set_transition(mode)
            return {"transition": mode, "state": m.state.value, **self._fresh(st)}

    def _custom_image(self, scene_id: str) -> Image.Image | None:
        img = self._custom_scenes.get(scene_id)
        if img is not None:
            self._custom_scenes.move_to_end(scene_id)
        return img

    def _remember_custom(self, scene_id: str, img: Image.Image) -> None:
        """Keeps the image of a custom scene; the least recently used go when the cap is reached, except the
        ones a stage is showing (an evicted scene would just have to be uploaded again)."""
        self._custom_scenes[scene_id] = img
        self._custom_scenes.move_to_end(scene_id)
        shown = {self.machine.scene} | ({self.rehearsal.machine.scene} if self.rehearsal else set())
        for key in list(self._custom_scenes):
            if len(self._custom_scenes) <= MAX_CUSTOM_IMAGES:
                break
            if key not in shown and key != scene_id:
                del self._custom_scenes[key]

    def set_custom_scene(
        self, scene_id: str, image_bytes: bytes | None, transition: str | None = None, setup: bool = False
    ) -> dict:
        import io

        from PIL import Image

        if not isinstance(scene_id, str) or not scene_id.startswith("custom:") or len(scene_id) <= 7:
            raise ValueError(_("unknown scene: {scene}", scene=scene_id))
        with self.lock:
            st = self._stage_for(setup)
            m = st.machine
            if image_bytes:
                try:
                    im = Image.open(io.BytesIO(image_bytes))
                    im.load()
                    self._remember_custom(scene_id, im.convert("RGBA"))
                except Exception:
                    raise ValueError(_("unreadable image file")) from None
            elif scene_id not in self._custom_scenes:
                raise ValueError(_("unknown scene: {scene}", scene=scene_id))
            if transition is not None:
                m.set_transition(transition)
            if st is self.live_stage and self._take_offair_scene(scene_id, setup):
                m.touch()
                return {
                    "message": _("scene {scene} (off air: picture only)", scene=scene_id),
                    "state": m.state.value,
                    "scene": scene_id,
                    "transition": m.transition,
                    **self._fresh(st),
                }
            msg = m.command("scene", self.signals(), scene_id)
            self._sync_stage(st)
            return {
                "message": msg,
                "state": m.state.value,
                "scene": scene_id,
                "transition": m.transition,
                **self._fresh(st),
            }

    def set_overlay(self, kind: str, data: dict, setup: bool = False) -> dict:
        with self.lock:
            st = self._stage_for(setup)
            overlays = st.machine.set_overlay(kind, data)
            self._sync_stage(st)
            return {"overlays": overlays, "state": st.machine.state.value, **self._fresh(st)}

    def set_mute(self, muted: bool, setup: bool = False) -> dict:
        with self.lock:
            st = self._stage_for(setup)
            st.machine.set_mute(muted)
            self._sync_stage(st)
            return {
                "mic_muted": st.machine.mic_muted,
                "mic": st.encoder.mic_on,
                "state": st.machine.state.value,
                **self._fresh(st),
            }

    def set_setup(self, on: bool, ttl=None, compositing: str | None = None) -> dict:
        """Takes, renews or releases the setup lease. Opening wakes nothing by itself (the process is already
        running when this is called); it prepares the rehearsal stage, which starts once a scene is shown.

        Stopping an encoder waits for ffmpeg (seconds): that happens outside `self.lock`, so the engine's loop and
        the other commands are not held. `_setup_gate` serialises lease changes, so a new stage is never built (same
        ports, same folder) while the previous encoder is still going down.

        `compositing`: "studio" when the lease is a Sada Studio device's, which composes the picture itself (the
        rehearsal then only relays); None keeps what the previous call said."""
        with self._setup_gate:
            if not on:
                with self.lock:
                    if self.setup.close():
                        log.info(_("Setup mode: ended"))
                    old = self._detach_rehearsal()
                self._stop_stage(old)
                with self.lock:
                    return self.setup_status()
            if not self.cfg.preview_url:
                raise ValueError(_("setup mode needs the monitoring copy (SADA_PREVIEW_URL)"))
            with self.lock:
                if compositing is not None:
                    self._setup_compositing = setup_mode.compositing_of(compositing)
                    self._set_compositing(self.rehearsal, self._setup_compositing)
                fresh = self.setup.open(setup_mode.clamp_ttl(ttl))
                rebuild = fresh or self.rehearsal is None
                old = self._detach_rehearsal() if rebuild else None
            if rebuild:
                self._stop_stage(old)
                stage = self._build_rehearsal()
                with self.lock:
                    if self.setup.active():  # the lease may have been released meanwhile
                        self._install_rehearsal(stage)
                        log.info(_("Setup mode: started"))
            with self.lock:
                return self.setup_status()

    def _build_rehearsal(self) -> setup_mode.Stage:
        """A fresh rehearsal stage: its own machine (the day's plan, for the texts), encoder and folders."""
        cfg = replace(self.cfg, rtmp_urls=[], record_clean=False, zmq_port=setup_zmq_port(self.cfg))
        run_dir = self.run_dir / "setup"
        run_dir.mkdir(parents=True, exist_ok=True)
        enc = Encoder(cfg, run_dir, log=log.info, rehearsal=True)
        enc.reload_background = self._template_active()
        enc.prepare(self.renderer.background())
        sessions, extras = self.day_plan(self.clock.now().date())
        machine = Machine(sessions, cfg, log=log.info, extras=extras)
        machine.custom_known = self._custom_scenes.__contains__
        machine.idx = min(self.machine.idx, len(machine.sessions))
        machine.transition = self.machine.transition
        return setup_mode.Stage(machine, enc, rehearsal=True, compositing=self._setup_compositing)

    def _install_rehearsal(self, stage: setup_mode.Stage) -> None:
        """Makes the stage current (under `self.lock`) and aligns it; nothing slow happens here."""
        self.rehearsal = stage
        if not self.machine.stream_on:
            stage.machine.command("scene", self.signals(), setup_mode.FIRST_SCENE)
        self._sync_setup()

    def _detach_rehearsal(self) -> setup_mode.Stage | None:
        """Forgets the current stage (under `self.lock`) and hands it back, to be stopped outside the lock."""
        st, self.rehearsal = self.rehearsal, None
        return st

    @staticmethod
    def _stop_stage(st: setup_mode.Stage | None) -> None:
        """Stops a stage's encoder (the monitoring copy goes away with it): slow, never under `self.lock`."""
        if st is not None and st.encoder.wanted:
            st.encoder.stop()

    def _stop_rehearsal(self, drop: bool = False) -> None:
        """Stops the rehearsal encoder (the monitoring copy goes away with it); `drop` forgets the stage."""
        st = self.rehearsal
        if st is None:
            return
        self._stop_stage(st)
        st.shown_key = None
        if drop:
            self.rehearsal = None

    def _sync_setup(self) -> None:
        """One pass on the rehearsal stage: lapsed lease, live taking over, scene on screen, encoder on/off."""
        st = self.rehearsal
        if st is None:
            return
        if not self.setup.active():
            log.info(_("Setup mode: lease lapsed, rehearsal stopped"))
            self._stop_rehearsal(drop=True)
            return
        if self.machine.stream_on:
            self._stop_rehearsal()  # a real live is on air: the monitoring copy is its own
            return
        if st.machine.scene is None:
            # The stage was opened while a live was still on air (its end screen): no scene was set then, and
            # nothing else would ever set one, so the monitoring copy would never be published.
            st.machine.command("scene", self.signals(), setup_mode.FIRST_SCENE)
        self._show(st)
        if st.machine.stream_on and not st.encoder.wanted:
            st.encoder.start()
        elif not st.machine.stream_on and st.encoder.wanted:
            st.encoder.stop()

    def setup_status(self) -> dict:
        """The setup block of the status: lease, who has the monitoring copy, and the rehearsal stage's picture."""
        st = self.rehearsal
        active = self.setup.active()
        out = {
            "active": active,
            "remaining_s": round(self.setup.remaining(), 1),
            "available": bool(self.cfg.preview_url),
            "live": bool(self.machine.stream_on),
            "rehearsing": bool(active and st is not None and st.encoder.wanted and not self.machine.stream_on),
        }
        if active and st is not None:
            m = st.machine
            out.update(
                {
                    "state": m.state.value,
                    "scene": m.scene,
                    "override": m.override,
                    "transition": m.transition,
                    "overlays": {k: dict(v) for k, v in m.overlays.items()},
                    "mic_muted": m.mic_muted,
                    "janaza_name": m.janaza_name,
                    "janaza_info": m.janaza_info,
                    "playing_event": m.playing.event() if m.playing is not None else None,
                    "encoder_alive": st.encoder.alive(),
                    "rev": m.observe(),
                    "compositing": st.compositing,
                }
            )
        return out

    def _signal_status(self) -> dict:
        """Where the grace stands while the reconnection screen is on air: when the signal was lost (epoch s), when the
        live ends if it does not come back, and what remains (the readers count down from it, free of any clock skew)."""
        lost_for = self.encoder.signal_lost_for() if self._signal_lost else None
        lost = self.encoder.lost_wall if lost_for is not None else None
        if lost_for is None or lost is None:
            return {"signal_lost_since": None, "fallback_until": None, "fallback_remaining_s": None}
        return {
            "signal_lost_since": round(lost, 1),
            "fallback_until": round(lost + studio_link.SIGNAL_GRACE_S, 1),
            "fallback_remaining_s": round(max(0.0, studio_link.SIGNAL_GRACE_S - lost_for), 1),
        }

    def status(self) -> dict:
        with self.lock:
            st = self.machine.status()
            if self.machine.stream_on:
                self.offair_scene = None  # a live took over: the scene on air is the machine's
            st["preview_scene"] = self.offair_scene
            v, s = self.vad.runs()
            _tok, pos = self.encoder.position()
            face_abs = self.faces.absence_run() if self.faces else None
            face_score = self.faces.last_score() if self.faces else None
            st.update(
                {
                    "run_id": self.run_id,
                    "clock": self.clock.now().strftime("%H:%M:%S"),
                    "clock_speed": self.clock.speed,
                    "vad": {"connected": self.vad.connected, "voice_run_s": round(v, 1), "silence_run_s": round(s, 1)},
                    "encoder": {
                        "alive": self.encoder.alive(),
                        "restarts": self.encoder.restarts,
                        "recording": self.encoder.current_recording(),
                        "pos_s": round(pos, 1),
                        "fallback": bool(self.encoder.fallback),
                    },
                    **self._signal_status(),
                    "setup": self.setup_status(),
                    "compositing": self.live_stage.compositing,
                    "mic": self.encoder.mic_on,
                    "mic_muted": self.machine.mic_muted,
                    "audio_level_db": getattr(self.vad, "last_db", lambda: None)(),
                    "presence": (
                        {"mode": "motion", "present": self.presence.present(), "score": self.presence.last_score()}
                        if self.presence
                        else {"mode": "off", "present": None, "score": None}
                    ),
                    "face": (
                        {
                            "mode": self.cfg.face,
                            "present": self.faces.present(),
                            "absence_s": round(face_abs, 1) if face_abs is not None else None,
                            "score": round(face_score, 2) if face_score is not None else None,
                        }
                        if self.faces
                        else {"mode": "off", "present": None, "absence_s": None, "score": None}
                    ),
                }
            )
            return st

    # --- loop --------------------------------------------------------------
    def _target_speed(self) -> float:
        return self.accel if self.machine.clock_only(self.clock.now()) else 1.0

    def run(self):
        cfg = self.cfg
        self.vad.start()
        self.studio_poll.start()
        if self.presence:
            self.presence.start()
        if self.faces:
            self.faces.start()
        self.api = make_server(self, cfg.api_host, cfg.api_port, cfg.api_token)
        log.info(
            _(
                "Control API: http://{host}:{port}/   | initial state {state}",
                host=cfg.api_host,
                port=cfg.api_port,
                state=self.machine.state.value,
            )
        )
        for sig_ in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig_, lambda *a: self._stop.set())
        last_status = 0.0
        while not self._stop.is_set():
            with self.lock:
                want = self._target_speed()
                if want != self.clock.speed:
                    self.clock.set_speed(want)
                    log.info(_("Simulated clock: speed x{speed:g}", speed=want))
                sig = self.signals()
                self.machine.tick(sig)
                self._roll_day(sig)
                self._retry_plan(sig)
                self._retry_live_config()
                ann = self.studio_poll.take()
                if note := self.studio.step(self.machine, sig, ann):
                    log.info(note)
                self._follow_editor(ann)
                self._sync()
                self._sync_setup()
            if time.monotonic() - last_status > 30:
                last_status = time.monotonic()
                st = self.status()
                log.info(
                    _(
                        "status: state={state} clock={clock} vad={vad} enc={enc}",
                        state=st["state"],
                        clock=st["clock"],
                        vad=st["vad"],
                        enc=st["encoder"],
                    )
                )
            self._stop.wait(0.5)
        log.info(_("Stop requested"))
        self.shutdown()

    def shutdown(self):
        self.studio_poll.stop()
        self.vad.stop()
        if self.presence:
            self.presence.stop()
        if self.faces:
            self.faces.stop()
        self._stop_rehearsal(drop=True)
        if self.encoder.wanted:
            self.encoder.stop()
        self._envoyer_rediffusions()
        if self.api:
            self.api.shutdown()
        self._save_sessions()
        self.telemetry.shutdown()


# Command-line aliases: the flag keeps the field name, unless a shorter name is in use.
CLI_ALIASES = {
    "jumua_times_override": ("--times",),
    "mosque_name": ("--mosque-name",),
    "mosque_name_ar": ("--mosque-name-ar",),
}


def cli_type(template):
    """Argument type, deduced from the default value of the setting."""
    if isinstance(template, bool):
        return lambda v: str(v).strip().lower() in ("1", "true", "yes", "on", "oui")
    if isinstance(template, int):
        return int
    if isinstance(template, float):
        return float
    return str


def parser() -> argparse.ArgumentParser:
    """Command line built from Config: one flag per setting, same name as the JSON key.

    Nothing is defaulted here: an absent flag stays None and Config.load applies the one precedence
    (flag > SADA_<FIELD> environment > --config file > default). Per-session timings (khutba, dars)
    are only read from the JSON file: `{"khutba": {"silence_stop_s": 60}}`.
    """
    from dataclasses import MISSING, fields

    from .config import env_name

    ap = argparse.ArgumentParser(description=_("Sadā — orchestrator"))
    ap.add_argument("--config", help=_("JSON configuration file"))
    for f in fields(Config):
        template = (
            f.default
            if f.default is not MISSING
            else (f.default_factory() if f.default_factory is not MISSING else None)
        )
        if isinstance(template, SessionParams):
            continue
        flags = (f"--{f.name.replace('_', '-')}",) + tuple(CLI_ALIASES.get(f.name, ()))
        ap.add_argument(
            *flags,
            dest=f.name,
            type=cli_type(template),
            default=None,
            metavar=f.name.upper(),
            help=_("default {default} ; env {env}", default=repr(template), env=env_name(f.name)),
        )
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    ov = {k: v for k, v in vars(a).items() if k != "config" and v is not None}
    Orchestrator(Config.load(a.config, **ov)).run()


if __name__ == "__main__":
    main()
