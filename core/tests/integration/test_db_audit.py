"""Guarda-corpo de esquema: toda FK precisa de índice.

Postgres não cria índice de FK automaticamente, e a falta só aparece em
produção — quando apagar um usuário começa a varrer tabelas inteiras.
Este teste falha na hora em que alguém adicionar uma FK sem índice.
"""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


async def test_toda_fk_tem_indice(db):
    async with db.session() as s:
        idx = (
            await s.execute(
                text(
                    "SELECT tablename, indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname='public' ORDER BY tablename, indexname"
                )
            )
        ).all()
        assert idx, "nenhum índice encontrado — migrações não rodaram?"

        faltando = (
            await s.execute(
                text("""
                SELECT c.conrelid::regclass AS tabela,
                       a.attname AS coluna
                FROM pg_constraint c
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                WHERE c.contype = 'f'
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_index i
                      WHERE i.indrelid = c.conrelid
                        AND a.attnum = i.indkey[0]
                  )
                ORDER BY 1, 2
                """)
            )
        ).all()
    sem_indice = [f"{tabela}.{coluna}" for tabela, coluna in faltando]
    assert sem_indice == [], (
        "chaves estrangeiras sem índice (apagar o pai varre a tabela filha): "
        + ", ".join(sem_indice)
    )


async def test_indices_vetoriais_e_lexicais_existem(db):
    """HNSW e GIN são o que tornam a busca híbrida viável — se sumirem,
    a busca continua 'funcionando', só que lenta."""
    async with db.session() as s:
        idx = (
            await s.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public'")
            )
        ).all()
    defs = {nome: ddl.lower() for nome, ddl in idx}
    assert "hnsw" in defs.get("ix_chunks_embedding", "")
    assert "gin" in defs.get("ix_chunks_tsv", "")
    assert "hnsw" in defs.get("ix_memory_items_embedding", "")
    assert "gin" in defs.get("ix_memory_items_tsv", "")
