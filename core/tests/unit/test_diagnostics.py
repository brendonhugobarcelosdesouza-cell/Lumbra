"""Diagnóstico: o contrato é 'todo problema vem com instrução de correção'.

Um diagnóstico sem conserto só transfere o problema para quem menos sabe
resolvê-lo. Estes testes travam essa promessa.
"""

import sys

import pytest
from pydantic import SecretStr

from lumbra.diagnostics import checks
from lumbra.diagnostics.checks import Status
from lumbra.shared.config import (
    AISettings,
    DatabaseSettings,
    SecuritySettings,
    Settings,
    StorageSettings,
)


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


class TestContratoDosResultados:
    async def test_todo_problema_traz_como_corrigir(self, tmp_path):
        """A regra que dá valor ao doctor: WARN e FAIL sem 'fix' são bugs."""
        resultados = await checks.executar(
            _settings(storage=StorageSettings(attachments_dir=str(tmp_path)))
        )
        sem_conserto = [
            r.name for r in resultados if r.status in (Status.WARN, Status.FAIL) and not r.fix
        ]
        assert sem_conserto == [], f"verificações sem instrução de correção: {sem_conserto}"

    async def test_nenhuma_verificacao_derruba_o_diagnostico(self, tmp_path):
        """O diagnóstico é o que roda quando tudo está quebrado — ele
        mesmo nunca pode ser a coisa que explode."""

        async def explode(_s):
            raise RuntimeError("provedor em chamas")

        resultados = await checks.executar(
            _settings(storage=StorageSettings(attachments_dir=str(tmp_path))),
            apenas=(explode,),
        )
        assert len(resultados) == 1
        assert resultados[0].status is Status.FAIL
        assert "chamas" in (resultados[0].detail or "")

    async def test_verificacao_travada_vira_falha_e_nao_pendura(self, tmp_path):
        import asyncio

        async def pendura(_s):
            await asyncio.sleep(3600)

        original = checks.asyncio.wait_for

        async def wait_for_rapido(coro, timeout):  # acelera o teste
            return await original(coro, 0.05)

        checks.asyncio.wait_for = wait_for_rapido  # type: ignore[assignment]
        try:
            resultados = await checks.executar(
                _settings(storage=StorageSettings(attachments_dir=str(tmp_path))),
                apenas=(pendura,),
            )
        finally:
            checks.asyncio.wait_for = original  # type: ignore[assignment]
        assert resultados[0].status is Status.FAIL
        assert "demorou" in resultados[0].summary

    def test_avisos_nao_impedem_o_uso(self):
        resultados = [
            checks.CheckResult("a", Status.OK, "ok"),
            checks.CheckResult("b", Status.WARN, "limitado", fix="opcional"),
            checks.CheckResult("c", Status.SKIP, "n/a"),
        ]
        assert checks.tudo_pronto(resultados) is True
        resultados.append(checks.CheckResult("d", Status.FAIL, "quebrado", fix="conserte"))
        assert checks.tudo_pronto(resultados) is False


