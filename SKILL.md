---
name: jianying-preview
description: 只读预览与校验剪映(JianYingPro)草稿：解析/解密 draft_content.json，在浏览器按时间线复现画面与声音（多轨叠序、文本样式/描边/阴影/渐变、动画、转场、混音、复合子画布），并提供无浏览器的离线合成通道与回归门（全量跑 28 条判据，逐层报 PASS/FAIL/SKIP）。当用户要求"预览剪映草稿""看看改完的效果""不开剪映能不能看到时间线""草稿截图""校验/验证剪映改动"，或在自动化剪辑改完草稿后需要确认结果时使用。绝不修改草稿内容。
---

# 剪映草稿只读预览与校验（M2）

三条硬规矩，先读：

1. **草稿只读。** 本 Skill 不写 `draft_content.json`、不写 `.jypreview/`、不动封面与素材索引。
   任何"看起来要写回"的需求都转交 `jianying-editor` 那条线。
2. **改完播放器必须先过门。** `python scripts/playback_check.py …` 是唯一裁判；
   手工看一张截图不算验证（历史上五个缺陷里有五个先骗过了人眼和一层临时检查）。
3. **临时产物只进 `temp/`，证据进 `evidence/`（根仓跟踪）。** 草稿副本、代理片、导出成片一律不提交。
   `origin/docs` 已在 `1fed3d8` 并进 main，所以规格与证据现在住在根目录的 `spec/`、`evidence/`；
   历史文本里写 `docs/spec/…`、`docs/evidence/…` 的地方指的是同一批文件。

## 通道结构

