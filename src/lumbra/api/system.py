"""Rotas de saúde do sistema — mesma fonte de verdade do `lumbra doctor`.

Deliberadamente SEM autenticação para leitura do estado agregado: é a
página que alguém abre justamente quando nada funciona, inclusive o
login. Por isso nunca expõe segredo, DSN, caminho absoluto ou chave —
apenas se cada peça responde e o que fazer quando não responde.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from lumbra.diagnostics import checks
from lumbra.kernel.kernel import LumbraKernel
from lumbra.shared.config import Settings

_PAGINA = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Lumbra — System Health</title>
<style>
body{font:14px/1.5 ui-monospace,Consolas,monospace;background:#0f1115;color:#e6e6e6;margin:0;padding:32px}
h1{font-size:18px;margin:0 0 4px}.sub{color:#8b93a7;margin-bottom:24px}
table{border-collapse:collapse;width:100%;max-width:1000px}
td{padding:10px 12px;border-bottom:1px solid #23262e;vertical-align:top}
td.s{width:80px;font-weight:700}td.n{width:150px;color:#cbd2e0}
.ok{color:#7ecb7e}.warn{color:#e8c76b}.fail{color:#ef7070}.skip{color:#6b7280}
.fix{color:#8ab4f8;margin-top:4px}.det{color:#8b93a7;margin-top:4px}
.top{display:flex;gap:16px;align-items:baseline;margin-bottom:8px}
button{background:#23262e;color:#e6e6e6;border:1px solid #333;border-radius:4px;padding:6px 12px;cursor:pointer}
</style>
<div class="top"><h1>Lumbra — System Health</h1><button onclick="carregar()">atualizar</button></div>
<div class="sub" id="resumo">carregando...</div>
<table id="tabela"></table>
<script>
const SIM={ok:'OK',warn:'AVISO',fail:'FALHA',skip:'-'};
async function carregar(){
 const r=await fetch('/api/v1/system/health');const d=await r.json();
 document.getElementById('resumo').textContent =
  `versão ${d.version} · ambiente ${d.environment} · ${d.ready?'pronta para uso':'com problemas'} · `+
  `${d.summary.ok} ok, ${d.summary.warn} avisos, ${d.summary.fail} falhas`;
 document.getElementById('tabela').innerHTML = d.checks.map(c=>
  `<tr><td class="s ${c.status}">${SIM[c.status]}</td><td class="n">${c.name}</td><td>${esc(c.summary)}`+
  (c.detail?`<div class="det">${esc(c.detail)}</div>`:'')+
  (c.fix&&c.status!=='ok'?`<div class="fix">como corrigir: ${esc(c.fix)}</div>`:'')+
  `</td></tr>`).join('');
}
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
carregar();setInterval(carregar,30000);
</script></html>"""


def build_system_router(settings: Settings, kernel: LumbraKernel) -> APIRouter:
    router = APIRouter(prefix="/api/v1/system", tags=["ops"])

    @router.get("/health")
    async def saude() -> dict[str, Any]:
        resultados = await checks.executar(settings)
        return {
            "version": checks.versao_da_plataforma(),
            "environment": settings.environment,
            "ready": checks.tudo_pronto(resultados),
            "summary": checks.resumo(resultados),
            "modules": [m.manifest.name for m in kernel.modules()],
            "skills": len(kernel.skills.manifests()),
            "checks": [r.as_dict() for r in resultados],
        }

    @router.get("", response_class=HTMLResponse)
    async def pagina() -> str:
        return _PAGINA

    return router


# canário anti-truncamento
