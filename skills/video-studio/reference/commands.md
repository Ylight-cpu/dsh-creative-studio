# video-studio · 命令与参数参考

> 按需加载。所有命令支持 `--json`；输入文件永不被覆盖。

## 命令速查

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `video-probe <files…>` | 素材通览：时长/体积/码率/编码/分辨率/帧率/像素格式/音轨 | `--json` |
| `video-sheet <files…>` | 按间隔抽帧（通览/复核） | `--interval 2`、`--width 480`、`--out-dir` |
| `video-cut <file>` | 裁切 | `--start 5` / `1:30`、`--end`、`--duration`、`--accurate`（帧精确，重编码）、`--out`、`--out-dir` |
| `video-join <files…>` | 拼接 | `--transition none\|<任意 xfade 名>\|glitch\|whip-pan\|flash\|soft-zoom\|film-burn`、`--list-transitions`、`--transition-duration 0.5`、`--fps 30`、`--reencode` |
| `video-matte <file>` | **抠像换背景**（AI 逐帧：rembg 通用 / RVM 人像 / 绿幕色键） | `--backend auto\|rembg\|rvm\|chromakey`、`--quality fast\|auto\|best`、`--mode composite\|alpha\|mask`、`--bg-color`、`--bg-image`、`--min-subject 0.005`、`--allow-empty`、`--mask-scale`、`--post-process-mask`、`--backend chromakey --key-color 0x00FF00 --key-similarity 0.3`、`--model`、`--downsample-ratio 0.375`（RVM）、`--alpha-smooth 0.25`、`--limit`、`--gpu`、`--compare` |
| `video-text-anim [file]` | **动效文字**（ASS 生成 / 烧入） | `--text`、`--spec blocks.json`、`--preset fade\|slide-up\|slide-down\|slide-left\|slide-right\|typewriter\|pop\|bounce\|karaoke\|lower-third`、`--position`、`--size-ratio 0.055`、`--outline`、`--shadow`、`--box '#00000099'`、`--highlight`、`--ass-out`、`--ass-only` |
| `video-fx <file>` | **光效 / 调色** | `--list`、`--preset glow,bloom,soft-focus,leak,trail,grain,vignette,sharpen,warm,cool,teal-orange,film,punch`、`--lut x.cube`、`--leak-opacity 0.35`、`--compare` |
| `video-text <file>` | 屏幕文案（PIL 渲染透明层 → overlay，中文可靠） | `--text "行1\n行2"`、`--position tc…br`、`--size`、`--color`、`--stroke`、`--stroke-width`、`--box`、`--start`、`--end`、`--png-out` |
| `video-subtitle <file>` | 烧入字幕 | `--subtitle subs.srt`、`--font-name "Microsoft YaHei"`、`--font-size 26`、`--color`、`--outline`、`--alignment 2`、`--margin-v 40` |
| `video-audio <file>` | 配乐/混音/淡入淡出/静音 | `--music bgm.mp3`、`--music-volume 0.35`、`--original-volume 1.0`、`--mute`、`--fade-in`、`--fade-out`、`--loop` |
| `video-cover <files…>` | 封面帧 | `--at 5`、`--scan 8`（采样 N 帧取边缘能量最高者）、`--out` |
| `video-export <files…>` | 平台规格导出 | `--preset reel-9x16\|wide-16x9\|square-1x1\|thumb-4x5\|hd-720p`、`--size WxH`、`--mode pad\|crop`、`--bg white`、`--fps 30`、`--crf 20`、`--preset-speed` |
| `doctor` / `selftest` | 环境自检 / 端到端验收 | `--json` |

## 时间格式

`12.5`（秒）、`1:30`（分:秒）、`00:01:30.250`（时:分:秒.毫秒）都接受，`--start/--end/--duration/--at` 通用。

## 剪辑模式选择

| 场景 | 用法 | 说明 |
|---|---|---|
| 掐头去尾、不要求帧对齐 | `video-cut --start --end`（默认） | 流复制，秒级完成；切口落在关键帧上，可能差几帧 |
| 卡在台词/鼓点上 | `video-cut --accurate` | 重编码，帧精确；速度取决于时长 |
| 同源素材直接接 | `video-join`（默认） | concat 流复制，无损最快 |
| 参数不一致（手机横竖混拍、不同帧率） | `video-join --transition fade` 或 `--reencode` | 内置归一化：时基/帧率/像素格式/采样率统一后拼接 |
| 需要转场 | `--transition <名> --transition-duration 0.6` | 输出强制 `yuv420p`（社交平台兼容） |

## 已知坑与处理

| 现象 | 原因与处理 |
|---|---|
| `xfade ... timebase do not match` | 手工写 filter 时未归一化；本工具已内置 `settb=AVTB,fps,setsar=1` |
| 输出在某些播放器偏色/花屏 | 转场后像素格式会漂成 yuv444p；本工具链尾强制 `format=yuv420p`，手写命令也要加 `-pix_fmt yuv420p` |
| 找不到 `ffprobe` | 本机只有 `imageio-ffmpeg` 自带的 ffmpeg；`video-probe` 会自动退化为解析 `ffmpeg -i` 输出，无需处理 |
| Windows 字幕路径报错 | libass 需要转义盘符冒号；本工具已处理，手写用 `subtitles='C\:/path/subs.srt'` |
| 中文字幕变方框 | `--font-name "Microsoft YaHei"`（Windows）或机器上已有的 CJK 字体；`doctor` 会列出检测到的字体 |
| 某段素材没有音轨 | `video-join --transition` 会自动丢弃音轨而不是报错；补 `video-audio --music bgm.mp3 --loop` 得到统一成片 |
| 拼接后时长不对 | 有转场时会短掉 `(n-1) × 转场时长`，属正常；用 `video-probe` 核对 |

