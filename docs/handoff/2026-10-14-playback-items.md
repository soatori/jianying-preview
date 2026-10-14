# 播放四项问题（2026-10-14）

用户在一次交互测试里连着报了四件事：① 内存瞬间爆满、② 播放一卡一卡、③ 音频轨道只有背景音乐、
视频里包含的音频没有播放、④ 字幕效果预览异常。本文记录定位口径、已经修掉的部分、以及还没收到
根因的部分。夹具与像素匹配基线见 `2026-10-13-export-match-fixture.md`，本机 MLT 运行时限制见
`2026-10-12-mlt-runtime-rebuild-device2.md`。

四项状态（2026-10-14 收口）：

| 项 | 状态 | 结论 |
| --- | --- | --- |
| ③ 视频原声不响 | **已修**（`draft_adapter`） | 片段的媒体种类被特效标签覆盖 → 被两处音频判据拒发 lane。修后真夹具图测到 PCM（peak 4868/4296/6641，`test_audio=0`），像素基线逐位不变 |
| ④ 字幕效果异常 | **已修两处**（`effects.js`/`render.js`） | 动画字幕被平移两倍掉出画布（25/37 条）；原生模式下字幕被浏览器与 pango 各画一遍 |
| ② 播放卡顿 | 部分改善，账在解码 | 按预览尺寸编译：4.08 → 4.94 fps（gap 0）；恢复音频后实测 3.12 fps（单程）。要接近实时需要窗口化图 |
| ① 内存爆满 | **未解**，已定量 | 与画幅无关：每条 lane ≈190 MB、98 个片段就是十几 GB；恢复音频后 open 从 11.2 → 13.59 GB。解法同样是窗口化图（task #12） |

## 1. 先分清页面跑在哪条播放路径——这决定了 ③ 该往哪儿查

| 路径 | 画面来源 | 声音来源 |
| --- | --- | --- |
| 浏览器回退（`nativeMode=false`） | `web/render.js` 的 `<video>`/SVG 图层 | 只有"最底部那个可见 video 取消静音"一路（`render.js:491`）；`web/media.js` 的 `AudioScheduler` 从未被实例化（死代码）；`model/framedesc.py:228` 的 `audio_labels` 只收 `track_type=="audio"` 的片段 |
| 原生 MLT（`nativeMode=true`） | `/api/backend/stream` 的 multipart PNG | 服务端 `sdl2_audio` sink（MLT 图混出来的） |

回退路径连 BGM 都放不出来，所以"只听到背景音乐"只可能发生在原生 MLT 路径上：**③ 是图侧问题，
不是浏览器音频问题**（浏览器路径的音频缺失是另一件事，见 §5）。

## 2. ④ 字幕效果预览异常：两处真 bug（已修）

**(a) 带动画的字幕被平移了两倍，直接跑到画布外。** `web/text.js:59-61` 建字幕时已经把
`translate(cx-w/2, cy-h/2)` 写进内层 `<g>`；`web/effects.js` 的 `applyTransform()` 又把同一份 rect
transform 写到外层节点上。实测（夹具 8.00 s，片段 `0791C477`，"缩小"动画）：图层框左上
(200, 1350)，实际绘制位置 (400, 2679)，画布只有 1920 高 → 字幕整条消失。夹具 37 条字幕里
25 条带入场动画，也就是**六成的字幕在页面上看不见**。对比图
`temp/inspect/sub/ab-t8.00-as-is.png` vs `ab-t8.00-patched.png`。

修法：`effects.js` 新增 `animationTarget(entry)`——文字与嵌套文字把动画作用在字幕自己的 `<g>`
上（嵌套文字的 holder 是整画布大小的 div），`applyTransform(node, css, state, positioned)` 在
`positioned` 时只接受去掉 `translate(...)` 的那半（`rotate`/flip 仍然保留），并给 SVG 节点设
`transform-box: fill-box; transform-origin: center`，否则 scale/rotate 会绕视口中心而不是字形转。
`render.js:resetTransform()` 走同一个入口，避免"重置"路径再犯一次。