class TestVerificacoesIndividuais:
    async def test_python_atual_passa(self):
        assert (await checks.check_python(_settings())).status is Status.OK

    async def test_dependencias_presentes(self):
        assert (await checks.check_dependencias(_settings())).status is Status.OK

    async def test_segredo_padrao_em_producao_e_falha(self):
        resultado = await checks.check_variaveis(_settings(environment="production"))
        assert resultado.status is Status.FAIL
        assert "forjar" in (resultado.detail or "")
        assert "JWT_SECRET" in (resultado.fix or "")

    async def test_segredo_padrao_em_dev_e_apenas_aviso(self):
        resultado = await checks.check_variaveis(_settings(environment="local"))
        assert resultado.status is Status.WARN

    async def test_segredo_proprio_passa(self):
        resultado = await checks.check_variaveis(
            _settings(
                environment="production",
                security=SecuritySettings(jwt_secret=SecretStr("x" * 48)),
            )
        )
        assert resultado.status is Status.OK

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="chmod POSIX não restringe escrita em diretório no Windows (usa ACLs)",
    )
    async def test_pasta_sem_permissao_e_falha(self, tmp_path):
        alvo = tmp_path / "sem-permissao"
        alvo.mkdir()
        alvo.chmod(0o500)  # leitura e execução, sem escrita
        try:
            resultado = await checks.check_permissoes(
                _settings(storage=StorageSettings(attachments_dir=str(alvo / "sub")))
            )
            assert resultado.status is Status.FAIL
            assert str(alvo) in (resultado.fix or "")
        finally:
            alvo.chmod(0o700)

    async def test_persistencia_em_memoria_avisa_sobre_perda(self):
        resultado = await checks.check_postgres(_settings(persistence="memory"))
        assert resultado.status is Status.WARN
        assert "reinícios" in resultado.summary

    async def test_embutido_e_diagnosticado_como_banco_de_verdade(self):
        """A regressão que este teste tranca: no modo embedded o diagnóstico
        dizia "persistência em memória — nada é salvo", que é falso e
        assustador. Os três checks de banco comparavam com "postgres" e não
        conheciam o modo novo."""
        resultado = await checks.check_postgres(
            _settings(
                persistence="embedded",
                database=DatabaseSettings(
                    dsn=SecretStr("postgresql+asyncpg://ninguem@127.0.0.1:1/nada")
                ),
            )
        )
        assert resultado.status is Status.FAIL  # tentou conectar, não deu de ombros
        assert "memória" not in resultado.summary

    async def test_banco_inacessivel_explica_o_que_fazer(self):
        resultado = await checks.check_postgres(
            _settings(
                persistence="postgres",
                database=DatabaseSettings(
                    dsn=SecretStr("postgresql+asyncpg://ninguem@127.0.0.1:1/nada")
                ),
            )
        )
        assert resultado.status is Status.FAIL
        assert "lumbra dev" in (resultado.fix or "")

    async def test_ollama_ausente_ensina_a_instalar(self):
        resultado = await checks.check_ollama(
            _settings(ai=AISettings(ollama_base_url="http://127.0.0.1:1"))
        )
        assert resultado.status is Status.FAIL
        assert "ollama pull" in (resultado.fix or "")

    async def test_nuvem_ausente_e_skip_e_nao_problema(self):
        """Rodar 100% local é uma escolha legítima, não uma pendência."""
        resultado = await checks.check_provedor_nuvem(_settings())
        assert resultado.status is Status.SKIP

    async def test_nuvem_configurada_deixa_claro_quando_e_usada(self):
        resultado = await checks.check_provedor_nuvem(
            _settings(ai=AISettings(anthropic_api_key=SecretStr("sk-teste")))
        )
        assert resultado.status is Status.OK
        assert "allow_cloud" in (resultado.detail or "")

    async def test_resultado_nunca_expoe_segredo(self):
        """A página de saúde é pública: não pode vazar chave nem DSN."""
        settings = _settings(
            ai=AISettings(anthropic_api_key=SecretStr("sk-ant-super-secreta")),
            security=SecuritySettings(jwt_secret=SecretStr("segredo-de-producao-123")),
        )
        resultados = await checks.executar(settings)
        texto = " ".join(f"{r.summary} {r.detail} {r.fix} {r.data}" for r in resultados)
        assert "sk-ant-super-secreta" not in texto
        assert "segredo-de-producao-123" not in texto


class TestCLI:
    def test_parser_exige_subcomando(self):
        from lumbra.cli.main import construir_parser

        with pytest.raises(SystemExit):
            construir_parser().parse_args([])

    @pytest.mark.parametrize("comando", ["doctor", "dev", "up", "init", "version"])
    def test_comandos_documentados_existem(self, comando):
        from lumbra.cli.main import construir_parser

        args = construir_parser().parse_args([comando])
        assert hasattr(args, "func")

    def test_versao_reportada(self):
        assert checks.versao_da_plataforma()


# canário anti-truncamento
