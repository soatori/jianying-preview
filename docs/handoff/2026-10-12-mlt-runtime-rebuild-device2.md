# MLT 运行时重建与全量门槛回归（2026-10-12，第二台设备）

承接 `2026-10-12-workspace-consolidation.md` 的 P0-1「恢复隔离 MLT 运行时并重跑完整回归」。
本机（用户目录 `11`，仓库 `C:\Users\11\.agents\skills\jianying-preview`，`main = fe34bc7` clean）
原本完全没有 MLT 运行时：`JY_PREVIEW_MLT_PYTHON` 未设置，报告里的 `cbsjz` ucrt64 路径不存在，
`temp/` 目录也不存在。本轮在本机从零重建了运行时并跑完计划中的全部 MLT 门槛。

只记录实际观察到的结果；未跑通的项一律标为失败或未验证。

## 1. 运行时重建方式

报告中的运行时是一棵解压出来的 MSYS2 UCRT64 目录树（不是 pacman 安装），因此本机按同样形状重建，
不装 MSYS2、不跑 pacman、不动全局 Python、不改 `scripts/requirements.txt`：

- 构建脚本 `temp/mlt-build/prepare_mlt_runtime.py`（仅用 Python 3.14 标准库：`compression.zstd` + `tarfile`）。
  `resolve` 阶段解析 `repo.msys2.org/mingw/ucrt64/ucrt64.db` 求传递依赖闭包，`build`/`refill` 阶段下载
  `.pkg.tar.zst` 并按原归档布局解压到 `temp/mlt-runtime/ucrt64/`，符号链接成员（fontconfig `conf.d` 等）
  落地为真实副本，跳过 `include/`、`man/`、`doc/`、`*.a`、`*.la` 等运行时永不加载的内容。
- 闭包 149 个包，下载 212.4 MiB，落地 634 MB；清单与逐包 SHA-256 在 `temp/mlt-runtime/package-manifest.json`。
- 下载源用 TUNA 镜像（28 MiB/s，官方 `repo.msys2.org` 本机只有 0.10 MiB/s）；
  `mingw-w64-ucrt-x86_64-mlt-7.40.0-2-any.pkg.tar.zst` 落地后与官方仓库同一文件字节一致：
  `ffa20815444a4081953fd297ded9fa1fb9482e631bd730d9ad5289a5df55f520`。

| 组件 | 本机版本 | 门槛报告（另一台设备） |
| --- | --- | --- |
| MLT | 7.40.0（包 `7.40.0-2`） | 7.40.0（包 `7.40.0-2`），完全一致 |
| Python | 3.14.8 [MINGW GCC UCRT 16.2.0 64 bit] | 3.14.7 [MINGW GCC UCRT 16.2.0 64 bit] |
| 绑定 | `ucrt64/lib/python3.14/site-packages/mlt7.py` + `_mlt7.pyd` | 同路径同文件 |
| ffmpeg / pango / frei0r / SDL2 | 9.0.2 / 1.58.2 / 3.6.0 / 2.32.10 | 未逐项记录 |
| aiohttp / Pillow / websocket-client | 3.14.5 / 12.3.0 / 1.9.2 | 报告未列，但计划技术栈含 aiohttp+Pillow |

MLT 的硬依赖只有 5 个包，ffmpeg/pango/frei0r-plugins 都是 `optdepends`，所以必须显式加进闭包，
否则 `avformat`/`pango`/`frei0r.cairoaffineblend` 门槛服务起不来。此外 `test_mlt_controller` 需要
`aiohttp`，`test_mlt_compiler` 的精确字体分支需要 `PIL`，`test_playback_state` 经 `jypreview.shot.cdp`
需要 `websocket-client`。

pacman 的安装钩子在本方式下不会执行，`temp/mlt-build/bootstrap.ps1` 补了三件事：
生成 `ucrt64/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache`（`loader` 产者解 BMP/PNG 静帧要用），
跑一次 `glib-compile-schemas`（本机无 schema，空操作），以及用运行时自带 ffmpeg 生成合成夹具
`temp/mlt-fixtures/gate.mp4`（300×180 / 30 fps / 4 s H.264+AAC，帧随时间变化）和
`gate.wav`（48 kHz 立体声 s16le 4 s），与门槛报告的媒体类别一致。

环境文件 `temp/mlt-runtime/process-env.ps1` 只做本进程内的事：把 `ucrt64/bin` 前缀进 `PATH`，
设 `JY_PREVIEW_MLT_PYTHON`、`MLT_REPOSITORY/DATA/PROFILES_PATH/PRESETS_PATH`、`FREI0R_PATH`、
`FONTCONFIG_FILE/PATH`、`PYTHONNOUSERSITE`，并把 font/cache/TEMP 全部收在 `temp/mlt-runtime/cache/` 下。
未设 `MLT_REPOSITORY_DENY`，与门槛报告保持同一告警形态。

