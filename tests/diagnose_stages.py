"""逐级定位：join → titled → final 每一步到底改了什么、改在哪里。

B/C 版的「底部幽灵人头」必须定位到具体是哪一级产生的，否则重建还会翻车。
输出：每一步在 6行×4列 网格上的差分强度 + 最强区块位置。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolkit"))
import cs  # noqa: E402

FF = cs.find_ffmpeg()
ROOT = Path(r"F:\deepseek harness\dsh-creative-studio\tests\out\stove")
OUT = ROOT / "diag2"
OUT.mkdir(parents=True, exist_ok=True)

STAGES = {
    "B": ["styles/B-join.mp4", "styles/B-titled.mp4", "styles/B-final.mp4",
          "styles/deliver/B-final-reel-9x16.mp4"],
    "C": ["styles/C-join.mp4", "styles/C-titled.mp4", "styles/C-final.mp4",
          "styles/deliver/C-final-reel-9x16.mp4"],
    "A": ["styles/A-join.mp4", "styles/A-titled.mp4", "styles/A-final.mp4",
          "styles/deliver/A-final-reel-9x16.mp4"],
}


def grab(video: Path, t: float) -> np.ndarray | None:
    f = OUT / f"g_{video.stem}_{t:.2f}.png"
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                    "-ss", f"{t:.3f}", "-frames:v", "1", str(f)], capture_output=True)
    if not f.exists():
        return None
    return np.asarray(Image.open(f).convert("RGB"), dtype=np.float32)


def report(a: np.ndarray, b: np.ndarray, label: str) -> None:
    if a.shape != b.shape:
        b = np.asarray(Image.fromarray(b.astype(np.uint8)).resize((a.shape[1], a.shape[0]),
                                                                 Image.BILINEAR), dtype=np.float32)
    d = np.abs(a - b).mean(axis=2)
    h, w = d.shape
    rows, cols = 6, 4
    cells = [[float(d[r*h//rows:(r+1)*h//rows, c*w//cols:(c+1)*w//cols].mean()) for c in range(cols)]
             for r in range(rows)]
    print(f"    {label}")
    for r, row in enumerate(cells):
        print("      " + "  ".join(f"{v:6.1f}" if v >= 0.5 else "     ." for v in row))
    flat = [(cells[r][c], r, c) for r in range(rows) for c in range(cols)]
    flat.sort(reverse=True)
    top = flat[0]
    where = ["上", "中上", "中", "中下", "下", "底部"][top[1]]
    print(f"      → 最大差异块 {top[0]:.1f} 位于第{top[1]+1}行/第{top[2]+1}列（画面{where}区），"
          f"全画面均值 {float(d.mean()):.1f}")


def main() -> int:
    for tag, files in STAGES.items():
        print(f"\n########## {tag} 版逐级差异 ##########")
        paths = [ROOT / f for f in files]
        for t in (1.0, 4.0):
            print(f"  --- t={t:.1f}s ---")
            for i in range(len(paths) - 1):
                a, b = grab(paths[i], t), grab(paths[i + 1], t)
                if a is None or b is None:
                    print(f"    {paths[i].name} → {paths[i+1].name}: 取帧失败")
                    continue
                report(a, b, f"{paths[i].name} → {paths[i+1].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
