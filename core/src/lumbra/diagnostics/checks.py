"""Diagnóstico da plataforma — fonte ÚNICA de verdade (ADR-037).

O mesmo conjunto de verificações alimenta três consumidores: o comando
``lumbra doctor``, o endpoint ``/api/v1/system/health`` e a página System
Health do console. Três implementações separadas divergiriam, e a versão
que o usuário vê discordaria da que o desenvolvedor depura.

Cada verificação responde três coisas: **o que está errado**, **por que
importa** e **como corrigir** — um diagnóstico sem instrução de correção
só transfere o problema para quem menos sabe resolvê-lo.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from lumbra.shared.config import Settings


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"  # funciona, mas com limitação que o usuário deve conhecer
    FAIL = "fail"  # não funciona
    SKIP = "skip"  # não se aplica a esta configuração


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    summary: str
    detail: str | None = None
    fix: str | None = None  # instrução acionável — obrigatória em WARN/FAIL
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "summary": self.summary,
            "detail": self.detail,
            "fix": self.fix,
            "data": self.data,
        }


Check = Callable[[Settings], Awaitable[CheckResult]]

# ---------------------------------------------------------------- ambiente


async def check_python(_settings: Settings) -> CheckResult:
    versao = sys.version_info
    atual = f"{versao.major}.{versao.minor}.{versao.micro}"
    if versao < (3, 12):
        return CheckResult(
            "python",
            Status.FAIL,
            f"Python {atual} — a plataforma exige 3.12+",
            fix="Instale o Python 3.12 ou superior e recrie o ambiente virtual.",
        )
    return CheckResult("python", Status.OK, f"Python {atual}", data={"version": atual})


async def check_dependencias(_settings: Settings) -> CheckResult:
    faltando = []
    for modulo in ("fastapi", "sqlalchemy", "asyncpg", "pgvector", "fastembed", "redis", "httpx"):
        try:
            __import__(modulo)
        except ImportError:
            faltando.append(modulo)
    if faltando:
        return CheckResult(
            "dependencias",
            Status.FAIL,
            f"faltam pacotes: {', '.join(faltando)}",
            fix="Rode `pip install -e .[dev]` dentro do ambiente virtual do projeto.",
        )
    return CheckResult("dependencias", Status.OK, "todas as dependências importáveis")


async def check_docker(_settings: Settings) -> CheckResult:
    binario = shutil.which("docker")
    if binario is None:
        return CheckResult(
            "docker",
            Status.WARN,
            "Docker não encontrado",
            detail="Só é necessário se você usa o compose para subir Postgres e Redis.",
            fix="Instale o Docker Desktop, ou aponte LUMBRA_DATABASE__DSN para um "
            "PostgreSQL que você já tenha.",
        )
    try:
        processo = await asyncio.create_subprocess_exec(
            binario,
            "info",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await processo.wait()
    except Exception as exc:
        return CheckResult(
            "docker",
            Status.WARN,
            "Docker encontrado mas não respondeu",
            detail=f"O comando `docker info` falhou: {exc}",
            fix="Inicie o Docker Desktop ou o daemon do Docker.",
        )
    if processo.returncode != 0:
        return CheckResult(
            "docker",
            Status.WARN,
            "Docker instalado, mas o daemon não responde",
            fix="Abra o Docker Desktop e aguarde ficar 'running'.",
        )
    return CheckResult("docker", Status.OK, "Docker disponível")


async def check_variaveis(settings: Settings) -> CheckResult:
    env = Path(".env")
    inseguro = "dev-only-insecure" in settings.security.jwt_secret.get_secret_value()
    if settings.is_production and inseguro:
        return CheckResult(
            "configuracao",
            Status.FAIL,
            "segredo de JWT padrão em ambiente de produção",
            detail="Qualquer pessoa que conheça o código consegue forjar um token.",
            fix="Defina LUMBRA_SECURITY__JWT_SECRET com 32+ bytes aleatórios "
            '(ex.: `python -c "import secrets; print(secrets.token_urlsafe(48))"`).',
        )
    if inseguro:
        return CheckResult(
            "configuracao",
            Status.WARN,
            "usando segredo de JWT de desenvolvimento",
            detail=(
                f"ambiente={settings.environment}; "
                f"arquivo .env {'existe' if env.exists() else 'ausente'}"
            ),
            fix="Aceitável em desenvolvimento. Antes de expor a plataforma na rede, "
            "defina LUMBRA_SECURITY__JWT_SECRET.",
        )
    return CheckResult(
        "configuracao", Status.OK, f"ambiente={settings.environment}, segredo próprio definido"
    )


async def check_portas(_settings: Settings) -> CheckResult:
    ocupadas = []
    for porta, servico in ((8000, "API"), (11434, "Ollama")):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                ocupadas.append((porta, servico))
    livre_api = not any(p == 8000 for p, _ in ocupadas)
    detalhe = ", ".join(f"{p} ({s}) em uso" for p, s in ocupadas) or "8000 e 11434 livres"
    return CheckResult(
        "portas",
        Status.OK,
        detalhe,
        detail=None if livre_api else "A porta 8000 já responde — a API pode já estar rodando.",
        data={"em_uso": [p for p, _ in ocupadas]},
    )


async def check_permissoes(settings: Settings) -> CheckResult:
    destino = Path(settings.storage.attachments_dir)
    try:
        destino.mkdir(parents=True, exist_ok=True)
        teste = destino / ".lumbra-write-test"
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
    except OSError as exc:
        return CheckResult(
            "permissoes",
            Status.FAIL,
            f"sem permissão de escrita em {destino}",
            detail=str(exc),
            fix=f"Garanta permissão de escrita em {destino.resolve()} ou aponte "
            "LUMBRA_STORAGE__ATTACHMENTS_DIR para outra pasta.",
        )
    return CheckResult("permissoes", Status.OK, f"escrita liberada em {destino}")


# ---------------------------------------------------------------- serviços


async def check_postgres(settings: Settings) -> CheckResult:
    from sqlalchemy import text

    from lumbra.adapters.persistence.database import Database

    if not settings.com_banco:
        return CheckResult(
            "postgres",
            Status.WARN,
            "persistência em memória — nada é salvo entre reinícios",
            detail="Documentos, memórias e conversas somem ao parar o processo.",
            fix="Defina LUMBRA_PERSISTENCE=embedded (o Nó sobe o próprio "
            "Postgres, sem Docker) ou =postgres apontando para um banco seu.",
        )
    db = Database(settings.database)
    try:
        async with db.session() as sessao:
            versao = (await sessao.execute(text("SHOW server_version"))).scalar_one()
            vetor = (
                await sessao.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            ).first()
    except Exception as exc:
        return CheckResult(
            "postgres",
            Status.FAIL,
            "não foi possível conectar ao PostgreSQL",
            detail=f"{type(exc).__name__}: {exc}"[:300],
            fix="Suba o banco com `lumbra dev` (usa Docker) ou confira "
            "LUMBRA_DATABASE__DSN. O padrão é "
            "postgresql+asyncpg://lumbra:lumbra@localhost:5432/lumbra",
        )
    finally:
        await db.dispose()
    if vetor is None:
        return CheckResult(
            "postgres",
            Status.FAIL,
            f"PostgreSQL {versao} conectado, mas sem a extensão pgvector",
            detail="Sem pgvector não há busca semântica — só busca por palavra.",
            fix="Use a imagem pgvector/pgvector do compose, ou rode "
            "`CREATE EXTENSION vector;` no banco.",
        )
    return CheckResult(
        "postgres", Status.OK, f"PostgreSQL {versao} com pgvector", data={"version": str(versao)}
    )


async def check_migracoes(settings: Settings) -> CheckResult:
    from sqlalchemy import text

    from lumbra.adapters.persistence.database import Database

    if not settings.com_banco:
        return CheckResult("migracoes", Status.SKIP, "sem banco relacional configurado")
    revisoes = sorted(
        p.name.split("_")[0]
        for p in (
            Path(__file__).resolve().parents[1]
            / "adapters"
            / "persistence"
            / "migrations"
            / "versions"
        ).glob("[0-9]*.py")
    )
    esperada = revisoes[-1] if revisoes else None
    db = Database(settings.database)
    try:
        async with db.session() as sessao:
            atual = (
                await sessao.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
    except Exception:
        atual = None
    finally:
        await db.dispose()
    if atual is None:
        return CheckResult(
            "migracoes",
            Status.FAIL,
            "banco sem migrações aplicadas",
            fix="Rode `alembic upgrade head` (ou `lumbra dev`, que já faz isso).",
        )
    if esperada is not None and atual != esperada:
        return CheckResult(
            "migracoes",
            Status.FAIL,
            f"banco na revisão {atual}, código espera {esperada}",
            detail="Tabelas ou colunas novas podem estar faltando.",
            fix="Rode `alembic upgrade head`.",
        )
    return CheckResult("migracoes", Status.OK, f"esquema atualizado (revisão {atual})")


async def check_indices(settings: Settings) -> CheckResult:
    from sqlalchemy import text

    from lumbra.adapters.persistence.database import Database

    if not settings.com_banco:
        return CheckResult("indices", Status.SKIP, "sem banco relacional configurado")
    esperados = {
        "ix_chunks_embedding": "vetorial de documentos",
        "ix_chunks_tsv": "lexical de documentos",
        "ix_memory_items_embedding": "vetorial de memórias",
        "ix_memory_items_tsv": "lexical de memórias",
    }
    db = Database(settings.database)
    try:
        async with db.session() as sessao:
            existentes = {
                nome
                for (nome,) in (
                    await sessao.execute(
                        text("SELECT indexname FROM pg_indexes WHERE schemaname='public'")
                    )
                ).all()
            }
    except Exception as exc:
        return CheckResult(
            "indices", Status.FAIL, "não foi possível ler os índices", detail=str(exc)[:200]
        )
    finally:
        await db.dispose()
    faltando = {k: v for k, v in esperados.items() if k not in existentes}
    if faltando:
        return CheckResult(
            "indices",
            Status.WARN,
            f"faltam índices: {', '.join(faltando.values())}",
            detail="A busca continua funcionando, mas fica lenta conforme a base cresce.",
            fix="Rode `alembic upgrade head` para recriar os índices.",
        )
    return CheckResult("indices", Status.OK, "índices vetoriais (HNSW) e lexicais (GIN) presentes")


async def check_redis(settings: Settings) -> CheckResult:
    if settings.eventbus != "redis":
        return CheckResult(
            "redis",
            Status.WARN,
            "Event Bus em memória — eventos se perdem ao reiniciar",
            detail="Suficiente para uso pessoal em uma máquina; o processamento em "
            "andamento é perdido se o processo cair.",
            fix="Para durabilidade, defina LUMBRA_EVENTBUS=redis e suba o Redis "
            "(`lumbra dev` já sobe).",
        )
    from redis.asyncio import Redis

    cliente = Redis.from_url(settings.redis.url.get_secret_value())
    try:
        await cliente.ping()
        info = await cliente.info("server")
    except Exception as exc:
        return CheckResult(
            "redis",
            Status.FAIL,
            "Event Bus configurado para Redis, mas o Redis não responde",
            detail=f"{type(exc).__name__}: {exc}"[:200],
            fix="Suba o Redis (`lumbra dev`) ou volte para LUMBRA_EVENTBUS=memory.",
        )
    finally:
        await cliente.aclose()
    return CheckResult("redis", Status.OK, f"Redis {info.get('redis_version', '?')} respondendo")


# ---------------------------------------------------------------- IA


async def check_ollama(settings: Settings) -> CheckResult:
    import httpx

    url = settings.ai.ollama_base_url.rstrip("/")
    modelo = settings.ai.ollama_chat_model
    try:
        async with httpx.AsyncClient(timeout=3.0) as cliente:
            resposta = await cliente.get(f"{url}/api/tags")
            resposta.raise_for_status()
            modelos = [m["name"] for m in resposta.json().get("models", [])]
    except Exception:
        return CheckResult(
            "ollama",
            Status.FAIL,
            f"Ollama não respondeu em {url}",
            detail="Sem ele não há chat local — só resta a nuvem, se configurada.",
            fix="Instale em https://ollama.com e rode `ollama pull " + modelo + "`. "
            "No Windows o Ollama já roda como serviço após instalado.",
        )
    if not any(m == modelo or m.startswith(modelo.split(":")[0]) for m in modelos):
        return CheckResult(
            "ollama",
            Status.FAIL,
            f"Ollama ativo, mas o modelo {modelo} não está baixado",
            detail=f"disponíveis: {', '.join(modelos) or 'nenhum'}",
            fix=f"Rode `ollama pull {modelo}`.",
        )
    return CheckResult("ollama", Status.OK, f"Ollama ativo com {modelo}", data={"modelos": modelos})


async def check_provedor_nuvem(settings: Settings) -> CheckResult:
    if settings.ai.anthropic_api_key is None:
        return CheckResult(
            "ia_nuvem",
            Status.SKIP,
            "nenhum provedor de nuvem configurado (100% local)",
            fix="Opcional: defina LUMBRA_AI__ANTHROPIC_API_KEY para habilitar o Claude "
            "em conversas marcadas como allow_cloud.",
        )
    return CheckResult(
        "ia_nuvem",
        Status.OK,
        f"Anthropic configurado ({settings.ai.anthropic_chat_model})",
        detail="Só é usado em conversas com privacidade allow_cloud — nunca por padrão.",
    )


async def check_embeddings(settings: Settings) -> CheckResult:
    from lumbra.adapters.ai.fastembed_local import FastEmbedProvider

    provedor = FastEmbedProvider(
        settings.ai.embedding_model,
        dim=settings.ai.embedding_dim,
        cache_dir=Path(settings.ai.embedding_cache_dir)
        if settings.ai.embedding_cache_dir
        else None,
    )
    inicio = time.perf_counter()
    try:
        vetores = await provedor.embed(("teste de diagnóstico",))
    except Exception as exc:
        return CheckResult(
            "embeddings",
            Status.FAIL,
            "não foi possível gerar embeddings",
            detail=f"{type(exc).__name__}: {exc}"[:300],
            fix="O modelo é baixado no primeiro uso e exige internet UMA vez. "
            "Verifique a conexão e rode o diagnóstico de novo.",
        )
    ms = (time.perf_counter() - inicio) * 1000
    dim = len(vetores[0])
    if dim != settings.ai.embedding_dim:
        return CheckResult(
            "embeddings",
            Status.FAIL,
            f"modelo devolve {dim} dimensões, banco espera {settings.ai.embedding_dim}",
            detail="Buscas vetoriais falhariam ou trariam resultados sem sentido.",
            fix="Alinhe LUMBRA_AI__EMBEDDING_DIM ao modelo e reindexe os documentos.",
        )
    return CheckResult(
        "embeddings",
        Status.OK,
        f"modelo local pronto ({dim} dims, {ms:.0f} ms na primeira chamada)",
        data={"modelo": settings.ai.embedding_model, "dim": dim},
    )


# ---------------------------------------------------------------- execução


TODAS: tuple[Check, ...] = (
    check_python,
    check_dependencias,
    check_variaveis,
    check_permissoes,
    check_portas,
    check_docker,
    check_postgres,
    check_migracoes,
    check_indices,
    check_redis,
    check_ollama,
    check_provedor_nuvem,
    check_embeddings,
)


async def executar(
    settings: Settings, *, apenas: tuple[Check, ...] | None = None
) -> list[CheckResult]:
    """Roda as verificações em paralelo. Uma verificação que explode vira
    FAIL com o erro — o diagnóstico nunca deve ser a coisa que quebra."""

    async def seguro(check: Check) -> CheckResult:
        try:
            return await asyncio.wait_for(check(settings), timeout=30)
        except TimeoutError:
            return CheckResult(
                check.__name__.removeprefix("check_"),
                Status.FAIL,
                "verificação demorou demais (30s)",
                fix="Serviço pode estar travado. Verifique se está de fato no ar.",
            )
        except Exception as exc:
            return CheckResult(
                check.__name__.removeprefix("check_"),
                Status.FAIL,
                f"erro ao verificar: {type(exc).__name__}",
                detail=str(exc)[:300],
            )

    return list(await asyncio.gather(*(seguro(c) for c in (apenas or TODAS))))


def resumo(resultados: list[CheckResult]) -> dict[str, int]:
    contagem = {s.value: 0 for s in Status}
    for r in resultados:
        contagem[r.status.value] += 1
    return contagem


def tudo_pronto(resultados: list[CheckResult]) -> bool:
    """WARN não impede o uso — FAIL sim."""
    return not any(r.status is Status.FAIL for r in resultados)


def versao_da_plataforma() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("lumbra")
    except PackageNotFoundError:  # rodando do código-fonte
        return os.environ.get("LUMBRA_VERSION", "0.1.0+dev")


# canário anti-truncamento
