#Requires -Version 5.1
<#
.SYNOPSIS
  dsh-creative-studio 一键引导：准备独立运行时（Python venv + 依赖 + 模型）。
.DESCRIPTION
  任意一台装了 DSH 的 Windows 机器上运行本脚本即可获得可用的美工/剪辑工具链。
  幂等：重复运行会跳过已就绪的部分；-Force 重建运行时。
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -Tier core          # 只装图片基础能力
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -Proxy http://127.0.0.1:7897
#>
[CmdletBinding()]
param(
  [ValidateSet('core', 'full')][string]$Tier = 'full',
  [string]$Mirror = 'https://pypi.tuna.tsinghua.edu.cn/simple',
  [switch]$NoMirror,
  [string]$Proxy = '',
  [switch]$Gpu,
  [switch]$SkipModels,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
$pkg = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $pkg 'runtime'
$py = Join-Path $runtime 'Scripts\python.exe'
$cs = Join-Path $pkg 'toolkit\cs.py'

function Info($m) { Write-Host "[bootstrap] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[   ok   ] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[  warn  ] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[  fail  ] $m" -ForegroundColor Red; exit 1 }

if ($Proxy) {
  $env:HTTP_PROXY = $Proxy; $env:HTTPS_PROXY = $Proxy
  Info "使用代理：$Proxy"
}

# ---------------------------------------------------------------- 1) 找到或获取 uv
$uv = $null
foreach ($cand in @('uv', 'uv.exe')) {
  $c = Get-Command $cand -ErrorAction SilentlyContinue
  if ($c) { $uv = $c.Source; break }
}
if (-not $uv) {
  foreach ($p in @(
      (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
      (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe'),
      (Join-Path $env:LOCALAPPDATA 'Programs\uv\uv.exe'),
      (Join-Path $pkg 'tools\uv\uv.exe'))) {
    if (Test-Path $p) { $uv = $p; break }
  }
}
if (-not $uv) {
  Info '未找到 uv，尝试下载独立二进制（单文件，无需管理员）...'
  try {
    $zip = Join-Path $env:TEMP 'uv-windows.zip'
    $url = 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip'
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 180
    $dest = Join-Path $pkg 'tools\uv'
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Expand-Archive -Path $zip -DestinationPath $dest -Force
    $found = Get-ChildItem $dest -Recurse -Filter 'uv.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $uv = $found.FullName; Ok "uv 就绪：$uv" }
  } catch {
    Warn "uv 下载失败：$($_.Exception.Message)"
  }
}

# ---------------------------------------------------------------- 2) 创建独立运行时
if ((Test-Path $py) -and -not $Force) {
  Ok "运行时已存在：$runtime"
} else {
  if ($uv) {
    Info '用 uv 创建运行时（Python 3.12）...'
    & $uv venv $runtime --python 3.12 2>&1 | Out-Host
  } else {
    $sys = $null
    foreach ($cand in @('py', 'python', 'python3')) {
      $c = Get-Command $cand -ErrorAction SilentlyContinue
      if ($c) { $sys = $c.Source; break }
    }
    if (-not $sys) {
      Die '既没有 uv 也没有可用的 Python。请先安装 Python 3.10+（或联网后重跑本脚本自动下载 uv）。'
    }
    Info "用系统 Python 创建运行时：$sys"
    & $sys -m venv $runtime 2>&1 | Out-Host
  }
}
if (-not (Test-Path $py)) { Die '运行时创建失败：找不到 runtime\Scripts\python.exe' }

# ---------------------------------------------------------------- 3) 分层安装依赖
$mirrorArgs = @()
if (-not $NoMirror) { $mirrorArgs = @('-i', $Mirror) }

Info '升级 pip ...'
& $py -m pip install -q --upgrade pip @mirrorArgs 2>&1 | Out-Host

$pkgs = @('pillow', 'numpy', 'imageio-ffmpeg')          # T0 图片 + T2 视频底座
if ($Tier -eq 'full') { $pkgs += @('rembg', 'onnxruntime') }   # T1 抠图
if ($Gpu) {
  $pkgs = $pkgs | Where-Object { $_ -ne 'onnxruntime' }
  $pkgs += 'onnxruntime-gpu'
  Warn 'onnxruntime-gpu 需要机器上可用的 CUDA/cuDNN 运行库；缺失时会自动回退 to CPU。'
}
Info ("安装依赖：{0}" -f ($pkgs -join ', '))
& $py -m pip install -q @pkgs @mirrorArgs 2>&1 | Out-Host

# ---------------------------------------------------------------- 4) 预取模型
if ($Tier -eq 'full' -and -not $SkipModels) {
  $model = Join-Path $env:USERPROFILE '.rembg\models\u2net\u2net.onnx'
  if (Test-Path $model) {
    Ok "抠图模型已存在：$model"
  } else {
    Info '预取抠图模型 u2net（约 176MB，来自 GitHub releases）...'
    try {
      & $py -c "from rembg import new_session; new_session('u2net'); print('u2net ready')" 2>&1 | Out-Host
    } catch {
      Warn "模型预取失败（可在首次 matte 时自动重试）：$($_.Exception.Message)"
    }
  }
}

# ---------------------------------------------------------------- 5) 自检
Info '运行 doctor 自检 ...'
& $py $cs doctor --json 2>&1 | Out-Host
Ok '引导完成。可用 scripts\install-into-dsh.ps1 把技能装进 DSH。'
