"""Esquema inicial do E1: users, events_log, documents, chunks e knowledge graph.

Notas de projeto (doc 08):
* ``events_log`` nasce sem particionamento — partição mensal entra quando
  o volume justificar (operação expand/contract sem downtime).
* ``chunks.tsv`` é coluna gerada (portuguese) + índice GIN: metade léxica
  da busca híbrida. HNSW cobre a metade vetorial.
* unicidade de entidade por (user_id, kind, lower(name)) sustenta o
  upsert/merge do Knowledge Graph.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ux_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "events_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("causation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("producer", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_log_occurred_at", "events_log", ["occurred_at"])
    op.create_index("ix_events_log_type", "events_log", ["type"])
    op.create_index("ix_events_log_user", "events_log", ["user_id"])

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("uri", sa.Text, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=True),
        sa.Column("content_hash", sa.LargeBinary, nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("doc_kind", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expires_on", sa.Date, nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "uri", "content_hash", name="ux_documents_user_uri_hash"),
    )
    op.create_index("ix_documents_user", "documents", ["user_id"])
    op.create_index("ix_documents_expires_on", "documents", ["expires_on"])

    op.create_table(
        "chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "tsv",
            TSVECTOR,
            sa.Computed("to_tsvector('portuguese', text)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_chunks_document", "chunks", ["document_id"])
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("aliases", ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("attrs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence", sa.Float, nullable=False, server_default=sa.text("1.0")),
    )
    op.create_index(
        "ux_entities_user_kind_name",
        "entities",
        ["user_id", "kind", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "entity_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "from_id",
            UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_id",
            UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rel", sa.Text, nullable=False),
        sa.Column("attrs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_relations_from", "entity_relations", ["from_id"])
    op.create_index("ix_relations_to", "entity_relations", ["to_id"])

    op.create_table(
        "entity_mentions",
        sa.Column(
            "entity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "chunk_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    for table in (
        "entity_mentions",
        "entity_relations",
        "entities",
        "chunks",
        "documents",
        "events_log",
        "users",
    ):
        op.drop_table(table)
