"""Alembic environment of the back office database.

Never run on its own: `sada.backoffice.migrations` hands over the connection (`config.attributes`), already
bound to the right database (SQLite file, or PostgreSQL schema through `search_path`).
"""

from __future__ import annotations

from alembic import context

from sada.backoffice import migrations, models

conn = context.config.attributes["connection"]
context.configure(
    connection=conn,
    target_metadata=models.metadata,
    render_as_batch=conn.dialect.name == "sqlite",  # SQLite alters a table by copying it
    include_object=migrations.include_object,
    compare_type=True,
    compare_server_default=False,  # SQLite and PostgreSQL reflect literal defaults differently
)
with context.begin_transaction():
    context.run_migrations()
