"""O contrato da Platform API é um artefato: mudou a API, muda o snapshot.

P1-a da plataforma (docs/24, Regra 1): ``contracts/platform-api-v1.json``
é a fonte revisável do contrato que todos os clientes (desktop, mobile,
web, plugins) consomem. Estes testes travam duas promessas: o snapshot
está sempre em dia com o código, e toda rota vive sob versionamento.
"""

from lumbra.api import contract


def test_snapshot_em_dia_com_o_codigo():
    """Mudança de API sem regenerar o contrato = build quebrado, de propósito."""
    arquivo = contract.repo_root() / contract.CONTRACT_RELPATH
    assert arquivo.is_file(), (
        f"snapshot do contrato ausente em {arquivo}; gere com: python -m lumbra.api.contract"
    )
    esperado = arquivo.read_text(encoding="utf-8")
    atual = contract.canonical_json()
    assert atual == esperado, (
        "A superfície da Platform API mudou sem atualizar o contrato.\n"
        "Se a mudança é intencional, regenere e REVISE O DIFF:\n"
        "    python -m lumbra.api.contract\n"
        "e commite contracts/platform-api-v1.json junto da mudança."
    )


def test_geracao_e_deterministica():
    """Duas gerações no mesmo código produzem bytes idênticos — sem isso,
    o teste de snapshot viraria loteria."""
    assert contract.canonical_json() == contract.canonical_json()


def test_toda_rota_e_versionada_ou_ops():
    """Regra de versionamento: tudo sob /api/v1, exceto liveness/readiness.
    Uma rota fora disso escaparia da janela de compatibilidade N-1 (ADR-046)."""
    schema = contract.openapi_schema()
    fora = [
        path
        for path in schema["paths"]
        if not path.startswith("/api/v1/") and path not in ("/health", "/ready")
    ]
    assert fora == [], f"rotas fora de /api/v1 (ou ops): {fora}"


def test_campos_required_nao_sao_anulaveis():
    """Um campo ``required`` E anulável faz o gerador Dart cravar
    ``assert(json[k] != null)`` e quebrar quando o valor vem null. A regra
    que evita isso: campo anulável é OPCIONAL (default), não required."""
    schema = contract.openapi_schema()
    problemas: list[str] = []
    for nome, esquema in schema.get("components", {}).get("schemas", {}).items():
        props = esquema.get("properties", {})
        for campo in esquema.get("required", []):
            p = props.get(campo, {})
            tipos = p.get("type")
            anulavel = ("null" in tipos if isinstance(tipos, list) else False) or any(
                sub.get("type") == "null" for sub in p.get("anyOf", [])
            )
            if anulavel:
                problemas.append(f"{nome}.{campo}")
    assert problemas == [], f"campos required+anuláveis (quebram o cliente Dart): {problemas}"


def test_contrato_independe_do_adaptador():
    """Regra 1 (docs/24) como trava: um cliente vê a MESMA API contra um Nó
    em modo memória ou em modo postgres. Se a superfície divergir por
    adaptador, este teste falha — foi o defeito #12, agora barrado."""
    import os

    from lumbra.shared.config import get_settings

    def rotas(persistence: str) -> set[str]:
        anterior = os.environ.get("LUMBRA_PERSISTENCE")
        os.environ["LUMBRA_PERSISTENCE"] = persistence
        os.environ["LUMBRA_EVENTBUS"] = "memory"
        get_settings.cache_clear()
        try:
            from lumbra.api.main import create_default_app

            return set(create_default_app().openapi()["paths"])
        finally:
            if anterior is None:
                os.environ.pop("LUMBRA_PERSISTENCE", None)
            else:
                os.environ["LUMBRA_PERSISTENCE"] = anterior
            get_settings.cache_clear()

    memoria = rotas("memory")
    postgres = rotas("postgres")
    assert memoria == postgres, (
        "a superfície da API difere entre modos de persistência (viola Regra 1):\n"
        f"  só em memória: {sorted(memoria - postgres)}\n"
        f"  só em postgres: {sorted(postgres - memoria)}"
    )


# canário anti-truncamento
