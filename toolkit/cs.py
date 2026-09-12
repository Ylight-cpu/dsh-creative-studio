#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""cs.py — DSH Creative Studio toolkit (image + video).

零第三方依赖的图片基础操作（Pillow 必需），抠图等增强能力按需降级：
  T0  Pillow only            : text / logo / compose / resize / sheet / inspect / palette
  T1  + rembg + onnxruntime  : matte（抠图）/ 换背景
  T2  + ffmpeg (imageio-ffmpeg 或系统) : 视频探针 / 关键帧 / 裁剪 / 拼接 / 导出

设计原则
  1) 每个子命令都支持 --json，便于 agent 解析与验收；
  2) 缺依赖时给出明确安装提示（不静默失败）；
  3) 输出默认同目录加后缀，永不覆盖输入。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat
except ImportError:  # pragma: no cover
    print("MISSING_DEP: Pillow 未安装。运行：python -m pip install pillow", file=sys.stderr)
    raise SystemExit(2)

# Windows PowerShell 5.1 会按控制台代码页解码子进程输出；强制 UTF-8 避免中文路径乱码。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

Image.MAX_IMAGE_PIXELS = None

# --------------------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------------------

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",       # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\impact.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def find_font(name: str | None = None, size: int = 48) -> ImageFont.FreeTypeFont:
    """按名称/路径找字体；找不到则退回内置位图字体并给出告警。"""
    candidates: list[str] = []
    if name:
        p = Path(name)
        if p.exists():
            candidates.append(str(p))
        else:
            candidates += [
                rf"C:\Windows\Fonts\{name}.ttf",
                rf"C:\Windows\Fonts\{name}.ttc",
                rf"C:\Windows\Fonts\{name}",
            ]
    candidates += [str(Path(__file__).parent / "fonts" / f) for f in
                   ("Inter-Bold.ttf", "NotoSansSC-Bold.otf", "DejaVuSans-Bold.ttf")]
    candidates += FONT_CANDIDATES
    for c in candidates:
        try:
            if Path(c).exists():
                return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default(size)


def parse_color(value: str) -> tuple[int, int, int, int]:
    """支持 #RGB / #RRGGBB / #RRGGBBAA / 常用英文色名 / white|black|transparent。"""
    named = {
        "white": (255, 255, 255, 255), "black": (0, 0, 0, 255),
        "red": (220, 38, 38, 255), "green": (22, 110, 67, 255),
        "blue": (37, 99, 235, 255), "grey": (128, 128, 128, 255),
        "gray": (128, 128, 128, 255), "transparent": (0, 0, 0, 0),
        "yellow": (250, 204, 21, 255), "orange": (249, 115, 22, 255),
    }
    v = (value or "").strip().lower()
    if v in named:
        return named[v]
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) == 6:
            h += "ff"
        if len(h) == 8:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]
    raise ValueError(f"无法解析颜色: {value}")


def open_rgba(path: str | Path) -> Image.Image:
    """打开并转为 RGBA。自动按 EXIF 方向标记旋正——手机/相机直出照片常带 Orientation 标记，
    不处理会导致竖拍照片被当成横图（尺寸、文字定位、平台规格全错）。"""
    img = Image.open(path)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img.convert("RGBA")


def save_image(img: Image.Image, out: str | Path, quality: int = 95) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        img.convert("RGB").save(out, quality=quality, subsampling=0)
    elif out.suffix.lower() == ".webp":
        img.save(out, quality=quality, method=6)
    else:
        img.save(out)
    return out


def default_out(src: str | Path, suffix: str, ext: str | None = None) -> Path:
    src = Path(src)
    ext = ext or src.suffix or ".png"
    return src.with_name(f"{src.stem}{suffix}{ext}")


def emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for k, v in payload.items():
            print(f"{k}: {v}")


def warn_tier(feature: str, install_hint: str) -> None:
    print(f"TIER_UNAVAILABLE[{feature}] 需要额外依赖：{install_hint}", file=sys.stderr)


# --------------------------------------------------------------------------------------
# 九宫格定位
# --------------------------------------------------------------------------------------

POSITIONS = {
    "tl": (0.0, 0.0), "tc": (0.5, 0.0), "tr": (1.0, 0.0),
    "ml": (0.0, 0.5), "mc": (0.5, 0.5), "mr": (1.0, 0.5),
    "bl": (0.0, 1.0), "bc": (0.5, 1.0), "br": (1.0, 1.0),
}


def anchor_box(canvas: tuple[int, int], size: tuple[int, int], pos: str, margin: int) -> tuple[int, int]:
    W, H = canvas
    w, h = size
    fx, fy = POSITIONS.get(pos, POSITIONS["br"])
    x = margin + fx * (W - w - 2 * margin)
    y = margin + fy * (H - h - 2 * margin)
    return int(round(x)), int(round(y))


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        if not raw:
            lines.append("")
            continue
        cur = ""
        for ch in raw:
            trial = cur + ch
            if draw.textlength(trial, font=font) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------------------
# 子命令实现
# --------------------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    report: dict = {"python": sys.version.split()[0], "executable": sys.executable}
    deps = {}
    for mod in ("PIL", "numpy", "cv2", "rembg", "onnxruntime", "imageio_ffmpeg", "torch"):
        try:
            m = __import__(mod)
            deps[mod] = getattr(m, "__version__", "ok")
        except Exception:
            deps[mod] = None
    report["deps"] = deps
    if deps.get("onnxruntime"):
        try:
            import onnxruntime as ort
            report["onnx_providers"] = ort.get_available_providers()
        except Exception as e:  # pragma: no cover
            report["onnx_providers"] = f"error: {e}"
    # ffmpeg 探测
    ff = shutil.which("ffmpeg")
    if not ff and deps.get("imageio_ffmpeg"):
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ff = None
    report["ffmpeg"] = ff
    # 字体
    usable = [c for c in FONT_CANDIDATES if Path(c).exists()]
    report["fonts_found"] = usable[:4]
    # 模型缓存（rembg 2.x -> ~/.rembg/models；旧版/自定义 -> ~/.u2net）
    caches = [Path.home() / ".rembg" / "models", Path.home() / ".u2net"]
    if os.environ.get("U2NET_HOME"):
        caches.insert(0, Path(os.environ["U2NET_HOME"]))
    found = []
    for c in caches:
        if c.exists():
            found += [str(p) for p in c.rglob("*.onnx")]
    report["model_cache"] = str(caches[0])
    report["model_cache_files"] = found
    report["model_cache_alt"] = [str(c) for c in caches if c.exists()]
    # GPU
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=15)
        report["gpu"] = out.stdout.strip() or None
    except Exception:
        report["gpu"] = None
    tier = "T0 (Pillow)"
    if deps.get("rembg") and deps.get("onnxruntime"):
        tier = "T1 (matting/onnx)" if report["model_cache_files"] else "T1 (matting ready, model not downloaded yet)"
    if ff:
        tier += " + video via ffmpeg"
    report["tier"] = tier.strip()
    emit(report, args.json)
    return 0


def cmd_inspect(args) -> int:
    results = []
    for src in args.inputs:
        img = open_rgba(src)
        info: dict = {"file": str(src), "size": list(img.size), "mode": Image.open(src).mode}
        alpha = img.getchannel("A")
        if alpha.getextrema()[0] < 255:
            info["has_alpha"] = True
            bbox = alpha.getbbox()
            info["subject_bbox"] = list(bbox) if bbox else None
            if bbox:
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                info["subject_coverage"] = round((w * h) / (img.size[0] * img.size[1]), 4)
            info.update(alpha_quality(img))
        else:
            info["has_alpha"] = False
        stat = ImageStat.Stat(img.convert("L"))
        info["mean_luma"] = round(stat.mean[0], 1)
        info["stddev_luma"] = round(stat.stddev[0], 1)
        if img.size[0] * img.size[1] > 0:
            small = img.convert("RGB").resize((64, 64))
            colors = small.getcolors(64 * 64) or []
            colors.sort(reverse=True)
            info["dominant_rgb"] = [c[1] for c in colors[:3]]
        results.append(info)
    emit({"count": len(results), "images": results} if args.json else
         {r["file"]: f"{r['size'][0]}x{r['size'][1]} alpha={r.get('has_alpha')} luma={r['mean_luma']}"
          for r in results}, args.json)
    return 0


