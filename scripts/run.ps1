# DataClaw 一键启动（生产形态：单端口，前后端同源）
param(
  [int]$Port = 8787,
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "_env.ps1")
$py = Resolve-DataClawPython

Write-Host "==> DataClaw 启动（端口 $Port）" -ForegroundColor Cyan
Write-Host "    Python: $py"

if (-not $SkipBuild) {
  if (-not (Test-Path "$root/backend/app/static/index.html")) {
    Write-Host "==> 构建前端…" -ForegroundColor Yellow
    Push-Location "$root/frontend"
    try {
      if (Get-Command pnpm -ErrorAction SilentlyContinue) { pnpm install; pnpm build }
      else { npm install; npm run build }
    } finally { Pop-Location }
  }
}

Write-Host "==> http://127.0.0.1:$Port" -ForegroundColor Green
Push-Location "$root/backend"
try {
  & $py -m uvicorn app.main:app --host 127.0.0.1 --port $Port
} finally { Pop-Location }
