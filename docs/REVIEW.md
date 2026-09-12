# 同类技能对比与自我剖析（2026-09-12）

> 目的：把 dsh-creative-studio 放到同类方案里横向比，找出**真实差距**并排优先级。
> 结论先说：**工程骨架与可移植性达到同类水准，能力覆盖面偏窄**——最大缺口是"生成式改图"，
> 其次是抠图模型选型与技能文档的渐进披露结构。

## 一、对比基准

| 对比对象 | 类型 | 关键做法 | 我的差异 |
|---|---|---|---|
| Anthropic Agent Skills（官方 PDF/DOCX/PPTX skills） | 规范与最佳实践 | 三层渐进披露：frontmatter 元数据 → SKILL.md 主体 → 按需加载的 `reference.md` / `forms.md`；代码既当工具又当文档；强调"先评测再写技能" | 我用的是单文件 SKILL.md（7.7KB/9.4KB），**未做第三层拆分**；命令级验收已有，任务级评测缺 |
| agentskills.io 开放标准 / agentskills 规范仓 | 跨平台标准 | 目录 + SKILL.md + 捆绑资源；强调可审计（依赖与网络访问要能被审查） | 结构符合；但**依赖未锁版本、未提供离线包、网络访问点未集中说明** |
| DSH 自带 `dsh-univer-office` | 同宿主插件 | 插件在 `lib` 里 `ctx.skills.registerProvider()`，技能随 npm 包分发、支持 worktree 与宿主工具 | 我走"用户级技能根 + junction"，**跨版本更稳但不随 npm 包自动分发**（保留 package.json，未来可切 bundle 路径） |
| DSH `dsh-ppt` | 同宿主技能包 | `skills/` + `lib/` + 许可与第三方声明（THIRD_PARTY_NOTICES） | 我**缺第三方许可声明与依赖清单** |
| 社区 ffmpeg 类技能（如 [ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill)、[ffhub-ffmpeg](https://github.com/ffhub-io/ffhub-ffmpeg)） | 同类视频技能 | 多为 ffmpeg 命令封装/云转码 | 我的覆盖更全（转场归一化、字幕烧入、智能封面、平台规格），但**缺自动字幕、响度标准化、批量队列** |
| 生产级抠图方案对比（[BiRefNet vs rembg vs U2Net](https://dev.to/om_prakash_3311f8a4576605/birefnet-vs-rembg-vs-u2net-which-background-removal-model-actually-works-in-production-d2f)） | 模型选型依据 | 500 张真实商品图：U2Net 毛发 71%/玻璃 48%；rembg-ISNet 81%/59%；**BiRefNet 94%/78%** | 我默认 `u2net`——**用最弱的一档做默认**，属选型失误 |
| 生成式编辑模型（[Qwen-Image-Edit / FLUX.1 Kontext / OmniGen2](https://www.spheron.network/blog/deploy-open-source-ai-image-editing-models-gpu-cloud-2026/)） | 能力现状 | 指令式改图：换背景、去物体、换材质、扩图；16GB 显存可跑量化版 | **完全没有**——用户原始需求里明确要"改图"，我目前只能"拆层重拼" |

## 二、做得对的地方（有实测证据）

1. **不靠想象、真操作文件**：所有能力是可执行命令，交付前用 `inspect` / `video-probe` 复核（18/18 自动化验收可复现）。
2. **能力分层 + 诚实降级**：T0/T1/T2 自动识别（`doctor`），缺依赖时明确报错并给安装提示，不假装完成——这条纪律写进了两份技能文档。
3. **可移植性做透**：内置运行时 + 内置 ffmpeg（`imageio-ffmpeg`）+ 三条包根定位路径（环境变量/位置标记/junction 反推）+ 一键引导（uv 自动获取、镜像、代理）。同类开源技能多数要求用户自己装 ffmpeg/Python 环境。
4. **踩过的坑写成纪律**：xfade 时基归一化、yuv420p 强制、Windows 盘符冒号解析、PowerShell 5.1 编码——都进代码或文档，而不是留在"我这次记得"。
5. **验收驱动开发**：`selftest` 一上线就抓出 `compose` 在 Windows 路径下的真 bug（盘符冒号把 `path:x:y:scale` 切碎），并被我修复验证。

## 三、差距与改进（按优先级）

### P0 — 不补就是能力缺口

**1. 生成式改图缺失（最严重）**
- 现状：只能 `matte` 抠出主体 + `compose` 重新摆放；无法"去掉画面里的杂物""把产品换到新场景""按指令改材质"。
- 改法：分两步走，且都要保留 CPU 降级——
  - **T3-a 局部重绘（CPU 可跑）**：接入 LaMa inpainting ONNX（约 200MB），新增 `inpaint <img> --mask <mask.png|--box x,y,w,h>`，用于去水印/去杂物/补背景；
  - **T3-b 指令式编辑（GPU）**：本机 RTX 5070 Ti 16GB 可跑 FLUX.1 Kontext / Qwen-Image-Edit 量化版，做成 `edit --instruction "..."`（可选安装，缺 GPU 时明确报不可用，并给 API 兜底入口）。
- 依据：用户原始需求明确包含"改图"；同类方案（[Qwen-Image-Edit 等](https://www.spheron.network/blog/deploy-open-source-ai-image-editing-models-gpu-cloud-2026/)）已把指令式改图当作基线能力。

**2. 抠图默认模型选错档**
- 现状：默认 `u2net`（毛发 71% / 玻璃 48%）。
- 改法：默认改 `isnet-general-use`，新增 `--quality auto|fast|best`：auto 先跑 `isnet`，再用边缘 holo 检测（沿 alpha 边界的梯度方差 + 半透明像素比例）判断是否需要重跑 `birefnet-general`；`birefnet` 首次需下载（走 `HF_ENDPOINT` 镜像）。同时把"边缘质检"作为 `inspect` 的一个字段输出。
- 依据：[生产对比](https://dev.to/om_prakash_3311f8a4576605/birefnet-vs-rembg-vs-u2net-which-background-removal-model-actually-works-in-production-d2f) 显示 BiRefNet 毛发 94%、玻璃 78%，把最弱档当默认等于主动降低质量。

**3. 技能文档未做渐进披露**
- 现状：SKILL.md 单文件 7.7KB / 9.4KB，首屏即全量加载。
- 改法：按 Anthropic 三层结构拆——
  - `SKILL.md` 保留：何时用、包根定位、doctor/selftest、命令速查（一行一条）、核心工作流 2 条、验收与红线；
  - `reference/commands.md`（全参数）、`reference/platform-specs.md`（平台规格与安全区）、`reference/recipes.md`（电商主图/A+/短视频模板）、`reference/troubleshooting.md`。
- 依据：[Anthropic 官方指南](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) 把渐进披露列为核心设计原则，第三层"只在需要时读"。

### P1 — 明显提升可用性

4. **图像增强缺失**：无超分（Real-ESRGAN/SUPIR ONNX，GPU 更佳）、无批量水印、无自动白平衡/锐化预设。→ 新增 `enhance --upscale 2 --auto-tone`、`watermark --text/--logo --tile`。
5. **视频缺三件常用件**：自动字幕（faster-whisper，可选层）、**响度标准化**（社交平台按 -14 LUFS 更稳）、**图片转视频（Ken Burns）**——最后一项对"只有产品照也能出短视频"的场景价值最高。
6. **依赖与供应链透明度**：加 `requirements.lock`（锁版本）、`THIRD_PARTY_NOTICES.md`（Pillow/rembg/onnxruntime/imageio-ffmpeg 许可）、集中说明网络访问点（GitHub releases 取 uv 与模型、PyPI 取包），并提供 `make-offline-bundle.ps1`（wheels + 模型打包）供内网机器。
7. **安装自愈**：包目录移动后 junction 断链 → `install-into-dsh.ps1 -Verify` 检测并 `-Repair` 重建；同时校验 `DSH_CREATIVE_STUDIO_HOME` 是否漂移。
8. **跨平台未验证**：代码路径已兼容 POSIX，但只在 Windows 实测。→ README 明确标注，并在 `doctor` 里输出平台与已知限制。

### P2 — 锦上添花

9. **电商模板化**：A+ 图文版式、卖点信息图、尺寸对比图、前后对比图的版式模板（`layout` 命令），把"排版规范"从文档变成可执行模板。
10. **字体可移植**：当前依赖系统字体（换机器可能缺中文字体）→ 打包一份开源 CJK 字体（如 Noto Sans SC）并优先使用。
11. **色彩与格式**：ICC 配置保留、AVIF/WebP 输出策略、印刷 CMYK 校验。
12. **任务级评测**：`selftest` 只证明"命令能跑"；应加 `tests/eval-tasks.md` 的评分表（例：Amazon 主图合规评分、短视频节奏评分），按 Anthropic"先评测"的建议反向驱动改进。

## 四、本轮已落地的快修与 P0 改进

| 项 | 状态 | 说明 |
|---|---|---|
| EXIF 方向修正 | ✅ 已修 | `open_rgba` 加 `ImageOps.exif_transpose`。实测：存储 1200×800 + Orientation=6 的照片，现在正确读成 800×1200 |
| `selftest` 接入技能文档 | ✅ 已完成 | 新机器第一次使用前先跑 19 项验收；失败必须上报而不是硬交付 |
| **P0-1 改图能力** | ✅ 部分补齐 | 新增 `inpaint`：掩码/矩形/圆形区域局部重绘，去水印、灰尘、划痕、小杂物；`telea/ns` 零额外依赖，`lama-onnx` 提供模型即可启用。**大面积生成式替换（换场景/换材质）仍属 T4，未实现，已如实标注** |
| **P0-2 抠图模型选型** | ✅ 已修 | 默认改为 `--quality auto`：≤2MP 用 `birefnet-general`、大图用 `isnet-general-use`；`fast=u2net` 仅用于草稿。并把"边缘过渡宽度"做成量化指标：实测 u2net 5.28px vs birefnet 2.76px |
| **P0-3 渐进披露** | ✅ 已完成 | 两份 SKILL.md 瘦身，细节移入 `reference/commands.md`、`reference/quality.md`、`reference/platform-specs.md` |
| 依赖冲突治理 | ✅ 已处理 | `simple-lama-inpainting` 硬锁 numpy<2/pillow<10 与 rembg 冲突 → 卸载并改走 ONNX 可选路径；记录为"必须锁版本"的实证 |

## 五、下一步路线（按优先级执行）

1. **P1-生成式改图**：GPU 层接 FLUX.1 Kontext / Qwen-Image-Edit（本机 16GB 显存可跑量化版），`edit --instruction "把产品放到木桌上"`；缺 GPU 明确报不可用
2. **P1-视频三件**：图片转视频（Ken Burns，只有产品照也能出片）、响度标准化（-14 LUFS）、自动字幕（faster-whisper 可选层）
3. **P1-工程**：`requirements.lock` 锁版本 + `THIRD_PARTY_NOTICES.md` + 离线包 + `install-into-dsh.ps1 -Verify/-Repair`
4. **P2**：A+ 版式模板、CJK 字体打包、任务级评测表（审美质量需人过目，见下）
5. **跨平台**：在 macOS/Linux 实机跑一次 `selftest` 并标注结果

## 六、诚实的局限声明

- 本机只在 **Windows** 实测；macOS/Linux 路径已写但未验证。
- 运行时约 500MB（含 ffmpeg 与 onnxruntime），首次引导需联网；无网机器需要离线包（尚未提供）。
- 生成式改图**目前完全没有**；在补齐前，遇到"把产品换到新场景"这类需求必须如实说明能力边界。
- `selftest` 是命令级验收，不代表成片/成图的审美质量；视觉质量仍需导出帧/图给人过目。