| 件 | 位置 | 职责 |
|---|---|---|
| L1 模型 | `scripts/playback_model.py` | 解密/解析草稿 → `model.json`（段、几何、字体、动画引用、音量、断言） |
| 安装定位 | `scripts/jy_paths.py` | 自动检测剪映安装（`ffmpeg.exe` / `videoeditor.dll` / `canvas_agent` 的 js 目录都从这里取），结果记在 `config.local.json`；不再往脚本里写死盘符 |
| 依赖 | `requirements.txt` → `temp/venv`；`temp/px-probe/node_modules` | Python 侧 `pillow`(门与离线通道的地基) `numpy` `psutil`(仅 `browser_soak` 的 RSS 峰值) `av`(仅 `media_probe`) `pyyaml`(仅 `check_spec_yaml`)；node 侧 `pixi.js` + `mediabunny`。**跑脚本请一律用 `temp/venv/Scripts/python.exe`**——PATH 上那个 `python` 没有 pillow，`playback_check.py` 连 import 都过不去。门派生的子进程走 `sys.executable`（`playback_check.py:55`），所以会跟着同一个 venv |
| 网关 | `scripts/preview_gateway.py` | 只绑 127.0.0.1、GET/HEAD、Range + keep-alive；媒体与字体按不透明 id 供；`/report` `/shot` `/wave` 回收入口。日志行以 `epoch=<毫秒>` 开头（页面回送 `epoch_base`，于是页内 await 窗能与服务端窗 `[epoch-ms, epoch]` **逐窗相交**）；`--log` / `--log-max-mb`（默认 64，超限**改名归档不删**）/ `--run-id` 让每轮有独立可筛的日志 |
| 浏览器通道 | `player/player.html` | Pixi 8 合成 + mediabunny 解码 + WebAudio 混音；运行副本在 `temp/playback-test/player.html`（门会逐字节校验）。仪表开关：`&split=0/1`（默认 1；**0 = 改前那段循环原样**，用作新通路自己的负样本）、`&slowleg=<ms>`（慢腿入册门槛，默认 100）、`&probe=<8位id,…>`（点名腿无条件回送，**判活只认它且 `pushes>0`**，"没进前 16 名"证明不了任何事）；报告里 `play.slow_legs={gaps,over,dropped,rows}` 的**分母是 `gaps`**，`play.switches` 回映生效值并附整条 `search` |
| 离线通道 | `scripts/render_frame.py` | PIL/ffmpeg 同律渲染，用于像素级对照与成片比对 |
| 门 | `scripts/playback_check.py` | 回归门，**判据条数随开关变化**：P-97 全量跑 28 条 = 22 判绿 + 3 INFO + 3 红；`--skip-jank` 会为 `L4 frame budget` 与 `L4 live pacing` 各留一行 SKIP。末尾那行"N of N checks passed"**把 SKIP 计作未失败**，所以报绿必须连 SKIP 条数一起报。`--settle-seconds`（默认 12）在相邻浏览器阶段交界处空机等待——理由是 `browser_soak` 返回时只 terminate 自己的主进程，gpu/renderer 与 profile 落盘还在收尾，背靠背会同时污染 live pacing、L6 与 RSS peak。**四条防"绿的谎话"**：① `L4 continuous` 除 fps≥24 外还要求 `fresh_track_frames_per_second > 0`（P-99：代理片那一跑 28.4 fps 全绿而 `decoded=0`、`opens` 里只有 mp3 —— 零解码时 rAF 均值照样满格）；② L7 mixmode 三层依赖 `temp/playback-test/mixmode/`（`mixmode_extract.py` 从安装目录 `Resources/MixMode` 抽的 10 份 frag + manifest），`temp/` 重建后缺了会**三条同红**且详情只写 `no output`（真因在 stderr），门现在缺件即当场补建并在详情标注；③ `L4 frame budget` 与 `L4 live pacing` 都吃 `--repeat`：**每个点各自过线才算绿，不取中位**（P-100 那个残差 950 ms 的直播红点只报了 1 个点，11 个隔离点复现不出、门内重跑也复现不出——n=1 的分布型判据既造出无法解释的红，也造出无法引用的红，见 U-102）；代价随 `--repeat` 线性涨：整条约 +1~2 分钟/点、直播约 +50 s/点；**但分母不随 `--repeat` 涨**（每点打在同一个判据行的详字段里，`:512-556`/`:604-625`），分母只由 `--skip-*` 与 `--mixmode-gpu` 决定；④ **`--negative-model` 夹具不在场时 `L6 guard has teeth` 连 SKIP 都不留**（`:718` 的 `if ... and Path(...).is_file():` 没有 else）⇒ 那一跑会打印 `27 of 27 全绿` 而其实少一条，`--cover-frame` 不给时 `L3` 同一机制（`:382`）。`temp/` 重建后先跑 `temp/playback-test/preflight_s5.py`（无计时，负载机合法；判读只认 RC，不认打印了几项），夹具用 `make_blacktest.py` 重建（P-21 配方），口径见 `evidence/playback-log.md` P-116 ⑫⑭ |

播放器依赖的 `pixi.js` **8.22.0** / `mediabunny` **1.65.0** 从 `temp/px-probe/node_modules` 取本地固定版本
——**不走 CDN**，因为换版本就是换像素，历史对照会失真。
⚠ **2026-11-02 重建**：这两个号是重装时 registry 上的最新版，**不是当初跑绿 28 条判据的那一对**——
原固定版本只存在于被 gitignore 的 `temp/` 里，仓库从未登记，temp 一清就没了（把号写在这里就是为了下次不再丢）。
代价：**只有真的走浏览器的那条像素判据** —— 对着 `JY_ORACLE_MP4` 的 **L10 三方截图** 在重新标定之前不可引用，
L7/L8 那几条依赖 `BlendModeFilter`/`ColorMatrixFilter`/`BlurFilter` 的接线判据同理要重跑一遍才算数。
（**判据名以门自己打印的为准**，这一列被误挂过三次，全按代码改回来了：
① 曾把 `L3` 当成"对成片的相关性"写在这里——`L3 video band` 实际是**离线通道**对 `--cover-frame`
封面帧的相关性，不碰成片。2026-11-02 更正。
② 曾把 `L11 flash` 列进来——`flash_channel2_ab.py` 只 import `numpy`/`PIL`/`render_frame`
（曝光与垂直模糊在**离线通道 2** 里实现，它翻 `rf.AE_FLASH`），一个 node 库都不加载。
2026-11-03 按代码更正并当场用配对成片复跑，九个计数与 P-97 门内那一行逐位相同（P-116 ⑪）。
③ 曾把 `L2 色层包围盒` 列进来——门里的 L2 建在 `playback_check.py:345-377`，比的是
`render_frame.py`（离线通道）对 ffmpeg 抽的成片帧，**整条判据不开浏览器**。2026-11-03 更正并门外复跑，
`255,255,255` 那一行与 P-97 `playback-log.md:3417` 逐位相同（P-116 ⑫）。
教训三条同一句：**引用判据清单前先读那条层调的是哪个脚本**——抄清单会把不该等的窗口等出来，
也会把已经复现的读数白白重标定一遍。）

