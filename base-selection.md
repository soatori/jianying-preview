# 渲染基座选型（M1 交付物 D）

**状态（2026-10-21）：候选与许可证已实测核验（含 2026-10-21 用 `gh api` 复测并补 9 行）；字形轴、服务端出图轴、浏览器解码轴、多路合成轴都已 spike 并回填。**
浏览器轴的结果是**有条件通过**：首帧/连续播放/内存/Range 四条达标，**只剩 seek 一条不达标**（U-55）。
原先判为不达标的 HEVC 一条已由 F-044 更正为**探针自身的假阴性**；多路合成（F-043）在带硬件通路的浏览器里达标。
**同日 F-053/F-054 给 U-55 改了性质**：自建 mediabunny+WebCodecs 管线实测后，「关键帧索引 + 闭区间取块」
**作为 seek 的解被证伪**（相机片 207.6 / 257.8 ms，与 `<video>` 同量级），成本是 `GOP/2 ÷ 管道fps`
的结构项（GOP 实测 1 秒、moov 13/13 在尾）⇒ 达标路径改为**把素材搬进可硬解的 profile**；
首帧则从 85–110 ms 刷新到 **2.7–35.7 ms**，U-59（NAS 首帧预热）以「字节数从来不是病因」结案。
`## spike 结果` 里每一项都有脚本与落盘数据；还没量的指标明确标 **未测**，不当成已通过。

## 规格对基座的硬要求（由 `spec/` 推出，不是偏好）

1. **预乘 alpha 的混合模式**：剪映 10 个内置混合模式在 `Resources/MixMode/*/Library/ShaderData/*/shaderGLES/*.frag` 里是明文 GLSL 的 `*BlendPreMul(fg,bg)`。要数值对齐，就必须能**替换/自写混合着色器** → 需要 WebGL 层控制，Canvas2D 的 `globalCompositeOperation` 与 CSS `mix-blend-mode` 只能作为近似与交叉验证。
2. **动画曲线复用**：预设动效是包内明文 Lua + GLSL（`spec/animations.yaml`），渲染器需能吃自定义 shader/uniform 与时间参数。
3. **蒙版与轮廓路径**：`common_mask.config{centerX,centerY,feather,rotation,invert,roundCorner,aspectRatio}` + `contour_path` + 15 种蒙版关键帧 → 需要可裁剪路径 + 羽化 + 反相的遮罩能力。
4. **素材来自 NAS 与草稿本地缓存**：`\\192.168.0.247\…`（映射 `Z:`/`X:`）与 `<draft>/materials/<md5>.mp4`、旧安装路径。必须 **HTTP Range 流式 + 按 basename 重解析**，不能整片读进内存。**NAS 腿已实测**（F-046）：连续播放与丢帧零退化，seek 只加性上涨，但**首帧 2.7 倍、破 300 ms 阈值** ⇒ 转成实现项 U-59。
5. **编码面**：手机/相机 MP4、MOV、HEVC、可能的 10-bit；浏览器不支持的需明确降级而非静默黑帧。
6. **内存硬上限 2 GB / 会话**（历史教训：MLT 会话 11.4~13.6 GB 常驻、服务端 4.9 fps）。
   口径修正（F-037 + F-039）：不可接受的是 **MLT / 整条时间线常驻解码器**那一条服务端实现（11.4~13.6 GB），
   **不是服务端出图本身** —— ffmpeg 管道 + PIL 合成实测进程树峰值 **233~606 MB**。
   但服务端通道也**不是万能，也不是不可救**：4K HEVC **软解**上限约 24 fps（自带 ffmpeg 23.5、PyAV 24.4），
   够不到 30 fps 连续预览；换 `-c:v hevc_cuvid` 显式硬解后同一素材 **125.8 fps**（F-042）。
   所以这条限制的正确表述是「**软解路径**够不到 30 fps」，且硬解只认显式解码器名——`-hwaccel cuda` 会静默回落软解。
7. **工程格式即剪映草稿**：基座的数据模型必须允许我们把自己的 segment/material 映射层作为唯一真相，而不是被基座模型反向约束。

## 候选（2026-10-15 经 GitHub API 实测：stars / license / 最近推送）

