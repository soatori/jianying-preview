# 剪映 DLL 原生预览器重建设计

**状态：** 按独立审查意见修订，待审阅本文档

## 目标

在不启动 JianyingPro 客户端 UI 的条件下，通过独立预览器正确播放国内版剪映草稿。预览帧必须来自剪映原生 DLL；当前仓库的 GStreamer/GES 与浏览器媒体合成后端不再作为最终播放实现。首期覆盖 YASHIDA 9 月 24 日测试草稿的完整“成片”时间线，并与随测试包提供的 MP4 导出文件比较。

## 已验证事实与限制

- 本机测试目标为 Jianying Pro 国内版 11.5.3.14501；`videoeditor.dll` SHA-256 为 `E5E4020BD5B37EB19968473E19D7246CA5EFE80064A039136341A27B1FD5D8B7`。
- `PlayerWin` 导出播放、定位、取帧和离屏表面方法；`Server`、`Session`、`VeWrapper` 也有导出，但构造配置与生命周期尚未恢复。尚未证明这些对象能独立打开草稿并产生完整时间线帧。
- `lvve::FrameReader::create()` 已在无剪映 GUI 的独立进程中成功创建；内部辅助调用能输出 1920×1080 RGBA 首帧，且与同源 FFmpeg 首帧逐字节相同。该辅助调用将时间写死为 0；直接时间回调目前不能稳定返回像素。
- 现有 `GstGesBackend` 仅将 IR 中的媒体片段、起始时间、速度等字段转成 GES clip，不能完整处理草稿的文字、合成、画面效果与调整层。浏览器 `Stage` 负责另一套部分近似的画面合成。
- YASHIDA 草稿有 14 条轨道，包括复合片段、视频、文字和音频；现有解密副本包含 71 个文字素材、22 个视频引用、32 个音频引用，并使用调整层、HSL、美颜类效果和聚光灯视频效果。五个现成导出锚点为 0.5、5、20、40、50 秒。
- 研究报告和逐项证据在 `temp/reverse-skill-jianying/analysis.md`；旧 GES/browser 对比在 `temp/engine-replacement-test/comparison.md`。这些是临时研究材料，不属于运行时依赖。

## 架构

### 重建前的原生取帧门槛

- 先做最小 C++ 垂直验证，不先重写合成器或清理旧播放代码。`PlayerWin` 路径必须在无 JianyingPro UI、无宿主认证绕过时打开这份 YASHIDA 活动时间线并返回完整合成帧；`FrameReaderWin` 路径必须在同一条件下为 C0308.MP4 返回任意素材时刻的独立帧。
- `PlayerWin` 路径须完成 100 个跨时间线位置请求，`FrameReaderWin` 路径须完成 100 个分散素材时间请求和 3 秒连续取帧。所有帧都要匹配当前请求代次、PTS 偏差不超过一帧且无空/旧帧。只有某条路径通过自己的门槛，才进入对应的大规模实现：完整 PlayerWin 路径接入外部预览；FrameReader 路径才重建时间线合成器。
- 两条原生路径都不通过时，停止播放重建与旧链路清理，继续报告 DLL 初始化/取帧的具体阻塞；不改用 FFmpeg，也不把首帧成功当成播放能力。

### 草稿读取与宿主隔离

- 保留 Python 的草稿发现、只读解密、时间线解析、资产路径解析和属性/轨道 UI。原草稿、`Timelines/` 和测试导出只读。
- `videoeditor.dll` 不加载到常驻 Python HTTP 服务。新增 MSVC x64 C++ 子进程作为唯一播放宿主；它从本机国内版安装目录加载 DLL 及其同版本依赖。解密仍走现有短命 worker。
- 当前没有可用的公开预览 SDK；调用面按该 DLL 私有 C++ ABI 和哈希版本锁定，不承诺跨版本兼容。
- 子进程启动前校验目标版本和 DLL 哈希。版本不符、依赖缺失或初始化失败时返回明确错误，不静默切到 GStreamer、浏览器视频解码或 FFmpeg。
- 不伪造 `external_sid`、不绕过宿主认证、不启动或隐藏运行 JianyingPro UI。子进程使用 DLL 可用的离屏输出路径。

### 两级原生渲染路径

1. **完整时间线优先：** 恢复 `Server/Session/VeWrapper/PlayerWin` 的合法初始化流程，用 `PlayerWin` 离屏取得剪映已经合成的 RGBA 帧。若此路径可用，属性与时间线仍由现有解析器提供，预览画面直接显示原生合成结果。
2. **原生解码加重建合成：** 若完整时间线对象不能独立初始化，恢复 `FrameReaderWin` 的任意时间回调 ABI，以 DLL 帧解码为基础重写播放调度、图层合成、文字/变换/音画同步和 YASHIDA 实际用到但 DLL 不提供的效果。不得将首帧辅助调用当作可播放的随机取帧接口。

第二条路径依旧必须从 DLL 稳定取到任意时间的视频帧。该能力若最终无法恢复，项目不能达到“剪映 DLL 原生预览”目标；届时报告具体阻塞，不以 FFmpeg 替代解码后宣称完成。

### 接口与生命周期

