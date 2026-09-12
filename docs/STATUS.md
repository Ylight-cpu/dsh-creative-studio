# dsh-creative-studio — 建设状态（2026-09-11；发布记录更新至 2026-09-12）

## 发布状态（2026-09-12）

| 项 | 状态 | 证据 |
|---|---|---|
| 公开仓库 | ✅ | https://github.com/Ylight-cpu/dsh-creative-studio （public，main） |
| Release v0.1.0 + tarball | ✅ | 资产 `dsh-creative-studio.tgz`，63,819 B，sha256 `9ac411f8…`（与本地打包一致） |
| 条目引用的 tarball 地址 | ✅ | `.../releases/latest/download/dsh-creative-studio.tgz` 实测 HEAD 200 + 实下载 62.3 KB |
| 仓库 topic | ✅ | `dsh-plugin`、`deepseek-harness`、`skill`、`image-editing`、`video-editing`、`ffmpeg` |
| 从公开源安装（CI 检查项） | ✅ | 临时 profile 执行 `dsh plugin --profile citest add github:Ylight-cpu/dsh-creative-studio` 成功，bundles 被官方 CLI 自动纳入（临时 profile 已清理） |
| peer 范围预发布陷阱 | ✅ | semver 实测：旧 `^0.1.1-rc.2` 不匹配 `0.1.2-rc.1`（本机宿主版本），已改为显式分支范围 |
| 列表条目 PR | 🕐 待审 | https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/4908 （1 文件 +23 行）<br>仓库创建当天提交，`check-submission.mjs` 的 `MIN_AGE_DAYS = 1` 会在首轮报"0.x days old"，该检查自述会自行重跑（仓库另有 `regate.yml` 重评刚满龄条目），故 PR 说明中已注明 |

发布流程细节与两条硬门槛（`dsh.bundle`、仓库满 1 天）见 `docs/PUBLISH.md`。
npm 发布为可选项（不影响收录）：发布后 `repository` 字段需指回本仓库，市场会自动关联下载量。

## 已完成并实测通过

| 能力 | 状态 | 验证方式 |
|---|---|---|
| 插件骨架（package.json / cordis.patch.yml / lib/index.js） | ✅ | 结构对齐 dsh-univer-office 的 dsh 包规范 |
| 跨平台启动器 `scripts/run-toolkit.mjs` | ✅ | node 侧转发到 toolkit venv |
| 独立运行时 `runtime/`（Python 3.12 + pillow/numpy/rembg/onnxruntime/imageio-ffmpeg） | ✅ | `doctor` 自检；清华镜像秒装 |
| 图片体检 `inspect` | ✅ | 真实素材 739×743 输出尺寸/透明通道/主体 bbox/亮度 |
| 加文字 `text`（中英混排/描边/阴影/底块/自动换行/九宫格） | ✅ | 真实素材出图 |
| 贴 logo `logo`（九宫格/透明度/白底自动抠） | ✅ | 用 YLight 真 logo 合成 |
| 多图层合成 `compose` | ✅ | px/% 定位 + 缩放 |
| 平台规格导出 `export`（amazon-main/shopify/faire/9x16… pad·fit·crop） | ✅ | 2000×2000 白底出图 |
| 接触表 `sheet`（选片/交付预览，支持目录递归） | ✅ | 批量出图 |
| 主色提取 `palette` | ✅ | 真实素材 |
| 抠图 `matte`（rembg u2net，模型 176MB 自动下载） | ✅ | 输出 RGBA，主体占比 79% |
| 视频通览 `video-probe`（时长/分辨率/帧率/码率/音轨，无 ffprobe 时解析 ffmpeg stderr） | ✅ | 两条真实视频（横/竖版各一） |
| 视频抽帧 `video-sheet` | ✅ | 53.6s 视频抽 18 帧 |
| 视频裁切 `video-cut`（copy 秒切 + `--accurate` 精确重编码） | ✅ | 7.04s / 4.0s 两段，探针复核 |
| 视频拼接 `video-join`（copy 无损 + `--transition` 转场，含时基/帧率/像素格式/音频归一化） | ✅ | fade 拼接 7.04+4.0-0.6=10.45s，pix_fmt=yuv420p |
| 视频贴字 `video-text`（PIL 渲染透明 PNG → overlay，可限时间段） | ✅ | 568×320 视频自动取画布 + 时间窗 |
| 字幕烧入 `video-subtitle`（SRT/ASS，中文字体/描边/位置可调） | ✅ | 含中文 cue，样式串生效 |
| 配乐混音 `video-audio`（音量/淡入淡出/静音/循环 BGM） | ✅ | 原声 0.8 + fade in/out |
| 智能封面 `video-cover`（`--scan N` 按边缘能量挑最清晰帧） | ✅ | 8 帧采样，选中 10.05s（sharpness 41.5） |
| 视频规格导出 `video-export`（9:16/16:9/1:1/4:5，pad/crop，yuv420p+faststart） | ✅ | 1080×1920 竖版 |
| **技能文档** `skills/image-studio/SKILL.md`、`skills/video-studio/SKILL.md` | ✅ | frontmatter + 工作流/命令表/验收清单/红线/排错 |