⚠ **`temp/` 一清，所有"读冻结中间产物"的工具都会变红或变哑**（同一族，2026-11-02 P-102）：
`temp/playback-test/mixmode/`（门的 L7 层缺件即当场补建，见下）、
`temp/corpus-scan/`（`spec_audit.py` / `build_evidence_tables.py` 的输入）。
后两个现在有前置守卫：缺件就 **RC=2 并印出重建命令**，`spec_audit` 只 SKIP 不代跑扫描，
`build_evidence_tables` 在打开任何输出文件之前退出——它写的是**已提交的** `evidence/tables/*.csv`，
空 `temp/` 走到第一个 `write()` 等于把一张实测表清零。要更新覆盖台账就得真重扫
（`corpus_scan.py --limit 0 --batch 40` → `corpus_detail.py` → `spec_audit.py`），这是有代价的一步，别被工具悄悄触发。

## 最小可用流程

```bash
# 0) 安装位置自检（只读，结果记在 config.local.json），再解密草稿（plain 产物进 temp/）
python scripts/jy_paths.py
python scripts/playback_model.py "<plain.json>" --draft-root "<草稿根>" \
       --timeline <uuid> --out temp/playback-test/model.json

# 0b) 素材结构清点：media_probe 吃的是**素材文件路径**（文件/目录/glob 都行），不是草稿 JSON。
#     要从模型里取路径就自己抽一遍 media[]，它只会按你给的文件逐个报 GOP/moov/elst/ctts。
python scripts/media_probe.py "X:\…\C7502.MP4"                # ← 直接点文件
python scripts/media_probe.py $(python -c "import json;print(*[m['path'] for m in \
  json.load(open('temp/playback-test/model.json',encoding='utf-8-sig'))['media'] \
  if m.get('type')=='video'])")                                # ← 或从 model 抽全部视频源

# 1) 无浏览器校验：模型断言 + 离线成帧 + PNG
python scripts/render_frame.py --model temp/playback-test/model.json --t 1.0 --out temp/playback-test/check-1.00s.png

# 2) 浏览器预览（人在环里看）
python scripts/preview_gateway.py --port 8790 --serve-dir temp --model temp/playback-test/model.json
# 浏览器打开 http://127.0.0.1:8790/playback-test/player.html?model=model.json

# 3) 回归门（跳掉慢层先跑通）
python scripts/playback_check.py --plain "<plain.json>" --draft-root "<草稿根>" --timeline <uuid> \
       --model temp/playback-test/model-check.json --media-model temp/playback-test/model-proxy-a.json \
       --oracle-mp4 "<你的成片 mp4>" --pixel-t 1.0 --pixel-colour 255,255,255 \
       --repeat 1 --skip-flash --skip-mixmode --skip-browser-shots

# 3b) 慢层（帧预算 + 直播节奏）：判"体"与判"尾"分开，--repeat 至少 3
#     跑前先确保 mixmode 抽取件在位（否则 L7 三层会因缺件同红，详情只写 no output）：
#     python scripts/mixmode_extract.py --out-dir temp/playback-test/mixmode
python scripts/playback_check.py --plain "<plain.json>" --draft-root "<草稿根>" --timeline <uuid> \
       --model temp/playback-test/model-check.json --media-model temp/playback-test/model-proxy-a.json \
       --repeat 3 --skip-flash --skip-mixmode --skip-browser-shots
```

