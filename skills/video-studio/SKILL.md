---
name: video-studio
description: Review, script and edit video with the bundled Creative Studio toolkit — footage inventory (duration/resolution/fps/audio), frame extraction and contact sheets, copywriting and storyboard structure, timeline cutting, transition joins, on-screen text, burned-in subtitles, music mixing with fades, smart cover-frame selection, and platform-spec exports (9:16 / 16:9 / 1:1 / 4:5). Use proactively for any task involving 视频/短视频/素材整理/剪辑/分镜/脚本/字幕/配乐/封面/转码, product videos, TikTok/Reels/Shorts/YouTube deliverables, or when a hand-made video looks rough and needs a professional pass.
---

# Video studio（视频剪辑）

Act like a working editor: **inventory the footage, write the copy and storyboard, then cut with real commands.** Never claim a visual result you have not extracted frames for and shown to the user.

## Resolve the toolkit first

```powershell
$pkg = $env:DSH_CREATIVE_STUDIO_HOME
if (-not $pkg) {
  $marker = Join-Path $env:DSH_HOME 'skills\dsh-creative-studio.location.json'
  if (Test-Path $marker) { $pkg = (Get-Content $marker -Raw | ConvertFrom-Json).packageRoot }
}
if (-not $pkg) {
  # 插件安装时 resourceBase 就是 <包>\skills\video-studio；junction 安装时 <skill base> 是指向包内的链接
  $t = (Get-Item '<skill base>' -Force).Target
  $pkg = if ($t) { Split-Path -Parent (Split-Path -Parent $t) } else { Split-Path -Parent (Split-Path -Parent '<skill base>') }
}
chcp 65001 > $null
[Console]::OutputEncoding = [Text.Encoding]::UTF8
node "$pkg\scripts\run-toolkit.mjs" doctor --json     # confirm the video tier and ffmpeg path
```

ffmpeg ships inside the runtime (`imageio-ffmpeg`) — never install system ffmpeg or describe an edit you did not perform.
**First use on any machine:** `node "$pkg\scripts\run-toolkit.mjs" selftest` (18 checks, includes cut/join/subtitles/export). Non-zero exit = broken capability here: report it.

## Three stages — never skip stage 1

**1 · 素材通览.** `video-probe` every source, `video-sheet --interval 2` on the keepers, then present:

| # | 文件 | 时长 | 分辨率 | 帧率 | 音频 | 可用性 | 用途/时间码 |
|---|---|---|---|---|---|---|---|
| 1 | A带料仓.mp4 | 53.6s | 568×320 | 30 | AAC 2ch | 可交付 | 炉体全景 0:06–0:14 |

Flag what limits the edit: low resolution, vertical/horizontal mismatch, silent clips, clips shorter than the planned cut. Extract frames for anything you cannot see and hand them to the user.

**2 · 文案与脚本.** Write copy first, cut to the copy. Short-form skeleton: 0–2 s hook → 2–6 s context → 6–20 s proof (two or three beats, one visual each) → 20–30 s objection handling → final 3 s CTA + brand mark. Hand over a storyboard before cutting:

| 镜号 | 时间码 | 画面（素材+片段） | 屏幕文案 | 旁白/字幕 | 音效/BGM | 时长 |
|---|---|---|---|---|---|---|
| 1 | 0:00–0:03 | A带料仓.mp4 特写 0:06–0:09 | 无电重力落料 | Gravity-fed, no electricity | 低音铺底 | 3s |

**3 · 剪辑执行.** `video-cut --accurate` for cuts that must land on a word or beat → `video-join --transition fade` (normalises timebase, fps, pixel format and audio) → `video-text` → `video-subtitle` → `video-audio` → `video-export --preset reel-9x16` → `video-cover --scan 8`.

```powershell
node "$pkg\scripts\run-toolkit.mjs" video-cut  raw/A.mp4 --start 6 --duration 8 --accurate --out work/a.mp4 --json
node "$pkg\scripts\run-toolkit.mjs" video-join work/a.mp4 work/b.mp4 --transition fade --out work/ab.mp4 --json
node "$pkg\scripts\run-toolkit.mjs" video-text work/ab.mp4 --text "无电重力落料`nGravity-Fed" --position tc --size 44 --stroke '#1F6E43' --stroke-width 5 --start 0 --end 6 --out work/ab-t.mp4 --json
node "$pkg\scripts\run-toolkit.mjs" video-export work/ab-t.mp4 --preset reel-9x16 --out-dir deliver --json
```

Every command, option and failure mode: **`reference/commands.md`**.
Platform canvases, safe zones, pacing and delivery specs: **`reference/platform-specs.md`**.

## Verification checklist (before claiming delivery)

1. `video-probe` each delivered file: expected duration (±0.2 s), canvas, `yuv420p`, audio present when intended.
2. Extract frames from the **output** (`video-sheet --interval 2`) and inspect them, or hand them to the user — never assert visual quality you did not verify.
3. First frame as cover: `video-cover --scan 8` and confirm it shows the product, not a blur.
4. Subtitles in sync (±0.3 s) and inside the safe zones; nothing clipped at the edges.
5. Music must not mask narration: start around `--music-volume 0.3` against `--original-volume 1.0`.

## Red lines

- Source footage stays untouched; every result goes to a new file.
- Only licensed or user-provided music/footage; never rip another creator's audio or clips.
- Get consent for identifiable people before publishing workshop or staff footage.
- No fabricated demos, no performance claims (efficiency, emission, removal-rate), no certifications the product does not hold.
- Do not fake a completed edit. If a step cannot run here, name the exact failing command and reason.