**(b) 原生模式下浏览器还在自己叠一层字幕。** 原来只隐藏 `entry.kind === "media"`，`#overlay` 里的
文字仍可见，于是同一句字幕出现两遍（浏览器全样式一份、pango 烧进画面一份），看起来就是"字幕特效
坏了"。改成 `Stage.hiddenInNative()` 一并隐藏 `text` / `nested-text`。

验证：`node temp/inspect/sub/caption_placement.mjs` 4/4 通过（含"媒体图层行为不变"的反向断言），
并已把同样的断言并入常驻门槛 `tools/test_playback_kernel.mjs`（node 跑 exit 0）。
真页面复测只做到一半：打开 `?draft=…&t=6.787` 时页面**自动**开了 MLT 内核（`__state.backend="mlt"`、
`playbackId` 有值），而原生模式下 DOM 字幕按设计被隐藏（`__layers[0].display="none"`），所以
"浏览器画的字幕落在 IR 框位"这一条只能在浏览器内核下量；那条路径的等价验证由子代理在页面里即时
打过补丁量过（`temp/inspect/sub/ab-t8.00-patched.png`：绘制中心回到 (200,1339)=框位）。
原生模式下的字幕正确性另有像素口径兜底：`export_match` 全画幅 12 帧 median 0.8634 / max 0.9084
（字幕是 pango 烧进画面的，几何此前已量到与导出差 ~1%）。

**不是回归的部分**（文档里已记为未实现）：逐字上色 `runs.0.use_letter_color`（夹具 19 条）、
25 条入场动画只有近似曲线、花字/阴影/多描边（`text_shadow_unsupported` 37/37、
`text_runs_unsupported` 1）。近似动画还额外绕 SVG 视口中心缩放的问题已随 (a) 一并解决。

## 3. ③ 视频原声：根因是适配器把片段的"媒体种类"覆盖成了"特效标签"（已修）

`model/draft_adapter.py` 里那段给 UI 生成特效 chip 的循环写了这一行：

```python
kind = str(label.get("kind") or label_bucket)   # ← 复用了片段自己的 kind 变量
```

它本是标签的种类，却把 `_clip()` 顶部算出来的**媒体种类**覆盖掉，再传进 `Clip(ident, kind, ...)`。
于是凡带 `智能调节/美颜` 标签的画面片段，`clip.kind` 变成 `smart_color_adjust` / `makeup_root`，
而两处音频判据都按种类放行——`mlt_backend.py:375-377` 与 `model/timeline.py:367` 的
`clip.kind in ("audio","video","draft","compound")`——片段因此拿不到音频 lane；画面分支
（`clip.kind != "audio"`）不受影响，所以像素一切正常，问题只在声音。

修法：标签种类留在 `label_kind`，不再动 `kind`。

排除过程（脚本在 `temp/inspect/audio/`，日志在 `temp/gate-logs/`）：

| 步骤 | 结果 |
| --- | --- |
| `audio_gate.py` 复刻判据跑夹具 | 约 40 个 `kind=video` 嵌套片段本来就过闸（`has_audio=True / enabled=1 / volume=1.0`），媒体实到 `…/subdraft/EE3FBF9F…/IMG_7318.MOV`（ffprobe hevc+aac）→ 模型层不是嫌疑 |
| `pcm_probe.py` | 这些 MOV 的 `audio_index=1`（不是 -1），排除 `broken → 静音占位`分支（`mlt_backend.py:499`） |
| `compile_audio.py`（真编译器 + 小模型） | flat / compound 嵌套 / BGM / 叠加四种形状全部出声（`flat` peak 2952、`nested` 与它逐位一致、叠加 13303，`test_audio=0`，warnings 空）→ 图的形状没问题 |
| `volume_level.py` | `level=0`（dB 写法）并不静音；带 crossfade / fade 的编译结果照样出声且看得出衰减（f16 peak 991）→ 音量滤镜不是嫌疑 |
| `fixture_audio.py`（真夹具 14-18 s 窗口） | 只留非音频轨 → **f430..f477 全部 peak=0 test_audio=1**（MLT 用静音顶上）；只留音频轨 → peak 8651..17124 test_audio=0。用户听到的正是后者 |
| `fixture_bisect.py`（修前） | `F9596D35 → FE4B6D93:smart_color_adjust:kind=smart_color_adjust`（被拒），而同一个片段的**子图单独编译有声**（peak 7181）→ 丢在父层那条 lane 上 |
| `segment_kind.py` | 该片段的 material bucket=`videos`、type=`video`、1080x1920、48.7 s → 它本来就是画面片段，种类是被标签覆盖掉的 |
| `fixture_bisect.py`（修后） | dump 变 `FE4B6D93:compound:AUDIO`；`video/effect/text only` f407 peak=4868 / f419 4296 / f436 6641，`test_audio=0` → **原声回到图里** |

