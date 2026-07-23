"""Testes do FilesystemSource e do estágio de OCR sem provider."""

from pathlib import Path
from uuid import uuid4

import pytest

from lumbra.adapters.sources.filesystem import FilesystemSource
from lumbra.domain.pipeline import PipelineContext, PipelineError
from lumbra.pipeline.stages.ocr import OCRStage
from lumbra.ports.document_store import DocumentRecord
from lumbra.ports.pipeline import StageInput


class TestFilesystemSource:
    async def test_scan_supported_files_with_mime(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("# doc")
        (tmp_path / "b.py").write_text("x = 1")
        (tmp_path / "ignorado.exe").write_bytes(b"\x00")
        source = FilesystemSource(tmp_path)
        items = [i async for i in source.scan()]
        mimes = {Path(i.uri).suffix: i.mime_type for i in items}
        assert mimes == {".md": "text/markdown", ".py": "text/x-python"}

    async def test_read_blocks_path_traversal(self, tmp_path: Path):
        inside = tmp_path / "dentro"
        inside.mkdir()
        secret = tmp_path / "segredo.txt"
        secret.write_text("fora da raiz")
        source = FilesystemSource(inside)
        with pytest.raises(PermissionError):
            await source.read(secret.as_uri())

    async def test_scan_since_filters_unmodified(self, tmp_path: Path):
        from datetime import UTC, datetime, timedelta

        (tmp_path / "velho.txt").write_text("x")
        source = FilesystemSource(tmp_path)
        future = datetime.now(tz=UTC) + timedelta(hours=1)
        assert [i async for i in source.scan(since=future)] == []


class TestOCRStageWithoutProvider:
    async def test_fails_explicitly_and_resumably(self):
        stage = OCRStage(provider=None)
        doc = DocumentRecord(
            id=uuid4(),
            user_id=uuid4(),
            source="filesystem",
            uri="file:///img.png",
            mime_type="image/png",
            title=None,
            doc_kind=None,
            metadata={},
            version=1,
            processing_state="pending",
        )
        with pytest.raises(PipelineError, match="nenhum OCRProvider"):
            await stage.run(StageInput(document=doc, raw=b"png", context=PipelineContext()))
