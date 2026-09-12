# dsh-creative-studio

**给 DeepSeek Harness 用的「AI 美工 + 视频剪辑」技能包。** 装一次，任意装了 DSH 的电脑都能用：

- **图片**：抠图（多档质量）/ 改图（局部重绘去杂物）/ 加文字 / 贴 logo / 多图层合成 / 平台规格批量导出 / 体检报告
- **视频**：素材通览 / 文案脚本 / 精确裁切 / 拼接转场（53 种 + 5 个风格化）/ **AI 抠像换背景** / **动效文字**（打字机·卡拉OK·滑入弹出）/ 字幕 / 配乐 / **光效调色**（辉光·泛光·光泄漏·拖影·LUT）/ 智能封面 / 平台导出

> 为什么不是"让模型直接画图"：设计和剪辑的瑕疵大多来自"凭描述想象"。
> 这个包让 agent **真正操作文件**——调用本地工具链干活，再按验收清单核对结果。

## 特效能力与边界（先看这张表）

| 能力 | 命令 | 实测 |
|---|---|---|
| 抠像换背景（任意背景） | `video-matte` | RVM ONNX，CPU 上 568×320 **81 fps** / 720×1280 **17 fps**；绿幕素材走 `--backend chromakey` 秒级；可输出成片 / 透明 WebM / 黑白遮罩 |
| 动效文字 | `video-text-anim` | 10 个预设：淡入、四向滑入、打字机、弹出、弹跳、逐词卡拉OK、下三分之一条；产出标准 ASS 可二次编辑 |
| 转场 | `video-join --transition` | 从 ffmpeg 枚举 **53 种** xfade；风格化：`glitch`/`whip-pan`/`flash`/`soft-zoom`/`film-burn` |
| 光效调色 | `video-fx --preset` | 13 个预设：辉光、泛光、柔焦、光泄漏、拖影、颗粒、暗角、锐化、暖调、冷调、青橙、胶片、强对比；支持外部 `.cube` LUT |

**做不到的（需要 After Effects）**：运动跟踪（把文字钉在运动物体上）、3D 相机、粒子系统、复杂 roto 遮罩。这条写进技能文档，避免交付时含糊。

## 装到一台新机器

```powershell
# 1) 拷贝整个 dsh-creative-studio 文件夹到新机器任意位置（runtime/ 可先不拷，引导时自动生成）

# 2) 准备运行时：独立 Python + 依赖 + 抠图模型（约 400MB，首次几分钟）
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#   国内默认走清华镜像；需要代理加 -Proxy http://127.0.0.1:7897；只要图片基础能力用 -Tier core

# 3) 装成 DSH 插件（推荐）：写入 profile 的 node_modules 与 dsh.profile.bundles
powershell -ExecutionPolicy Bypass -File scripts\install-as-plugin.ps1
#   装完重启 DSH，插件与包内两个技能在启动时加载
```

或者直接双击 `scripts\bootstrap.cmd`、`scripts\install-as-plugin.cmd`。

**安装方式对比**

| 方式 | 命令 | 特点 |
|---|---|---|
| **插件（推荐）** | `install-as-plugin.ps1` | 随 DSH profile 加载，技能由插件提供（`ctx.skills.registerProvider`），不占用技能根；改代码后重启 DSH 生效 |
| 技能根（备用） | `install-into-dsh.ps1` | 把 `skills/*` 以 junction 挂到 `<DSH_HOME>\skills`，**无需重启即时生效**，适合临时/受限环境 |

两者可共存，但同名技能建议只留一处；插件生效后清理技能根：`install-into-dsh.ps1 -Uninstall`。
卸载插件：`install-as-plugin.ps1 -Uninstall`（会先备份 profile 配置）。

插件模式下包根同样好定位：技能目录就是 `<包>\skills\<技能名>`，向上两级即包根；脚本还会写位置标记与环境变量作为兜底。

## 手工调用（不经过技能，也可直接用）