代理片（大素材的时间轴测试要用）由 **`scripts/make_all_proxies.py`** 生成（2026-11-02 重建；
原先在 `temp/playback-test/` 的那两份随 temp 一起丢了，`add_proxy_audio.py` 不再需要——音频在同一次
编码里用 `-c:a aac` 带上）。配方：**`h264_nvenc yuv420p` + `1/6 s` 关键帧 + `+faststart`**
（2026-11-02 由门里三臂对照定档，P-110：同一配方刚重写的对照臂没动，1/6 s 那条把 `L4 first frame` 从
388–431 ms 的 FAIL 拉到 128 ms PASS、`L4 seek` 118→38 ms、帧 max 中位 329→187 ms；代价是全量体积
**+55%**（1758→2726 MB，且逐只不单调，见 P-107 ②-补）。要旧配率就 `--gop-seconds 1.0`，**换配率请换目录**：
已存在的产物只复用、不重编），
**保帧率**（源是 59.94/50 就还是 59.94/50）、**不缩放**（对像素比的几条：`L2 pixel layer` /
`L10 browser pixels` / `L11 flash …`，外加 `L3 video band` 对封面帧那一条——缩了就是
自己把基线挪走）。它同时产出媒体模型（默认 `model-proxy-g16.json`，只换 `media[].path`，原路径留在 `path_original`），
音乐与图片类素材**不代理**——mp3 本来就能流式，换编码等于偷偷改 L5 在测的东西。

⚠ **换路径必须递归到底**：组合（composite）子时间线里的段带**自己的 `media` 对象**，只换顶层
`materials` 会留下几十处嵌套原路径 ⇒ 视频腿一条都不跑，而门报出来的形状是"`composited_fps` 28 全绿 +
`decoded=0`"与 `L6 media … not served`（P-99 就是这么过的）。`make_all_proxies.py` 的 `swap_paths()`
已递归 dict/list 全体，并在**写完重读后**用 `leftover_paths()` 自查，有残留就 `return 1`——
"79 paths swapped"与"25 swapped"是两种完全不同的模型。

⚠ **代理片会把容器旋转烘进像素**（ffmpeg 默认 autorotate，配方里没有 `-noautorotate`）。实测 Sony
竖拍源 coded `1920x1080`+`rot=90` → 代理 coded `1080x1920`+`rot=0`：**显示几何不变**，因为
`place()` 对四分之一转做了 `sx=H/tw, sy=W/th` 并 `node.rotation=rot`（`player.html:1294-1301`，函数起 `:1288`；旧文写的 `:1245` 已按 P-114 ⑦ 漂到这儿），两条路落同一个框。
这个等价是**有条件的**：谁把容器的 `s.rotation` 与草稿的 `c.rotation` 合并成同一个数、或去掉那段补偿，
代理就会悄悄把竖拍变横拍，而门不会红。改动 `place()` 前先看 `evidence/playback-log.md` P-98 ④b。
另外代理是 8-bit 4:2:0（源常见 `yuv422p10le`），色彩标签两边一致（bt709/tv），所以 L2/L3 的差异预算
要容下次采样这一项，但不存在系统性色偏。

## 环境变量

