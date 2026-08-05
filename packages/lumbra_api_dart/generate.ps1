# Gera o cliente Dart da Lumbra Platform a partir do contrato OpenAPI.
#
# Irmao do generate.sh, para Windows. Existe porque o `bash` do Windows
# costuma ser o do WSL: o script .sh monta caminhos no formato /mnt/c/... e
# entrega para um npx do Windows, que nao os entende -- e o gerador falha com
# "spec file is not found" apontando para um arquivo que existe. Aqui os
# caminhos sao nativos do comeco ao fim.
#
# SEM ACENTOS DE PROPOSITO: o PowerShell 5.1 le .ps1 como ANSI, e um arquivo
# UTF-8 sem BOM vira lixo no meio das strings ("terminador nao encontrado").
#
# Uso (de qualquer lugar):  .\packages\lumbra_api_dart\generate.ps1
# Requer: Node (npx) e Java 11+ (o openapi-generator e uma ferramenta Java).

$ErrorActionPreference = "Stop"

$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = (Resolve-Path (Join-Path $Aqui "..\..")).Path

# CAMINHOS RELATIVOS, COM BARRA NORMAL, RODANDO DA RAIZ: o gerador trata o
# --input-spec como URI, e um caminho absoluto do Windows quebra o parser
# Java ("Illegal character in opaque part at index 2" -- a barra invertida
# logo depois de "C:"). Relativo nao tem letra de unidade nem barra invertida,
# entao nao vira URI ambigua.
$Contrato = "core/contracts/platform-api-v1.json"
# gera num subdiretorio dedicado: o pacote Dart inteiro vive em generated/,
# sem nunca tocar os arquivos autorais (generate.sh/.ps1, README, .gitignore)
$Saida = "packages/lumbra_api_dart/generated"

Push-Location $Raiz
try {

if (-not (Test-Path $Contrato)) {
    Write-Error "contrato nao encontrado: $Raiz\$Contrato (gere com: cd core; python -m lumbra.api.contract)"
}

# versao do GERADOR fixada (o wrapper npm e 2.x; o gerador Java e 7.x):
# reprodutibilidade -- a mesma entrada produz a mesma saida em toda maquina.
if (-not $env:OPENAPI_GENERATOR_VERSION) { $env:OPENAPI_GENERATOR_VERSION = "7.14.0" }

Write-Host "Gerando cliente Dart de $Contrato ..."
if (Test-Path $Saida) { Remove-Item -Recurse -Force $Saida }

npx --yes "@openapitools/openapi-generator-cli@2.24.0" generate `
    --generator-name dart `
    --input-spec $Contrato `
    --output $Saida `
    --additional-properties=pubName=lumbra_api,pubVersion=0.1.0

if ($LASTEXITCODE -ne 0) { Write-Error "o gerador falhou (codigo $LASTEXITCODE)" }

Write-Host "OK: cliente Dart em $Raiz\$Saida (lib). Regenerado do contrato, nao editar a mao." -ForegroundColor Green

}
finally { Pop-Location }
