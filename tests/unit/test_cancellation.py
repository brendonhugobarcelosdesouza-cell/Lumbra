"""O primitivo de cancelamento da plataforma (ADR-032).

Estes testes são a especificação executável do mecanismo: se algum deles
falhar, alguma operação longa da Lumbra ficará pendurada ou mentirá sobre
o próprio estado final.
"""

import asyncio

import pytest

from lumbra.shared.cancellation import (
    CancellationToken,
    CancelReason,
    OperationCancelledError,
    with_deadline,
)


class TestEstado:
    def test_nasce_ativo(self):
        token = CancellationToken(name="t")
        assert token.is_cancelled is False
        assert token.reason is None

    def test_cancelar_registra_quem_e_porque(self):
        token = CancellationToken(name="t")
        assert token.cancel(CancelReason.USER, requested_by="console") is True
        assert token.is_cancelled is True
        assert token.reason is CancelReason.USER
        assert token.requested_by == "console"
        assert token.requested_at is not None

    def test_primeiro_motivo_vence(self):
        """O motivo original explica a interrupção; os seguintes são efeito."""
        token = CancellationToken(name="t")
        token.cancel(CancelReason.USER, requested_by="usuário")
        assert token.cancel(CancelReason.TIMEOUT, requested_by="prazo") is False
        assert token.reason is CancelReason.USER

    def test_etapas_concluidas_sobrevivem_ao_cancelamento(self):
        token = CancellationToken(name="t")
        token.step("contexto reunido")
        token.step("prompt montado")
        token.cancel(CancelReason.USER, requested_by="usuário")
        assert token.completed_steps == ("contexto reunido", "prompt montado")

    def test_raise_if_cancelled(self):
        token = CancellationToken(name="t")
        token.step("etapa 1")
        token.raise_if_cancelled()  # não levanta
        token.cancel(CancelReason.POLICY, requested_by="orçamento")
        with pytest.raises(OperationCancelledError) as exc:
            token.raise_if_cancelled()
        assert exc.value.reason is CancelReason.POLICY
        assert exc.value.completed_steps == ("etapa 1",)


class TestPropagacao:
    def test_pai_cancela_filhos(self):
        pai = CancellationToken(name="pai")
        filho = pai.child("filho")
        neto = filho.child("neto")
        pai.cancel(CancelReason.SHUTDOWN, requested_by="kernel")
        assert filho.is_cancelled and neto.is_cancelled
        assert filho.reason is CancelReason.PARENT
        assert neto.reason is CancelReason.PARENT

    def test_filho_nao_cancela_pai(self):
        pai = CancellationToken(name="pai")
        filho = pai.child("filho")
        filho.cancel(CancelReason.USER, requested_by="usuário")
        assert pai.is_cancelled is False

    def test_filho_de_pai_cancelado_nasce_cancelado(self):
        pai = CancellationToken(name="pai")
        pai.cancel(CancelReason.SHUTDOWN, requested_by="kernel")
        filho = pai.child("tardio")
        assert filho.is_cancelled is True

    def test_callbacks_liberam_recursos(self):
        token = CancellationToken(name="t")
        liberados = []
        token.on_cancel(lambda _: liberados.append("conexão"))
        token.cancel(CancelReason.USER, requested_by="x")
        assert liberados == ["conexão"]

    def test_callback_tardio_dispara_na_hora(self):
        token = CancellationToken(name="t")
        token.cancel(CancelReason.USER, requested_by="x")
        chamado = []
        token.on_cancel(lambda _: chamado.append(1))
        assert chamado == [1]

    def test_callback_quebrado_nao_impede_os_outros(self):
        token = CancellationToken(name="t")
        ok = []

        def explode(_):
            raise RuntimeError("observador ruim")

        token.on_cancel(explode)
        token.on_cancel(lambda _: ok.append(1))
        token.cancel(CancelReason.USER, requested_by="x")
        assert ok == [1]


