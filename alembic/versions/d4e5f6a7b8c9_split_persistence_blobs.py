"""split_persistence_blobs

Splits the legacy single-row user_data and chat_data blobs into per-key
rows. After this migration, each user and chat has its own row keyed as
'user_data:{id}' and 'chat_data:{id}' respectively. Concurrent writes
from different users now touch disjoint rows, eliminating the
read-modify-write race that the single-blob design had under simultaneous
check-ins.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-31 00:00:01.000000

"""

from collections.abc import Sequence
import json
import re

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import structlog

from alembic import op

logger = structlog.get_logger()

# Stricter than int(): rejects int("1_0")==10, int(" 7 ")==7, int("+5")==5.
# Both the original string and the per-ID row suffix must be identical so
# _load_prefixed's int(suffix) yields the same Telegram ID without aliasing.
_INTEGER_PATTERN = re.compile(r"-?[0-9]+")

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLAlchemy's :param::type syntax is not portable across dialects because the
# compile-time BIND_PARAMS regex misparses the trailing ::, silently dropping
# the bind value before it reaches PostgreSQL. bindparams() attaches the JSONB
# type annotation without embedding it in the SQL text, so the compiled form
# becomes %(data)s::JSONB and the value travels to the server intact.
_UPSERT = sa.text(
    "INSERT INTO bot_persistence (key, data, updated_at) "
    "VALUES (:key, :data, NOW()) "
    "ON CONFLICT (key) DO UPDATE SET data = :data, updated_at = NOW()"
).bindparams(sa.bindparam("data", type_=postgresql.JSONB()))


def _split_blob(conn, blob_key: str, prefix: str) -> None:
    """Read a legacy single-blob row and expand it into per-ID rows.

    Handles three cases: the table is empty (nothing to do), the blob row
    exists with valid data (split it), or the row is absent or malformed
    (skip without discarding anything - malformed rows are left in place
    so they can be inspected rather than silently destroyed).
    """
    row = conn.execute(
        sa.text("SELECT data FROM bot_persistence WHERE key = :key"),
        {"key": blob_key},
    ).fetchone()
    if row is None:
        logger.info("split_blob found no legacy blob to split", key=blob_key)
        return

    data = row[0]
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            # Malformed blob: leave the row intact rather than destroy state.
            # The application will not see it (LIKE 'prefix:%' does not match
            # the bare key), so this warrants an operator alert.
            logger.warning(
                "split_blob skipping malformed JSON blob - row left intact for inspection",
                key=blob_key,
            )
            return

    if not isinstance(data, dict):
        logger.warning(
            "split_blob skipping blob with unexpected type - row left intact for inspection",
            key=blob_key,
            observed_type=type(data).__name__,
        )
        return

    had_skips = False
    for item_id, item_data in data.items():
        if not _INTEGER_PATTERN.fullmatch(item_id):
            # The application calls int(suffix) on every row it loads, so a
            # non-integer key would crash Application.initialize(). Skipping
            # means this entry cannot be migrated; the source blob must stay in
            # place so the operator can recover it - do not delete below.
            logger.warning(
                "split_blob skipping non-integer key - source blob will be preserved",
                blob_key=blob_key,
                item_id=item_id,
            )
            had_skips = True
            continue
        conn.execute(
            _UPSERT,
            {"key": f"{prefix}:{item_id}", "data": item_data},
        )

    if had_skips:
        # Some entries could not be migrated; keep the source blob intact so
        # the operator can inspect and recover the skipped data.
        logger.warning(
            "split_blob preserved source blob because some keys were skipped",
            key=blob_key,
        )
    else:
        conn.execute(
            sa.text("DELETE FROM bot_persistence WHERE key = :key"),
            {"key": blob_key},
        )


def _merge_rows(conn, prefix: str, blob_key: str) -> None:
    """Collect per-ID rows and write them back as a single blob.

    This is the inverse of _split_blob: used by downgrade() to restore the
    old single-row layout so a rollback leaves data intact.
    """
    # Escape _ so LIKE treats it as a literal character, not a wildcard.
    escaped_prefix = prefix.replace("_", "!_")
    rows = conn.execute(
        sa.text("SELECT key, data FROM bot_persistence WHERE key LIKE :pattern ESCAPE '!'"),
        {"pattern": f"{escaped_prefix}:%"},
    ).fetchall()

    if not rows:
        return

    # upgrade() deliberately leaves a malformed blob in place rather than
    # destroying it. Read any existing row first so we can merge rather than
    # clobber: overwriting would discard the preserved original.
    existing = conn.execute(
        sa.text("SELECT data FROM bot_persistence WHERE key = :key"),
        {"key": blob_key},
    ).fetchone()

    blob: dict = {}
    if existing is not None:
        existing_data = existing[0]
        if isinstance(existing_data, str):
            try:
                existing_data = json.loads(existing_data)
            except json.JSONDecodeError:
                existing_data = None
        if isinstance(existing_data, dict):
            blob = existing_data
        else:
            # Cannot safely merge per-ID rows into a malformed blob without
            # destroying the original. Raise so the transaction rolls back and
            # Alembic does not stamp the revision - the operator sees a failure,
            # not a silent half-downgrade with exit code 0.
            raise RuntimeError(
                f"_merge_rows: existing blob at {blob_key!r} is malformed and cannot be "
                "safely merged; transaction will roll back."
            )

    # Per-ID rows are live post-upgrade data; the existing blob entry for the
    # same key is the stale pre-upgrade copy, so per-ID rows win on collision.
    for row in rows:
        key = row[0]
        suffix = key.split(":", 1)[1]
        data = row[1]
        blob[suffix] = json.loads(data) if isinstance(data, str) else data

    conn.execute(
        _UPSERT,
        {"key": blob_key, "data": blob},
    )

    conn.execute(
        sa.text("DELETE FROM bot_persistence WHERE key LIKE :pattern ESCAPE '!'"),
        {"pattern": f"{escaped_prefix}:%"},
    )


def upgrade() -> None:
    conn = op.get_bind()
    _split_blob(conn, "user_data", "user_data")
    _split_blob(conn, "chat_data", "chat_data")


def downgrade() -> None:
    conn = op.get_bind()
    _merge_rows(conn, "user_data", "user_data")
    _merge_rows(conn, "chat_data", "chat_data")