## 关键环境事实

- 本机 GPU：NVIDIA RTX 5070 Ti 16GB（T2/GPU 增强尚未接入）
- 网络：PyPI（清华+官方）、GitHub、hf-mirror、modelscope 均可达；**无需代理**（Clash Verge 仅装了服务，代理端口未监听）
- 字体：微软雅黑/黑体/Arial 可用；中文输出需 `chcp 65001`（PowerShell 5.1 默认 GBK 解码）
- ffmpeg：由 `imageio-ffmpeg` 内置（v7.1 二进制），无需系统安装

## 已装进 DSH（本机实测生效）

| 项 | 状态 | 证据 |
|---|---|---|
| `scripts/bootstrap.ps1` + `.cmd` 一键引导 | ✅ | uv 探测/自动下载 → venv → 分层依赖（清华镜像）→ 模型预取 → doctor |
| `scripts/install-into-dsh.ps1` + `.cmd` 装进 DSH | ✅ | 以 junction 挂到 `<DSH_HOME>\skills\{image-studio,video-studio}` |
| 技能被发现并加载 | ✅ | **当前会话技能目录即时刷新出两个技能**；`image-studio` 加载成功，基目录解析为 `<DSH_HOME>\skills\image-studio` |
| 位置标记（解决 junction 下 `..\..` 不是包根） | ✅ | 写 `<DSH_HOME>\skills\dsh-creative-studio.location.json`（packageRoot） |
| 用户级环境变量 | ✅ | `DSH_CREATIVE_STUDIO_HOME=F:\deepseek harness\dsh-creative-studio`（User 级） |
| 三条定位路径全部实测 | ✅ | ① 环境变量 ② 位置标记 ③ junction Target 反推，均得到正确 packageRoot |
| node 可移植启动器 | ✅ | `node <pkg>\scripts\run-toolkit.mjs doctor --json` + 真实抠图均成功 |

## 2026-09-12 第 4 轮：验收套件 + 同类对比剖析

- [x] `selftest` 端到端验收（18 项，自造素材、不碰用户文件）：`node <pkg>\scripts\run-toolkit.mjs selftest` → 18/18 通过，报告 `tests/out/selftest/acceptance-report.json`
- [x] 验收套件抓出并修复真 bug：`compose` 在 Windows 下被盘符冒号切碎 → 新增 `parse_overlay_spec()` 从右往左吃坐标
- [x] `open_rgba` 加 EXIF 方向修正（实测：存储 1200×800+Orientation=6 → 正确读为 800×1200）
- [x] `selftest` 接入两份技能文档（新机器首次使用前先自检）
- [x] `docs/REVIEW.md`：结合 Anthropic Agent Skills 三层渐进披露、agentskills 规范、DSH 自带技能工程惯例、生产级抠图模型对比、生成式编辑现状，给出 P0/P1/P2 改进清单
- [ ] 下一轮落地 P0：`inpaint`（LaMa 局部重绘，CPU 可跑）+ 抠图默认模型升级（isnet/birefnet + `--quality auto`）+ 技能文档三层拆分

## 2026-09-12 第 5 轮：P0 改进落地（改图 / 模型选型 / 文档分层）