def cmd_matte(args) -> int:
    try:
        from rembg import new_session, remove
    except Exception:
        warn_tier("matte", "python -m pip install rembg onnxruntime  (首次运行会下载模型)")
        return 3

    import time

    inputs = list(args.inputs)

    def resolve_model(src_path: str) -> str:
        """质量策略：fast=u2net(最快) / auto=小图用 birefnet、大图用 isnet / best=birefnet。
        依据：生产实测 BiRefNet 毛发 94%、玻璃 78%，U2Net 仅 71%/48%。"""
        if args.model and args.model != "auto":
            return args.model
        q = args.quality
        if q == "fast":
            return "u2net"
        if q == "best":
            return "birefnet-general"
        try:
            with Image.open(src_path) as im:
                mp = (im.size[0] * im.size[1]) / 1e6
        except Exception:
            mp = 99.0
        return "birefnet-general" if mp <= 2.0 else "isnet-general-use"

    session_cache: dict[str, object] = {}
    outs, reports = [], []
    for src in inputs:
        model = resolve_model(src)
        if model not in session_cache:
            try:
                session_cache[model] = new_session(model)
            except Exception as e:
                print(f"MODEL_ERROR[{model}]: {e}", file=sys.stderr)
                return 4
        t0 = time.time()
        img = Image.open(src)
        cut = remove(img, session=session_cache[model], alpha_matting=args.alpha_matting,
                     **({"alpha_matting_foreground_threshold": args.fg_threshold,
                         "alpha_matting_background_threshold": args.bg_threshold,
                         "alpha_matting_erode_size": args.erode} if args.alpha_matting else {}))
        elapsed = time.time() - t0
        if args.feather:
            a = cut.getchannel("A").filter(ImageFilter.GaussianBlur(args.feather))
            cut.putalpha(a)
        if args.bg:
            bg = Image.new("RGBA", cut.size, parse_color(args.bg))
            cut = Image.alpha_composite(bg, cut)
        out = Path(args.out) if (args.out and len(inputs) == 1) else \
            default_out(src, "-matte", ".png")
        save_image(cut, out)
        qa = alpha_quality(cut)
        warning = None
        if qa.get("transition_px", 0) and qa["transition_px"] > 3.0:
            warning = (f"边缘过渡宽度 {qa['transition_px']}px 偏大（可能糊边/光晕）；"
                       "可试 --quality best 或 --alpha-matting")
        outs.append(str(out))
        reports.append({"input": str(src), "output": str(out), "model": model,
                        "seconds": round(elapsed, 2), "qa": qa, "warning": warning})
    emit({"model_policy": args.quality, "results": reports, "outputs": outs}, args.json)
    return 0


def alpha_quality(img: Image.Image) -> dict:
    """抠图边缘质检：过渡宽度（像素）+ 半透明占比。

    `transition_px` = 半透明像素数 × 2 ÷ 边界周长，近似"从背景过渡到主体要走几个像素"。
    干净硬边约 1–1.5px；糊边/光晕会明显变大（>3px 需要复核或改用更高质量模型）。
    """
    try:
        import numpy as np
    except Exception:
        return {}
    alpha = img.getchannel("A")
    if alpha.getextrema()[0] == 255:
        return {"has_alpha": False}
    a = np.asarray(alpha, dtype=np.uint8).astype(np.float32) / 255.0
    soft = (a > 0.05) & (a < 0.95)
    solid = a > 0.5
    edge = np.zeros_like(solid)
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        edge |= solid != np.roll(np.roll(solid, dy, 0), dx, 1)
    edge_n = int(edge.sum())
    soft_n = int(soft.sum())
    transition = round(2.0 * soft_n / edge_n, 2) if edge_n else 0.0
    return {"has_alpha": True,
            "alpha_soft_ratio": round(soft_n / a.size, 4),
            "edge_pixels": edge_n,
            "transition_px": transition}


