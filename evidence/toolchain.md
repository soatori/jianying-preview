# 工具链与供应链记录（toolchain）

记录时间：2026-10-15　｜　里程碑：M1　｜　前置授权见 [scope.md](scope.md)

## 1. 第三方工具

| 工具 | 来源 | 版本 / commit | License | 用途 | 使用方式 |
|---|---|---|---|---|---|
| REA (Reverse Engineer Anything) | `github.com/morluto/rea`（官方；README 明确警告仿冒仓库） | clone `c61a24b`（`--depth 1`）；npm 包 `rea-agents@6.5.0` | MIT | JS 静态分析、SQLite 只读快照检查，**2026-10-21 起另用其 Ghidra provider 做原生只读静态取证**（scope §1.1） | `temp/vendor/rea`；执行走 `npx -y rea-agents@6.5.0 <cmd>`（**版本钉死，不用 `@latest`**，保证可复现）；原生侧走 `scripts/rea_session.py` 的 MCP stdio 会话 |
| Ghidra | `github.com/NationalSecurityAgency/ghidra` release 12.1.4 PUBLIC（zip 由**用户浏览器**下载，agent 校验 sha256 后解压） | `ghidra_12.1.4_PUBLIC_20260921.zip` 569,649,598 B，sha256 `ddac49f9…87d2d4db`（GitHub release 资产 `digest` 官方口径） | Apache-2.0 | 反汇编/反编译引擎本身（**只读静态**，由 REA 编排；不加载、不执行、不修改目标） | `temp/vendor/ghidra_12.1.4_PUBLIC`；`analyzeHeadless.bat` 经 REA provider 调用，heap 预算显式设定 |
| reverse-skill | `github.com/zhaoxuya520/reverse-skill` | clone `cab634b`（`--depth 1`） | MIT | 方法论与证据纪律（路由、Evidence→Finding→Path、scope 门禁） | `temp/vendor/reverse-skill`；**只读，未执行其任何脚本** |
| `pixi.js` | npm `pixi.js@8`（registry 实测可达） | **8.22.0**（12 个包、`node_modules` 89 MB） | MIT | WebCodecs 帧的多层合成基底（路线 A 的合成层；S3/S4 的自定义 blend shader 靠它） | `npm i --prefix temp/px-probe pixi.js@8`，ESM 经 `media_server.py` 的 `probe` 白名单根从 `/probe/node_modules/…` 直接解析，**不装 vite/build 链** |
| `mediabunny` | npm `mediabunny`（`gh api` 2026-10-21 复测 7,343★、推送 2026-10-20） | **1.62.0**；`dist/bundles/mediabunny.mjs` 1,483 KB、sha256 前缀 `3f772842de4befed`；`dist.integrity` = `sha512-D8E8BDxjCyqyrGj074jLRQNgilDW5izJu8o9pg7THMYMIZBL1Fao5hOtdDPDfA+nSnk68tMa8IaCJmz8hSpJpw==` | **MPL-2.0**（文件级 copyleft，`base-selection.md` 已接受） | 解封装 + sample table/关键帧索引 + 取数调度（路线 A 的解码底座；F-054 用它实测 seek） | `npm i --prefix temp/px-probe mediabunny@1.62.0`，**探针期只进 `temp/px-probe/node_modules`，不进产品依赖清单**；单文件 ESM bundle 由 `probe` 根直供。取数形态要记牢：`UrlSource` 发**开区间** `bytes=pos-`（64 MiB LRU、parallelism 2），闭区间精确取块得走 `CustomSource{getSize,read(start,end)}`（默认缓存 8 MiB） |
| `OpenCut-app/OpenCut` | GitHub 官方仓（≈95.4k★，2026-10-20） | clone HEAD `e668010`（2026-09-24，`--depth 1 --single-branch`，1.4 MB） | MIT | **只读参考实现**：高星开源剪辑器的仓库结构与「自建并 pin 各平台 FFmpeg」做法（`.github/workflows/media-deps.yml`） | `temp/vendor/opencut`；**不执行、不作依赖**——main 是重写骨架（`Cargo.toml` 里 `crates/*` 被注释掉、`apps/web` 无任何渲染/解码依赖），可抄的只有架构与依赖策略 |

npm 完整性（`registry.npmjs.org/rea-agents/6.5.0`）：

