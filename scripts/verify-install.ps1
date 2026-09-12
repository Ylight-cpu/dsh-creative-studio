#Requires -Version 5.1
<#
.SYNOPSIS
  一条命令确认 dsh-creative-studio 的安装是否真正生效。
.DESCRIPTION
  逐项检查并打印结论：插件是否登记、能否加载、provider 契约是否合规、
  运行时是否可用、技能当前来源是插件还是技能根、运行中的 DSH 是否已加载最新代码。
  默认只跑快检；加 -Full 会额外跑 19 项工具链验收。
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\verify-install.ps1
  powershell -ExecutionPolicy Bypass -File scripts\verify-install.ps1 -Full
#>
[CmdletBinding()]
param(
  [string]$DshHome = $env:DSH_HOME,
  [string]$Profile = 'web',
  [switch]$Full
)

$pkg = Split-Path -Parent $PSScriptRoot
$pkgName = 'dsh-creative-studio'
$results = @()

function Add-Result([string]$name, [bool]$ok, [string]$detail) {
  $script:results += [pscustomobject]@{ 项 = $name; 结果 = $(if ($ok) { 'OK' } else { 'FAIL' }); 说明 = $detail }
}
function Note($m) { Write-Host $m -ForegroundColor DarkGray }

if (-not $DshHome) { $DshHome = Join-Path $env:APPDATA 'dsh-desktop\harness' }
$profileDir = Join-Path $DshHome "profiles\$Profile"
$profileJson = Join-Path $profileDir 'package.json'
$skillsRoot = Join-Path $DshHome 'skills'

Write-Host ''
Write-Host '=== dsh-creative-studio 安装确认 ===' -ForegroundColor Cyan
Write-Host "包目录 : $pkg"
Write-Host "DSH_HOME: $DshHome"
Write-Host ''

# 1) profile 与插件登记
if (-not (Test-Path $profileJson)) {
  Add-Result 'profile package.json' $false "找不到 $profileJson"
} else {
  Add-Result 'profile package.json' $true $profileJson
  try {
    $json = Get-Content $profileJson -Raw -Encoding UTF8 | ConvertFrom-Json
    $inDeps = $null -ne $json.dependencies.$pkgName
    $inBundles = @($json.dsh.profile.bundles) -contains $pkgName
    Add-Result '插件已登记 dependencies' $inDeps $(if ($inDeps) { [string]$json.dependencies.$pkgName } else { '未登记' })
    Add-Result '插件已登记 bundles' $inBundles $(if ($inBundles) { ($json.dsh.profile.bundles -join ', ') } else { '未登记' })
  } catch {
    Add-Result 'profile JSON 可解析' $false $_.Exception.Message
  }
}

