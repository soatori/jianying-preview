# 剪映 DLL 原生预览实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 不启动 JianyingPro UI，以剪映原生 DLL 帧播放 YASHIDA 9 月 24 日完整“成片”时间线，并按已确认的同源 MP4 基线验收。

**Architecture:** Python 继续负责草稿发现、只读解密、时间线与资产路径解析；只有 MSVC x64 子进程加载版本锁定的 DLL。先验证完整 PlayerWin 路径，失败后再验证 FrameReaderWin；两者都失败就停止重建。选定路径后接入现有后端 API 与时间线 UI；Reader 路径才实现 jypreview 合成器和浏览器音频补充。旧链路只在新后端整体验收通过后删除。

**Tech Stack:** 现有 Python/aiohttp、MSVC x64 C++、浏览器 ES modules、已列入 requirements 的 Pillow；测试继续用仓库现有 Python 工具和 Node 内置 assert。

**Spec:** docs/superpowers/specs/2026-10-05-jianying-dll-native-preview-design.md

## Global Constraints

- 本机测试目标为 Jianying Pro 国内版 11.5.3.14501；videoeditor.dll SHA-256 为 E5E4020BD5B37EB19968473E19D7246CA5EFE80064A039136341A27B1FD5D8B7。
- videoeditor.dll 不加载到常驻 Python HTTP 服务。新增 MSVC x64 C++ 子进程作为唯一播放宿主；它从本机国内版安装目录加载 DLL 及其同版本依赖。解密仍走现有短命 worker。
- 不伪造 external_sid、不绕过宿主认证、不启动或隐藏运行 JianyingPro UI。
- 版本不符、依赖缺失或初始化失败时返回明确错误，不静默切到 GStreamer、浏览器视频解码或 FFmpeg。
- 原草稿、Timelines/ 和测试导出只读；测试前后 SHA-256 不变。
- 前端时间单位继续使用整数微秒；帧格式固定为 RGBA。
- IPC 请求字段为 protocol_version/request_id/generation/op/payload；响应先返回长度前缀元数据，再附 RGBA 字节，避免 base64 化。
- PlayerWin 路径须完成 100 个跨时间线位置请求；FrameReaderWin 路径须完成 100 个分散素材时间请求和 3 秒连续取帧。所有帧都要匹配当前请求代次、PTS 偏差不超过一帧且无空/旧帧。
- 30 秒实时播放丢帧率低于 1%；音画同步偏差不超过一帧（30 fps 时约 33.3 ms）。
- 不能证明 MP4 是同一草稿导出时，只用于场景/时间线对应性检查，不用于 PSNR/SSIM pass/fail；现有源帧对合成导出的 8.719 dB 不作为目标阈值依据。
- 新后端及整稿回归门槛通过前，旧实现和测试保持可运行；新预览不得静默回退到旧后端。

## Review Focus

- DLL 哈希不符、依赖缺失或初始化被宿主拒绝：明确失败且不回退。[Task 1]
- 素材路径缺失或文件不可读：错误可见，不能伪造黑帧作为成功结果。[Task 2, Task 5]
- 嵌套/重复复合片段、变速和片段边界：局部时间、素材时间及半开区间查询一致。[Task 3, Task 5]
- 调整层、HSL、美颜、聚光灯和文字等实际用到的能力：无缺字/错层；不支持项进入 unsupported_effects。[Task 5, Task 6]
- 快速连续 seek、重开 stream 或关闭预览：旧 generation 的帧不能显示或进入新 stream。[Task 2, Task 4]

---

### Task 1: 建立隔离 DLL 宿主并通过原生帧门槛

**Files:**
- Create: scripts/jypreview/native/preview_host.vcxproj
- Create: scripts/jypreview/native/preview_host.cpp
- Test: scripts/jypreview/tools/test_dll_native_gate.py
- Artifacts: temp/dll-native-preview/