| 项目 | ★ | License | 推送 | 定位 | 判断 |
|---|---|---|---|---|---|
| `pixijs/pixijs` | 48,382 | MIT | 2026-10-14 | WebGL 2D 合成、滤镜、遮罩、混合 | **采纳**为合成层：满足要求 1/2/3，社区密度最高且仍在活跃 |
| `Vanilagy/mediabunny` | 7,343（2026-10-21 `gh api` 复测） | MPL-2.0 | 2026-10-20 | 纯 TS 读写/解封装 MP4，WebCodecs 友好 | **采纳为唯一解码底座**（2026-10-21 F-054 实测后升级）。它已经 owns：`keySampleIndices`（由 `stss` 建）+ 二分找上一个 IDR、`getSample(t)`/`samplesAtTimestamps`、闭区间取块（`CustomSource.read(start,end)`）+ LRU 缓存 + 顺序读指数扩窗、**解码器复用**（关键帧切换/回跳走 `flush()` 而非重建）+ `MAX_QUEUE_SIZE` 背压 + 没人用的 `VideoFrame` 直接 `close()`、`ctts` 带符号重排、HEVC RASL 跳过、`verifyKeyPackets`（容器 `stss` 撒谎时回退重推 NAL 类型）、**尾部 moov 靠跳过 `mdat` 不下载**来读。⇒ 我们**不写** MP4 box 解析、索引、Range 调度、LRU、解码器生命周期、B 帧重排 |
| `WebAV-Tech/WebAV`（`bilibili/WebAV` 只是 301 跳转，不是第二个项目） | 2,092 | MIT | **2026-01-10，停更约 9 个月** | `av-cliper`（WebCodecs 合成）+ `av-canvas`（交互画布） | **2026-10-21 改判为反面教材**（源码读过，仍不作依赖）：每次 seek **关掉并重建 `VideoDecoder`**、注释自陈不信 `flush()`（「某些 Windows 设备上可能永不 resolve」）、音频是**每 tick 每轨新建 `AudioBuffer/BufferSource`**（N 轨 ×30 Hz 的节点 churn，还要挂一个静音振荡器才压住时钟漂移）、**`elst`/`ctts` 零支持**、尾部 moov 靠 30 MB 顺序 append 而不是尾读。可抄的只有一条：**按 GOP 把取数合并成一段连续区间**（我们的 GOP 正好 ≈ 一个区间） |
| `fabricjs/fabric.js` | 31,500 | MIT | 2026-10-14 | 交互式画布对象模型（拖拽/缩放/旋转/命中） | **候选**：若要求画布内直接编辑字幕框；与 Pixi 二选一或分层共存 |
| `xzdarcy/react-timeline-editor` | 800 | MIT | 2026-01-25 | React 时间轴组件 | **暂不采纳**：其 action 模型与剪映 segment/timerange 需双向映射，收益低于成本；自绘时间轴即可满足 |
| `ffmpegwasm/ffmpeg.wasm` | 17,874 | MIT（core LGPL/GPL） | 2026-09-29 | 浏览器内转码 | **仅作降级兜底**：不支持的编码离线转一次，不进播放热路径（慢、内存大） |
| `etro-js/etro` | 1,152 | **GPL-3.0** | 2026-10-12 | 浏览器视频编辑库 | **排除**（copyleft 传染风险） |
| `remotion-dev/remotion` | 64,174 | **NOASSERTION**（商用需授权） | 2026-10-15 | React 视频渲染 | **排除**（许可）；且服务端渲染路线与本要求 6 冲突 |
| `openvideodev/react-video-editor` | 1,811 | **NOASSERTION** | 2026-06-30 | CapCut 风 React 编辑器 | **排除**（许可不明），但值得作为**交互形态参考**（UI 结构、面板组织） |
| `konvajs/konva` | 14,868 | **NOASSERTION**（需核实） | 2026-10-15 | 2D 画布场景图 | **待定**：若核实为 MIT 可替代 fabric |
| `GuanYixuan/pyJianYingDraft` | 4,570 | Apache-2.0 | 2026-10-14 | Python 草稿生成 | **格式参考**（5.9 时代语义），不支持 6.0+ 加密，不作运行时依赖 |
| `renezander030/capcut-cli` | 893 | MIT | 2026-10-14 | 草稿 lint/schema 参考 | **交叉参考**；若引入作第二意见必须 pin ≥0.18.0 |
| `OpenCut-app/OpenCut` | ≈95.4k★（2026-10-20 实测） | MIT | 浅克隆 HEAD `e668010`（2026-09-24） | 开源 CapCut 替代，Web/桌面/移动 | **参考实现，不作依赖**：main 是重写骨架——`crates/*` 在 `Cargo.toml` 里被注释掉、`apps/web` 依赖中没有任何渲染/解码包，真正在跑的版本已拆到独立 classic 仓库；要求 7 也不允许被外来工程模型反向约束。**但它坐实了 F-042 的依赖做法**：`.github/workflows/media-deps.yml` 明写「为每个平台自建 FFmpeg，源与版本 pin 在 `crates/media/setup/ffmpeg.json`」，即高星方案同样不把系统 ffmpeg 当依赖 |
| `Augani/openreel-video` | 5,412 | MIT | 2026-10-17 | React+TS+WebCodecs+WebGPU 剪辑器 | **参考实现（活跃度最高）**：解码层同样选 mediabunny、WebGPU 合成（Canvas2D 兜底）、**多轨混音已真接线**（per-clip BufferSource→volume→fade→panner→destination）。取数用 `BlobSource` ⇒ 整片常驻，不合我们的 NAS/Range 腿 |
| `OpenCut-app/opencut-classic` | 282 | MIT | **已归档 2026-05-17** | OpenCut 重写前的真实版本 | **抄设计、不作依赖**：`core/managers/audio-manager.ts` 是本次见到的**最好多轨混音模板**（`AudioContext` 当时钟权威 + per-chunk BufferSource/gain 自动化 + 2 s 前瞻 + `waitUntilCaughtUp` 背压 + generation counter 合并 seek + 每资产只留 current/next 两帧）。顺带**证伪流传说法**「OpenCut = WebCodecs + FFmpeg.wasm」：classic 是 mediabunny + Rust/WASM 合成器，没有 ffmpeg.wasm |
| `walterlow/freecut` | 2,283 | MIT | 2026-10-20 | WebCodecs 剪辑器 | **API 用法样本**：第三个独立选 mediabunny 做解码的活跃项目（自绘 canvas2D 合成 + AudioWorklet 混音）⇒ 佐证「底座选 mediabunny」不是孤例 |
| `omni-media/omniclip` | 1,467 | MIT | 2026-10-20 | Pixi v7 WebGL 剪辑器 | **忽略**：画面是 `Texture.from(<video>)` 每层一个元素、"混音"是 `Map<string, HTMLAudioElement>.play()` ⇒ **正是本项目旧方案踩坑 17 次的那种架构**，反例价值大于参考价值 |
| `bilibili/web-demuxer` | 201 | MIT | 2025-12-20 | WASM 解封装供 WebCodecs | **不采纳**：`load(file)` 把整片读进 WASM，直接违反要求 4（不得整片进内存）；它证明了"有索引不等于有闭区间取数" |
| `mifi/lossless-cut` | 44,803 | **GPL-2.0** | 2026-10-21 | Electron + `<video>`/MSE，剪切走外部 ffmpeg | **排除**（许可 + 不是合成引擎），但它是"高星项目也停在 `<video>` 上"的对照样本 |
| `0xsline/OpenChatCut` | 2,571 | **AGPL-3.0** | 2026-10-20 | `@remotion/player` 血统的免后端口播剪辑器 | **排除**（许可，同 etro/remotion）；交互形态与"口播+字幕"这条业务线值得看，但不进依赖 |
| `diffusionstudio/core` | 1,248 | MPL-2.0 | 2025-11-18 | 宣称 Canvas2D + WebCodecs | **不可审计**：HEAD 里只剩 playground，引擎只发 npm ⇒ 无法核验它的 seek/缓冲/mixer，不作依据也不作反证 |
| `liamega/kazeta` | — | — | — | — | **不存在**：`gh api repos/liamega/kazeta` 404，`search/repositories?q=kazeta` 31 个结果无一相关。2026-10-21 曾作为候选被提出，此处正式作废，**不要再引用** |
| `morluto/rea` | 250,302 | MIT | 2026-10-15 | RE MCP/CLI | 已用：JS 应用图与 SQLite 只读快照；对格式清点无产出（F-002） |

