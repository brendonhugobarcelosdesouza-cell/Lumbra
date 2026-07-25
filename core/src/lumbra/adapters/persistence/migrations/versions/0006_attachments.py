"""Anexos de conversa (E2-03).

Um anexo NÃO é uma entidade paralela ao documento: é um documento normal
(ingerido pelo mesmo pipeline, com os mesmos chunks e embeddings) com um
vínculo à conversa onde foi enviado. Assim, perguntar sobre um arquivo
recém-anexado e perguntar sobre um arquivo indexado há meses percorrem
exatamente o mesmo caminho.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("storage_uri", sa.Text, nullable=False),
        # estado da extração: pending | ready | unsupported | failed
        sa.Column("state", sa.Text, nullable=False, server_default="pending"),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("extracted_chars", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_chat_attachments_conversation", "chat_attachments", ["conversation_id", "created_at"]
    )
    # a mensagem que citou o anexo (preenchida quando o usuário pergunta)
    op.add_column("messages", sa.Column("attachment_ids", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "attachment_ids")
    op.drop_table("chat_attachments")


# canário anti-truncamento
