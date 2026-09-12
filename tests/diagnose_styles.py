# 诊断：A 版产品是否消失、B/C 版颜色是否整体偏移、转场效果是否越界
import subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image

FF = r"F:\deepseek harness\dsh-creative-studio\runtime\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
ROOT = Path(r"F:\deepseek harness\dsh-creative-studio\tests\out\stove")
DEL = ROOT / "styles" / "deliver"
SRC1 = ROOT / "shot1.mp4"
SRC2 = ROOT / "shot2.mp4"


def frames(video: Path, times, tmp: Path, tag: str):
    tmp.mkdir(parents=True, exist_ok=True)
    out = []
    for t in times:
        f = tmp / f"{tag}_{t:.2f}.png"
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                        "-ss", f"{t:.3f}", "-frames:v", "1", str(f)], capture_output=True)
        if f.exists():
            out.append((t, np.asarray(Image.open(f).convert("RGB"), dtype=np.float32)))
    return out


def stats(a: np.ndarray):
    """返回 非背景像素占比 / 平均 RGB"""
    h, w, _ = a.shape
    nonwhite = ((a < 240).any(axis=2)).mean()          # 相对白底
    nonblack = ((a > 16).any(axis=2)).mean()
    return nonwhite, nonblack, a.reshape(-1, 3).mean(axis=0)


def main():
    times = [0.5, 1.2, 2.0, 2.7, 3.2, 4.0, 4.8, 5.3]
    tmp = ROOT / "diag"
    print("=== 原始素材（参照）===")
    for name, p in (("shot1", SRC1), ("shot2", SRC2)):
        for t, a in frames(p, [0.5, 1.5, 2.5], tmp, f"src-{name}"):
            nw, nb, m = stats(a)
            print(f"  {name} t={t:.1f}s  非白占比={nw:.3f}  平均RGB=({m[0]:.0f},{m[1]:.0f},{m[2]:.0f})")

    print("\n=== A 版：产品是否还在（非白占比应显著 > 0）===")
    for t, a in frames(sorted(DEL.glob("A-final*.mp4"))[0], times, tmp, "A"):
        nw, nb, m = stats(a)
        print(f"  t={t:.1f}s  非白占比={nw:.4f}  平均RGB=({m[0]:.0f},{m[1]:.0f},{m[2]:.0f})")

    for tag in ("B", "C"):
        print(f"\n=== {tag} 版：颜色是否整体偏移（R 明显高于 G/B = 偏红/粉）===")
        for t, a in frames(sorted(DEL.glob(f"{tag}-final*.mp4"))[0], times, tmp, tag):
            h, w, _ = a.shape
            core = a[int(h*0.18):int(h*0.82), int(w*0.12):int(w*0.88)]   # 避开字幕区
            m = core.reshape(-1, 3).mean(axis=0)
            rg = m[0] - (m[1] + m[2]) / 2
            print(f"  t={t:.1f}s  平均RGB=({m[0]:.0f},{m[1]:.0f},{m[2]:.0f})  R-均值差={rg:+.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
