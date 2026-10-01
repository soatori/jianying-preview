# 时间线播放与预览核心重构设计

**状态：** 待用户审阅

**日期：** 2026-10-01

## 目标

重构剪映草稿预览的播放核心，使时间线位置成为唯一的播放时间来源。对任意时间 `t`，系统都能确定当前活动片段、素材时间、轨道层序和最终画面；Seek 不依赖此前播放位置。

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
  id, durationUs, frameRate{num, den}, canvas, tracks[], warnings

Track
  id, type, order, enabled, muted, renderIndex, clips[]

Clip
  id, kind, mediaRef, timelineRange, sourceRange, timeMapping,
  transform, opacity, crop, blendMode, effects[], transitions[], animations[]
```

素材引用单独保存路径、存在状态、时长、源 FPS 等信息。track/clip ID 来自草稿稳定 ID；复合片段 ID 包含父子路径，避免子时间线的重复 ID 相互覆盖。

### 时间与求值规则

- 模型和 API 时间统一为整数微秒；时间段一律使用半开区间 `[startUs, endUs)`。不引入第二种 tick 单位，以免在现有微秒 IR 与模型之间重复量化。
- 帧率用有理数 `{num, den}` 表示。Adapter 保留草稿中的精确帧率字段；遇到常见 NTSC 小数表示时规范化为标准有理数。缺失帧率时沿用现有 30 FPS 默认值并写入 warning；无法可靠规范化的非标准值保留最接近的有理值并标记来源。
- 将时间转为时间线帧号时使用绝对值计算：`frame = floor(tUs * fpsNum / (1_000_000 * fpsDen))`。帧号转回 `timeUs` 时同样从帧号直接计算，不逐帧累计浮点增量。仅在 MLT 边界转换为 MLT 帧位置。
- clip 活动条件为 `timelineStartUs <= tUs < timelineStartUs + timelineDurationUs`。相邻片段 seam 不会同时活动；同轨重叠片段仍分别参与求值。
- clip 的目标时间和源时间独立保存，不假设 `targetDuration = sourceDuration / speed`。`timeMapping` 首期实现正的有理常速 `{rateNum, rateDen}` 和独立方向字段；支持 0.5×、1×、2×。设 `localUs = tUs - timelineStartUs`，正向映射为 `sourceStartUs + floor(localUs * rateNum / rateDen)`；倒放映射为 `sourceEndUs - 1 - floor(localUs * rateNum / rateDen)`，再限制在 `[sourceStartUs, sourceEndUs)`。MLT 编译器按素材自己的 FPS/PTS 选择源帧，不能用项目 FPS 代替素材 FPS。映射超出 source range 时产生 warning，不读到素材范围外。
- `TimeMapping` 保留曲线映射的位置。首期将可读出的曲线起止 source range 按整段平均速率近似为常速，保留 target duration，并写入 `speed_curve_approximated` warning；没有可用起止信息时输出该片段的占位，不按 1× 静默播放。
- 图片 clip 在整个 timeline range 内引用同一静态帧。
- `Evaluate(tUs)` 是纯函数：返回活动的视频、音频和覆盖层、source time、合成顺序、当前变换/动画值与 warnings。随机 Seek 与连续播放调用同一套定义。
- `visible:false` clip 与 disabled track 不进入活动场景；mute 只影响音频。合成顺序沿用现有语义：clip `render_index` 优先于 track `render_index`，再回退到类型默认层级；相同 z 值按原 track 顺序、segment 顺序稳定排序。MLT 的 priority 方向在编译器边界反转映射。几何先通过现有布局/绘制代码转换为画布坐标，再交给后端。
- Transition 使用独立对象记录类型、from/to clip、持续时间和参数；不延长 clip/timeline。首期支持 fade 与 crossfade；未知转场按近似 crossfade 或占位告警处理。

### MLT 编译与合成

`MltCompiler` 只消费 `TimelineModel`，负责构建背景、媒体 Producer、轨道 Playlist、轨道间合成和最终 Tractor。模型更新时编译图；逐帧播放不重建图。编译器在内部为同轨重叠片段生成必要的并行 lane，同时保留逻辑 track ID 与层序。

- 视频、图片与复合片段进入 MLT 视频图；音频 clip 进入对应音频轨；gap 输出画布背景。复合片段编译成嵌套 Tractor，递归深度沿用现有解析上限；超过上限保留区间并输出占位 warning。
- affine/composite 能力处理位置、缩放、旋转、anchor、crop、flip、opacity 和 blend mode。轨道启用、静音和 layer 顺序由编译器映射至对应 MLT track/filter/transition。
- 普通文字使用 MLT Pango title producer，贴纸按透明图像源处理。首期保证时间、基本字号/位置、透明度和层序；不支持的逐字渐变、花字、特殊字体或动画以透明占位/诊断 warning 表示。未知 effect 的说明放在信息/告警 UI 中，不用不透明层遮住底下的真实视频。
- 媒体缺失时输出位于原 clip 区间和 z 层的可见占位素材及 warning，不删除片段或缩短时间线。
- MLT 对象只存在于播放后端内部，不进入 HTTP payload 或 UI 状态。

### PlaybackController 与音频

- 唯一播放时间是 MLT 项目时间轴帧位置；UI 和 API 的微秒时间是该位置的派生值。源素材的 decoder PTS 不回写时间线。
- 控制器公开 `open/play/pause/seek/snapshot/close`。Seek 量化到项目帧，等待该帧，旧 generation 的迟到结果丢弃；若 Seek 前处于 playing，正确帧到达后恢复播放。
- 状态至少包括 `ready / playing / paused / seeking / buffering / ended / error`。结束、关闭、切换 timeline 会停止消费者并释放资源。
- MLT 一条时间线同时产生视频帧和混音 PCM。视频、音频、动画和效果共享同一帧位置；浏览器不再逐素材控制 `<video>` / `<audio>` 元素。
- 音频轨支持 trim、timeline offset、track mute、clip volume 和常速映射；首期由本机 MLT audio sink 输出。全局预览 transport 初期保持 1×，与单 clip 的 source speed 区分。

## 降级与错误处理

- Unsupported effect/animation 不中断 MLT 图编译，不改变时间或 z；用 placeholder 或 warning 标识。
- MLT 不支持的素材解码格式作为单 clip warning/placeholder 暴露，不默默移除其他轨道。
- 无效时长、负范围、空 mediaRef 等边界输入在 DraftAdapter 处验证；损坏片段变为占位并给出可追踪的错误 ID。
- MLT 初始化/消费者失败时进入 `error`，给 UI 可读错误；不自动切回旧浏览器调度器，避免同一项目两种播放语义。
- 所有播放后端访问由一个串行 worker 负责，防止多线程并发操作 MLT 对象。

## 验收标准

### 时间线模型

- `Evaluate(tUs)` 对重复调用、乱序 Seek 结果一致。
- 覆盖 0、timeline end、clip 起止、相邻 seam、重叠 clip、缺失素材、嵌套片段和不同帧率。
- trim 与 0.5×/1×/2×、倒放的 source time 正确，且 source time 不越出半开源范围。
- `Evaluate(tUs)` 活动 clip ID、track 和层序与 FrameDescriptor 在代表采样点一致。

### 合成与播放

- 至少三层同时可见时，track order、z-index、opacity、position、scale、rotation、crop 与 canvas aspect ratio 正确。
- 图片在有效区间内保持静态；简单文字、sticker、crossfade 和 fade 有正确时段与层级。
- Exact seek 返回目标 MLT project frame；连续播放的输出时间戳单调，无意外黑帧、乱序帧或重复时间戳。
- 多轨音频的 trim、offset、mute、volume 与视频同轴；连续播放期间 A/V 偏差不超过一项目帧。
- 在现有 64 秒/105 片段样本上记录首次打开延迟、seek 延迟、持续输出 FPS 和掉帧数；先以硬件可复现基线评估实时表现，不先写入未经测量的固定吞吐阈值。
- 用现有剪映导出样本检查真实画面接近度；FrameDescriptor 仅作结构/时间 oracle。

### 环境与只读

- Windows/Python 3.14 能导入 `mlt7`，找到所需插件，打开代表性素材并输出含视频和音频的多轨帧。
- 预览期间源草稿文件、`Timelines/` 和草稿元数据保持不变；只写入允许的预览缓存。

## 分阶段迁移

1. **后端可用性门槛**：建立隔离 MLT 运行时，验证 Python binding、插件、三层合成、单素材变速、精确 seek、音频 sink 和目标草稿素材覆盖。若门槛失败，暂停整体替换并比较 `libopenshot`，不提前实现完整 MLT adapter。
2. **模型与求值**：从 `TimelineContent` 建 `TimelineModel` 和纯 `Evaluate(tUs)`；用 FrameDescriptor 做采样对照。
3. **MLT 图与音频**：编译 tracks/lanes/Tractor，支持基础 transforms、图片、音频和已列出的降级。
4. **UI 接入**：保留现有 UI 外壳，将 seek/play/pause/snapshot/stream 接到一个 MLT controller 和合成输出。
5. **验收与删除旧路径**：通过模型、图形、连续播放、A/V、只读与打包验收后，删除旧 GES 播放适配器和浏览器窗口帧调度代码；保留解析器、FrameDescriptor oracle 与调试信息。

## 外部参考路径限制

本机提供的 `E:/Develop/lib/jianying-editor-skill/` 没有可读工作树，因此本设计没有依赖该目录内容。草稿语义以当前项目的 `references/draft-schema-notes.md` 和 `TimelineContent` 为工作区证据；恢复参考仓库后可在 DraftAdapter 计划阶段核对差异。