## 推荐路线

**路线 A（推荐）**：纯浏览器合成。
`mediabunny` 解封装 → `WebCodecs VideoDecoder` → `PixiJS` 合成（自定义 blend shader 对齐 `*BlendPreMul`，mask 用 `Geometry`/`Graphics` 路径 + 羽化）→ 字幕层自绘（Canvas 纹理或 `Text`+自定义 shader，按 `spec/text.yaml`）→ 自绘时间轴（DOM/canvas，直接以草稿 `tracks/segments` 为模型）→ Python 网关（自研 crypto worker）负责解密、规格 JSON 化、媒体 Range 服务。

不采纳「WebAV 打底」：它把 clip/sprite 模型钉死在产品层，而我们的模型必须就是剪映草稿（要求 7）；npm 半年未更新。
不采纳「服务端解码」：已知 4.9 fps 与 9 GB 峰值量级，与要求 6 直接冲突。

## spike 结果（2026-10-19 回填）

### 已测：字形轴（谁画字、画得多像、花多少内存）

样本 = 用户导出的黑底白字成片帧（`X0 Y0.mp4` 第 45 帧，画布 1080×1920，「默认文本」size=15，
transform 0/0，墨迹盒 **高 86 宽 363**）；三个候选都用草稿自己记录的那份 `zh-hans.ttf`。
脚本 `temp/px-probe/spike_base.py`，数据 `temp/px-probe/spike-report.txt` + `spike-result.json`，结论 F-036。