# 1b) 是否被禁用 —— 插件被 DSH 市场健康检查判定失败后会往 profile 的 patch 层
#     写 `- id: <插件> / disabled: true`，该 patch 在所有 bundle 层之后应用，
#     于是每次启动都被跳过（现象：登记、解析、契约全 OK，但技能不出现）。
$patchFile = Join-Path $profileDir 'cordis.patch.yml'
$disabledInPatch = $false
if (Test-Path $patchFile) {
  $pt = Get-Content $patchFile -Raw -Encoding UTF8
  $m = [regex]::Match($pt, "(?ms)^\s*-\s*id:\s*['`"]?creative-studio['`"]?\s*\r?\n\s*disabled:\s*true")
  $disabledInPatch = $m.Success
}
Add-Result 'profile patch 未禁用插件' (-not $disabledInPatch) $(
  if ($disabledInPatch) { "被 $patchFile 中的 `disabled: true` 关掉了 → 删除该行后重启 DSH" }
  else { 'patch 层无禁用行' })

$marketState = Join-Path $profileDir '.dsh-market\state.json'
if (Test-Path $marketState) {
  try {
    $ms = Get-Content $marketState -Raw -Encoding UTF8 | ConvertFrom-Json
    $inDisabled = @($ms.disabled) -contains $pkgName
    Add-Result '市场未标记禁用' (-not $inDisabled) $(
      if ($inDisabled) { '市场状态里被禁用 → 清空 .dsh-market\state.json 的 disabled 列表' }
      else { '市场状态正常' })
  } catch {
    Add-Result '市场状态可解析' $false $_.Exception.Message
  }
}

# 2) node_modules 链接
$link = Join-Path $profileDir "node_modules\$pkgName"
if (Test-Path $link) {
  $item = Get-Item $link -Force
  Add-Result 'node_modules 链接' $true "$($item.LinkType) -> $($item.Target)"
} else {
  Add-Result 'node_modules 链接' $false "不存在：$link"
}

# 3) 用【宿主加载方式】require() 加载已安装路径 + provider 契约
#    注意：宿主用 CJS 兼容路径加载 bundle；入口若有顶层 await 会 ERR_REQUIRE_ASYNC_MODULE
#    而静默失败，因此这里必须用 require，而不是 import()（import 会掩盖该问题）。
$probe = @'
import { createRequire } from "node:module"
const require = createRequire(import.meta.url)
const mod = require(process.argv[2])
let captured = null
mod.apply({ skills: { registerProvider: (f) => { captured = f() } } })
const list = await captured.list()
const ranks = list.map(c => `${c.name}=${c.rank}`)
const bad = list.filter(c => typeof c.rank !== 'number' || c.provider !== captured.name || !c.resourceBase?.path)
const loaded = await captured.get(list[0])
console.log(JSON.stringify({ provider: captured.name, ranks, invalid: bad.length, contentChars: loaded.content.length, stripped: !loaded.content.startsWith('---') }))
'@
$probeFile = Join-Path $env:TEMP "creative-studio-verify-$PID.mjs"
$probe | Out-File -FilePath $probeFile -Encoding utf8
$installedPath = ($link -replace '\\', '/') + '/lib/index.js'
$loadOut = node $probeFile $installedPath 2>&1 | Out-String
if ($LASTEXITCODE -eq 0 -and $loadOut -match '"invalid":0') {
  $info = $loadOut | ConvertFrom-Json
  Add-Result '插件按宿主方式 require() 加载' $true ("provider=" + $info.provider + "; " + ($info.ranks -join ', ') + "; 正文 " + $info.contentChars + " 字符")
} else {
  Add-Result '插件按宿主方式 require() 加载' $false ($loadOut.Trim() -split "`n" | Select-Object -First 2) -join ' | '
}
Remove-Item $probeFile -Force -ErrorAction SilentlyContinue

# 4) provider 契约测试套件
$selfTest = Join-Path $pkg 'scripts\provider-selftest.mjs'
if (Test-Path $selfTest) {
  $out = node $selfTest 2>&1 | Out-String
  Add-Result 'provider 契约测试' ($LASTEXITCODE -eq 0) $(if ($LASTEXITCODE -eq 0) { '逐字段对齐宿主校验规则' } else { ($out -split "`n" | Select-Object -First 2) -join ' ' })
} else {
  Add-Result 'provider 契约测试' $false '缺少 scripts\provider-selftest.mjs'
}

# 5) 运行时
$py = Join-Path $pkg 'runtime\Scripts\python.exe'
$hasRuntime = Test-Path $py
Add-Result '工具链运行时' $hasRuntime $(if ($hasRuntime) { $py } else { '未创建：先跑 scripts\bootstrap.ps1' })
if ($hasRuntime) {
  $doc = & $py (Join-Path $pkg 'toolkit\cs.py') doctor --json 2>&1 | Out-String
  try {
    $d = $doc | ConvertFrom-Json
    Add-Result 'doctor 自检' $true ("tier=" + $d.tier)
  } catch {
    Add-Result 'doctor 自检' $false 'doctor 输出无法解析'
  }
}

# 6) 技能来源：技能根副本是否还在
$rootSkills = @()
foreach ($s in @('image-studio', 'video-studio')) {
  if (Test-Path (Join-Path $skillsRoot $s)) { $rootSkills += $s }
}
if ($rootSkills.Count -gt 0) {
  Add-Result '技能根副本' $true ("仍存在：" + ($rootSkills -join ', ') + '（与插件重复；插件确认生效后可双击 uninstall-skills-root.cmd 清理）')
} else {
  Add-Result '技能根副本' $true '已清理，技能完全由插件提供'
}

# 7) 运行中的 DSH 是否已加载最新代码
#    比较对象必须包含【启动时读取的配置】：插件代码/cordis.patch.yml/profile 的 patch 层/市场状态。
#    只看 lib 与 skills 会漏掉"改了禁用状态但没重启"的情况，从而给出假绿灯。
$watch = @((Join-Path $pkg 'lib'), (Join-Path $pkg 'skills'), (Join-Path $pkg 'cordis.patch.yml'))
$watch += @($patchFile, $marketState)
$newest = Get-ChildItem $watch -Recurse -File -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
$dshProcs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'DSH Desktop*' } |
  Sort-Object StartTime | Select-Object -First 1
if ($dshProcs -and $newest) {
  $started = $dshProcs.StartTime
  $ok = $started -gt $newest.LastWriteTime
  Add-Result '运行中 DSH 已加载最新代码' $ok (
    "DSH 启动 " + $started.ToString('MM-dd HH:mm:ss') + " vs 代码最后修改 " + $newest.LastWriteTime.ToString('MM-dd HH:mm:ss') +
    $(if ($ok) { '' } else { ' → 需要重启 DSH' }))
} else {
  Add-Result '运行中 DSH 状态' $false '未检测到 DSH Desktop 进程'
}

# 8) 可选：工具链完整验收
if ($Full -and $hasRuntime) {
  Write-Host ''
  Note '跑工具链 19 项验收 ...'
  & $py (Join-Path $pkg 'toolkit\cs.py') selftest 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host $_ }
  Add-Result '工具链 19 项验收' ($LASTEXITCODE -eq 0) $(if ($LASTEXITCODE -eq 0) { 'selftest 全通过' } else { 'selftest 有失败项（见上方）' })
}

Write-Host ''
$results | Format-Table -AutoSize -Wrap
$failed = @($results | Where-Object { $_.结果 -eq 'FAIL' })
if ($failed.Count -eq 0) {
  Write-Host '结论：全部通过 —— 插件已生效。' -ForegroundColor Green
  exit 0
} else {
  Write-Host ("结论：" + $failed.Count + " 项需要处理（见上表 FAIL 行）。") -ForegroundColor Yellow
  exit 1
}