```
dist.integrity: sha512-C6BG7LyrAdR74mSjertM6PrxJkcNZ2bfQNOJornPo9erDEp2tyPRVYPnV5Yodr+1RqewCQla68WulXlVnveD+A==
dist.tarball:   https://registry.npmjs.org/rea-agents/-/rea-agents-6.5.0.tgz
dependencies:   39
```

clone 体积：`rea` 68 MB（3886 文件）、`reverse-skill` 14 MB。两者均**未**全局安装、**未** fork、**未**修改。

### REA 复跑记录（2026-10-20，F-047）

```bash
npx -y rea-agents@6.5.0 providers
npx -y rea-agents@6.5.0 analyze-javascript-application "<canvas_agent>" --artifact-format directory \
  --source-path runtime/app-server.mjs --max-heap-mb 6144 --analysis-timeout-ms 600000 --json
```

- 默认 `--max-heap-mb 1024` 在 9.2 MB 的 `app-server.mjs` 上**worker 堆耗尽**（`parsed_javascript_files:1`、`modules:0`、`visited_ast_nodes:35,156`）；
  提到 6144 MiB 才解析完（`visited_ast_nodes:2,163,421`、`findings:3,426`、应用图 1,229 节点 / 4,391 边），
  但**语义关系被父进程结果预算丢掉**（`coverage.status=partial`、`truncated=true`、`relations:0`）。两道墙缺一不可，属于工具固有上限，不是用法问题。
- `rea providers` 实测本机可用 provider 只有 `rea-artifact-graph`、`rea-dotnet-static`、`sqlite`；
  **native 分析（Ghidra/Hopper/IDA）全部未配置**，且 `objdump`/`readelf`/`nm`/`strings`/`rizin` 在本机与 Git for Windows 里都不存在、`java` 不在 PATH。
  ⇒ `videoeditor.dll` 的 `xmldraft/v1` → draft JSON 映射**读不到**，这是本轮之后仍然读不到的唯一原生通道。
- 于是 10-15 的判断（「REA 对草稿字段清点无产出」）这次有了量化理由与边界：**REA 只用它给清单、模块图与可复现摘要，字段级事实仍由自研脚本产出**。
  本轮的三方核对就是自研脚本：`temp/rea/diff_xmldraft_attrs.py`、`temp/rea/three_way_check.py` → `temp/rea/xmldraft_attrs_3way.csv`。
- 证据产物（`temp/rea/`，不进 git）：`providers-1020.txt` 38 KB、`canvas_agent_runtime.json` 42 MB（默认堆、partial）、`app_server_h6144.json` 18.5 MB、
  `app_server_draft_regions.txt` 56 KB（按 marker 抽出的代码窗口，F-047 的源码见证）。

### REA 复跑记录（2026-10-21，F-049）

**新发现：F-047 说的「语义关系被父进程结果预算丢掉」其实有可调的 flag**，当时没查 `--help`：

```bash
npx -y rea-agents@6.5.0 analyze-javascript-application --help
```

- `--max-semantic-nodes <number>`：整个应用保留的语义节点上限，**默认 100,000**；
  `--max-semantic-nodes-per-file <number>`：单文件上限，**默认 20,000**（help 原话：
  「Worker heap and parent heap admission remain enforced」——即这两个 flag 之外，worker 堆与父进程准入仍然封顶）。
  F-047 的 `relations:0` 很可能就是撞在 per-file 20,000 这一档（`visited_ast_nodes` 2,163,421 ≫ 20,000）。
  **本轮没有重跑大堆验证**：字段级事实已由自研脚本拿到，重跑只为复核工具边界，不产出新事实。
- 全局输出侧还有 `--filter-output <keys>`、`--format <toon|json|yaml|md|jsonl>`、`--token-limit`、`--token-offset`、
  `--token-count`、`--schema`、`--llms/--llms-full` ⇒ **本机没有 `jq` 也不必等 REA 吐 18 MB 原始 JSON**，
  用 `--filter-output` + `--token-limit` 直接在 CLI 侧投影。F-047 落 42 MB / 18.5 MB 两个大文件是因为默认全量输出。

**本轮实际执行的动作**（全部白名单内、只读）：

