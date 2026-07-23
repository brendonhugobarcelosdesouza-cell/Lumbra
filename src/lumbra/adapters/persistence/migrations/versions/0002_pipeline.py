"""Pipeline resiliente e versionamento de documentos (ADR-020).

* documents: identidade lógica passa a ser (user, source, uri); ganha
  version, reindex_reason, processing_state e error.
* document_versions: histórico completo (hash, parent, motivo, datas).
* document_timeline: observabilidade por estágio (req. 8).
* document_processing: contexto persistido para retomada exata (req. 1).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ux_documents_user_uri_hash", "documents", type_="unique")
    op.create_unique_constraint(
        "ux_documents_user_source_uri", "documents", ["user_id", "source", "uri"]
    )
    op.add_column(
        "documents",
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
    )
    op.add_column("documents", sa.Column("reindex_reason", sa.Text, nullable=True))
    op.add_column(
        "documents",
        sa.Column("processing_state", sa.Text, nullable=False, server_default=sa.text("'pending'")),
    )
    op.add_column("documents", sa.Column("error", sa.Text, nullable=True))
    op.create_index("ix_documents_state", "documents", ["processing_state"])

    op.create_table(
        "document_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("parent_version", sa.Integer, nullable=True),
        sa.Column("content_hash", sa.LargeBinary, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("document_id", "version", name="ux_document_versions"),
    )

    op.create_table(
        "document_timeline",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Float, nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("message", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("metrics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_timeline_document", "document_timeline", ["document_id", "started_at"])

    op.create_table(
        "document_processing",
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("context", JSONB, nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("document_processing")
    op.drop_table("document_timeline")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_state", "documents")
    op.drop_column("documents", "error")
    op.drop_column("documents", "processing_state")
    op.drop_column("documents", "reindex_reason")
    op.drop_column("documents", "version")
    op.drop_constraint("ux_documents_user_source_uri", "documents", type_="unique")
    op.create_unique_constraint(
        "ux_documents_user_uri_hash", "documents", ["user_id", "uri", "content_hash"]
    )
