"""用「人像专用模型」(RVM) 反过来当人体探测器，回答：视频里到底有没有人？

RVM 只在画面里有人时才会输出非零 alpha（0.2.1 已实测：拿它抠产品得到 0.0000）。
所以可以反过来用：它对某一帧给出可观的前景覆盖率 = 该帧存在人体/人形目标。

同时记录前景块的**位置**（画面上/中/下），用来判断"幽灵人头"是出现在人该在的位置，
还是出现在画面底部某个不该有人的地方。

用法：python tests/detect_person.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "toolkit"))
import cs  # noqa: E402

FF = cs.find_ffmpeg()
MODEL = Path.home() / ".dsh-creative-studio" / "models" / "rvm_mobilenetv3_fp32.onnx"
SRC = Path(r"F:\新建文件夹 (2)\供暖炉\视频")
STOVE = HERE / "out" / "stove"
NEW = Path(r"F:\deepseek harness\供暖炉视频样片\修复版")
MAXSIDE = 960
RATIO = 0.5

TARGETS: list[tuple[str, Path, float]] = []
# 原始素材（14 段）：每 2 秒采一帧
for p in sorted(SRC.glob("*.mp4")):
    TARGETS.append(("源素材", p, 2.0))
TARGETS += [
    ("中途素材", STOVE / "shot1.mp4", 0.5),
    ("中途素材", STOVE / "shot2.mp4", 0.5),
]
# 旧的三条（被判不可交付）
for tag in ("A", "B", "C"):
    TARGETS.append(("旧版", STOVE / "styles" / "deliver" / f"{tag}-final-reel-9x16.mp4", 0.5))
# 新的三条
for f in sorted(NEW.glob("*.mp4")):
    TARGETS.append(("修复版", f, 0.5))


def probe_size(p: Path) -> tuple[int, int, float]:
    j = cs.ffprobe_json(FF, str(p))
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    fps = 30.0
    try:
        n, d = (v.get("r_frame_rate") or "30/1").split("/")
        fps = float(n) / float(d or 1)
    except Exception:
        pass
    return w, h, fps


def scan(path: Path, interval: float, sess, in_names, out_names) -> dict:
    W, H, fps = probe_size(path)
    if not W:
        return {"error": "no size"}
    scale = min(1.0, MAXSIDE / max(W, H))
    sw, sh = max(2, int(W * scale) // 2 * 2), max(2, int(H * scale) // 2 * 2)
    step = max(1, int(round(interval * fps)))
    dec = subprocess.Popen(
        [FF, "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-vf", f"select='not(mod(n\\,{step}))',scale={sw}:{sh}", "-vsync", "0",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    rec = [np.zeros([1, 1, 1, 1], dtype=np.float32) for _ in range(4)]
    ratio = np.array([RATIO], dtype=np.float32)
    fsize = sw * sh * 3
    rows, idx = [], 0
    try:
        while True:
            buf = dec.stdout.read(fsize)
            if len(buf) < fsize:
                break
            fr = np.frombuffer(buf, dtype=np.uint8).reshape(sh, sw, 3).astype(np.float32) / 255.0
            feeds = {}
            for nm in in_names:
                low = nm.lower()
                if low == "src":
                    feeds[nm] = fr.transpose(2, 0, 1)[None]
                elif low == "downsample_ratio":
                    feeds[nm] = ratio
                elif low.startswith("r") and low.endswith("i"):
                    k = int(low[1]) - 1
                    if 0 <= k < 4:
                        feeds[nm] = rec[k]
            outs = sess.run(None, feeds)
            by = dict(zip(out_names, outs))
            pha = np.asarray(by.get("pha", outs[min(1, len(outs) - 1)]))[0, 0]
            for k in range(4):
                if f"r{k+1}o" in by:
                    rec[k] = by[f"r{k+1}o"]
            m = pha > 0.5
            cov = float(m.mean())
            t = idx * interval
            ys, xs = np.where(m)
            pos = None
            if cov > 1e-4 and ys.size:
                cy = float((ys.min() + ys.max()) / 2) / sh
                height = float(ys.max() - ys.min()) / sh
                pos = {"cy": round(cy, 2), "h": round(height, 2)}
            rows.append({"t": round(t, 2), "cov": round(cov, 4), "pos": pos})
            idx += 1
    finally:
        dec.stdout.close()
        dec.wait()
    return {"size": f"{sw}x{sh}", "samples": len(rows), "rows": rows}


def main() -> int:
    try:
        import onnxruntime as ort
    except Exception as e:
        print(f"缺 onnxruntime：{e}")
        return 3
    if not MODEL.exists():
        print(f"缺 RVM 模型：{MODEL}")
        return 3
    print(f"模型：{MODEL.name}  推理缩放={RATIO}  解码上限={MAXSIDE}px（数值= 人体前景占比）\n")
    sess = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    in_names = [i.name for i in sess.get_inputs()]
    out_names = [o.name for o in sess.get_outputs()]

    report = {}
    for group, path, interval in TARGETS:
        if not path.exists():
            print(f"[跳过] 缺文件 {path}")
            continue
        r = scan(path, interval, sess, in_names, out_names)
        if "error" in r:
            print(f"[跳过] {path.name}: {r['error']}")
            continue
        covs = [x["cov"] for x in r["rows"]]
        mx = max(covs) if covs else 0.0
        mean = float(np.mean(covs)) if covs else 0.0
        hits = [x for x in r["rows"] if x["cov"] >= 0.005]
        report[str(path)] = {"group": group, "max": round(mx, 4), "mean": round(mean, 5),
                             "hits": hits[:12], "samples": r["samples"]}
        flag = "★有人形" if mx >= 0.02 else ("·微弱" if mx >= 0.005 else "")
        print(f"[{group}] {path.name}  {r['size']}  采样 {r['samples']} 帧  "
              f"最大占比={mx:.4f}  均值={mean:.5f}  {flag}")
        for x in hits[:6]:
            p = x["pos"] or {}
            print(f"      t={x['t']:6.2f}s  占比={x['cov']:.4f}  "
                  f"纵向中心={p.get('cy')}（0=顶 1=底）  高度占画面={p.get('h')}")
    (HERE / "out" / "person-scan.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n明细：tests/out/person-scan.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