def cmd_text(args) -> int:
    img = open_rgba(args.input)
    W, H = img.size
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    size = args.size or max(18, int(W * 0.06))
    font = find_font(args.font, size)
    margin = args.margin
    max_w = int(W * args.max_width_ratio)
    lines = wrap_text(draw, args.text, font, max_w) if args.max_width_ratio < 1 else args.text.split("\n")

    line_h = int(size * 1.25)
    block_h = line_h * len(lines)
    widest = max((draw.textlength(ln, font=font) for ln in lines), default=0)

    x, y = anchor_box((W, H), (int(widest), block_h), args.position, margin)
    if args.position in ("tc", "mc", "bc"):
        x = int((W - widest) / 2)
    if args.position in ("ml", "mr"):
        y = int((H - block_h) / 2)
    if args.position in ("tc", "bc") and args.margin:
        y = margin if args.position == "tc" else H - block_h - margin

    if args.box:
        pad = int(size * 0.35)
        draw.rounded_rectangle(
            [x - pad, y - pad, x + widest + pad, y + block_h + pad],
            radius=int(size * 0.25), fill=parse_color(args.box),
        )

    for i, ln in enumerate(lines):
        ly = y + i * line_h
        if args.shadow:
            draw.text((x + max(1, size // 24), ly + max(1, size // 24)), ln, font=font,
                      fill=parse_color(args.shadow))
        draw.text((x, ly), ln, font=font, fill=parse_color(args.color),
                  stroke_width=args.stroke_width,
                  stroke_fill=parse_color(args.stroke) if args.stroke else None)

    out = save_image(Image.alpha_composite(img, layer), args.out or default_out(args.input, "-text", ".png"))
    emit({"output": str(out), "lines": len(lines), "font_size": size}, args.json)
    return 0


def key_out_white(img: Image.Image, threshold: int = 245, soft: int = 12) -> Image.Image:
    """把接近纯白的像素变透明（用于白底 logo）。"""
    img = img.convert("RGBA")
    px = img.load()
    W, H = img.size
    for y in range(H):
        for x in range(W):
            r, g, b, a = px[x, y]
            if r >= threshold and g >= threshold and b >= threshold:
                px[x, y] = (r, g, b, 0)
            elif soft and min(r, g, b) > threshold - soft:
                lum = (r + g + b) / 3
                px[x, y] = (r, g, b, int(255 * max(0.0, (threshold - lum) / soft)))
    return img


def cmd_inpaint(args) -> int:
    """局部重绘（改图）：去掉杂物/水印/瑕疵并补全背景。

    后端：
      telea/ns  OpenCV 修复算法——零额外依赖，适合小面积缺陷（水印、灰尘、划痕、小物体）
      lama-onnx LaMa 大范围重绘——需要模型文件（体积大、效果强），用 --lama-model 或环境变量 CS_LAMA_ONNX 指定
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        warn_tier("inpaint", "python -m pip install opencv-python-headless numpy")
        return 3

    src = args.input
    img = Image.open(src)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    rgb = img.convert("RGB")
    W, H = rgb.size

    # ---------- 组装掩码（白色 = 要重绘的区域）----------
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    painted = False
    if args.mask:
        m = Image.open(args.mask).convert("L")
        if m.size != (W, H):
            m = m.resize((W, H), Image.NEAREST)
        mask = Image.composite(Image.new("L", (W, H), 255), mask, m.point(lambda v: 255 if v > 127 else 0))
        painted = True
    for box in (args.box or []):
        try:
            x, y, w, h = (int(float(v)) for v in box.split(","))
        except Exception:
            print(f"BOX_ERROR: 需要 x,y,w,h 形式，收到 {box}", file=sys.stderr)
            return 2
        md.rectangle([x, y, x + w, y + h], fill=255)
        painted = True
    for c in (args.circle or []):
        try:
            x, y, r = (int(float(v)) for v in c.split(","))
        except Exception:
            print(f"CIRCLE_ERROR: 需要 x,y,r 形式，收到 {c}", file=sys.stderr)
            return 2
        md.ellipse([x - r, y - r, x + r, y + r], fill=255)
        painted = True
    if not painted:
        print("需要 --mask 或 --box/--circle 指定要重绘的区域", file=sys.stderr)
        return 2

    if args.dilate:
        mask = mask.filter(ImageFilter.MaxFilter(args.dilate * 2 + 1))

    mask_np = np.asarray(mask, dtype=np.uint8)
    mask_bin = (mask_np > 127).astype(np.uint8)

    backend = args.backend
    if backend == "auto":
        lama_model = args.lama_model or os.environ.get("CS_LAMA_ONNX")
        backend = "lama-onnx" if (lama_model and Path(lama_model).exists()) else "telea"

    # ---------- 执行 ----------
    if backend == "lama-onnx":
        model_path = args.lama_model or os.environ.get("CS_LAMA_ONNX")
        if not model_path or not Path(model_path).exists():
            print("LAMA_MODEL_MISSING: 用 --lama-model 或环境变量 CS_LAMA_ONNX 指向 LaMa ONNX 模型",
                  file=sys.stderr)
            return 4
        try:
            import onnxruntime as ort
            sess = ort.InferenceSession(str(model_path), providers=ort.get_available_providers())
            in_names = [i.name for i in sess.get_inputs()]
            size = args.lama_size
            work = rgb.resize((size, size), Image.LANCZOS)
            wmask = mask.resize((size, size), Image.NEAREST)
            arr = np.asarray(work, dtype=np.float32) / 255.0
            marr = (np.asarray(wmask, dtype=np.float32) > 127).astype(np.float32)
            feeds = {}
            for nm in in_names:
                if nm.lower().startswith(("mask", "m")):
                    feeds[nm] = marr[None, None, :, :]
                else:
                    feeds[nm] = arr.transpose(2, 0, 1)[None, :, :, :]
            out = sess.run(None, feeds)[0]
            res = out[0].transpose(1, 2, 0)
            res = np.clip(res * 255.0, 0, 255).astype(np.uint8)
            filled = Image.fromarray(res, "RGB").resize((W, H), Image.LANCZOS)
            result = Image.composite(filled, rgb, mask.point(lambda v: 255 if v > 127 else 0))
            note = f"lama-onnx({Path(model_path).name}, inputs={in_names})"
        except Exception as e:
            print(f"LAMA_ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            return 5
    else:
        flag = cv2.INPAINT_NS if backend == "ns" else cv2.INPAINT_TELEA
        bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
        out_bgr = cv2.inpaint(bgr, mask_bin * 255, args.radius, flag)
        result = Image.fromarray(cv2.cvtColor(out_bgr, cv2.COLOR_BGR2RGB))
        note = f"{backend}(radius={args.radius})"

    out = Path(args.out or default_out(src, "-inpaint", ".png"))
    save_image(result, out)
    covered = round(float(mask_bin.mean()), 4)
    emit({"output": str(out), "backend": note, "mask_coverage": covered,
          "mask_pixels": int(mask_bin.sum()), "dilate": args.dilate}, args.json)
    return 0


def cmd_logo(args) -> int:
    img = open_rgba(args.input)
    W, H = img.size
    logo = open_rgba(args.logo)
    if args.key_white:
        logo = key_out_white(logo)
    target_w = int(W * args.width_ratio)
    ratio = target_w / logo.size[0]
    logo = logo.resize((max(1, target_w), max(1, int(logo.size[1] * ratio))), Image.LANCZOS)
    if args.opacity < 1.0:
        a = logo.getchannel("A").point(lambda v: int(v * args.opacity))
        logo.putalpha(a)
    x, y = anchor_box((W, H), logo.size, args.position, args.margin)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    layer.alpha_composite(logo, (x, y))
    out = save_image(Image.alpha_composite(img, layer), args.out or default_out(args.input, "-logo", ".png"))
    emit({"output": str(out), "logo_size": list(logo.size), "position": args.position}, args.json)
    return 0


def _is_coord_token(tok: str) -> bool:
    import re
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?%?", tok or ""))


def parse_overlay_spec(spec: str) -> tuple[str, str, str, str]:
    """解析 `path:x:y[:scale]`。从右往左吃坐标，避免 Windows 盘符冒号被误切。"""
    toks = spec.split(":")
    coords: list[str] = []
    while toks and len(coords) < 3 and _is_coord_token(toks[-1]):
        coords.insert(0, toks.pop())
    path = ":".join(toks)
    x = coords[0] if len(coords) > 0 else "0"
    y = coords[1] if len(coords) > 1 else "0"
    scale = coords[2] if len(coords) > 2 else ""
    return path, x, y, scale


def cmd_compose(args) -> int:
    base = open_rgba(args.base)
    applied = []
    for spec in args.overlay:
        path, xs, ys, scale_tok = parse_overlay_spec(spec)
        ov = open_rgba(path)
        if scale_tok:
            s = float(scale_tok.rstrip("%"))
            s = s / 100 if scale_tok.endswith("%") else s
            ow, oh = ov.size
            ov = ov.resize((max(1, int(ow * s)), max(1, int(oh * s))), Image.LANCZOS)

        def coord(v: str, total: int) -> int:
            return int(total * float(v.rstrip("%")) / 100) if v.endswith("%") else int(float(v))

        x = coord(xs, base.size[0])
        y = coord(ys, base.size[1])
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        layer.alpha_composite(ov, (x, y))
        base = Image.alpha_composite(base, layer)
        applied.append({"path": path, "at": [x, y], "size": list(ov.size)})
    out = save_image(base, args.out or default_out(args.base, "-composed", ".png"))
    emit({"output": str(out), "overlays": applied}, args.json)
    return 0


PRESETS = {
    "amazon-main": ((2000, 2000), "pad", "white"),
    "amazon-zoom": ((3000, 3000), "pad", "white"),
    "amazon-lifestyle": ((1600, 1600), "crop", None),
    "shopify": ((2048, 2048), "pad", "white"),
    "faire": ((1600, 1600), "pad", "white"),
    "square": ((1080, 1080), "pad", "white"),
    "story-9x16": ((1080, 1920), "pad", "white"),
    "wide-16x9": ((1920, 1080), "pad", "white"),
    "thumb-4x5": ((1080, 1350), "pad", "white"),
}


def cmd_export(args) -> int:
    if args.preset and args.preset in PRESETS:
        (tw, th), mode, bg = PRESETS[args.preset]
        if args.mode:
            mode = args.mode
        if args.bg:
            bg = args.bg
    elif args.size:
        tw, th = (int(v) for v in args.size.lower().split("x"))
        mode, bg = args.mode or "pad", args.bg or "white"
    else:
        print("需要 --preset 或 --size WxH", file=sys.stderr)
        return 2

    srcs = []
    for p in args.inputs:
        p = Path(p)
        srcs += sorted([q for q in p.iterdir() if q.suffix.lower() in
                        (".png", ".jpg", ".jpeg", ".webp")]) if p.is_dir() else [p]

    outs = []
    for src in srcs:
        img = open_rgba(src)
        if mode == "fit":
            r = min(tw / img.size[0], th / img.size[1])
            new = img.resize((max(1, int(img.size[0] * r)), max(1, int(img.size[1] * r))), Image.LANCZOS)
            canvas = Image.new("RGBA", (tw, th), parse_color(bg) if bg else (0, 0, 0, 0))
            canvas.alpha_composite(new, ((tw - new.size[0]) // 2, (th - new.size[1]) // 2))
        elif mode == "crop":
            r = max(tw / img.size[0], th / img.size[1])
            new = img.resize((max(1, int(img.size[0] * r)), max(1, int(img.size[1] * r))), Image.LANCZOS)
            left = (new.size[0] - tw) // 2
            top = (new.size[1] - th) // 2
            canvas = new.crop((left, top, left + tw, top + th))
        else:  # pad
            r = min(tw / img.size[0], th / img.size[1])
            new = img.resize((max(1, int(img.size[0] * r)), max(1, int(img.size[1] * r))), Image.LANCZOS)
            canvas = Image.new("RGBA", (tw, th), parse_color(bg) if bg else (0, 0, 0, 0))
            canvas.alpha_composite(new, ((tw - new.size[0]) // 2, (th - new.size[1]) // 2))
        out_dir = Path(args.out_dir) if args.out_dir else src.parent
        out = save_image(canvas, out_dir / f"{src.stem}-{args.preset or f'{tw}x{th}'}.png")
        outs.append(str(out))
    emit({"mode": mode, "size": [tw, th], "background": bg, "count": len(outs), "outputs": outs}, args.json)
    return 0


def cmd_sheet(args) -> int:
    srcs: list[Path] = []
    for p in args.inputs:
        p = Path(p)
        srcs += sorted([q for q in p.rglob("*") if q.suffix.lower() in
                        (".png", ".jpg", ".jpeg", ".webp")]) if p.is_dir() else [p]
    if not srcs:
        print("没有找到图片", file=sys.stderr)
        return 2
    cell = args.cell
    cols = args.cols or 4
    rows = (len(srcs) + cols - 1) // cols
    label_h = 22 if args.labels else 0
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    font = find_font(None, 14)
    for i, src in enumerate(srcs):
        img = Image.open(src).convert("RGB")
        img.thumbnail((cell - 8, cell - 8), Image.LANCZOS)
        cx = (i % cols) * cell + (cell - img.size[0]) // 2
        cy = (i // cols) * (cell + label_h) + (cell - img.size[1]) // 2
        sheet.paste(img, (cx, cy))
        if args.labels:
            draw.text(((i % cols) * cell + 4, (i // cols) * (cell + label_h) + cell + 2),
                      f"{i+1}. {src.name[:38]}", font=font, fill=(40, 40, 40))
    out = save_image(sheet, args.out or "contact-sheet.jpg")
    emit({"output": str(out), "count": len(srcs), "grid": f"{cols}x{rows}"}, args.json)
    return 0


def cmd_palette(args) -> int:
    img = Image.open(args.input).convert("RGB")
    small = img.resize((128, 128))
    q = small.quantize(colors=args.colors, method=Image.MEDIANCUT).convert("RGB")
    counts = sorted(q.getcolors(128 * 128) or [], reverse=True)
    total = sum(c for c, _ in counts) or 1
    palette = [{"hex": "#%02x%02x%02x" % rgb, "rgb": list(rgb), "share": round(c / total, 3)}
               for c, rgb in counts[: args.colors]]
    emit({"file": str(args.input), "palette": palette}, args.json)
    return 0


# ---------------------------- 视频（T2：需要 ffmpeg） ----------------------------

def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffprobe_json(ffmpeg: str, src: str) -> dict:
    """优先 ffprobe；没有 ffprobe 时解析 `ffmpeg -i` 的 stderr（imageio-ffmpeg 只带 ffmpeg）。"""
    import re

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        out = subprocess.run([ffprobe, "-v", "quiet", "-print_format", "json",
                              "-show_format", "-show_streams", src],
                             capture_output=True, text=True, errors="replace")
        try:
            return json.loads(out.stdout)
        except Exception:
            pass

    out = subprocess.run([ffmpeg, "-hide_banner", "-i", src],
                         capture_output=True, text=True, errors="replace")
    text = out.stderr or ""
    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    streams: list[dict] = []
    mv = re.search(r"Stream #\d+:\d+.*?: Video:\s*([A-Za-z0-9_]+).*?,\s*(\d+)x(\d+)", text)
    if mv:
        v: dict = {"codec_type": "video", "codec_name": mv.group(1),
                   "width": int(mv.group(2)), "height": int(mv.group(3))}
        mf = re.search(r"(\d+(?:\.\d+)?)\s*fps", text)
        if mf:
            v["r_frame_rate"] = mf.group(1)
        mpix = re.search(r"Video:\s*[A-Za-z0-9_]+.*?,\s*(yuv[a-z0-9]+|rgb[a0-9]*|gray)", text)
        if mpix:
            v["pix_fmt"] = mpix.group(1)
        streams.append(v)
    ma = re.search(r"Stream #\d+:\d+.*?: Audio:\s*([A-Za-z0-9_]+).*?,\s*(\d+)\s*Hz,\s*(\w+)", text)
    if ma:
        streams.append({"codec_type": "audio", "codec_name": ma.group(1),
                        "sample_rate": ma.group(2),
                        "channels": 2 if ma.group(3) == "stereo" else 1})

    size = os.path.getsize(src) if os.path.exists(src) else 0
    return {
        "format": {"duration": duration, "size": size,
                   "bit_rate": int(size * 8 / duration) if duration else 0},
        "streams": streams,
    }


def cmd_video_probe(args) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        warn_tier("video", "pip install imageio-ffmpeg  （或系统安装 ffmpeg）")
        return 3
    reports = []
    for src in args.inputs:
        data = ffprobe_json(ffmpeg, src)
        fmt = data.get("format", {})
        v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
        reports.append({
            "file": str(src),
            "duration_s": round(float(fmt.get("duration", 0) or 0), 2),
            "size_mb": round(float(fmt.get("size", 0) or 0) / 1e6, 2),
            "bitrate_kbps": int(float(fmt.get("bit_rate", 0) or 0) / 1000),
            "video": {"codec": v.get("codec_name"), "size": f"{v.get('width')}x{v.get('height')}",
                      "fps": v.get("r_frame_rate"), "pix_fmt": v.get("pix_fmt")},
            "audio": {"codec": a.get("codec_name"), "channels": a.get("channels"),
                      "sample_rate": a.get("sample_rate")} if a else None,
        })
    emit({"count": len(reports), "videos": reports}, args.json)
    return 0


def cmd_video_sheet(args) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3
    out_dir = Path(args.out_dir or "video-sheet")
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = []
    for src in args.inputs:
        stem = Path(src).stem
        vf = f"fps=1/{args.interval},scale={args.width}:-1"
        target = out_dir / f"{stem}-%03d.jpg"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vf", vf, str(target)]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        frames = sorted(out_dir.glob(f"{stem}-*.jpg"))
        produced.append({"file": str(src), "frames": len(frames), "dir": str(out_dir),
                         "error": None if r.returncode == 0 else r.stderr[:300]})
    emit({"videos": produced}, args.json)
    return 0


# ---------------------------- 视频剪辑 ----------------------------

def parse_time(value: str | float | None) -> float | None:
    """接受 12.5 / 1:30 / 00:01:30.250 → 秒。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).strip().split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        raise SystemExit(f"时间格式无法解析: {value}")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def run_ff(args_list: list[str]) -> tuple[int, str]:
    r = subprocess.run(args_list, capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stderr or "").strip()


def cmd_video_cut(args) -> int:
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3
    start = parse_time(args.start) or 0.0
    end = parse_time(args.end)
    dur = parse_time(args.duration)
    if end is not None and end <= start:
        print("CUT_ERROR: --end 必须大于 --start", file=sys.stderr)
        return 2
    outs = []
    for src in args.inputs:
        out = Path(args.out) if args.out and len(args.inputs) == 1 else \
            Path(args.out_dir or Path(src).parent) / f"{Path(src).stem}-cut{Path(src).suffix}"
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y"]
        if args.accurate:
            cmd += ["-i", src, "-ss", f"{start:.3f}"]
            if end is not None:
                cmd += ["-to", f"{end:.3f}"]
            elif dur is not None:
                cmd += ["-t", f"{dur:.3f}"]
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
        else:
            cmd += ["-ss", f"{start:.3f}", "-i", src]
            if end is not None:
                cmd += ["-to", f"{end - start:.3f}"]
            elif dur is not None:
                cmd += ["-t", f"{dur:.3f}"]
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero", str(out)]
        code, err = run_ff(cmd)
        outs.append({"output": str(out), "start_s": start,
                     "end_s": end, "duration_s": dur,
                     "mode": "accurate(reencode)" if args.accurate else "fast(copy)",
                     "error": None if code == 0 else err[:300]})
    emit({"cuts": outs}, args.json)
    return 0


def cmd_video_join(args) -> int:
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3
    srcs = [str(Path(p)) for p in args.inputs]
    if len(srcs) < 2:
        print("JOIN_ERROR: 至少两个输入", file=sys.stderr)
        return 2
    out = Path(args.out or "joined.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.transition and args.transition != "none":
        # 先把每个输入归一化（时基/帧率/像素格式/采样率统一），否则 xfade 会报 timebase 不匹配
        probes = [ffprobe_json(ff, s) for s in srcs]
        durs = [float(p.get("format", {}).get("duration", 0) or 0) for p in probes]
        has_audio = [any(st.get("codec_type") == "audio" for st in p.get("streams", [])) for p in probes]
        use_audio = all(has_audio)
        target_fps = getattr(args, "fps", None) or 30
        v0 = next((st for st in probes[0].get("streams", []) if st.get("codec_type") == "video"), {})
        W = int(v0.get("width") or 1080)
        H = int(v0.get("height") or 1920)

        filters: list[str] = []
        for i in range(len(srcs)):
            filters.append(
                f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={target_fps},"
                f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}]")
            if use_audio:
                filters.append(
                    f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                    f"asetpts=PTS-STARTPTS[a{i}]")

        cur_v, cur_a, offset = "[v0]", "[a0]", 0.0
        for i in range(1, len(srcs)):
            offset += durs[i - 1] - args.transition_duration
            filters.append(f"{cur_v}[v{i}]xfade=transition={args.transition}:"
                           f"duration={args.transition_duration}:offset={max(0.0, offset):.3f}[x{i}]")
            if use_audio:
                filters.append(f"{cur_a}[a{i}]acrossfade=d={args.transition_duration}[y{i}]")
            cur_v, cur_a = f"[x{i}]", f"[y{i}]"

        # xfade 会重新协商像素格式，链尾强制回 yuv420p 保证播放器/平台兼容
        filters.append(f"{cur_v}format=yuv420p[vout]")
        cur_v = "[vout]"

        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y"]
        for s in srcs:
            cmd += ["-i", s]
        cmd += ["-filter_complex", ";".join(filters), "-map", cur_v]
        if use_audio:
            cmd += ["-map", cur_a, "-c:a", "aac", "-b:a", "160k"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(out)]
    else:
        listfile = out.with_suffix(".concat.txt")
        listfile.write_text("".join(f"file '{s.replace(chr(92), '/')}'\n" for s in srcs), encoding="utf-8")
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
               "-i", str(listfile), "-c", "copy", str(out)]
        if args.reencode:
            cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                   "-i", str(listfile), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                   "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]

    code, err = run_ff(cmd)
    ratio = (out.stat().st_size / (1e6)) if out.exists() else 0
    emit({"output": str(out), "inputs": len(srcs), "transition": args.transition or "none",
          "size_mb": round(ratio, 2), "error": None if code == 0 else err[:400]}, args.json)
    return 0