| 变量 | 用途 |
|---|---|
| `JY_ORACLE_MP4` | 原生导出成片路径（**L2 / L10 / L11** 三条像素判据与若干 A/B 的对照物；`L3 video band` 用的是 `--cover-frame` 封面帧，不是这个）。未设时相关脚本走"文件不存在"分支并报错，不会静默用空路径比对 |
| `LOCALAPPDATA` | 剪映机器资产（效果包、字体）根，即 `%LOCALAPPDATA%\JianyingPro\User Data\...`（脚本用 `Path.home()`，不写死用户名） |
| `JY_INSTALL_DIR` | 钉死剪映安装版本目录（如 `D:\Program Files\JianyingPro\11.6.0.14552`）。不设时由 `scripts/jy_paths.py` 查 C:/D: 的 `Program Files`、`Program Files (x86)` 与 user 的 `%LOCALAPPDATA%\JianyingPro\Apps`，取「完整安装」（有 `Resources/` 且带 `ffmpeg.exe`/`videoeditor.dll`）里版本号最大的那个，并写回 `config.local.json` |
| `config.local.json` | 本机安装记录（skill 根目录，已 gitignore）。记录里的目录还在就沿用，不再走盘；被升级/删除后自动重扫。`python scripts/jy_paths.py --rescan` 强制重扫 |
| `JIANYING_VIDEOEDITOR_DLL` | 钉死**解密用**的 `videoeditor.dll` 绝对路径（`dll.py:discover_dll` 首选项，不设则取版本最大的完整安装）。剪映升级后必设：11.7.0.14652 的内存 `decrypt` 在冷进程里对任何输入都返 `ok=true / 0 字节`（含它自己 `encrypt` 的产物），详见 `evidence/crypto-probe-log.md` 探测 3。恢复办法：升级器把旧文件改名留在旧版本目录（`11.6.0.14552/*_d_*`，实测 65/66 个文件都改了名），
`python scripts/rebuild_dll_sandbox.py --version-dir <旧版本目录> --out temp/dll-11.6 --sha256 <基线>`
整批还原到 `temp/` 下的沙箱（安装目录只读；落点由 `cache.assert_scratch_target` 兜死；sha256 对不上就非零退出，
**必须绝对路径**加载，`add_dll_directory` 收相对路径抛 WinError 87）。已知良好基线 sha256 `8cfcbb612ccd946df974428977b1902736c1de0ae561e20c26cbd4ea86099cb1` |
| `gate.py` 的门禁读数（不是环境变量，是**口径**） | 引用前先确认这一跑真的钉住了 DLL：**要么 export `JIANYING_VIDEOEDITOR_DLL`、要么带 `--dll`**，二者其一。2026-11-03 之前 `--dll` 只喂给 identity 的 `report`，样本那三次 `call` 一律走 `discover_dll()` ⇒ 报告里写 11.6、真正干活的是 11.7（`evidence/crypto-probe-log.md` 探测 6）。同一探测还修掉第二条：scratch 产物按**源 sha** 命名且改前跑时**不清空** ⇒ 上一轮留下的旧明文被当成本轮结果，把"全失败"读成 1 条 PASS。改后对照：带 `--dll` 3/3 PASS(RC=0) / 不带 0/3(RC=1) |

## 门能判什么（编号即层名）

L0 在册播放器与运行副本逐字节相同 · L1 模型断言 / 几何通道 / 载体新鲜度 / 轨类型覆盖(INFO) ·
L2 帧 vs 成片的色层包围盒 · L3 离线通道对**封面帧**（`--cover-frame`）在色层白名单下的相关性 ·
L4 连续播放、seek、首帧、Range 流、**整条时间轴的帧耗时尾部分布**、直播节奏 + A/V 残差 ·
L5 混音器 · L6 静帧守卫（正反两个方向都有牙齿）·
L7 混模式浏览器接线 · L8 动画/打字机接线 · L9 跨通道曲线一致 · L10 浏览器自截图 vs 离线通道 vs 成片 ·
L11 闪光律 in/out 单变量。

**层号是给人看的索引，不是判据名**——以门自己打印的行为准（`L2 pixel layer` / `L3 video band` /
`L10 browser pixels` / `L11 flash …`）。两条我记错过、这次按代码改回来的性质：
① 对导出成片 `--oracle-mp4` 的是 **L2 / L10 / L11**，`L3 video band` 对的是封面帧，不碰成片；
② `--skip-browser-shots` / `--skip-flash` / `--skip-mixmode` 关掉的层**一行都不留**（只有 `L2 pixel layer`
和 `--skip-jank` 下的 `L4 frame budget` / `L4 live pacing` 会补一行 SKIP），
所以末尾的"23 of 23"与"少了 5 行"是两件事：**少掉的行是没测，不是过了**。
报绿要连"总行数 / 判绿 / INFO / SKIP / 红"一起报，且**逐行从日志数**，不按层号推断。

