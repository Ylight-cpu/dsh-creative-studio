# image-studio · 命令与参数参考

> 按需加载：只有在需要精确参数或遇到边界情况时才读本文件。
> 所有命令都支持 `--json`；输出默认写在输入旁边并加后缀，**永不覆盖输入**。

## 命令速查

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `inspect <imgs…>` | 体检：尺寸/模式/透明通道/主体 bbox 与占比/亮度/主色/边缘过渡宽度 | `--json` |
| `matte <imgs…>` | 抠图 → RGBA PNG | `--quality fast\|auto\|best`、`--model <名>`、`--bg white\|#f5f5f5`、`--feather 1.5`、`--alpha-matting`、`--fg-threshold/--bg-threshold/--erode` |
| `inpaint <img>` | 局部重绘改图：去杂物/水印/瑕疵 | `--mask 掩码.png`、`--box x,y,w,h`（可重复）、`--circle x,y,r`、`--dilate 2`、`--backend auto\|telea\|ns\|lama-onnx`、`--radius 6`、`--lama-model 路径` |
| `text <img>` | 加文字（自动换行/描边/阴影/底块/九宫格定位） | `--text "行1\n行2"`、`--position tl…br`、`--size`、`--font msyh`、`--color`、`--stroke '#1F6E43'`、`--stroke-width`、`--shadow`、`--box '#00000099'`、`--margin`、`--max-width-ratio` |
| `logo <img>` | 贴 logo/水印 | `--logo x.png`、`--position br`、`--width-ratio 0.16`、`--margin`、`--opacity 0.9`、`--key-white` |
| `compose <base>` | 多图层合成 | `--overlay path:x:y[:scale]`（px 或 `%`，可重复） |
| `export <imgs…\|dir>` | 平台规格导出（目录自动递归批处理） | `--preset amazon-main\|amazon-zoom\|amazon-lifestyle\|shopify\|faire\|square\|story-9x16\|wide-16x9\|thumb-4x5`、`--size WxH`、`--mode pad\|fit\|crop`、`--bg`、`--out-dir` |
| `sheet <imgs…\|dir>` | 接触表（选片/交付预览） | `--cols`、`--cell`、`--labels`、`--out` |
| `palette <img>` | 主色提取 | `--colors 6` |
| `doctor` / `selftest` | 环境自检 / 端到端验收 | `--json` |

## 抠图模型可选值

`u2net`、`u2netp`、`u2net_human_seg`、`u2net_cloth_seg`、`isnet-general-use`、`isnet-anime`、
`birefnet-general`、`birefnet-general-lite`、`birefnet-portrait`、`birefnet-cod`、`birefnet-dis`、
`birefnet-hrsod`、`birefnet-massive`、`bria-rmbg`、`silueta`、`sam`、`withoutbg`

选型经验：
- 商品/静物 → `birefnet-general`（最佳）或 `isnet-general-use`（快）
- 人像/头发 → `birefnet-portrait` 或 `u2net_human_seg`
- 玻璃、半透明、毛发 → 必须 `birefnet-*`，`u2net` 会明显糊
- 动漫插画 → `isnet-anime`
- 批量草稿 → `u2net`（0.15s/张）

## 改图（inpaint）决策树

```
要改的地方有多大？
├─ 小面积（水印、灰尘、划痕、电线、小杂物，< 画面 5%）
│   → inpaint --box/--circle/--mask --backend telea --dilate 2   （零额外依赖，秒级）
├─ 中等面积（去掉一个人/一件道具，背景纹理较规则）
│   → inpaint --mask （先用 matte 或手绘掩码）；telea 会糊，改用 lama-onnx
└─ 大面积 / 需要"生成新内容"（换场景、换材质、补全大片缺失）
    → 本工具链不提供生成式重绘；如实告知，或让用户提供 LaMa ONNX 模型后
      inpaint --backend lama-onnx --lama-model <路径>（或设 CS_LAMA_ONNX）
```

掩码制作：白色 = 要重绘的区域，黑色 = 保留。`--mask` 尺寸与原因不同会自动缩放（NEAREST）。
用 `--dilate 1~3` 外扩掩码可消除边缘残影；先小后大，过大会吃掉纹理。

## compose 叠加语法

`--overlay "F:\path\logo.png:50%:80%:0.35"` = 路径 : X : Y : 缩放。
X/Y 支持像素（`120`）或百分比（`50%`）；缩放支持倍数（`0.35`）或百分比（`35%`）。
路径含盘符冒号也安全（解析器从右往左吃坐标）。

## 平台规格预设

| 预设 | 尺寸 | 模式 | 背景 | 用途 |
|---|---|---|---|---|
| `amazon-main` | 2000×2000 | pad | white | 亚马逊主图（纯白底，商品占比大） |
| `amazon-zoom` | 3000×3000 | pad | white | 需要放大镜细节时 |
| `amazon-lifestyle` | 1600×1600 | crop | — | 场景图/辅图 |
| `shopify` | 2048×2048 | pad | white | Shopify 商品图 |
| `faire` | 1600×1600 | pad | white | Faire 批发平台 |
| `thumb-4x5` | 1080×1350 | pad | white | 信息流竖版 |
| `story-9x16` | 1080×1920 | pad | white | 竖屏故事/短视频封面 |

`--mode`：`pad` 留白居中（不改构图，平台最安全）· `fit` 等比缩放到框内（可透明底）· `crop` 等比填满后居中裁切（会切边）。

## 常见故障

| 现象 | 处理 |
|---|---|
| `matte` 首次运行卡住 | 正在下载模型（u2net 176MB / birefnet 更大）；网络受限时设 `HF_ENDPOINT=https://hf-mirror.com` |
| `TIER_UNAVAILABLE` | 缺依赖层；运行 `scripts\bootstrap.ps1`，不要手工往无关环境装包 |
| 中文变方框/乱码 | 命令前加 `chcp 65001`，并显式 `--font msyh`（Windows） |
| 图片方向不对（竖拍变横图） | 已自动按 EXIF 旋正；若源图 EXIF 被剥离过，先手工旋正再处理 |
| `compose` 报路径错 | 确认 `--overlay` 用 `路径:X:Y[:缩放]`；路径可含盘符冒号 |
| 抠图边缘发虚/有白边 | 看 `matte` 返回的 `transition_px`；>3 时改 `--quality best`，必要时加 `--alpha-matting` |
| inpaint 结果像涂抹 | 用 telea 处理大面积必然糊；改小掩码、加 `--dilate`，或换 `lama-onnx` |