| 基底 | 最佳 em | 四边偏差(上/下/左/右) | 质心偏差 | 整帧 RMSE | 字迹区 RMSE | 单帧墙钟 | 峰值内存 |
|---|---|---|---|---|---|---|---|
| PIL/numpy | 94 | 0/0/-1/+2 | 0.5 / -0.4 px | 3.05 | 22.35 | 5 ms | 54 MB |
| headless Chrome canvas2d | 94 | 0/0/-1/+2 | 0.5 / -0.3 px | 2.86 | 20.93 | 609 ms | 594 MB |
| headless Chrome DOM 文本 | 94 | 0/0/-1/+2 | 0.5 / -0.3 px | 2.86 | 20.93 | 629 ms | 546 MB |

- **三者对同一条导出的墨迹盒都在 2 px 内** → 「非原生引擎画不像剪映」这个担忧被数据否掉，
  字形保真**不构成选型轴**；剩下真正的差别是混合模式/蒙版/解码（要求 1/2/3/4/5）。
- **canvas 与 DOM 逐行同分**（同一 Skia 光栅）→ 网页里字幕层用 DOM/CSS 还是 canvas 只关便利性，不关像素一致性。
- **headless Chrome 不当渲染服务器**：0.6 s + ~590 MB/帧，字形又不比 PIL 好。它的位置是 M2 的**标定仪**与页面自动化。
- 顺带把字号律钉死：逐 em 复测给 k=0.005741（9:16）与 0.005781（16:9），两画幅一致到 0.7%。

### 已测：服务端出图轴（要求 6 的判据）

`temp/px-probe/spike_pipeline_rate.py`（60 帧窗口，均值+分位数，进程树**含 ffmpeg 本体**）：
素材 → ffmpeg 管道 `scale+pad` 到 1080×1920 → PIL `alpha_composite` 叠字幕。

| 素材 | 读均值 | 合成均值 | 稳态 | 进程树峰值 |
|---|---|---|---|---|
| HEVC 4K60（软解） | 27.1 ms | 8.6 ms | 26.3 fps | 606 MB |
| H.264 10bit 4:2:2 1080p60 | 6.8 ms | 11.3 ms | 48.6 fps | 327 MB |
| H.264 8bit 1080x1920 30p | 4.7 ms | 9.1 ms | 55.3 fps | 233 MB |
| HEVC 4K60 + `-c:v hevc_cuvid`（**解码上限口径**，`-f null` 无消费者） | — | — | **125.8 fps** | 627 MB |