修后门槛 `test_timeline_model`、`test_mlt_compiler`、`test_mlt_controller` 全部 exit 0；像素基线与
内存/帧率复跑见 §4 末（`temp/mlt-build/verify_t14b.ps1`）。

顺带否掉一个先到的判断："给音频 lane 的 kind 白名单补上 `makeup_root` / `smart_color_adjust`"是错的
治法——这两个字符串本不该出现在 `clip.kind` 里，补白名单等于把适配器的错误固化成编译器的特例。

## 4. ①② 内存与卡顿：预览尺寸这条路只买到 20%，内存的账另有其因

并行的性能任务把播放会话改成按预览尺寸编译：`TimelineModel.rescale(factor)`（`model/timeline.py:268`，
纯值变换：画布、`Clip.transform` x/y/w/h、`TextPayload.font_size`/`box`，递归进 `nested`），
`POST /api/backend/open?longest=N`（`handlers_backend.py:88/123`，不给参数就保持全画幅，老调用方零影响），
`web/backend.js` 打开时请求 960，**流侧二次缩放代码删除**（只留一条缩放路径）。
夹具 1012-1626、从帧 440 起 40 段：

| 指标 | 修前 | 修后（longest=960，串行 sink） |
| --- | --- | --- |
| 交付帧率 | 4.08 fps（全画幅）/ 4.89（仅缩 PNG 流） | **4.94 fps** |
| gap / 重复 | 0 | **0**，身份头逐帧正确 |
| 播放逐帧相似度 median | 0.9078 | 0.9079 |
| open 私有内存 | 11.4 GB | 11.2 GB（画幅不是内存的账）；③ 修好后复测 **13.59 GB** |

量化后的结论：

- **卡顿的大头在图里**。串行 sink 下每帧墙钟就是交付帧率；缩小画幅只买到 20%，剩下的是
  98 个片段的解码与合成。要接近 30 fps 只剩"减少同时存活的解码器数量"（窗口化图）这条路。
- **`real_time=1`（多线程 sink）在 540x960 下实测更差**：0.82 fps、36 个 gap、内存照旧 →
  保留串行默认，没有新增 `?threads` 接口（env 旋钮 `JY_PREVIEW_MLT_REALTIME` 够测量用）。
- **内存的账是解码器，不是像素**：相位探针显示 11 GB 全部在 `_compile` 里 commit（540x960 一样），
  把每个 producer 的帧缓存压到 2 并主动 purge 也省不下来，close 后回到 ~1.6 GB。
  窗口实测每条 lane ≈ **190 MB**（`temp/inspect/audio/audio_cost.py`：12 s 窗口 18 片段 →
  `_compile` +3.6 GB）。所以 ① 的真解法是"只编译播放头附近的窗口"，本轮未做；
  也正因为这条账，③ 的修复必须先量再加 lane——按现在这份草稿，③ 只给 2 个顶层片段新增 lane
  （其余在被静音的美化轨上，仍由 `track.muted` 正确拒绝），代价约 0.4 GB。
- ③ 的代价也量了（这是 ② 的坏消息）：恢复视频原声后同一取法两次实测交付
  **3.12 / 3.13 fps**（修前 4.94），gap 仍为 0、到达帧 median 仍 0.9079 —— 每片段多一份解码器
  就是要付的墙钟。③ 与 ①② 在今天的架构下直接对冲，只有窗口化图（task #12）能两头一起救。
- 像素测量没被缩放污染：③ 修完后全画幅复跑 `export_match --frames 12 --attribute
  --min-clean-similarity 0.86` → PASS，clean-frame median **0.8634**、min 0.8199、max 0.9084、
  grade-normalized 0.90235、对齐偏移 +3、`rendered_frame_header_mismatches: 0` ——与 2026-10-13 记下的
  基线逐位一致（`temp/export-match-t14.json`），也就是说恢复音频 lane 一点没动画面。
