# AIE Windows 安装脚本
# 用法 (PowerShell, 项目根目录执行):
#   powershell -ExecutionPolicy Bypass -File scripts/install-windows.ps1
# 幂等: 已存在 .venv 且 aife 可用则跳过；失败给出可复制修复命令。
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Root = Resolve-Path (Join-Path $Root '..')
$Venv = Join-Path $Root '.venv'

function Fail($msg) {
    Write-Host "✘ $msg" -ForegroundColor Red
    Write-Host "   请修复后重试。" -ForegroundColor Yellow
    exit 1
}

Write-Host "==> 检查 Python (需要 3.10 - 3.12)..." -ForegroundColor Cyan
$py = $null
foreach ($cand in @('py', 'python', 'python3')) {
    try { $v = & $cand --version 2>$null; if ($v -match 'Python (\d+)\.(\d+)') { $maj, $min = [int]$Matches[1], [int]$Matches[2]; if ($maj -eq 3 -and $min -ge 10 -and $min -le 12) { $py = $cand; break } } } catch {}
}
if (-not $py) { Fail "未找到 Python 3.10-3.12。请到 https://www.python.org/downloads/ 安装，并勾选 'Add to PATH'。" }
Write-Host "    使用 $py ($(& $py --version 2>&1))" -ForegroundColor Green

if (Test-Path (Join-Path $Venv 'Scripts/aife.exe')) {
    Write-Host "==> 检测到已安装，跳过创建 venv。" -ForegroundColor Green
} else {
    Write-Host "==> 创建虚拟环境 $Venv ..." -ForegroundColor Cyan
    & $py -m venv $Venv
}

Write-Host "==> 安装 aife ..." -ForegroundColor Cyan
& "$Venv/Scripts/pip.exe" install -e $Root
if ($LASTEXITCODE -ne 0) { Fail "pip install 失败，请检查网络后重试。" }

# 验证
$activate = Join-Path $Venv 'Scripts/Activate.ps1'
& "$Venv/Scripts/python.exe" -c "import aife; print('aife', aife.__version__)" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "aife 导入失败。" }

Write-Host ""
Write-Host "✔ 安装完成！" -ForegroundColor Green
Write-Host "   下一步（在当前终端执行）:" -ForegroundColor Yellow
Write-Host "     . $activate" -ForegroundColor White
Write-Host "     aife setup      # 一键部署（安装 Ollama + 拉取模型 + 启动服务）" -ForegroundColor White
Write-Host "   或重新打开一个终端后执行: aife setup" -ForegroundColor White