- 复用现有 `PlaybackBackend` 操作与 `/api/backend/*` 路由：`open`、`seek`、`render_at`、`play`、`pause`、`snapshot`、`close`。前端时间单位继续使用整数微秒。
- 将现有 `PlaybackBackend` 契约补齐连续帧：`render_at(t_us, generation)` 返回一帧；`pull_frame(timeout_ms, generation)` 返回连续播放帧或 `None`。两者均返回 `{generation, pts_us, width, height, format, buffer}`，其中 `format` 首期固定为 `RGBA`。
- Python 后端启动一个原生子进程并串行发送请求。IPC 请求以 `protocol_version/request_id/generation/op/payload` 为字段；响应先返回长度前缀元数据，再附 RGBA 字节，避免 base64 化。控制面、`/api/backend/render` 和 multipart `/api/backend/stream` 都传递 generation 和 PTS。
- 前端只显示仍对应当前 seek/play generation 的帧；开始新 seek 时关闭并重开旧 stream，清掉传输队列中的旧帧。关闭预览时关闭 DLL 对象并退出子进程。
- capability 在现有响应中新增 `render_path`（`playerwin` 或 `frame-reader-compositor`）、`video_decoder`（固定 `videoeditor.dll`）、`compositor`（`videoeditor.dll` 或 `jypreview`）、`audio_path`（`videoeditor.dll`、`browser-audio-scheduler` 或 `none`）及 `unsupported_effects`。保留现有 `exact_frame/audio/transitions/effects` 字段，并按真实运行结果填写。

### 时间线查询与预览 UI

- 保留 `FrameDescriptor` 和当前时间线/属性 UI。把 `Stage` 中供 UI 查询的层展平、复合片段时间映射、`primaryAt`、`timeAt`、可见层查询迁到纯 `TimelineState`；它只接收 IR 和 `t_us`，不持有 DOM 或媒体节点。
- `TimelineState.at(t_us)` 至少提供可见层、主视频层、每层局部时间/素材时间、嵌套深度和音频活动片段。属性栏、选中层和 `window.__snapshot()` 改用该结果；新渲染器只负责画面，不再兼任 UI 状态来源。
- 完整 PlayerWin 路径优先由 DLL 输出合成音频。FrameReader 路径保留现有浏览器 `AudioScheduler` 作为音频补充，补齐该测试草稿实际使用的混音、静音、音量、淡入淡出和剪切点语义；音频补充不得替换 DLL 视频解码。

### 导出对照基线

- 现有 MP4 与草稿的五个文字锚点吻合，但目前没有证据证明它们来自同一次导出；也没有 DLL 完整渲染帧作为像素误差基线。
- 实施前先核实导出文件与活动“成片”时间线的对应关系，并固定帧率、PTS、方向、分辨率和色彩空间对齐规则。不能证明是同一草稿导出时，该 MP4 只用于场景/时间线对应性检查，不用于 PSNR/SSIM pass/fail；像素级验收须等到取得来源明确的同草稿导出参考。
- 只有匹配的导出基线确认后，才通过多处静态/移动/文字/效果样本测量编码和色彩转换残差，先锁定 PSNR、SSIM 阈值，再将其作为原生预览验收门槛。现有源帧对合成导出的 8.719 dB 不作为目标阈值依据。

### 旧播放链路清理

- 新后端通过完整验收后，删除 `GstGesBackend`/`clips_from_frame_ir`、`BrowserPlaybackBackend`、旧 `Stage` DOM/视频合成与 `MediaScheduler`，以及只验证这些实现的 GES/browser 渲染测试和工具。
- 在删除前迁出并保留 `Stage` 的纯时间线查询职责到 `TimelineState`；保留草稿读取/解密/解析、外部预览 UI、轨道/属性面板、`PlaybackController`、`AudioScheduler`（仅在 Reader 路径作音频补充）和通用播放回归工具。
- 删除边界只限上一条列出的旧渲染实现；新后端及整稿回归门槛通过前，旧实现和测试保持可运行。重写后的预览输出不得静默回退到旧后端。
- 切换前旧实现只可作为明确的诊断选项，不能静默出现在剪映原生验收结果中。

## 验收

- **进程：** 运行外部预览器时不启动 `JianyingPro.exe`，预览服务进程不映射 `videoeditor.dll`，只有隔离子进程加载目标 DLL。
- **随机访问：** 同一素材执行 100 次跨时段随机 seek，均收到请求代次匹配的有效帧，实际 PTS 偏差不超过一帧；不得返回旧帧或空帧。
- **整稿图像：** 对完整 YASHIDA 时间线，在五个锚点以及所有已用转场/效果边界采集输出。先按已确认的导出基线对齐 PTS、方向、分辨率和色彩空间；逐点记录 PSNR、SSIM、MAE。只有基线校准完成后才启用其固定数值阈值。无黑帧、错层、缺失文字和未报告的效果缺口是硬性条件。
- **连续播放与音频：** 30 秒实时播放的丢帧率低于 1%。音频样本检查覆盖素材切入/切出、来源时间、静音/音量、淡入淡出及混音；匹配的音频参考确认后比较波形/能量分布，否则只报告内容检查、不判定相似度。音画同步偏差不超过一帧（30 fps 时约 33.3 ms）。
- **只读与版本：** 测试前后原始草稿包和 MP4 SHA-256 不变；仅支持本机已验证的国内版 11.5.3.14501 哈希。国际版和其他国内版不在首期兼容承诺内。