**Interfaces:**
- IPC v1 请求：4 字节 little-endian 元数据长度，后接 UTF-8 JSON；字段为 protocol_version=1、request_id、generation、op、payload。
- 响应：相同长度前缀加 JSON；取帧时元数据含 generation、pts_us、width、height、format=RGBA、byte_length，后接恰好 width×height×4 个字节。stdout 只传协议数据，诊断写 stderr。
- 子进程校验安装版本和上述 SHA-256，并只从该安装目录加载 DLL 及依赖；不创建认证凭据、不启动 JianyingPro.exe。

- [ ] **Step 1: 写门槛失败测试**
  - test_wrong_dll_hash_fails_closed：错误哈希必须返回版本错误，不能加载 DLL。
  - test_wrong_version_fails_closed、test_missing_dependency_fails_closed、test_initialization_rejected_fails_closed：三种启动错误都返回明确错误，不崩溃、不打开预览、不回退。
  - test_playerwin_random_timeline_frames：YASHIDA 活动“成片”时间线的 100 个跨时间请求都返回非空 RGBA、当前 generation，PTS 偏差不超过一帧。
  - PlayerWin 未通过时才运行 test_framereader_random_source_frames：C0308.MP4 的 100 个分散素材时刻和连续 3 秒均返回有效帧；否则记录具体阻塞并停止后续任务。

- [ ] **Step 2: 运行门槛测试确认缺少宿主/能力时失败**

  运行：从 scripts/ 执行 python -X utf8 -m jypreview.tools.test_dll_native_gate。

  预期：宿主尚不存在时测试明确失败；两条路径都失败时保留旧后端、记录错误并停止。

- [ ] **Step 3: 实现最小宿主和合法初始化路径**

  使用 Windows CNG 校验 SHA-256，以受支持的 DLL 初始化流程调用 PlayerWin。仅在 PlayerWin 门槛失败时恢复 FrameReaderWin 任意时刻回调；不把固定 0 秒的辅助首帧调用视作随机取帧能力。

- [ ] **Step 4: 重建 x64 宿主并重跑门槛**

  运行：msbuild scripts/jypreview/native/preview_host.vcxproj /p:Configuration=Release /p:Platform=x64，再从 scripts/ 运行 python -X utf8 -m jypreview.tools.test_dll_native_gate。

  预期：测试只报告通过的 render_path；确认未启动 JianyingPro.exe、Python 服务进程未加载 videoeditor.dll、目标 DLL 只由隔离宿主加载；所有探测结果和阻塞写入 temp/dll-native-preview/。

- [ ] **Step 5: Commit Task 1 files only**

  feat: add isolated Jianying DLL preview host

### Task 2: 接入 Python PlaybackBackend 与现有 API

**Files:**
- Modify: scripts/jypreview/playback_backend.py:24-38
- Modify: scripts/jypreview/server/handlers_backend.py:23-191
- Test: scripts/jypreview/tools/test_dll_preview_backend.py

**Interfaces:**
- 新增 JianyingDllBackend；保持现有 open(draft, timeline, *, profile) / close / snapshot 操作。
- seek(t_us, generation)、play(rate, generation)、pause(generation)、render_at(t_us, generation)、pull_frame(timeout_ms, generation) 传递 generation。
- render_at 返回 {generation, pts_us, width, height, format, buffer}；pull_frame 超时返回 None。
- snapshot 返回当前 generation/phase/video PTS；只有能取得真实音频时钟时才报告 audio_pts_us，否则为 null，不用 timeline t_us 冒充音频时钟。
- capability 保留 exact_frame/audio/transitions/effects 并按真实运行结果填写；新增 render_path（playerwin 或 frame-reader-compositor）、video_decoder（videoeditor.dll）、compositor（videoeditor.dll 或 jypreview）、audio_path（videoeditor.dll、browser-audio-scheduler 或 none）及 unsupported_effects。
- 复用单线程 NativeHandle 串行 IPC；open 的 profile 携带 draft_root、timeline_path、timeline_id、完整 timeline IR 和 duration_us，不传只含媒体片段的旧 GES profile。

- [ ] **Step 1: 写 backend/IPC 测试**
  - test_frame_contract_and_generation：每个返回帧字段正确，旧 generation 不返回为当前帧。
  - test_missing_host_and_bad_ipc_fail_explicitly：宿主缺失、错误长度前缀和进程退出都返回明确错误，绝不切到旧 backend。

