<#
.SYNOPSIS
    Conversa com o Lumbra pelo terminal, com a resposta em tempo real.

.EXAMPLE
    .\scripts\chat.ps1 -Email voce@exemplo.com -Password sua-senha
    .\scripts\chat.ps1 -Email voce@exemplo.com -Password sua-senha -Pergunta "Como funciona a busca hibrida?"

.NOTES
    Este arquivo e salvo em UTF-8 COM BOM de proposito: o Windows
    PowerShell 5.1 le .ps1 sem BOM como ANSI e quebra em acentos.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [Parameter(Mandatory = $true)][string]$Password,
    [string]$Pergunta,
    [string]$BaseUrl = "http://localhost:8000",
    [string]$ConversationId,
    [ValidateSet("local_only", "allow_cloud")][string]$Privacidade = "local_only",
    [string]$Provedor
)

$ErrorActionPreference = "Stop"

# No PowerShell 5.1 o System.Net.Http nem sempre vem carregado
try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch {}

function Get-LumbraToken {
    try {
        $resposta = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/auth/token" `
            -Body @{ username = $Email; password = $Password }
        return $resposta.access_token
    }
    catch {
        Write-Host "Falha no login. Se a conta ainda nao existe, crie com:" -ForegroundColor Yellow
        $corpo = @{ email = $Email; password = $Password } | ConvertTo-Json -Compress
        Write-Host "  Invoke-RestMethod -Method Post -Uri '$BaseUrl/api/v1/auth/register' -ContentType 'application/json' -Body '$corpo'" -ForegroundColor Yellow
        throw
    }
}

$token = Get-LumbraToken
$headers = @{ Authorization = "Bearer $token" }

if (-not $ConversationId) {
    $corpo = @{ privacy = $Privacidade }
    if ($Provedor) { $corpo.provider = $Provedor }
    $conversa = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/chat/conversations" `
        -Headers $headers -ContentType "application/json" -Body ($corpo | ConvertTo-Json -Compress)
    $ConversationId = $conversa.conversation_id
    Write-Host ("Conversa {0} (privacidade: {1})" -f $ConversationId, $conversa.privacy) -ForegroundColor DarkGray
}

function Send-Streaming {
    param([string]$Texto)

    $url = "$BaseUrl/api/v1/chat/conversations/$ConversationId/messages/stream"
    $cliente = New-Object System.Net.Http.HttpClient
    $cliente.Timeout = [TimeSpan]::FromMinutes(10)
    $cliente.DefaultRequestHeaders.Authorization = `
        New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $token)

    $json = @{ content = $Texto } | ConvertTo-Json -Compress
    $payload = New-Object System.Net.Http.StringContent($json, [System.Text.Encoding]::UTF8, "application/json")

    # SendAsync (nao PostAsync) e quem aceita HttpCompletionOption; sem
    # ResponseHeadersRead o .NET so devolve depois do corpo INTEIRO, ou
    # seja: nada de streaming.
    $requisicaoHttp = New-Object System.Net.Http.HttpRequestMessage(
        [System.Net.Http.HttpMethod]::Post, $url)
    $requisicaoHttp.Content = $payload

    try {
        $requisicao = $cliente.SendAsync(
            $requisicaoHttp,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()

        if (-not $requisicao.IsSuccessStatusCode) {
            $erro = $requisicao.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            Write-Host ("HTTP {0}: {1}" -f $requisicao.StatusCode, $erro) -ForegroundColor Red
            return
        }

        $stream = $requisicao.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $leitor = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
        $evento = ""
        $pediuCancelar = $false

        while (-not $leitor.EndOfStream) {
            # ESC durante a geracao pede o cancelamento (ADR-032): o modelo
            # para de gerar e libera a GPU, e o texto ja produzido e salvo
            if (-not $pediuCancelar -and [Console]::KeyAvailable) {
                $tecla = [Console]::ReadKey($true)
                if ($tecla.Key -eq "Escape") {
                    $pediuCancelar = $true
                    Invoke-RestMethod -Method Post -Headers $headers `
                        -Uri "$BaseUrl/api/v1/chat/conversations/$ConversationId/messages/cancel" | Out-Null
                }
            }
            $linha = $leitor.ReadLine()

            if ($linha.StartsWith("event:")) {
                $evento = $linha.Substring(6).Trim()
                continue
            }
            if (-not $linha.StartsWith("data:")) { continue }

            $dados = $linha.Substring(5).Trim() | ConvertFrom-Json

            switch ($evento) {
                "sources" {
                    if ($dados.citations -and $dados.citations.Count -gt 0) {
                        Write-Host "`nFontes consultadas:" -ForegroundColor DarkCyan
                        foreach ($c in $dados.citations) {
                            $titulo = if ($c.title) { $c.title } else { $c.kind }
                            Write-Host ("  [{0}] {1}" -f $c.ordinal, $titulo) -ForegroundColor DarkCyan
                        }
                        Write-Host ""
                    }
                    else {
                        Write-Host "`n(nenhuma fonte encontrada nos seus dados)`n" -ForegroundColor DarkGray
                    }
                }
                "token" { Write-Host -NoNewline $dados.delta }
                "done" {
                    Write-Host ""
                    Write-Host ("[{0} / {1}] {2} tokens de entrada, {3} de saida" -f `
                            $dados.provider, $dados.model, $dados.usage.in, $dados.usage.out) -ForegroundColor DarkGray
                }
                "cancelled" {
                    Write-Host ""
                    Write-Host ("[interrompido: {0}, pedido por {1}] parcial salvo: {2}" -f `
                            $dados.reason, $dados.requested_by, $dados.partial_saved) -ForegroundColor DarkYellow
                }
                "error" { Write-Host ("`nErro: {0}" -f $dados.detail) -ForegroundColor Red }
            }
        }
    }
    finally {
        $requisicaoHttp.Dispose()
        $cliente.Dispose()
    }
}

