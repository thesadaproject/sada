#!/usr/bin/env python3
"""Copy what a mosque owns on a local instance to the production back office (k3s).

Run from the workstation, with the repository kubeconfig:

    KUBECONFIG=~/.config/sada-deploy/kubeconfig tools/migrate_mosque.py <slug> [--dry-run] [--force]

What is copied (idempotent; whatever already exists in production is left alone):

- `data/screens/<slug>/`                 screen templates (ecrans.html) and their assets
- `data/backoffice/<slug>/`              if present (per-mosque back office files)
- `data/backoffice/custom_scenes/<slug>/` custom scenes (manifest + images, not the `.lock`)
- `data/backoffice/logos/<slug>.*`       logo
- table `screen_texts` of the mosque     free texts of the live screens (one row per screen+slot)

Rules: a file or a row missing in production is added; one that is identical is skipped; one that
differs is **kept as it is in production** and reported, unless `--force` (then the local version
replaces it). Nothing is ever deleted in production. `--dry-run` only prints the plan.

The database is the local SQLite file (opened read-only; override with `--db`); production is
reached through `kubectl exec` in the back office pod (`/app/data`, PostgreSQL via the app's own
settings). Not a deploy tool: it neither restarts nor touches the orchestrators, so restart
`orchestrator-<slug>` yourself afterwards (only when no broadcast is running) to load a new template.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
REMOTE_DATA = "/app/data"
SKIP_NAMES = {".lock"}


# ------------------------------------------------------------------ files (pure)
def local_files(data: Path, slug: str) -> dict[str, Path]:
    """Relative path (under the data directory) -> local file, for everything the mosque owns."""
    found: dict[str, Path] = {}
    roots = [data / "screens" / slug, data / "backoffice" / slug, data / "backoffice" / "custom_scenes" / slug]
    for root in roots:
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.name not in SKIP_NAMES and not p.is_symlink():
                    found[p.relative_to(data).as_posix()] = p
    logos = data / "backoffice" / "logos"
    if logos.is_dir():
        for p in sorted(logos.glob(f"{slug}.*")):
            if p.is_file():
                found[p.relative_to(data).as_posix()] = p
    return found


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan_files(local: dict[str, Path], remote: dict[str, str], force: bool) -> dict[str, list[str]]:
    """Split the local files: `add` (absent in prod), `same`, `differ` (kept unless force), `replace`."""
    plan: dict[str, list[str]] = {"add": [], "same": [], "differ": [], "replace": []}
    for rel, p in local.items():
        if rel not in remote:
            plan["add"].append(rel)
        elif remote[rel] == sha256(p):
            plan["same"].append(rel)
        else:
            plan["replace" if force else "differ"].append(rel)
    return plan


# ------------------------------------------------------------------ screen_texts
def local_screen_texts(db: Path, slug: str) -> list[dict]:
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT t.screen, t.slot, t.text, t.updated_at FROM screen_texts t "
            "JOIN mosques m ON m.id = t.mosque_id WHERE m.slug = ? ORDER BY t.screen, t.slot",
            (slug,),
        ).fetchall()
    except sqlite3.DatabaseError:
        return []
    finally:
        con.close()
    return [{"screen": s, "slot": o, "text": t, "updated_at": u} for s, o, t, u in rows]


def apply_screen_texts(conn, slug: str, rows: list[dict], force: bool, dry_run: bool) -> dict:
    """Runs in production (the back office pod). `conn` is a back office session.

    Missing rows are inserted, identical ones skipped, different ones kept unless `force`.
    """
    import sqlalchemy as sa

    from sada.backoffice.models import Mosque, screen_texts

    mid = conn.scalar(sa.select(Mosque.id).where(Mosque.slug == slug))
    if mid is None:
        return {"error": f"mosque {slug!r} not found in production"}
    have = {
        (r.screen, r.slot): r.text for r in conn.execute(sa.select(screen_texts).where(screen_texts.c.mosque_id == mid))
    }
    out = {"add": 0, "same": 0, "differ": 0, "replace": 0}
    for r in rows:
        key = (r["screen"], r["slot"])
        if key not in have:
            out["add"] += 1
            if not dry_run:
                conn.execute(sa.insert(screen_texts).values(mosque_id=mid, **r))
        elif have[key] == r["text"]:
            out["same"] += 1
        elif force:
            out["replace"] += 1
            if not dry_run:
                conn.execute(
                    sa.update(screen_texts)
                    .where(
                        screen_texts.c.mosque_id == mid,
                        screen_texts.c.screen == r["screen"],
                        screen_texts.c.slot == r["slot"],
                    )
                    .values(text=r["text"], updated_at=r["updated_at"])
                )
        else:
            out["differ"] += 1
    if not dry_run:
        conn.commit()
    return out


REMOTE_TEXTS = """
import json, sys
from sada.backoffice import db
{source}
payload = json.load(sys.stdin)
conn = db.connect(db.DEFAULT_DB)
print(json.dumps(apply_screen_texts(conn, payload["slug"], payload["rows"], payload["force"], payload["dry_run"])))
"""


# ------------------------------------------------------------------ kubectl
def kubectl(*args: str, stdin: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [
        "kubectl",
        "-n",
        "sada",
        "exec",
        *(["-i"] if stdin is not None else []),
        "deploy/backoffice",
        "-c",
        "backoffice",
        "--",
        *args,
    ]
    r = subprocess.run(cmd, input=stdin, capture_output=True)
    if check and r.returncode:
        sys.exit(f"kubectl failed: {r.stderr.decode(errors='replace').strip()}")
    return r


def remote_hashes(slug: str) -> dict[str, str]:
    """Relative path -> sha256 of the same candidate files in production."""
    script = (
        f"cd {REMOTE_DATA} && for p in screens/{slug} backoffice/{slug} backoffice/custom_scenes/{slug}; do "
        f'[ -d "$p" ] && find "$p" -type f ! -name .lock; done; '
        f"ls backoffice/logos/{slug}.* 2>/dev/null; true"
    )
    names = [n for n in kubectl("sh", "-c", script).stdout.decode().splitlines() if n]
    if not names:
        return {}
    r = kubectl("sh", "-c", f'cd {REMOTE_DATA} && sha256sum "$@"', "sh", *names)
    out = {}
    for line in r.stdout.decode().splitlines():
        digest, _, rel = line.partition("  ")
        out[rel] = digest
    return out


def push_files(data: Path, rels: list[str]) -> None:
    if not rels:
        return
    tar = subprocess.run(["tar", "-C", str(data), "-cf", "-", *rels], capture_output=True, check=True)
    kubectl("tar", "-C", REMOTE_DATA, "--no-same-owner", "-xf", "-", stdin=tar.stdout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--data", type=Path, default=ROOT / "data", help="local data directory")
    ap.add_argument("--db", type=Path, help="local SQLite file (default: <data>/backoffice/sada.db)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--force", action="store_true", help="replace what differs in production")
    a = ap.parse_args(argv)
    if not SLUG_RE.match(a.slug):
        sys.exit("invalid slug")
    db = a.db or a.data / "backoffice" / "sada.db"

    local = local_files(a.data, a.slug)
    plan = plan_files(local, remote_hashes(a.slug), a.force)
    for k in ("add", "replace", "differ", "same"):
        for rel in plan[k]:
            print(f"file {k:8} {rel}")
    if not a.dry_run:
        push_files(a.data, plan["add"] + plan["replace"])

    rows = local_screen_texts(db, a.slug)
    payload = json.dumps({"slug": a.slug, "rows": rows, "force": a.force, "dry_run": a.dry_run}).encode()
    code = REMOTE_TEXTS.format(source=inspect.getsource(apply_screen_texts))
    res = json.loads(kubectl("python", "-c", code, stdin=payload).stdout.decode().strip().splitlines()[-1])
    print("screen_texts", res)
    if "error" in res:
        return 1
    if plan["differ"] or res.get("differ"):
        print("note: differing items were kept as in production (use --force to replace them)")
    if a.dry_run:
        print("dry run: nothing changed")
    elif plan["add"] or plan["replace"]:
        print(f"restart orchestrator-{a.slug} (when no broadcast is running) to load new templates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
