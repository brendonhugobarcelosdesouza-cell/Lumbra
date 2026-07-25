"""DataSourcePort do sistema de arquivos local — primeira fonte do pipeline."""

from __future__ import annotations

import mimetypes
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from lumbra.ports.datasource import DataSourcePort, SourceItem

_EXTRA_MIME = {
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".ts": "text/x-typescript",
    ".js": "text/x-javascript",
    ".go": "text/x-go",
    ".rs": "text/x-rust",
    ".java": "text/x-java",
    ".json": "application/json",
    ".yml": "text/yaml",
    ".yaml": "text/yaml",
}
_SUPPORTED_SUFFIXES = set(_EXTRA_MIME) | {".txt", ".pdf", ".docx", ".png", ".jpg", ".jpeg"}


def _mime_for(path: Path) -> str | None:
    if path.suffix.lower() in _EXTRA_MIME:
        return _EXTRA_MIME[path.suffix.lower()]
    guess, _encoding = mimetypes.guess_type(path.name)
    return guess


class FilesystemSource(DataSourcePort):
    """Enumera arquivos suportados sob uma raiz. Leituras são restritas
    à raiz (proteção contra path traversal)."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        if not self._root.is_dir():
            raise NotADirectoryError(str(root))

    @property
    def kind(self) -> str:
        return "filesystem"

    async def scan(self, *, since: datetime | None = None) -> AsyncIterator[SourceItem]:
        for path in sorted(self._root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
                continue
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            if since is not None and modified <= since:
                continue
            yield SourceItem(
                uri=path.as_uri(),
                mime_type=_mime_for(path),
                size_bytes=stat.st_size,
                modified_at=modified,
            )

    async def read(self, uri: str) -> bytes:
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        parsed = urlparse(uri)
        path = Path(url2pathname(parsed.path)).resolve()
        if not path.is_relative_to(self._root):
            raise PermissionError(f"uri fora da raiz da fonte: {uri}")
        return path.read_bytes()


# canário anti-truncamento