def build_subtitle_style(args) -> str:
    """生成 ASS 样式串（注意 ASS 颜色为 &HAABBGGRR）。"""
    def bgr(hex_color: str) -> str:
        r, g, b, a = parse_color(hex_color)
        return f"&H{255 - a:02X}{b:02X}{g:02X}{r:02X}"

    return (f"FontName={args.font_name},FontSize={args.font_size},"
            f"PrimaryColour={bgr(args.color)},OutlineColour={bgr(args.outline_color)},"
            f"BorderStyle=1,Outline={args.outline},Shadow={args.shadow},"
            f"Alignment={args.alignment},MarginV={args.margin_v}")


def cmd_video_subtitle(args) -> int:
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3
    sub = Path(args.subtitle)
    if not sub.exists():
        print(f"SUBTITLE_ERROR: 找不到字幕文件 {sub}", file=sys.stderr)
        return 2
    out = Path(args.out or Path(args.input).with_name(Path(args.input).stem + "-sub.mp4"))
    style = build_subtitle_style(args)
    # Windows 路径需转义盘符冒号
    sub_escaped = str(sub).replace("\\", "/").replace(":", r"\:")
    vf = f"subtitles='{sub_escaped}':force_style='{style}'"
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", args.input,
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "copy", "-movflags", "+faststart", str(out)]
    code, err = run_ff(cmd)
    emit({"output": str(out), "subtitle": str(sub), "style": style,
          "error": None if code == 0 else err[:400]}, args.json)
    return 0


