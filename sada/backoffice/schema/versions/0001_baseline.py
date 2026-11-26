"""Baseline: the schema the former home-made migrations reached at their version 26 (0.1.0-alpha.22).

A database of that system is stamped here without running it (`migrations._adopt_legacy`).

Revision ID: 0001
Revises:
Create Date: 2026-11-26 23:57:19.764944
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from sada.backoffice import models

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mosques",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), server_default=sa.text("'Europe/Paris'"), nullable=False),
        sa.Column("mawaqit_url", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("orchestrator_url", sa.Text(), server_default=sa.text("'http://127.0.0.1:8088'"), nullable=False),
        sa.Column("orchestrator_token", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("agent_token_hash", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("publish_key_hash", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("mawaqit_cache", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("mawaqit_cached_at", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("state_dir", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("output_dir", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("publish_dir", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("default_imam_id", sa.Integer(), nullable=True),
        sa.Column("auto_import", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("logo_path", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("onboarded_at", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("brand_green", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("brand_gold", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("habillage_defaults", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "connectors",
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("settings", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("mosque_id", "key"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mosque_id", "uid"),
    )
    op.create_table(
        "live_input",
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column(
            "mode",
            sa.Text(),
            sa.CheckConstraint("mode IN ('camera', 'push')"),
            server_default=sa.text("'camera'"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("mosque_id"),
    )
    op.create_table(
        "live_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("live_targets", schema=None) as batch_op:
        batch_op.create_index("live_targets_mosque", ["mosque_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column(
            "mode",
            sa.Text(),
            sa.CheckConstraint("mode IN ('', 'webhook', 'telegram')"),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("webhook", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("telegram_token", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("telegram_chat", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("mosque_id"),
    )
    op.create_table(
        "prayer_settings",
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Text(),
            sa.CheckConstraint("source IN ('mawaqit', 'computed', 'manual')"),
            server_default=sa.text("'mawaqit'"),
            nullable=False,
        ),
        sa.Column("calc", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("public", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("jumua", sa.Text(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.Column("accent", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("accent2", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("show_logo", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("mosque_id"),
    )
    op.create_table(
        "prayer_times",
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("fajr", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("sunrise", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("dhuhr", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("asr", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("maghrib", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("isha", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("fajr_iqama", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("dhuhr_iqama", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("asr_iqama", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("maghrib_iqama", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("isha_iqama", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("mosque_id", "day"),
    )
    op.create_table(
        "screen_texts",
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("screen", sa.Text(), nullable=False),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("mosque_id", "screen", "slot"),
    )
    op.create_table(
        "storage",
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("region", sa.Text(), server_default=sa.text("'auto'"), nullable=False),
        sa.Column("bucket", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("access_key", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("secret_key", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("prefix", sa.Text(), server_default=sa.text("'rediffusions/'"), nullable=False),
        sa.Column("enabled", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("mosque_id"),
    )
    op.create_table(
        "stream_quality",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), server_default=sa.text("720"), nullable=False),
        sa.Column("video_kbps", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("fps", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mosque_id"),
    )
    op.create_table(
        "studio_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("start_margin_s", sa.Integer(), server_default=sa.text("120"), nullable=False),
        sa.Column("offline_alert_min", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.Column("khutba_min", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("dars_min", sa.Integer(), server_default=sa.text("90"), nullable=False),
        sa.Column("preflight_min", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mosque_id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.Text(collation="NOCASE").with_variant(sa.Text(), "postgresql"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), sa.CheckConstraint("role IN ('admin', 'responsable', 'imam')"), nullable=False),
        sa.Column("active", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_login_at", sa.Text(), nullable=True),
        sa.Column("permissions", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("must_change_password", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("platform_admin", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("email", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("studio_mail_optout", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit", schema=None) as batch_op:
        batch_op.create_index("audit_mosque", ["mosque_id", "id"], unique=False)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("csrf", sa.Text(), nullable=False),
        sa.Column("created_at", sa.REAL(), nullable=False),
        sa.Column("expires_at", sa.REAL(), nullable=False),
        sa.Column("last_seen_at", sa.REAL(), nullable=False),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("flash", sa.Text(), nullable=True),
        sa.Column("mosque_id", sa.Integer(), nullable=True),
        sa.Column("support", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("secret_hash", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("prev_secret_hash", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("prev_valid_until", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("rotate_requested", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.Float(), nullable=True),
        sa.Column("last_ip", sa.Text(), nullable=True),
        sa.Column("app_version", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("last_state", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("camera_ok", sa.Integer(), nullable=True),
        sa.Column("mic_ok", sa.Integer(), nullable=True),
        sa.Column("bitrate_kbps", sa.Integer(), nullable=True),
        sa.Column("health", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("held_until", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("revoked_at", sa.Text(), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.create_index("devices_mosque", ["mosque_id"], unique=False)

    op.create_table(
        "khutbas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("session_index", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("planned", sa.Text(), nullable=True),
        sa.Column("date", sa.Text(), nullable=True),
        sa.Column("start_clock", sa.Text(), nullable=True),
        sa.Column("end_clock", sa.Text(), nullable=True),
        sa.Column("duration_s", sa.REAL(), nullable=True),
        sa.Column("imam_id", sa.Integer(), nullable=True),
        sa.Column("speaker", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("theme", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("output_dir", sa.Text(), nullable=False),
        sa.Column("recording", sa.Text(), nullable=True),
        sa.Column("start_pos", sa.REAL(), nullable=True),
        sa.Column("end_pos", sa.REAL(), nullable=True),
        sa.Column("video_path", sa.Text(), nullable=True),
        sa.Column("verses_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("'khutba'"), nullable=False),
        sa.Column("title", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("series", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("session_no", sa.Integer(), nullable=True),
        sa.Column("chapters", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("imported_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["imam_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mosque_id", "run_id", "session_index"),
    )
    with op.batch_alter_table("khutbas", schema=None) as batch_op:
        batch_op.create_index("khutbas_mosque", ["mosque_id", "date"], unique=False)

    op.create_table(
        "memberships",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["mosque_id"], ["mosques.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "mosque_id"),
    )
    op.create_table(
        "tarawih",
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column(
            "mode",
            sa.Text(),
            sa.CheckConstraint("mode IN ('off', 'audio', 'video')"),
            server_default=sa.text("'audio'"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("end_date", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("offset_min", sa.Integer(), server_default=sa.text("20"), nullable=False),
        sa.Column("max_min", sa.Integer(), server_default=sa.text("180"), nullable=False),
        sa.Column("after_isha", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("isha_min", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.Column("silence_end_min", sa.Integer(), server_default=sa.text("6"), nullable=False),
        sa.Column("reciters", sa.Text(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("nights", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("video_confirmed_by", sa.Integer(), nullable=True),
        sa.Column("video_confirmed_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(
            ["video_confirmed_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("mosque_id"),
    )
    op.create_table(
        "added_subtitles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("khutba_id", sa.Integer(), nullable=False),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("end", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["khutba_id"],
            ["khutbas.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "clips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("khutba_id", sa.Integer(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("why", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("start", sa.REAL(), nullable=False),
        sa.Column("end", sa.REAL(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("video_source", sa.Text(), nullable=True),
        sa.Column("source_offset", sa.REAL(), nullable=True),
        sa.Column("crop", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            sa.CheckConstraint("status IN ('a_valider', 'valide', 'rejete', 'publie')"),
            server_default=sa.text("'a_valider'"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("needs_regen", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("regen_state", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("regen_error", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column(
            "origin",
            sa.Text(),
            sa.CheckConstraint("origin IN ('ia', 'manuel')"),
            server_default=sa.text("'ia'"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("bounds_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["bounds_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["khutba_id"],
            ["khutbas.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("khutba_id", "idx"),
    )
    with op.batch_alter_table("clips", schema=None) as batch_op:
        batch_op.create_index("clips_mosque", ["mosque_id", "status"], unique=False)

    op.create_table(
        "corrections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("khutba_id", sa.Integer(), nullable=False),
        sa.Column("seg_index", sa.Integer(), nullable=False),
        sa.Column("field", sa.Text(), sa.CheckConstraint("field IN ('text', 'fr')"), nullable=False),
        sa.Column("original", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["khutba_id"],
            ["khutbas.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("khutba_id", "seg_index", "field"),
    )
    op.create_table(
        "device_pairings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_code_hash", sa.Text(), nullable=False),
        sa.Column("user_code_hash", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            sa.CheckConstraint("status IN ('pending', 'approved', 'claimed')"),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("mosque_id", sa.Integer(), nullable=True),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.Float(), nullable=True),
        sa.Column("claimed_at", sa.Float(), nullable=True),
        sa.Column("suggested_name", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_code_hash"),
    )
    op.create_table(
        "habillages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("khutba_id", sa.Integer(), nullable=False),
        sa.Column("options", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            sa.CheckConstraint("status IN ('', 'en_cours', 'pret', 'echec')"),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("progress", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("file_path", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("preview_at", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("finished_at", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["khutba_id"],
            ["khutbas.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("khutba_id"),
    )
    op.create_table(
        "setup_leases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("since", sa.Float(), nullable=False),
        sa.Column("until", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mosque_id"),
    )
    op.create_table(
        "studio_claims",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), sa.CheckConstraint("source IN ('device', 'obs', 'regie')"), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("since", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mosque_id"),
    )
    op.create_table(
        "studio_incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("slot_key", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("open_key", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("opened_at", sa.Float(), nullable=False),
        sa.Column("resolved_at", sa.Float(), nullable=True),
        sa.Column("mailed_at", sa.Float(), nullable=True),
        sa.Column("mail_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("resolved_mailed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("open_key"),
    )
    with op.batch_alter_table("studio_incidents", schema=None) as batch_op:
        batch_op.create_index("studio_incidents_mosque", ["mosque_id", "resolved_at"], unique=False)

    op.create_table(
        "studio_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column(
            "origin", sa.Text(), sa.CheckConstraint("origin IN ('manual', 'slot_stop', 'announce')"), nullable=False
        ),
        sa.Column("kind", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("title", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("slot_key", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("ended_at", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("studio_runs", schema=None) as batch_op:
        batch_op.create_index("studio_runs_mosque", ["mosque_id", "started_at"], unique=False)

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("sermon_id", sa.Integer(), nullable=False),
        sa.Column("seg_index", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), server_default=sa.text("'transcript'"), nullable=False),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("end", sa.Float(), nullable=False),
        sa.Column("lang", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("norm", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("tsv", sa.Text().with_variant(postgresql.TSVECTOR(), "postgresql"), nullable=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(["sermon_id"], ["khutbas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transcript_segments", schema=None) as batch_op:
        batch_op.create_index("transcript_segments_mosque", ["mosque_id"], unique=False)
        batch_op.create_index("transcript_segments_sermon", ["sermon_id", "seg_index"], unique=False)
    # full-text and vector side of the search, outside the models: FTS5 + triggers / GIN, unaccent, pgvector
    models.create_search_extras(op.get_bind())

    op.create_table(
        "verse_citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("sermon_id", sa.Integer(), nullable=False),
        sa.Column("surah", sa.Integer(), nullable=False),
        sa.Column("ayah", sa.Integer(), nullable=False),
        sa.Column("t", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(["sermon_id"], ["khutbas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("verse_citations", schema=None) as batch_op:
        batch_op.create_index("verse_citations_ref", ["mosque_id", "surah", "ayah"], unique=False)
        batch_op.create_index("verse_citations_sermon", ["sermon_id"], unique=False)

    op.create_table(
        "publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mosque_id", sa.Integer(), nullable=False),
        sa.Column("clip_id", sa.Integer(), nullable=False),
        sa.Column("clip_version", sa.Integer(), nullable=False),
        sa.Column("connector", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), sa.CheckConstraint("status IN ('publie', 'refuse', 'erreur')"), nullable=False),
        sa.Column("location", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("caption", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("message", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["clip_id"],
            ["clips.id"],
        ),
        sa.ForeignKeyConstraint(
            ["mosque_id"],
            ["mosques.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    raise NotImplementedError("the baseline is not undone: restore a backup instead")