- [ ] **Step 2: 运行测试确认失败**

  从 scripts/ 运行 python -X utf8 -m jypreview.tools.test_dll_preview_backend；预期缺少 JianyingDllBackend 和 generation-aware IPC。

- [ ] **Step 3: 实现串行子进程 transport 和 backend**

  用标准库 subprocess 读写长度前缀协议；对短读、无效元数据、request_id/generation 不匹配及意外退出报错。Python HTTP 服务不加载 DLL。

- [ ] **Step 4: 更新 /api/backend/* 控制面、render 与 stream**

  render 和每个 multipart frame 均附 generation、PTS；seek 更新当前 generation；close 和 app shutdown 都关闭 DLL 对象并退出子进程。

- [ ] **Step 5: 运行 backend 测试并提交本任务文件**

  预期：API 保持既有路由；错误不触发静默 fallback。Commit: feat: add DLL playback backend IPC

### Task 3: 把时间线查询从 Stage 移到 TimelineState

**Files:**
- Create: scripts/jypreview/web/timeline-state.js
- Modify: scripts/jypreview/web/render.js:79-405
- Modify: scripts/jypreview/web/app.js:120-124, 390-440, 640-700, 967-982
- Test: scripts/jypreview/tools/test_timeline_state.mjs

**Interfaces:**
- new TimelineState(ir).at(t_us) 只读 IR，返回 {visible_layers, primary_video, audio_segments}。
- 每个可见层包含 {layer_id, layer, local_time_us, source_time_us, depth}；primary_video 是相同记录或 null；audio_segments 是当前活动音频层。

- [ ] **Step 1: 写纯查询测试**

  test_nested_repeated_layers_and_half_open_boundaries 断言复合时间映射、重复片段、局部/素材时间、嵌套深度，以及相邻片段边界只命中一侧；test_active_audio_layers 断言音频活动区间。

- [ ] **Step 2: 运行测试确认失败**

  运行：node scripts/jypreview/tools/test_timeline_state.mjs。预期：TimelineState 模块不存在。

- [ ] **Step 3: 实现 TimelineState 并接入现有 UI**

  将 Stage.timeAt/primaryAt 的纯时间计算迁入新类；Stage 继续负责渲染。属性栏、选中层、主视频层、音频活动片段和 window.__snapshot() 使用同一 at(t_us) 结果，不读取 DOM/媒体节点推断时间线状态。

- [ ] **Step 4: 运行 Node 查询测试并提交本任务文件**

  预期：两个测试通过，Stage 的显示顺序和已有选中层 UI 不变。Commit: refactor: separate timeline state from stage rendering

### Task 4: 让 seek 和连续 stream 丢弃旧帧

**Files:**
- Modify: scripts/jypreview/web/app.js:35-170, 491-510, 673-681, 700-740, 920-940
- Modify: scripts/jypreview/web/playback.js:202-253
- Modify: scripts/jypreview/tools/test_native_preview.py

**Interfaces:**
- PlaybackController 是 generation 唯一来源；native seek/render/stream 请求都携带该 generation。
- app.js 的 seek() 和 window.__renderAt 统一调用 PlaybackController.seek()；renderTimelineAt(t_us, context) 将 context.generation 交给 nativeRenderAt(t_us, generation)。nativeRenderAt 校验响应 generation，不自行递增 generation 或用 syncExternal 覆盖 controller 状态。
- activateNativeBackend 的首帧使用 controller 当前 generation；togglePlay 的 play/pause 请求及 stream URL 也传递当前 generation。
- 新 generation 开始时先移除旧 img src 以中止旧 stream、隐藏旧画面，再以新 generation 重开；只有新请求首帧到达后显示。
- 服务器及前端均拒绝 generation 不匹配或 PTS 超过一帧的帧。

- [ ] **Step 1: 扩展 native preview 回归断言**

  覆盖 seek 后 generation 递增、快速连续 seek、stream 重开、旧响应延迟到达、pause 和 close；断言任何旧 generation 帧都不显示。

- [ ] **Step 2: 运行回归确认当前实现暴露旧帧**

  运行：从 scripts/ 执行 python -X utf8 -m jypreview.tools.test_native_preview。预期：新增 generation/race 断言失败。

- [ ] **Step 3: 将 controller generation 传到 API 和 img stream**

  renderTimelineAt 的 native 分支带 context.generation 调用 nativeRenderAt；seek 与 window.__renderAt 都经过 PlaybackController.seek()。启动、play/pause 和 stream URL 使用同一 controller generation；新 seek 替换旧 stream；close 时中止 stream、清空帧并关闭 object URL。

- [ ] **Step 4: 重跑 native preview 回归并提交本任务文件**

  预期：延迟旧响应、旧 multipart 帧及关闭后的帧均被忽略。Commit: fix: discard stale native preview frames

### Task 5: 仅为 FrameReaderWin 路径实现时间线合成和音频补充

**Files:**
- Create: scripts/jypreview/native_compositor.py
- Modify: scripts/jypreview/playback_backend.py
- Modify: scripts/jypreview/web/media.js:16-89
- Modify: scripts/jypreview/web/app.js:117-141, 495-510, 713-730
- Test: scripts/jypreview/tools/test_dll_compositor.py
- Test: scripts/jypreview/tools/test_playback_kernel.mjs

**Interfaces:**
- 此任务只在 Task 1 选中 frame-reader-compositor 时执行；PlayerWin 路径直接使用 DLL 完整合成帧并跳过本任务。
- compose_frame(ir, t_us, decode_frame) -> {width, height, format, buffer}；decode_frame(path, source_time_us) 只能通过 FrameReaderWin 取得视频源帧。
- Reader 路径的 capability 为 video_decoder=videoeditor.dll、compositor=jypreview、audio_path=browser-audio-scheduler。
- activateNativeBackend 保存返回的 capabilities。app.js 只在 audio_path=browser-audio-scheduler 时按原生 snapshot 的 t_us/phase 驱动 AudioScheduler；pause/close 时停音。PlayerWin 使用 DLL 音频时清掉浏览器音频，避免重复播放。
- window.__snapshot 暴露 Reader AudioScheduler 的当前素材位置；PlayerWin 从 backend snapshot 暴露 audio_pts_us。没有独立音频位置时，Task 6 的同步门槛不通过。

- [ ] **Step 1: 写合成与音频行为测试**

  合成测试用小型 RGBA 输入断言层序、变换、文字、片段边界和实际 YASHIDA 效果；每个无法实现的效果必须出现在 unsupported_effects。音频测试断言 source trim、muted、volume、fade-in/fade-out、混音和 seek 后重新对齐。

- [ ] **Step 2: 运行测试确认缺少 compositor/语义**

  运行：python -X utf8 -m jypreview.tools.test_dll_compositor（scripts/）和 node scripts/jypreview/tools/test_playback_kernel.mjs。预期：Reader 合成与淡入淡出断言失败。

- [ ] **Step 3: 用 Pillow 合成 Reader 帧并补齐 AudioScheduler**

  复用现有 Pillow，不新增依赖；按 IR 的复合映射解码源帧，绘制文字/变换/图层及 YASHIDA 实际效果。只对 Reader 路径启用浏览器音频补充，不替代 DLL 视频解码；将原生 snapshot 的时间和播放状态接入 app.js 音频调度，PlayerWin 不重复播放浏览器音频。

- [ ] **Step 4: 运行两组测试并提交本任务文件**

  预期：合成像素断言和音频边界断言通过；未知效果明确报告。Commit: feat: compose FrameReader preview timeline

### Task 6: 校准导出基线并完成整稿验收

**Files:**
- Create: scripts/jypreview/tools/compare_native_export.py
- Modify: scripts/jypreview/tools/test_native_preview.py
- Artifacts: temp/dll-native-preview/

- [ ] **Step 1: 固定草稿/导出来源和对齐规则**

  记录草稿包及 MP4 的前后 SHA-256；确认是否为同一草稿导出；固定帧率、PTS、方向、分辨率、色彩空间对齐。不能确认同源时将 MP4 限定为场景/时间线检查，不设像素 pass/fail。

- [ ] **Step 2: 写可复现的图像比较测试**

  比较 0.5、5、20、40、50 秒锚点及已用转场/效果边界，记录 PSNR、SSIM、MAE 到 temp/dll-native-preview/。同源基线确认后才从测量结果锁定数值阈值；未确认时不产生阈值。

- [ ] **Step 3: 运行完整 YASHIDA 和播放验收**

  运行：从 scripts/ 执行 python -X utf8 -m jypreview.tools.test_native_preview；图像比较运行 python -X utf8 -m jypreview.tools.compare_native_export --draft $env:JY_PREVIEW_TEST_DRAFT --timeline active --export $env:JY_PREVIEW_TEST_EXPORT。

  扩展 test_native_preview.py：30 秒内记录 multipart 每帧的 generation、X-Backend-PTS-US、单调时钟到达时间及帧数；同时从选中的音频路径记录实际媒体位置/时间戳，并用同一单调时钟关联音频与视频事件，不得只用 state.tUs 同时推导两侧。以时间线帧率计算丢帧率，以音频/视频事件时间计算同步偏差；任一侧缺少可测时钟时，该门槛保持未通过。

  预期：请求代次有效、PTS 偏差不超过一帧、丢帧率低于 1%、音画同步不超过一帧；无黑帧、错层、缺字或未报告效果缺口；有匹配音频参考时比较波形/能量分布，无参考时只报告内容检查，不判相似度。

- [ ] **Step 4: 验证源文件哈希不变并提交验收工具**

  预期：草稿包和 MP4 前后 SHA-256 完全一致；所有结果写入 temp/。Commit: test: gate native preview on full timeline evidence

### Task 7: 整体验收通过后移除旧渲染实现

**Files:**
- Modify: scripts/jypreview/playback_backend.py
- Modify: scripts/jypreview/server/handlers_backend.py
- Modify: scripts/jypreview/web/backend.js
- Modify: scripts/jypreview/web/app.js
- Modify: scripts/jypreview/web/render.js
- Modify: scripts/jypreview/web/media.js
- Remove only tests/tools that exclusively validate deleted GES/browser render paths.

- [ ] **Step 1: 列出旧实现的全部引用与专用测试**

  搜索 GstGesBackend、clips_from_frame_ir、BrowserPlaybackBackend、Stage DOM/video composition、MediaScheduler；先迁走仍由 UI 查询、AudioScheduler 或通用 PlaybackController 使用的逻辑。

- [ ] **Step 2: 删除旧后端和其专用测试/工具**

  仅在 Task 6 全部门槛通过后删除；保留草稿读取/解密、TimelineState、属性与轨道 UI、PlaybackController、Reader 路径 AudioScheduler 及通用回归工具。activateNativeBackend 启动失败时显示错误并停止，不自动转 browser；只有用户显式选择 backend=browser 诊断模式时才启用旧渲染路径。

- [ ] **Step 3: 运行最终回归并提交清理**

  运行 native preview、TimelineState 和 playback kernel 回归。预期：默认只使用已通过门槛的 DLL 路径，关闭/失败时返回明确错误。Commit: refactor: remove legacy preview renderers

## Self-Review

- **Spec coverage:** 两条原生路径及停止门槛在 Task 1；进程隔离、接口、generation、capability 在 Task 1–4；Reader 合成和音频在 Task 5；导出基线与所有运行门槛在 Task 6；旧链路清理在 Task 7。
- **Step scan:** 每项测试、实现、验收和提交都有独立结果；私有 ABI 不预设签名，必须以合法初始化探测通过为门槛。
- **Type consistency:** Python 帧统一为 generation/pts_us/width/height/format/buffer；TimelineState 统一返回 visible_layers/primary_video/audio_segments。
- **Review Focus:** 五类输入各自绑定 Task 1–5 的回归；音频、整稿和导出来源另在 Task 6 验收。
- **Proportion:** 计划保留路径、接口、门槛和命令，未展开 DLL 内部 ABI 或合成算法实现细节。