def render_text_png(width: int, height: int, args) -> Image.Image:
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    size = args.size or max(18, int(width * 0.055))
    font = find_font(args.font, size)
    margin = args.margin
    max_w = int(width * args.max_width_ratio)
    lines = wrap_text(draw, args.text, font, max_w)
    line_h = int(size * 1.28)
    block_h = line_h * len(lines)
    widest = max((draw.textlength(ln, font=font) for ln in lines), default=0)
    x, y = anchor_box((width, height), (int(widest), block_h), args.position, margin)
    if args.position in ("tc", "mc", "bc"):
        x = int((width - widest) / 2)
    if args.position in ("tc",):
        y = margin
    if args.position in ("bc",):
        y = height - block_h - margin
    if args.position == "mc":
        y = int((height - block_h) / 2)
    if args.box:
        pad = int(size * 0.35)
        draw.rounded_rectangle([x - pad, y - pad, x + widest + pad, y + block_h + pad],
                               radius=int(size * 0.25), fill=parse_color(args.box))
    for i, ln in enumerate(lines):
        ly = y + i * line_h
        if args.shadow:
            draw.text((x + max(1, size // 24), ly + max(1, size // 24)), ln, font=font,
                      fill=parse_color(args.shadow))
        draw.text((x, ly), ln, font=font, fill=parse_color(args.color),
                  stroke_width=args.stroke_width,
                  stroke_fill=parse_color(args.stroke) if args.stroke else None)
    return layer


def cmd_video_text(args) -> int:
    """在视频上贴文字（PIL 渲染透明 PNG → ffmpeg overlay，支持时间段显示）。"""
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3
    data = ffprobe_json(ff, args.input)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    W, H = int(v.get("width") or 1080), int(v.get("height") or 1920)
    overlay = render_text_png(W, H, args)
    tmp = Path(args.png_out or Path(args.input).with_name(Path(args.input).stem + "-text-overlay.png"))
    save_image(overlay, tmp)
    out = Path(args.out or Path(args.input).with_name(Path(args.input).stem + "-text.mp4"))
    start = parse_time(args.start) or 0.0
    end = parse_time(args.end)
    enable = f":enable='between(t,{start:.3f},{end:.3f})'" if end else (f":enable='gte(t,{start:.3f})'" if start else "")
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", args.input, "-i", str(tmp),
           "-filter_complex", f"[0:v][1:v]overlay=0:0{enable}[v]",
           "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "copy", "-movflags", "+faststart", str(out)]
    code, err = run_ff(cmd)
    emit({"output": str(out), "overlay_png": str(tmp), "canvas": [W, H],
          "window_s": [start, end], "error": None if code == 0 else err[:400]}, args.json)
    return 0


def cmd_video_audio(args) -> int:
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3
    out = Path(args.out or Path(args.input).with_name(Path(args.input).stem + "-audio.mp4"))
    if not args.music:
        # 只做原声处理（音量/淡入淡出/静音）
        filters = []
        if args.mute:
            cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", args.input,
                   "-an", "-c:v", "copy", str(out)]
        else:
            if args.original_volume != 1.0:
                filters.append(f"volume={args.original_volume}")
            if args.fade_in:
                filters.append(f"afade=t=in:st=0:d={args.fade_in}")
            if args.fade_out:
                dur = float(ffprobe_json(ff, args.input).get("format", {}).get("duration", 0) or 0)
                filters.append(f"afade=t=out:st={max(0.0, dur - args.fade_out):.3f}:d={args.fade_out}")
            cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", args.input]
            if filters:
                cmd += ["-af", ",".join(filters)]
            cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)]
    else:
        dur = float(ffprobe_json(ff, args.input).get("format", {}).get("duration", 0) or 0)
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y"]
        if args.loop:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", args.music, "-i", args.input]
        bg = [f"volume={args.music_volume}"]
        if args.fade_in:
            bg.append(f"afade=t=in:st=0:d={args.fade_in}")
        if args.fade_out and dur:
            bg.append(f"afade=t=out:st={max(0.0, dur - args.fade_out):.3f}:d={args.fade_out}")
        orig = "volume=0" if args.mute else f"volume={args.original_volume}"
        fc = (f"[0:a]{','.join(bg)}[bg];[1:a]{orig}[orig];"
              f"[bg][orig]amix=inputs=2:duration=first:dropout_transition=0[a]")
        cmd += ["-filter_complex", fc, "-map", "1:v", "-map", "[a]",
                "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(out)]
    code, err = run_ff(cmd)
    emit({"output": str(out), "music": args.music, "music_volume": args.music_volume,
          "original_volume": args.original_volume, "mute": args.mute,
          "error": None if code == 0 else err[:400]}, args.json)
    return 0


def cmd_video_cover(args) -> int:
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3
    outs = []
    for src in args.inputs:
        data = ffprobe_json(ff, src)
        dur = float(data.get("format", {}).get("duration", 0) or 0)
        at = parse_time(args.at) if args.at else (dur / 2 if dur else 0)
        tmp_dir = Path(args.out_dir or Path(src).parent)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(src).stem
        if args.scan and args.scan > 1 and dur:
            # 多点采样，取边缘能量（清晰度）最高的一帧做封面
            best, best_score = None, -1.0
            for i in range(args.scan):
                t = dur * (i + 0.5) / args.scan
                f = tmp_dir / f"{stem}-scan{i:02d}.jpg"
                run_ff([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}",
                        "-i", src, "-frames:v", "1", "-q:v", "2", str(f)])
                if not f.exists():
                    continue
                img = Image.open(f).convert("L")
                edges = img.filter(ImageFilter.FIND_EDGES)
                score = ImageStat.Stat(edges).stddev[0]
                if score > best_score:
                    best, best_score = (f, t, score), score
            if best:
                f, t, score = best
                out = Path(args.out or tmp_dir / f"{stem}-cover.jpg")
                save_image(Image.open(f), out)
                outs.append({"file": str(src), "output": str(out), "at_s": round(t, 2),
                             "sharpness": round(score, 1), "mode": "scan"})
                for g in tmp_dir.glob(f"{stem}-scan*.jpg"):
                    if g != f:
                        g.unlink(missing_ok=True)
                continue
        out = Path(args.out or tmp_dir / f"{stem}-cover.jpg")
        code, err = run_ff([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.3f}",
                            "-i", src, "-frames:v", "1", "-q:v", "2", str(out)])
        outs.append({"file": str(src), "output": str(out), "at_s": round(at, 2),
                     "mode": "at", "error": None if code == 0 else err[:200]})
    emit({"covers": outs}, args.json)
    return 0