## 素材卫生

- 中间产物放 `work/`，交付物只从 `deliver/` 出。
- 输出命名带规格后缀（`-reel-9x16`、`-sub`），便于回溯。
- 批量导出：`video-export <目录>\*.mp4` 或逐个传参，均支持。

## 抠像换背景（video-matte）

| 项 | 说明 |
|---|---|
| 默认后端（0.2.1 起） | `rembg` **逐帧通用抠像**：`--quality fast=u2net / auto=isnet-general-use / best=birefnet-general`，产品、物体、动物、人都能抠 |
| 实测速度 | CPU + 720×1280：isnet ≈ **2.3 fps**（3 秒片约 40 秒）；birefnet 约 6 秒/帧，长片先 `--limit 3` 试跑 |
| 人像后端 | `--backend rvm`（RVM ONNX，首次自动下载到 `~/.dsh-creative-studio/models`，mobilenetv3 14 MB / resnet50 102 MB）。**只适合画面里有人的素材**：拿它抠产品会得到全空遮罩 |
| 时间一致性 | 逐帧推理本身会闪，所以默认 `--alpha-smooth 0.25` 做 alpha 时域平滑；RVM 另带循环状态（r1i–r4i） |
| 三种输出 | `composite`（换背景出成片，保留原音轨）/ `alpha`（透明通道 WebM，VP9+yuva420p）/ `mask`（黑白遮罩，灰阶 mp4） |
| 背景 | `--bg-color white\|#1F6E43`、`--bg-image 背景图.jpg`（自动缩放） |
| 绿幕素材 | `--backend chromakey --key-color 0x00FF00 --despill green`，不加载模型，秒级（走色键时不受主体闸门约束） |
| **主体存在性闸门** | 每帧统计前景覆盖率（alpha>0.5 的像素占比）。均值低于 `--min-subject`（默认 0.005）→ 第 20 帧提前熔断、删除产物、`status: rejected`、退出码 2，**不会交付空视频**。`--allow-empty` 才强行输出（会打印警告并标记 `gate_overridden`） |
| 质量辅助参数 | `--mask-scale 0.5`（更快更柔）、`--post-process-mask`（去小噪点） |
| 判据 | JSON 里的 `subject.coverage_mean/min/max` + `gate.verdict`；`--compare` 导出前后帧 + 接触表；模型看不到画面，交付前用 `tests/verify_fix.py --matte` 量「非白像素占比」并由人眼确认 |
| 已知限制 | 玻璃、纱料、快速甩动、主体与背景同色仍会有边缘瑕疵；逐帧抠像在细发丝/半透明处的时域稳定性弱于专业工具 |

## 动效文字（video-text-anim）

- 产物是**标准 ASS 文件**：可以只生成（`--ass-only`）交给人工微调，也可以直接烧入。
- 预设与实现方式：`fade`（\fad）· `slide-*`（\move + \fad）· `typewriter`（逐字符 \alpha 时间标签）· `pop`/`bounce`（\t 缩放）· `karaoke`（\k 逐词高亮，中文按字切）· `lower-third`（位移 + 无描边底条样式）。
- 多条文案用 `--spec blocks.json`：`{"width":1080,"height":1920,"blocks":[{text,start,end,preset,position,size,color}]}`。
- 安全区：默认底部留白为竖版 20%、横版 12%（避开平台 UI 遮挡）。
- 字号用 `--size-ratio`（占画面高度比例）：竖版 0.05–0.08 是常用区间。

## 转场（video-join --transition）

- `--list-transitions` 从 ffmpeg 自身枚举，当前构建 **53 种**（`fade/fadeblack/fadewhite/wipe*/slide*/smooth*/circle*/vert*/horz*/dissolve/pixelize/radial/hlslice/diag*/cover*/reveal*/squeeze*/zoomin/lunax` 等）。
- 风格化预置（自动加"后一段"开头的局部效果，再做基础转场）：

| 预置 | 效果 | 基础转场 |
|---|---|---|
| `flash` | 白闪 | `fadewhite` |
| `glitch` | 色彩偏移 + 噪点 → 像素化切入 | `pixelize` |
| `whip-pan` | 方向拖影 → 平滑左滑 | `smoothleft` |
| `soft-zoom` | 高斯模糊 → 淡入（近似变焦） | `fade` |
| `film-burn` | 暖色偏移 + 颗粒 → 黑场 | `fadeblack` |

## 光效与调色（video-fx）

- 预设可串联：`--preset teal-orange,glow,film`（按顺序应用）。
- `leak` 用 lavfi `gradients` 生成**左上角径向暖光斑**（`type=radial` + 外圈近黑，只提亮局部）。不要用 `geq` 逐像素表达式（CPU 上会慢到超时），也不要用全画面线性渐变——0.2.0 事故就是它把整片染粉，并产生一个缓慢漂移的亮斑（用户看出像"幽灵人头"）。强度用 `--leak-opacity`（默认 0.35）。
- **screen/blend 类叠加必须显式 `format=gbrp` 再回 `format=yuv420p`**：在 yuv420p 上混 UV 平面会产生品红偏色。所有内置预设已按此写死。
- 外部 LUT：`--lut look.cube`（`.cube`/`.3dl`），会追加在预设链末尾。
- **偏色闸门**：任何调色/光效交付前用 `python tests/verify_fix.py --fx <成片> --fx-ref <未调色文件>` 量 `R-(G+B)/2` 的相对增量，|Δ| ≤ 20 才算通过（`selftest` 里也带这条）。
- 与抠像组合的典型流程：`video-matte`（换背景）→ `video-fx --preset teal-orange,glow`（统一影调）→ `video-text-anim`（标题）→ `video-export`。

