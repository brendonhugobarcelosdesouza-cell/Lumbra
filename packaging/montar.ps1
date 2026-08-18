# Monta a Lumbra inteira: o app com o No dentro (P2-f.3).
#
# O sidecar procura o No em "<pasta do app>\no\lumbra.exe" (ADR-067), e o
# pacote congelado ja se chama "no" - entao montar e, literalmente, copiar
# para o lugar certo. O que este script acrescenta e a PROVA de que o
# conjunto funciona depois de copiado, antes de existir instalador.
#
# Provar aqui importa porque o pacote congelado guarda caminhos relativos a
# si mesmo. Ele funcionar em core\dist nao garante que funcione dentro da
# pasta do app: e o mesmo tipo de suposicao que ja quebrou o Alembic quando
# rodamos de outro diretorio.

$ErrorActionPreference = "Stop"
$codificacaoAnterior = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$raiz = Split-Path -Parent $PSScriptRoot
$core = Join-Path $raiz "core"
$app = Join-Path $raiz "clients\app"
$noConstruido = Join-Path $core "dist\no"
$release = Join-Path $app "build\windows\x64\runner\Release"

Write-Host ""
Write-Host "== Lumbra: montando o conjunto ==" -ForegroundColor Cyan

# 1. O No -------------------------------------------------------------
$exeCongelado = Join-Path $noConstruido "lumbra.exe"
$precisaCongelar = $true
$motivo = "ainda nao congelado"

if (Test-Path $exeCongelado) {
    # O pacote e mais novo que o codigo? Reaproveitar um No desatualizado e
    # o pior tipo de economia: o conjunto monta, o script aprova, e o que vai
    # para o instalador e a versao ANTERIOR. Aconteceu na primeira montagem -
    # o No embalado ainda tinha o bug do .env que acabara de ser corrigido.
    $congeladoEm = (Get-Item $exeCongelado).LastWriteTime
    $fonteMaisNova = (Get-ChildItem (Join-Path $core "src") -Recurse -File -Include *.py |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    if ($null -ne $fonteMaisNova -and $fonteMaisNova.LastWriteTime -gt $congeladoEm) {
        $motivo = "o codigo mudou depois ($($fonteMaisNova.Name))"
    } else {
        $precisaCongelar = $false
    }
}

if ($precisaCongelar) {
    Write-Host "   congelando o No: $motivo" -ForegroundColor DarkGray
    & (Join-Path $core "packaging\construir.ps1")
    if ($LASTEXITCODE -ne 0) { throw "a construcao do No falhou" }
} else {
    Write-Host "   No congelado esta em dia" -ForegroundColor DarkGray
}

# 2. O app ------------------------------------------------------------
Write-Host ""
Write-Host "   compilando o app (release)..." -ForegroundColor DarkGray
Push-Location $app
try {
    flutter build windows --release
    if ($LASTEXITCODE -ne 0) { throw "flutter build falhou" }
}
finally {
    Pop-Location
}

$appExe = Join-Path $release "lumbra_app.exe"
if (-not (Test-Path $appExe)) { throw "app nao encontrado em $appExe" }

# 3. Juntar -----------------------------------------------------------
$destinoNo = Join-Path $release "no"
if (Test-Path $destinoNo) {
    # um postgres.exe vivo aqui dentro impede a copia com "Acesso negado"
    $presos = @(Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" |
        Where-Object { $_.ExecutablePath -like "$destinoNo*" })
    if ($presos.Count -gt 0) {
        Write-Host "   parando $($presos.Count) postgres.exe do pacote anterior..." -ForegroundColor Yellow
        $presos | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2
    }
    Remove-Item -Recurse -Force $destinoNo
}
Write-Host ""
Write-Host "   copiando o No para dentro do app..." -ForegroundColor DarkGray
Copy-Item -Recurse $noConstruido $destinoNo

$tamanho = [math]::Round(((Get-ChildItem $release -Recurse |
    Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host ""
Write-Host "== Conjunto montado: $tamanho MB ==" -ForegroundColor Cyan
Write-Host "   $release"

# 4. Provar -----------------------------------------------------------
# O No, rodando do lugar DEFINITIVO. Se algum caminho interno tiver
# ficado preso a core\dist, e aqui que se descobre.
Write-Host ""
Write-Host "== Conferindo o No no lugar final ==" -ForegroundColor Cyan
$temp = Join-Path $env:TEMP ("lumbra-montagem-" + [guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Path $temp -Force | Out-Null
$env:LUMBRA_DATA_DIR = $temp
$env:LUMBRA_PERSISTENCE = "embedded"
$env:LUMBRA_EVENTBUS = "memory"

try {
    $exe = Join-Path $destinoNo "lumbra.exe"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = "up --seguir-a-entrada"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $processo = New-Object System.Diagnostics.Process
    $processo.StartInfo = $psi
    $registro = New-Object System.Text.StringBuilder
    $aoSair = { if ($null -ne $EventArgs.Data) { [void]$registro.AppendLine($EventArgs.Data) } }
    Register-ObjectEvent -InputObject $processo -EventName OutputDataReceived -Action $aoSair | Out-Null
    Register-ObjectEvent -InputObject $processo -EventName ErrorDataReceived -Action $aoSair | Out-Null
    [void]$processo.Start()
    $processo.BeginOutputReadLine()
    $processo.BeginErrorReadLine()

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
        Write-Host "O No NAO respondeu de dentro do app. Log:" -ForegroundColor Red
        Write-Host $registro.ToString()
        if (-not $processo.HasExited) { $processo.Kill() }
        exit 1
    }
    Write-Host "   /health respondeu (No rodando de dentro do app)" -ForegroundColor Green

    $processo.StandardInput.Close()
    $null = $processo.WaitForExit(60000)
    Start-Sleep -Seconds 3

    Write-Host ""
    Write-Host "== Pronto para instalar ==" -ForegroundColor Green
    Write-Host "   app: $appExe"
    Write-Host "   no:  $destinoNo"
    Write-Host ""
    Write-Host "Para experimentar como usuario, feche o No do terminal e rode:" -ForegroundColor Cyan
    Write-Host "   $appExe"
}
finally {
    Remove-Item Env:\LUMBRA_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\LUMBRA_PERSISTENCE -ErrorAction SilentlyContinue
    Remove-Item Env:\LUMBRA_EVENTBUS -ErrorAction SilentlyContinue
    [Console]::OutputEncoding = $codificacaoAnterior
}