对照 MLT 的 230 ms/帧、11.4~13.6 GB：**同机差一个数量级，要求 6 达标**。
最后一行是 F-042 的补测，**口径与前四行不同**（前四行是 ffmpeg→PIL 端到端管道，最后一行是纯解码上限），
它说明「4K HEVC 只有 0.405× 实时」是**软解路径的属性**，加 `-c:v hevc_cuvid` 后解码侧不再是瓶颈；
同轮还测出 `-hwaccel cuda` 会**静默回落软解**、`*_qsv` 在无核显机器上挂到超时（F-042）。

### 已测：浏览器解码轴（阈值判据，HeadlessChrome/155）

三件套在 `temp/px-probe/`：`media_server.py`（Range/206 只读服务）+ `decode-probe.html`（自动跑并把结果
`POST /report` 落盘）+ `run_browser_probe.py`（自起 Chrome、绝对 profile、每秒采样进程树 RSS）。
汇总 `browser-probe-report.txt`，结论 F-038（判据读数）与 F-040（取块体积与 seek 成因）。
**下表除注明外都是 `--disable-gpu`（软件光栅、无硬件解码器）下的读数——F-043/F-044 已证明这一列是下界**。
**六条判据的判决**：

| 判据 | 实测 | 判决 |
|---|---|---|
| 首帧 ≤ 300 ms | 85.2 / 96.8 / 110.2 ms；F-045 六轮复测散布 108.9~228 ms | **达标**（但散布有 2 倍，引用要带区间） |
| 连续播放 ≥ 24 fps | 29.38 / 59.69 / 60.18 fps，丢帧 0；浸泡 600 s 只丢 8 帧 | **达标** |
| seek ≤ 150 ms | 小片 25 ms；269 MB 片 266.7、1.6 GB 片 278.2（最大 378.6）ms。F-045：缓存与预取钳位都不改延迟 | **不达标**，且**服务端无解**（U-55 只能在播放器里做） |
| 10 分钟会话 ≤ 2 GB | 600.2 s、596 次 seek，峰值 956 MB，末段回落到 358 MB | **达标**（无泄漏迹象） |
| Range 流式 | 1.6 GB 片深跳，6 个请求只取整片 16.4% | **达标**（NAS 成对实测见 F-046：播放零退化、首帧 2.7 倍 → U-59） |
| HEVC/MOV/10-bit | 10-bit 4:2:2 可解（60 fps）；HEVC 在软件光栅下零帧 | **HEVC 已由 F-044 改判为可用**（带 GPU 时四个 `hvc1` 串全 True、真解 241 帧；U-54 结案）。MOV 仍未测 |

两条要特别记住：
- **HEVC 的失败形态是静默的**：拿到 metadata、不触发 `error`、`videoWidth` 为 0、0 帧，
  还把 32 MB 整片下完（104.9%）。任何「先渲染后报错」的预览都会变成黑帧，必须先做能力判定。
- **`<video>` 的 seek 会开区间预取**（`bytes=<offset>-`），12 个请求里 11 个是播放器主动掐断的。
  达标路径是自己拿关键帧索引（mediabunny sample table）或走代理片，而不是裸用 `<video>`。
- **seek 不是服务端能治的**（F-045 六轮）：`no-store` 基线 252.1 / 298.2 ms，允许缓存并跑暖轮仍是 248.5~306.9 ms，
  把开区间钳到 32 MiB 仍是 250.4~317.3 ms；延迟随目标位置单调上升（101 → 412 ms）⇒ 成本在关键帧定位与解码前进。
  首帧延迟这六轮的散布是 108.9~228 ms（比 F-038 记的 96.8~110.2 宽），阈值 ≤300 ms 仍过但要写散布。
- **本节的 HEVC 行已被 F-044 更正**：那条「`isConfigSupported` 两种 profile 都 false、`<video>` 零帧」的阴性
  是 `--disable-gpu` 关掉硬件通路 **加上** 探针给 `description` 传了 4 字节假值造成的。
  带 GPU 重测：四个 `hvc1` 串全 True，同一条 4K HEVC 真解出 241 帧 ⇒ HEVC 不是 Chrome 的能力缺口。