- [x] **`inpaint` 局部重绘改图**（弥补原始需求里的"改图"缺口）：`--mask` / `--box` / `--circle` + `--dilate`，后端 `telea|ns`（OpenCV，零额外依赖）+ `lama-onnx`（提供模型即可启用）
- [x] **抠图质量策略**：默认从最弱的 `u2net` 改为按 `--quality fast|auto|best` 选择 —— auto：≤2MP 用 `birefnet-general`、大图用 `isnet-general-use`。实测同一张商品图：auto 小图 → birefnet 5.68s；大图 → isnet 0.46s
- [x] **边缘质检指标重做**：原指标饱和（恒为 1.0）无判别力 → 改为 `transition_px`（边缘过渡宽度）。实测：u2net 5.28px（触发告警）、birefnet 2.76px（干净），量化验证了模型差距
- [x] **依赖冲突实战处理**：`simple-lama-inpainting` 硬锁 numpy<2/pillow<10 会破坏 rembg/opencv → 卸载（顺带省 2GB torch），改走 ONNX 可选后端；补回被误删的 scikit-image 后环境恢复（rembg 2.0.84 / cv2 4.11 / numpy 2.5.3 共存）
- [x] **技能文档渐进披露拆分**：两份 SKILL.md 瘦身为"何时用 + 定位 + 四条主要工作 + 验收 + 红线"，细节移入 `reference/`（image: commands/quality；video: commands/platform-specs）
- [x] **验收套件扩到 19 项**（新增 inpaint 检查），经 node 可移植启动器运行 → **19/19 通过**

## 2026-09-12 第 6 轮：改造为正式 DSH 插件

- [x] `lib/index.js` 重写为真实插件入口：`inject = ['skills']` + `ctx.skills.registerProvider()`，技能随包分发（不再依赖技能根 junction）
- [x] `cordis.patch.yml` 改为插件声明的 `insert` 结构（与官方 `dsh-univer-office` 同构）
- [x] `scripts/provider-selftest.mjs`：安装前的 provider 契约冒烟测试（name/description/invocation/provider/source/resourceBase/locator + 正文 frontmatter 剥离）
- [x] `scripts/install-as-plugin.ps1`（+ `.cmd`）：备份 profile → pnpm link/copy → 定点写入 `dsh.profile.bundles` → JSON 合法性校验（非法自动回滚）；支持 `-Uninstall`
- [x] 已装入本机 profile：`profiles\web\node_modules\dsh-creative-studio`（junction → 包目录），`bundles` 已含该插件，从 profile 可解析 `import('dsh-creative-studio')`
- [x] `install-into-dsh.ps1` 增加 `-Uninstall`（插件生效后清理技能根，避免同名技能来自两处）
- [x] **修复宿主校验报错 `provider "creative-studio" returned skill "image-studio" with an invalid rank`**：候选对象缺 `rank`。依据 `@deepseek-ai/dsh-skill` 的 `validateCandidate`（lib/index.js:460 要求有限数字）与 `BUNDLED_SKILL_RANK = 600`（lib/index.js:23）补上 `rank: 600`；能解析到宿主包时读取官方常量，否则用同值兜底
- [x] 冒烟测试升级为**逐字段对齐宿主校验**（name 正则 / description / invocation 两个布尔 / source / rank 有限数字 / provider 一致 / resourceBase 目录存在 / 正文非空且剥离 frontmatter），并把 600 钉为期望值——官方常量变更会被测出
- [x] 新增「按已安装路径加载」验证：经 `profiles/web/node_modules/dsh-creative-studio` junction 实际 `import` → `apply` → `list` → `get`，确认 rank/provider/resourceBase/正文全部合规
- [ ] **待用户重启 DSH** 以加载修复后的插件（运行中进程不热加载 bundle；技能根副本先保留作兜底）

## 2026-09-12 第 8 轮：真凶 = 插件被 DSH 市场禁用（本轮确证并已解除）

顶层 await 是**真缺陷**（已修），但**不是**"技能不出现"的直接原因。来源确证实验（清掉技能根副本 → 技能消失）之后，从`.dsh-market\log.ndjson` 找到直接证据：

```
{"event":"toggle","detail":"dsh-creative-studio -> off: fiber=false"}
{"event":"patch","detail":"disabled row creative-studio in profiles\web\cordis.patch.yml"}
{"event":"boot","detail":"plugin kept off: dsh-creative-studio"}   ← 此后每次启动都跳过
```

`.dsh-market\state.json` 亦为 `{"disabled":["dsh-creative-studio"], ...}`。

**机制**：DSH 市场的插件健康检查在插件首次激活失败（就是那次 `invalid rank`）后将其拉黑，方法是往 **profile 自己的 patch 层**写：

```yaml
- id: creative-studio
  disabled: true
```

而 profile patch 在**所有 bundle 层之后**应用 → 该行覆盖插件自身的 insert → 每次启动都被跳过。这解释了为什么"登记 OK、解析 OK、契约 OK，技能就是不出现"。

