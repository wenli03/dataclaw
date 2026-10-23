# DataClaw 开发模式：后端 8787 + 前端 5173（Vite 代理 /api）
param(
  [int]$ApiPort = 8787,
  [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "_env.ps1")
$py = Resolve-DataClawPython

Write-Host "==> 后端 http://127.0.0.1:$ApiPort （$py）" -ForegroundColor Green
$api = Start-Process -PassThru -WorkingDirectory "$root/backend" -WindowStyle Hidden `
  -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$ApiPort","--reload"

Write-Host "==> 前端 http://127.0.0.1:$WebPort" -ForegroundColor Green
Push-Location "$root/frontend"
try {
  $env:VITE_API_PORT = "$ApiPort"
  if (Get-Command pnpm -ErrorAction SilentlyContinue) { pnpm dev --port $WebPort }
  else { npm run dev -- --port $WebPort }
} finally {
  Pop-Location
  if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
}