### 已测：多路合成轴（阈值判据，F-043；6 配置 × 软件光栅/带 GPU 两条通路）

判定配置 = **两路 1080p60 10-bit + 字幕层**（画布 1080x1920，预热 1.2 s 后计 3 s，分母是实际渲染窗）。

| 配置 | 软件光栅（`--disable-gpu`） | 带 GPU（ANGLE = GTX 1650） |
|---|---|---|
| L1 单路 | 29.061 fps | 未测 |
| L2 两路 | 16.098 fps | 57.756 fps |
| **L3 判定配置** | **14.95 fps —— 不达标** | **59.98 fps / render p95 0.2 ms / 峰值 1.29 GB —— 三条全过** |
| L4 判定 + 4K HEVC 层 | 12.65 fps（HEVC 层 0 帧） | 60.055 fps（HEVC 层 241 帧）/ 峰值 1.41 GB |
| L5 / L6（三~四路 + Multiply） | 11.261 / 12.961 fps | 未测 |

- **结论**：多路合成**不推翻路线 A**——真实浏览器有硬件通路时四层仍是 60 fps，内存 1.29~1.41 GB 在 2 GB 上限内。
- **瓶颈不在合成**：`app.render()` 只花 0.1~0.3 ms，恶化全在视频帧到达（interval p95 17.3 ms → 41~116 ms）
  ⇒ M2 可以把遮罩/滤镜/字幕样式做重而不担心基底。
- **软件光栅那一列只是下界**：一个 flag 同时关掉硬解与硬栅，两者尚未分离（U-58）。

### 已测：NAS 轴（成对对照，F-046）

同一素材两份字节数与 mtime 一致的副本（本地 `E:` vs `X:` 共享），同一服务器配置、同一浏览器 profile 先后跑：
连续播放 **58.39 / 60.08 fps、丢帧 0**（1 Gbps 链路对 58 Mbps 码率有富余，抖动没有复现）；
seek 中位 **+27.1% / +23.8%**（257.0 → 326.5、273.7 → 338.8 ms，仍随目标位置单调上升 ⇒ 解码侧主导）；
**首帧是唯一破线的判据**：422.1 ms（同轮本地 158.8 ms，2.7 倍；阈值 300 ms）。
⇒ 浏览器路线对 NAS **不需要改评**，但要补一条首帧预热的实现要求（U-59）。

### 仍未测 / 已测待修（2026-10-21 按 F-053/F-054 更新）

**已测（2026-10-23，F-077）**：`PixiJS` 自定义 blend shader 与剪映 `*BlendPreMul` 的数值等价（要求 1）已首轮判定 —— oracle 是包内 `.frag` 原文在 headless Chrome WebGL1 里编译执行，对照腿独立实现 W3C 标准式，两腿吃同一份 8-bit 输入；screen/darken/lighten/multiply/linearBurn 五包在 1/255 内等价，`叠加/强光` 与 CSS 同名模式互为反面，`柔光` 须移植包内 sqrt 形式，`颜色减淡/颜色加深` 预乘支待判（U-90）。**SP-09 代理片路线同样已测**（P-04/P-05：关键是 4:2:0 而非短 GOP；seek 37.6 ms / 合成 28.31 fps / 首帧 116.6 ms，三条原判据翻绿）。

**已测且结论反了的那半**：seek 达标的实现路径不再"未测"——F-054 用自建 mediabunny+WebCodecs 管线实测过
「sample table + 精确闭区间 + 从 IDR 解到目标」，在相机片上是 **207.6 / 257.8 ms**，与裸 `<video>` 同量级
⇒ **(i) 作为 seek 的解被证伪**，成本是 `GOP/2 ÷ 管道fps`（GOP 实测 1 秒，F-053）的结构项。