VIDEO_PRESETS = {
    "reel-9x16": (1080, 1920), "story-9x16": (1080, 1920),
    "wide-16x9": (1920, 1080), "square-1x1": (1080, 1080),
    "thumb-4x5": (1080, 1350), "hd-720p": (1280, 720),
}


def cmd_video_export(args) -> int:
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3
    if args.preset in VIDEO_PRESETS:
        tw, th = VIDEO_PRESETS[args.preset]
    elif args.size:
        tw, th = (int(v) for v in args.size.lower().split("x"))
    else:
        print("需要 --preset 或 --size WxH", file=sys.stderr)
        return 2
    outs = []
    for src in args.inputs:
        out = Path(args.out) if args.out and len(args.inputs) == 1 else \
            Path(args.out_dir or Path(src).parent) / f"{Path(src).stem}-{args.preset or f'{tw}x{th}'}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        if args.mode == "crop":
            vf = f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}"
        else:
            vf = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                  f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color={args.bg}")
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vf", vf]
        if args.fps:
            cmd += ["-r", str(args.fps)]
        cmd += ["-c:v", "libx264", "-preset", args.preset_speed, "-crf", str(args.crf),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                "-movflags", "+faststart", str(out)]
        code, err = run_ff(cmd)
        outs.append({"output": str(out), "size": f"{tw}x{th}", "mode": args.mode,
                     "crf": args.crf, "error": None if code == 0 else err[:300]})
    emit({"exports": outs}, args.json)
    return 0



# ---------------------------- 自检 / 验收 ----------------------------

