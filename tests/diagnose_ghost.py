"""定位 B/C 版「底部幽灵人头」的来源：把旧成片与源素材逐块对比。

做法：从旧成片取帧，从对应源素材取「同一内容的帧」，缩放到同一尺寸后做块状差分。
成片里多出来的东西（幽灵/叠影/残留帧）会在差分网格上表现为局部高亮。
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


def grab(video: Path, t: float, tag: str) -> np.ndarray:
    f = OUT / f"{tag}_{t:.2f}.png"
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                    "-ss", f"{t:.3f}", "-frames:v", "1", str(f)], capture_output=True)
    return np.asarray(Image.open(f).convert("RGB"), dtype=np.float32)


def grid(diff: np.ndarray, rows: int = 6, cols: int = 4) -> str:
    h, w = diff.shape
    lines = []
    for r in range(rows):
        cells = []
        for c in range(cols):
            blk = diff[r * h // rows:(r + 1) * h // rows, c * w // cols:(c + 1) * w // cols]
            v = float(blk.mean())
            cells.append(f"{v:5.1f}" if v >= 0.05 else "    .")
        lines.append("   ".join(cells))
    return "\n".join(lines)


def main() -> int:
    # 旧成片（B/C）与源片：join 结构是 shot1(0-3s) + 0.5s 转场 + shot2(2.5-5.5s)
    cases = [
        ("B", ROOT / "styles" / "deliver" / "B-final-reel-9x16.mp4",
         ROOT / "styles" / "B-join.mp4"),
        ("C", ROOT / "styles" / "deliver" / "C-final-reel-9x16.mp4",
         ROOT / "styles" / "C-join.mp4"),
    ]
    for tag, final, join in cases:
        print(f"\n########## {tag} 版 ##########")
        if not final.exists() or not join.exists():
            print(f"  缺文件：final={final.exists()} join={join.exists()}")
            continue
        # 先看 deliver 相对 join 的差异（deliver 只是缩放+文字，不应有结构性差异）
        for t in (1.0, 3.2, 4.8):
            a = grab(final, t, f"{tag}-final")
            b = grab(join, t, f"{tag}-join")
            if a.shape != b.shape:
                b = np.asarray(Image.fromarray(b.astype(np.uint8)).resize((a.shape[1], a.shape[0]),
                                                                         Image.BILINEAR), dtype=np.float32)
            d = np.abs(a - b).mean(axis=2)
            print(f"  [deliver vs join] t={t:.1f}s  全画面块差分（6行×4列）:")
            print("    " + grid(d).replace("\n", "\n    "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
