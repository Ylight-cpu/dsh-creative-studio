# 隔离测试：单帧 RVM 推理的 alpha 统计（绕开解码管道）
# 目的：判断"产品消失"是模型喂参问题，还是解码/管线问题。
import subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image
import onnxruntime as ort

FF = r"F:\deepseek harness\dsh-creative-studio\runtime\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
MODEL = Path.home() / ".dsh-creative-studio" / "models" / "rvm_mobilenetv3_fp32.onnx"
SRC = Path(r"F:\deepseek harness\dsh-creative-studio\tests\out\stove\shot1.mp4")
TMP = Path(r"F:\deepseek harness\dsh-creative-studio\tests\out\stove\diag")


def grab(t: float) -> Image.Image:
    TMP.mkdir(parents=True, exist_ok=True)
    f = TMP / f"rvmtest_{t:.1f}.png"
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(SRC),
                    "-ss", f"{t:.3f}", "-frames:v", "1", str(f)], capture_output=True)
    return Image.open(f).convert("RGB")


def run(sess, img: Image.Image, ratio: float, rec=None):
    W, H = img.size
    a = np.asarray(img, dtype=np.float32) / 255.0
    feeds = {}
    for i in sess.get_inputs():
        n = i.name.lower()
        if n == "src":
            feeds[i.name] = a.transpose(2, 0, 1)[None]
        elif n == "downsample_ratio":
            feeds[i.name] = np.array([ratio], dtype=np.float32)
        elif n.startswith("r") and n.endswith("i"):
            idx = int(n[1]) - 1
            feeds[i.name] = (rec[idx] if rec else np.zeros([1, 1, 1, 1], dtype=np.float32))
    outs = sess.run(None, feeds)
    names = [o.name for o in sess.get_outputs()]
    by = dict(zip(names, outs))
    return by, names


def main():
    print("模型:", MODEL, "存在:", MODEL.exists())
    s = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    print("输入名:", [i.name for i in s.get_inputs()])
    print("输出名:", [o.name for o in s.get_outputs()])
    img = grab(1.0)
    print("测试帧尺寸:", img.size)

    for ratio in (0.375, 0.25, 1.0):
        by, names = run(s, img, ratio)
        pha = by.get("pha")
        fgr = by.get("fgr")
        if pha is None:
            print(f"  ratio={ratio}: 没有 pha 输出！实际输出={names}")
            continue
        p = pha[0, 0]
        print(f"  ratio={ratio}: pha min={p.min():.4f} mean={p.mean():.4f} max={p.max():.4f} "
              f"| >0.5 占比={(p>0.5).mean():.4f} | fgr mean={fgr.mean():.3f}")

    # 对照：rembg 单帧抠图（图片路径用的是同一类模型，理论上应能找出主体）
    try:
        from rembg import new_session, remove
        cut = remove(img, session=new_session("isnet-general-use"))
        al = np.asarray(cut.getchannel("A"), dtype=np.float32) / 255.0
        print(f"  对照 rembg/isnet: alpha mean={al.mean():.4f} | >0.5 占比={(al>0.5).mean():.4f}")
    except Exception as e:
        print("  rembg 对照失败:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
