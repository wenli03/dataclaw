# 解析可用的 Python 解释器：优先显式指定，其次系统 python，最后 DSH 运行时
function Resolve-DataClawPython {
  $candidates = @()
  if ($env:DATACLAW_PYTHON) { $candidates += $env:DATACLAW_PYTHON }
  $candidates += @(
    "python",
    "py",
    "$env:USERPROFILE\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
  )
  foreach ($c in $candidates) {
    if (-not (Get-Command $c -ErrorAction SilentlyContinue)) {
      if (-not (Test-Path $c)) { continue }
    }
    try {
      & $c -c "import fastapi, sqlalchemy, sqlglot" 2>$null
      if ($LASTEXITCODE -eq 0) { return $c }
    } catch { }
  }
  throw "找不到已安装依赖的 Python（需 fastapi/sqlalchemy/sqlglot）。请先 pip install -r backend/requirements.txt，或设置 DATACLAW_PYTHON 指向解释器。"
}

function Get-DataClawPnpm {
  if (Get-Command pnpm -ErrorAction SilentlyContinue) { return "pnpm" }
  return "npm"
}