## 2. 门槛结果（本轮全部为新执行）

命令与 `2026-10-12-workspace-consolidation.md` P0-1 清单一致；`compileall`、`git diff --check`、
`test_timeline_model`、`test_playback_kernel.mjs`、`test_backend_lifecycle` 也已在本机跑通。

| 检查 | 退出码 | 观测 |
| --- | --- | --- |
| `test_timeline_model` | 0 | ok |
| `test_playback_kernel.mjs` | 0 | ok |
| `compileall -q scripts` | 0 | ok |
| `git diff --check origin/main..HEAD` | 0 | 无输出 |
| `test_backend_lifecycle` | 0 | 通过（报告里因默认 3.14 缺 aiohttp 而导入失败，本机默认解释器装有 aiohttp 3.14.3，该阻塞在本机不成立） |
| `test_mlt_runtime` | 0 | `PASS: MLT runtime gate`；见下节 |
| `test_mlt_compiler` | 0 | `ok: MLT graph composition regressions`（带 `JY_PREVIEW_TEST_FONT=C:\Windows\Fonts\simhei.ttf` 再跑一次仍为 0，精确字体别名分支实际执行） |
| `test_mlt_controller` | 0 | `ok: MLT playback controller phase, identity, and clock regressions` + `ok: MLT playback endpoint acceptance`；含 `ok: missing output kept target/buffering then failed after 1.663s` |
| `test_mlt_acceptance` | 2 | 9 个 section 全 PASS，仅 capture 证据门槛 FAIL（`temp/mlt-av-evidence.json` 不存在） |
| `benchmark_mlt` | 崩溃 1 次 / 通过 5 次 | 第 1 次 `access violation`，第 2–6 次退出 0 |
| `test_playback_state` | 1 | 两个草稿上各有独立失败点，见第 4 节 |

原始日志在 `temp/gate-logs/*.log`，JSON 证据在 `temp/mlt-runtime-gate.json`、`temp/mlt-benchmark-run2..6.json`。

### Runtime 门槛与历史数值对照

本机 `temp/mlt-runtime-gate.json` 与门槛报告记录的观测逐项一致：
请求位置 0/15/3/30 的 video==audio，每帧 `pcm_samples=3200`、`pcm_sum_max_error=1`，
`max_internal_av_delta_frames=0`，RGBA 216000 字节/帧，三层仿射混合探针 `[255,0,0]/[0,255,0]/[0,0,255]`，
`null` 与 `sdl2_audio` 均启动并推进到项目帧 3，负控制 `audio_offset_selfcheck.rejected=true`
（`Internal A/V offset is 2 project frames (maximum 1)`），`ok=true`。
必需服务 `avformat / loader / timewarp / frei0r.cairoaffineblend / pango / sdl2_audio / null / color / mix`
全部实例化成功。仍失败的只有可选模块 dlopen 告警：`glaxnimate-qt6, plus, qt6, resample, rnnoise, rtaudio,
rubberband, sox`（本机额外多一个 `rtaudio`，因为闭包没装 rtaudio），与报告同性质。

### Acceptance 分节结果

`evaluate determinism`、`FrameDescriptor parity`、`three-layer geometry`、`interval counts`、
`missing handle clamps`、`mixed audio`、`internal A/V PTS`（11 个 marker 位置 `max_internal_av_delta_frames=0`）、
`read-only non-mutation`（84631 帧拉取，`mtime_snapshot` 无变化）、`capture-evidence validator self-test`
（合成样例通过、13 个变异体拒绝）全部 PASS。FAIL 项只有 `av-evidence schema` / `av-evidence gate`：
capture lane 的真实证据在本机不存在。按报告要求，这不是可以跳过的门槛。

## 3. 新发现：原生 teardown 访问违例仍在，1.5 秒 drain 不足

`benchmark_mlt` 第 1 次运行硬崩（`exit status: -1073741819` 即 `0xC0000005`，JSON 报告未写出）。
faulthandler 落在 `scripts/jypreview/mlt_backend.py:805 _h_close → _shutdown`：
播放线程在关闭消费者/释放图时访问违例，主线程卡在 `close()` 投递的队列等待上。

这不是新问题——`scripts/jypreview/tools/benchmark_mlt.py:437` 的注释已经写了同一现象
（"A stopped-but-recently-playing 105-lane graph crashes native teardown (observed access violation in `_h_close`)"），
给出的缓解是 close 前 `time.sleep(1.5)` 让 consumer 先排空。本机该缓解不充分：

| 运行 | 结果 |
| --- | --- |
| run1 | 崩溃，`access violation`，无 JSON |
| run2–run6 | 退出 0，JSON 完整 |

