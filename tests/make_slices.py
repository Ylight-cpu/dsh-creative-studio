# 生成"时间切片"审片图：转场过程 + 文字动效过程
# 单帧对比图无法体现转场/动画，必须按时间轴连抽多帧。
import subprocess
from pathlib import Path

FF = r"F:\deepseek harness\dsh-creative-studio\runtime\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
ROOT = Path(r"F:\deepseek harness\dsh-creative-studio\tests\out\stove\styles")
DELIVER = ROOT / "deliver"

# 转场窗口：shot1=3.0s，xfade offset = 3.0 - 转场时长 → A(0.4s) 从 2.60s 起，B/C(0.5s) 从 2.50s 起
TRANS = {
    "A": [2.35, 2.55, 2.70, 2.85, 3.10],
    "B": [2.25, 2.45, 2.60, 2.75, 3.05],
    "C": [2.25, 2.45, 2.60, 2.75, 3.05],
}
# 文字动效窗口：打字机 0.3-2.0 / 卡拉OK 2.2-3.8 / 上滑 4.0-5.3
TITLES = [0.50, 1.10, 1.80, 3.00, 4.30, 5.00]


def grab(video: Path, t: float, out: Path) -> bool:
    # -i 之后再 -ss = 精确解码定位（转场窗口只有 0.15 秒，必须精确）
    r = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(video), "-ss", f"{t:.3f}", "-frames:v", "1", "-q:v", "2", str(out)],
                       capture_output=True)
    return r.returncode == 0 and out.exists()


def main() -> int:
    for tag in ("A", "B", "C"):
        vids = sorted(DELIVER.glob(f"{tag}-final*.mp4"))
        if not vids:
            print(f"{tag}: 找不到成片")
            continue
        video = vids[0]
        dtrans = ROOT / tag / "trans"
        dtitles = ROOT / tag / "titles"
        dtrans.mkdir(parents=True, exist_ok=True)
        dtitles.mkdir(parents=True, exist_ok=True)
        nt = sum(1 for i, t in enumerate(TRANS[tag]) if grab(video, t, dtrans / f"{tag}-T{i+1}_{t:.2f}s.jpg"))
        na = sum(1 for i, t in enumerate(TITLES) if grab(video, t, dtitles / f"{tag}-A{i+1}_{t:.2f}s.jpg"))
        print(f"{tag}: 转场帧 {nt} 张 -> {dtrans}")
        print(f"{tag}: 文字帧 {na} 张 -> {dtitles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