- 未跑 REA。原因：F-047 已经量化了 `app-server.mjs` 的两道墙，且这轮需要的不是模块图而是**具体常数与字段表**，
  marker 抽取（`temp/rea/js_markers.py`）与专用解析器（`scripts/js_model_extract.py`）直接给答案。
- `--help` 两次（`analyze-web-bundle`、`analyze-javascript-application`）——只是读 usage，不触碰目标。

**新增「明确不执行」条目**：

- **`analyze-web-bundle` 不用**。它的参数是 `<endpoint> <targetId>`（loopback CDP HTTP 端点或浏览器 WebSocket），
  即它**必须先有一个活的浏览器会话**再抓该页面的 bundle。对 `canvas_agent/app/` 这条路意味着要把剪映自带的 web 面加载起来，
  而页面会按它自己的 origin 发起请求 ⇒ 与 `scope.md` §2 的 `local-only, no-target-act` 冲突（我们不允许让被测对象自己发网络请求）。
  本轮改用 `analyze-javascript-application` / 自研 marker 抽取**静态**读磁盘上的 chunk，等价且零副作用。
- 仍然不跑 `rea setup`、不注册 MCP、不装 native provider、不碰 `videoeditor.dll` 的原生分析。

**`compare-*` 一族在本机不可用（2026-10-21，F-051）**：`compare-application-versions` / `compare-bundles` 需要两个都真实存在的应用目录，而安装根下 13 个版本名目录里 **12 个是更新载荷**（37~77 文件、无 `Resources/`、无 exe），只有 `11.1.0.14287 - 副本` 与 `11.6.0.14552` 是完整安装 ⇒ 可对比的只有**一对**，且这一对用 `ls`/`diff`/`sha256sum` 手工比更快（本轮就是这么拿到 `Resources/` 差集与 `MixMode.json` 逐字节相同两条结论的）。所以 `compare-*` 未执行，不是失败。

### 靶面 A 清点（2026-10-21，F-049）

| 项 | 值 |
|---|---|
| `app/static/js/` | **76 个 `.js`、16 MB**（顶层 43 + `async/` 33），另有 `.LICENSE.txt`；任务书里写的「50 个 chunk」不对 |
| 最大件 | `initial-vendors-4f3a8f70.4d3131ce.js` 2,164,220 B |
| 关键件 | `ai-creation~10.0176e5c4.js`（220,739 B，**190 条**模型字段表）、`ai-creation~11.aa2812ea.js`（288,169 B，**154 条**）、`ai-creation~7.bba738bb.js`（288,414 B，草稿 canvas_config 修复层）、`ai-creation~12.a54b7e83.js`（209,718 B，`render_index` 14 次）、`async/2142.1b79d57f.js`（253,274 B） |
| 产出 | `scripts/js_model_extract.py` → `docs/evidence/tables/js_model_keys.csv`（132 条去重记录、880 个键、逐类默认值）+ `temp/rea/js_model_diff.json`（对语料键集 981 个的差：模型独有 303 / 语料独有 404） |
| 内存 | 未起 REA worker、未起服务；抽取脚本是单遍正则 + 括号配平，峰值 < 300 MB（远低于 2 GB 硬上限） |

### 原生只读静态逆向就位（Ghidra provider，2026-10-21/22，F-055）

**这一节推翻了本文件先前两次的禁令**（F-047 的「native 分析全部未配置」描述 + F-049 的「不装 Ghidra / JDK」动作禁令）。
变更依据是 `scope.md` §1.1（2026-10-21 用户扩面：**只读静态、仅限结构与格式取证**），不是工具链自己变了。

