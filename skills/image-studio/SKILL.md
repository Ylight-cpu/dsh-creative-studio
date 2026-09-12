---
name: image-studio
description: Produce publication-quality product and marketing images with the bundled Creative Studio toolkit — background removal (matting) with quality tiers, white-background e-commerce main images, local object removal / retouching (inpainting), headline/caption text, logo and watermark placement, multi-layer compositing, batch platform-size exports, contact sheets, colour palettes and image QA. Use proactively for any task involving product photos, 主图/白底图/详情页/海报/广告图/素材图, 抠图、换背景、改图、去杂物、加文字、贴 logo、加水印、批量处理、图片规格化 or image quality review, especially when the user complains that generated or hand-made images look unpolished.
---

# Image studio（美工）

Deliver images by **operating the real files with the bundled toolkit**, not by describing edits.
Every operation writes a new file; never overwrite an input.

## Resolve the toolkit first

```powershell
$pkg = $env:DSH_CREATIVE_STUDIO_HOME
if (-not $pkg) {
  $marker = Join-Path $env:DSH_HOME 'skills\dsh-creative-studio.location.json'
  if (Test-Path $marker) { $pkg = (Get-Content $marker -Raw | ConvertFrom-Json).packageRoot }
}
if (-not $pkg) {
  # 插件安装时 resourceBase 就是 <包>\skills\image-studio；junction 安装时 <skill base> 是指向包内的链接
  $t = (Get-Item '<skill base>' -Force).Target
  $pkg = if ($t) { Split-Path -Parent (Split-Path -Parent $t) } else { Split-Path -Parent (Split-Path -Parent '<skill base>') }
}
chcp 65001 > $null                                    # PowerShell 5.1: keep Chinese paths readable
[Console]::OutputEncoding = [Text.Encoding]::UTF8
node "$pkg\scripts\run-toolkit.mjs" doctor --json     # tiers, ffmpeg, fonts, models, GPU
```

Call the toolkit as `node "$pkg\scripts\run-toolkit.mjs" <command> …` (or directly `"$pkg\runtime\Scripts\python.exe" "$pkg\toolkit\cs.py" …`). Always pass `--json`.

**First use on any machine:** `node "$pkg\scripts\run-toolkit.mjs" selftest` — 29 checks on self-generated fixtures (the 3 video-effect gates run too, so a pass means the whole pack is healthy). Non-zero exit means a capability is broken here: report it, do not deliver.

**Tiers.** T0 Pillow (text, logo, compose, export, sheet, palette, inspect) · T1 rembg+ONNX (matting, inpaint) · T2 ffmpeg (video cut/join/subtitles/export) · T3 onnxruntime (video matting, animated titles, transitions, light effects — see the `video-studio` skill). If `doctor` reports a missing tier, say so instead of faking the result.

## The four jobs you will actually be asked to do

1. **White-background e-commerce main image** — `matte --quality auto --bg white --feather 1.2` → `inspect` → `export --preset amazon-main`.
2. **Marketing image: headline + brand mark** — `text` (stroke/shadow/box) → `logo --key-white`.
3. **改图 / retouch: remove or replace something** — `matte` to cut the subject and `compose` to rebuild, or `inpaint --box/--circle/--mask` to erase a waterline, watermark, dust, scratch or small object in place.
4. **Batch normalisation** — point `export` at a directory; then `sheet` the output and review the contact sheet.

Full command list, every option and the retouch decision tree: **`reference/commands.md`**.
Layout, typography and matting-quality rules: **`reference/quality.md`**.

Video work — AI matting with background replacement, animated titles, transitions and light effects — lives in the companion skill **`video-studio`** (same package, same toolkit: `video-matte`, `video-text-anim`, `video-join --transition`, `video-fx`). When a task mixes stills and motion, do the stills here and the motion there.

## Matting quality policy (do not default to the fastest model)

`--quality fast|auto|best` (default `auto`):

| Policy | Model | When |
|---|---|---|
| `fast` | u2net | drafts, huge batches (edge quality visibly worse: measured transition ≈5.3 px vs 2.8 px) |
| `auto` | ≤2 MP → `birefnet-general`, larger → `isnet-general-use` | default; ≈0.5 s (isnet) … ≈6 s (birefnet, CPU) |
| `best` | `birefnet-general` | hero images, glass/hair/transparent objects (94 %/78 % vs u2net 71 %/48 %) |

`matte` prints `transition_px` (how many pixels the edge takes to fade) and warns above 3 px — treat a warning as "review or re-run with `--quality best`", never as a pass.

## Verification checklist (before claiming delivery)

1. `inspect` every delivered file: size, alpha state, subject coverage, `transition_px`, dominant colours.
2. Text: no clipping, inside the safe margin, readable against the underlying pixels.
3. Platform rules: correct canvas/background; no unapproved badges, claims or certifications.
4. Keep the untouched original; name outputs `-white`, `-poster`, `-amazon-main`.
5. If you cannot view images on this model route, export a `sheet` and hand it to the user for sign-off — never assert visual quality you did not verify.

## Red lines

- Never overwrite or destructively edit an input file.
- Never fabricate product evidence: no certification marks, no "100 %"/"best" claims, no fake before/after, no features the product lacks.
- Regulated-claim discipline: material and structure facts only (plant-based, plastic-free, no dyes) — no removal-rate/antibacterial/medical/purifying claims, no unverified certifications.
- Do not lift a competitor's watermarked imagery; ask for the user's own photography or a licensed asset.

Troubleshooting (model downloads, CJK fonts, tier gaps, Windows path quirks): **`reference/quality.md`**.
