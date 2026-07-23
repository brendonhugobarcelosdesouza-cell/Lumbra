"""Índices em chaves estrangeiras que faltavam (consolidação).

Postgres NÃO cria índice automaticamente para FK. Sem eles, apagar um
documento ou um usuário faz varredura completa nas tabelas filhas para
verificar as referências — barato hoje, caro quando a base crescer.
Encontrados por auditoria (tests/integration/test_db_audit.py).
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_entity_mentions_chunk", "entity_mentions", ["chunk_id"])
    op.create_index("ix_chat_attachments_document", "chat_attachments", ["document_id"])
    op.create_index("ix_chat_attachments_user", "chat_attachments", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_attachments_user", "chat_attachments")
    op.drop_index("ix_chat_attachments_document", "chat_attachments")
    op.drop_index("ix_entity_mentions_chunk", "entity_mentions")


# canário anti-truncamento
