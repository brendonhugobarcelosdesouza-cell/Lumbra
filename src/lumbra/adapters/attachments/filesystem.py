"""BlobStore em sistema de arquivos local (privacidade por padrão: os
arquivos do usuário não saem da máquina)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from uuid import UUID

from lumbra.ports.attachments import BlobStorePort
from lumbra.shared.ids import uuid7

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize(filename: str) -> str:
    """Nome de arquivo do usuário NUNCA vira caminho: sem barras, sem '..'."""
    limpo = _SAFE.sub("_", Path(filename).name).strip("._-")
    return limpo[:120] or "arquivo"


class FilesystemBlobStore(BlobStorePort):
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    async def save(self, data: bytes, *, filename: str, owner: UUID) -> str:
        destino = self._root / str(owner)
        destino.mkdir(parents=True, exist_ok=True)
        caminho = destino / f"{uuid7()}-{_sanitize(filename)}"
        await asyncio.to_thread(caminho.write_bytes, data)
        return caminho.resolve().as_uri()

    async def read(self, uri: str) -> bytes:
        caminho = self._path_of(uri)
        return await asyncio.to_thread(caminho.read_bytes)

    async def delete(self, uri: str) -> None:
        caminho = self._path_of(uri)
        await asyncio.to_thread(caminho.unlink, True)

    def _path_of(self, uri: str) -> Path:
        # url2pathname (não urlparse+unquote cru) para converter o path do
        # file:// URI em caminho nativo: no Windows, "/C:/Users/..." vira
        # "C:\\Users\\..." corretamente; no POSIX é passthrough + unquote.
        caminho = Path(url2pathname(urlparse(uri).path)).resolve()
        raiz = self._root.resolve()
        # defesa contra travessia: só lemos o que está sob a raiz
        if not caminho.is_relative_to(raiz):
            raise PermissionError(f"caminho fora do armazenamento: {caminho}")
        return caminho


# canário anti-truncamento
