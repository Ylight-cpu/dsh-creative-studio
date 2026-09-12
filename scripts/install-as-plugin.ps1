#Requires -Version 5.1
<#
.SYNOPSIS
  把 dsh-creative-studio 作为 DSH 插件安装进 profile（推荐方式）。
.DESCRIPTION
  做三件事：
    1) 备份 profile 的 package.json / pnpm-lock.yaml
    2) 用 DSH 自带 pnpm 把本包链接（默认）或复制进 profile 的 node_modules
    3) 把包名写进 dsh.profile.bundles —— 插件与包内技能由 DSH 自己加载
  装完需要重启 DSH（或新开会话）才会加载新插件。
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install-as-plugin.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install-as-plugin.ps1 -Copy          # 复制而非链接
  powershell -ExecutionPolicy Bypass -File scripts\install-as-plugin.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  [string]$DshHome = $env:DSH_HOME,
  [string]$Profile = 'web',
  [switch]$Copy,
  [switch]$Uninstall,
  [switch]$SkipSelftest
)

$ErrorActionPreference = 'Stop'
$pkg = Split-Path -Parent $PSScriptRoot
$pkgName = 'dsh-creative-studio'

function Info($m) { Write-Host "[plugin] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[   ok ] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[ warn ] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[ fail ] $m" -ForegroundColor Red; exit 1 }

if (-not $DshHome) { $DshHome = Join-Path $env:APPDATA 'dsh-desktop\harness'; Warn "未提供 DSH_HOME，用默认：$DshHome" }
$profileDir = Join-Path $DshHome "profiles\$Profile"
$profileJson = Join-Path $profileDir 'package.json'
if (-not (Test-Path $profileJson)) { Die "找不到 profile：$profileJson（先运行一次 DSH，或用 -Profile 指定）" }

$pnpm = Join-Path $DshHome '.desktop-bin\pnpm.cmd'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

# ---------------------------------------------------------------- 卸载
if ($Uninstall) {
  Copy-Item $profileJson "$profileJson.bak-$stamp" -Force
  $text = Get-Content $profileJson -Raw -Encoding UTF8
  $text = [regex]::Replace($text, "(\s*""$pkgName"",\r?\n)", "`n")
  [System.IO.File]::WriteAllText($profileJson, $text, (New-Object System.Text.UTF8Encoding($false)))
  $target = Join-Path $profileDir "node_modules\$pkgName"
  if (Test-Path $target) {
    $item = Get-Item $target -Force
    if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') { cmd /c rmdir "$target" | Out-Null }
    else { Remove-Item $target -Recurse -Force }
  }
  Ok "已从 bundles 与 node_modules 移除 $pkgName（备份：package.json.bak-$stamp）"
  Info '重启 DSH 后生效。技能根安装（若还在）不受影响。'
  exit 0
}

# ---------------------------------------------------------------- 预检
if (-not $SkipSelftest) {
  Info 'provider 契约冒烟测试 ...'
  $node = Get-Command node -ErrorAction SilentlyContinue
  if ($node) {
    & node (Join-Path $pkg 'scripts\provider-selftest.mjs') | Out-Null
    if ($LASTEXITCODE -ne 0) { Die 'provider 冒烟测试失败，已中止安装（避免装坏 DSH 启动）' }
    Ok 'provider 契约正常'
  } else {
    Warn '未找到 node，跳过冒烟测试'
  }
}

# ---------------------------------------------------------------- 备份
Copy-Item $profileJson "$profileJson.bak-$stamp" -Force
if (Test-Path (Join-Path $profileDir 'pnpm-lock.yaml')) {
  Copy-Item (Join-Path $profileDir 'pnpm-lock.yaml') (Join-Path $profileDir "pnpm-lock.yaml.bak-$stamp") -Force
}
Ok "已备份 profile 配置（后缀 $stamp）"

# ---------------------------------------------------------------- 安装本体
if ($Copy) {
  $target = Join-Path $profileDir "node_modules\$pkgName"
  if (Test-Path $target) { Remove-Item $target -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  foreach ($item in @('lib', 'skills', 'toolkit', 'scripts', 'docs', 'package.json', 'cordis.patch.yml', 'README.md')) {
    $src = Join-Path $pkg $item
    if (Test-Path $src) { Copy-Item $src $target -Recurse -Force }
  }
  Ok "已复制到 $target（runtime/ 需在该机重跑 bootstrap.ps1 生成）"
} else {
  if (-not (Test-Path $pnpm)) { Warn "找不到 DSH 自带 pnpm（$pnpm），改用复制模式"; $Copy = $true }
  else {
    # 用 cmd 执行：pnpm 的 stderr 备注在 PowerShell 5.1 里会被当成错误记录刷红
    $out = cmd /c "`"$pnpm`" add `"link:$pkg`" --prefer-offline 2>&1"
    $code = $LASTEXITCODE
    $out | Select-Object -Last 6 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    if ($code -ne 0) { Die "pnpm add 失败（exit=$code）；可用 -Copy 模式重试" }
    Ok "已链接到 profile node_modules"
  }
}

# ---------------------------------------------------------------- 登记 bundles（保留文件格式的定点插入）
$text = Get-Content $profileJson -Raw -Encoding UTF8
if ($text -notmatch [regex]::Escape("`"$pkgName`"")) {
  $pattern = '(?s)("bundles"\s*:\s*\[)(.*?)(\s*\])'
  $m = [regex]::Match($text, $pattern)
  if (-not $m.Success) { Die 'profile package.json 里找不到 dsh.profile.bundles，请手工添加 ' + $pkgName }
  $inner = $m.Groups[2].Value.TrimEnd()
  $sep = if ($inner.Trim().Length -gt 0) { ',' } else { '' }
  $replacement = $m.Groups[1].Value + $inner + $sep + "`n        `"$pkgName`"" + $m.Groups[3].Value
  $text = $text.Remove($m.Index, $m.Length).Insert($m.Index, $replacement)
  [System.IO.File]::WriteAllText($profileJson, $text, (New-Object System.Text.UTF8Encoding($false)))
  Ok "已写入 dsh.profile.bundles"
} else {
  Ok 'bundles 里已存在，跳过'
}

# ---------------------------------------------------------------- 校验
try {
  Get-Content $profileJson -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
  Ok 'profile package.json JSON 合法'
} catch {
  Copy-Item "$profileJson.bak-$stamp" $profileJson -Force
  Die "写入后 JSON 非法，已回滚：$($_.Exception.Message)"
}

Write-Host ''
Info '完成。请重启 DSH（完全退出后重新打开），插件与其中的 image-studio / video-studio 会在启动时加载。'
Write-Host '   - 若之前用 install-into-dsh.ps1 装过技能根版本，插件生效后可执行：'
Write-Host '       powershell -ExecutionPolicy Bypass -File scripts\install-into-dsh.ps1 -Uninstall'
Write-Host '     避免同名技能来自两处。'
