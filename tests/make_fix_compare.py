"""生成「修复前 vs 修复后」对比图（三版同一时刻并排），供人眼一票确认。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "toolkit"))
import cs  # noqa: E402

FF = cs.find_ffmpeg()
PY = sys.executable
CS = HERE.parent / "toolkit" / "cs.py"
OLD = HERE / "out" / "stove" / "styles" / "deliver"
NEW = Path(r"F:\deepseek harness\供暖炉视频样片\修复版")
TMP = HERE / "out" / "cmp-fix"
TMP.mkdir(parents=True, exist_ok=True)

PAIRS = [
    ("A", OLD / "A-final-reel-9x16.mp4", NEW / "A-干净商务风-修复版-9x16.mp4"),
    ("B", OLD / "B-final-reel-9x16.mp4", NEW / "B-科技故障风-修复版-9x16.mp4"),
    ("C", OLD / "C-final-reel-9x16.mp4", NEW / "C-电影感-修复版-9x16.mp4"),
]
T = 2.0


def grab(video: Path, t: float, out: Path) -> bool:
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
                    "-ss", f"{t:.3f}", "-frames:v", "1", "-vf", "scale=440:-2", str(out)],
                   capture_output=True)
    return out.exists()


def main() -> int:
    frames: list[Path] = []
    for tag, old, new in PAIRS:
        for label, src in (("修复前", old), ("修复后", new)):
            if not src.exists():
                print(f"缺文件：{src}")
                continue
            f = TMP / f"{tag}-{label}_{T:.1f}s.jpg"
            if grab(src, T, f):
                frames.append(f)
    if not frames:
        print("没有可对比的帧")
        return 1
    out = NEW / "修复前后对比-同一时刻.jpg"
    subprocess.run([PY, str(CS), "sheet"] + [str(f) for f in frames]
                   + ["--labels", "--out", str(out)], capture_output=True, text=True, encoding="utf-8")
    print(f"{'已生成' if out.exists() else '生成失败'}：{out}")
    return 0 if out.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
