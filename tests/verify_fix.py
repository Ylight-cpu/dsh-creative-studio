"""0.2.1 修复验收：抠像主体存在性 + 光效全局偏色。

两次真实事故（用户实拍供暖炉素材复现，已写入 CHANGELOG）：
  A 版：RVM 人像模型抠产品 → 主体被整个抠没，成片全白只剩字幕（非白占比 0.0000–0.0134）。
  B/C 版：blend=screen 跑在 yuv420p 上 + 品红渐变光 → 全片泛粉（R-均值差 +56…+67，源片 +13）。

本脚本把这两项变成可复现的客观闸门，任何一次改动后都能一条命令复核：
    python tests/verify_fix.py --matte <成片.mp4> --fx <成片.mp4> [--fx-ref <源片.mp4>]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
import cs  # noqa: E402  （复用工具链自己的 ffmpeg 定位与探测）

FF = cs.find_ffmpeg()
TMP = Path(__file__).resolve().parent / "out" / "verify"


def frame(video, t: float, tag: str) -> np.ndarray | None:
    TMP.mkdir(parents=True, exist_ok=True)
    f = TMP / f"{tag}_{t:.2f}.png"
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                    "-ss", f"{t:.3f}", "-frames:v", "1", str(f)], capture_output=True)
    if not f.exists():
        return None
    return np.asarray(Image.open(f).convert("RGB"), dtype=np.float32)


def subject_share(a: np.ndarray, thresh: int = 245) -> float:
    """非白像素占比 = 主体是否还在画面里（白底成片专用）。"""
    return float((a < thresh).any(axis=2).mean())


def channel_cast(a: np.ndarray) -> float:
    """R - (G+B)/2，正得越多越偏红/粉。避开上下字幕带，只看画面主体区。"""
    h, w, _ = a.shape
    core = a[int(h * 0.18):int(h * 0.82), int(w * 0.12):int(w * 0.88)]
    m = core.reshape(-1, 3).mean(axis=0)
    return float(m[0] - (m[1] + m[2]) / 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matte", help="抠像换白底的成片")
    ap.add_argument("--matte-ref", help="对应的原始素材（可选，做对照）")
    ap.add_argument("--fx", help="加了光效/调色的成片")
    ap.add_argument("--fx-ref", help="未加光效的对照片（强烈建议给）")
    ap.add_argument("--times", default="0.4,1.2,2.0,2.8",
                    help="抽样时间点（秒，逗号分隔）")
    ap.add_argument("--min-subject", type=float, default=0.02,
                    help="主体存在性下限：非白占比低于此判 FAIL")
    ap.add_argument("--max-cast", type=float, default=25.0,
                    help="偏色上限：|R-(G+B)/2| 超过此值判 FAIL")
    ap.add_argument("--max-cast-delta", type=float, default=15.0,
                    help="相对源片的偏色增量上限")
    args = ap.parse_args()

    if not FF:
        print("找不到 ffmpeg（先 pip install imageio-ffmpeg）")
        return 3
    times = [float(x) for x in args.times.split(",") if x.strip()]
    fails: list[str] = []

    if args.matte:
        print(f"=== 主体存在性（抠像成片 {Path(args.matte).name}）===")
        for t in times:
            a = frame(args.matte, t, "matte")
            if a is None:
                print(f"  t={t:.1f}s  读不到帧")
                fails.append(f"matte@{t}s 无帧")
                continue
            share = subject_share(a)
            ok = share >= args.min_subject
            if not ok:
                fails.append(f"matte@{t:.1f}s 主体占比 {share:.4f} < {args.min_subject}")
            print(f"  t={t:.1f}s  主体(非白)占比={share:.4f}  {'OK' if ok else 'FAIL ← 主体可能被抠没'}")
        if args.matte_ref:
            for t in times[:2]:
                a = frame(args.matte_ref, t, "mref")
                if a is not None:
                    print(f"  [对照] 源片 t={t:.1f}s 非白占比={subject_share(a):.4f}")

    if args.fx:
        print(f"\n=== 全局偏色（光效成片 {Path(args.fx).name}）===")
        refs = {}
        if args.fx_ref:
            for t in times:
                r = frame(args.fx_ref, t, "fxref")
                if r is not None:
                    refs[t] = channel_cast(r)
        for t in times:
            a = frame(args.fx, t, "fx")
            if a is None:
                print(f"  t={t:.1f}s  读不到帧")
                fails.append(f"fx@{t}s 无帧")
                continue
            c = channel_cast(a)
            r = refs.get(t)
            delta = None if r is None else c - r
            bad = abs(c) > args.max_cast or (delta is not None and abs(delta) > args.max_cast_delta)
            if bad:
                fails.append(f"fx@{t:.1f}s 偏色 {c:+.1f}" + (f"（源 {r:+.1f}，Δ{delta:+.1f}）" if delta is not None else ""))
            print(f"  t={t:.1f}s  R-均值差={c:+.1f}"
                  + (f"  源={r:+.1f}  Δ={delta:+.1f}" if r is not None else "")
                  + ("  OK" if not bad else "  FAIL ← 全片偏色"))

    print()
    if fails:
        print("结论：不通过")
        for f in fails:
            print("  - " + f)
        return 1
    print("结论：通过（这两项客观闸门没有发现问题；画面美观度仍需人眼确认）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