6 次同夹具同参数运行崩溃 1 次（约 1/6），因此这是时序竞态而不是确定性失败，
不能把 1.5 秒 drain 当作已修复。停止规则上它属于 P1「DLL/原生门槛」同类问题：
`_shutdown` 里 `_stop_consumer → purge → tractor 释放 → listener thunk 释放` 的顺序仍需一次独立定位，
不要靠重试次数把它跑绿。

## 4. 新发现：`test_playback_state` 两处失败，均与本机无关

该检查需要「隔离解释器起的 serve + 真实浏览器页面 + 真实草稿」，本机满足，草稿取自
`D:\JianyingPro\JianyingPro Drafts`（NAS `\\192.168.0.247` 在线，素材可解析）。

### 4.1 `ended` 判定依赖帧边界（`YASHIDA 10月8日` / `5726AC1A-…`）

前 5 步全部通过（页面 ready、`backend=mlt`、有 `playback_id`、播放推进、生成内时间戳不回退、pause 冻结时钟），
第 6 步 `end seek did not enter ended` 失败。直接用后端 HTTP API 复现，不依赖浏览器：

```text
duration_us = 55766666
seek(t_us=55766666) -> phase=seeking -> ready, frame_index=1672, t_us=55733334
seek(t_us=55766667) -> phase=ended,  frame_index=1673
```

`PlaybackController._h_seek` 只在 `frame >= self._duration_frames` 时置 `ended`
（`mlt_backend.py:865`），而 `FrameRate.quantize` 是「取包含 t 的帧」的下取整
（`model/timeline.py:47-50`）。`55766666 × 30 / 1e6 = 1672.99998`，所以 `seek(duration_us)` 落在
最后一帧而非越过终点；只有 `t_us ≥ 55766667` 才 `ended`。也就是说：只要草稿的 `duration_us`
不是 `1/30 s` 的整数倍，`window.__renderAt(durationUs)` 永远不会进入 `ended`。

对照验证：在 `duration_us` 恰为整帧边界的草稿上，同一 API 调用 `seek(duration_us) -> ended` 直接通过
（`断刀8月4日` 时间线05 `7dac4cbc11623803` 42400000 µs → `ended/1272`；
`恒锋6月30日 (1)` 时间线06 `d65dde68bdc2a243` 51100000 µs → `ended/1533`）。
结论是判定边界差一，而非设备或素材问题。修法二选一，需要独立评审决定：
`_h_seek` 对 `target >= duration_us` 直接判 `ended`，或测试用 `duration_us + 1`；`docs/` 与 `SKILL.md`
里都没有把这条记为已知问题。

### 4.2 页面 JS 在无 root 的池条目上抛错（`断刀8月4日` / 时间线05 `2D35CF74-…`）

换成整帧边界草稿后失败点更早，停在第 2 步 `exact seek reported a non-canonical PTS`，页面状态是
`phase=error`、`error="Cannot read properties of undefined (reading 'style')"`、
`pool=2, armed=0, visible=2`、`displayedPtsUs=10000000`。

定位到 `scripts/jypreview/web/effects.js:65`：`applyTransform(entry.root, entry.layer.css …, state)`
没有对 `entry.root` 判空，而 `applyTransform`（`effects.js:29`）只守 `css`，进 `state` 分支即
`node.style.filter = …`（`effects.js:40`）。当条目可见但未装根（`armed=0`）时 `entry.root` 为
`undefined`，异常被 `app.js` 的 `enterMltError` 捕获并写成 `phase=error`。同样是逻辑缺陷，
与本机无关；本轮未改代码，留待有独立审查的修复。

## 5. 本机播放节律明显低于门槛设备，B1 类验收不宜在本机做

`benchmark_mlt` 5 次成功运行的观测高度一致（合成 105 片段夹具，sink `sdl2_audio`，
Windows-11-10.0.26200 / Intel64 Model 151 / 12 逻辑核）：

| 指标 | run2 | run3 | run4 | run5 | run6 |
| --- | --- | --- | --- | --- | --- |
| cold open (ms) | 7176.8 | 7271.0 | 7352.0 | 7422.0 | 7154.0 |
| seek p50 (ms) / 20 次未命中 | 167.0 / 0 | 170.0 / 0 | 164.3 / 0 | 162.8 / 0 | 166.9 / 0 |
| 30 s 窗口内观测帧 / 期望 | 49 / 900 | 49 / 900 | 49 / 900 | 49 / 900 | 49 / 900 |
| `output_fps`（帧槽轮询） | 1.617 | 1.617 | 1.617 | 1.611 | 1.617 |
| `output_fps_clock` | 10.49 | 10.53 | 10.52 | 10.71 | 10.53 |
| `clock_span_us`（30.3 s 墙钟内） | 10.6 s | 10.6 s | 10.6 s | 10.8 s | 10.6 s |
| `dropped_frames` | 270 | 270 | 270 | 270 | 270 |
| 内部 A/V 稳态差（帧） | 0 | 7 | 0 | 0 | 0 |
| `failures` | 空 | 空 | 空 | 空 | 空 |

