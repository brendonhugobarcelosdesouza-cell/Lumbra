"""BlobStore em disco: nome de arquivo do usuário é entrada NÃO confiável."""

from pathlib import Path
from uuid import uuid4

import pytest

from lumbra.adapters.attachments.filesystem import FilesystemBlobStore, _sanitize


class TestConstrucaoSemEfeito:
    def test_construir_nao_cria_diretorio(self, tmp_path):
        """Instanciar um adapter não pode ter efeito no filesystem: o Nó sobe
        em modo memória e não deve escrever em disco no boot (regressão do
        crash do container no P1-b.1)."""
        raiz = tmp_path / "nao-deve-existir"
        FilesystemBlobStore(raiz)
        assert not raiz.exists()

    async def test_save_cria_diretorio_sob_demanda(self, tmp_path):
        store = FilesystemBlobStore(tmp_path / "blobs")
        uri = await store.save(b"conteudo", filename="a.txt", owner=uuid4())
        assert (await store.read(uri)) == b"conteudo"


class TestSanitizacao:
    @pytest.mark.parametrize(
        ("entrada", "esperado_nao_contem"),
        [
            ("../../etc/passwd", ".."),
            ("/etc/shadow", "/"),
            ("..\\..\\windows\\system32", "\\"),
            ("nome com espaço.txt", " "),
        ],
    )
    def test_remove_travessia_e_separadores(self, entrada, esperado_nao_contem):
        assert esperado_nao_contem not in _sanitize(entrada)

    def test_preserva_nome_legivel(self):
        assert _sanitize("contrato-2026.pdf") == "contrato-2026.pdf"

    def test_nome_vazio_vira_padrao(self):
        assert _sanitize("...") == "arquivo"

    def test_limita_tamanho(self):
        assert len(_sanitize("a" * 500 + ".pdf")) <= 120


class TestArmazenamento:
    async def test_salva_e_le(self, tmp_path: Path):
        store = FilesystemBlobStore(tmp_path)
        dono = uuid4()
        uri = await store.save(b"conteudo", filename="nota.txt", owner=dono)
        assert uri.startswith("file://")
        assert await store.read(uri) == b"conteudo"

    async def test_separa_por_dono(self, tmp_path: Path):
        store = FilesystemBlobStore(tmp_path)
        a, b = uuid4(), uuid4()
        uri_a = await store.save(b"de a", filename="x.txt", owner=a)
        uri_b = await store.save(b"de b", filename="x.txt", owner=b)
        assert uri_a != uri_b
        assert str(a) in uri_a and str(b) in uri_b

    async def test_recusa_leitura_fora_da_raiz(self, tmp_path: Path):
        """Mesmo com uma URI forjada, não se lê fora do armazenamento."""
        store = FilesystemBlobStore(tmp_path / "blobs")
        fora = tmp_path / "segredo.txt"
        fora.write_text("nao deveria vazar", encoding="utf-8")
        with pytest.raises(PermissionError):
            await store.read(fora.resolve().as_uri())

    async def test_apagar_e_idempotente(self, tmp_path: Path):
        store = FilesystemBlobStore(tmp_path)
        uri = await store.save(b"x", filename="a.txt", owner=uuid4())
        await store.delete(uri)
        await store.delete(uri)  # não explode


# canário anti-truncamento
