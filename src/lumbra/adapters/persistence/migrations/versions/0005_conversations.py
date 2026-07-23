"""Conversas, mensagens e citações (E2-01/E2-02; doc 08).

message_sources generaliza o DDL planejado: a citação aponta para
qualquer origem de contexto (documento OU memória), não só chunks —
o assistente cita memórias com o mesmo rigor com que cita documentos.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("model_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_conversations_user", "conversations", ["user_id", "created_at"])

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=True),
        sa.Column("tokens_out", sa.Integer, nullable=True),
        sa.Column("provider", sa.Text, nullable=True),
        sa.Column("model", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user','assistant','system','tool')", name="ck_messages_role"),
    )
    op.create_index("ix_messages_conversation", "messages", ["conversation_id", "created_at"])

    op.create_table(
        "message_sources",
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ordinal", sa.Integer, primary_key=True),  # [1], [2]... na resposta
        sa.Column("kind", sa.Text, nullable=False),  # document | memory
        sa.Column("ref_id", UUID(as_uuid=True), nullable=False),  # chunk_id ou memory_id
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("uri", sa.Text, nullable=True),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("snippet", sa.Text, nullable=True),
        sa.CheckConstraint("kind IN ('document','memory')", name="ck_message_sources_kind"),
    )


def downgrade() -> None:
    op.drop_table("message_sources")
    op.drop_table("messages")
    op.drop_table("conversations")


# canário anti-truncamento