音频主控时钟在 30.3 s 墙钟里只推进约 10.6 s（≈0.35× 实时），五次都稳定在这个量级。
这跟上一台设备记录的浏览器侧 `29.999238 fps` 不是同一个量级的东西，说明：
播放性能结论不可跨设备搬运，报告 P0-2 的「45 秒 1080p 夹具 direct-consumer + 浏览器 B1≥30fps」
在本机测出来的数只能描述本机，不能作为 `codex/stale-seek-fix-20261002` 的合并证据。
`seek` 精度（20/20 命中目标帧、p50 167 ms）与「时间戳不回退」在本机是好的，可以用作回归哨兵。

## 6. 仍未验证

- capture lane：`temp/mlt-av-evidence.json` 不存在；同步采集、normal/dropped-video 双模式、
  外部 ≥240fps 屏幕+音频标定、匹配的剪映真实导出对照，本机全部缺失，未做任何绕行。
- T1/T2 实际呈现与设备发射、T3/T4 精度：未采集。
- DLL 分支：`temp/dll-native-preview-review-hardening/`（`4669` 的原始证据）没随仓库过来，
  `scripts/jypreview/native/bin|obj` 在本机为空，Task 1 的 `PlayerWin init_rejected` 与
  `FrameReader pts_out_of_range` 本机尚未复现。
- `codex/stale-seek-fix-20261002` 未合并，其合并前三道门槛（完整 controller 重跑、B1 实测、独立审查）
  本机只满足第一道的 controller 部分。
- 4669/release 工作区「快进到 main」属于另一台设备，本机无法代做。

## 7. 下一台设备的最短复现路径

脚本目前都在被 `.gitignore` 忽略的 `temp/` 下（`temp/mlt-build/`、`temp/mlt-runtime/process-env.ps1`），
不入库就换不了机器。入库与否待决定。入库后：

```powershell
# 1) 解析闭包并解包（约 212 MiB 下载 / 634 MB 落地，几分钟）
py -3.14 temp/mlt-build/prepare_mlt_runtime.py resolve
py -3.14 temp/mlt-build/prepare_mlt_runtime.py build

# 2) 补 pacman 钩子 + 生成合成夹具
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\bootstrap.ps1

# 3) 单个门槛（run_gate.ps1 负责 source 环境、PYTHONPATH、原始日志与退出码）
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\run_gate.ps1 `
  -Module jypreview.tools.test_mlt_runtime -UseFixtures `
  -ExtraArgs '--json temp/mlt-runtime-gate.json'
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\run_gate.ps1 `
  -Module jypreview.tools.test_mlt_compiler -Font 'C:\Windows\Fonts\simhei.ttf'
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\run_gate.ps1 `
  -Module jypreview.tools.test_mlt_controller
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\run_gate.ps1 `
  -Module jypreview.tools.test_mlt_acceptance -Font 'C:\Windows\Fonts\simhei.ttf' `
  -ExtraArgs '--av-evidence temp/mlt-av-evidence.json'
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\run_gate.ps1 `
  -Module jypreview.tools.benchmark_mlt -ExtraArgs '--json temp/mlt-benchmark.json'

# 4) 浏览器状态机门槛需要先有跑在隔离解释器上的 serve
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\server.ps1 -Action start
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\run_gate.ps1 `
  -Module jypreview.tools.test_playback_state `
  -Env 'JY_PREVIEW_TEST_DRAFT=<did> JY_PREVIEW_TEST_TIMELINE=<tid>'
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\server.ps1 -Action stop
```

草稿 `did` 从 `GET /api/drafts?q=<名称>` 取；测试脚本默认值 `timeline-primary` 在本机草稿里解析不到，
必须显式给 `tid`。注意 `test_playback_state` 收尾会把它连的 server 一并关掉，属正常行为。

## 8. 证据索引

- 门槛日志（原始 stdout+stderr，含退出码）：`temp/gate-logs/`
- 运行时门槛 JSON：`temp/mlt-runtime-gate.json`
- Benchmark JSON：`temp/mlt-benchmark-run2.json` … `run6.json`（run1 崩溃未产出）
- 包清单与逐包 SHA-256：`temp/mlt-runtime/package-manifest.json`
- 依赖闭包：`temp/mlt-build/closure.json`
- 合成夹具：`temp/mlt-fixtures/gate.mp4`、`gate.wav`
- 构建/运行脚本：`temp/mlt-build/prepare_mlt_runtime.py`、`bootstrap.ps1`、`run_gate.ps1`、`server.ps1`
- 运行时环境：`temp/mlt-runtime/process-env.ps1`
