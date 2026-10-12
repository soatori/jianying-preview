# 时间线播放与预览核心重构设计

**状态：** 待用户审阅

**日期：** 2026-10-01

## 目标

重构剪映草稿预览的播放核心，使时间线位置成为唯一的播放时间来源。对任意时间 `t`，系统先按项目帧率映射到唯一采样帧，再确定当前活动片段、素材时间、轨道层序和最终画面；Seek 不依赖此前播放位置。

首期优先保证片段边界、素材 trim、常速/倒放、多轨合成、基础变换、音频混音和连续播放。私有特效无法复刻时保留其时段与层级，并显示告警或占位。

## 范围与约束

- 保留现有剪映草稿解密、解析、素材路径解析能力和大致 UI 框架。
- 播放核心使用项目自己的 `TimelineModel`；草稿原始 JSON 只由 `DraftAdapter` 读取。
- 不要求兼容旧播放实现；新核心通过验收后，旧播放调度路径可以删除。
- 草稿内容、`Timelines/` 和元数据仍只读。缓存继续使用现有 `.jypreview` 或用户缓存路径。
- 首期不做草稿写回、完整剪映私有特效、最终导出或完整编辑命令层。

## 后端选择与研究结论

**执行后端目标为 MLT；OpenCut 作为架构与时间表示参考；现有 GStreamer/GES 作为本地对照基线。**

