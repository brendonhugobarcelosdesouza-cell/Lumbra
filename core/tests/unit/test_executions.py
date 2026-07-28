"""Testes do ExecutionTracker: sucesso, falha, cancelamento, rerun, eventos, export."""

import asyncio

import pytest

from lumbra.adapters.eventbus.in_memory import InMemoryEventBus
from lumbra.adapters.eventstore.in_memory import InMemoryEventStore
from lumbra.adapters.permissions.static import StaticPermissionAdapter
from lumbra.domain.events import EventRegistry
from lumbra.kernel.executions import ExecutionNotFoundError, ExecutionStatus, ExecutionTracker
from lumbra.kernel.kernel import LumbraKernel
from lumbra.ports.event_bus import ConsumerSpec
from lumbra.ports.skills import Skill, SkillContext, SkillInput, SkillManifest, SkillOutput
from lumbra.shared.ids import uuid7


class EchoInput(SkillInput):
    text: str = "oi"


class EchoOutput(SkillOutput):
    echoed: str


@pytest.fixture()
async def kernel_tracker():
    kernel = LumbraKernel(
        events=EventRegistry(),
        bus=InMemoryEventBus(),
        event_store=InMemoryEventStore(),
        permissions=StaticPermissionAdapter(default_allow=True),
    )
    tracker = ExecutionTracker(kernel)
    kernel.bus.register(
        ConsumerSpec(name="devconsole-observer", patterns=("*",), handler=tracker.on_event)
    )

    async def echo(payload: SkillInput, _ctx: SkillContext) -> EchoOutput:
        assert isinstance(payload, EchoInput)
        return EchoOutput(echoed=payload.text.upper())

    async def slow(payload: SkillInput, _ctx: SkillContext) -> EchoOutput:
        await asyncio.sleep(30)
        return EchoOutput(echoed="nunca")

    async def broken(payload: SkillInput, _ctx: SkillContext) -> EchoOutput:
        raise RuntimeError("quebrou de propósito")

    async def cooperative(payload: SkillInput, ctx: SkillContext) -> EchoOutput:
        """Skill bem-comportada: marca etapas e verifica o token."""
        assert ctx.cancellation is not None
        ctx.cancellation.step("preparou")
        for _ in range(200):
            ctx.cancellation.raise_if_cancelled()
            await asyncio.sleep(0.01)
        return EchoOutput(echoed="terminou")

    for name, handler in (
        ("test.echo", echo),
        ("test.slow", slow),
        ("test.broken", broken),
        ("test.cooperative", cooperative),
    ):
        await kernel.skills.register(
            Skill(
                manifest=SkillManifest(name=name, description=name, provider="test"),
                input_model=EchoInput,
                output_model=EchoOutput,
                handler=handler,
            )
        )
    await kernel.start()
    yield kernel, tracker
    await kernel.stop()


class TestExecutions:
    async def test_success_records_output_and_duration(self, kernel_tracker):
        _kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.echo", {"text": "olá"}, subject="dev", user_id=None)
        done = await tracker.wait(record.id)
        assert done.status is ExecutionStatus.COMPLETED
        assert done.output == {"echoed": "OLÁ"}
        assert done.duration_ms is not None
        assert tracker.history()[0].id == record.id

    async def test_execucao_raiz_nao_tem_pai(self, kernel_tracker):
        _kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.echo", {}, subject="dev", user_id=None)
        await tracker.wait(record.id)
        assert record.parent_execution_id is None

    async def test_execucao_filha_herda_correlacao_do_pai(self, kernel_tracker):
        """A0: a árvore de delegação compartilha um só correlation_id, e a
        filha aponta para o pai (parent_execution_id)."""
        _kernel, tracker = kernel_tracker
        pai = tracker.start_skill("test.echo", {"text": "pai"}, subject="dev", user_id=None)
        await tracker.wait(pai.id)
        filha = tracker.start_skill(
            "test.echo", {"text": "filha"}, subject="dev", user_id=None, parent_execution_id=pai.id
        )
        await tracker.wait(filha.id)
        assert filha.parent_execution_id == pai.id
        assert filha.correlation_id == pai.correlation_id  # árvore correlacionada
        assert filha.id != pai.id

    async def test_failure_captures_traceback(self, kernel_tracker):
        _kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.broken", {}, subject="dev", user_id=None)
        done = await tracker.wait(record.id)
        assert done.status is ExecutionStatus.FAILED
        assert "quebrou de propósito" in (done.error or "")
        assert "Traceback" in (done.error_detail or "")

    async def test_cancel_running_execution(self, kernel_tracker):
        _kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.slow", {}, subject="dev", user_id=None)
        await asyncio.sleep(0.05)
        assert tracker.cancel(record.id) is True
        done = await tracker.wait(record.id)
        assert done.status is ExecutionStatus.CANCELLED
        assert tracker.cancel(record.id) is False  # já terminou

    async def test_rerun_creates_new_execution_with_same_input(self, kernel_tracker):
        _kernel, tracker = kernel_tracker
        first = tracker.start_skill("test.echo", {"text": "de novo"}, subject="dev", user_id=None)
        await tracker.wait(first.id)
        second = tracker.rerun(first.id)
        done = await tracker.wait(second.id)
        assert second.id != first.id
        assert done.output == {"echoed": "DE NOVO"}

    async def test_events_correlated_to_execution(self, kernel_tracker):
        kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.echo", {"text": "x"}, subject="dev", user_id=None)
        await tracker.wait(record.id)
        await kernel.bus.drain()  # type: ignore[attr-defined]
        events = tracker.events_of(record.id)
        assert any(e.type == "skill.executed" for e in events)
        exported = tracker.export(record.id)
        assert exported["execution"]["name"] == "test.echo"
        assert len(exported["events"]) == len(events)

    async def test_unknown_execution(self, kernel_tracker):
        _kernel, tracker = kernel_tracker
        with pytest.raises(ExecutionNotFoundError):
            tracker.get(uuid7())


