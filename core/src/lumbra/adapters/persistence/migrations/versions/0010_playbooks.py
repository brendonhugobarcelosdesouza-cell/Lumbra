"""Playbooks — memória procedural persistente (L1.6, ADR-061).

Até aqui os procedimentos viviam só em memória: reiniciar o Nó apagava o que
a plataforma tinha aprendido a fazer. Conhecimento procedural que evapora não
é conhecimento — é anotação.

O ``tsv`` é gerado e PONDERADO (peso A para título/quando-usar, B para o
corpo): é o 'quando usar' que decide a recuperação, e o ts_rank já sabe
respeitar peso. Coluna gerada em vez de trigger porque a expressão é imutável
e o banco mantém a consistência sozinho.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

from lumbra.adapters.persistence.models import PLAYBOOK_TSV_EXPR

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playbooks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("when_to_use", sa.Text, nullable=False),
        sa.Column("steps", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("pitfalls", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("verification", sa.Text, nullable=False, server_default=""),
        # user | agent | imported — proveniência muda o quanto se confia
        sa.Column("origin", sa.Text, nullable=False, server_default="user"),
        # rastreabilidade até a execução que originou o procedimento (ADR-059)
        sa.Column("source_execution_id", UUID(as_uuid=True), nullable=True),
        sa.Column("uses", sa.Integer, nullable=False, server_default="0"),
        # projeção de busca: passos + armadilhas achatados em texto. Existe
        # porque array_to_string é STABLE e o Postgres recusa coluna gerada
        # com expressão não-imutável — e porque playbook não é editado, só
        # criado e apagado, então a projeção não tem como divergir.
        sa.Column("search_body", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "tsv",
            TSVECTOR,
            sa.Computed(PLAYBOOK_TSV_EXPR, persisted=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # FK user_id indexada (ADR-036): listar procedimentos de um usuário não
    # pode varrer a tabela
    op.create_index("ix_playbooks_user", "playbooks", ["user_id"])
    op.create_index("ix_playbooks_tsv", "playbooks", ["tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_playbooks_tsv", table_name="playbooks")
    op.drop_index("ix_playbooks_user", table_name="playbooks")
    op.drop_table("playbooks")


# canário anti-truncamento
