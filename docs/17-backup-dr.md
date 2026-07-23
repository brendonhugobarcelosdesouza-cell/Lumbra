# 17 — Backup e Recuperação de Desastres

## Cloud

| Ativo | Estratégia | RPO | RTO |
|---|---|---|---|
| PostgreSQL | WAL contínuo (PITR) + snapshot diário + réplica cross-region | 5 min | 1 h |
| Object storage | Versionamento + replicação cross-region | 15 min | 2 h |
| Redis | Efêmero (cache/filas); streams críticos re-deriváveis do event store | n/a | 15 min |
| events_log | Partições mensais arquivadas em storage frio imutável (WORM) | 24 h | 4 h |
| Config/Terraform | Git (infra as code); segredos em vault com backup | 0 | 30 min |

Backups criptografados (chaves separadas do dado), testados por **restore drill mensal automatizado**: restaura em ambiente isolado, roda suíte de integridade, mede RTO real. Backup não testado = inexistente.

## Desktop (dados do usuário)

- Banco local com WAL; snapshot local diário automático (retenção 7/4/12: diários/semanais/mensais).
- Backup opcional para destino do usuário (pasta, NAS, nuvem própria) — sempre criptografado com chave do usuário.
- Exportação completa em formato aberto (JSON + arquivos) a qualquer momento (LGPD e anti lock-in).
- Com sync ativo, a nuvem funciona como backup adicional E2E-criptografado; recuperar = autenticar novo dispositivo + chave de recuperação.
- **Chave de recuperação**: gerada no onboarding (frase impressa/salva pelo usuário). Perdeu senha + chave = dados E2E irrecuperáveis — decisão consciente, comunicada com clareza (privacy first).

## Cenários de desastre

| Cenário | Resposta |
|---|---|
| Corrupção de banco cloud | PITR para minuto anterior; validação de integridade; comunicação se houver janela de perda |
| Região cloud fora | Failover DNS para réplica cross-region (RTO 1 h) |
| Ransomware/comprometimento | Backups imutáveis (WORM) permitem restore limpo; rotação total de credenciais; postmortem público |
| Bug de migração destrói dados locais | Auto-snapshot pré-migração obrigatório no desktop; downgrade testado (doc 15) |
| Deleção acidental pelo usuário | Lixeira lógica 30 dias para documentos/memórias (exceto exclusão LGPD explícita, que é imediata e definitiva) |