def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """以子进程方式调用本 CLI 自身，确保测的是真实命令行接口。"""
    r = subprocess.run([sys.executable, str(Path(__file__).resolve())] + argv,
                       capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _probe(path: Path) -> dict:
    ff = find_ffmpeg()
    if not ff:
        return {}
    data = ffprobe_json(ff, str(path))
    fmt = data.get("format", {})
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {"duration": float(fmt.get("duration", 0) or 0),
            "size_mb": round(float(fmt.get("size", 0) or 0) / 1e6, 3),
            "width": v.get("width"), "height": v.get("height"),
            "pix_fmt": v.get("pix_fmt"), "has_audio": bool(a)}


def cmd_selftest(args) -> int:
    """端到端验收：自造素材 → 跑全部命令 → 核对产物。每台机器可独立运行。"""
    work = Path(args.work_dir) if args.work_dir else \
        Path(__file__).resolve().parent.parent / "tests" / "out" / "selftest"
    work.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:240]})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {str(detail)[:110]}" if detail else ""), flush=True)

    # ---------- 造素材 ----------
    a = Image.new("RGB", (800, 800), (245, 245, 245))
    da = ImageDraw.Draw(a)
    da.ellipse((180, 180, 620, 620), fill=(31, 110, 67))
    da.rectangle((300, 300, 500, 500), fill=(252, 252, 252))
    fx1 = work / "fixture-a.png"
    a.save(fx1)

    b = Image.new("RGB", (800, 800), (250, 248, 240))
    db = ImageDraw.Draw(b)
    db.rounded_rectangle((160, 260, 640, 560), radius=40, fill=(183, 208, 238))
    fx2 = work / "fixture-b.png"
    b.save(fx2)

    logo = Image.new("RGB", (480, 140), (255, 255, 255))
    ImageDraw.Draw(logo).text((24, 36), "YLIGHT", font=find_font(None, 64), fill=(31, 110, 67))
    fx_logo = work / "logo.png"
    logo.save(fx_logo)

    srt = work / "subs.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:02,500\nSelf-test subtitle cue\n", encoding="utf-8")

    ff = find_ffmpeg()
    clip1 = work / "clip-a.mp4"
    clip2 = work / "clip-b.mp4"
    if ff:
        for src, dst, dur in ((fx1, clip1, 4), (fx2, clip2, 3)):
            run_ff([ff, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(src),
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-t", str(dur), "-r", "30", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(dst)])

    def call(args_list: list[str]) -> tuple[int, str, str]:
        return _run_cli(args_list + ["--json"])

    # ---------- T0 图片基础 ----------
    code, out, err = call(["inspect", str(fx1)])
    check("T0 inspect", code == 0 and '"size"' in out and "800" in out, err)

    t1 = work / "t1-text.png"
    code, _, err = call(["text", str(fx1), "--text", "验收自检\nSelf Test", "--position", "bc",
                         "--size", "56", "--color", "white", "--stroke", "#1F6E43",
                         "--stroke-width", "5", "--out", str(t1)])
    check("T0 text (中英混排)", code == 0 and t1.exists(), err)

    t2 = work / "t2-logo.png"
    code, _, err = call(["logo", str(t1), "--logo", str(fx_logo), "--position", "br",
                         "--width-ratio", "0.2", "--key-white", "--out", str(t2)])
    check("T0 logo (白底自动抠)", code == 0 and t2.exists(), err)

    t3 = work / "t3-compose.png"
    code, _, err = call(["compose", str(fx2), "--overlay", f"{fx_logo}:50%:80%:0.35", "--out", str(t3)])
    check("T0 compose (百分比定位)", code == 0 and t3.exists(), err)

    t4dir = work / "export"
    code, _, err = call(["export", str(t2), "--preset", "amazon-main", "--out-dir", str(t4dir)])
    t4 = t4dir / "t2-logo-amazon-main.png"
    ok_size = False
    if t4.exists():
        ok_size = Image.open(t4).size == (2000, 2000)
    check("T0 export (amazon-main 2000²)", code == 0 and ok_size, err)

    t5 = work / "sheet.jpg"
    code, _, err = call(["sheet", str(fx1), str(fx2), "--out", str(t5), "--labels"])
    check("T0 sheet (接触表)", code == 0 and t5.exists(), err)

    code, out, err = call(["palette", str(fx1), "--colors", "4"])
    check("T0 palette", code == 0 and "#" in out, err)

    # ---------- T1 抠图 ----------
    m1 = work / "m1-matte.png"
    code, _, err = call(["matte", str(fx1), "--out", str(m1)])
    alpha_ok = False
    if m1.exists():
        im = Image.open(m1)
        alpha_ok = im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 255
    check("T1 matte (RGBA + 透明)", code == 0 and alpha_ok, err)

    m2 = work / "m2-white.png"
    code, _, err = call(["matte", str(fx1), "--bg", "white", "--feather", "1.5", "--out", str(m2)])
    check("T1 matte --bg white --feather", code == 0 and m2.exists(), err)

    # ---------- T1 改图（局部重绘）----------
    ip = work / "ip-test.png"
    code, out, err = call(["inpaint", str(fx1), "--box", "0,0,220,140", "--dilate", "2", "--out", str(ip)])
    changed = False
    if ip.exists() and code == 0:
        try:
            import numpy as np
            before = np.asarray(Image.open(fx1).convert("RGB").crop((0, 0, 220, 140)), dtype=float)
            after = np.asarray(Image.open(ip).convert("RGB").crop((0, 0, 220, 140)), dtype=float)
            changed = float(np.abs(before - after).mean()) > 1.0
        except Exception:
            changed = False
    check("T1 inpaint (局部重绘改图)", code == 0 and changed, err)

    # ---------- T2 视频 ----------
    code, out, err = call(["video-probe", str(clip1)])
    check("T2 video-probe", code == 0 and '"duration_s"' in out, err)
    if not ff:
        check("T2 ffmpeg 可用", False, "未找到 ffmpeg（imageio-ffmpeg 未安装）")

    vdir = work / "vsheet"
    code, _, err = call(["video-sheet", str(clip1), "--interval", "1", "--width", "320", "--out-dir", str(vdir)])
    frames = len(list(vdir.glob("clip-a-*.jpg"))) if vdir.exists() else 0
    check("T2 video-sheet (抽帧)", code == 0 and frames >= 3, f"frames={frames} {err}")

    vcut = work / "v-cut.mp4"
    code, _, err = call(["video-cut", str(clip1), "--start", "1", "--duration", "2", "--accurate", "--out", str(vcut)])
    p = _probe(vcut)
    check("T2 video-cut --accurate", code == 0 and abs(p.get("duration", 0) - 2.0) < 0.25, f"dur={p.get('duration')} {err}")

    vjoin = work / "v-join.mp4"
    code, _, err = call(["video-join", str(clip1), str(clip2), "--transition", "fade",
                         "--transition-duration", "0.5", "--out", str(vjoin)])
    p = _probe(vjoin)
    ok = code == 0 and abs(p.get("duration", 0) - 6.5) < 0.4 and p.get("pix_fmt") == "yuv420p"
    check("T2 video-join (fade, yuv420p)", ok, f"dur={p.get('duration')} pix={p.get('pix_fmt')} {err}")

    vtext = work / "v-text.mp4"
    code, _, err = call(["video-text", str(clip1), "--text", "验收自检\nSelf Test", "--position", "tc",
                         "--size", "40", "--stroke", "#1F6E43", "--stroke-width", "4", "--out", str(vtext)])
    check("T2 video-text (中英贴片)", code == 0 and vtext.exists(), err)

    vsub = work / "v-sub.mp4"
    code, _, err = call(["video-subtitle", str(clip1), "--subtitle", str(srt), "--out", str(vsub)])
    check("T2 video-subtitle (SRT 烧入)", code == 0 and vsub.exists(), err)

    vaudio = work / "v-audio.mp4"
    code, _, err = call(["video-audio", str(clip1), "--original-volume", "0.8",
                         "--fade-in", "0.5", "--fade-out", "0.5", "--out", str(vaudio)])
    check("T2 video-audio (淡入淡出)", code == 0 and vaudio.exists(), err)

    vcover = work / "v-cover.jpg"
    code, out, err = call(["video-cover", str(clip1), "--scan", "4", "--out", str(vcover)])
    check("T2 video-cover (智能选帧)", code == 0 and vcover.exists(), err)

    vexp = work / "v-export.mp4"
    code, _, err = call(["video-export", str(clip1), "--preset", "reel-9x16", "--out", str(vexp)])
    p = _probe(vexp)
    check("T2 video-export (9:16)", code == 0 and p.get("width") == 1080 and p.get("height") == 1920,
          f"{p.get('width')}x{p.get('height')} {err}")

    # ---------- 汇总 ----------
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    report = {"passed": passed, "total": total, "failed": [r for r in results if not r["ok"]],
              "work_dir": str(work), "checks": results}
    (work / "acceptance-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
    print(f"\n验收结果：{passed}/{total} 通过" + ("" if passed == total else "  ← 有失败项，见上方 FAIL"))
    print(f"报告：{work / 'acceptance-report.json'}")
    return 0 if passed == total else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cs", description="DSH Creative Studio toolkit")
    p.add_argument("--json", action="store_true", help="以 JSON 输出（agent 友好）")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="环境自检（依赖/模型/ffmpeg/GPU）")
    d.set_defaults(func=cmd_doctor)

    i = sub.add_parser("inspect", help="图片体检（尺寸/透明通道/主体占比/亮度）")
    i.add_argument("inputs", nargs="+")
    i.set_defaults(func=cmd_inspect)

    m = sub.add_parser("matte", help="抠图（T1：rembg）")
    m.add_argument("inputs", nargs="+")
    m.add_argument("--model", default="auto",
                   help="auto（默认，按 --quality 策略）| u2net | u2net_human_seg | isnet-general-use | "
                        "birefnet-general | birefnet-portrait | birefnet-general-lite | bria-rmbg | sam | silueta")
    m.add_argument("--quality", default="auto", choices=["fast", "auto", "best"],
                   help="fast=u2net 最快 / auto=≤2MP 用 birefnet、大图用 isnet / best=birefnet 始终最高质量")
    m.add_argument("--out")
    m.add_argument("--bg", help="抠完合成到指定底色，如 white/#f5f5f5")
    m.add_argument("--feather", type=float, default=0.0, help="边缘羽化像素")
    m.add_argument("--alpha-matting", action="store_true")
    m.add_argument("--fg-threshold", type=int, default=240)
    m.add_argument("--bg-threshold", type=int, default=10)
    m.add_argument("--erode", type=int, default=10)
    m.set_defaults(func=cmd_matte)

    t = sub.add_parser("text", help="加文字（换行/描边/阴影/底色块）")
    t.add_argument("input")
    t.add_argument("--text", required=True)
    t.add_argument("--out")
    t.add_argument("--position", default="bc", choices=sorted(POSITIONS))
    t.add_argument("--size", type=int)
    t.add_argument("--font")
    t.add_argument("--color", default="white")
    t.add_argument("--stroke")
    t.add_argument("--stroke-width", type=int, default=0)
    t.add_argument("--shadow")
    t.add_argument("--box", help="文字底块颜色，如 #00000099")
    t.add_argument("--margin", type=int, default=48)
    t.add_argument("--max-width-ratio", type=float, default=0.9)
    t.set_defaults(func=cmd_text)

    lg = sub.add_parser("logo", help="贴 logo/水印（九宫格定位、透明度、白底自动抠）")
    lg.add_argument("input")
    lg.add_argument("--logo", required=True)
    lg.add_argument("--out")
    lg.add_argument("--position", default="br", choices=sorted(POSITIONS))
    lg.add_argument("--width-ratio", type=float, default=0.18)
    lg.add_argument("--margin", type=int, default=40)
    lg.add_argument("--opacity", type=float, default=1.0)
    lg.add_argument("--key-white", action="store_true", help="白底 logo 自动透明化")
    lg.set_defaults(func=cmd_logo)

    ip = sub.add_parser("inpaint", help="局部重绘改图：去杂物/水印/瑕疵（telea 零依赖；lama-onnx 更强）")
    ip.add_argument("input")
    ip.add_argument("--mask", help="掩码图（白色=要重绘的区域），尺寸可不同会自动缩放")
    ip.add_argument("--box", action="append", help="矩形区域 x,y,w,h，可重复")
    ip.add_argument("--circle", action="append", help="圆形区域 x,y,r，可重复")
    ip.add_argument("--dilate", type=int, default=0, help="掩码外扩像素（消除残影）")
    ip.add_argument("--backend", default="auto", choices=["auto", "telea", "ns", "lama-onnx"])
    ip.add_argument("--radius", type=int, default=6, help="telea/ns 的邻域半径")
    ip.add_argument("--lama-model", help="LaMa ONNX 模型路径（或设环境变量 CS_LAMA_ONNX）")
    ip.add_argument("--lama-size", type=int, default=512)
    ip.add_argument("--out")
    ip.set_defaults(func=cmd_inpaint)

    c = sub.add_parser("compose", help="多图层合成：--overlay path:x:y[:scale]")
    c.add_argument("base")
    c.add_argument("--overlay", action="append", required=True)
    c.add_argument("--out")
    c.set_defaults(func=cmd_compose)

    e = sub.add_parser("export", help="平台规格导出（pad/fit/crop，支持目录批处理）")
    e.add_argument("inputs", nargs="+")
    e.add_argument("--preset", choices=sorted(PRESETS))
    e.add_argument("--size", help="自定义 WxH")
    e.add_argument("--mode", choices=["pad", "fit", "crop"])
    e.add_argument("--bg")
    e.add_argument("--out-dir")
    e.set_defaults(func=cmd_export)

    s = sub.add_parser("sheet", help="图片接触表（选片/交付预览）")
    s.add_argument("inputs", nargs="+")
    s.add_argument("--out")
    s.add_argument("--cols", type=int, default=4)
    s.add_argument("--cell", type=int, default=320)
    s.add_argument("--labels", action="store_true")
    s.set_defaults(func=cmd_sheet)

    pal = sub.add_parser("palette", help="主色提取（配色/包装参考）")
    pal.add_argument("input")
    pal.add_argument("--colors", type=int, default=6)
    pal.set_defaults(func=cmd_palette)

    vp = sub.add_parser("video-probe", help="视频通览：时长/分辨率/码率/音轨")
    vp.add_argument("inputs", nargs="+")
    vp.set_defaults(func=cmd_video_probe)

    vs = sub.add_parser("video-sheet", help="视频抽帧（每 N 秒一张，供通览）")
    vs.add_argument("inputs", nargs="+")
    vs.add_argument("--interval", type=float, default=2.0)
    vs.add_argument("--width", type=int, default=480)
    vs.add_argument("--out-dir")
    vs.set_defaults(func=cmd_video_sheet)

    vc = sub.add_parser("video-cut", help="视频裁切（默认秒切 copy；--accurate 精确重编码）")
    vc.add_argument("inputs", nargs="+")
    vc.add_argument("--start", help="起点：12.5 或 1:30 或 00:01:30.250")
    vc.add_argument("--end", help="终点（绝对时间）")
    vc.add_argument("--duration", help="时长（与 --end 二选一）")
    vc.add_argument("--accurate", action="store_true")
    vc.add_argument("--out")
    vc.add_argument("--out-dir")
    vc.set_defaults(func=cmd_video_cut)

    vj = sub.add_parser("video-join", help="视频拼接（默认无损 copy；--transition 加转场重编码）")
    vj.add_argument("inputs", nargs="+")
    vj.add_argument("--out")
    vj.add_argument("--transition", default="none",
                    help="none|fade|wipeleft|wiperight|slideup|slidedown|circleopen|dissolve")
    vj.add_argument("--transition-duration", type=float, default=0.5)
    vj.add_argument("--fps", type=int, default=30, help="转场拼接时的统一帧率")
    vj.add_argument("--reencode", action="store_true", help="无转场时也重编码（参数不一致时用）")
    vj.set_defaults(func=cmd_video_join)

    vsub = sub.add_parser("video-subtitle", help="烧入字幕（SRT/ASS，可调字体/描边/位置）")
    vsub.add_argument("input")
    vsub.add_argument("--subtitle", required=True)
    vsub.add_argument("--out")
    vsub.add_argument("--font-name", default="Microsoft YaHei")
    vsub.add_argument("--font-size", type=int, default=24)
    vsub.add_argument("--color", default="white")
    vsub.add_argument("--outline-color", default="#000000")
    vsub.add_argument("--outline", type=int, default=2)
    vsub.add_argument("--shadow", type=int, default=0)
    vsub.add_argument("--alignment", type=int, default=2, help="1 左下 / 2 中下 / 3 右下 …（ASS 编号）")
    vsub.add_argument("--margin-v", type=int, default=40)
    vsub.set_defaults(func=cmd_video_subtitle)

    vt = sub.add_parser("video-text", help="视频贴文字（透明 PNG overlay，可限时间段）")
    vt.add_argument("input")
    vt.add_argument("--text", required=True)
    vt.add_argument("--out")
    vt.add_argument("--png-out", help="保留生成的文字层 PNG 便于复用")
    vt.add_argument("--position", default="bc", choices=sorted(POSITIONS))
    vt.add_argument("--size", type=int)
    vt.add_argument("--font")
    vt.add_argument("--color", default="white")
    vt.add_argument("--stroke")
    vt.add_argument("--stroke-width", type=int, default=0)
    vt.add_argument("--shadow")
    vt.add_argument("--box")
    vt.add_argument("--margin", type=int, default=80)
    vt.add_argument("--max-width-ratio", type=float, default=0.9)
    vt.add_argument("--start")
    vt.add_argument("--end")
    vt.set_defaults(func=cmd_video_text)

    va = sub.add_parser("video-audio", help="配乐/混音/淡入淡出/静音")
    va.add_argument("input")
    va.add_argument("--music")
    va.add_argument("--music-volume", type=float, default=0.35)
    va.add_argument("--original-volume", type=float, default=1.0)
    va.add_argument("--mute", action="store_true")
    va.add_argument("--fade-in", type=float, default=0.0)
    va.add_argument("--fade-out", type=float, default=0.0)
    va.add_argument("--loop", action="store_true", help="音乐短于视频时循环")
    va.add_argument("--out")
    va.set_defaults(func=cmd_video_audio)

    vcov = sub.add_parser("video-cover", help="导出封面帧（--scan N 自动挑最清晰的一帧）")
    vcov.add_argument("inputs", nargs="+")
    vcov.add_argument("--at", help="指定时间点")
    vcov.add_argument("--scan", type=int, default=0, help="采样帧数，>1 时自动选最清晰帧")
    vcov.add_argument("--out")
    vcov.add_argument("--out-dir")
    vcov.set_defaults(func=cmd_video_cover)

    ve = sub.add_parser("video-export", help="视频平台规格导出（9:16 / 16:9 / 1:1 / 4:5，pad 或 crop）")
    ve.add_argument("inputs", nargs="+")
    ve.add_argument("--preset", choices=sorted(VIDEO_PRESETS))
    ve.add_argument("--size", help="自定义 WxH")
    ve.add_argument("--mode", choices=["pad", "crop"], default="pad")
    ve.add_argument("--bg", default="white")
    ve.add_argument("--fps", type=int)
    ve.add_argument("--crf", type=int, default=20)
    ve.add_argument("--preset-speed", default="veryfast")
    ve.add_argument("--out")
    ve.add_argument("--out-dir")
    ve.set_defaults(func=cmd_video_export)

    st = sub.add_parser("selftest", help="端到端验收：自造素材跑全部命令并核对产物")
    st.add_argument("--work-dir", help="验收工作目录（默认 tests/out/selftest）")
    st.set_defaults(func=cmd_selftest)

    return p


def main() -> int:
    # 允许 --json 出现在子命令前后（cs --json doctor / cs doctor --json）
    argv = sys.argv[1:]
    if "--json" in argv:
        argv = ["--json"] + [a for a in argv if a != "--json"]
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
