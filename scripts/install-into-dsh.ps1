#Requires -Version 5.1
<#
.SYNOPSIS
  把 dsh-creative-studio 的 skills 装进 DSH（用户级技能根），任意机器一次即可。
.DESCRIPTION
  DSH 的文件系统技能发现器会扫描 <DSH_HOME>\skills\<名称>\SKILL.md。
  本脚本把包内的 skills/* 以目录联接（junction）方式挂到该位置：
    - 默认用 junction：源码只有一份，改完立即生效，不占额外空间
    - -Copy：目标机不方便联接到源目录时改用复制
  同时可选把技能挂到某个工作区的 .dsh\skills（项目级根）。
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install-into-dsh.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install-into-dsh.ps1 -ProjectRoot "F:\deepseek harness" -Bootstrap
#>
[CmdletBinding()]
param(
  [string]$DshHome = $env:DSH_HOME,
  [string]$ProjectRoot = '',
  [switch]$Copy,
  [switch]$Bootstrap,
  [switch]$Force,
  [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$pkg = Split-Path -Parent $PSScriptRoot
$srcSkills = Join-Path $pkg 'skills'

function Info($m) { Write-Host "[install] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[   ok  ] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[  warn ] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[  fail ] $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $srcSkills)) { Die "找不到技能目录：$srcSkills" }
if (-not $DshHome) {
  $DshHome = Join-Path $env:APPDATA 'dsh-desktop\harness'
  Warn "未提供 DSH_HOME，使用默认路径：$DshHome"
}
if (-not (Test-Path $DshHome)) { Die "DSH_HOME 不存在：$DshHome（先运行一次 DSH 或显式传入 -DshHome）" }

function Remove-Link($path) {
  if (-not (Test-Path $path)) { return }
  $item = Get-Item $path -Force
  if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') {
    # 删除联接本身，绝不动源目录内容
    cmd /c rmdir "$path" | Out-Null
  } else {
    Remove-Item $path -Recurse -Force
  }
}

# ---------------------------------------------------------------- 卸载（改由插件提供技能后清理重复来源）
if ($Uninstall) {
  $root = Join-Path $DshHome 'skills'
  foreach ($s in Get-ChildItem $srcSkills -Directory) {
    $dest = Join-Path $root $s.Name
    if (Test-Path $dest) { Remove-Link $dest; Ok "已移除技能根链接：$($s.Name)" }
    else { Warn "技能根里没有：$($s.Name)" }
  }
  $marker = Join-Path $root 'dsh-creative-studio.location.json'
  if (Test-Path $marker) { Remove-Item $marker -Force; Ok '已移除位置标记' }
  Info '用户级环境变量如需一并清除：'
  Write-Host '   [Environment]::SetEnvironmentVariable("DSH_CREATIVE_STUDIO_HOME", $null, "User")'
  Info '卸载技能根安装后，技能改由插件提供，需重启 DSH 才生效。'
  exit 0
}

function Install-Skills([string]$root, [string]$label) {
  New-Item -ItemType Directory -Force -Path $root | Out-Null
  $installed = @()
  foreach ($s in Get-ChildItem $srcSkills -Directory) {
    $dest = Join-Path $root $s.Name
    $skillFile = Join-Path $s.FullName 'SKILL.md'
    if (-not (Test-Path $skillFile)) { Warn "跳过 $($s.Name)：缺少 SKILL.md"; continue }
    if (Test-Path $dest) {
      if ($Force) { Remove-Link $dest } else { Ok "$label 已存在，跳过：$($s.Name)（用 -Force 覆盖）"; $installed += $s.Name; continue }
    }
    if ($Copy) {
      Copy-Item $s.FullName $dest -Recurse -Force
    } else {
      New-Item -ItemType Junction -Path $dest -Target $s.FullName | Out-Null
    }
    if (Test-Path (Join-Path $dest 'SKILL.md')) { $installed += $s.Name } else { Warn "安装校验失败：$($s.Name)" }
  }
  Ok ("$label → " + ($installed -join ', '))
}

# 用户级根：所有项目/会话都能看到
Install-Skills (Join-Path $DshHome 'skills') 'user-level'

# 位置标记：junction 安装时 <技能目录>\..\.. 不是包根，必须给 agent 留一份权威坐标
$marker = Join-Path (Join-Path $DshHome 'skills') 'dsh-creative-studio.location.json'
$markerMode = if ($Copy) { 'copy' } else { 'junction' }
$markerData = [ordered]@{
  packageRoot = $pkg
  skills      = @('image-studio', 'video-studio')
  installMode = $markerMode
  installedAt = (Get-Date).ToString('s')
} | ConvertTo-Json
[System.IO.File]::WriteAllText($marker, $markerData, (New-Object System.Text.UTF8Encoding($false)))
Ok "位置标记已写入：$marker"

try {
  [Environment]::SetEnvironmentVariable('DSH_CREATIVE_STUDIO_HOME', $pkg, 'User')
  $env:DSH_CREATIVE_STUDIO_HOME = $pkg
  Ok "已设置用户环境变量 DSH_CREATIVE_STUDIO_HOME = $pkg"
} catch {
  Warn "设置环境变量失败（位置标记可兜底）：$($_.Exception.Message)"
}

# 可选：项目级根
if ($ProjectRoot) {
  if (-not (Test-Path $ProjectRoot)) { Warn "ProjectRoot 不存在，跳过：$ProjectRoot" }
  else { Install-Skills (Join-Path $ProjectRoot '.dsh\skills') 'project-level' }
}

# 运行时就绪检查（技能里的命令需要它）
$py = Join-Path $pkg 'runtime\Scripts\python.exe'
if (Test-Path $py) {
  Ok "运行时已就绪：$py"
} else {
  Warn '运行时尚未创建；技能可用但命令会失败。'
  if ($Bootstrap) {
    Info '执行 bootstrap ...'
    & (Join-Path $PSScriptRoot 'bootstrap.ps1')
  } else {
    Info '请运行：powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1'
  }
}

Write-Host ''
Info '完成。重启 DSH（或新开会话）后，技能目录中会出现：'
Write-Host '   - image-studio   （美工：抠图/文字/logo/合成/规格化/批量/质检）'
Write-Host '   - video-studio   （剪辑：素材通览/文案脚本/剪辑/字幕/配乐/封面/导出）'
Write-Host ''
Info '验证方式：新会话里让 agent 使用 image-studio，或直接查看：'
Write-Host ("   Get-ChildItem `"" + (Join-Path $DshHome 'skills') + "`"")