- 门槛复跑（`temp/gate-logs/kindfix-*.log`）：`test_timeline_model`、`test_mlt_compiler`、
  `test_mlt_controller`、`test_mlt_acceptance`（8 节 PASS + 3 条 capture-evidence FAIL，缺真机采集证据，
  与本轮无关；其中 `mixed audio trim/offset/mute/gain` 含 PCM 断言的那节 PASS → 加 lane 没有破坏
  A/V 混合与静音轨排除）、`node tools/test_playback_kernel.mjs`（含新加的字幕平移断言）全部通过。

## 5. 浏览器回退路径没有混音（另一件事，未修）

`AudioScheduler` 在 `web/media.js` 里实现完整但从未被实例化，而 `framedesc.py` 的 `audio_labels`
只列音频轨片段。结果是回退路径最多只有"最底部那一个 video"的声音，BGM 与叠加音轨全无。
计划：video 轨片段若媒体带 `audio_codec` 也进 `audio_labels`，页面用 `AudioScheduler` 统一驱动全部
声音并保持所有 `<video>` 静音（避免与它重复出声），原生模式下清空调度器由 sink 发声。
注意：改 `framedesc` 属于模型层，验证前必须重启服务并清掉草稿里的 `.jypreview/` 缓存。

## 6. 方法记录（别再犯）

- `mlt_frame_get_audio(frame, buffer**, format*, frequency*, channels*, samples*)`：后四个是
  **调用方要求的格式入参**（会被写回实际值）。传没初始化的 0，MLT 会打
  `[filter swresample] Invalid Parameters: … -> 0Hz 0C none` 并返回全零样本——看起来就像图是静音的
  （我这样误判过一次，连 `gate.wav` 都"peak=0"）。正确写法照抄
  `tools/test_mlt_runtime.py:pcm()`，指针用 `int(frame.get_frame())`，DLL 句柄复用
  `mlt_backend._libmlt()`（`GetModuleHandleW("libmlt-7.dll")` 在新进程里可能拿到 NULL）。
- 手工搭的 lane 图在这个运行时**与调用顺序有关**：同一个"画面 lane 出声"形状，一次 `no-pcm`、
  一次有 peak。问产品图的问题不要用手工图回答，用真 `MltCompiler` + 小模型（4 s 300x180 几乎不吃内存）。
- `Consumer.run(from, length)` 在 SWIG 绑定里不存在（只有 `run()`）；手搭 `avformat` WAV 消费者调
  `run()` 直接 access violation（`0xC0000005`）。要"渲染成 wav 再量"这条路在这个 build 上不通。
- 也不要手驱动图来量帧时间：`tractor.seek()/get_frame()` + `get_image()` 的循环同样 access violation
  （两种拉法都试过）。每帧成本只能从产品路径读——起服务、`temp/playback_match.py`、`temp/mem_probe.py`。
- `temp/` 下这些 HTTP 夹具（`mem_probe.py` 需要 psutil、`playback_match.py` 需要 Pillow）要跑在系统
  `py -3.14` 上，**不是**隔离 MLT 解释器里——那个 python 没有 psutil，跑起来只会留一份
  `ModuleNotFoundError` 日志（`t14-mem-960.log` 的第一次尝试就是这么废掉的）。
- 中途失败的测量会留下 8 GB 级的活体会话：`server.ps1 -Action stop` 只认 `temp/gate-logs/server.pid`，
  脚本步骤死在半路时先 `POST /api/backend/close` 再 stop，并确认 8765 的 owner 已经消失。
- **"只起个轻服务看看 IR"在这个项目里不存在**：页面一打开就自动 `POST /api/backend/open`
  （`__state.backend="mlt"`），于是任何端口的预览服务都会去编译整张图（实测 ~13.6 GB）。
  只想读 IR 就用 `preview.py frame`/`what-at` 这类进程内通道，别开页面。
- `server.ps1` 的 pid 文件不区分端口：在 8765 的测量脚本收尾时，它 stop 掉的是 pid 文件里
  记录的那个进程——本次就是被它顺手杀掉了 8801 上的服务。并发多端口跑测量前，先确认谁在写 pid 文件。
