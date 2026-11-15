# Manda a fila.json da semana para o app na nuvem (GitHub), sem precisar instalar o git.
# Uso:
#   enviar-fila.ps1                       -> envia "Documentos\Varela Indica Telegram\fila.json"
#   enviar-fila.ps1 -Arquivo C:\...\x.json -> envia outro arquivo
# O token do GitHub fica em Documentos\github-token.txt (nunca mostre esse arquivo para ninguem).
param([string]$Arquivo = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Varela Indica Telegram\fila.json'),
      [string]$Repo = 'adrianevarela/varela-indica-app')

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$token = ([IO.File]::ReadAllText((Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'github-token.txt'))).Trim()
$cab   = @{ Authorization = "Bearer $token"; Accept = 'application/vnd.github+json'; 'User-Agent' = 'varela-indica' }
$url   = "https://api.github.com/repos/$Repo/contents/fila.json"

# confere se o JSON esta valido antes de mandar
$bytes = [IO.File]::ReadAllBytes($Arquivo)
$texto = (New-Object System.Text.UTF8Encoding($false)).GetString($bytes).TrimStart([char]0xFEFF)
$itens = @($texto | ConvertFrom-Json | ForEach-Object { $_ })
foreach ($i in $itens) {
  if (-not $i.quando -or -not $i.produto -or -not $i.link) { throw "Item sem quando/produto/link: $($i | ConvertTo-Json -Compress)" }
  [datetime]::ParseExact($i.quando, 'yyyy-MM-dd HH:mm', $null) | Out-Null
}

# junta com a fila que ja esta na nuvem: os produtos novos tomam o lugar do que estiver no mesmo horario
# (ex.: um produto da Shopee que o robo colocou), o resto continua
$sha = $null; $nuvem = @()
try {
  $atual = Invoke-RestMethod -Uri $url -Headers $cab
  $sha = $atual.sha
  $nuvem = @([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($atual.content -replace '\s', ''))) | ConvertFrom-Json | ForEach-Object { $_ })
} catch { }
$horarios = @($itens | ForEach-Object { $_.quando })
$juntos = @($itens) + @($nuvem | Where-Object { $_ -and $horarios -notcontains $_.quando }) | Sort-Object quando
$texto = ConvertTo-Json @($juntos) -Depth 6
$corpo = @{ message = "Fila da semana ($($itens.Count) produtos)"; content = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($texto)) }
if ($sha) { $corpo.sha = $sha }
try {
  Invoke-RestMethod -Method Put -Uri $url -Headers $cab -ContentType 'application/json' -Body ($corpo | ConvertTo-Json) | Out-Null
} catch {
  throw ("GitHub recusou: " + ($_.Exception.Message -replace [regex]::Escape($token), '***'))
}
# a partir de agora quem manda no Telegram e a nuvem: o enviar.ps1 do PC para, para nao duplicar
Set-Content -Path (Join-Path $PSScriptRoot 'NUVEM-ATIVA.txt') -Value 'O app na nuvem (GitHub) envia o Telegram. Apague este arquivo para o PC voltar a enviar.' -Encoding UTF8
Write-Output "Fila enviada: $($itens.Count) produtos novos ($($juntos.Count) no total), de $($itens[0].quando) a $($itens[-1].quando)."
