"""O Nó sabe subir o próprio Postgres (P2-f.1, ADR-069).

Estes são os testes que NÃO precisam do banco de verdade: a tradução da URI
e o endereço dos dados. O teste que sobe o servidor mesmo vive em
``tests/integration/test_embedded_server.py`` — separados de propósito,
porque este arquivo tem que rodar em qualquer máquina, em milissegundos.
"""

import os
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


class TestPadraoNaoAtropelaEscolha:
    """Padrão que sobrescreve configuração explícita não é padrão."""

    def test_variavel_de_ambiente_e_respeitada(self, monkeypatch):
        from lumbra.cli.main import _padrao

        monkeypatch.setenv("LUMBRA_PERSISTENCE", "memory")
        _padrao("LUMBRA_PERSISTENCE", "embedded")
        assert os.environ["LUMBRA_PERSISTENCE"] == "memory"

    def test_o_env_tambem_conta_como_escolha(self, monkeypatch, tmp_path):
        """O bug real: o ``.env`` não está em ``os.environ``, então
        ``setdefault`` não o via e o padrão do comando vencia. Com
        ``LUMBRA_ENVIRONMENT=local`` no arquivo, ``lumbra up`` subia em
        produção assim mesmo — e reprovava o segredo de desenvolvimento numa
        máquina que dizia, por escrito, não ser produção."""
        from lumbra.cli.main import _padrao

        monkeypatch.delenv("LUMBRA_ENVIRONMENT", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("LUMBRA_ENVIRONMENT=local\n", encoding="utf-8")
        _padrao("LUMBRA_ENVIRONMENT", "production")
        assert os.environ.get("LUMBRA_ENVIRONMENT") is None

    def test_sem_escolha_nenhuma_o_padrao_vale(self, monkeypatch, tmp_path):
        from lumbra.cli.main import _padrao

        monkeypatch.delenv("LUMBRA_PERSISTENCE", raising=False)
        monkeypatch.chdir(tmp_path)  # sem .env
        _padrao("LUMBRA_PERSISTENCE", "embedded")
        assert os.environ["LUMBRA_PERSISTENCE"] == "embedded"


class TestSegredoDaInstalacao:
    """ADR-070: cada instalação tem a própria chave de assinatura."""

    def test_a_chave_e_criada_uma_vez_e_reusada(self, monkeypatch, tmp_path):
        """Gerar uma chave nova a cada partida deslogaria o usuário toda vez
        que ele abrisse a Lumbra — sem nenhuma pista do porquê."""
        from lumbra.shared.segredo_local import segredo_desta_instalacao

        monkeypatch.setenv("LUMBRA_DATA_DIR", str(tmp_path))
        primeira = segredo_desta_instalacao()
        assert primeira == segredo_desta_instalacao()

    def test_duas_instalacoes_nao_compartilham_chave(self, monkeypatch, tmp_path):
        """O motivo de não afrouxar a checagem: uma chave conhecida em toda
        instalação é pior que não ter autenticação, porque parece que tem."""
        from lumbra.shared.segredo_local import segredo_desta_instalacao

        monkeypatch.setenv("LUMBRA_DATA_DIR", str(tmp_path / "a"))
        uma = segredo_desta_instalacao()
        monkeypatch.setenv("LUMBRA_DATA_DIR", str(tmp_path / "b"))
        outra = segredo_desta_instalacao()
        assert uma != outra

    def test_a_chave_nao_e_a_de_desenvolvimento(self, monkeypatch, tmp_path):
        from lumbra.shared.segredo_local import segredo_desta_instalacao

        monkeypatch.setenv("LUMBRA_DATA_DIR", str(tmp_path))
        gerada = segredo_desta_instalacao()
        assert "dev-only-insecure" not in gerada
        assert len(gerada) >= 32  # RFC 7518 para HS256


class TestModoDeExecucao:
    """`com_banco` existe para que 'quem subiu o Postgres' não vaze."""

    @pytest.mark.parametrize("modo", ["postgres", "embedded"])
    def test_os_dois_modos_com_banco_sao_indistinguiveis(self, modo):
        assert Settings(persistence=modo).com_banco is True

    def test_memoria_nao_tem_banco(self):
        assert Settings(persistence="memory").com_banco is False


# canário anti-truncamento
