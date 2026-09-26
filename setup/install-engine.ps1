#Requires -Version 5.1
<#
.SYNOPSIS
    给本仓 ComfyUI 引擎装出可独立运行的虚拟环境（ComfyUI/.venv）。

.DESCRIPTION
    做四件事，顺序固定、每步都自检，任何一步失败即停并给出下一步提示：

      1. 建/复用 ComfyUI/.venv（Python 3.11）
      2. 装 PyTorch：默认按本机 NVIDIA 驱动装 CUDA 轮子（GPU 主算），
         没有 N 卡时自动回退 PyPI 的 CPU 轮子（-Cpu 可强制）
      3. 装 ComfyUI/requirements.txt 的其余依赖（把模板那一行剔出来，交给第 4 步）
      4. 装 comfyui-workflow-templates 全家桶（薄封装 + core + json + 6 个 media 缩略图包）

    为什么模板要单独走第 4 步（事实，不是猜的）：
    上游 ComfyUI/requirements.txt 钉了 comfyui-workflow-templates==0.11.70，它硬依赖
    media-assets-02==0.1.6 等 6 个 media 缩略图包。本机 pip 默认源是清华镜像，它只同步了
    其中 5 个，唯独 media-assets-02 在清华镜像上是 404，于是整份清单解析失败、一个包都
    装不进去。官方 PyPI 上 6 个 media 包都在，所以第 4 步改用官方源一次性装全家桶，
    让模板数据 + 缩略图都齐全 —— 否则前端模板库会因缩略图 404 而整片空白。

    过滤后的清单写在 .cache/ 下，每次运行都从上游 requirements.txt 重新派生，
    所以上游改清单时本脚本会自动跟上，不保存副本。

.PARAMETER PythonExe
    建 venv 用的解释器。默认按 py -3.11 -> py -3 -> python 的顺序找一个 >= 3.11 的。

.PARAMETER TorchIndex
    PyTorch 轮子索引名（cu130 / cu128 / cpu ...）。默认自动：有 NVIDIA GPU 用 cu130，
    否则 cpu。取值必须存在于 https://download.pytorch.org/whl/<name>。

.PARAMETER Cpu
    强制装 CPU 版 torch，忽略本机 N 卡。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup/install-engine.ps1
#>
[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [string]$TorchIndex = '',
    [switch]$Cpu
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ---- 路径：全部从脚本自身位置推导，不含任何机器专有盘符 ----
$SetupDir = $PSScriptRoot
$RepoRoot = Split-Path -Parent $SetupDir
$ComfyDir = Join-Path $RepoRoot 'ComfyUI'
$ComfyVenv = Join-Path $ComfyDir '.venv'
$VenvPython = Join-Path $ComfyVenv 'Scripts\python.exe'
$CacheDir = Join-Path $RepoRoot '.cache'
$FilteredReq = Join-Path $CacheDir 'engine-requirements.filtered.txt'

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "    !!  $Text" -ForegroundColor Yellow }

function Fail([string]$Message, [string]$Hint = '') {
    Write-Host "`n[X] $Message" -ForegroundColor Red
    if ($Hint) { Write-Host "    -> $Hint" -ForegroundColor Yellow }
    exit 1
}

# ---- 0. 上游在位检查 ----
if (-not (Test-Path (Join-Path $ComfyDir 'main.py'))) {
    Fail "没找到引擎入口：$ComfyDir\main.py" "确认 ComfyUI 上游仓库在 $ComfyDir"
}
$ReqFile = Join-Path $ComfyDir 'requirements.txt'
if (-not (Test-Path $ReqFile)) {
    Fail "没找到依赖清单：$ReqFile" "上游 ComfyUI 仓库不完整？"
}

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null

# ---- 1. 解释器与 venv ----
Write-Step '准备 Python 解释器'
$basePython = $null
$baseArgs = @()
if ($PythonExe -ne '') {
    if (-not (Test-Path $PythonExe)) { Fail "指定的解释器不存在：$PythonExe" }
    $basePython = $PythonExe
}
else {
    foreach ($candidate in @(@('py', @('-3.11')), @('py', @('-3')), @('python', @()))) {
        $exe = Get-Command $candidate[0] -ErrorAction SilentlyContinue
        if ($null -eq $exe) { continue }
        $probe = & $candidate[0] @($candidate[1] + @('-c', 'import sys;print(''%d.%d''%sys.version_info[:2])')) 2>$null
        if ($probe -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 11) {
            $basePython = $exe.Source
            $baseArgs = $candidate[1]
            break
        }
    }
}
if ($null -eq $basePython) {
    Fail '找不到 Python >= 3.11' '装一个 Python 3.11（ComfyUI 官方也是 3.11），或用 -PythonExe 指路'
}
$ver = & $basePython @($baseArgs + @('-c', 'import sys;print(''%d.%d.%d''%sys.version_info[:3])'))
Write-Ok "解释器 $basePython ($ver)"

if (Test-Path $VenvPython) {
    Write-Ok "复用已有 venv：$ComfyVenv"
}
else {
    Write-Host "    新建 venv：$ComfyVenv"
    & $basePython @($baseArgs + @('-m', 'venv', $ComfyVenv))
    if (-not (Test-Path $VenvPython)) { Fail "venv 建失败：$VenvPython 不存在" }
    Write-Ok 'venv 已创建'
}

