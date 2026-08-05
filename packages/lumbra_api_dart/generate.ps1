# Gera o cliente Dart da Lumbra Platform a partir do contrato OpenAPI.
#
# Irmão do generate.sh, para Windows. Existe porque o `bash` do Windows
# costuma ser o do WSL: o script .sh monta caminhos no formato /mnt/c/... e
# entrega para um npx do Windows, que não os entende — e o gerador falha com
# "spec file is not found" apontando para um arquivo que existe. Aqui os
# caminhos são nativos do começo ao fim.
#
# Uso (de qualquer lugar):  .\packages\lumbra_api_dart\generate.ps1
# Requer: Node (npx) e Java 11+ (o openapi-generator é uma ferramenta Java).

$ErrorActionPreference = "Stop"

$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = (Resolve-Path (Join-Path $Aqui "..\..")).Path
$Contrato = Join-Path $Raiz "core\contracts\platform-api-v1.json"
# gera num subdiretório dedicado: o pacote Dart inteiro vive em generated\,
# sem nunca tocar os arquivos autorais (generate.sh/.ps1, README, .gitignore)
$Saida = Join-Path $Aqui "generated"

if (-not (Test-Path $Contrato)) {
    Write-Error "contrato nao encontrado: $Contrato`nGere-o com: cd core; python -m lumbra.api.contract"
}

# versão do GERADOR fixada (o wrapper npm é 2.x; o gerador Java é 7.x):
# reprodutibilidade — a mesma entrada produz a mesma saída em toda máquina.
if (-not $env:OPENAPI_GENERATOR_VERSION) { $env:OPENAPI_GENERATOR_VERSION = "7.14.0" }

Write-Host "Gerando cliente Dart de $Contrato (openapi-generator $env:OPENAPI_GENERATOR_VERSION) ..."
if (Test-Path $Saida) { Remove-Item -Recurse -Force $Saida }

npx --yes "@openapitools/openapi-generator-cli@2.24.0" generate `
    --generator-name dart `
    --input-spec $Contrato `
    --output $Saida `
    --additional-properties=pubName=lumbra_api,pubVersion=0.1.0

if ($LASTEXITCODE -ne 0) { Write-Error "o gerador falhou (codigo $LASTEXITCODE)" }

Write-Host "OK: cliente Dart em $Saida (lib\). Regenerado do contrato — nao editar a mao." -ForegroundColor Green