| 件 | 实测 |
|---|---|
| Ghidra | `ghidra_12.1.4_PUBLIC_20260921.zip`，**569,649,598 B**，sha256 `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db`（摘要取自 `api.github.com` 该 release 资产的 `digest`，落盘前后逐字节比对一致）；解压 `temp/vendor/ghidra_12.1.4_PUBLIC`（6,695 条目、未压缩 0.84 GiB） |
| 取件路径 | 本机直连 GitHub 资产域不可用（单连接 25 KB/s、4 路并发 Range 各 20 s **0 字节**、`gh release download` 6 分钟 1.3 MiB）⇒ **zip 由用户浏览器下载**，agent 只做校验与解压 |
| Java 区间 | `application.properties`：`application.version=12.1.4`、`application.java.min=21`、**`max=`（空＝无上限）**、`compiler=21` |
| JDK | `<DRIVE_D>/Program Files\Java\jdk-21.0.12.1`，`IMPLEMENTOR = Oracle Corporation`（**不是 Temurin**——先前的建议与实际安装不符，按实测记），x86_64 完整 JDK（含 `javac`/`jmods`） |
| 环境变量 | 只写**用户级** `HKCU\Environment`：`JAVA_HOME`、`GHIDRA_INSTALL_DIR` 两条；**未改 `Path`、未改 HKLM、未跑 `rea setup`、未注册 MCP** |
| `rea doctor --json` | `healthy:false`，但**九项 ghidra 检查全绿**（`native_decompiler → decompile.exe reports pe x86_64, matches win32/x64`、`java → accepted a 64-bit full JDK 21 or newer`、`native_authority → private DACL + reparse-safe handle, local NTFS only`），`providerInspections[ghidra] = configured/available: true`；红灯只有未装的 hopper/IDA/JADX 与五个 MCP 注册项 `config_drift`（**§5 故意不做**，不是故障）。doctor 顺带列出 `rea setup` 会改写的文件（含 `<HOME>\.qoder-cn\settings.json`），佐证「不跑 setup」该留 |

**四次活会话的执行账**（`scripts/rea_session.py` 走 MCP stdio：`open_binary` → N 次 `tools/call` → `close_binary`）：

| 会话 | 步数 | 全量 auto-analysis | 之后单步 | 拿到 |
|---|---|---|---|---|
| 1 `videoeditor.dll` | 27 | **3,101.5 s**（在 `binary_overview` 里付） | 搜索 **0.0–0.1 s** | `draft_store` 771 函数框架图、段表与自研 PE 解析逐段吻合、快照 507,197 B |
| 2 深挖 | 87（69 档案 + 16 xrefs） | **2,976.1 s**（在**第一个** `analyze_function` 里付） | 档案 0.6–3.6 s、xrefs 0.0 s | 556 个字段名引用点、源码树路径泄露 |
| 3 定点伪代码 | 分页取 | **2,976.1 → 2,632.6 s**（第三次仍要付） | 档案 3.5–6.7 s | `ReadDraftMetaJsonMaterials` 全量 47,236 units / 24 页 |
| 4 函数表+字符串表 | 5 | **2,632.6 s** | 导出 0.9 s | `export_evidence_bundle` → `bundle-tables.json` 78,572,639 B（116,637 函数行 + 124,028 字符串行） |

- **摊平成立但只有「一次会话问完」才成立**：分析费每次都付（**四次共 11,684 s ≈ 3.24 小时**），付完后的查询几乎免费。
  反向也证伪了「靠快照跳过分析」：`snapshot` 是 **cached observations, not a provider database**（`temp/vendor/rea/docs/cli.md:200-206`），
  retained evidence **只在会话内有效**（实测 `evidence_integrity_mismatch`），取消活动请求会**销毁临时库**（`native-investigation.md:77`），
  provider socket **只在默认分析完成后**暴露（`ghidra-provider.md:38`）。
  ⇒ 纪律：**先离线榨干（PE 头/RTTI/字面量/导出表，零分析费）→ 再一次会话批量取证 → 把地址→函数映射落成离线件复用**
  （已落 `temp/rea-native/procedures.tsv` 115,800 行，之后字段引用点→函数不再花 Ghidra 时间）。
- **内存**：`GHIDRA_HEADLESS_MAXMEM` 显式设预算（会话用 4 G heap），冒烟先小后大；`scope.md` §4 那条 2 GB 上限是**给预览服务/探针**的，
  不套在 Ghidra headless 上（§1.1 明文）。
- **产物纪律**：伪代码/JSON 只落 `temp/rea-native/`（不入库、不分发），docs 只留结构与格式结论。
  **未做**：算法还原、密钥提取、修改/patch/hook、附加调试器、加载或执行 DLL。
- **`rea-agents` 不升版**：上游已有 6.7.0，本轮**继续钉 6.5.0**。升版要重新取包 sha256/`dist.integrity` 并重跑冒烟，
  而四次会话的产出没有任何一步依赖 6.6/6.7 的新行为；`temp/vendor/rea` 的 clone commit 同理钉在 `c61a24b`。



