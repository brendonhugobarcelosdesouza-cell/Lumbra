#!/usr/bin/env bash
# Gera o cliente Dart da Lumbra Platform a partir do contrato OpenAPI.
#
# O contrato (core/contracts/platform-api-v1.json) é a ÚNICA fonte: este
# cliente nunca é escrito à mão, sempre regenerado. Assim ele não pode
# divergir da API — se o contrato muda, o cliente muda junto (docs/24).
#
# Uso (de qualquer lugar):  packages/lumbra_api_dart/generate.sh
# Requer: Node (npx) e Java 11+ (o openapi-generator é uma ferramenta Java).
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
CONTRATO="$RAIZ/core/contracts/platform-api-v1.json"
# gera num subdiretório dedicado: o pacote Dart inteiro vive em generated/,
# sem nunca tocar os arquivos autorais (generate.sh, README, .gitignore)
SAIDA="$AQUI/generated"

if [[ ! -f "$CONTRATO" ]]; then
  echo "contrato não encontrado: $CONTRATO" >&2
  echo "gere-o com: (cd core && python -m lumbra.api.contract)" >&2
  exit 1
fi

# versão do GERADOR fixada (o wrapper npm é 2.x; o gerador Java é 7.x):
# reprodutibilidade — a mesma entrada produz a mesma saída em toda máquina.
export OPENAPI_GENERATOR_VERSION="${OPENAPI_GENERATOR_VERSION:-7.14.0}"

echo "Gerando cliente Dart de $CONTRATO (openapi-generator $OPENAPI_GENERATOR_VERSION) ..."
rm -rf "$SAIDA"
npx --yes @openapitools/openapi-generator-cli@2.24.0 generate \
  --generator-name dart \
  --input-spec "$CONTRATO" \
  --output "$SAIDA" \
  --additional-properties=pubName=lumbra_api,pubVersion=0.1.0

echo "OK: cliente Dart em $SAIDA (lib/). Regenerado do contrato — não editar à mão."