function Send-Anexo {
    param([string]$Caminho)

    if (-not (Test-Path $Caminho)) {
        Write-Host "Arquivo nao encontrado: $Caminho" -ForegroundColor Red
        return
    }
    $arquivo = Get-Item $Caminho
    $cliente = New-Object System.Net.Http.HttpClient
    $cliente.Timeout = [TimeSpan]::FromMinutes(10)
    $cliente.DefaultRequestHeaders.Authorization = `
        New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $token)

    try {
        $form = New-Object System.Net.Http.MultipartFormDataContent
        $bytes = [System.IO.File]::ReadAllBytes($arquivo.FullName)
        $conteudo = New-Object System.Net.Http.ByteArrayContent($bytes)
        $conteudo.Headers.ContentType = `
            New-Object System.Net.Http.Headers.MediaTypeHeaderValue("application/octet-stream")
        $form.Add($conteudo, "file", $arquivo.Name)

        $url = "$BaseUrl/api/v1/chat/conversations/$ConversationId/attachments"
        $resposta = $cliente.PostAsync($url, $form).GetAwaiter().GetResult()
        $corpo = $resposta.Content.ReadAsStringAsync().GetAwaiter().GetResult()

        if (-not $resposta.IsSuccessStatusCode) {
            Write-Host ("Falha no anexo (HTTP {0}): {1}" -f $resposta.StatusCode, $corpo) -ForegroundColor Red
            return
        }
        $dados = $corpo | ConvertFrom-Json
        if ($dados.state -eq "ready") {
            Write-Host ("Anexado: {0} - {1} trechos indexados e citaveis" -f `
                    $arquivo.Name, $dados.chunks) -ForegroundColor DarkYellow
        }
        else {
            Write-Host ("Anexado: {0} - estado '{1}' ({2})" -f `
                    $arquivo.Name, $dados.state, $dados.detail) -ForegroundColor DarkYellow
        }
    }
    finally {
        $cliente.Dispose()
    }
}

function Show-Anexos {
    $lista = Invoke-RestMethod -Method Get -Headers $headers `
        -Uri "$BaseUrl/api/v1/chat/conversations/$ConversationId/attachments"
    if ($lista.attachments.Count -eq 0) {
        Write-Host "Nenhum anexo nesta conversa." -ForegroundColor DarkGray
        return
    }
    Write-Host "`nAnexos:" -ForegroundColor DarkCyan
    foreach ($a in $lista.attachments) {
        Write-Host ("  {0,-30} {1,-12} {2}" -f $a.filename, $a.state, $(if ($a.detail) { $a.detail } else { "" })) -ForegroundColor DarkCyan
    }
    Write-Host ""
}

