# 18 — Segurança e Privacidade

## Modelo de ameaças (resumo)

Ativos críticos: memórias, documentos (saúde/finanças/identidade), chaves. Adversários considerados: atacante remoto, plugin malicioso, dispositivo roubado, insider no serviço cloud, provedor de IA curioso. Princípios: menor privilégio, defesa em profundidade, **o servidor nunca precisa ler conteúdo do usuário**.

## Criptografia

| Camada | Mecanismo |
|---|---|
| Em trânsito | TLS 1.3 obrigatório; certificate pinning nos apps |
| Em repouso (cloud) | Volumes cifrados + criptografia por coluna na aplicação (AES-256-GCM) para conteúdo |
| Em repouso (desktop) | Banco e arquivos cifrados com chave derivada da senha (Argon2id) + keychain do SO |
| Sync | E2E: payloads cifrados no dispositivo; servidor armazena blobs opacos (doc 08, `sync_ops`) |
| Chaves | Hierarquia: chave-mestra do usuário → chaves por categoria (saúde, finanças, docs) → rotação sem re-cifrar tudo (envelope encryption) |

## Autenticação e autorização

OAuth2/OIDC + JWT curto (15 min) com refresh rotativo e detecção de reuso. 2FA (TOTP + passkeys/WebAuthn; SMS não). Biometria nos apps para desbloqueio local. Sessões por dispositivo, revogáveis. Autorização: Permission Manager central — escopos `verbo:recurso` para usuários, agentes e plugins; toda ação com efeito externo checa consentimento ativo; audit log imutável de concessões, revogações e usos.

## Privacidade e IA

- Roteamento por sensibilidade: categorias marcadas `local_only` nunca saem para provedores cloud (forçadas a Ollama).
- Nenhum dado do usuário usado para treinar modelos; contratos com provedores com zero-retention quando disponível.
- Prompt injection: conteúdo indexado (e-mails, documentos, páginas) é tratado como não-confiável — nunca vira instrução; agentes com efeito externo exigem confirmação do usuário para ações originadas de conteúdo não-confiável.
- Telemetria: opt-in, agregada, sem conteúdo (doc 16).

## LGPD/GDPR

Base legal por categoria com consentimento explícito e granular (saúde é dado sensível — art. 11 LGPD). Direitos implementados como API, não como processo manual: exportação (`/privacy/export`), exclusão total (`/privacy/erase`, com 2FA), revisão de consentimentos (`/consents`). Minimização: coletamos apenas o que o usuário conecta. DPO nomeado no beta; RIPD (relatório de impacto) para saúde e finanças; avisos de privacidade em linguagem simples.

## Segurança de plugins

Sandbox em processo separado com API mediada pelo kernel (sem acesso direto a FS/rede/banco). Manifesto de permissões aprovado pelo usuário na instalação; escopo negado = erro, não prompt repetitivo. Diretório oficial com revisão; plugins fora do diretório exigem modo desenvolvedor. Kill switch: `plugin.quarantined` remoto para plugins maliciosos conhecidos.

## Operação

SDLC: SAST, scan de dependências e segredos no CI (doc 15); revisão de segurança obrigatória em PRs que tocam auth/crypto/permissões. Pentest externo antes do beta público e anualmente. Programa de divulgação responsável (security.txt + recompensas a definir). Resposta a incidentes: playbook com prazos LGPD/ANPD (comunicação em prazo razoável), rotação de credenciais automatizável. Backups imutáveis (doc 17).
