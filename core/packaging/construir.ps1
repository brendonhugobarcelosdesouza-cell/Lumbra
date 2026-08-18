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

# O No fala UTF-8; sem isto o console decodifica com a pagina de codigo
# antiga e "indices" chega como "Yndices". Log ilegivel e log que ninguem le.
$codificacaoAnterior = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

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

# Um postgres.exe de uma execucao anterior segura os arquivos do proprio
# pacote, e a reconstrucao morre com "Acesso negado" - um erro que nao diz
# nada sobre a causa. Melhor avisar antes de tentar.
$presos = @(Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" |
    Where-Object { $_.ExecutablePath -like "$saida*" })
if ($presos.Count -gt 0) {
    Write-Host "Ha $($presos.Count) postgres.exe rodando de DENTRO do pacote anterior." -ForegroundColor Yellow
    Write-Host "Eles seguram os arquivos e a reconstrucao falharia. Parando..." -ForegroundColor Yellow
    $presos | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
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

    # Subimos do jeito que o APP sobe: com --seguir-a-entrada, e depois
    # fechando a entrada padrao. Nao e detalhe de teste - e o unico jeito de
    # provar que o encerramento limpo (ADR-071) funciona no executavel
    # congelado. A versao anterior deste script derrubava o No com
    # Stop-Process -Force e deixava um postgres.exe segurando os arquivos do
    # proprio pacote: a reconstrucao seguinte falhava com "Acesso negado".
    # O script reproduzia, nele mesmo, o bug que o produto tinha acabado de
    # consertar.
    Write-Host ""
    Write-Host "   subindo o No congelado..." -ForegroundColor DarkGray
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = "up --seguir-a-entrada"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $processo = New-Object System.Diagnostics.Process
    $processo.StartInfo = $psi

    # consumir a saida e obrigatorio: cano cheio TRAVA o filho, e o sintoma
    # (fica lento e para) nao parece ter relacao nenhuma com log
    $registro = New-Object System.Text.StringBuilder
    $aoSair = {
        if ($null -ne $EventArgs.Data) { [void]$registro.AppendLine($EventArgs.Data) }
    }
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
        Write-Host ""
        Write-Host "O No congelado NAO respondeu. Log:" -ForegroundColor Red
        Write-Host $registro.ToString()
        if (-not $processo.HasExited) { $processo.Kill() }
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
        $processo.StandardInput.Close()
        $null = $processo.WaitForExit(60000)
        exit 1
    }

    # Fechar a entrada e PEDIR que o No encerre. Se o pacote estiver certo,
    # ele desliga o Postgres antes de sair (ADR-071 + o conserto dos donos
    # fantasmas). Este e o teste mais valioso do script.
    Write-Host ""
    Write-Host "   pedindo o encerramento (fechando a entrada padrao)..." -ForegroundColor DarkGray
    $processo.StandardInput.Close()
    if (-not $processo.WaitForExit(60000)) {
        Write-Host "O No congelado nao encerrou em 60s." -ForegroundColor Red
        $processo.Kill()
        exit 1
    }
    Start-Sleep -Seconds 3

    $sobrou = @(Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" |
        Where-Object { $_.CommandLine -like "*$temp*" })
    if ($sobrou.Count -gt 0) {
        Write-Host ""
        Write-Host "O No saiu, mas deixou $($sobrou.Count) postgres.exe de pe." -ForegroundColor Red
        Write-Host "E o bug dos donos fantasmas voltando - nao siga sem investigar." -ForegroundColor Red
        $sobrou | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        exit 1
    }

    Write-Host "   encerrou sozinho e desligou o banco junto" -ForegroundColor Green
    Write-Host ""
    Write-Host "== O No congelado sobe, migra, responde e sai limpo ==" -ForegroundColor Green
    Write-Host "   $exe"
}
finally {
    Remove-Item Env:\LUMBRA_DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:\LUMBRA_PERSISTENCE -ErrorAction SilentlyContinue
    Remove-Item Env:\LUMBRA_EVENTBUS -ErrorAction SilentlyContinue
    [Console]::OutputEncoding = $codificacaoAnterior
}