### 明确不执行的动作

- `npx rea-agents setup` / `rea setup`——会改 agent 与 MCP 配置（REA 自己的 AGENTS.md 也要求 setup 先展示计划并获批）。
- `reverse-skill` 的 `master-route.ps1`、`case-init.ps1`、`refresh-tool-index.ps1`、`bootstrap-reverse.ps1`、`smoke.ps1`——其 AGENTS.md 规定「读仓库不等于授权执行」，且 bootstrap 会经 winget 装 Node、注册 MCP。本项目改为**读路由表选路**（结论见 `findings.md` F-002），不执行任何脚本。
- 任何 `install.sh`。
- **反汇编/反编译的围栏（2026-10-22 就地更正）**：本文件先前写「Ghidra/IDA/Hopper/Binary Ninja 一律不配置、不调用」
  与「不装 Ghidra / JDK / objdump / rizin」——这两条已被 `scope.md` §1.1（2026-10-21 用户扩面）**部分废止**：
  Ghidra 12.1.4 + JDK 21 已就位并用了四次（见上一节），**只读静态、仅限结构与格式取证**。
  IDA / Hopper / Binary Ninja / JADX 仍未装、不调用；objdump/rizin 本机不存在。
  **仍然禁止**：加密算法还原与密钥提取的任何产物、修改/patch/hook/inject DLL、附加调试器与断点（动态面）、
  以及把伪代码或产物分发出去（伪代码只留 `temp/`）。
  「XML→JSON 别名表对本项目无用」这条判断不变——我们不经 XML 层。

## 2. 本机运行时

| 组件 | 版本 | 备注 |
|---|---|---|
| Node.js | v24.19.0 | 满足 `rea-agents` engines `^22.19.0 \|\| ^24.11.0 \|\| >=26.0.0` |
| npm | 11.17.0 | |
| Python | 3.14.5 | 自研脚本运行时。清点脚本只用标准库；**渲染基底 spike 起引入三个第三方包**（`importlib.metadata` 读到的 SPDX 许可证表达式）：`pillow==12.3.0` = `MIT-CMU`、`numpy==2.4.6` = `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`、`psutil==7.2.2` = `BSD-3-Clause`（仅测试采样用，不进产品路径）；F-042 起服务端备胎解码再加 `av==18.0.0`（PyAV，libavcodec `(62, 28, 102)`，BSD-3） |
| Java | **`<DRIVE_D>/Program Files\Java\jdk-21.0.12.1`**（Oracle Corporation，x86_64 完整 JDK） | 由**用户**安装（2026-10-21）；`JAVA_HOME` + `GHIDRA_INSTALL_DIR` 由 agent 写入**用户级** `HKCU\Environment`。`setx` 不影响已在运行的进程 ⇒ 本会话内跑 Ghidra/REA 时按命令注入这两个变量，不要求重启 Qoder |
| Ghidra | **12.1.4 PUBLIC**，`temp/vendor/ghidra_12.1.4_PUBLIC`（6,695 条目 / 未压缩 0.84 GiB） | 只经 REA 的 Ghidra provider 调用（`scripts/rea_session.py`），**只读静态**；取证面与禁令见上一节与 `scope.md` §1.1 |
| ffmpeg | **PATH 上没有**（`shutil.which` 为空；F-036/F-037 当时用的 8.1.2 full build 安装已消失） | 服务端出图通道**不是 PATH 依赖**：主用剪映自带 ffmpeg，路径由 `scripts/jy_paths.py` 自动检测后记在 `config.local.json`（本机实测落点 `<JY_INSTALL>\11.6.0.14552\ffmpeg.exe`，版本串 `21.7.0-9c087b133d`，`--disable-ffprobe` ⇒ 同目录无 ffprobe）；**不做 PATH 兜底**，检测不到就报错，绝不静默换成另一个版本（换版本就是换像素）。备胎 PyAV 18.0.0。硬解只认 `-c:v hevc_cuvid`（GTX 1650 / 驱动 610.88）；`-hwaccel cuda` 静默回落软解，`*_qsv` 挂到超时（i5-12400F 无核显）。数据：`temp/px-probe/decode-backend.txt` |
| GPU / CPU | NVIDIA GeForce GTX 1650 4 GB（驱动 610.88）/ i5-12400F | 决定 F-042 的硬解结论：有 NVDEC，无核显 ⇒ qsv 全路死 |
| 浏览器 | Chrome + Edge（均已安装） | 渲染 spike 用 |
| `jq` | **不可用** | REA 文档里的视图投影示例改用 Python 实现 |

