# 发布到 DSH 插件市场（按官方 contributing.md 核对过的流程）

> 一句话：**上架 = 往 [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin) 提一个 PR，只加一个文件**
> `data/plugins/<你的GitHub用户名>__dsh-creative-studio.yml`
> 该仓库的 **README 是脚本生成的，不要手工编辑**；数据源是 `data/plugins/` 下「一个插件一个 YAML」。
> DSH 市场（`dshmarket`）只是这个列表的阅读器——市场本身没有上传入口（本机已核实：其 lib 里没有任何 publish/submit 代码）。

## 一、CI 的硬门槛（逐条对照本包）

| 门槛（来自 contributing.md） | 本包状态 |
|---|---|
| 仓库 `package.json` 声明 `dsh.bundle`（**只声明 `dsh.client` 会被拒**） | ✅ 已声明 `dsh.bundle.patch` |
| 仓库根有 `cordis.patch.yml`（`insert` 行） | ✅ 已就位 |
| 真实可用的代码（非占位/纯 README） | ✅ 18 个命令、19 项端到端验收 |
| **仓库创建满 1 天**（CI 自动检查） | ⚠️ 新仓库需等 1 天——过了门槛再提 PR |
| 仓库加 `dsh-plugin` topic | ⚠️ 建仓后要在设置里加 |
| 描述属实、无营销词、句末有句号 | ✅ 见 `contrib/data-plugins/*.yml`（已按此写） |
| 分类贴合实际 | ✅ `skill`（技能包） |
| 一个 PR 最多 3 条 | ✅ 本包只 1 条 |

## 二、安装来源（决定用户怎么装）

| 方式 | 是否需要账号 | 说明 |
|---|---|---|
| **npm 发布** | 需要 npm 账号 | 官方推荐：预构建安装可免 `allowBuilds` 构建授权；市场会显示下载量 |
| **GitHub Release + tarball** | 只需 GitHub 账号 |  **不发 npm 就用这个**；条目里加 `tarball:` 字段（必须是 GitHub Release 上的 https `.tgz`） |
| 纯源码安装（`github:owner/repo`） | 只需 GitHub 账号 | 可以，但没有 tarball 时的体验略差 |

> ⚠️ **tarball 资产名不要带版本号**：`latest/download/` 只在请求时解析 `latest`，文件名按字面取。
> 用 `dsh-creative-studio.tgz` 这种不带版本的名字；若要带版本号，就把 URL 钉到具体 tag（`releases/download/v0.1.0/...`）。

## 三、peerDependencies 的预发布陷阱（已实测并已修正）

contributing.md 特别警告：**不带显式预发布分支的 peer 范围会静默排除 DSH 的所有预发布构建**。
本机实测（semver 直接验证）：

| peer 范围 | 0.1.1-rc.2 | **0.1.2-rc.1（本机宿主版本）** | 0.1.2 | 0.2.0-rc.1 |
|---|---|---|---|---|
| ❌ 旧：`^0.1.1-rc.2` | OK | **FAIL** | OK | FAIL |
| ✅ 新：`>=0.1.1-rc.2 <0.1.2 \|\| >=0.1.2-rc.1 <0.2.0-0` | OK | **OK** | OK | FAIL |

**旧写法会让所有跑 0.1.2-rc.1 的用户装不上**（ERESOLVE）。`package.json` 已改为新写法，`engines.dsh` 同步。

## 四、提交步骤

### 若走 GitHub tarball 路线（无 npm 账号）

1. **建公开仓库** `dsh-creative-studio`，把包内容推上去（`runtime/`、`tests/out/`、`dist/` 已被 `.gitignore` 排除）
2. **发一个 Release**，上传资产 `dsh-creative-studio.tgz`（版本号不要写进名字；本地已生成：`dist/dsh-creative-studio.tgz`）
3. 仓库 **Settings → Topics** 加 `dsh-plugin`
4. （可选）在仓库根放 `screenshots.json`（参考 `contrib/screenshots.json.example`），图片放 `assets/`
5. **等满 1 天**，然后到 awesome-dsh-plugin 提 PR：新增一个文件
   `data/plugins/<你的用户名>__dsh-creative-studio.yml`
   内容照抄 `contrib/data-plugins/REPLACE_WITH_OWNER__dsh-creative-studio.yml`（把 `REPLACE_WITH_OWNER` 三处替换掉）
6. 合并后网站自动重建，市场里即可搜到

### 若走 npm 路线

1. 先把 4 处占位符替换成真实仓库信息（见 `package.json` 的 `repository`/`homepage`/`bugs`/`author`）
2. `pnpm publish`（本机已有 pnpm；需要你的 npm 登录态）
3. 其余同上一节第 2-6 步；此时条目**不需要** `tarball:` 字段（npm 会被自动关联，手写 `npm:` 反而会被校验拒绝）

## 五、评审会看什么（据 contributing.md）

1. 代码是否与描述一致——**描述里的数字与命令都会被逐个核对**，夸大是打回的头号原因
2. 分类是否合理（不贴切由维护者直接改，不会打回）
3. 是否真实可用而非空壳
4. 是否与现有条目重复
5. 源码是否有可疑之处（混淆、凭据外传、异常安装行为）
6. PR 是否动了无关条目
7. 不能是"只依赖别人的聚合包"
8. 聚合包的依赖必须指向原作者上游

## 六、本包上架前的自查清单

- [x] `dsh.bundle` + `cordis.patch.yml`
- [x] `require()` 可加载（无顶层 await）、provider 契约合规（含 `rank`）
- [x] 端到端 19/19 验收
- [x] peer 范围已避开预发布陷阱（实测）
- [x] `files` + `.npmignore` + `.gitignore` 干净（打包 61.7 KB，无运行时/缓存）
- [x] `LICENSE`（MIT）
- [x] 条目 YAML 模板（中英双语描述、category=skill）
- [ ] `package.json` 的 `repository`/`homepage`/`bugs`/`author` 占位符替换
- [ ] 建公开仓库 + 发 Release tarball + 加 `dsh-plugin` topic
- [ ] 等满 1 天后提 PR
- [ ] （可选）截图 1-3 张

## 七、我能代劳的部分

只要机器上有可用的授权，我可以把上面第 1-5 步全部跑完（建仓、推代码、发 Release、加 topic、生成 PR 分支）。
当前这台机器**没有 git、gh、npm，也没有任何 GitHub/npm 令牌或 SSH 密钥**，所以需要你先做一次授权，二选一：

| 方式 | 你做什么 | 之后我做什么 |
|---|---|---|
| A. 装工具 + 浏览器登录 | `winget install Git.Git GitHub.cli` 然后 `gh auth login`（浏览器点一下） | 用你的登录态建仓、推代码、发 Release、开 PR |
| B. 给令牌 | 把一个有 `repo` 权限的 GitHub PAT 写进工作区文件（**别贴在聊天里**） | 用 GitHub API 建仓、提交文件、发 Release、开 PR |

> 安全提示：方式 B 的令牌建议用完即撤；我只会把它用于这一次发布，不写进任何包文件。
