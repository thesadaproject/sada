"""Deployment mode, read the same way by the back office and the orchestrator."""

from __future__ import annotations

import os


def hosted() -> bool:
    """Hosted platform (SADA_MODE=hosted): one server, many mosques, run by an operator. Otherwise the server is the
    mosque's own (self-hosted)."""
    return os.environ.get("SADA_MODE", "").strip().lower() == "hosted"
