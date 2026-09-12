# video-studio · 命令与参数参考

> 按需加载。所有命令支持 `--json`；输入文件永不被覆盖。

## 命令速查

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `video-probe <files…>` | 素材通览：时长/体积/码率/编码/分辨率/帧率/像素格式/音轨 | `--json` |
| `video-sheet <files…>` | 按间隔抽帧（通览/复核） | `--interval 2`、`--width 480`、`--out-dir` |
| `video-cut <file>` | 裁切 | `--start 5` / `1:30`、`--end`、`--duration`、`--accurate`（帧精确，重编码）、`--out`、`--out-dir` |
| `video-join <files…>` | 拼接 | `--transition none\|<任意 xfade 名>\|glitch\|whip-pan\|flash\|soft-zoom\|film-burn`、`--list-transitions`、`--transition-duration 0.5`、`--fps 30`、`--reencode` |
| `video-matte <file>` | **抠像换背景**（AI RVM / 绿幕色键） | `--mode composite\|alpha\|mask`、`--bg-color`、`--bg-image`、`--backend chromakey --key-color 0x00FF00 --key-similarity 0.3`、`--model mobilenetv3\|resnet50`、`--downsample-ratio 0.375`、`--alpha-smooth 0.25`、`--limit`、`--gpu`、`--compare` |
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
| AI 模型 | RVM（Robust Video Matting）ONNX，首次自动下载到 `~/.dsh-creative-studio/models`（mobilenetv3 14 MB / resnet50 102 MB）。可用 `CS_MODEL_DIR` 改缓存目录 |
| 实测速度 | CPU：568×320 ≈ **81 fps**；720×1280 ≈ **17 fps**。装 `onnxruntime-gpu` 后加 `--gpu` 更快 |
| 时间一致性 | RVM 自带循环状态（r1i–r4i），外加 `--alpha-smooth 0.25` 时域平滑，抑制边缘闪烁 |
| 三种输出 | `composite`（换背景出成片，保留原音轨）/ `alpha`（透明通道 WebM，VP9+yuva420p）/ `mask`（黑白遮罩，灰阶 mp4） |
| 背景 | `--bg-color white\|#1F6E43`、`--bg-image 背景图.jpg`（自动缩放） |
| 绿幕素材 | `--backend chromakey --key-color 0x00FF00 --despill green`，不加载模型，秒级 |
| 判据 | `--compare` 会导出前后帧 + 接触表；单帧客观判据：换白底后画面四角像素应 > 225 |
| 已知限制 | 玻璃、纱料、快速甩动仍会有边缘瑕疵；`mobilenetv3` 比 `resnet50` 更容易糊边，成片标准高时用 `--model resnet50` |

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
- `leak` 用 lavfi `gradients` 生成慢速流动光斑（不要用 `geq` 逐像素表达式——CPU 上会慢到超时），透明度用 `--leak-opacity`。
- 外部 LUT：`--lut look.cube`（`.cube`/`.3dl`），会追加在预设链末尾。
- 与抠像组合的典型流程：`video-matte`（换背景）→ `video-fx --preset teal-orange,glow`（统一影调）→ `video-text-anim`（标题）→ `video-export`。

