"""First Run Wizard — da instalação ao primeiro uso real.

O objetivo não é configurar tudo: é chegar rápido ao momento em que a
plataforma responde uma pergunta sobre um documento SEU. Cada passo
valida o anterior, e qualquer falha explica o que fazer em vez de deixar
o usuário adivinhando.

Roda contra a API já no ar (usa os mesmos endpoints públicos), então o
que o wizard faz, o usuário também consegue fazer sozinho depois.
"""

from __future__ import annotations

import asyncio
import getpass
from pathlib import Path
from typing import Any

import httpx

from lumbra.cli import console
from lumbra.diagnostics import checks
from lumbra.shared.config import get_settings

_TIMEOUT = httpx.Timeout(600.0)  # indexação e primeira resposta podem demorar


def _perguntar(texto: str, padrao: str | None = None) -> str:
    sufixo = f" [{padrao}]" if padrao else ""
    resposta = input(f"{texto}{sufixo}: ").strip()
    return resposta or (padrao or "")


def _confirmar(texto: str, *, padrao: bool = True) -> bool:
    marca = "S/n" if padrao else "s/N"
    resposta = input(f"{texto} [{marca}]: ").strip().lower()
    if not resposta:
        return padrao
    return resposta.startswith("s")


async def executar_wizard(base_url: str) -> int:
    console.titulo(f"Lumbra {checks.versao_da_plataforma()} — primeira execução")
    console.linha(
        console.cor(
            "Vamos configurar sua plataforma e indexar seus primeiros documentos.\n"
            "Nada sai da sua máquina, a não ser que você peça explicitamente.",
            "cinza",
        )
    )

    # 1. a plataforma está no ar?
    console.titulo("1. Verificando a plataforma")
    try:
        async with httpx.AsyncClient(timeout=10.0) as cliente:
            resposta = await cliente.get(f"{base_url}/api/v1/system/health")
            saude = resposta.json()
    except Exception:
        console.erro(f"não consegui falar com a API em {base_url}")
        console.linha(console.cor("Suba a plataforma com `lumbra dev` e rode de novo.", "azul"))
        return 1

    bloqueios = [c for c in saude["checks"] if c["status"] == "fail"]
    for bloqueio in bloqueios:
        console.linha(
            f"  {console.cor('FALHA', 'vermelho')}  {bloqueio['name']}: {bloqueio['summary']}"
        )
        if bloqueio["fix"]:
            console.linha(f"        {console.cor(bloqueio['fix'], 'azul')}")
    if bloqueios:
        console.linha(
            console.cor("\nCorrija os itens acima (`lumbra doctor` detalha) e volte.", "vermelho")
        )
        return 1
    console.linha(console.cor("  OK    plataforma no ar e saudável", "verde"))

    # 2. conta
    console.titulo("2. Sua conta")
    email = _perguntar("e-mail")
    senha = getpass.getpass("senha (mínimo 12 caracteres): ")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as cliente:
        registro = await cliente.post(
            f"{base_url}/api/v1/auth/register", json={"email": email, "password": senha}
        )
        if registro.status_code not in (200, 201, 409):
            console.erro(f"não foi possível criar a conta: {registro.text[:200]}")
            return 1
        if registro.status_code == 409:
            console.linha(console.cor("  conta já existia — vou apenas entrar", "cinza"))
        entrada = await cliente.post(
            f"{base_url}/api/v1/auth/token", data={"username": email, "password": senha}
        )
        if entrada.status_code != 200:
            console.erro("e-mail ou senha não conferem")
            return 1
        token = entrada.json()["access_token"]
        cabecalho = {"Authorization": f"Bearer {token}"}
        console.linha(console.cor("  OK    conta pronta", "verde"))

        # 3. IA
        console.titulo("3. Inteligência artificial")
        resposta_provedores = await cliente.get(
            f"{base_url}/api/v1/chat/providers", headers=cabecalho
        )
        if resposta_provedores.status_code != 200:
            console.linha(
                console.cor(
                    f"aviso: não consegui listar os provedores ({resposta_provedores.status_code})",
                    "amarelo",
                )
            )
            provedores = []
        else:
            provedores = resposta_provedores.json().get("providers", [])
        if provedores:
            for provedor in provedores:
                tipo = "local, sem custo" if provedor["is_local"] else "nuvem, com custo por token"
                console.linha(f"  - {provedor['name']} ({provedor['model']}) — {tipo}")
        if provedores and not any(p["is_local"] for p in provedores):
            console.linha(
                console.cor(
                    "  Nenhum modelo local disponível. Instale o Ollama (ollama.com) "
                    "para manter tudo na sua máquina.",
                    "amarelo",
                )
            )
        settings = get_settings()
        if settings.ai.anthropic_api_key is None:
            console.linha(
                console.cor(
                    "  Nuvem não configurada (opcional). Para habilitar o Claude em "
                    "conversas marcadas como allow_cloud, defina "
                    "LUMBRA_AI__ANTHROPIC_API_KEY no .env.",
                    "cinza",
                )
            )

        # 4. documentos
        console.titulo("4. Seus documentos")
        console.linha(
            console.cor(
                "Escolha uma pasta para indexar. Comece pequena (dezenas de arquivos) "
                "para ver o resultado rápido.",
                "cinza",
            )
        )
        pasta = _perguntar("pasta", str(Path.home() / "Documentos"))
        indexados: dict[str, Any] = {}
        if Path(pasta).is_dir():
            console.linha("  indexando (pode demorar alguns minutos)...")
            # a indexação é uma execução de skill ASSÍNCRONA: dispara e devolve
            # um id; a gente consulta até o scan da pasta terminar (os arquivos
            # em si processam em segundo plano depois).
            resposta = await cliente.post(
                f"{base_url}/api/v1/dev/executions",
                headers=cabecalho,
                json={"kind": "skill", "name": "document.index", "payload": {"path": pasta}},
            )
            if resposta.status_code == 202:
                exec_id = resposta.json()["execution_id"]
                execucao: dict[str, Any] = {}
                for _ in range(120):
                    await asyncio.sleep(1)
                    detalhe = await cliente.get(
                        f"{base_url}/api/v1/dev/executions/{exec_id}", headers=cabecalho
                    )
                    execucao = detalhe.json().get("execution", {})
                    if execucao.get("status") in ("completed", "failed"):
                        break
                if execucao.get("status") == "completed":
                    indexados = execucao.get("output") or {}
                    console.linha(
                        console.cor(
                            f"  OK    {indexados.get('queued', 0)} de "
                            f"{indexados.get('discovered', 0)} arquivos enfileirados "
                            "(processam em segundo plano)",
                            "verde",
                        )
                    )
                else:
                    motivo = execucao.get("error") or "tempo esgotado"
                    console.linha(console.cor(f"  não consegui indexar: {motivo}", "amarelo"))
            else:
                console.linha(
                    console.cor(f"  não consegui indexar: {resposta.text[:200]}", "amarelo")
                )
        else:
            console.linha(console.cor(f"  pasta não encontrada: {pasta} — pulando", "amarelo"))

        # 5. memória
        console.titulo("5. Memória")
        if _confirmar("Quer guardar um primeiro fato sobre você?"):
            fato = _perguntar("algo que a Lumbra deve lembrar", "Prefiro respostas objetivas")
            gravado = await cliente.post(
                f"{base_url}/api/v1/memory", headers=cabecalho, json={"content": fato}
            )
            if gravado.status_code in (200, 201):
                console.linha(console.cor("  OK    memória guardada", "verde"))
                busca = await cliente.get(
                    f"{base_url}/api/v1/memory",
                    headers=cabecalho,
                    params={"query": fato[:30]},
                )
                encontrou = bool(busca.json().get("items") or busca.json().get("hits"))
                console.linha(
                    console.cor(
                        f"  {'OK    recall funcionando' if encontrou else 'aviso: recall vazio'}",
                        "verde" if encontrou else "amarelo",
                    )
                )

        # 6. primeira conversa
        console.titulo("6. Primeira conversa")
        if _confirmar("Fazer uma pergunta de teste agora?"):
            conversa = await cliente.post(
                f"{base_url}/api/v1/chat/conversations", headers=cabecalho, json={}
            )
            conversa_id = conversa.json()["conversation_id"]
            pergunta = _perguntar("pergunta", "O que você sabe sobre mim?")
            console.linha("  pensando (o primeiro uso carrega o modelo, pode demorar)...")
            resposta = await cliente.post(
                f"{base_url}/api/v1/chat/conversations/{conversa_id}/messages",
                headers=cabecalho,
                json={"content": pergunta},
            )
            if resposta.status_code == 200:
                dados = resposta.json()
                console.linha()
                console.linha(f"  {dados['text']}")
                fontes = dados.get("citations", [])
                if fontes:
                    console.linha(
                        console.cor(
                            f"  fontes: {', '.join(f['title'] or f['kind'] for f in fontes)}",
                            "cinza",
                        )
                    )
            else:
                console.linha(console.cor(f"  falhou: {resposta.text[:300]}", "amarelo"))

    console.titulo("Pronto")
    console.linha("Daqui em diante:")
    console.linha(f"  conversar         {base_url}/docs  (ou scripts/chat.ps1)")
    console.linha(f"  ver a saúde       {base_url}/api/v1/system/health")
    console.linha(f"  console de dev    {base_url}/api/v1/dev/console")
    console.linha(f"  auditar memória   {base_url}/api/v1/memory")
    return 0


# canário anti-truncamento
