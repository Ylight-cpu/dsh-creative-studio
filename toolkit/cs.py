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
import time
import urllib.request
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
        tier = "T1 (image matting/onnx)" if report["model_cache_files"] else "T1 (image matting ready, model not downloaded yet)"
    if ff:
        tier += " + T2 (video editing: cut/join/subtitles/export)"
    # T3：视频抠像（RVM）与特效，依赖 onnxruntime；模型按需下载
    rvm = MODEL_DIR / RVM_MODELS["mobilenetv3"]["file"]
    report["rvm_model"] = {"path": str(rvm), "present": rvm.exists(),
                           "size_mb": round(rvm.stat().st_size / 1e6, 1) if rvm.exists() else None}
    if deps.get("onnxruntime"):
        tier += " + T3 (video matting/effects" + (", RVM model cached" if rvm.exists() else ", RVM downloads on first use") + ")"
    if ff:
        n_x = len(list_xfade_transitions(ff)) if "list_xfade_transitions" in globals() else 0
        report["xfade_transitions"] = n_x
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
        """质量策略：fast=u2net(最快) / auto=小图用 birefnet、大图先 isnet（质量不达标会自动升级）/ best=birefnet。
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

    def get_session(name: str):
        if name not in session_cache:
            session_cache[name] = new_session(name)
        return session_cache[name]

    session_cache: dict[str, object] = {}
    outs, reports = [], []
    for src in inputs:
        model = resolve_model(src)
        try:
            get_session(model)
        except Exception as e:
            print(f"MODEL_ERROR[{model}]: {e}", file=sys.stderr)
            return 4
        t0 = time.time()
        img = Image.open(src)

        def run_matte(mdl: str):
            return remove(img, session=get_session(mdl), alpha_matting=args.alpha_matting,
                          **({"alpha_matting_foreground_threshold": args.fg_threshold,
                              "alpha_matting_background_threshold": args.bg_threshold,
                              "alpha_matting_erode_size": args.erode} if args.alpha_matting else {}))

        cut = run_matte(model)
        qa = alpha_quality(cut)
        escalated = None
        # auto 策略：只看像素数不够——实测 2048×2048 用 isnet 边缘过渡 9.75px（糊边），
        # 而 birefnet 只要 6 秒且降到 2.99px。因此按【边缘质量实测结果】自动升级。
        if (args.quality == "auto" and model != "birefnet-general"
                and qa.get("transition_px", 0) > 4.0):
            try:
                cut2 = run_matte("birefnet-general")
                qa2 = alpha_quality(cut2)
                if qa2.get("transition_px", 99) < qa.get("transition_px", 99):
                    escalated = f"{model}({qa.get('transition_px')}px) -> birefnet-general({qa2.get('transition_px')}px)"
                    cut, qa, model = cut2, qa2, "birefnet-general"
            except Exception as e:
                print(f"ESCALATE_SKIPPED: {e}", file=sys.stderr)
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
        # qa 取自合成前的 alpha 结果（加了 --bg 之后 alpha 已被吃掉，无法再量边缘）
        warning = None
        if qa.get("transition_px", 0) and qa["transition_px"] > 3.0:
            warning = (f"边缘过渡宽度 {qa['transition_px']}px 偏大（可能糊边/光晕）；"
                       "可试 --quality best 或 --alpha-matting")
        outs.append(str(out))
        reports.append({"input": str(src), "output": str(out), "model": model,
                        "seconds": round(elapsed, 2), "qa": qa, "escalated": escalated,
                        "warning": warning})
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


def subject_bbox(img: Image.Image, bg_tolerance: int = 14) -> tuple[int, int, int, int] | None:
    """求主体外接框：有 alpha 用 alpha；否则以边框主色为背景做差。

    用途：产品图常在整机居中时留下大片空白（实测某 2048² 图商品只占 31% 画幅），
    平台主图（如亚马逊）要求商品占画幅 ≥85%，必须先按主体紧裁再规格化。
    """
    try:
        import numpy as np
    except Exception:
        return None
    if img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 255:
        return img.getchannel("A").getbbox()
    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    h, w, _ = arr.shape
    border = np.concatenate([arr[0:2].reshape(-1, 3), arr[h - 2:h].reshape(-1, 3),
                             arr[:, 0:2].reshape(-1, 3), arr[:, w - 2:w].reshape(-1, 3)])
    bgc = np.median(border, axis=0)
    diff = np.abs(arr - bgc).max(axis=2)
    mask = diff > bg_tolerance
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


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

    outs, tightings = [], []
    for src in srcs:
        img = open_rgba(src)
        if args.tight:
            box = subject_bbox(img if not bg else img, args.tight_tolerance)
            if box:
                w, h = img.size
                mx = int(min(w, h) * args.tight)
                x0, y0, x1, y1 = box
                x0, y0 = max(0, x0 - mx), max(0, y0 - mx)
                x1, y1 = min(w, x1 + mx), min(h, y1 + mx)
                before = (x1 - x0) * (y1 - y0) / (w * h)
                img = img.crop((x0, y0, x1, y1))
                tightings.append({"file": str(src), "crop": [x0, y0, x1, y1],
                                  "was_fill": round(before, 3), "margin_ratio": args.tight})
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
        suffix = f"-tight{args.tight}" if args.tight else ""
        out = save_image(canvas, out_dir / f"{src.stem}-{args.preset or f'{tw}x{th}'}{suffix}.png")
        outs.append(str(out))
    payload = {"mode": mode, "size": [tw, th], "background": bg, "count": len(outs), "outputs": outs}
    if tightings:
        payload["tight"] = tightings
    emit(payload, args.json)
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


def list_xfade_transitions(ff: str) -> list[str]:
    """从 ffmpeg 自身枚举可用的 xfade 转场名（不写死列表，随构建更新）。"""
    out = subprocess.run([ff, "-hide_banner", "-h", "filter=xfade"],
                         capture_output=True, text=True, errors="replace").stdout or ""
    names: set[str] = set()
    for line in out.splitlines():
        if "transition" in line.lower() and ":" in line and "fade" in line:
            continue
        for tok in line.replace(",", " ").split():
            t = tok.strip()
            if 3 <= len(t) <= 22 and t.islower() and t.isalpha():
                names.add(t)
    # 只保留真的能用的：以常见转场词典过滤，避免把参数名当成转场名
    known = {
        "fade", "fadeblack", "fadewhite", "fadegrays", "distance", "wipeleft", "wiperight",
        "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown", "smoothleft",
        "smoothright", "smoothup", "smoothdown", "circleopen", "circleclose", "circlecrop",
        "rectcrop", "vertopen", "vertclose", "horzopen", "horzclose", "dissolve", "pixelize",
        "radial", "hlslice", "hrslice", "vuslice", "vdslice", "hblur", "diagtl", "diagtr",
        "diagbl", "diagbr", "hlwind", "hrwind", "vuwind", "vdwind", "coverleft", "coverright",
        "coverup", "coverdown", "revealleft", "revealright", "revealup", "revealdown",
        "squeezev", "squeezeh", "zoomin", "lunax", "custom",
    }
    found = sorted((names & known) | {"fade"})
    return found


# 风格化转场：pre = 作用在"后一段"开头的效果（trim+效果+concat 实现，不依赖时间轴支持）
STYLIZED_TRANSITIONS = {
    "flash":      {"base": "fadewhite", "pre": None, "note": "白闪转场（原生 fadewhite）"},
    "glitch":     {"base": "pixelize", "pre": "rgbashift=rh=-14:bh=14,noise=alls=26:allf=t", "note": "故障风：色彩偏移+噪点后像素化切入"},
    "whip-pan":   {"base": "smoothleft", "pre": "tmix=frames=7:weights='1 1 1 2 2 3 3',boxblur=luma_radius=8:luma_power=1", "note": "鞭甩：方向性拖影后平滑左滑"},
    "soft-zoom":  {"base": "fade", "pre": "gblur=sigma=16", "note": "柔焦推入：高斯模糊后淡入（近似变焦）"},
    "film-burn":  {"base": "fadeblack", "pre": "colorbalance=rs=0.35:gs=-0.05:bs=-0.25,noise=alls=18:allf=t", "note": "胶片灼烧：暖色偏移+颗粒后黑场切入"},
}


def cmd_video_join(args) -> int:
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3

    if getattr(args, "list_transitions", False):
        names = list_xfade_transitions(ff)
        emit({"count": len(names), "xfade": names,
              "stylized": {k: v["note"] for k, v in STYLIZED_TRANSITIONS.items()}}, args.json)
        return 0

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
        stylized = STYLIZED_TRANSITIONS.get(args.transition)
        transition_name = stylized["base"] if stylized else args.transition
        pre_node: dict[int, str] = {}
        if stylized and stylized.get("pre"):
            # 把效果只加在"后一段"的开头：trim(0,d) 加效果 + trim(d) 原样，再 concat
            win = max(0.2, min(0.5, args.transition_duration))
            for i in range(1, len(srcs)):
                filters.append(
                    f"[{i}:v]trim=0:{win:.3f},setpts=PTS-STARTPTS,{stylized['pre']}[pe{i}];"
                    f"[{i}:v]trim={win:.3f},setpts=PTS-STARTPTS[pn{i}];"
                    f"[pe{i}][pn{i}]concat=n=2:v=1[pre{i}]")
                pre_node[i] = f"[pre{i}]"

        for i in range(len(srcs)):
            head = pre_node.get(i, f"[{i}:v]")
            filters.append(
                f"{head}settb=AVTB,setpts=PTS-STARTPTS,fps={target_fps},"
                f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}]")
            if use_audio:
                filters.append(
                    f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                    f"asetpts=PTS-STARTPTS[a{i}]")

        cur_v, cur_a, offset = "[v0]", "[a0]", 0.0
        for i in range(1, len(srcs)):
            offset += durs[i - 1] - args.transition_duration
            filters.append(f"{cur_v}[v{i}]xfade=transition={transition_name}:"
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



# ---------------------------- AI 视频抠像（RVM ONNX） ----------------------------

MODEL_DIR = Path(os.environ.get("CS_MODEL_DIR") or (Path.home() / ".dsh-creative-studio" / "models"))

RVM_MODELS = {
    "mobilenetv3": {
        "file": "rvm_mobilenetv3_fp32.onnx",
        "url": "https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_mobilenetv3_fp32.onnx",
        "min_bytes": 10 * 1024 * 1024,
        "note": "RVM MobileNetV3 — 14 MB，CPU 可跑，视频抠像首选",
    },
    "resnet50": {
        "file": "rvm_resnet50_fp32.onnx",
        "url": "https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_resnet50_fp32.onnx",
        "min_bytes": 60 * 1024 * 1024,
        "note": "RVM ResNet50 — 102 MB，边缘更好但更慢",
    },
}


def ensure_rvm_model(name: str) -> Path:
    """确保 RVM ONNX 模型就位（首次自动下载）。"""
    spec = RVM_MODELS.get(name)
    if not spec:
        raise SystemExit(f"未知模型 {name}；可选：{', '.join(RVM_MODELS)}")
    dest = MODEL_DIR / spec["file"]
    if dest.exists() and dest.stat().st_size >= spec["min_bytes"]:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[model] 下载 {spec['note']} ...", file=sys.stderr, flush=True)
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(spec["url"], timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r[model] {pct:3d}%  {done/1e6:.1f}/{total/1e6:.1f} MB", end="", file=sys.stderr, flush=True)
    print("", file=sys.stderr, flush=True)
    if tmp.stat().st_size < spec["min_bytes"]:
        tmp.unlink(missing_ok=True)
        raise SystemExit("模型下载不完整，请重试（或设 HTTPS_PROXY 走代理）")
    tmp.replace(dest)
    return dest


def _fps_of(v: dict) -> float:
    rate = v.get("r_frame_rate") or "30"
    try:
        if isinstance(rate, str) and "/" in rate:
            num, den = rate.split("/")
            return float(num) / float(den or 1)
        return float(rate)
    except Exception:
        return 30.0


def cmd_video_matte(args) -> int:
    """视频抠像换背景：AI（RVM ONNX，任意背景）或色键（绿幕，纯 ffmpeg）。"""
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3

    src = args.input
    data = ffprobe_json(ff, src)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    W, H = int(v.get("width") or 0), int(v.get("height") or 0)
    if not W or not H:
        print("MATTE_ERROR: 读不到视频尺寸", file=sys.stderr)
        return 2
    fps = _fps_of(v)
    limit = parse_time(args.limit) if args.limit else None
    out = Path(args.out or Path(src).with_name(Path(src).stem + "-matte.mp4"))

    # ---------- 色键路径（纯 ffmpeg，最快，适合绿幕素材）----------
    if args.backend == "chromakey" or args.key_color:
        key = args.key_color or "0x00FF00"
        chain = f"colorkey={key}:{args.key_similarity}:{args.key_blend}"
        if args.despill:
            chain += f",despill=type={args.despill}"
        pre = ["-y"] + (["-t", f"{limit:.3f}"] if limit else [])
        if args.bg_image:
            cmd = ([ff, "-hide_banner", "-loglevel", "error"] + pre + ["-i", src, "-loop", "1", "-i", str(args.bg_image),
                   "-filter_complex",
                   f"[0:v]{chain}[fg];[1:v]scale={W}:{H},setsar=1[bg];[bg][fg]overlay=shortest=1[v]",
                   "-map", "[v]", "-map", "0:a?", "-shortest",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
                   "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)])
        else:
            bg = args.bg_color or "white"
            cmd = ([ff, "-hide_banner", "-loglevel", "error"] + pre + ["-i", src,
                   "-filter_complex",
                   f"[0:v]{chain}[fg];color=c={bg}:s={W}x{H}:r={fps:.3f}[bg];[bg][fg]overlay=shortest=1[v]",
                   "-map", "[v]", "-map", "0:a?", "-shortest",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
                   "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)])
        code, err = run_ff(cmd)
        result = {"output": str(out), "backend": "chromakey", "key": key, "size": f"{W}x{H}",
                  "background": args.bg_color or (str(args.bg_image) if args.bg_image else "white"),
                  "error": None if code == 0 else err[:400]}
        if args.compare and code == 0:
            result["compare"] = export_compare_frames(ff, src, out, Path(args.compare_dir or out.parent),
                                                      Path(src).stem + "-matte", args.json)
        emit(result, args.json)
        return 0 if code == 0 else 2

    # ---------- AI 路径（RVM，任意背景）----------
    try:
        import numpy as np
        import onnxruntime as ort
    except Exception:
        warn_tier("video-matte", "python -m pip install onnxruntime numpy")
        return 3

    model_path = ensure_rvm_model(args.model)
    providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
    if args.gpu and "CUDAExecutionProvider" not in providers:
        print("提示：未检测到 CUDA provider，回退 CPU（装 onnxruntime-gpu 可加速）", file=sys.stderr)
    sess = ort.InferenceSession(str(model_path), providers=providers)
    in_names = [i.name for i in sess.get_inputs()]
    out_names = [o.name for o in sess.get_outputs()]

    bg_img = Image.open(args.bg_image).convert("RGB").resize((W, H), Image.LANCZOS) if args.bg_image else None
    bg_rgb = np.array(parse_color(args.bg_color)[:3], dtype=np.float32) if args.bg_color else None
    if args.mode == "composite" and bg_rgb is None and bg_img is None:
        bg_rgb = np.array([255, 255, 255], dtype=np.float32)

    dec_cmd = [ff, "-hide_banner", "-loglevel", "error", "-i", src]
    if limit:
        dec_cmd += ["-t", f"{limit:.3f}"]
    dec_cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    dec = subprocess.Popen(dec_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    frame_out_dir = Path(args.frames_dir or (out.parent / f"{out.stem}-frames"))
    enc = None
    enc_err = b""
    if args.mode == "composite":
        enc_cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{fps:.3f}", "-i", "-"]
        if limit:
            enc_cmd += ["-t", f"{limit:.3f}"]
        enc_cmd += ["-i", src, "-map", "0:v", "-map", "1:a?", "-shortest",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
                    "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)]
        enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        frame_out_dir.mkdir(parents=True, exist_ok=True)

    rec = [np.zeros([1, 1, 1, 1], dtype=np.float32) for _ in range(4)]
    ratio = np.array([args.downsample_ratio], dtype=np.float32)
    fcount, t0, prev_alpha = 0, time.time(), None
    frame_size = W * H * 3
    try:
        while True:
            buf = dec.stdout.read(frame_size)
            if len(buf) < frame_size:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 3).astype(np.float32) / 255.0
            feeds = {}
            for nm in in_names:
                low = nm.lower()
                if low == "src":
                    feeds[nm] = frame.transpose(2, 0, 1)[None, :, :, :]
                elif low == "downsample_ratio":
                    feeds[nm] = ratio
                elif low.startswith("r") and low.endswith("i"):
                    idx = int(low[1]) - 1
                    if 0 <= idx < 4:
                        feeds[nm] = rec[idx]
            outs = sess.run(None, feeds)
            by_name = dict(zip(out_names, outs))
            pha = by_name.get("pha", outs[min(1, len(outs) - 1)])[0, 0]
            fgr = by_name.get("fgr", outs[0])[0].transpose(1, 2, 0)
            for i in range(4):
                if f"r{i+1}o" in by_name:
                    rec[i] = by_name[f"r{i+1}o"]
            if args.alpha_smooth and prev_alpha is not None:
                a = args.alpha_smooth
                pha = a * prev_alpha + (1 - a) * pha
            prev_alpha = pha
            pha3 = pha[:, :, None]

            if args.mode == "composite":
                bg = (np.asarray(bg_img, dtype=np.float32) / 255.0) if bg_img is not None \
                    else np.broadcast_to(bg_rgb / 255.0, (H, W, 3))
                com = fgr * pha3 + bg * (1 - pha3)
                enc.stdin.write((np.clip(com, 0, 1) * 255).astype(np.uint8).tobytes())
            elif args.mode == "mask":
                Image.fromarray((np.clip(pha, 0, 1) * 255).astype(np.uint8), "L") \
                    .save(frame_out_dir / f"mask-{fcount:05d}.png")
            else:  # alpha：前景 + 透明通道
                rgba = np.concatenate([(np.clip(fgr, 0, 1) * 255).astype(np.uint8),
                                       (np.clip(pha, 0, 1) * 255).astype(np.uint8)[:, :, None]], axis=2)
                Image.fromarray(rgba, "RGBA").save(frame_out_dir / f"alpha-{fcount:05d}.png")
            fcount += 1
            if fcount % 30 == 0:
                el = time.time() - t0
                print(f"\r[matte] {fcount} 帧  {fcount/max(el,1e-6):.1f} fps", end="", file=sys.stderr, flush=True)
    finally:
        dec.stdout.close()
        dec.wait()
        if enc is not None:
            enc.stdin.close()
            enc_err = enc.stderr.read()
            enc.wait()
    elapsed = max(time.time() - t0, 1e-6)
    print("", file=sys.stderr, flush=True)

    final_out = out
    if args.mode == "alpha":
        final_out = out.with_suffix(".webm")
        run_ff([ff, "-hide_banner", "-loglevel", "error", "-y", "-framerate", f"{fps:.3f}",
                "-i", str(frame_out_dir / "alpha-%05d.png"), "-c:v", "libvpx-vp9",
                "-pix_fmt", "yuva420p", "-crf", "30", "-b:v", "0", "-auto-alt-ref", "0", str(final_out)])
    elif args.mode == "mask":
        run_ff([ff, "-hide_banner", "-loglevel", "error", "-y", "-framerate", f"{fps:.3f}",
                "-i", str(frame_out_dir / "mask-%05d.png"), "-c:v", "libx264",
                "-preset", "veryfast", "-crf", str(args.crf), "-pix_fmt", "gray", str(final_out)])

    result = {
        "output": str(final_out),
        "backend": f"rvm:{args.model}",
        "providers": providers,
        "size": f"{W}x{H}", "fps": round(fps, 2), "frames": fcount,
        "seconds": round(elapsed, 1),
        "matting_fps": round(fcount / elapsed, 2),
        "mode": args.mode,
        "background": args.bg_color or (str(args.bg_image) if args.bg_image else None),
        "alpha_smooth": args.alpha_smooth,
        "frames_dir": str(frame_out_dir) if args.mode in ("alpha", "mask") else None,
        "encode_error": (enc_err.decode("utf-8", "replace")[:300] if enc_err else None),
    }
    if args.compare and fcount:
        result["compare"] = export_compare_frames(ff, src, final_out, Path(args.compare_dir or out.parent),
                                                  Path(src).stem + "-matte", args.json)
    emit(result, args.json)
    return 0 if fcount else 2


def export_compare_frames(ff: str, before, after, out_dir: Path, stem: str, as_json: bool) -> dict:
    """导出前后对比帧 + 接触表（本模型路线看不到画面，交付前必须由人过目）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs = []
    for label, path in (("before", before), ("after", after)):
        f = out_dir / f"{stem}-{label}.jpg"
        run_ff([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", "1", "-i", str(path),
                "-frames:v", "1", "-q:v", "2", str(f)])
        if f.exists():
            pairs.append(str(f))
    sheet = out_dir / f"{stem}-compare.jpg"
    code, _out, err = _run_cli(["sheet", *pairs, "--out", str(sheet), "--cols", "2", "--labels"])
    return {"frames": pairs, "sheet": str(sheet) if sheet.exists() else None,
            "error": None if code == 0 else err[:200]}