**仍未测（本文件不声称通过）**：`PixiJS` 自定义 blend shader 与剪映 `*BlendPreMul` GLSL 的数值等价（要求 1，
唯一没动的基座判据）、
`hevc_cuvid` **带消费者的端到端吞吐**（F-042 只量过 `-f null` 上限，帧从没离开 GPU，SP-07）、
闭区间取块的 keep-alive 成本（**已测，SP-04 结案**：真负载 141,655 条请求复用率 99.9%，seek 30~39 ms 达标；多端口不需要。逐请求 `ms=` 已插桩，供 P-08 那条「NAS 上复用反而慢」在真负载上复算）、
U-58 的 **WebGL 光栅那一格**（解码侧已由"不经过 WebGL 的 seek 读数"分离出来，剩光栅需细粒度 flag 或 Pixi 对照，SP-05）、
**多轨混音器**（K 轨节点数/CPU/同步误差/倍速变调，SP-10）、**MOV 从未测**、跨语料的 GOP 普查（现只有 13 片）。
判据不变：**这些不达标就得改评「服务端预转码 + 浏览器播放代理文件」并重新举证**。

## 定案：双通道（M1-D）

**2026-10-21 用户裁定：保留 web 方案。** 交互预览的播放内核维持路线 A（mediabunny + WebCodecs + Pixi），
下面第 1 条的「有条件成立」**不改评**为服务端渲染/解码通道；seek 那条残留判据按**素材侧**解决
（把素材搬进可硬解的 4:2:0 profile，代理转码只是输入手段，播放仍在浏览器），达标证据仍要 SP-09 实测补上，
不达标时重新举证义务与「改评」触发条件照旧保留。

1. **交互预览 = 浏览器**（路线 A：mediabunny + WebCodecs + Pixi 合成，字幕层 DOM/CSS 皆可）——
   **有条件成立**：H.264 素材上首帧/帧率/内存/Range 四条达标，多轨道 + 字幕层的合成也达标
   （判定配置 59.98 fps、峰值 1.29 GB，F-043）。剩下的唯一条件是 **seek**，而它的性质在 2026-10-21
   被实测改判（F-054）：`<video>` 与「mediabunny 关键帧索引 + 精确闭区间 + WebCodecs 从 IDR 解到目标」
   **在相机片上同为 207–258 ms 中位** ⇒ 不是取数问题、也不是"换个播放器"能解决的，而是
   `GOP/2 ÷ 管道fps` 的**结构成本**（GOP 实测 1 秒、moov 13/13 在尾部，F-053）。
   ⇒ **达标路径 = 让素材进入可硬解的 profile**：同一条 1 秒 GOP 在硬解 HEVC 上是 58–61 ms（管道
   370–379 fps），在只能软解的 H.264 4:2:2 10-bit 上是 200+ ms（管道 147–165 fps）。
   所以代理片的关键不是低码率而是 **4:2:0（可硬解）**，短 GOP 是第二顺位；关键帧索引改记为
   **首帧与尾 moov 的手段**（实测首帧 2.7–35.7 ms，远低于 `<video>` 的 85–110 ms）而非 seek 的解。
   服务端改法依旧无效（F-045）；新增一条前置：闭区间取块**单次 seek 花 11–62 个请求**，在
   `Connection: close` + Chromium ~6 连接/源下不可用 ⇒ **keep-alive / 多端口是自建管线的前置条件**（SP-04）。
   HEVC 不再是前提条件（F-044），但 F-054 加回限定：**只在有硬件通路时可用**，无通路时
   mediabunny 在解封装成功之后**直接抛** `cannot be decoded in this environment`——这是
   「解码器报不支持时必须显式提示、不许静默黑帧」第一次有可依赖的显式信号（不再是 `videoWidth==0` 反推）。
   **生效环境是「浏览器启用了硬件解码/光栅通路」**：软件光栅下判定配置只有 14.95 fps（F-043），
   所以「在无 GPU 的远程桌面/虚拟机里跑预览」不在本定案的保证范围内。
2. **agent 侧出图/校验 = PIL/numpy + ffmpeg 管道**，达标（进程树 233~606 MB、单帧读+合成 11.5~35.7 ms、
   字迹 RMSE 与浏览器同量级），且不需要浏览器进程 —— 它是「不开剪映也能看到时间线」的落地形态。
   限制：**软解路径**的 4K HEVC 只有 26.3 fps，**静态出帧/逐帧校验没问题，整条时间线连续预览不行**；
   加 `-c:v hevc_cuvid` 后解码上限是 125.8 fps（F-042），所以这条限制的实际范围是「没用硬解的时候」。
   后端因此按 profile 白名单路由，且**不依赖 PATH 上的 ffmpeg**（那个安装已消失，旧 spike 脚本按现状跑会失败）。
