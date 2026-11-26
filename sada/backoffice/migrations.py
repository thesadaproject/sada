"""Schema of the back office database, versioned with Alembic.

- The models (`models.py`) are the only description of the schema. Every change ships with a migration in
  `schema/versions/`, generated from them: `python -m sada.backoffice.migrations revision "message"`.
- `init(path)` brings a database to the latest revision at start-up. A new database goes through every
  migration, exactly like production did: no shortcut that could hide a missing one.
- A test rebuilds a database through the migrations and compares it to the models (`differences`): a model
  changed without its migration fails the CI.

Adoption of the former home-made system (`schema_migrations`, versions 1 to 26, last shipped in
0.1.0-alpha.22): a database at version 26 has exactly the baseline schema; it is stamped at the baseline
revision without touching its data, and the old bookkeeping table is dropped. An older one is refused: no
installation older than that exists.
"""

from __future__ import annotations

import sys
import tempfile
import warnings
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from ..i18n import _

SCRIPTS = Path(__file__).resolve().parent / "schema"
#: revision whose schema is the one the former system left at its last version
BASELINE = "0001"
LEGACY_TABLE = "schema_migrations"
LEGACY_LAST = 26

#: objects of the database that the models do not describe: search side tables, triggers' FTS5 storage,
#: pgvector table, bookkeeping. Alembic never compares nor drops them.
_EXTRA_TABLE_PREFIXES = ("transcript_segments_fts", "segment_vectors", "alembic_version", LEGACY_TABLE)
_EXTRA_INDEXES = {"transcript_segments_tsv", "segment_vectors_hnsw"}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table" and name and name.startswith(_EXTRA_TABLE_PREFIXES):
        return False
    if type_ == "index" and name in _EXTRA_INDEXES:
        return False
    return True


def config(conn: sa.Connection | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(SCRIPTS))
    cfg.attributes["connection"] = conn
    return cfg


def head() -> str:
    h = ScriptDirectory.from_config(config()).get_current_head()
    assert h, "no migration"
    return h


def current(conn: sa.Connection) -> str | None:
    return MigrationContext.configure(conn).get_current_revision()


def _tables(conn: sa.Connection) -> set[str]:
    return set(sa.inspect(conn).get_table_names())


def _adopt_legacy(conn: sa.Connection, path) -> None:
    """A database of the former system: stamped at the baseline if it reached its last version."""
    version = conn.scalar(sa.text(f"SELECT MAX(version) FROM {LEGACY_TABLE}"))
    if version != LEGACY_LAST:
        raise RuntimeError(
            _(
                "database {path} is at version {version} of the former migrations: update it with 0.1.0-alpha.22 first",
                path=path,
                version=version,
            )
        )
    command.stamp(config(conn), BASELINE)
    conn.exec_driver_sql(f"DROP TABLE {LEGACY_TABLE}")


def init(path: str | Path) -> None:
    """Creates or upgrades the database `path` to the latest revision, in one transaction."""
    from .db import DEFAULT_DB  # late import: avoids the db <-> migrations cycle
    from .orm import engine

    with engine(path, DEFAULT_DB).connect() as conn:
        with conn.begin():
            tables = _tables(conn)
            rev = current(conn)
            if rev is None and LEGACY_TABLE in tables:
                _adopt_legacy(conn, path)
            elif rev is None and tables:
                raise RuntimeError(
                    _("database {path} has tables but no schema version: refusing to touch it", path=path)
                )
            rev = current(conn)
            if rev is not None and rev not in {
                s.revision for s in ScriptDirectory.from_config(config()).walk_revisions()
            }:
                raise RuntimeError(
                    _(
                        "database {path} is at version {version}, newer than the code ({latest}): update the back-office",
                        path=path,
                        version=rev,
                        latest=head(),
                    )
                )
            command.upgrade(config(conn), "head")


def differences(conn: sa.Connection) -> list:
    """What separates the database from the models (empty: the migrations describe them fully)."""
    from . import models

    ctx = MigrationContext.configure(conn, opts={"include_object": include_object, "compare_type": True})
    with warnings.catch_warnings():  # pgvector's `vector` (segment_vectors, outside the models) is reflected too
        warnings.filterwarnings("ignore", "Did not recognize type", sa.exc.SAWarning)
        return compare_metadata(ctx, models.metadata)


def revision(message: str) -> None:
    """Generates the migration of what changed in the models, against a database at the latest revision."""
    with tempfile.TemporaryDirectory() as td:
        eng = sa.create_engine(f"sqlite:///{Path(td) / 'head.db'}")
        with eng.begin() as conn:
            command.upgrade(config(conn), "head")
            command.revision(config(conn), message=message, autogenerate=True, rev_id=_next_id())
        eng.dispose()


def _next_id() -> str:
    ids = [s.revision for s in ScriptDirectory.from_config(config()).walk_revisions()]
    return f"{max((int(i) for i in ids if i.isdigit()), default=0) + 1:04d}"


if __name__ == "__main__":  # python -m sada.backoffice.migrations revision "message"
    if len(sys.argv) != 3 or sys.argv[1] != "revision":
        sys.exit('usage: python -m sada.backoffice.migrations revision "what changed"')
    revision(sys.argv[2])
