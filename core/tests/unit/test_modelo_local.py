"""Cache de modelo pela metade se cura sozinho (P2-f.3).

Encontrado empacotando: depois de o Nó ser morto no meio da primeira
partida, o download do modelo ficou incompleto. O ``fastembed`` seguiu com
os arquivos truncados e falhou muito depois, ao gerar o vetor — com um
"não foi possível gerar embeddings" que não menciona download nenhum. A
única pista era um aviso discreto sobre tamanhos que não batem.

Sem cura, a busca semântica fica quebrada PARA SEMPRE naquela instalação.
É a mesma armadilha do banco sujo, com outra roupa — e o conserto aqui é
barato, porque o cache é descartável por definição.
"""

import sys
import types
from pathlib import Path
from typing import ClassVar

from lumbra.adapters.ai.fastembed_local import FastEmbedProvider


class _FalsoTextEmbedding:
    """Falha na primeira tentativa (cache podre) e funciona na segunda."""

    tentativas = 0
    caches_vistos: ClassVar[list[str]] = []

    def __init__(self, modelo: str, cache_dir: str | None = None) -> None:
        type(self).tentativas += 1
        type(self).caches_vistos.append(cache_dir or "")
        if type(self).tentativas == 1:
            raise RuntimeError("Local file sizes do not match the metadata")


def _fingir_fastembed(monkeypatch) -> None:
    modulo = types.ModuleType("fastembed")
    modulo.TextEmbedding = _FalsoTextEmbedding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", modulo)
    _FalsoTextEmbedding.tentativas = 0
    _FalsoTextEmbedding.caches_vistos = []


class TestCachePelaMetade:
    def test_apaga_e_baixa_de_novo(self, monkeypatch, tmp_path):
        _fingir_fastembed(monkeypatch)
        cache = tmp_path / "modelos"
        cache.mkdir()
        (cache / "meio-arquivo.onnx").write_bytes(b"truncado")

        provedor = FastEmbedProvider("modelo-x", cache_dir=cache)
        provedor._load()

        assert _FalsoTextEmbedding.tentativas == 2, "não tentou de novo"
        assert not (cache / "meio-arquivo.onnx").exists(), "o cache podre ficou"

    def test_cache_bom_carrega_de_primeira(self, monkeypatch, tmp_path):
        """A cura não pode virar hábito: rebaixar 120 MB a cada partida seria
        pior que o problema."""
        _fingir_fastembed(monkeypatch)
        _FalsoTextEmbedding.tentativas = 1  # a próxima já dá certo

        provedor = FastEmbedProvider("modelo-x", cache_dir=tmp_path / "modelos")
        provedor._load()

        assert _FalsoTextEmbedding.tentativas == 2  # ou seja: só UMA aqui


class TestOndeOModeloMora:
    def test_sem_configuracao_vai_para_a_pasta_de_dados(self, monkeypatch, tmp_path):
        """O padrão do fastembed é um diretório TEMPORÁRIO — que o sistema
        apaga. Num aplicativo instalado, isso é rebaixar 120 MB pelas costas
        do usuário, sem explicação."""
        monkeypatch.setenv("LUMBRA_DATA_DIR", str(tmp_path))
        provedor = FastEmbedProvider("modelo-x")
        assert provedor._cache_dir == tmp_path / "modelos"

    def test_configuracao_explicita_vence(self, tmp_path):
        escolhida = tmp_path / "meu-lugar"
        assert FastEmbedProvider("modelo-x", cache_dir=escolhida)._cache_dir == escolhida

    def test_nunca_e_temporario_por_omissao(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LUMBRA_DATA_DIR", str(tmp_path))
        caminho = FastEmbedProvider("modelo-x")._cache_dir
        assert caminho is not None
        assert Path(caminho).is_absolute()


# canário anti-truncamento
