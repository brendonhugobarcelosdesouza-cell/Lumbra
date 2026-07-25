"""Testes do PipelineRunner com fakes: resume, idempotência, timeline, falha."""

from uuid import UUID, uuid4

from lumbra.adapters.metrics.in_memory import InMemoryMetrics
from lumbra.domain.pipeline import (
    PipelineContext,
    PipelineError,
    ProcessingState,
    StageOutcome,
)
from lumbra.pipeline.runner import PipelineResolver, PipelineRunner, default_resolver
from lumbra.ports.document_store import DocumentRecord
from lumbra.ports.pipeline import (
    PipelineStagePort,
    ProcessingStorePort,
    StageInput,
    TimelineEntry,
)


class FakeProcessingStore(ProcessingStorePort):
    def __init__(self):
        self.states: dict[UUID, ProcessingState] = {}
        self.errors: dict[UUID, str | None] = {}
        self.contexts: dict[UUID, PipelineContext] = {}
        self.timeline: list[TimelineEntry] = []
        self.indexed: list[UUID] = []

    async def set_state(self, document_id, state, *, error=None):
        self.states[document_id] = state
        self.errors[document_id] = error

    async def get_state(self, document_id):
        return self.states.get(document_id, ProcessingState.PENDING)

    async def save_context(self, document_id, context):
        self.contexts[document_id] = context

    async def load_context(self, document_id):
        return self.contexts.get(document_id, PipelineContext())

    async def add_timeline(self, document_id, entry):
        self.timeline.append(entry)

    async def get_timeline(self, document_id):
        return self.timeline

    async def reset_context(self, document_id):
        self.contexts.pop(document_id, None)

    async def mark_indexed(self, document_id):
        self.indexed.append(document_id)


class CountingStage(PipelineStagePort):
    def __init__(self, name: str, state: ProcessingState, *, fail: bool = False):
        self._name, self._state, self.fail = name, state, fail
        self.calls = 0

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    async def run(self, payload: StageInput) -> StageOutcome:
        self.calls += 1
        if self.fail:
            raise PipelineError(f"{self._name} quebrou")
        return StageOutcome(
            context=payload.context.model_copy(update={"text": f"por {self._name}"}),
            message=f"{self._name} ok",
            metrics={"unidades": 1.0},
        )


def _doc() -> DocumentRecord:
    return DocumentRecord(
        id=uuid4(),
        user_id=uuid4(),
        source="filesystem",
        uri="file:///x.txt",
        mime_type="text/plain",
        title="x",
        doc_kind=None,
        metadata={},
        version=1,
        processing_state="pending",
    )


async def _raw(_d) -> bytes:
    return b"conteudo"


def _runner(stages, store, resolver=None):
    return PipelineRunner(
        stages=stages,
        resolver=resolver or PipelineResolver(default_plan=[s.name for s in stages]),
        processing=store,
        metrics=InMemoryMetrics(),
        read_raw=_raw,
    )


class TestHappyPath:
    async def test_runs_all_stages_and_records_timeline(self):
        store = FakeProcessingStore()
        a = CountingStage("a", ProcessingState.EXTRACTING)
        b = CountingStage("b", ProcessingState.CHUNKING)
        doc = _doc()
        state = await _runner([a, b], store).process(doc)
        assert state is ProcessingState.INDEXED
        assert store.states[doc.id] is ProcessingState.INDEXED
        assert doc.id in store.indexed
        assert [t.stage for t in store.timeline] == ["a", "b"]
        assert all(t.success for t in store.timeline)
        assert store.contexts[doc.id].stages_done == ["a", "b"]


class TestFailureAndResume:
    async def test_failure_marks_failed_with_error(self):
        store = FakeProcessingStore()
        a = CountingStage("a", ProcessingState.EXTRACTING)
        boom = CountingStage("boom", ProcessingState.CHUNKING, fail=True)
        doc = _doc()
        state = await _runner([a, boom], store).process(doc)
        assert state is ProcessingState.FAILED
        assert "boom quebrou" in (store.errors[doc.id] or "")
        assert [t.success for t in store.timeline] == [True, False]

    async def test_resume_skips_completed_stages(self):
        store = FakeProcessingStore()
        a = CountingStage("a", ProcessingState.EXTRACTING)
        boom = CountingStage("boom", ProcessingState.CHUNKING, fail=True)
        doc = _doc()
        await _runner([a, boom], store).process(doc)
        assert a.calls == 1

        # "corrige o bug" e retoma: o estágio a NÃO re-executa
        boom.fail = False
        state = await _runner([a, boom], store).process(doc)
        assert state is ProcessingState.INDEXED
        assert a.calls == 1  # retomada exata (req. 1)
        assert boom.calls == 2

    async def test_unknown_stage_fails_explicitly(self):
        store = FakeProcessingStore()
        doc = _doc()
        runner = _runner(
            [CountingStage("a", ProcessingState.EXTRACTING)],
            store,
            resolver=PipelineResolver(default_plan=["a", "fantasma"]),
        )
        state = await runner.process(doc)
        assert state is ProcessingState.FAILED
        assert "não registrado" in (store.errors[doc.id] or "")


class TestResolver:
    def test_source_plan_overrides_everything(self):
        resolver = default_resolver()
        assert resolver.resolve(mime_type="image/png", source_plan=["x"]) == ["x"]

    def test_image_plan_uses_ocr(self):
        plan = default_resolver().resolve(mime_type="image/png")
        assert plan[0] == "ocr"
        assert "extract" not in plan

    def test_text_plan_uses_extract(self):
        plan = default_resolver().resolve(mime_type="text/markdown")
        assert plan[0] == "extract"