# ---------------------------- 动效文字（ASS） ----------------------------

# 九宫格 -> ASS \an（数字键盘布局）
ASS_ANCHOR = {"tl": 7, "tc": 8, "tr": 9, "ml": 4, "mc": 5, "mr": 6, "bl": 1, "bc": 2, "br": 3}

TEXT_PRESETS = (
    "fade",          # 淡入淡出
    "slide-up",      # 自下而上滑入
    "slide-down",    # 自上而下滑入
    "slide-left",    # 自右向左滑入
    "slide-right",   # 自左向右滑入
    "typewriter",    # 逐字打出
    "pop",           # 缩放弹出
    "bounce",        # 弹跳落定
    "karaoke",       # 逐词高亮（按空格/字符切词）
    "lower-third",   # 下三分之一条 + 滑入
)


def ass_color(value: str) -> str:
    """#RRGGBB / white … -> ASS &HAABBGGRR（alpha 取反）。"""
    r, g, b, a = parse_color(value)
    return f"&H{255 - a:02X}{b:02X}{g:02X}{r:02X}"


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _grid_pos(position: str, W: int, H: int, margin: int, bottom_margin: int) -> tuple[int, int]:
    fx = {"l": 0.0, "c": 0.5, "r": 1.0}[(position[1] if len(position) > 1 else "c")]
    fy = {"t": 0.0, "m": 0.5, "b": 1.0}[(position[0] if position else "c")]
    x = int(margin + fx * (W - 2 * margin))
    y = int(margin + fy * ((H - bottom_margin) - margin)) if fy < 1.0 else int(H - bottom_margin)
    return x, y