class TestGuard:
    async def test_deixa_terminar_quando_nao_cancelado(self):
        token = CancellationToken(name="t")

        async def trabalho():
            await asyncio.sleep(0.01)
            return 42

        assert await token.guard(trabalho()) == 42

    async def test_interrompe_e_aborta_a_tarefa(self):
        """Não basta parar de esperar: a tarefa precisa MORRER, senão o
        provedor continua ocupando GPU/rede."""
        token = CancellationToken(name="t")
        estado = {"limpou": False, "terminou": False}

        async def trabalho():
            try:
                await asyncio.sleep(5)
                estado["terminou"] = True
            except asyncio.CancelledError:
                estado["limpou"] = True  # finally do provedor roda
                raise

        async def cancelar():
            await asyncio.sleep(0.01)
            token.cancel(CancelReason.USER, requested_by="usuário")

        tarefa_cancelar = asyncio.create_task(cancelar())
        with pytest.raises(OperationCancelledError):
            await token.guard(trabalho())
        await asyncio.sleep(0)
        assert estado["limpou"] is True
        assert estado["terminou"] is False
        await tarefa_cancelar

    async def test_token_ja_cancelado_nem_comeca(self):
        token = CancellationToken(name="t")
        token.cancel(CancelReason.SHUTDOWN, requested_by="kernel")
        comecou = []

        async def trabalho():
            comecou.append(1)

        with pytest.raises(OperationCancelledError):
            await token.guard(trabalho())
        assert comecou == []

    async def test_erro_do_trabalho_passa_intacto(self):
        token = CancellationToken(name="t")

        async def quebra():
            raise ValueError("erro real")

        with pytest.raises(ValueError, match="erro real"):
            await token.guard(quebra())


class TestGuardStream:
    async def _fonte(self, marcador: dict):
        try:
            for i in range(100):
                await asyncio.sleep(0.005)
                yield i
        finally:
            marcador["fechou"] = True  # aclose → httpx fecha a conexão

    async def test_entrega_tudo_sem_cancelamento(self):
        token = CancellationToken(name="t")

        async def curta():
            for i in range(3):
                yield i

        assert [x async for x in token.guard_stream(curta())] == [0, 1, 2]

    async def test_fecha_a_fonte_ao_cancelar(self):
        token = CancellationToken(name="t")
        marcador = {"fechou": False}
        recebidos = []
        with pytest.raises(OperationCancelledError):
            async for item in token.guard_stream(self._fonte(marcador)):
                recebidos.append(item)
                if len(recebidos) == 3:
                    token.cancel(CancelReason.CLIENT_GONE, requested_by="navegador")
        assert marcador["fechou"] is True, "fonte não foi fechada — conexão vazaria"
        assert len(recebidos) == 3  # o que já chegou é aproveitável


class TestTimeout:
    async def test_prazo_cancela_com_motivo_proprio(self):
        token = CancellationToken(name="t")
        await with_deadline(token, 0.02, requested_by="teste")

        async def demorado():
            await asyncio.sleep(5)

        with pytest.raises(OperationCancelledError) as exc:
            await token.guard(demorado())
        assert exc.value.reason is CancelReason.TIMEOUT  # distinto de USER

    async def test_prazo_nao_dispara_se_terminar_antes(self):
        token = CancellationToken(name="t")
        tarefa = await with_deadline(token, 5, requested_by="teste")

        async def rapido():
            return "pronto"

        assert await token.guard(rapido()) == "pronto"
        tarefa.cancel()
        assert token.is_cancelled is False


class TestSnapshot:
    def test_snapshot_serializa_para_console_e_explain(self):
        token = CancellationToken(name="chat.send")
        token.step("contexto reunido")
        token.cancel(CancelReason.CLIENT_GONE, requested_by="navegador")
        s = token.snapshot()
        assert s["scope"] == "chat.send"
        # a chave NÃO pode se chamar "token": o redator de logs trata esse
        # nome como credencial e apagaria o dado de diagnóstico
        assert "token" not in s
        assert s["cancelled"] is True
        assert s["reason"] == "client_gone"
        assert s["requested_by"] == "navegador"
        assert s["completed_steps"] == ["contexto reunido"]
        assert s["requested_at"] is not None


# canário anti-truncamento