```powershell
chcp 65001 > $null; [Console]::OutputEncoding = [Text.Encoding]::UTF8   # 中文路径/文字不乱码
node "<包目录>\scripts\run-toolkit.mjs" doctor --json                     # 自检：依赖/ffmpeg/模型/GPU/字体
node "<包目录>\scripts\run-toolkit.mjs" matte 产品.jpg --bg white --out 白底.png --json
node "<包目录>\scripts\run-toolkit.mjs" text  白底.png --text "标题`nSubtitle" --position bc --color white --json
node "<包目录>\scripts\run-toolkit.mjs" video-probe 素材.mp4 --json
node "<包目录>\scripts\run-toolkit.mjs" video-export 成片.mp4 --preset reel-9x16 --out-dir deliver --json
```

## 能力分层（换机器自动降级/解锁）

| 层 | 依赖 | 能力 |
|---|---|---|
| **T0** | Pillow | 加文字、贴 logo（含白底自动抠）、多图层合成、平台规格导出、接触表、体检报告、主色提取 |
| **T1** | + rembg / onnxruntime | 抠图（`--quality fast\|auto\|best`，模型按需下载）、换背景、**局部重绘改图 `inpaint`**（telea 零依赖；`lama-onnx` 可选） |
| **T2** | + ffmpeg（`imageio-ffmpeg` 内置） | 视频探针、抽帧、裁切、拼接/转场、贴字、字幕、配乐、智能封面、规格导出 |
| **T3** | + onnxruntime（已含） | **AI 视频抠像 `video-matte`**（RVM）、**动效文字 `video-text-anim`**、**风格化转场**、**光效调色 `video-fx`**（含 LUT） |
| **T4（可选）** | + GPU / 代理 | `onnxruntime-gpu` 加速（`--gpu`）、更快模型下载（`bootstrap -Gpu` / `-Proxy`） |

`doctor` 会报告当前机器处于哪一层；缺层时命令会明确报错并给安装提示，**不会假装完成**。

## 目录结构

```
package.json / cordis.patch.yml / lib/index.js   插件外壳（profile bundle）
skills/image-studio/SKILL.md + reference/        美工技能（工作流/命令表/质量规范）
skills/video-studio/SKILL.md + reference/        剪辑技能（三段式工作法/特效/平台规格）
toolkit/cs.py                                    工具箱：25 个子命令
scripts/bootstrap.ps1 | .cmd                     运行时一键引导（Python + ffmpeg + 模型）
scripts/install-as-plugin.ps1 | .cmd             装成 DSH 插件（推荐）
scripts/install-into-dsh.ps1 | .cmd              技能根安装（免重启，备用）
scripts/verify-install.ps1 | .cmd                安装体检（11 项，含"是否被禁用"）
scripts/provider-selftest.mjs                    provider 契约测试（逐字段对齐宿主校验）
docs/STATUS.md                                   建设状态与实测证据台账
docs/PUBLISH.md                                  市场收录流程（已核实）
runtime/                                         独立 Python 运行时（引导时生成，勿手工改）
```

## 设计取舍

- **不注册 host 工具**：能力全部走 shell 可调用的工具链，因此不绑定任何 DSH 私有 API，任何版本的 DSH 都能用。
- **独立运行时**：不污染用户已有的 Python 环境；`-Force` 可重建。
- **junction 安装**：技能源码只有一份，改完立即生效；不便联接时用 `-Copy`。
- **一切可验收**：每个命令都支持 `--json`，`inspect` / `video-probe` 用于交付前核对；无法查看图像时导出帧交用户确认。
- **红线写进技能**：不覆盖原图、不伪造认证与功效宣称、不用未授权音乐素材。

## 已验证（本机证据见 docs/STATUS.md）

`selftest` **29/29 通过**（经 node 可移植启动器运行），其中两条是"看起来像成品、实际是废片"的闸门，见 `CHANGELOG.md`。

图片侧：抠图（RGBA、主体占比、边缘过渡宽度量化）、局部重绘改图、中英文字与描边、白底 logo 自动抠、多图层合成、2000×2000 白底主图、接触表、主色提取。
视频侧：探针、抽帧、秒切/精确裁切、fade 转场拼接（10.45s，yuv420p）、贴字、中文字幕烧入、配乐淡入淡出、智能封面选帧、9:16 导出；AI 抠像换白底（**主体存在性闸门**：修复后覆盖率 0.41，错误后端在第 20 帧被拦下）、色键路径、ASS 动效文字烧入、53 种转场枚举、风格化 glitch 转场（时长 2.52s 校验）、调色+辉光+对比帧、光泄漏（**全局偏色闸门**：Δ ≤ 20）。

关键实测数据：
- 视频抠像：默认后端 rembg 逐帧通用抠像（isnet）720×1280 **2.3 fps**；主体覆盖率 0.41（RVM 人像模型在同一素材上是 0.0000，已被闸门拦下）
- 光效偏色：teal-orange+punch+leak 组合的相对偏色增量 **+4.2…+7.2**（0.2.0 事故为 +45 以上）
- 图片抠图：`fast`→u2net 0.15s / 边缘过渡 5.28px；`best`→birefnet 5.7s(CPU) / 2.76px
- 转场：风格化预置每个约 0.4s（3s+3s 素材、0.6s 转场 → 成片 5.44s，符合 3+3−0.6）

## 已知边界（诚实声明）

- **需要 After Effects 的**：运动跟踪、3D 相机、粒子系统、复杂 roto 遮罩——ffmpeg + 现有模型做不到，技能文档已写明，不含糊替代。
- 生成式改图（换场景/换材质）**未实现**；`inpaint` 只适合小面积缺陷修复。
- 视频抠像对玻璃/纱料/快速甩动仍有边缘瑕疵；逐帧抠像在细发丝、半透明处的时域稳定性弱于专业工具。`--quality best`（birefnet）约 6 秒/帧，长片要先 `--limit` 试跑。
- 抠像与调色都有客观闸门（主体覆盖率、偏色增量），但**审美质量仍需人眼过目**：看不到图像时，验收靠导出帧/接触表交用户确认。
- 仅在 Windows 实测；macOS/Linux 代码路径已写但未验证。
