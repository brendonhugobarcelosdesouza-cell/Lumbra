# Testa as rotas /api/v1/playbooks (L1.5) de ponta a ponta.
#
# Existe porque colar comandos multilinha no PowerShell 5.1 gruda as linhas e
# quebra o teste por motivo errado. Aqui o script e um arquivo: roda igual.
#
# Uso:  .\scripts\testar_playbooks.ps1 -Email "voce@exemplo.com"

param(
    [Parameter(Mandatory = $true)][string]$Email,
    [string]$BaseUrl = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

function Post-Json($uri, $headers, $obj) {
    # PS 5.1 envia o corpo em ISO-8859-1: convertemos para UTF-8 na mao,
    # senao acento vira "error parsing the body".
    $json = $obj | ConvertTo-Json -Depth 6
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -ContentType "application/json; charset=utf-8" -Body $bytes
}

Write-Host "`n[1/5] autenticando..." -ForegroundColor Cyan
$senha = Read-Host "Senha de $Email" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($senha))
$tok = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/auth/token" -Body @{ username = $Email; password = $plain }
$h = @{ Authorization = "Bearer $($tok.access_token)" }
Write-Host "  ok" -ForegroundColor Green

Write-Host "`n[2/5] gravando procedimento (playbook.write, risco MEDIUM)..." -ForegroundColor Cyan
$corpo = @{
    title        = "Reindexar apos mudar a extracao"
    when_to_use  = "quando o pipeline de extracao muda e os chunks ficam obsoletos"
    steps        = @(
        "Reiniciar o No para carregar o codigo novo",
        "Rodar /reindexar na pasta com force=true",
        "Conferir no dev/search se o trecho esperado aparece"
    )
    pitfalls     = @("Reindexar sem reiniciar o No reprocessa com o codigo ANTIGO")
    verification = "o valor certo aparece no topo do dev/search"
}
try {
    $criado = Post-Json "$BaseUrl/api/v1/playbooks" $h $corpo
    Write-Host "  criado: $($criado.playbook_id)" -ForegroundColor Green
}
catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 409) {
        Write-Host "  409: a politica de aprovacao exige confirmacao humana (HITL). Esperado se o teto foi baixado." -ForegroundColor Yellow
        return
    }
    throw
}

Write-Host "`n[3/5] listando..." -ForegroundColor Cyan
(Invoke-RestMethod -Uri "$BaseUrl/api/v1/playbooks" -Headers $h).playbooks | Format-Table title, origin, uses

Write-Host "[4/5] buscando (e assim que o chat recupera o procedimento)..." -ForegroundColor Cyan
$busca = [uri]::EscapeDataString("chunks obsoletos extracao")
$hits = (Invoke-RestMethod -Uri "$BaseUrl/api/v1/playbooks/search?query=$busca" -Headers $h).hits
if ($hits.Count -eq 0) { Write-Host "  NENHUM hit - a busca lexical nao casou" -ForegroundColor Red }
else { $hits | ForEach-Object { Write-Host "  hit: $($_.title) (usos: $($_.uses))" -ForegroundColor Green } }

Write-Host "`n[5/5] busca sem relacao deve voltar vazia..." -ForegroundColor Cyan
$nada = (Invoke-RestMethod -Uri "$BaseUrl/api/v1/playbooks/search?query=receita+de+bolo" -Headers $h).hits
if ($nada.Count -eq 0) { Write-Host "  ok: vazio" -ForegroundColor Green }
else { Write-Host "  RUIM: trouxe $($nada.Count) resultado(s) sem relacao" -ForegroundColor Red }

Write-Host "`nPara apagar:  Invoke-RestMethod -Method Delete -Uri `"$BaseUrl/api/v1/playbooks/$($criado.playbook_id)`" -Headers `$h`n"
