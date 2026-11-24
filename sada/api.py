"""Local HTTP API for manual control (stdlib).  Listens on 127.0.0.1 by default; optional X-Token.

GET  /status
POST /<command>?name=...|min=...    Machine.COMMANDS commands (e.g. /extend?min=5, /scene?name=priere,
                                    /janaza?name=...[&info=...]: name and note of the deceased, only with the family's consent)

JSON only: the control screen is the back-office dashboard, there is no page served here.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .i18n import _
from .state import Machine


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
                data = {k: v for k, v in body.items() if k != "kind"}
                try:
                    res = orch.set_overlay(kind, data)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, **res})
            if cmd == "transition":
                body = self._read_json(4096)
                if body is None or not isinstance(body.get("mode"), str):
                    return self._send(400, {"error": _("invalid body")})
                try:
                    res = orch.set_transition(body["mode"])
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
                    res = orch.set_custom_scene(body["scene"], raw, transition=transition)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, **res})
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            arg = q.get("name") or q.get("min")
            if q.get("info"):  # janaza record: "name|note"
                arg = f"{q.get('name', '')}|{q['info']}"
            if cmd not in Machine.COMMANDS:
                return self._send(404, {"error": _("unknown command")})
            tr_mode = q.get("transition")
            res = orch.manual(cmd, arg, transition=tr_mode) if tr_mode is not None else orch.manual(cmd, arg)
            self._send(200, {"ok": True, **res})

    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="api").start()
    return srv
