"""CLI da Lumbra — um comando para cada coisa que você precisa fazer.

    lumbra doctor    diagnostica o ambiente e diz como corrigir
    lumbra dev       sobe tudo para desenvolvimento (banco, migrações, API)
    lumbra up        sobe em modo produção local
    lumbra init      assistente de primeira execução
    lumbra version   versão da plataforma

Implementado com ``argparse`` de propósito: uma dependência a menos para
falhar numa instalação limpa, que é exatamente o cenário que este comando
existe para consertar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lumbra.cli import console
from lumbra.diagnostics import checks
from lumbra.shared.config import Settings, get_settings

if TYPE_CHECKING:
    from alembic.config import Config

# core/src/lumbra/cli/main.py → parents[3] = core/ (onde vive o alembic.ini)
CORE_RAIZ = Path(__file__).resolve().parents[3]
# a raiz do monorepo (um nível acima de core/) orquestra a infra: é onde
# ficam docker-compose.yml e docker/ — toda interface consome a Platform API,
# mas o compose sobe Postgres/Redis/API do produto inteiro
MONOREPO_RAIZ = CORE_RAIZ.parent


def _settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


# ---------------------------------------------------------------- doctor


def _imprimir_resultado(resultado: checks.CheckResult) -> None:
    simbolo = console.SIMBOLOS[resultado.status.value]
    cor_status = console.CORES_STATUS[resultado.status.value]
    console.linha(
        f"  {console.cor(simbolo, cor_status)}  "
        f"{console.cor(resultado.name.ljust(14), 'negrito')} {resultado.summary}"
    )
    if resultado.detail:
        console.linha(f"        {console.cor(resultado.detail, 'cinza')}")
    if resultado.fix and resultado.status in (checks.Status.FAIL, checks.Status.WARN):
        console.linha(f"        {console.cor('como corrigir: ' + resultado.fix, 'azul')}")


def comando_doctor(args: argparse.Namespace) -> int:
    console.silenciar_logs(args.verbose)
    resultados = asyncio.run(checks.executar(_settings()))
    if args.json:
        print(
            json.dumps(
                {
                    "version": checks.versao_da_plataforma(),
                    "ready": checks.tudo_pronto(resultados),
                    "summary": checks.resumo(resultados),
                    "checks": [r.as_dict() for r in resultados],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if checks.tudo_pronto(resultados) else 1

    console.titulo(f"Lumbra {checks.versao_da_plataforma()} — diagnóstico")
    for resultado in resultados:
        _imprimir_resultado(resultado)

    contagem = checks.resumo(resultados)
    console.linha()
    if checks.tudo_pronto(resultados):
        console.linha(
            console.cor(
                f"Tudo pronto para usar. ({contagem['ok']} ok, {contagem['warn']} avisos)", "verde"
            )
        )
        if contagem["warn"]:
            console.linha(
                console.cor("Avisos não impedem o uso — são limitações que vale conhecer.", "cinza")
            )
        return 0
    console.linha(
        console.cor(
            f"{contagem['fail']} problema(s) impedem o funcionamento. "
            "Siga as instruções acima e rode `lumbra doctor` de novo.",
            "vermelho",
        )
    )
    return 1


# ---------------------------------------------------------------- dev / up


def _compose_disponivel() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    return (
        subprocess.run([docker, "compose", "version"], capture_output=True, check=False).returncode
        == 0
    )


def _preparar_embutido() -> bool:
    """Sobe o Postgres do próprio Nó e aponta a configuração para ele.

    A variável de ambiente é o canal certo, e não um parâmetro: sob
    ``--reload`` o uvicorn cria um processo FILHO que monta a aplicação de
    novo, e ele precisa achar o mesmo banco. Passando por argumento, o pai
    migraria um banco e o filho abriria outro — sintoma: "tabela não existe"
    logo depois de uma migração que deu certo.
    """
    from lumbra.adapters.persistence.embedded import preparar_banco

    settings = _settings()
    if settings.persistence != "embedded":
        return False
    console.linha("Subindo o Postgres embutido (sem Docker)...")
    dsn, servidor = preparar_banco(settings.database, embutido=True)
    os.environ["LUMBRA_DATABASE__DSN"] = dsn
    get_settings.cache_clear()
    console.linha(console.cor(f"  dados em {servidor.pasta if servidor else '?'}", "azul"))
    return True


def _ja_configurado(chave: str) -> bool:
    """O usuário já decidiu isto — na variável de ambiente ou no ``.env``?

    ``os.environ.setdefault`` parecia suficiente e não era: o ``.env`` não
    está em ``os.environ``, então o "padrão" do comando **vencia** uma
    escolha explícita do usuário. Com ``LUMBRA_ENVIRONMENT=local`` no
    arquivo, o ``lumbra up`` subia em ``production`` assim mesmo — e a
    primeira consequência foi ele reprovar o segredo de JWT de
    desenvolvimento numa máquina que dizia, por escrito, não ser produção.

    Padrão que sobrescreve configuração explícita não é padrão: é ordem
    disfarçada.
    """
    if chave in os.environ:
        return True
    from lumbra.shared.config import arquivos_de_configuracao

    # os MESMOS arquivos que o Settings lê: se olhássemos noutro lugar, o
    # comando decidiria por um arquivo e a aplicação obedeceria a outro
    for nome in arquivos_de_configuracao():
        env = Path(nome)
        if not env.exists():
            continue
        if any(
            linha.strip().startswith(f"{chave}=")
            for linha in env.read_text(encoding="utf-8").splitlines()
        ):
            return True
    return False


def _padrao(chave: str, valor: str) -> None:
    """Define ``chave`` só se o usuário não tiver decidido antes."""
    if not _ja_configurado(chave):
        os.environ[chave] = valor


def _garantir_segredo_local() -> None:
    """Dá a esta instalação uma chave só dela (ADR-070).

    Só entra quando o usuário não definiu a sua: quem administra um servidor
    continua mandando na configuração. E não toca em ``lumbra dev`` — lá o
    segredo de desenvolvimento é conhecido de propósito, e trocá-lo por um
    aleatório derrubaria a sessão a cada máquina nova sem ganho nenhum.
    """
    from lumbra.shared.segredo_local import caminho_do_segredo, segredo_desta_instalacao

    # pelo mesmo motivo de _ja_configurado: uma chave escrita no .env é
    # escolha do usuário e não pode ser trocada por uma gerada por nós
    if _ja_configurado("LUMBRA_SECURITY__JWT_SECRET"):
        return
    os.environ["LUMBRA_SECURITY__JWT_SECRET"] = segredo_desta_instalacao()
    get_settings.cache_clear()
    console.linha(console.cor(f"  chave desta instalação em {caminho_do_segredo()}", "azul"))


def _subir_servicos() -> bool:
    if _preparar_embutido():
        return True
    if not _compose_disponivel():
        console.linha(
            console.cor(
                "Docker indisponível — assumindo que Postgres e Redis já estão no ar.", "amarelo"
            )
        )
        return False
    console.linha("Subindo Postgres e Redis (docker compose)...")
    resultado = subprocess.run(
        [shutil.which("docker") or "docker", "compose", "up", "-d", "postgres", "redis"],
        cwd=MONOREPO_RAIZ,
        check=False,
    )
    return resultado.returncode == 0


def _config_alembic() -> Config:
    """Alembic apontado para as migrações PELO PACOTE, não pelo repositório.

    O ``script_location`` do ``alembic.ini`` é relativo, e o Alembic o
    resolve contra o diretório ATUAL. Rodar ``lumbra up`` da raiz do
    monorepo em vez de dentro de ``core/`` já bastava para quebrar:
    "Path doesn't exist: src\\lumbra\\adapters\\persistence\\migrations".

    Instalado seria pior: não existe ``core/`` nenhum, e o diretório atual é
    a pasta de onde o atalho foi clicado. Perguntar ao próprio pacote onde
    ele mora é a única forma que funciona nos dois casos.
    """
    from alembic.config import Config

    from lumbra.adapters import persistence

    # o .ini traz só preferências de log e vive no repositório; instalado,
    # ele não existe, e isso não é motivo para não migrar
    ini = CORE_RAIZ / "alembic.ini"
    cfg = Config(str(ini)) if ini.exists() else Config()
    migracoes = Path(persistence.__file__).resolve().parent / "migrations"
    cfg.set_main_option("script_location", str(migracoes))
    return cfg


def _aplicar_migracoes() -> bool:
    console.linha("Aplicando migrações...")
    from alembic import command

    try:
        command.upgrade(_config_alembic(), "head")
    except Exception as exc:
        console.erro(f"falha ao migrar: {exc}")
        console.linha(
            console.cor(
                "O banco está no ar? Rode `lumbra doctor` para um diagnóstico completo.", "azul"
            )
        )
        return False
    return True


def _vigiar_a_entrada(servidor: Any) -> None:
    """Encerra o Nó com dignidade quando quem o iniciou vai embora.

    O app desktop não tem como mandar um sinal para o Nó no Windows: o
    ``Process.kill`` do Dart vira ``TerminateProcess``, que não avisa
    ninguém. E o preço disso foi cobrado — o Postgres embutido levou um tiro
    no meio de um ``COMMIT`` e o cluster ficou precisando de recuperação
    (correção ao ADR-069).

    O canal que existe nos dois sistemas é a entrada padrão: quando o app
    fecha o ``stdin`` do filho, ou quando o app MORRE, o cano fecha e a
    leitura devolve EOF. Aí pedimos ao uvicorn uma parada limpa, o
    interpretador termina normalmente e o ``atexit`` do ``pgserver``
    desliga o banco como se deve.

    A propriedade que mais vale é a segunda: isto também protege do app
    fechar de forma abrupta, que é o caso que nenhum "fechar bonitinho"
    cobre.
    """
    try:
        for _ in sys.stdin:
            pass  # qualquer coisa que chegue é ignorada: só o FIM interessa
    except Exception as exc:
        # entrada fechada de forma estranha também é fim — e é o caso mais
        # importante: significa que quem nos iniciou morreu de repente
        _log_cli(f"entrada interrompida ({type(exc).__name__})")
    _log_cli("entrada encerrada — parando o Nó")
    servidor.should_exit = True


def _log_cli(mensagem: str) -> None:
    console.linha(console.cor(f"[Nó] {mensagem}", "cinza"))


def _servir(*, reload: bool, host: str, porta: int, seguir_a_entrada: bool = False) -> int:
    import uvicorn

    console.linha(
        console.cor(
            f"\nAPI em http://{host}:{porta}  |  console em "
            f"http://{host}:{porta}/api/v1/dev/console  |  saúde em "
            f"http://{host}:{porta}/api/v1/system/health",
            "verde",
        )
    )
    if reload:
        # com recarga automática quem manda é o supervisor do uvicorn, e não
        # há um `Server` para pedir que pare. É por isso que o sidecar usa
        # `--no-reload`: recarga é ferramenta de quem edita o Core.
        uvicorn.run(
            "lumbra.api.main:create_default_app",
            factory=True,
            host=host,
            port=porta,
            reload=True,
            log_level="info",
        )
        return 0

    # a fábrica entra como OBJETO, não como texto "lumbra.api.main:...".
    # Congelado, um import por nome é invisível para o empacotador: ele não
    # tem como saber que aquele texto é um módulo, e o executável sai sem a
    # aplicação dentro. O sintoma seria ótimo de errar e péssimo de achar —
    # roda no repositório, quebra na máquina de quem instalou.
    from lumbra.api.main import create_default_app

    servidor = uvicorn.Server(
        uvicorn.Config(
            create_default_app,
            factory=True,
            host=host,
            port=porta,
            log_level="info",
        )
    )
    if seguir_a_entrada:
        threading.Thread(target=_vigiar_a_entrada, args=(servidor,), daemon=True).start()
    try:
        servidor.run()
    finally:
        # o banco embutido é NOSSO: desligá-lo faz parte de encerrar, e não
        # é tarefa que se delegue ao acaso de um atexit
        from lumbra.adapters.persistence.embedded import parar_embutidos

        parar_embutidos()
    return 0


def comando_dev(args: argparse.Namespace) -> int:
    console.titulo("Lumbra — ambiente de desenvolvimento")
    _padrao("LUMBRA_ENVIRONMENT", "local")
    _padrao("LUMBRA_PERSISTENCE", "postgres")
    _subir_servicos()
    if not _aplicar_migracoes():
        return 1
    resultados = asyncio.run(
        checks.executar(_settings(), apenas=(checks.check_postgres, checks.check_ollama))
    )
    for resultado in resultados:
        if resultado.status is not checks.Status.OK:
            _imprimir_resultado(resultado)
    return _servir(reload=not args.no_reload, host=args.host, porta=args.port)


# O que impede SERVIR — e não o que estraga uma funcionalidade.
#
# Antes, qualquer FALHA barrava o `lumbra up`, e isso funcionava enquanto o
# comando era coisa de quem administra um servidor. Como caminho do produto,
# vira absurdo: sem o Ollama instalado, a Lumbra inteira não abriria — nem
# documentos, nem memória, nem busca, que não dependem de modelo de conversa
# nenhum. "Falhar cedo" vale para o que compromete os DADOS; para o resto, o
# certo é abrir avisando o que ficou de fora.
IMPEDEM_SUBIR = frozenset(
    {"python", "dependencias", "configuracao", "permissoes", "postgres", "migracoes"}
)


def comando_up(args: argparse.Namespace) -> int:
    """Produção local: sem recarga automática, e sem subir se o que falta
    comprometer os dados. O que só tira uma funcionalidade vira aviso."""
    console.titulo("Lumbra — modo produção local")
    _padrao("LUMBRA_ENVIRONMENT", "production")
    # 'embedded' por padrão porque `up` é o Nó como PRODUTO: é o que o
    # instalador vai chamar, na máquina de alguém que não tem Docker e não
    # deveria precisar ter. Quem prefere um banco próprio define
    # LUMBRA_PERSISTENCE=postgres. `lumbra dev` segue no compose — lá o
    # Docker é ferramenta de trabalho, não requisito imposto ao usuário.
    _padrao("LUMBRA_PERSISTENCE", "embedded")
    _garantir_segredo_local()
    _subir_servicos()
    if not _aplicar_migracoes():
        return 1
    resultados = asyncio.run(checks.executar(_settings()))
    falhas = [r for r in resultados if r.status is checks.Status.FAIL]
    impedem = [r for r in falhas if r.name in IMPEDEM_SUBIR]
    if impedem:
        console.linha(console.cor("Não vou subir com problemas pendentes:", "vermelho"))
        for problema in impedem:
            _imprimir_resultado(problema)
        return 1
    for degradado in falhas:
        console.linha(console.cor(f"Sem {degradado.name}: {degradado.summary}", "amarelo"))
        if degradado.fix:
            console.linha(console.cor(f"  como corrigir: {degradado.fix}", "azul"))
    return _servir(
        reload=False, host=args.host, porta=args.port, seguir_a_entrada=args.seguir_a_entrada
    )


# ---------------------------------------------------------------- version


def comando_version(_args: argparse.Namespace) -> int:
    console.silenciar_logs()
    print(f"lumbra {checks.versao_da_plataforma()} (python {sys.version.split()[0]})")
    return 0


# ---------------------------------------------------------------- parser


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lumbra",
        description="Lumbra — plataforma pessoal de inteligência.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exemplos:\n"
            "  lumbra doctor          verifica o ambiente e diz como corrigir\n"
            "  lumbra init            assistente de primeira execução\n"
            "  lumbra dev             sobe tudo para desenvolvimento\n"
            "  lumbra up              sobe em modo produção local\n"
        ),
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    doctor = sub.add_parser("doctor", help="diagnostica o ambiente")
    doctor.add_argument("--json", action="store_true", help="saída legível por máquina")
    doctor.add_argument(
        "--verbose", action="store_true", help="mostra logs internos (depurar o diagnóstico)"
    )
    doctor.set_defaults(func=comando_doctor)

    dev = sub.add_parser("dev", help="sobe o ambiente de desenvolvimento")
    dev.add_argument("--host", default="127.0.0.1")
    dev.add_argument("--port", type=int, default=8000)
    dev.add_argument("--no-reload", action="store_true")
    dev.set_defaults(func=comando_dev)

    up = sub.add_parser("up", help="sobe em modo produção local")
    up.add_argument("--host", default="127.0.0.1")
    up.add_argument("--port", type=int, default=8000)
    up.add_argument(
        "--seguir-a-entrada",
        dest="seguir_a_entrada",
        action="store_true",
        help="encerra quando a entrada padrão fechar (o app usa isto para "
        "desligar o Nó sem matá-lo à força)",
    )
    up.set_defaults(func=comando_up)

    init = sub.add_parser("init", help="assistente de primeira execução")
    init.add_argument("--host", default="http://127.0.0.1:8000")
    init.set_defaults(func=lambda args: _comando_init(args))

    versao = sub.add_parser("version", help="mostra a versão")
    versao.set_defaults(func=comando_version)
    return parser


def _comando_init(args: argparse.Namespace) -> int:
    console.silenciar_logs()
    from lumbra.cli.wizard import executar_wizard

    return asyncio.run(executar_wizard(args.host))


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        console.linha("\ninterrompido")
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


# canário anti-truncamento
