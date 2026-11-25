"""Local HTTP API for manual control (stdlib).  Listens on 127.0.0.1 by default; optional X-Token.

GET  /status
POST /<command>?name=...|min=...    Machine.COMMANDS commands (e.g. /extend?min=5, /scene?name=priere,
                                    /janaza?name=...[&info=...]: name and note of the deceased, only with the family's consent)
POST /setup {"on": bool, "ttl": seconds}   takes, renews or releases the setup lease (see setup_mode.py)

Any command, overlay, mute or transition may carry `setup` (`?setup=1`, or `"setup": true` in the body): it then
acts on the setup rehearsal stage instead of the live, and is refused once the setup lease lapsed.

JSON only: the control screen is the back-office dashboard, there is no page served here.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .i18n import _
from .setup_mode import SetupInactive
from .state import Machine


def _setup_kw(body: dict) -> dict:
    """`setup=True` only when the caller marked the request: the engine's methods keep their plain shape otherwise."""
    return {"setup": True} if body.get("setup") is True else {}


def make_server(orch, host: str, port: int, token: str = "") -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj, ctype="application/json"):
            body = (obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth(self) -> bool:
            if not token:
                return True
            if self.headers.get("X-Token") == token:
                return True
            auth = self.headers.get("Authorization") or ""
            if auth == f"Bearer {token}":
                return True
            self._send(401, {"error": _("token required")})
            return False

        def _read_json(self, max_bytes: int = 16_384) -> dict | None:
            try:
                n = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                return None
            if n <= 0 or n > max_bytes:
                return None
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return None
            return body if isinstance(body, dict) else None

        def do_GET(self):
            u = urlparse(self.path)
            if not self._auth():
                return
            if u.path == "/status":
                return self._send(200, orch.status())
            self._send(404, {"error": _("unknown")})

        def do_POST(self):
            if not self._auth():
                return
            u = urlparse(self.path)
            cmd = u.path.strip("/")
            if cmd == "overlay":
                body = self._read_json(16_384)
                if body is None or not isinstance(body.get("kind"), str):
                    return self._send(400, {"error": _("invalid body")})
                kind = body["kind"]
                data = {k: v for k, v in body.items() if k not in ("kind", "setup")}
                try:
                    res = orch.set_overlay(kind, data, **_setup_kw(body))
                except SetupInactive as e:
                    return self._send(409, {"error": str(e), "code": "setup_off"})
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, **res})
            if cmd == "mute":
                body = self._read_json(4096)
                if body is None or not isinstance(body.get("muted"), bool):
                    return self._send(400, {"error": _("invalid body")})
                try:
                    res = orch.set_mute(body["muted"], **_setup_kw(body))
                except SetupInactive as e:
                    return self._send(409, {"error": str(e), "code": "setup_off"})
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, **res})
            if cmd == "transition":
                body = self._read_json(4096)
                if body is None or not isinstance(body.get("mode"), str):
                    return self._send(400, {"error": _("invalid body")})
                try:
                    res = orch.set_transition(body["mode"], **_setup_kw(body))
                except SetupInactive as e:
                    return self._send(409, {"error": str(e), "code": "setup_off"})
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, **res})
            if cmd == "custom-scene":
                body = self._read_json(8 * 1024 * 1024)
                if body is None or not isinstance(body.get("scene"), str):
                    return self._send(400, {"error": _("invalid body")})
                raw = None
                if isinstance(body.get("image_b64"), str) and body["image_b64"]:
                    try:
                        raw = base64.b64decode(body["image_b64"].encode("ascii"), validate=True)
                    except ValueError:
                        return self._send(400, {"error": _("invalid body")})
                transition = body.get("transition")
                try:
                    res = orch.set_custom_scene(body["scene"], raw, transition=transition, **_setup_kw(body))
                except SetupInactive as e:
                    return self._send(409, {"error": str(e), "code": "setup_off"})
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, **res})
            if cmd == "setup":
                body = self._read_json(4096)
                if body is None or not isinstance(body.get("on"), bool):
                    return self._send(400, {"error": _("invalid body")})
                try:
                    res = orch.set_setup(body["on"], body.get("ttl"))
                except SetupInactive as e:
                    return self._send(409, {"error": str(e), "code": "setup_off"})
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, **res})
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            arg = q.get("name") or q.get("min")
            if q.get("info"):  # janaza record: "name|note"
                arg = f"{q.get('name', '')}|{q['info']}"
            if cmd not in Machine.COMMANDS:
                return self._send(404, {"error": _("unknown command")})
            kwargs: dict = {"setup": True} if q.get("setup") == "1" else {}
            if q.get("transition") is not None:
                kwargs["transition"] = q["transition"]
            try:
                res = orch.manual(cmd, arg, **kwargs)
            except SetupInactive as e:
                return self._send(409, {"error": str(e), "code": "setup_off"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            self._send(200, {"ok": True, **res})

    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="api").start()
    return srv
