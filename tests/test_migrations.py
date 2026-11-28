"""Schéma versionné avec Alembic : base neuve, adoption des bases de l'ancien système, refus de ce qui
ne se reconnaît pas, et surtout : les migrations décrivent exactement les modèles."""

import re

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from conftest import columns, table_names  # noqa: E402

from sada.backoffice import db, migrations, models  # noqa: E402
from sada.backoffice.orm import engine  # noqa: E402

SQLITE = pytest.mark.skipif(bool(__import__("os").environ.get("SADA_DATABASE_URL")), reason="SQLite file format")


def _conn(path):
    return engine(path, db.DEFAULT_DB).connect()


def test_une_seule_tete_et_des_numeros_qui_se_suivent():
    scripts = ScriptDirectory.from_config(migrations.config())
    assert len(scripts.get_heads()) == 1
    ids = [s.revision for s in scripts.walk_revisions()][::-1]
    assert ids == [f"{i:04d}" for i in range(1, len(ids) + 1)]
    assert ids[0] == migrations.BASELINE


def test_les_migrations_decrivent_exactement_les_modeles(tmp_path):
    """Un modèle changé sans sa migration fait échouer ce test : générer la migration avec
    `python -m sada.backoffice.migrations revision "ce qui change"`."""
    path = tmp_path / "neuve.db"
    db.init(path)
    with _conn(path) as conn:
        assert migrations.current(conn) == migrations.head()
        assert migrations.differences(conn) == []


def test_base_neuve_complete(tmp_path):
    path = tmp_path / "neuve.db"
    db.init(path)
    conn = db.connect(path)
    try:
        assert {t.name for t in models.TABLES} <= table_names(conn)
        assert "schema_migrations" not in table_names(conn)
        assert {"kind", "title", "series", "session_no", "chapters"} <= columns(conn, "khutbas")
    finally:
        conn.close()


def test_init_est_rejouable(tmp_path):
    path = tmp_path / "bo.db"
    db.init(path)
    conn = db.connect(path)
    mid = db.create_mosque(conn, "exemple", "Mosquée Exemple")
    conn.close()
    db.init(path)
    conn = db.connect(path)
    try:
        assert conn.scalar(sa.select(models.mosques.c.id).where(models.mosques.c.slug == "exemple")) == mid
    finally:
        conn.close()


# Tables created by a migration after the baseline: the former system never had them. A later migration that
# changes a baseline table (a column) makes the models drift further: freeze that table's former shape here then.
APRES_LA_BASE = {"preview_requests", "tarawih_options"}


def _schema_de_l_ancien_systeme(conn) -> None:
    """Ce que l'ancien code créait : les tables des modèles telles qu'à la version 0001."""
    models.metadata.create_all(conn, tables=[t for t in models.metadata.sorted_tables if t.name not in APRES_LA_BASE])


def _base_de_l_ancien_systeme(path, version: int = migrations.LEGACY_LAST) -> None:
    """Ce que l'ancien code laissait : le schéma des modèles et `schema_migrations` jusqu'à `version`."""
    with engine(path, db.DEFAULT_DB).begin() as conn:
        _schema_de_l_ancien_systeme(conn)
        conn.exec_driver_sql("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, appliquee_le TEXT NOT NULL)")
        for v in range(1, version + 1):
            conn.exec_driver_sql(f"INSERT INTO schema_migrations VALUES ({v}, 'avant')")
        conn.execute(models.mosques.insert().values(slug="pontoise", name="Mosquée de Pontoise", created_at="avant"))


def test_adoption_d_une_base_de_l_ancien_systeme(tmp_path):
    """La prod était à la version 26 de l'ancien système : elle est reprise telle quelle, ses données
    gardées, l'ancienne table de suivi retirée."""
    path = tmp_path / "prod.db"
    _base_de_l_ancien_systeme(path)
    db.init(path)
    with _conn(path) as conn:
        assert migrations.current(conn) == migrations.head()
        assert "schema_migrations" not in sa.inspect(conn).get_table_names()
        assert conn.scalar(sa.select(models.mosques.c.name)) == "Mosquée de Pontoise"
        assert migrations.differences(conn) == []


def test_une_base_trop_ancienne_est_refusee(tmp_path):
    path = tmp_path / "vieille.db"
    _base_de_l_ancien_systeme(path, version=20)
    with pytest.raises(RuntimeError, match="0.1.0-alpha.22"):
        db.init(path)


def test_une_base_sans_version_est_refusee(tmp_path):
    path = tmp_path / "inconnue.db"
    with engine(path, db.DEFAULT_DB).begin() as conn:
        models.metadata.create_all(conn)
    with pytest.raises(RuntimeError, match="no schema version"):
        db.init(path)


def test_une_base_plus_recente_que_le_code_est_refusee(tmp_path):
    path = tmp_path / "future.db"
    db.init(path)
    with engine(path, db.DEFAULT_DB).begin() as conn:
        conn.exec_driver_sql("UPDATE alembic_version SET version_num = '9999'")
    with pytest.raises(RuntimeError, match="newer than the code"):
        db.init(path)


@SQLITE
def test_le_schema_de_depart_est_celui_de_l_ancien_systeme(tmp_path):
    """Une base adoptée n'est pas reconstruite : la migration 0001 doit produire exactement ce que
    l'ancien code créait (tables, colonnes, défauts, contraintes, index, FTS5 et ses déclencheurs)."""

    def schema(md_or_alembic, path):
        eng = sa.create_engine(f"sqlite:///{path}")
        with eng.begin() as conn:
            if md_or_alembic == "ancien":
                _schema_de_l_ancien_systeme(conn)
            else:
                command.upgrade(migrations.config(conn), migrations.BASELINE)
        with eng.connect() as conn:
            rows = conn.exec_driver_sql(
                "SELECT type, name, sql FROM sqlite_master"
                " WHERE name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY type, name"
            ).all()
        eng.dispose()
        return {(t, n): _normalise(s) for t, n, s in rows}

    assert schema("ancien", tmp_path / "a.db") == schema("alembic", tmp_path / "b.db")


def _normalise(sql: str | None) -> str:
    """Le même CREATE, contraintes de table rangées (leur ordre n'a pas de sens)."""
    sql = re.sub(r"\s+", " ", sql or "").replace("( ", "(").replace(" )", ")")
    m = re.match(r"(CREATE TABLE \S+ \()(.*)\)$", sql)
    if not m:
        return sql
    parts = re.split(r", (?=PRIMARY KEY|FOREIGN KEY|UNIQUE|CHECK \()", m.group(2))
    return m.group(1) + parts[0] + " | " + " , ".join(sorted(parts[1:]))
