"""重建三版风格样片（0.2.1 修复版），每步都过客观闸门。

与旧三版的差别（旧版已被判定不可交付）：
  A 版：抠像后端由 RVM（人像模型）改为 rembg 通用逐帧抠像 → 主体不再被抠没
  B/C 版：光泄漏由「全画面漂移渐变」改为「左上角径向暖光斑」→ 不再全片泛粉、不再有幽灵光斑
  文字：第三条标题时间由 4.0–5.3s 调整为 4.35–5.4s（旧版在 5.55s 片长里几乎看不清）

用法：python tests/rebuild_styles.py [--only A,B,C] [--out <目录>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "toolkit"))

import verify_fix as vf  # noqa: E402

PY = sys.executable
CS = HERE.parent / "toolkit" / "cs.py"
WORK = HERE / "out" / "stove"
SRC1, SRC2 = WORK / "shot1.mp4", WORK / "shot2.mp4"

# 文案与旧版一致，只修时间轴（旧版第三条标题 4.0–5.3s 在 5.55s 成片里几乎一闪而过）
TITLES = {
    "width": 720, "height": 1280, "blocks": [
        {"text": "SHOTO 生物质颗粒炉", "start": 0.3, "end": 2.2, "preset": "typewriter",
         "position": "tc", "size": 0.055, "color": "white", "stroke": "#1F6E43"},
        {"text": "无电重力落料 · 多燃料", "start": 2.7, "end": 4.2, "preset": "karaoke",
         "position": "bc", "size": 0.05, "color": "white", "highlight": "#FFD54A"},
        {"text": "颗粒 木柴 秸秆 木炭", "start": 4.35, "end": 5.4, "preset": "slide-up",
         "position": "bc", "size": 0.045, "color": "white", "stroke": "#1F6E43"},
    ],
}

STYLES = {
    "A": {"name": "干净商务风", "matte": True, "transition": "soft-zoom",
          "fx": ["punch"], "leak": None},
    "B": {"name": "科技故障风", "matte": False, "transition": "glitch",
          "fx": ["punch", "leak", "grain"], "leak": 0.22},
    "C": {"name": "电影感", "matte": False, "transition": "film-burn",
          "fx": ["teal-orange", "film", "leak"], "leak": 0.15},
}


def run(args: list[str], label: str) -> dict:
    p = subprocess.run([PY, str(CS)] + args + ["--json"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        # 带 JSON 的失败（例如抠像闸门拒绝交付）也要把原因带出来
        print(f"  [FAIL] {label} (exit {p.returncode})")
        print("         " + (p.stdout or "").strip()[:600])
        print("         " + (p.stderr or "").strip()[:400])
        raise SystemExit(1)
    try:
        return json.loads(p.stdout)
    except Exception:
        return {"raw": p.stdout.strip()[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="A,B,C")
    ap.add_argument("--out", default=str(Path(r"F:\deepseek harness\供暖炉视频样片\修复版")))
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stage = WORK / "rebuild"
    stage.mkdir(parents=True, exist_ok=True)
    spec = stage / "titles-fix.json"
    spec.write_text(json.dumps(TITLES, ensure_ascii=False, indent=1), encoding="utf-8")

    todo = [s.strip().upper() for s in args.only.split(",") if s.strip()]
    summary: list[dict] = []

    for tag in todo:
        cfg = STYLES[tag]
        print(f"\n===== {tag} 版：{cfg['name']} =====")
        clips = [SRC1, SRC2]

        # 1) A 版先抠像换白底（rembg 通用逐帧抠像 + 主体存在性闸门）
        if cfg["matte"]:
            matted = []
            for i, c in enumerate(clips, 1):
                mo = stage / f"{tag}-shot{i}-white.mp4"
                j = run(["video-matte", str(c), "--bg-color", "white", "--out", str(mo)],
                        f"{tag} 抠像 shot{i}")
                cov = j["subject"]["coverage_mean"]
                print(f"  抠像 shot{i}：{j['engine']}/{j['model']}  主体覆盖率={cov:.3f}  "
                      f"{j['matting_fps']} fps  {j['seconds']}s")
                assert cov >= 0.02, f"主体覆盖率 {cov} 过低"
                matted.append(mo)
            clips = matted

        # 2) 转场拼接
        joined = stage / f"{tag}-join.mp4"
        run(["video-join", str(clips[0]), str(clips[1]), "--transition", cfg["transition"],
             "--transition-duration", "0.5", "--out", str(joined)], f"{tag} 拼接")
        print(f"  拼接：{cfg['transition']} 转场 0.5s")

        # 3) 动效文字
        titled = stage / f"{tag}-titled.mp4"
        run(["video-text-anim", str(joined), "--spec", str(spec), "--ass-out",
             str(stage / f"{tag}.ass"), "--out", str(titled)], f"{tag} 文字动效")

        # 4) 影调 / 光效
        final = stage / f"{tag}-final.mp4"
        fxargs = ["video-fx", str(titled), "--preset", ",".join(cfg["fx"])]
        if cfg["leak"] is not None:
            fxargs += ["--leak-opacity", str(cfg["leak"])]
        fxargs += ["--out", str(final)]
        run(fxargs, f"{tag} 影调")
        print(f"  影调：{', '.join(cfg['fx'])}" + (f"（光泄漏 {cfg['leak']}）" if cfg["leak"] else ""))

        # 5) 平台规格
        deliver = out_dir / f"{tag}-{cfg['name']}-修复版-9x16.mp4"
        run(["video-export", str(final), "--preset", "reel-9x16", "--out", str(deliver)],
            f"{tag} 导出 9:16")
        print(f"  导出：{deliver}")

        # ---------- 闸门 ----------
        times = [0.5, 1.2, 2.0, 3.2, 4.4, 5.2]
        record: dict = {"style": tag, "name": cfg["name"], "file": str(deliver), "checks": []}

        if cfg["matte"]:
            shares = []
            for t in times:
                a = vf.frame(deliver, t, f"{tag}-gate")
                if a is None:
                    continue
                s = vf.subject_share(a)
                shares.append(s)
                ok = s >= 0.02
                record["checks"].append({"gate": "主体存在性", "t": t, "value": round(s, 4), "ok": ok})
            print(f"  闸门·主体存在性：非白占比 {min(shares):.3f}–{max(shares):.3f} "
                  f"{'通过' if min(shares) >= 0.02 else '不通过'}")

        casts, deltas = [], []
        for t in times:
            a, b = vf.frame(deliver, t, f"{tag}-fx"), vf.frame(titled, t, f"{tag}-ref")
            if a is None or b is None:
                continue
            c, r = vf.channel_cast(a), vf.channel_cast(b)
            casts.append(c)
            deltas.append(c - r)
            record["checks"].append({"gate": "偏色增量", "t": t, "value": round(c - r, 2),
                                     "ok": abs(c - r) <= 20})
        dmax = max((abs(d) for d in deltas), default=0.0)
        print(f"  闸门·光效偏色增量：最大 |Δ|={dmax:.1f} {'通过' if dmax <= 20 else '不通过'}")

        # 6) 审片材料（人眼过目）
        sheet_dir = stage / f"frames-{tag}"
        run(["video-sheet", str(deliver), "--interval", "0.8", "--width", "360",
             "--out-dir", str(sheet_dir)], f"{tag} 抽帧")
        frames = sorted(sheet_dir.glob("*.jpg"))
        contact = out_dir / f"{tag}-{cfg['name']}-逐帧审片.jpg"
        if frames:
            run(["sheet"] + [str(f) for f in frames] + ["--labels", "--out", str(contact)],
                f"{tag} 审片图")
            print(f"  审片：{contact}")
        cover = out_dir / f"{tag}-{cfg['name']}-封面.jpg"
        run(["video-cover", str(deliver), "--scan", "10", "--out", str(cover)], f"{tag} 封面")

        record["gates_ok"] = all(c["ok"] for c in record["checks"])
        record["cast_max"] = round(dmax, 1)
        summary.append(record)

    (out_dir / "修复版-验收数据.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n===== 汇总 =====")
    allok = True
    for r in summary:
        allok &= bool(r["gates_ok"])
        print(f"  {r['style']} 版（{r['name']}）：闸门 {'全部通过' if r['gates_ok'] else '有不通过项'}"
              f"  最大偏色增量 {r['cast_max']}")
        print(f"    {r['file']}")
    print(f"\n验收数据：{out_dir / '修复版-验收数据.json'}")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