def build_text_block(block: dict, W: int, H: int, defaults: dict) -> str:
    """把一条文案块编译成 ASS Dialogue 行（含动效标签）。"""
    text = str(block.get("text", "")).strip()
    if not text:
        return ""
    start = float(block.get("start", 0.0))
    end = float(block.get("end", start + 3.0))
    if end <= start:
        end = start + 3.0
    preset = block.get("preset", defaults["preset"])
    position = block.get("position", defaults["position"])
    size_ratio = float(block.get("size", defaults["size"]))
    style = block.get("style", defaults.get("style", "Default"))
    color = ass_color(block.get("color", defaults["color"]))
    dur_ms = int((end - start) * 1000)

    an = ASS_ANCHOR.get(position, 2)
    x, y = _grid_pos(position, W, H, int(block.get("margin", defaults["margin"])),
                     int(block.get("bottom_margin", defaults["bottom_margin"])))

    tags = [f"\\an{an}", f"\\pos({x},{y})", f"\\fs{max(12, int(H * size_ratio))}"]
    body = text

    if preset == "fade":
        tags.append("\\fad(400,400)")
    elif preset.startswith("slide-"):
        dist = int(H * 0.12)
        frm = {"slide-up": (x, y + dist), "slide-down": (x, y - dist),
               "slide-left": (x + dist * 2, y), "slide-right": (x - dist * 2, y)}[preset]
        tags.append(f"\\move({frm[0]},{frm[1]},{x},{y},0,500)")
        tags.append("\\fad(300,300)")
    elif preset == "pop":
        tags.append("\\fscx60\\fscy60")
        tags.append("\\t(0,260,\\fscx104\\fscy104)")
        tags.append("\\t(260,400,\\fscx100\\fscy100)")
    elif preset == "bounce":
        tags.append(f"\\move({x},{max(0, y - int(H * 0.10))},{x},{y},0,420)")
        tags.append("\\t(420,520,\\fscx106\\fscy94)")
        tags.append("\\t(520,640,\\fscx100\\fscy100)")
    elif preset == "typewriter":
        step = max(30, int(dur_ms * 0.55 / max(len(text), 1)))
        out = []
        for i, ch in enumerate(text):
            t0 = i * step
            out.append(f"{{\\alpha&HFF&\\t({t0},{t0 + 40},\\alpha&H00&)}}{ch}")
        body = "".join(out)
    elif preset == "karaoke":
        words = [w for w in text.split(" ") if w]
        if len(words) == 1:  # 中文按字切
            words = list(text)
            joiner = ""
        else:
            joiner = " "
        per = max(20, int(dur_ms * 0.8 / max(len(words), 1)))
        body = joiner.join(f"{{\\k{per // 10}}}{w}" for w in words)
    elif preset == "lower-third":
        tags.append(f"\\move({max(0, x - int(W * 0.15))},{y},{x},{y},0,420)")
        tags.append("\\fad(300,300)")
        tags.append("\\bord0\\shad0")

    return (f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,"
            f"{{{''.join(tags)}}}{body}")


