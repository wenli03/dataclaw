# DataClaw 测试（三个测试文件各自独立进程运行）
#
# 为什么分进程：三份测试都在导入期通过 DATACLAW_DATA_DIR 锁定临时数据目录
# （app.core.config 是模块级单例），同进程收集会互相覆盖，导致后者拿到前者的空库。
# 用独立进程运行 = 每份测试一个干净库，这也是 CI 里的推荐方式。
param(
  [string]$Only = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "_env.ps1")
$py = Resolve-DataClawPython
Push-Location "$root/backend"
$failed = @()
$suites = @(
  @{ name = "核心 API（认证/员工/技能/公共员工/审计/越权）"; cmd = "pytest"; args = @("tests/test_core_api.py", "-q") },
  @{ name = "Agent 运行时（三场景/SSE/HITL/权限降级）";         cmd = "pytest"; args = @("tests/test_runtime.py", "-q") },
  @{ name = "数据安全（种子/矩阵/SQL 网关/知识库/渠道）";       cmd = "script"; args = @("tests/test_data_api.py") }
)
try {
  foreach ($s in $suites) {
    if ($Only -and $s.name -notlike "*$Only*") { continue }
    Write-Host "`n===== $($s.name) =====" -ForegroundColor Cyan
    if ($s.cmd -eq "pytest") {
      & $py -m pytest @($s.args)
    } else {
      & $py @($s.args)
    }
    if ($LASTEXITCODE -ne 0) { $failed += $s.name }
  }
} finally { Pop-Location }

if ($failed.Count -gt 0) {
  Write-Host "`n[FAIL] $($failed -join ', ')" -ForegroundColor Red
  exit 1
}
Write-Host "`n[OK] 全部测试通过（每份测试使用独立临时数据目录，不污染 data/）" -ForegroundColor Green