function Show-Provedores {
    $menu = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/v1/chat/providers" -Headers $headers
    Write-Host "`nProvedores disponiveis:" -ForegroundColor DarkCyan
    foreach ($p in $menu.providers) {
        if ($p.is_local) {
            $tipo = "local, sem custo"
        }
        else {
            $tipo = "nuvem, USD {0:N2} entrada / {1:N2} saida por 1M tokens" -f `
                $p.input_price_per_mtok, $p.output_price_per_mtok
        }
        Write-Host ("  {0,-16} {1,-32} ({2})" -f $p.name, $p.model, $tipo) -ForegroundColor DarkCyan
    }
    Write-Host ""
}

function Set-Provedor {
    param([string]$Nome)

    $corpo = @{ provider = $Nome }
    # provedor de nuvem exige o opt-in explicito de privacidade
    if ($Nome -ne "") { $corpo.privacy = "allow_cloud" }
    try {
        $novo = Invoke-RestMethod -Method Patch `
            -Uri "$BaseUrl/api/v1/chat/conversations/$ConversationId/policy" `
            -Headers $headers -ContentType "application/json" -Body ($corpo | ConvertTo-Json -Compress)
        Write-Host ("Agora usando: {0} (privacidade: {1})" -f `
            $(if ($novo.provider) { $novo.provider } else { "roteamento padrao, local primeiro" }), `
                $novo.privacy) -ForegroundColor DarkYellow
    }
    catch {
        Write-Host ("Nao foi possivel trocar: {0}" -f $_.ErrorDetails.Message) -ForegroundColor Red
    }
}

function Index-Pasta {
    param([string]$Caminho, [bool]$Forcar = $false)

    if (-not (Test-Path $Caminho)) {
        Write-Host "Pasta nao encontrada: $Caminho" -ForegroundColor Red
        return
    }
    if (-not (Test-Path $Caminho -PathType Container)) {
        Write-Host "Nao e uma pasta: $Caminho" -ForegroundColor Red
        return
    }

    $rotulo = if ($Forcar) { "Reindexando (forcado)" } else { "Indexando" }
    Write-Host ("{0} {1} (pode demorar minutos)..." -f $rotulo, $Caminho) -ForegroundColor DarkYellow
    try {
        $corpo = @{
            kind    = "skill"
            name    = "document.index"
            payload = @{ path = (Resolve-Path $Caminho).Path; force = $Forcar }
        } | ConvertTo-Json -Compress
        $inicio = Invoke-RestMethod -Method Post -Headers $headers `
            -Uri "$BaseUrl/api/v1/dev/executions" `
            -ContentType "application/json" -Body $corpo

        # a indexacao roda em segundo plano: consultamos o resultado ate concluir
        $execId = $inicio.execution_id
        $exec = $null
        for ($i = 0; $i -lt 600; $i++) {
            Start-Sleep -Milliseconds 500
            $registro = Invoke-RestMethod -Method Get -Headers $headers `
                -Uri "$BaseUrl/api/v1/dev/executions/$execId"
            $exec = $registro.execution
            if ($exec.status -ne "running") { break }
        }

        if ($exec.status -eq "completed") {
            $out = $exec.output
            Write-Host ("OK: {0} descoberto(s), {1} indexado(s), {2} inalterado(s)" -f `
                    $out.discovered, $out.queued, $out.unchanged) -ForegroundColor Green
        }
        elseif ($exec.status -eq "running") {
            Write-Host "Ainda processando em segundo plano. Consulte com /anexos ou aguarde." -ForegroundColor DarkYellow
        }
        else {
            Write-Host ("Indexacao terminou como '{0}': {1}" -f `
                    $exec.status, $exec.error) -ForegroundColor Red
        }
    }
    catch {
        Write-Host ("Falha na indexacao: {0}" -f $_.ErrorDetails.Message) -ForegroundColor Red
    }
}

if ($Pergunta) {
    Send-Streaming -Texto $Pergunta
}
else {
    Write-Host ("Conversando. Conversa: {0}" -f $ConversationId) -ForegroundColor DarkGray
    Write-Host "Comandos: /anexar <arquivo>  /anexos  /indexar <pasta>  /reindexar <pasta>  /provedores  /usar <nome>  /padrao" -ForegroundColor DarkGray
    Write-Host "ESC durante a resposta cancela a geracao. Linha vazia encerra." -ForegroundColor DarkGray
    while ($true) {
        Write-Host "`nvoce> " -NoNewline -ForegroundColor Green
        $entrada = Read-Host
        if ([string]::IsNullOrWhiteSpace($entrada)) { break }

        if ($entrada -eq "/anexos") { Show-Anexos; continue }
        if ($entrada -like "/anexar *") { Send-Anexo -Caminho $entrada.Substring(8).Trim('"'); continue }
        if ($entrada -like "/reindexar *") { Index-Pasta -Caminho $entrada.Substring(11).Trim('"') -Forcar $true; continue }
        if ($entrada -like "/indexar *") { Index-Pasta -Caminho $entrada.Substring(9).Trim('"'); continue }
        if ($entrada -eq "/provedores") { Show-Provedores; continue }
        if ($entrada -eq "/padrao") { Set-Provedor -Nome ""; continue }
        if ($entrada -like "/usar *") { Set-Provedor -Nome $entrada.Substring(6).Trim(); continue }

        Send-Streaming -Texto $entrada
    }
}