& $VenvPython -m pip install --upgrade pip --quiet
Write-Ok ("pip " + (& $VenvPython -m pip --version).Split(' ')[1])

# ---- 2. torch：GPU 优先，CPU 兜底 ----
Write-Step '安装 PyTorch'

$hasNvidia = $false
if (-not $Cpu) {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($null -ne $smi) { $hasNvidia = $true }
}

if ($TorchIndex -eq '') { $TorchIndex = if ($hasNvidia) { 'cu130' } else { 'cpu' } }
if ($Cpu) { $TorchIndex = 'cpu' }

$torchIndexUrl = "https://download.pytorch.org/whl/$TorchIndex"
Write-Host "    索引 $torchIndexUrl  ($(if ($hasNvidia) { '检测到 NVIDIA GPU' } else { '未检测到 NVIDIA GPU' }))"

# 已装就跳过：download.pytorch.org 的大轮子下载很慢/会卡，别重复拉。
# 判据是「已装的轮子类型与本次目标是否同类」（+cuXXX vs +cpu）：
# 只判 -Cpu 的话，-TorchIndex cu128 会被静默忽略（已装 cu130 直接跳过），
# 而 -Cpu 又会在每次运行时白重下一遍 CPU 轮子。
$torchVer = (& $VenvPython -c "import torch;print(torch.__version__)" 2>$null | Select-Object -First 1)
$installed = if ($torchVer) { $torchVer.Trim() } else { '' }
$wantCudaTorch = $TorchIndex -ne 'cpu'
$hasCudaTorch = ($installed -ne '') -and ($installed -notmatch '\+cpu$')

if (($installed -ne '') -and ($hasCudaTorch -eq $wantCudaTorch)) {
    Write-Ok "torch 已装 $installed（目标 $TorchIndex 同类），跳过"
}
else {
    if ($installed -ne '') { Write-Warn2 "已装 $installed，与目标 $TorchIndex 不同类，按目标重装" }
    # 不钉死 torch/torchvision 版本：同一个索引内 pip 会自己解出互相匹配的一组
    & $VenvPython -m pip install --index-url $torchIndexUrl torch torchvision
    if ($LASTEXITCODE -ne 0) { Fail "torch 装失败（索引 $TorchIndex）" "换一个 -TorchIndex，或加 -Cpu" }
    Write-Ok 'torch / torchvision 已装'
}

# ---- 3. 其余依赖（上游清单，剔掉断链那一行）----
Write-Step '安装引擎依赖（上游清单去断链）'

$wanted = @()
$needle = 'comfyui-workflow-templates=='
foreach ($line in (Get-Content -LiteralPath $ReqFile)) {
    if ($line.TrimStart().StartsWith($needle)) { continue }
    $wanted += $line
}
# 模板那一行剔出来后交给第 4 步用官方源装全家桶，这里不再手加 core/json
Set-Content -LiteralPath $FilteredReq -Value $wanted -Encoding utf8
Write-Ok "过滤后的清单：$FilteredReq"

& $VenvPython -m pip install -r $FilteredReq
if ($LASTEXITCODE -ne 0) { Fail '引擎依赖装失败' "看上面的 pip 输出；清单在 $FilteredReq" }

# ---- 4. 模板全家桶：官方源装全量（薄封装 + core + json + 6 个 media 缩略图包）----
Write-Step '安装 comfyui-workflow-templates（数据 + 缩略图）'
$tplLine = (Get-Content -LiteralPath $ReqFile | Where-Object { $_.TrimStart().StartsWith($needle) } | Select-Object -First 1)
if ($null -ne $tplLine) {
    $pin = $tplLine.Trim()
    # 显式官方源：默认源（清华镜像）没同步 media-assets-02，会整份解析失败
    & $VenvPython -m pip install --index-url https://pypi.org/simple $pin
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "装 $pin 失败 —— 引擎仍可跑，但模板缩略图缺失、前端模板库会空白" }
    else { Write-Ok "已装 $pin（含 6 个 media 缩略图包）" }
}
else {
    Write-Warn2 '上游清单里已没有 comfyui-workflow-templates，跳过'
}

# ---- 5. 自检 ----
Write-Step '自检'
$check = @'
import sys, importlib
print("python     :", sys.version.split()[0])
import torch
print("torch      :", torch.__version__)
print("cuda build :", torch.version.cuda)
print("cuda ready :", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu        :", torch.cuda.get_device_name(0))
for mod in ("comfyui_frontend_package", "comfyui_workflow_templates", "folder_paths", "comfy.model_management"):
    try:
        importlib.import_module(mod)
        print("import ok  :", mod)
    except Exception as exc:
        print("import FAIL:", mod, "->", type(exc).__name__, exc)
'@
$checkFile = Join-Path $CacheDir 'engine-selfcheck.py'
Set-Content -LiteralPath $checkFile -Value $check -Encoding utf8
Push-Location $ComfyDir
try { & $VenvPython $checkFile } finally { Pop-Location }

Write-Host "`n[OK] 引擎环境就绪：$ComfyVenv" -ForegroundColor Green
Write-Host "     单独起引擎：& '$VenvPython' main.py --port 8188 --listen 127.0.0.1" -ForegroundColor Gray
