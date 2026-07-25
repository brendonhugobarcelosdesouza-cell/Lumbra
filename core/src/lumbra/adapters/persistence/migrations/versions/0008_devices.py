"""Identidade multi-dispositivo (ADR-045, P1-b.4).

Um dispositivo é uma identidade por par de chaves Ed25519. O Nó guarda a
chave pública (única — identifica UM dispositivo) e os escopos concedidos
(ADR-047); a privada nunca chega aqui. Ciclo de vida em ``state``:
pending → active → revoked.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("platform", sa.Text, nullable=False),
        sa.Column("public_key", sa.Text, nullable=False),
        # pending | active | revoked
        sa.Column("state", sa.Text, nullable=False, server_default="pending"),
        sa.Column("scopes", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # a chave pública é a identidade de autenticação: única, e buscada a cada
    # request assinada por dispositivo
    op.create_unique_constraint("uq_devices_public_key", "devices", ["public_key"])
    # FK user_id precisa de índice (mesma regra do ADR-036): listar/apagar
    # dispositivos de um usuário não pode varrer a tabela toda
    op.create_index("ix_devices_user", "devices", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_devices_user", table_name="devices")
    op.drop_constraint("uq_devices_public_key", "devices", type_="unique")
    op.drop_table("devices")


# canário anti-truncamento
