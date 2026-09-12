"""把「模型认为有人」的帧连人形掩膜一起导出，供人眼确认到底是真人还是误判。

读 tests/out/person-scan.json（由 detect_person.py 生成），取占比最高的若干帧，
用 RVM 的人形掩膜做红色叠加：红色区域 = 模型判定的人体。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "toolkit"))
import cs  # noqa: E402
import detect_person as dp  # noqa: E402

FF = cs.find_ffmpeg()
SCAN = HERE / "out" / "person-scan.json"
OUT = HERE / "out" / "person-sheet"
WARM = 0.7   # RVM 是循环模型，先喂 0.7 秒让它收敛
TOPN = 9


def frames_until(path: Path, t: float, sw: int, sh: int):
    """解码 0/t-WARM → t 的帧，返回最后一帧的 (rgb, 掩膜)。"""
    start = max(0.0, t - WARM)
    dec = subprocess.Popen(
        [FF, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(path),
         "-t", f"{WARM + 0.2:.3f}", "-vf", f"scale={sw}:{sh}", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    rec = [np.zeros([1, 1, 1, 1], dtype=np.float32) for _ in range(4)]
    ratio = np.array([dp.RATIO], dtype=np.float32)
    fsize = sw * sh * 3
    last = None
    try:
        while True:
            buf = dec.stdout.read(fsize)
            if len(buf) < fsize:
                break
            fr = np.frombuffer(buf, dtype=np.uint8).reshape(sh, sw, 3)
            f = fr.astype(np.float32) / 255.0
            feeds = {}
            for nm in dp_in:
                low = nm.lower()
                if low == "src":
                    feeds[nm] = f.transpose(2, 0, 1)[None]
                elif low == "downsample_ratio":
                    feeds[nm] = ratio
                elif low.startswith("r") and low.endswith("i"):
                    k = int(low[1]) - 1
                    if 0 <= k < 4:
                        feeds[nm] = rec[k]
            outs = dp_sess.run(None, feeds)
            by = dict(zip(dp_out, outs))
            pha = np.asarray(by.get("pha", outs[min(1, len(outs) - 1)]))[0, 0]
            for k in range(4):
                if f"r{k+1}o" in by:
                    rec[k] = by[f"r{k+1}o"]
            last = (fr, pha)
    finally:
        dec.stdout.close()
        dec.wait()
    return last


if __name__ == "__main__":
    import onnxruntime as ort
    dp_sess = ort.InferenceSession(str(dp.MODEL), providers=["CPUExecutionProvider"])
    dp_in = [i.name for i in dp_sess.get_inputs()]
    dp_out = [o.name for o in dp_sess.get_outputs()]

    data = json.loads(SCAN.read_text(encoding="utf-8"))
    hits = []
    for path, info in data.items():
        if info.get("group") not in ("源素材", "中途素材"):
            continue
        for h in info.get("hits", []):
            if h["cov"] >= 0.02:
                hits.append((h["cov"], Path(path), h["t"]))
    hits.sort(reverse=True)
    seen_clip: dict[str, int] = {}
    picked = []
    for cov, path, t in hits:
        if seen_clip.get(path.name, 0) >= 2:
            continue
        seen_clip[path.name] = seen_clip.get(path.name, 0) + 1
        picked.append((cov, path, t))
        if len(picked) >= TOPN:
            break

    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.jpg"):
        f.unlink()
    made = []
    for cov, path, t in picked:
        j = cs.ffprobe_json(FF, str(path))
        v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
        W, H = int(v.get("width") or 0), int(v.get("height") or 0)
        sc = min(1.0, dp.MAXSIDE / max(W, H))
        sw, sh = max(2, int(W * sc) // 2 * 2), max(2, int(H * sc) // 2 * 2)
        got = frames_until(path, t, sw, sh)
        if not got:
            continue
        rgb, pha = got
        m = (pha > 0.5)[:, :, None]
        ov = np.where(m, rgb.astype(np.float32) * 0.45 + np.array([255, 40, 40]) * 0.55,
                      rgb.astype(np.float32)).astype(np.uint8)
        name = f"{path.stem.strip()} t={t:.1f}s 人形占比{cov:.3f}.jpg"
        f = OUT / name
        Image.fromarray(ov).save(f, quality=88)
        made.append(f)
        print(f"  已导出 {name}   纵向中心={next((h['pos'] or {}).get('cy') for h in data[str(path)]['hits'] if h['t'] == t)}")

    if made:
        out = Path(r"F:\deepseek harness\供暖炉视频样片\素材里的人物-人形掩膜.jpg")
        subprocess.run([sys.executable, str(HERE.parent / "toolkit" / "cs.py"), "sheet"]
                       + [str(f) for f in made] + ["--labels", "--out", str(out)],
                       capture_output=True, text=True, encoding="utf-8")
        print(f"\n拼图：{out}" if out.exists() else "\n拼图失败")
    return_code = 0
    raise SystemExit(return_code)