## 3. 分析目标（剪映）

| 项 | 值 |
|---|---|
| 安装根 | **由 `scripts/jy_paths.py` 自动检测**（2026-10-28 起），默认查 C: 与 D: 的 `Program Files` / `Program Files (x86)` 下的 `JianyingPro`，再查 user 侧 `%LOCALAPPDATA%\JianyingPro\Apps`；判定「完整安装」= 有 `Resources/` 且 `ffmpeg.exe`/`videoeditor.dll` 至少有一个，取版本号最大的版本目录，结果记进 `config.local.json`（gitignore，不进历史）。优先级 `JY_INSTALL_DIR` > 记录且仍有效 > 重扫（`--rescan` 强制）。本机实测根 `<JY_INSTALL>`（**15 个子目录，其中只有 2 个是完整安装**：`11.6.0.14552` 5,192 文件与 `11.1.0.14287 - 副本` 4,052 文件；其余 12 个版本名目录是**更新载荷**，各 37~77 文件、顶层项带 `_d_<7位hex>` 后缀、无 `Resources/`、无 `JianyingPro.exe`；`202687173850092_1` 是 11.2.0.14339 的更新包暂存目录 —— 全部数字出自 F-051 的只读清点） |
| 主分析版本 | `11.6.0.14552`（单版本 3.0 GB） |
| `videoeditor.dll`（11.6.0.14552） | 72,547,608 B，sha256 `8cfcbb612ccd946df974428977b1902736c1de0ae561e20c26cbd4ea86099cb1` —— **仅作为调用对象** |
| `videoeditor.dll`（11.1.0.14287 - 副本） | 66,037,920 B，sha256 `a7e856211bcd09c9c94a1eccde6b60e55ffb0c93da585436302a671782cf7e90` —— 备用版本 |
| 携带 `videoeditor.dll` 的版本 | 仅上述两个（其余 12 个版本目录不带） |
| `Resources/` | 817 MB |
| `Resources/canvas_agent/` | 235 MB，**11.6 自带的 agent 运行时 = 剪映自己写草稿的代码所在层**（239 个 js/mjs，只读）。关键件：`runtime/app-server.mjs` 9,206,933 B（sha256 `4f027a06…`，含 `wl0()` 成片草稿构造器、`gh1` 平台常量、草稿文件清单常量 `custom-agent.jianying-draft-understanding.v1`）；`runtime/videoeditor-service.mjs` 128,669 B（sha256 `ac566cd7…`，只有导出/渲染作业，**不含草稿字段**）；`skills/jianying.hub.studio_lyra_xml_timeline_builder_v2/`（协议 `xmldraft/v1`，SKILL.md sha256 `75d2a317…`，SKILL+10 references 共 132,883 B、146 个去重属性名）；`skills/studio.edit.speaker_cut/` 15 MB（走自己的中间模型，不碰 draft JSON） |
| `Resources/models/` | 240 MB（`SegmentJS` 1.4 MB / 4 文件） |
| `Resources/lynx_config/` | 9.8 MB，34 个 `template.js`，**多为商城/会员/积分页**，非编辑器属性面板 |
| `Resources/MixMode/` | 338 KB，10 个条目，每条 `<md5>/{config.json,content.json,blend.material,anim.prefab,xshader/,Library/}` |
| `Resources/Font/` | 25 MB（`Effect/`、`SystemFont/`、3 个 otf/ttf） |
| QML | 354 个，**全部属 Qt 框架**（`QtQuick/`、`Qt5Compat/`），非应用 UI |
| 资源缓存 | `<DRIVE_D>/JianyingPro\User Data\Cache\ressdk_db` 582 MB（含 `rp.db`）、`Cache\artistEffect`、`Cache\AETemplate`、`Cache\AITextTemplate` |
| 草稿语料（**两个根**，2026-10-22 F-056 更正） | 主根 `<DRIVE_D>/JianyingPro\<DRAFT_ROOT>`：内容文件 **2,268**（r4-d，10-22）/ 2,215（r3，10-16 在册基准），有内容目录 1,247；第二根 `<DRIVE_E>/JianyingPro\<DRAFT_ROOT>`：内容文件 **486**、有内容目录 **427**，其中 **480 个文件与 D 根逐字节同摘要** ⇒ 是镜像不是新料（去重内容只 +6）|
| 草稿注册表 | `<DRIVE_D>/JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json`（**明文**，只读）：顶层 `all_draft_store` / `draft_ids: 114` / `root_path`（写的是 `<HOME>/AppData/Local/…`，实际在 `<DRIVE_D>/JianyingPro\User Data\…` ⇒ 搬迁后失真，不可定位）。条目 **2,126** 条 × 38 键，按 `draft_root_path` 分 D 1,497 / E 629，**628 组同名草稿分居两根且 `draft_id` 无一相同**（580/628 组 create/modified 逐位相同 ⇒ 整目录复制后重注册）。`tm_draft_*` 单位是**微秒**；`draft_type` 全空，`draft_new_version` **1,798 空 + 328 有值**（`114.0.0`/`164.0.0`/`129.0.0`… 整体低于桌面当前 179–189 区间）。同目录另有 `com.lveditor.cloud.draft_*` 5 个与 `com.lveditor.textTemplate.draft` |
| 成片 oracle | `<DRIVE_E>/输出\<品牌>\` |

### SegmentJS 包溯源（`Resources/models/SegmentJS/package_info.json` + `version.json`）

```
name:    ccc_segment_js
version: 202608281900.382.a5ad9b4e.js.feat
branch:  release/22.2.0
source:  f/fengzicheng/22.1.0/lumi_gene_editing
commit:  a5ad9b4e39c77f3674cc51802c8222075006475a
built:   2026-08-28 19:03:00 +0800
files:   main.js 764,731 B  sha256 2ed3440a60a94b5aecb8f16a8ee4732589254c9c562b7c9aa61d91a5ed4b0ef3
         template/template.js 632,535 B  sha256 47f31a5f89ad84d9d4d0bd5816fd1f8ad5e6aba1fda14ba44cf299d7fb8ebe38
