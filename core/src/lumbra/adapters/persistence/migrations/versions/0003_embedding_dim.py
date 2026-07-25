"""Dimensão de embedding 768 → 384 (ADR-025).

O provedor local escolhido (paraphrase-multilingual-MiniLM-L12-v2, ONNX)
produz vetores de 384 dims — multilíngue (PT-BR), 0,22 GB, CPU-friendly.
Trocar de modelo no futuro = nova migração + reindexação (documentado).
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(384) USING NULL")
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768) USING NULL")
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
