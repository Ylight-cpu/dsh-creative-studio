# video-studio · 命令与参数参考

> 按需加载。所有命令支持 `--json`；输入文件永不被覆盖。

## 命令速查

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `video-probe <files…>` | 素材通览：时长/体积/码率/编码/分辨率/帧率/像素格式/音轨 | `--json` |
| `video-sheet <files…>` | 按间隔抽帧（通览/复核） | `--interval 2`、`--width 480`、`--out-dir` |
| `video-cut <file>` | 裁切 | `--start 5` / `1:30`、`--end`、`--duration`、`--accurate`（帧精确，重编码）、`--out`、`--out-dir` |
| `video-join <files…>` | 拼接 | `--transition fade\|wipeleft\|wiperight\|slideup\|slidedown\|circleopen\|dissolve`、`--transition-duration 0.5`、`--fps 30`、`--reencode` |
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