def build_ass(blocks: list[dict], W: int, H: int, defaults: dict) -> str:
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{defaults['font']},{max(12, int(H * defaults['size']))},{ass_color(defaults['color'])},{ass_color(defaults['highlight'])},{ass_color(defaults['stroke'])},{ass_color(defaults['box']) if defaults.get('box_style') else '&H80000000'},0,0,0,0,100,100,0,0,{1 if defaults.get('box_style') else 1},{defaults['outline']},{defaults['shadow']},2,40,40,40,1
Style: Boxed,{defaults['font']},{max(12, int(H * defaults['size']))},{ass_color(defaults['color'])},{ass_color(defaults['highlight'])},{ass_color(defaults['stroke'])},{ass_color(defaults['box'])},0,0,0,0,100,100,0,0,3,{defaults['outline']},{defaults['shadow']},2,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [l for l in (build_text_block(b, W, H, defaults) for b in blocks) if l]
    return head + "\n".join(lines) + "\n"


def cmd_video_text_anim(args) -> int:
    """动效文字：生成 ASS（淡入/滑入/打字机/卡拉OK/弹出…）并可一键烧入视频。"""
    ff = find_ffmpeg()
    blocks: list[dict] = []
    W = args.width or 1080
    H = args.height or 1920

    if args.spec:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        if isinstance(spec, dict):
            blocks = spec.get("blocks", [])
            W = int(spec.get("width", W))
            H = int(spec.get("height", H))
        else:
            blocks = spec

    if args.input:
        if not ff:
            warn_tier("video", "pip install imageio-ffmpeg")
            return 3
        data = ffprobe_json(ff, args.input)
        v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        W, H = int(v.get("width") or W), int(v.get("height") or H)

    if args.text:
        blocks.append({
            "text": args.text.replace("\\n", "\n"),
            "start": float(parse_time(args.start) or 0.0),
            "end": float(parse_time(args.end) or ((parse_time(args.start) or 0.0) + (parse_time(args.duration) or 3.0))),
            "preset": args.preset,
            "position": args.position,
            "size": args.size_ratio,
            "color": args.color,
        })
    if not blocks:
        print("需要 --text 或 --spec 提供文案", file=sys.stderr)
        return 2

    defaults = {
        "font": args.font_name or ("Microsoft YaHei" if os.name == "nt" else "Noto Sans CJK SC"),
        "size": args.size_ratio,
        "color": args.color,
        "highlight": args.highlight,
        "stroke": args.stroke,
        "box": args.box or "#00000099",
        "box_style": bool(args.box),
        "style": "Boxed" if args.box else "Default",
        "outline": args.outline,
        "shadow": args.shadow,
        "preset": args.preset,
        "position": args.position,
        "margin": int(H * 0.06),
        "bottom_margin": int(H * (0.20 if H > W else 0.12)),
    }

    ass_path = Path(args.ass_out or (Path(args.input).with_suffix(".anim.ass") if args.input else "titles.anim.ass"))
    ass_path.write_text(build_ass(blocks, W, H, defaults), encoding="utf-8")
    result = {"ass": str(ass_path), "canvas": f"{W}x{H}", "blocks": len(blocks),
              "presets": sorted({b.get("preset", defaults["preset"]) for b in blocks})}

    if args.input and not args.ass_only:
        out = Path(args.out or Path(args.input).with_name(Path(args.input).stem + "-titles.mp4"))
        sub_escaped = str(ass_path).replace("\\", "/").replace(":", r"\:")
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", args.input,
               "-vf", f"ass='{sub_escaped}'", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", str(args.crf), "-pix_fmt", "yuv420p", "-c:a", "copy",
               "-movflags", "+faststart", str(out)]
        code, err = run_ff(cmd)
        result.update({"output": str(out), "burn_error": None if code == 0 else err[:400]})
        if args.compare and code == 0:
            result["compare"] = export_compare_frames(ff, args.input, out, Path(args.compare_dir or out.parent),
                                                      Path(args.input).stem + "-titles", args.json)
    emit(result, args.json)
    return 0