```

## 4. 本里程碑允许执行的命令（白名单）

```bash
# REA：JS 静态分析（只读；证据落 temp/）
npx -y rea-agents@6.5.0 analyze-javascript-application "<abs-dir>" --json > temp/rea/<name>.json
npx -y rea-agents@6.5.0 inspect-analysis-view <view.json>
# REA：SQLite 只读快照（rp.db）
npx -y rea-agents@6.5.0 inspect-sqlite-database "<abs-db>" --json --table <name> --row-limit 20
# 自研脚本（只读草稿；产物只写 temp/）
python scripts/corpus_scan.py ...
python scripts/jy_crypto/worker.py ...
# 语料快照回归 diff（覆盖 vs 漂移分开归因；F-056）
python scripts/corpus_diff.py temp/corpus-scan-r3 temp/corpus-scan-r4d            # manifest 模式（默认）
python scripts/corpus_diff.py temp/corpus-scan-r4d temp/corpus-scan-r4de --mode stats
# 双根重扫（cache.py 已按 os.pathsep 切分；写围栏仍只允许 temp/）
JY_DRAFT_ROOTS='<DRIVE_D>/JianyingPro\<DRAFT_ROOT>;<DRIVE_E>/JianyingPro\<DRAFT_ROOT>' \
  python scripts/corpus_scan.py --limit 0 --batch 40
# 原生只读静态收割（mmap 只读，不加载不执行；scope §1.1）
python scripts/pe_harvest.py --rtti --literals --tables --against temp/corpus-scan/stats.json
# Ghidra provider：一次活会话批量取证（分析费一次 ~50 min；产物只落 temp/rea-native/）
JAVA_HOME=... GHIDRA_INSTALL_DIR=... GHIDRA_HEADLESS_MAXMEM=4096 \
  python scripts/rea_session.py --plan temp/rea-native/plan-<name>.json --out temp/rea-native/session-<name>
