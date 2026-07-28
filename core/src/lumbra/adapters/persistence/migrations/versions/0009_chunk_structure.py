"""Estrutura do chunk (issue #10, ADR-051).

O chunking ciente de estrutura precisa carimbar cada chunk com a seção a
que pertence, o tipo de bloco (tabela vs prosa) e a página. Colunas
nuláveis: chunks já indexados (prosa/legado) ficam nulos e são tratados
como chunk sem seção pela recuperação — reindexar preenche.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("section_path", sa.Text, nullable=True))
    op.add_column("chunks", sa.Column("block_type", sa.Text, nullable=True))
    op.add_column("chunks", sa.Column("page", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "page")
    op.drop_column("chunks", "block_type")
    op.drop_column("chunks", "section_path")
