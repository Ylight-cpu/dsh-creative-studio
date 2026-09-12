"""证明「人物虚影」的成因：whip-pan 转场的 tmix 拖影会把真人复制成半透明残影。

做法：取一段确实有人的素材，剪两段，分别用 whip-pan（带 7 帧拖影）和 fade（对照）
拼接，然后逐帧量「人形信号」。若 whip-pan 版在转场后仍残留人形信号、而 fade 版没有，
就证明那不是站在那儿的人，而是前面那个人被拖影复制出来的虚影。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "toolkit"))
import cs  # noqa: E402
import detect_person as dp  # noqa: E402

FF = cs.find_ffmpeg()
PY = sys.executable
CS = HERE.parent / "toolkit" / "cs.py"
SRC = Path(r"F:\新建文件夹 (2)\供暖炉\视频\微信视频2026-07-20_144029_366.mp4")
WORK = HERE / "out" / "ghost-test"
WORK.mkdir(parents=True, exist_ok=True)


def call(args: list[str]) -> None:
    p = subprocess.run([PY, str(CS)] + args + ["--json"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("命令失败：", " ".join(args[:4]), p.stderr[:300])


def human_curve(video: Path, step: float = 0.1) -> list[tuple[float, float]]:
    """逐帧人形信号（用 RVM 当人体探测器）。"""
    import onnxruntime as ort
    sess = ort.InferenceSession(str(dp.MODEL), providers=["CPUExecutionProvider"])
    inn = [i.name for i in sess.get_inputs()]
    outn = [o.name for o in sess.get_outputs()]
    j = cs.ffprobe_json(FF, str(video))
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    W, H = int(v.get("width")), int(v.get("height"))
    sc = min(1.0, dp.MAXSIDE / max(W, H))
    sw, sh = int(W * sc) // 2 * 2, int(H * sc) // 2 * 2
    fps = 30.0
    every = max(1, int(round(step * fps)))
    dec = subprocess.Popen(
        [FF, "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-vf", f"select='not(mod(n\\,{every}))',scale={sw}:{sh}", "-vsync", "0",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    rec = [np.zeros([1, 1, 1, 1], dtype=np.float32) for _ in range(4)]
    ratio = np.array([dp.RATIO], dtype=np.float32)
    fsize = sw * sh * 3
    rows, i = [], 0
    try:
        while True:
            buf = dec.stdout.read(fsize)
            if len(buf) < fsize:
                break
            f = np.frombuffer(buf, dtype=np.uint8).reshape(sh, sw, 3).astype(np.float32) / 255.0
            feeds = {}
            for nm in inn:
                low = nm.lower()
                if low == "src":
                    feeds[nm] = f.transpose(2, 0, 1)[None]
                elif low == "downsample_ratio":
                    feeds[nm] = ratio
                elif low.startswith("r") and low.endswith("i"):
                    k = int(low[1]) - 1
                    if 0 <= k < 4:
                        feeds[nm] = rec[k]
            outs = sess.run(None, feeds)
            by = dict(zip(outn, outs))
            pha = np.asarray(by.get("pha", outs[min(1, len(outs) - 1)]))[0, 0]
            for k in range(4):
                if f"r{k+1}o" in by:
                    rec[k] = by[f"r{k+1}o"]
            rows.append((round(i * step, 2), float((pha > 0.5).mean())))
            i += 1
    finally:
        dec.stdout.close()
        dec.wait()
    return rows


def main() -> int:
    if not SRC.exists():
        print(f"缺素材 {SRC}")
        return 3
    for nm, (s, d) in (("a", (0.0, 3.0)), ("b", (4.0, 3.0))):
        call(["video-cut", str(SRC), "--start", str(s), "--duration", str(d), "--accurate",
              "--out", str(WORK / f"{nm}.mp4")])

    outs = {}
    for tag, trans in (("whip", "whip-pan"), ("fade", "fade")):
        o = WORK / f"join-{tag}.mp4"
        call(["video-join", str(WORK / "a.mp4"), str(WORK / "b.mp4"), "--transition", trans,
              "--transition-duration", "0.5", "--out", str(o)])
        outs[tag] = human_curve(o)
        print(f"\n=== {tag}（{trans} 转场）人形信号曲线 ===")
        for t, c in outs[tag]:
            bar = "█" * int(c * 120)
            mark = "  ← 转场区" if 2.5 <= t <= 3.2 else ""
            if c > 0.0005 or mark:
                print(f"  t={t:4.1f}s  {c:.4f} {bar}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
