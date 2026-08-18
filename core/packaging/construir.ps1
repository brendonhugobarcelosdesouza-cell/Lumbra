# Constroi o No congelado e CONFERE que ele funciona.
#
# Escrito em ASCII puro de proposito: o PowerShell 5.1 le arquivos .ps1 como
# ANSI, e um travessao no meio de uma string quebra o script inteiro com um
# erro que nao menciona acentuacao nenhuma. Ja aconteceu neste repositorio.
#
# A verificacao no fim nao e zelo: um pacote que compila e nao roda e o
# resultado MAIS PROVAVEL aqui. Faltar um arquivo de dados nao quebra a
# compilacao - quebra a primeira execucao, na maquina de quem instalou.

$ErrorActionPreference = "Stop"

$core = Split-Path -Parent $PSScriptRoot
$saida = Join-Path $core "dist"
$spec = Join-Path $PSScriptRoot "lumbra.spec"

Write-Host ""
Write-Host "== Lumbra: congelando o No ==" -ForegroundColor Cyan
Write-Host "   core:  $core"
Write-Host "   saida: $saida"
Write-Host ""

# '2>&1 | Out-Null' e nao '2>$null': com ErrorActionPreference=Stop, o
# PowerShell 5.1 promove QUALQUER saida de erro de um programa externo a
# excecao fatal. O traceback do teste abaixo e esperado - e a resposta
# "nao esta instalado" - mas derrubava o script antes da mensagem amigavel.
# A verificacao gentil virava o erro mais feio da tela.
$temPyInstaller = $true
try {
    & python -c "import PyInstaller" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $temPyInstaller = $false }
} catch {
    $temPyInstaller = $false
}
if (-not $temPyInstaller) {
    Write-Host "PyInstaller ausente NESTE Python." -ForegroundColor Red
    Write-Host "Instale as dependencias de desenvolvimento:" -ForegroundColor Yellow
    Write-Host "   pip install -e .[dev]" -ForegroundColor Yellow
    exit 1
}

# QUAL Python esta sendo congelado decide o que entra no pacote: o
# empacotador embala as dependencias do interpretador que o executa, nao as
# do projeto. Rodar fora do ambiente virtual congela outro conjunto de
# bibliotecas - e o pacote pode ficar bom, ruim ou diferente sem aviso.
# Isto nao barra: informa, porque o resultado ainda e util e o dono da
# maquina decide.
$interpretador = (python -c "import sys; print(sys.executable)")
$noVenv = $interpretador -like "*\.venv\*"
Write-Host "   python: $interpretador"
if (-not $noVenv) {
    Write-Host ""
    Write-Host "AVISO: este Python nao e o do ambiente virtual do projeto." -ForegroundColor Yellow
    Write-Host "       O pacote vai levar as dependencias DELE. Para congelar" -ForegroundColor Yellow
    Write-Host "       o mesmo conjunto que voce testa, ative o venv antes:" -ForegroundColor Yellow
    Write-Host "       .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host ""
}

Push-Location $core
try {
    # --noconfirm: reconstruir e o caso normal, nao a excecao
    pyinstaller --noconfirm --clean --distpath $saida --workpath (Join-Path $core "build") $spec
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller falhou" }
}
finally {
    Pop-Location
}

$exe = Join-Path $saida "no\lumbra.exe"
if (-not (Test-Path $exe)) {
    Write-Host "Executavel nao encontrado em $exe" -ForegroundColor Red
    exit 1
}

$tamanho = [math]::Round(((Get-ChildItem (Join-Path $saida "no") -Recurse |
    Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host ""
Write-Host "== Pacote pronto: $tamanho MB ==" -ForegroundColor Cyan

# ---------------------------------------------------------------- prova
# Nao basta existir. As quatro coisas que o empacotador nao adivinha
# (PostgreSQL, migracoes, onnxruntime, adaptadores) so se denunciam AQUI.

Write-Host ""
Write-Host "== Conferindo o pacote (numa pasta de dados descartavel) ==" -ForegroundColor Cyan
$temp = Join-Path $env:TEMP ("lumbra-prova-" + [guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Path $temp -Force | Out-Null
$env:LUMBRA_DATA_DIR = $temp
$env:LUMBRA_PERSISTENCE = "embedded"
$env:LUMBRA_EVENTBUS = "memory"

try {
    & $exe version
    if ($LASTEXITCODE -ne 0) { throw "o executavel nao roda" }

    # `up` sobe o banco, migra e serve; damos 3 minutos e derrubamos fechando
    # a entrada padrao - o mesmo caminho que o app usa (ADR-071)
    Write-Host ""
    Write-Host "   subindo o No congelado..." -ForegroundColor DarkGray
    $processo = Start-Process -FilePath $exe -ArgumentList "up" `
        -RedirectStandardOutput (Join-Path $temp "saida.log") `
        -RedirectStandardError (Join-Path $temp "erro.log") `
        -PassThru -NoNewWindow
    $viva = $false
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 2
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) { $viva = $true; break }
        } catch { }
        if ($processo.HasExited) { break }
    }

    if (-not $viva) {
        Write-Host ""
        Write-Host "O No congelado NAO respondeu. Log:" -ForegroundColor Red
        Get-Content (Join-Path $temp "saida.log") -Tail 40 -ErrorAction SilentlyContinue
        Get-Content (Join-Path $temp "erro.log") -Tail 40 -ErrorAction SilentlyContinue
        if (-not $processo.HasExited) { Stop-Process -Id $processo.Id -Force }
        exit 1
    }

    Write-Host "   /health respondeu" -ForegroundColor Green

    # /health so prova que a API subiu. As partes que vem de ARQUIVOS DE
    # DADOS - pgvector, migracoes, indices, o modelo de embeddings - so se
    # denunciam quando alguem pergunta por elas. E o doctor pergunta.
    $diagnostico = (& $exe doctor --json) | ConvertFrom-Json
    $essenciais = @("postgres", "migracoes", "indices", "embeddings")
    $quebrados = @()
    foreach ($nome in $essenciais) {
        $item = $diagnostico.checks | Where-Object { $_.name -eq $nome }
        if ($null -eq $item -or $item.status -ne "ok") {
            $quebrados += "$nome ($($item.status)): $($item.summary)"
        } else {
            Write-Host "   $nome : $($item.summary)" -ForegroundColor Green
        }
    }
    if ($quebrados.Count -gt 0) {
        Write-Host ""
        Write-Host "O pacote subiu, mas falta coisa dentro dele:" -ForegroundColor Red
        $quebrados | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }
        Stop-Process -Id $processo.Id -Force
        exit 1
    }

    Stop-Process -Id $processo.Id -Force
    Start-Sleep -Seconds 3
    Get-Process postgres -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like "*$temp*" } |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "== O No congelado sobe, migra e responde ==" -ForegroundColor Green
    Write-Host "   $exe"
}
finally {
    Remove-Item Env:\LUMBRA_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\LUMBRA_PERSISTENCE -ErrorAction SilentlyContinue
    Remove-Item Env:\LUMBRA_EVENTBUS -ErrorAction SilentlyContinue
}