判据是**分布不是单值**：`--repeat ≥3` 才有资格说"通过"；`peak_fs`、首帧这类必须报中位与尾部。
`L4 frame budget` 与 `L4 live pacing` 是**每个点各自吃线、全部过才绿**（不取中位——取中位会让
一个被污染的点被其余点平均掉，那是悄悄放宽）。

## 做 A/B 之前（十三条，都是烧过机时换来的）

1. **先把自变量钉住**：说得出"改完之后哪个读数必须变"，并且那个读数**已经在页内或网关账本里**。
   两个反例（同一个坑的两种形态）：`&pool=4`/`&qmax=4` 与默认值逐字相同 ⇒ 两臂是同一臂；
   `&pool=8` 看着放开并发，其实池只是**空闲时的回收目标**，直接量出来的真实 in-flight 是 p50=1 / p95=2
   ⇒ 这条臂没测到任何东西，是**作废的臂**，不能写成"并发已测过且为负"。
2. **tag 必须含批次号**（`<实验>-<臂>-<批><轮>`）：`warm-<臂>-<轮>` 让后一批直接覆盖前一批的
   `report-*.jsonl`，于是"每臂 n=2"其实是"最后一批的 n=2"，前一批只剩汇总文本。
3. **跨时钟相交之前，先确认交的是哪一个窗**：慢腿同时给了 `w0/w1`（park+await+convert 的整个间隔）
   与 `aw0/aw1`（**纯 await 窗**）。用前者会把 park 期间的请求算成 await 窗内的请求——同一批腿的
   形状会从"窗内 7 个请求"变成"窗内 0 个"，结论直接反过来。
4. **变介质的实验要留内部对照**：只重编关心的那几个文件，其余逐字节不动，判据按
   `target / other` 分组——"other 不动"就是这次跑的空白臂。
5. **臂序不能固定**：每轮都同一臂先跑 ⇒ **臂与位置完全共线**，两臂之差既可以是介质效应，也可以是
   "每轮第一个点天然更慢"（缓存/预热）。要么分批反装（`ORDER="ctl dense"` / `"dense ctl"`），
   要么臂序随轮次翻。**主统计量选一个与阈值无关的**（如 `Σwaits/decoded` 这种每帧均值）：腿数类读数
   被 `SLOW_LEG_MS=100` 截断，"腿掉到阈值以下"和"腿没了"长得很像，b1 里就是靠 `>50ms` 复算才看出两组同比例下降。
6. **内部对照之前先做引用普查**：一个源文件常挂在多个 segment id 上（`091037` 一源 8 个 id）。
   "只换 4 只文件"实际动到 **79 个引用里的 29 个**，剩下不到 2/3 的 `other` 还要与被换的那半共用磁盘缓存与
   解码排队 ⇒ 空白组不空白。先跑 `model_path_census.py` 看 target 占比，过半就在结论里明说这批只能报**整跑级**，
   别把"other 也跟着变快"读成臂效应。
7. **两臂读不同文件时，"文件是刚写出来的"本身是一个变量**：碎片布局、MFT、页缓存状态都跟着变。
   全量重编做对照，就得用同一支脚本、同一时段、同样新写盘地把**旧配方也重编一遍**当对照臂
   （`temp/gate_ctl_all.sh`）。P-108 那一跑没这么办，于是 `seek` 118→38、`first frame` 431→128 这种
   "四条一起动"的读数**全部挂在待判状态**——配方效应和重写效应那时是同一条。
8. **整跑 max 只配当采纳门槛**（全量介质 + 每点都过线），**不配当部分换体语料的臂间判据**：
   整跑 max = 所有媒体里最差那一腿，只换 4/25 只时它被没换的那 21 只钉住。同一个错误判据在 P-106/P-107
   得出的"密度买不到尾巴"，到全量门里翻成 max 中位 329 → 187。臂间比较用与阈值无关的每帧均值（见 5）。
