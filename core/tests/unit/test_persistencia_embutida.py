"""O Nó sabe subir o próprio Postgres (P2-f.1, ADR-069).

Estes são os testes que NÃO precisam do banco de verdade: a tradução da URI
e o endereço dos dados. O teste que sobe o servidor mesmo vive em
``tests/integration/test_embedded_server.py`` — separados de propósito,
porque este arquivo tem que rodar em qualquer máquina, em milissegundos.
"""

from pathlib import Path

import pytest

from lumbra.adapters.persistence.embedded import preparar_banco, traduzir_uri
from lumbra.shared import paths
from lumbra.shared.config import DatabaseSettings, Settings


class TestTraduzirUri:
    def test_socket_unix_vira_parametro_host(self):
        """Linux/macOS: o servidor escuta num socket, não numa porta.

        É uma propriedade de privacidade, não um detalhe: o banco pessoal
        não fica alcançável pela rede nem por engano.
        """
        uri = "postgresql://postgres:@/postgres?host=/tmp/lumbra-pg"
        assert traduzir_uri(uri) == "postgresql+asyncpg://postgres@/postgres?host=/tmp/lumbra-pg"

    def test_windows_troca_apenas_o_driver(self):
        """Windows não tem socket Unix: sobra TCP local, e só o driver muda."""
        uri = "postgresql://postgres@127.0.0.1:5433/postgres"
        assert traduzir_uri(uri) == "postgresql+asyncpg://postgres@127.0.0.1:5433/postgres"


class TestOndeMoramOsDados:
    def test_variavel_de_ambiente_vence(self, monkeypatch, tmp_path):
        """Quem é dono dos dados escolhe onde eles ficam — disco externo,
        volume cifrado, pasta sincronizada. Não é decisão nossa."""
        monkeypatch.setenv("LUMBRA_DATA_DIR", str(tmp_path / "meus-dados"))
        assert paths.pasta_de_dados() == tmp_path / "meus-dados"

    def test_sem_variavel_cai_na_convencao_do_sistema(self, monkeypatch):
        monkeypatch.delenv("LUMBRA_DATA_DIR", raising=False)
        pasta = paths.pasta_de_dados()
        assert pasta.is_absolute()
        # nunca no diretório atual: instalado, o "diretório atual" é a pasta
        # de onde o atalho foi clicado, e os dados sumiriam de vista
        assert pasta != Path.cwd()

    def test_o_banco_fica_dentro_da_pasta_de_dados(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LUMBRA_DATA_DIR", str(tmp_path))
        assert paths.pasta_do_banco().parent == tmp_path


class TestPrepararBanco:
    def test_sem_embutido_devolve_o_dsn_configurado_e_nenhum_servidor(self):
        """Modo 'postgres': alguém já subiu o banco, e não encostamos nele."""
        cfg = DatabaseSettings()
        dsn, servidor = preparar_banco(cfg, embutido=False)
        assert dsn == cfg.dsn.get_secret_value()
        assert servidor is None


class TestOndeEstaoAsMigracoes:
    def test_o_caminho_nao_depende_do_diretorio_atual(self, monkeypatch, tmp_path):
        """`lumbra up` da raiz do monorepo falhava com "Path doesn't exist:
        src\\lumbra\\adapters\\persistence\\migrations".

        O ``script_location`` do alembic.ini é relativo e o Alembic o resolve
        contra o diretório ATUAL. Instalado seria pior: não existe ``core/``,
        e o diretório atual é a pasta de onde o atalho foi clicado.
        """
        from lumbra.cli.main import _config_alembic

        monkeypatch.chdir(tmp_path)  # o pior caso: um diretório sem nada
        destino = Path(_config_alembic().get_main_option("script_location") or "")
        assert destino.is_absolute()
        assert (destino / "versions").is_dir()


class TestModoDeExecucao:
    """`com_banco` existe para que 'quem subiu o Postgres' não vaze."""

    @pytest.mark.parametrize("modo", ["postgres", "embedded"])
    def test_os_dois_modos_com_banco_sao_indistinguiveis(self, modo):
        assert Settings(persistence=modo).com_banco is True

    def test_memoria_nao_tem_banco(self):
        assert Settings(persistence="memory").com_banco is False


# canário anti-truncamento