3. **排除**：MLT/常驻整线图解码（要求 6）、headless Chrome 作渲染服务器、`etro`(GPL)、`remotion`(许可+服务端渲染)、
   `react-video-editor`(许可不明，只当交互形态参考)。

## 依赖清单（路线 A 成立时）

```
runtime:  node 24.x（本机 24.19.0 满足 rea-engines 与前端构建）
frontend: pixi.js 8.22.0 (MIT)，mediabunny 1.62.0 (MPL-2.0)
          # 两者 2026-10-21 起都只 pin 在 temp/px-probe/node_modules（**探针期，不进产品依赖清单**）
          # mediabunny：dist/bundles/mediabunny.mjs 1,483 KB，sha256 前缀 3f772842de4befed；
          #   npm dist.integrity = sha512-D8E8BDxjCyqyrGj074jLRQNgilDW5izJu8o9pg7THMYMIZBL1Fao5hOtdDPDfA+nSnk68tMa8IaCJmz8hSpJpw==
          #   单文件 ESM bundle，可由 media_server 的 probe 根直接服务（.mjs 已是 text/javascript）
          # 注意取数形态：**UrlSource 发的是开区间 `bytes=pos-`**（自带 64 MiB LRU、parallelism 2），
          #   闭区间精确取块必须走 CustomSource{getSize,read(start,end)}（默认缓存 8 MiB）——F-054 两种都实测过
build:    vite + typescript（自绘时间轴，无 UI 框架）
backend:  python 3.14 + scripts/jy_crypto + pillow(MIT-CMU) + numpy(BSD-3 系) + psutil(BSD-3, 仅采样)
          # 清点/解密侧仍是标准库；agent 出图通道从 F-036 起需要 pillow+numpy（都宽松许可）
decode:   **不是 PATH 依赖**（F-042：本机 `shutil.which("ffmpeg")` 为空，F-036/F-037 当时那个 8.1.2 full build 已消失）
          主用剪映自带 ffmpeg，路径由 scripts/jy_paths.py 自动检测并记在 config.local.json（本机实测 `<JY_INSTALL>\11.6.0.14552\ffmpeg.exe`，版本串 21.7.0-9c087b133d，同目录无 ffprobe）
          备胎 PyAV 18.0.0（libavcodec 62.28.102，已装、锁版本、软解速率与前者同量级）
          硬解只写 `-c:v hevc_cuvid`（GTX 1650）；**禁** `-hwaccel cuda`（静默回落）与一切 `*_qsv`（无核显，且挂死）
```

## 风险

- Pixi 的混合模式默认与剪映 GLSL 的预乘语义是否等价需实测（M2 交叉验证）。
- HEVC 在 Windows Chrome 的硬件解码并非普遍可靠，需 fallback 计划。
- NAS 抖动会造成黑帧假象，先前已被误判过：任何「素材缺失」结论先查共享可达性与 basename 重解析。
  **F-046 成对复测没有复现黑帧**（时长与固有分辨率都正常读到，播放零丢帧），但首帧代价 2.7 倍、破 300 ms 阈值
  ⇒ 这条风险从「读数可信度」改为「起播体验」，处理办法在 U-59。
- mediabunny 的 muxing 精度（时间戳/编辑列表）会影响导出与剪映回读的帧对齐。
- **服务端解码有两个静默失败**（F-042）：`-hwaccel cuda` 初始化失败后**回落软解**（速率仍在软解区间，看不出来），
  `*_qsv` 在无核显机器上**挂到超时**而不是快速返回 ⇒ 后端按 profile 白名单路由（HEVC→`hevc_cuvid`，
  H.264 4:2:2 10-bit→软解），禁止运行时逐条试错。
- 主解码器是**剪映安装自带的 exe**，路径与版本串随剪映升级漂移，且同目录没有 ffprobe
  ⇒ 出图工具启动时断言该路径存在并打印版本串，缺失时明确降级到 PyAV 而不是静默改行为。