9. **离线算出来的回归量，必须与"那条腿真正播的那份介质"同源**：P-111 第一版把 `locate()` 的搜索列表按
   `proxies/` 排第一，于是 28 条腿的关键帧偏移**全按 1 s 原件算**，而其中一半腿在放换过的 `proxies-gop-<臂>/`——
   拿到手的 `Spearman = −0.21` 不是"机制不成立"，是**两条不同曲线的相关**。改成"按臂优先解析 + 打印每行落进哪个目录"
   之后同一个假设给出 `+0.16`（分臂 −0.52/+0.40/+0.40/0.00）与一份**真正的对照**（偏移 16.6→1.1 帧，await 不动）。
   ⇒ 凡用 ffprobe/离线量去解释页内读数，先把"这条腿读的是哪个文件"写死并打印出来；解析顺序是隐藏的自变量。
10. **跨表相交之前，先问"每个时间戳减掉了什么"，并先证明判决工具会拒判**：P-113 里同一份报告并存三套口径——
    驱逐/泵账本的 `at` 是 `now() − T0_PAGE`，慢腿的 `w0/w1` 是**裸** `performance.now()`，而腿的 `at` 是**媒体秒**；
    拿两套直接相减，差的是一个没人回送的常数，3 s 邻域窗会被它悄悄吃掉（修法是回送 `pool_stats.t0_page_ms`，
    换算不出就不开窗，而不是放宽窗）。同理，判决脚本要先拿旧报告跑出**拒判**、再拿合成跑做**变异检查**
    （把窗内那次驱逐挪出窗，分子必须从 1 掉到 0）：否则"0 条"永远分不清"没发生"与"拼不上"。
11. **回送账本要按值冻结，不能按引用带出**：`{...obj}` 只冻结标量，数组字段仍是活的引用——P-114 的
    `(a)` 就是这么被判据自己否掉的：`evictions` 停在 22 而 `evict_log` 在 `await postCapture()` 那一秒里
    继续长到 25 条。任何"计数 == 流水长度"的自检，先把两边取同一个瞬间（深快照），再判；
    并且**判据被真数据逼着改写时，要连着写下逼出它的那条读数**（这里还留了一条 `dispose_errors`：
    假设被否掉了，字段本身仍是有用的记账，但别让它冒充因果）。
12. **预注册的判据要先拿旧账验一次可满足性**：P-112 的门写"任一条超线就回滚"，而同一批旧账里参考臂
    自己就有一条 max 187 越线（那正是待解释的症状）⇒ 这条规则**遇到真数据必然触发**，回滚信号不携带信息。
    改法是拆两条：**绝对线**照报过/不过（不放宽），**回滚只看回归**（Δ中位出带、或超线行数比参考侧变多）。
    同理，噪声带要取 `max(预登记值, 参考侧自己的实测极偏)`——±31 比参考臂自身的 70 还紧时，用它判就是注定误报。
    分组按**定义字段**（`play.window_ms`），不按副作用（`seek.n>0`）也不按常量（`duration_s` 每行都等于时间线长度）。
13. **前置条件的采样器必须"取不到数就拒绝"，而且不许现场手敲**：10:38–10:42 我手敲
    `tasklist /FI … /NH | grep -c` 采到三连"ffmpeg=0 chrome=0"，几乎据此起门；实际是 Git Bash 把 `/NH`
    补成路径 ⇒ tasklist 报错、stderr 被 `2>/dev/null` 吞 ⇒ `grep -c` 数的是**空输入，恒等于 0**。
    同一分钟 CIM 查到三支接力转码。⇒ 判据改成**只认工具的退出码**（`temp/playback-test/idle_check.py`：
    psutil 枚举 + `nvidia-smi` 逐次采，任何一步取数失败 ⇒ RC=1 按"不空机"放行方向锁死）。
    这条判据当场生效过两次（这台驱动不认 `--samples`、`--query-gpu` 返回 `"22 %"` 带空格）——
    **两个 bug 都表现为"不许跑"而不是"可以跑"**，这才叫 fail-safe。同理，一个判据如果**从没被证明可满足过**
    （GPU ≤5 %：全部历史读数 8–37 % 都是在有转码时采的），要在窗口之外先把底数采出来，不许临场放宽（见 12）。

