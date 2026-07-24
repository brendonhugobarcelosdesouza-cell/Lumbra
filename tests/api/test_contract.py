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


# canário anti-truncamento