# ---------------------------- 光效与调色预设 ----------------------------

# 每个预设是一段 filter_complex 片段：{inp} 为输入标签，{out} 为输出标签
FX_PRESETS = {
    "glow":        "{inp}split=2[ga][gb];[ga]gblur=sigma=20[gg];[gg][gb]blend=all_mode=screen:all_opacity=0.55{out}",
    "bloom":       "{inp}split=2[ba][bb];[ba]curves=all='0/0 0.55/0.78 1/1',gblur=sigma=28[bg];[bg][bb]blend=all_mode=screen:all_opacity=0.6{out}",
    "soft-focus":  "{inp}split=2[sa][sb];[sa]gblur=sigma=12[sg];[sg][sb]blend=all_mode=screen:all_opacity=0.25{out}",
    "leak":        "{inp}[leakin]overlay=0:0:shortest=1{out}",
    "trail":       "{inp}tmix=frames=6:weights='1 1 2 3 5 8'{out}",
    "grain":       "{inp}noise=alls=9:allf=t{out}",
    "vignette":    "{inp}vignette=PI/5{out}",
    "sharpen":     "{inp}unsharp=5:5:1.0:5:5:0.0{out}",
    "warm":        "{inp}colorbalance=rs=0.06:gs=0.02:bs=-0.06,eq=saturation=1.06{out}",
    "cool":        "{inp}colorbalance=rs=-0.06:gs=0.0:bs=0.08,eq=saturation=0.98{out}",
    "teal-orange": "{inp}colorbalance=rs=0.12:gs=-0.02:bs=-0.10,colorbalance=rh=-0.06:bh=0.10,"
                   "eq=contrast=1.06:saturation=1.08{out}",
    "film":        "{inp}curves=all='0/0.02 0.5/0.5 1/0.98',noise=alls=6:allf=t,vignette=PI/4.5{out}",
    "punch":       "{inp}eq=contrast=1.12:saturation=1.12:brightness=0.02,unsharp=5:5:0.8{out}",
}