## 已知边界（不要在这里浪费回合）

- **调色/滤镜不实现**（按规范刻意排除），所以带调色的时间线整帧相关会低一截。
- **字幕字形有天花板**：草稿引用的建馆字体可能已被剪映自己清掉，两通道都只能落到校准过的兜底字体，
  比成片多 14–19% 墨量；这条已写进 `spec/text.yaml`，不是待修项。
- **真实 rAF 节奏测不了**：headless 与应用内浏览器都不发帧，门的每帧耗时来自定时器路径的代理。
  "卡不卡"最终要人眼看一次。
- **叠序未标定**（U-15）：`render_index` 与轨道位置两种读法在本语料上给出同一结果，无法分辨。
- **整条时间轴那条帧尾（定档前 298–367 ms，定档后 103–187 ms，线 150）方向已经收窄**（P-104）：网关服务端 `ms` max 4.94 / 复用 ≈100%、
  真实 in-flight p50=1、await 与窗内字节数与请求数都不相关（−0.10 / +0.02）、10/46 条慢腿的 await 窗内
  **一个请求都没有** ⇒ **别再从码率、keep-alive、并发这三头试**。剩下的候选全在 `await it.next()`
  （取字节+解封装+解码，Chrome 侧）里面。**GOP 密度这条已跑完并定档**（P-105/P-106/P-107）：
  四臂拉丁方（`ctl` 1 s / `g05` 0.5 s / `g16` 1/6 s / `dense` 2 帧，各 n=4，位置极差只有臂跨度的 11%）给出
  **mean await/帧 1.043 → 0.872 → 0.635 → 0.706 ms**——**谷底在 1/6 s**，比它更密要**倒赔**（`dense` 慢 0.070 ms
  且体积 +93%）⇒ `await` 里"少解码起步"与"多取字节"两头同时在场，曲线不单调就是这件事。
  尾巴那句要按语料范围说：A/B 里 max 323 → 247 → 287（线 150）是**只换 4/25 只**的读数，
  整跑 max 被剩下 21 只钉住 ⇒ 别拿它当"密度对尾巴无效"的证据（P-108 ②）。门里三臂对照（P-108/P-110）给的是
  max 中位 **329 → 187**、`first frame` **431 FAIL → 128 PASS**、`seek` 118 → 38 ms，并且**同一配方刚重写的对照臂
  一条都没动**（128.9 / 388.8 FAIL / 298）⇒ "文件是新的"被排除，**`-g` 成立，默认值已翻到 1/6 秒**（P-110 ①）。
  同一配方的自然散布顺手量出来了：**seek ±10 ms、first frame ±43 ms、帧 max ±31 ms**，比这小的差不要当成效应。
  代价（**全量实测，不是外推**）：25 只 1758 → **2726 MB（+55%）**，且**逐只不单调**
  ——`C8248` 一只 +437.6 MB 占了全部增幅的 45%，`091037` 反而 −5.9 MB ⇒ 只报合计会误导，见 P-107 ②-补 的逐只预算表；
  `proxies/`（1 s 原件）与 `proxies-ctl-all/`（1 s 重写件）都留着可比。**帧尾仍差一点没过线**（187 vs 150），
  那一条不由密度负责（P-110 已排除"新写盘"），也不由"剪切点离上一个关键帧多远"负责（P-111 判据与对照双双否掉：
  密度把回头距离压掉 15×，腿的 `await` 只在 113–126 ms 里动）。剩下能读到的形状是一条 **~120 ms 平台**，
  而暖泵每跑只起 22 只、覆盖 ≈8.6% 的切点 ⇒ 走 U-104：**先修仪表**（池驱逐/泵创建按段 uuid 全量记），
  参数一个都别先动。

细节与逐条证据在根目录 `evidence/`（`origin/docs` 已并入 main，不再是独立仓）：
`evidence/findings.md`（F-xx）、`evidence/unresolved.md`（U-xx）、`evidence/playback-log.md`（P-xx 现场记录）。