**处理**：
- 删除 `profiles\web\cordis.patch.yml` 中的禁用行（复原为 `[]`，已备份）
- 清空 `.dsh-market\state.json` 的 `disabled` 列表
- `verify-install.ps1` 新增两项检查：`profile patch 未禁用插件`、`市场未标记禁用`（原脚本完全没查这两处，故给出假绿灯）
- `运行中 DSH 已加载最新代码` 的时间比较范围扩展到**启动时读取的配置**（cordis.patch.yml / profile patch / 市场状态），否则"改了禁用状态但没重启"会被误判为已生效

**教训汇总**（三轮踩坑的共同点：验证方式与真实机制不一致）：
1. 契约测试用 `import()`，宿主用 `require()` → 改了加载方式却没测
2. 只验证"装上了"，没验证"没被禁用" → 配置层的否决权被忽略
3. 只比较代码文件时间，没比较启动时读取的配置 → 假绿灯

## 2026-09-12 第 7 轮：插件未生效的一个真缺陷（顶层 await）

（保留记录）宿主用 CJS 兼容路径（`require()`）加载 profile bundle；我在修 `rank` 时引入的顶层 `await import()` 使模块成为 async ESM 图，`require` 会 `ERR_REQUIRE_ASYNC_MODULE` 而静默失败。已改为静态导入 + `list()` 内惰性解析。

**现象**：插件已登记、可解析、契约自测通过，但把技能根副本清掉后，技能从目录里消失 → 说明**技能一直是技能根提供的，插件根本没注册上**。

**真因（已用实验证明）**：宿主用 **CJS 兼容路径（`require()`）** 加载 profile bundle。我在修 `rank` 时顺手在入口写了顶层 `await import('@deepseek-ai/dsh-skill')`，模块因此变成 async ESM 图：

| 加载方式 | 含顶层 await（旧） | 去掉顶层 await（现） | 官方 dsh-univer-office |
|---|---|---|---|
| `require()`（宿主方式） | ❌ `ERR_REQUIRE_ASYNC_MODULE` | ✅ 正常 | ✅ 正常 |
| `import()`（我此前测试用的方式） | ✅ 正常 | ✅ 正常 | ✅ 正常 |

**我的方法错误**：之前的自测全部使用 `import()`，与宿主的 `require()` 不一致，于是"一路绿灯"却实际加载失败。教训：**验证必须复刻宿主的加载方式**。

**修复**：
- `lib/index.js` 去掉顶层 await，改为静态导入 + 在 `list()` 内异步惰性解析官方常量（`resolveRank()`，失败回落 600）
- `scripts/verify-install.ps1` 的加载检查改为 `createRequire` + `require()`，与宿主一致（这条检查若早存在，本问题会在第一次安装时就被拦住）
- 新增 `scripts/verify-install.cmd`（双击）与 `uninstall-plugin.cmd`、`uninstall-skills-root.cmd`

**如何确证"技能到底由谁提供"**（唯一可靠的判定）：
1. 跑 `verify-install.cmd` → 看 `插件按宿主方式 require() 加载` 与 `运行中 DSH 已加载最新代码` 两项
2. 清掉技能根副本（`uninstall-skills-root.cmd`），刷新后技能若仍在 → 插件在供；若消失 → 仍是技能根在供（可秒级恢复：重跑 `install-into-dsh.ps1`）

**当前状态**：插件代码已修好并通过 require 加载自测；运行中的 DSH 启动时间早于本次修改 → **需再重启一次**。技能眼下由技能根副本提供，不受影响。

## 尚未完成（后续轮次）

1. P1：生成式改图（FLUX Kontext / Qwen-Image-Edit，GPU 层）、超分、批量水印、图片转视频（Ken Burns）、响度标准化、自动字幕
2. P1：依赖锁版本 + `THIRD_PARTY_NOTICES` + 离线包（wheels+模型）
3. P2：A+ 版式模板、CJK 字体打包、任务级评测表；macOS/Linux 实机验证

## 快速用法

```powershell
chcp 65001 > $null; [Console]::OutputEncoding = [Text.Encoding]::UTF8   # 中文不乱码
$cs = 'F:\deepseek harness\dsh-creative-studio\runtime\Scripts\python.exe'
$t  = 'F:\deepseek harness\dsh-creative-studio\toolkit\cs.py'
& $cs $t doctor --json
& $cs $t matte 产品图.png --bg white --out 白底图.png --json
& $cs $t text  产品图.png --text "标题`nSubtitle" --position bc --color white --stroke '#1F6E43' --stroke-width 6 --json
& $cs $t logo  产品图.png --logo logo.png --position br --width-ratio 0.16 --key-white --json
& $cs $t export 产品图.png --preset amazon-main --json
& $cs $t video-probe 素材.mp4 --json
```
