"""Memória em cinco camadas (E1-05/06; docs 08/09).

memory_items unifica as camadas em uma tabela com `kind` — as cinco
memórias compartilham embed/recall/decay (decisão do doc 08). Busca
híbrida igual à de chunks: HNSW (vetorial) + GIN/tsvector (léxica).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

KINDS = ("temporary", "episodic", "semantic", "procedural", "permanent")


def upgrade() -> None:
    op.create_table(
        "memory_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("importance", sa.Float, nullable=False, server_default=sa.text("0.5")),
        sa.Column("source_ref", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("access_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('temporary','episodic','semantic','procedural','permanent')",
            name="ck_memory_items_kind",
        ),
        sa.CheckConstraint(
            "importance >= 0 AND importance <= 1", name="ck_memory_items_importance"
        ),
    )
    op.execute("ALTER TABLE memory_items ADD COLUMN embedding vector(384)")
    op.execute(
        "ALTER TABLE memory_items ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('portuguese', content)) STORED"
    )
    op.create_index(
        "ix_memory_items_embedding",
        "memory_items",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_memory_items_tsv", "memory_items", ["tsv"], postgresql_using="gin")
    op.create_index("ix_memory_items_user_kind", "memory_items", ["user_id", "kind"])
    op.create_index("ix_memory_items_expires", "memory_items", ["expires_at"])


def downgrade() -> None:
    op.drop_table("memory_items")


# canário anti-truncamento
