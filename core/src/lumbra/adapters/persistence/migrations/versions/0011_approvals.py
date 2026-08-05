"""Fila de aprovações persistente (L2.2, ADR-063 revisado).

Correção por evidência, não por preferência: a fila era in-memory sob o
argumento de que confirmação humana é interação viva. No primeiro uso real o
Nó reiniciou entre listar o pedido e decidir, a fila evaporou, e a aprovação
virou um 404 sem explicação. Decisão pendente é estado do usuário — pertence
ao banco.

Índice parcial em (user_id) só para pendentes: a consulta quente é "o que
aguarda MINHA decisão", e o histórico de decididos cresce sem parar.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("risk_level", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        # o pedido original: aprovar e REEXECUTAR
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        # pending | approved | rejected
        sa.Column("state", sa.Text, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_approvals_user_pendentes",
        "approvals",
        ["user_id", "created_at"],
        postgresql_where=sa.text("state = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_user_pendentes", table_name="approvals")
    op.drop_table("approvals")


# canário anti-truncamento