# 测试期对照 oracle（非运行时依赖）
python "<HOME>/.agents/skills/jianying-editor-skill/scripts/jianying_project.py" inspect "<draft>" --timeline active
```

超出白名单的动作（新副作用类别）先停下来向用户披露并获批。

`scripts/mixmode_extract.py` / `scripts/mixmode_equivalence.py`（2026-10-23，要求 1）：前者把
`Resources/MixMode` 十包的 `.frag` **原文**逐字节复制到 `temp/playback-test/mixmode/frags/` 并记 sha256
（`tables/mixmode_frag_manifest.csv`），后者起网关 + headless Chrome，把包内 GLSL 与独立实现的 W3C 标准式
喂**同一份 8-bit 输入**逐 texel 比对，判据 1/255（量化下界）。oracle 全程不誊写公式，所以等价结论不是
「我们以为的等价」。表 `tables/mixmode_equivalence.csv`，结论 F-077 / 残留 U-90。
`scripts/cut_alignment.py` / `scripts/animation_gap.py` / `scripts/animation_curve.py` /
`scripts/animation_wiring_check.py`（2026-10-23，动画通道）：第一个是**固定 oracle 帧号**的逐轨平移探针
（P-29 用它推翻了「+2 帧对齐」，因为搜偏移会把平移实验的自由度吃掉）；第二个把「段带动画」量成
窗内/窗外的整帧相关分布（`--no-animations` 是 A/B 开关，`--head` 按 tween 长度取窗）；
第三个从预设包内明文 lua **读** `tween:fromTo(...)` 的曲线（不手抄数字，未知形不假装覆盖）；
第四个是接线判据，含「动画期外必须逐字节相同」这一条，专门用来抓「曲线常驻」。
分工纪律：曲线值只允许来自包内 lua，位移方向与 `Amaz.Ease.quadOut` 的函数式**由成片判**，
不许把假设写成取证。
`scripts/animation_region_check.py` / `scripts/merge_model_carrier.py`（2026-10-23，F-080/P-34）：
前者是**字幕动画唯一目前有区分力的判据**——把该段孤立渲染（画到黑底）取它自己的横向占位，
再在该列范围内与成片同帧比 RGB MAD（整帧相关与全画面色彩质心都被证明看不见字幕动画）；
后者把新 L1 的载体字段（`animations`/`mix_mode`）按段 id 合并进已有代理模型，
只搬白名单、不碰 `media.path`，带计数断言 + `.tmp`/`os.replace` 原子写 + `.bak` 备份。
门的 L9 用浏览器自报的 `{alpha,scale}` 与通道 2 逐段对数（`dy` 故意不判：两侧对「纹理高」的定义不同）。
`scripts/mix_stability.py` / `scripts/browser_shot_check.py`（2026-10-23）：
前者是 U-86 的**判决实验**——同一模型整条时间线确定性播放（`seeks=0`、`playms > 时长`）重复 N 次，
用极差 ≤0.02 判「离散来自 seek 覆盖」还是「真是混音竞态」；写它的理由也记在文件头：
54 个历史跑数里 14 个候选字段按爆/不爆分组**全部重叠**，观察性数据判不了这条，
继续找相关只会在共同因上再翻一次车（上一轮 `loudness_applied` 就是）。
后者把**浏览器自己画出来的帧**（`player.html?shots=` → 网关 `/shot`）与同刻成片帧、
同刻通道 2 帧三方对数，两条判据分开阈值（跨通道 ≥0.95 / 对成片 ≥0.90）：
门原来的 L2/L3 都用通道 2 出图，等于让另一条通道代答「预览看起来对不对」，
交互内核本体的画面此前从未被像素判过。
`scripts/rss_ab.py`（2026-10-23）：内存判据的**单变量 A/B**——同一份播放器代码只换模型，
每个 arm 独立起浏览器与 profile，报 median/p95/max/越线秒数与按 `--type=` 的角色峰值。
写它的直接起因：600 s 判据的 median 从 895 涨到 1166，但那两次之间代码、模型、峰值时刻都变了，
不是单变量，所以「改动涨了内存」当时不能写；归因要么用这条，要么别提。
另外门的 L10 现在把浏览器自己画的帧（`extract.pixels` → `/shot`）与同刻通道 2、同刻成片对数，
**两条判据按混淆项分开**：跨通道固定同刻（无对齐自由度），对成片允许 ±3 搜对齐并报偏移
（切点两侧是不同镜头，硬对会把 0.98 读成 0.13）。
