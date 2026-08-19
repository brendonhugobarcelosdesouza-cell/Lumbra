# Gera o instalador da Lumbra (P2-f.3).
#
# Tres etapas, nesta ordem: montar o conjunto (app + No), preparar o modelo
# de embeddings para viajar junto, e compilar o .iss.
#
# ASCII puro: o PowerShell 5.1 le .ps1 como ANSI, e um travessao no meio de
# uma string quebra o script inteiro com um erro que nao menciona acentuacao.

$ErrorActionPreference = "Stop"
$codificacaoAnterior = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$raiz = Split-Path -Parent $PSScriptRoot
$saida = Join-Path $raiz "dist"
$iss = Join-Path $PSScriptRoot "lumbra.iss"
$release = Join-Path $raiz "clients\app\build\windows\x64\runner\Release"
$modelosDestino = Join-Path $saida "modelos"

Write-Host ""
Write-Host "== Lumbra: gerando o instalador ==" -ForegroundColor Cyan

# 1. O compilador --------------------------------------------------------
$iscc = $null
foreach ($caminho in @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)) {
    if (Test-Path $caminho) { $iscc = $caminho; break }
}
if ($null -eq $iscc) {
    $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
}
if ($null -eq $iscc) {
    Write-Host "Inno Setup nao encontrado." -ForegroundColor Red
    Write-Host "Instale de https://jrsoftware.org/isdl.php (ou: winget install JRSoftware.InnoSetup)" -ForegroundColor Yellow
    exit 1
}
Write-Host "   compilador: $iscc" -ForegroundColor DarkGray

# 2. O conjunto ----------------------------------------------------------
if (-not (Test-Path (Join-Path $release "lumbra_app.exe"))) {
    Write-Host "   conjunto ainda nao montado; montando..." -ForegroundColor DarkGray
    & (Join-Path $PSScriptRoot "montar.ps1")
    if ($LASTEXITCODE -ne 0) { throw "a montagem falhou" }
}

# 3. O modelo ------------------------------------------------------------
# Vai junto para que a PRIMEIRA execucao nao exija internet nem minutos de
# espera calada. A copia e feita arquivo a arquivo de proposito: o cache do
# fastembed usa LINKS SIMBOLICOS (formato do HuggingFace), e copia-los como
# links produziria um pacote com atalhos quebrados na maquina do outro. Ler
# e escrever materializa os bytes.
$modelosOrigem = Join-Path $env:LOCALAPPDATA "Lumbra\modelos"
if (-not (Test-Path $modelosOrigem)) {
    Write-Host ""
    Write-Host "Modelo de embeddings ausente em $modelosOrigem" -ForegroundColor Yellow
    Write-Host "Abra a Lumbra uma vez para ele ser baixado, e rode de novo." -ForegroundColor Yellow
    Write-Host "(Sem ele o instalador sai menor, mas a primeira execucao do" -ForegroundColor Yellow
    Write-Host " usuario vai exigir internet.)" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "   materializando o modelo para o pacote..." -ForegroundColor DarkGray
    if (Test-Path $modelosDestino) { Remove-Item $modelosDestino -Recurse -Force }
    New-Item -ItemType Directory -Path $modelosDestino -Force | Out-Null
    Get-ChildItem $modelosOrigem -Recurse -File | ForEach-Object {
        $relativo = $_.FullName.Substring($modelosOrigem.Length).TrimStart('\')
        $alvo = Join-Path $modelosDestino $relativo
        New-Item -ItemType Directory -Path (Split-Path -Parent $alvo) -Force | Out-Null
        # -Force le o conteudo REAL mesmo quando a origem e um link
        Copy-Item $_.FullName $alvo -Force
    }
    $mb = [math]::Round(((Get-ChildItem $modelosDestino -Recurse -File |
        Measure-Object Length -Sum).Sum / 1MB), 0)
    Write-Host "   modelo: $mb MB" -ForegroundColor DarkGray
}

# 4. Compilar ------------------------------------------------------------
Write-Host ""
Write-Host "   compilando o instalador..." -ForegroundColor DarkGray
& $iscc /Q $iss
if ($LASTEXITCODE -ne 0) { throw "o Inno Setup falhou" }

$instalador = Get-ChildItem $saida -Filter "Lumbra-*-instalador.exe" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $instalador) { throw "instalador nao encontrado em $saida" }

$mb = [math]::Round($instalador.Length / 1MB, 1)
Write-Host ""
Write-Host "== Instalador pronto: $mb MB ==" -ForegroundColor Green
Write-Host "   $($instalador.FullName)"
Write-Host ""
Write-Host "Teste como usuario: abra o instalador, instale, e procure" -ForegroundColor Cyan
Write-Host "'Lumbra' no menu Iniciar. Nao rode do repositorio." -ForegroundColor Cyan

[Console]::OutputEncoding = $codificacaoAnterior