- Shotcut 和 Kdenlive 都使用 MLT；MLT 提供 Producer、Playlist、Tractor、Consumer 多轨结构，支持从时间轴产生合成音视频帧，并提供变速、倒放和变换能力。参考：[Shotcut](https://github.com/mltframework/shotcut)、[Kdenlive](https://github.com/KDE/kdenlive)、[MLT framework](https://mltframework.org/docs/framework/)、[MLT timewarp](https://www.mltframework.org/plugins/ProducerTimewarp/)。
- OpenCut 主仓库约有 91k Star，但当前仓库 README 表明项目正从头重写；其桌面端仍是早期窗口壳，旧版 `opencut-classic` 已归档。旧版 v0.3 设计值得参考：整数时间刻度、有理数帧率、Rust 合成器与 UI 分层。参考：[OpenCut](https://github.com/OpenCut-app/OpenCut)、[OpenCut Desktop](https://github.com/OpenCut-app/OpenCut/blob/main/apps/desktop/README.md)、[archived classic](https://github.com/OpenCut-app/opencut-classic)、[v0.3 release](https://github.com/OpenCut-app/OpenCut/releases/tag/v0.3.0)。
- `libopenshot` 有较直接的 Python `Timeline.GetFrame()` API，是 MLT 无法在目标环境运行时的备选评估对象。它也带来独立 FFmpeg/Qt 原生运行时。[Timeline API](https://github.com/OpenShot/libopenshot/blob/develop/src/Timeline.h)。
- 本地 GStreamer/GES 记录证明 105 片段草稿的随机定位 PTS 正确，但连续播放性能和完整合成尚未验收；当前 `clips_from_frame_ir()` 也不是独立时间线模型。[本地评估](../../native-backend-evaluation/2026-09-29-gstreamer-ges-report.md)、[现有适配器](../../../scripts/jypreview/playback_backend.py)。

**实施前的硬门槛：** 用目标 Windows/Python 3.14 运行时验证 MLT Python 绑定、插件发现、素材解码、音频 sink 和多轨帧输出。当前默认 Python 3.14.7 环境未安装 `mlt7`；MLT 官方 Windows 构建页面也提示说明过时。若门槛未通过，先比较 `libopenshot`，再决定执行后端；不在未验证时开始整体替换。[MLT Python bindings](https://mltframework.org/doxygen/group__python__bindings.html)、[MLT Windows build](https://www.mltframework.org/docs/windowsbuild/)。

## 架构

```text
Encrypted/plain Jianying draft
              ↓
Existing decrypt + Draft Parser
              ↓
       DraftAdapter
              ↓
       TimelineModel ───────────────→ Evaluate(t) → ExpectedScene
              ↓                                      │
          MltCompiler                                │ parity checks
              ↓                                      │
       MLT playlists + Tractor                       │
              ↓                                      │
     MLT Consumer: video frame + mixed audio ─────────┘
              ↓
     PlaybackController / local service
              ↓
       Existing preview UI shell
```

### Draft Parser / Adapter

`DraftAdapter` 消费解密后的 `TimelineContent` 和现有素材/字体元数据，直接生成 `TimelineModel`。每个草稿 segment 转为稳定 ID 的内部 clip；复合片段按现有解析能力递归建成子时间线。

播放调度不再从 `/api/frame?window_us=` 的窗口采样结果反推 clip，也不再通过窗口 IR 去重和合并播放片段。`FrameDescriptor` 保留为调试和时间/层级对照接口，不作为后端排程输入。

### 内部模型

模型在 Python 服务端拥有，使用不可变数据值；原始 JSON 字段不进入 MLT 图或浏览器播放状态。

```text
Timeline
  id, durationUs, frameRate{num, den}, canvas, tracks[], transitions[], warnings

Track
  id, type, order, enabled, muted, renderIndex, clips[]

Clip
  id, kind, mediaRef, timelineRange, sourceRange, timeMapping,
  audio{enabled, volume}, textPayload?, transform, opacity, crop,
  blendMode, effects[], animations[]

Transition
  id, kind, fromClipId?, toClipId?, window, durationUs, params
```

`textPayload` 是归一化后的文字、样式、字体和画布框，不保留原始 JSON 结构。`audio` 描述素材自带音轨是否参与混音及片段音量；独立音频片段使用同一字段。素材引用单独保存路径、存在状态、可用源区间、时长、源 FPS 等信息。track/clip ID 来自草稿稳定 ID；复合片段 ID 包含父子路径，避免子时间线的重复 ID 相互覆盖。

### 时间与求值规则

- 模型和 API 时间统一为整数微秒；时间段一律使用半开区间 `[startUs, endUs)`。不引入第二种 tick 单位，以免在现有微秒 IR 与模型之间重复量化。
- 帧率用有理数 `{num, den}` 表示。Adapter 保留草稿中的精确帧率字段；遇到常见 NTSC 小数表示时规范化为标准有理数。缺失帧率时沿用现有 30 FPS 默认值并写入 warning；无法可靠规范化的非标准值保留最接近的有理值并标记来源。
- 时间转帧使用绝对值计算：`frame = floor(tUs * fpsNum / (1_000_000 * fpsDen))`；该帧的唯一整数采样时刻为 `sampleUs = ceil(frame * 1_000_000 * fpsDen / fpsNum)`，即不早于精确帧起点的第一个可表示微秒。使用整数式 `(frame * 1_000_000 * fpsDen + fpsNum - 1) // fpsNum`，保证采样时刻量化回原帧号；有效帧率为正且不超过每微秒一帧。30 FPS 的第 1 帧采样为 `33_334µs`，`30000/1001` 的第 29 帧采样为 `967_634µs`。不逐帧累计浮点增量。`Evaluate(tUs)` 先量化到帧，再在其 `sampleUs` 求值；连续播放、乱序 Seek、MLT 编译和限定范围内的 FrameDescriptor 对照都使用同一采样时刻。仅在 MLT 边界转换为 MLT 帧位置。
- clip 活动条件为 `timelineStartUs <= sampleUs < timelineStartUs + timelineDurationUs`。边界落在两帧之间时，从第一个采样时刻不早于边界的帧开始生效。相邻片段 seam 不会同时正常活动；同轨重叠片段仍分别参与求值。`tUs >= durationUs` 进入 `ended` 并返回空场景，不请求越界帧；最后一个有效帧是采样时刻小于 `durationUs` 的最大帧号。
- 非负边界 `bUs` 的首个有效采样帧定义为 `firstFrameAtOrAfter(0) = 0`，正数时为 `floor((bUs - 1) * fpsNum / (1_000_000 * fpsDen)) + 1`。编译区间 `[startUs, endUs)` 使用 `[firstFrameAtOrAfter(startUs), firstFrameAtOrAfter(endUs))`；非空帧区间的 MLT inclusive out 再减 1。时间线帧数为 `firstFrameAtOrAfter(durationUs)`，零时长为 0；30 FPS 的 `33_334µs` 时长只有第 0 帧，`33_335µs` 时长才包含第 1 帧。求值、编译和终点验收共用这一规则。
- clip 的目标时间和源时间独立保存，不假设 `targetDuration = sourceDuration / speed`。`timeMapping` 首期实现正的有理常速 `{rateNum, rateDen}` 和独立方向字段；支持 0.5×、1×、2×。设 `localUs = sampleUs - timelineStartUs`，正向映射为 `sourceStartUs + floor(localUs * rateNum / rateDen)`；倒放映射为 `sourceEndUs - 1 - floor(localUs * rateNum / rateDen)`，再限制在 `[sourceStartUs, sourceEndUs)`。MLT 编译器按素材自己的 FPS/PTS 选择源帧，不能用项目 FPS 代替素材 FPS。正常片段映射超出 sourceRange 时产生 warning，不读出该范围；转场 handle 是唯一例外，且仍不得越出素材可用源区间。
- `TimeMapping` 保留曲线映射的位置。首期将可读出的曲线起止 source range 按整段平均速率近似为常速，保留 target duration，并写入 `speed_curve_approximated` warning；没有可用起止信息时输出该片段的占位，不按 1× 静默播放。
- 图片 clip 在整个 timeline range 内引用同一静态帧。
- `Evaluate(tUs)` 是纯函数：返回量化后采样帧中的活动视频、音频和覆盖层、source time、合成顺序、当前变换/动画值与 warnings。随机 Seek 与连续播放调用同一套定义。
- `visible:false` clip 与 disabled track 不进入活动场景；mute 只影响音频。合成顺序沿用现有语义：clip `render_index` 优先于 track `render_index`，再回退到类型默认层级；相同 z 值按原 track 顺序、segment 顺序稳定排序。MLT 的 priority 方向在编译器边界反转映射。几何先通过现有布局/绘制代码转换为画布坐标，再交给后端。
- Transition 独立存于 Timeline，记录类型、可选的 from/to clip、持续时间、半开作用区间和参数；不改变逻辑 clip 或 timeline 区间。Crossfade 期间求值会额外纳入两侧片段作为合成参与者，并按各自 timeMapping 读取 sourceRange 之外、素材可用源区间之内的 handle 帧。handle 不足时将缺少的一侧钳制到最近可用源帧并写入 warning，不读出素材范围。首期支持 fade 与 crossfade；未知转场按近似 crossfade 或占位告警处理。

### MLT 编译与合成

`MltCompiler` 只消费 `TimelineModel`，负责构建背景、媒体 Producer、Playlist、合成和最终 Tractor。模型更新时编译图；逐帧播放不重建图。首期每个视觉 clip 使用独立 lane，按 `(effective_render_index, original_track_index, original_segment_index)` 排序，同时保留逻辑 track ID。不能只按原轨道分 lane：同轨相邻 clip 的 z=0、z=2 可以跨越另一持续轨道的 z=1，前后合成关系必须变化。同轨重叠、相同 z 稳定次序和转场 handle 也使用同一顺序。仅在性能测量证明有必要、且像素验收仍通过后才复用视觉 lane；音频可按逻辑轨道组织并为重叠片段分 lane。

- 视频、图片与复合片段进入 MLT 视频图；有自带音轨的视频片段也按 Clip.audio 路由到混音轨，独立音频 clip 进入对应音频轨；静音轨不输出音频，clip volume 应用在线性增益阶段。gap 输出画布背景。复合片段编译成嵌套 Tractor，递归深度沿用现有解析上限；超过上限保留区间并输出占位 warning。
- affine/composite 能力处理位置、缩放、旋转、anchor、crop、flip、opacity 和 blend mode。轨道启用、静音和 layer 顺序由编译器映射至对应 MLT track/filter/transition。
- 普通文字使用归一化 `textPayload` 和 MLT Pango title producer，贴纸按透明图像源处理。首期保证文字内容、基本字号/位置、透明度和层序；不支持的逐字渐变、花字、特殊字体或动画以透明占位/诊断 warning 表示。未知 effect 的说明放在信息/告警 UI 中，不用不透明层遮住底下的真实视频。
- 媒体缺失时输出位于原 clip 区间和 z 层的可见占位素材及 warning，不删除片段或缩短时间线。
- MLT 对象只存在于播放后端内部，不进入 HTTP payload 或 UI 状态。

### PlaybackController 与音频

- 唯一播放时间是 MLT 项目时间轴帧位置；UI 和 API 的微秒时间是该位置的派生值。源素材的 decoder PTS 不回写时间线。MLT 音频时钟作为播放主时钟，controller 的 snapshot 从该时钟报告当前位置及项目帧号。
- 控制器公开 `open/play/pause/seek/snapshot/close`。每次 open 生成新的 `playback_id`；客户端在发起 Seek 时、任何等待或 HTTP 派发之前分配递增 `request_id`。控制器 `seek(t_us, *, playback_id, request_id)` 在串行 worker 上校验实例身份，只接受比已接受序号更大的请求并增加 generation；较小或重复请求仅返回当前 snapshot，不移动时间。请求按 3/1/2 到达时最终仍停在请求 3。若 Seek 前处于 playing，正确帧到达后恢复播放；显式向后 Seek 可以降低项目时间，单调性约束只适用于同一 generation 的连续播放。
- 帧在产生并进入队列时绑定不可变的 `playback_id/generation/seek_request_id/frame_index/pts_us`，PNG 与 multipart 传输沿用这些字段，不使用编码后的当前 snapshot 补标。客户端在响应、解码和显示前均校验实例、最新请求及 generation；切换或重新打开时间线后丢弃旧实例结果。HTTP 路由名称保持不变，但 handle 操作必须携带 playback 身份；`render` 只取得指定已接受请求的选定帧，不隐式再 Seek，失效身份返回 409，终点返回 `ended` JSON 而非 PNG。
- 状态至少包括 `ready / playing / paused / seeking / buffering / ended / error`。结束、关闭、切换 timeline 会停止消费者并释放资源。
- MLT 一条时间线同时产生带项目帧 PTS 的视频帧和混音 PCM。浏览器按音频主时钟呈现对应 PTS 的帧，丢弃已过期帧；controller 不以 HTTP 到帧时间或 decoder PTS 推进播放位置。视频、音频、动画和效果共享同一帧位置；浏览器不再逐素材控制 `<video>` / `<audio>` 元素。
- 音频轨支持 trim、timeline offset、track mute、clip volume 和常速映射；Adapter 从草稿音频字段解析 `audio.enabled` 与 `volume`，信息不足时给出 warning，不静默丢弃素材自带音轨。首期由本机 MLT audio sink 输出。全局预览 transport 初期保持 1×，与单 clip 的 source speed 区分。若目标 UI 无法在端到端验收中保持同步，需改为共用一个带时间戳的音视频呈现通道后再切换默认播放路径。
- 内部 PCM/视频 PTS 一致性与实际呈现的音画同步分别验收。端到端证据必须来自同一采集时钟下的浏览器画面与实际音频输出，并记录采集延迟/时钟偏差校准和不确定度；consumer 回调、HTTP 到达时间、`image.onload` 或 UI 自报 PTS 不能替代此证据。采集不可用或精度不足时标记 `unverified`，禁止删除旧路径。

## 降级与错误处理

- Unsupported effect/animation 不中断 MLT 图编译，不改变时间或 z；用 placeholder 或 warning 标识。
- MLT 不支持的素材解码格式作为单 clip warning/placeholder 暴露，不默默移除其他轨道。
- 无效时长、负范围、空 mediaRef 等边界输入在 DraftAdapter 处验证；损坏片段变为占位并给出可追踪的错误 ID。
- MLT 初始化/消费者失败时进入 `error`，给 UI 可读错误；不自动切回旧浏览器调度器，避免同一项目两种播放语义。
- 所有播放后端访问由一个串行 worker 负责，防止多线程并发操作 MLT 对象。

## 验收标准

### 时间线模型

- `Evaluate(tUs)` 对重复调用、乱序 Seek 结果一致；任意非帧边界时间按规定量化到帧起点。覆盖时间线终点时返回空场景且不请求越界帧。
- 覆盖 0、timeline end、clip 起止、相邻 seam、重叠 clip、缺失素材、嵌套片段和不同帧率。
- trim 与 0.5×/1×/2×、倒放的 source time 正确，且 source time 不越出半开源范围。
- FrameDescriptor 与 `model/timing.py` 首期保持不变，只在有效、启用、可见、非嵌套、无转场或源范围钳制的普通 clip 上比较同一 `sampleUs` 的活动 ID、track 和层序；source time 对照限定为正向 1×/2×。倒放、0.5×、禁用/静音、转场 handle、损坏占位、变速曲线近似和父路径限定的嵌套 ID 用独立预期值验收，不要求复现旧 oracle 的错误。例如倒放 2×、源 `[2_000_000, 3_000_000)`、local=`250_000`，新值必须是 `2_499_999`，旧值 `2_500_000` 不作为新语义依据。

### 合成与播放

- 至少三层同时可见时，track order、z-index、opacity、position、scale、rotation、crop 与 canvas aspect ratio 正确。
- 覆盖同轨相邻 z=0/z=2 片段跨越另一持续 z=1 片段的像素结果，以及同轨重叠和 equal-z 稳定次序；逐片段层序不能被固定原轨道优先级替代。
- 图片在有效区间内保持静态；文字内容与基本样式、sticker、crossfade 和 fade 有正确时段与层级。交叉淡化需覆盖素材有 handle 和 handle 不足时的告警/钳制行为。
- Exact seek 返回量化后的目标 MLT project frame 及其 PTS；请求时间达到 timeline end 时返回 `ended`/空场景，不请求不存在的帧。连续播放的输出时间戳单调，无意外黑帧、乱序帧或重复时间戳。
- 多轨音频及视频素材自带音轨的 trim、offset、mute、volume 与视频同轴；包含大于 1 的合法片段增益值。正常 URL 下运行有编号视觉标记及同帧音频脉冲的校准时间线，正常和人为丢视频帧各采集至少 30 秒。用共同采集时钟测量显示画面与音频输出，保留原始采集和延迟校准证据；测量不确定度不得大于四分之一项目帧，每个配对事件必须满足 `abs(video_capture_us - audio_capture_us) + uncertainty_us <= 1_000_000 * fpsDen / fpsNum`。丢帧模式需包含实际掉帧且覆盖标记附近；缺少标记或脉冲算失败，不删除样本。分别报告 `max_internal_av_delta_frames` 与含测量不确定度的 `max_presented_av_delta_frames`，均不得超过 1；另验证同 generation 的音频主时钟/UI 时间单调。缺失或不确定证据禁止切换验收通过。
- 在现有 64 秒/105 片段样本上记录首次打开延迟、seek 延迟、持续输出 FPS 和掉帧数；先以硬件可复现基线评估实时表现，不先写入未经测量的固定吞吐阈值。
- 用现有剪映导出样本检查真实画面接近度；FrameDescriptor 仅作结构/时间 oracle。

### 环境与只读

- Windows/Python 3.14 能导入 `mlt7`，找到所需插件，打开代表性素材并输出含视频和音频的多轨帧。
- 预览期间源草稿文件、`Timelines/` 和草稿元数据保持不变；只写入允许的预览缓存。

## 分阶段迁移

1. **后端可用性门槛**：建立隔离 MLT 运行时，验证 Python binding、插件、三层合成、单素材变速、精确 seek、带 PTS 的帧输出、音频 sink 和目标草稿素材覆盖。若门槛失败，暂停整体替换并比较 `libopenshot`，不提前实现完整 MLT adapter。
2. **模型与求值**：从 `TimelineContent` 建 `TimelineModel` 和纯 `Evaluate(tUs)`；固定可往返的整数帧起点和区间规则，只在明确的兼容子集上用 FrameDescriptor 对照，其余语义使用独立预期值。
3. **MLT 图与音频**：编译 tracks/lanes/Tractor，支持基础 transforms、图片、音频和已列出的降级。
4. **UI 接入**：保留现有 UI 外壳，将 seek/play/pause/snapshot/stream 接到一个 MLT controller 和合成输出。
5. **验收与删除旧路径**：通过模型、图形、连续播放、正常 URL 浏览器、实际呈现的端到端 A/V 采集、只读与打包验收后，删除旧 GES 播放适配器和浏览器窗口帧调度代码；采集缺失/未验证时阻止删除。只对旧后端符号及当前 UI 调度引用执行零匹配检查，保留新 Python `PlaybackController`、解析器、FrameDescriptor 和 `/api/frame` 的 `window_us` 诊断能力。播放行为、运行时或输出设备变化后重新采集。

## 外部参考路径限制

本机提供的 `E:/Develop/lib/jianying-editor-skill/` 没有可读工作树，因此本设计没有依赖该目录内容。草稿语义以当前项目的 `references/draft-schema-notes.md` 和 `TimelineContent` 为工作区证据；恢复参考仓库后可在 DraftAdapter 计划阶段核对差异。