class TestCancelamentoCooperativo:
    """ADR-032: cancelar é uma garantia, não uma sugestão — mas quem
    coopera consegue registrar o que já havia feito."""

    async def test_skill_cooperativa_registra_motivo_e_etapas(self, kernel_tracker):
        _kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.cooperative", {}, subject="dev", user_id=None)
        await asyncio.sleep(0.05)
        assert tracker.cancel(record.id, requested_by="console:eu") is True
        done = await tracker.wait(record.id)
        assert done.status is ExecutionStatus.CANCELLED
        assert done.cancel_reason == "user"
        assert done.cancelled_by == "console:eu"
        assert done.completed_steps == ["preparou"]
        assert done.is_failure is False  # NÃO é falha

    async def test_skill_que_ignora_o_token_e_forcada(self, kernel_tracker):
        """Sem fallback forçado, 'cancelar' seria só um pedido educado."""
        _kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.slow", {}, subject="dev", user_id=None)
        await asyncio.sleep(0.05)
        assert tracker.cancel(record.id) is True
        done = await tracker.wait(record.id)
        assert done.status is ExecutionStatus.CANCELLED
        assert done.duration_ms is not None and done.duration_ms < 5_000

    async def test_timeout_tem_estado_proprio(self, kernel_tracker):
        _kernel, tracker = kernel_tracker
        record = tracker.start_skill(
            "test.cooperative", {}, subject="dev", user_id=None, timeout_seconds=0.05
        )
        done = await tracker.wait(record.id)
        assert done.status is ExecutionStatus.TIMEOUT  # distinto de CANCELLED
        assert done.cancel_reason == "timeout"
        assert done.is_failure is False

    async def test_falha_continua_sendo_falha(self, kernel_tracker):
        _kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.broken", {}, subject="dev", user_id=None)
        done = await tracker.wait(record.id)
        assert done.status is ExecutionStatus.FAILED
        assert done.is_failure is True
        assert done.cancel_reason is None

    async def test_cancelamento_e_explicado(self, kernel_tracker):
        kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.cooperative", {}, subject="dev", user_id=None)
        await asyncio.sleep(0.05)
        tracker.cancel(record.id, requested_by="console:eu")
        await tracker.wait(record.id)
        explicacoes = kernel.explain.query(component="execution_tracker")
        assert explicacoes, "cancelamento não foi explicado"
        ultima = explicacoes[-1]
        assert "cancelled" in ultima.decision
        assert "console:eu" in ultima.reason
        assert any("preparou" in c for c in ultima.consequences)
        assert any("liberados" in c for c in ultima.consequences)

    async def test_desligar_kernel_cancela_execucoes_em_voo(self, kernel_tracker):
        kernel, tracker = kernel_tracker
        record = tracker.start_skill("test.cooperative", {}, subject="dev", user_id=None)
        await asyncio.sleep(0.05)
        await kernel.stop()
        done = await tracker.wait(record.id)
        assert done.status is ExecutionStatus.CANCELLED
        assert done.cancel_reason == "parent"  # veio do token raiz


# canário anti-truncamento