FX_NOTES = {
    "glow": "柔光晕：模糊层 screen 叠加",
    "bloom": "高光泛光：先提亮高光再模糊叠加",
    "soft-focus": "轻柔焦：低透明度叠加（人像/产品）",
    "leak": "光泄漏：叠加程序化渐变光斑（可调 --leak-opacity）",
    "trail": "运动拖影：6 帧加权混合",
    "grain": "胶片颗粒",
    "vignette": "暗角",
    "sharpen": "锐化",
    "warm": "暖调",
    "cool": "冷调",
    "teal-orange": "电影感青橙",
    "film": "胶片感：轻微压缩+颗粒+暗角",
    "punch": "增强对比与饱和（电商图更抓眼）",
}


def cmd_video_fx(args) -> int:
    """光效与调色：辉光/泛光/光泄漏/拖影/颗粒/暗角/冷暖/青橙/LUT。"""
    if args.list and not args.preset:
        emit({"presets": [{"name": k, "note": FX_NOTES.get(k, "")} for k in FX_PRESETS]}, args.json)
        return 0
    ff = find_ffmpeg()
    if not ff:
        warn_tier("video", "pip install imageio-ffmpeg")
        return 3

    names: list[str] = []
    for p in (args.preset or []):
        names += [x.strip() for x in str(p).split(",") if x.strip()]
    unknown = [n for n in names if n not in FX_PRESETS]
    if unknown:
        print(f"UNKNOWN_PRESET: {', '.join(unknown)}；可用：{', '.join(FX_PRESETS)}", file=sys.stderr)
        return 2
    if names and not args.input:
        print("需要 input（或在仅列清单时使用 --list）", file=sys.stderr)
        return 2
    if not names and not args.lut:
        print("需要 --preset（可多个）或 --lut", file=sys.stderr)
        return 2

    src = args.input
    data = ffprobe_json(ff, src)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    W, H = int(v.get("width") or 1080), int(v.get("height") or 1920)
    limit = parse_time(args.limit) if args.limit else None
    out = Path(args.out or Path(src).with_name(Path(src).stem + "-fx.mp4"))

    stages: list[str] = []
    uses_leak = "leak" in names
    if uses_leak:
        # 光泄漏：用 lavfi gradients 生成慢速流动的暖色光（比逐像素 geq 快两个数量级），
        # 透明度用 colorchannelmixer 控制，overlay 加 shortest 防止无限源拖死编码。
        op = max(0.0, min(1.0, args.leak_opacity))
        stages.append(f"[1:v]format=rgba,colorchannelmixer=aa={op:.2f}[leakin]")
    cur = "[0:v]"
    for i, nm in enumerate(names):
        outl = f"[fx{i}]"
        stages.append(FX_PRESETS[nm].format(inp=cur, out=outl))
        cur = outl
    if args.lut:
        lut_path = str(Path(args.lut).resolve()).replace("\\", "/").replace(":", r"\:")
        outl = f"[fx{len(names)}]"
        stages.append(f"{cur}lut3d=file='{lut_path}'{outl}")
        cur = outl
    stages.append(f"{cur}format=yuv420p[vout]")

    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y"]
    if limit:
        cmd += ["-t", f"{limit:.3f}"]
    cmd += ["-i", src]
    if uses_leak:
        dur = limit or float(data.get("format", {}).get("duration", 0) or 5.0)
        cmd += ["-f", "lavfi", "-i",
                f"gradients=s={W}x{H}:c0=0x2a1200:c1=0xff8a3c:c2=0xff3cac:"
                f"x0=0:y0=0:x1={W}:y1={H}:d={max(1.0, dur):.3f}:speed=0.012:n=3"]
    cmd += ["-filter_complex", ";".join(stages), "-map", "[vout]", "-map", "0:a?"]
    if limit:
        cmd += ["-t", f"{limit:.3f}"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)]
    code, err = run_ff(cmd)
    result = {"output": str(out), "presets": names, "lut": args.lut,
              "size": f"{W}x{H}", "error": None if code == 0 else err[:400]}
    if args.compare and code == 0:
        result["compare"] = export_compare_frames(ff, src, out, Path(args.compare_dir or out.parent),
                                                  Path(src).stem + "-fx", args.json)
    emit(result, args.json)
    return 0 if code == 0 else 2


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

    # 紧裁：大留白图 → 主体占画幅应显著提升（平台主图要求商品占画幅 ≥85%）
    sp = work / "sparse.png"
    sparse = Image.new("RGB", (800, 800), (255, 255, 255))
    ImageDraw.Draw(sparse).rectangle((300, 340, 500, 460), fill=(31, 110, 67))
    sparse.save(sp)
    tdir = work / "tight"
    code, _, err = call(["export", str(sp), "--preset", "square", "--tight", "0.05", "--out-dir", str(tdir)])
    tight_file = next(iter(sorted(tdir.glob("*.png"))), None) if tdir.exists() else None
    fill_before = (200 * 120) / (800 * 800)
    fill_after = 0.0
    if tight_file:
        try:
            import numpy as np
            a = np.asarray(Image.open(tight_file).convert("RGB"), dtype=np.int16)
            nz = (a < 245).any(axis=2)
            ys, xs = np.where(nz)
            fill_after = ((xs.max() - xs.min()) * (ys.max() - ys.min())) / (a.shape[0] * a.shape[1])
        except Exception:
            fill_after = 0.0
    check("T0 export --tight (主体紧裁)", code == 0 and fill_after > fill_before * 3,
          f"主体占画幅 {fill_before:.3f} → {fill_after:.3f}")

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

    # ---------- T3 视频特效（抠像换背景 / 动效文字 / 转场 / 光效）----------
    vfx_in = clip1
    if ff and vfx_in.exists():
        m1 = work / "fx-matte.mp4"
        code, _, err = call(["video-matte", str(vfx_in), "--limit", "1", "--bg-color", "white",
                             "--out", str(m1)])
        white_ok = False
        if m1.exists() and code == 0:
            try:
                import numpy as np
                f = work / "fx-matte-frame.jpg"
                run_ff([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", "0.5", "-i", str(m1),
                        "-frames:v", "1", "-q:v", "2", str(f)])
                if f.exists():
                    im = np.asarray(Image.open(f).convert("RGB"), dtype=np.int16)
                    h, w, _ = im.shape
                    corners = np.concatenate([im[2:6, 2:6].reshape(-1, 3), im[2:6, w-6:w-2].reshape(-1, 3),
                                              im[h-6:h-2, 2:6].reshape(-1, 3), im[h-6:h-2, w-6:w-2].reshape(-1, 3)])
                    white_ok = bool(corners.min() > 225)
            except Exception:
                white_ok = False
        check("T3 video-matte (AI 抠像→白底)", code == 0 and white_ok,
              "四角像素已被替换为白底" if white_ok else err[:200])

        mc = work / "fx-chromakey.mp4"
        code, _, err = call(["video-matte", str(vfx_in), "--backend", "chromakey", "--key-color",
                             "0x00FF00", "--bg-color", "white", "--limit", "1", "--out", str(mc)])
        check("T3 video-matte (色键路径)", code == 0 and mc.exists(), err[:200])

        ta = work / "fx-titles.mp4"
        ass = work / "fx-titles.ass"
        code, _, err = call(["video-text-anim", str(vfx_in), "--text", "自检标题\nSelf Test Title",
                             "--preset", "slide-up", "--start", "0.2", "--end", "1.2",
                             "--ass-out", str(ass), "--out", str(ta)])
        ass_ok = ass.exists() and "Dialogue:" in ass.read_text(encoding="utf-8", errors="replace")
        check("T3 video-text-anim (ASS+烧入)", code == 0 and ass_ok and ta.exists(), err[:200])

        code, out, err = call(["video-join", "--list-transitions"])
        n_x = len(json.loads(out).get("xfade", [])) if code == 0 and out.strip().startswith("{") else 0
        check("T3 video-transition 清单", n_x >= 40, f"可用 xfade 转场 {n_x} 种")

        j1, j2, jout = work / "fx-j1.mp4", work / "fx-j2.mp4", work / "fx-glitch.mp4"
        call(["video-cut", str(vfx_in), "--start", "0.5", "--duration", "1.5", "--accurate", "--out", str(j1)])
        call(["video-cut", str(vfx_in), "--start", "2.0", "--duration", "1.5", "--accurate", "--out", str(j2)])
        code, _, err = call(["video-join", str(j1), str(j2), "--transition", "glitch",
                             "--transition-duration", "0.5", "--out", str(jout)])
        p = _probe(jout)
        check("T3 video-transition (风格化 glitch)", code == 0 and abs(p.get("duration", 0) - 2.5) < 0.4,
              f"dur={p.get('duration')} {err[:150]}")

        fxo = work / "fx-look.mp4"
        code, _, err = call(["video-fx", str(vfx_in), "--preset", "teal-orange,glow", "--limit", "1",
                             "--compare", "--out", str(fxo)])
        sheet = work / "clip-a-fx-compare.jpg"
        check("T3 video-fx (调色+辉光+对比帧)", code == 0 and fxo.exists() and sheet.exists(), err[:200])

        fxl = work / "fx-leak.mp4"
        code, _, err = call(["video-fx", str(vfx_in), "--preset", "leak", "--limit", "1", "--out", str(fxl)])
        check("T3 video-fx (光泄漏)", code == 0 and fxl.exists(), err[:200])

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
    e.add_argument("--tight", type=float, nargs="?", const=0.06, default=0.0,
                   help="按主体自动紧裁后再规格化（可带边距比例，默认 0.06）；"
                        "平台主图要求商品占画幅 ≥85%% 时用它")
    e.add_argument("--tight-tolerance", type=int, default=14, help="判定主体的背景色差阈值")
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
    vj.add_argument("inputs", nargs="*")
    vj.add_argument("--out")
    vj.add_argument("--transition", default="none",
                    help="none|fade|wipeleft|slideup|circleopen|dissolve|… (46 种 xfade) "
                         "或风格化预置 flash|glitch|whip-pan|soft-zoom|film-burn")
    vj.add_argument("--list-transitions", action="store_true", help="列出全部可用转场与风格化预置")
    vj.add_argument("--transition-duration", type=float, default=0.5)
    vj.add_argument("--fps", type=int, default=30, help="转场拼接时的统一帧率")
    vj.add_argument("--reencode", action="store_true", help="无转场时也重编码（参数不一致时用）")
    vj.set_defaults(func=cmd_video_join)

    fx = sub.add_parser("video-fx", help="光效与调色预设（辉光/泛光/光泄漏/拖影/颗粒/暗角/LUT）")
    fx.add_argument("input", nargs="?", help="输入视频；配合 --list 时可省略")
    fx.add_argument("--preset", action="append", required=False,
                    help="可重复或逗号分隔：" + ",".join(FX_PRESETS))
    fx.add_argument("--list", action="store_true", help="列出全部光效/调色预设说明")
    fx.add_argument("--lut", help="3D LUT 文件（.cube/.3dl）")
    fx.add_argument("--leak-opacity", type=float, default=0.35, help="光泄漏叠加不透明度")
    fx.add_argument("--limit", help="只处理前 N 秒（试跑）")
    fx.add_argument("--crf", type=int, default=20)
    fx.add_argument("--compare", action="store_true", help="导出前后对比帧 + 接触表")
    fx.add_argument("--compare-dir")
    fx.add_argument("--out")
    fx.set_defaults(func=cmd_video_fx)

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

    vm = sub.add_parser("video-matte", help="视频抠像换背景：AI（RVM，任意背景）或色键（绿幕）")
    vm.add_argument("input")
    vm.add_argument("--backend", default="auto", choices=["auto", "rvm", "chromakey"])
    vm.add_argument("--model", default="mobilenetv3", choices=sorted(RVM_MODELS))
    vm.add_argument("--mode", default="composite", choices=["composite", "alpha", "mask"],
                    help="composite=换背景出成片 / alpha=输出带透明通道的 webm / mask=输出黑白遮罩")
    vm.add_argument("--bg-color", help="背景底色，如 white / #1F6E43")
    vm.add_argument("--bg-image", help="背景图（自动缩放到视频尺寸）")
    vm.add_argument("--key-color", help="色键颜色，如 0x00FF00（给了就走色键路径）")
    vm.add_argument("--key-similarity", type=float, default=0.3)
    vm.add_argument("--key-blend", type=float, default=0.1)
    vm.add_argument("--despill", help="去溢色类型：green / blue")
    vm.add_argument("--downsample-ratio", type=float, default=0.375, help="RVM 推理分辨率比例（越小越快）")
    vm.add_argument("--alpha-smooth", type=float, default=0.25, help="时间平滑系数，抑制边缘闪烁（0=关）")
    vm.add_argument("--limit", help="只处理前 N 秒（快速试跑）")
    vm.add_argument("--crf", type=int, default=20)
    vm.add_argument("--gpu", action="store_true", help="要求 CUDA provider（缺失会提示回退）")
    vm.add_argument("--compare", action="store_true", help="导出前后对比帧 + 接触表")
    vm.add_argument("--compare-dir")
    vm.add_argument("--frames-dir")
    vm.add_argument("--out")
    vm.set_defaults(func=cmd_video_matte)

    ta = sub.add_parser("video-text-anim", help="动效文字：ASS 生成（淡入/滑入/打字机/卡拉OK/弹出）并可烧入")
    ta.add_argument("input", nargs="?", help="要烧入的视频；省略则只生成 ASS")
    ta.add_argument("--text", help="单条文案（\\n 换行）")
    ta.add_argument("--spec", help="多条文案 JSON：[{text,start,end,preset,position,size,color}]")
    ta.add_argument("--preset", default="fade", choices=list(TEXT_PRESETS))
    ta.add_argument("--position", default="bc", choices=sorted(ASS_ANCHOR))
    ta.add_argument("--start")
    ta.add_argument("--end")
    ta.add_argument("--duration")
    ta.add_argument("--size-ratio", type=float, default=0.055, help="字号占画面高度比例")
    ta.add_argument("--color", default="white")
    ta.add_argument("--highlight", default="#FFD54A", help="卡拉OK 高亮色")
    ta.add_argument("--stroke", default="#000000")
    ta.add_argument("--outline", type=float, default=2.0)
    ta.add_argument("--shadow", type=float, default=0.0)
    ta.add_argument("--box", help="底块颜色（如 #00000099），设置后文字带底色块")
    ta.add_argument("--font-name")
    ta.add_argument("--width", type=int, help="无输入视频时指定画布宽")
    ta.add_argument("--height", type=int, help="无输入视频时指定画布高")
    ta.add_argument("--ass-out", help="指定 ASS 输出路径")
    ta.add_argument("--ass-only", action="store_true", help="只产出 ASS，不烧入")
    ta.add_argument("--crf", type=int, default=20)
    ta.add_argument("--compare", action="store_true")
    ta.add_argument("--compare-dir")
    ta.add_argument("--out")
    ta.set_defaults(func=cmd_video_text_anim)

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
