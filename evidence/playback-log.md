# 播放测试日志（M2 首轮，只读）

前置授权见 [scope.md](scope.md)；本文件记 **M2 播放通道在真草稿上的实测**。
编号用本文件自身的 **P-xx**，**不占用 `findings.md` 的 F 号段与 `unresolved.md` 的 U 号段**——
写作时 `findings.md`（尾 F-054）与 `unresolved.md`（尾 U-67）可能被另一会话同时追加，
沿用 `native-re-log.md` 的避撞做法，合并时再统一分号。

测试对象：`<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>`，活动 timeline `017E2FEC-…`
（36.83 s / 1080×1920 / 10 轨 / 104 段 / 48 份素材）。全程只读：草稿字节未被触碰，
所有产物在仓库 `temp/playback-test/`（不入库），读数由 `check_doc_counts.py` 的 PROBE_DIRS 覆盖。

工具：`scripts/playback_model.py`（L1 规范化 + L1 断言）、`scripts/preview_gateway.py`
（keep-alive Range + 按 id 服务 + 自报告通道）、`scripts/browser_soak.py`（进程树 RSS 采样，
按 Chrome `--type=` 分角色）、播放器 `temp/playback-test/player.html`
（mediabunny 1.62.0 `CustomSource` 闭区间 → WebCodecs → pixi.js 8.22.0）、
`scripts/render_frame.py`（通道 2：pin 的 ffmpeg + PIL 出帧）、`scripts/playback_check.py`
（四层门：L1 断言 + L2 对封面 + L4 判据分布 + L6 黑帧守卫正反双向）。

## 并号结果（2026-10-22：本通道的事实已并入正式号段）

| 本文件 | 并入 | 一句话 |
| --- | --- | --- |
| P-13 / P-16 | **F-057** | `clip` 是 segment 字段；律本身 `spec/panel-map.yaml:16` 早已 `conf: verified`（F-035），是我们没读规格 |
| P-14 | **F-058** | 复合子画布→父画布 = 按宽适配 + 垂直居中（封面四边残差 2–12 px）；残留 → **U-76** |
| P-17 | **F-059** | combination 视频缓存经字符串 API 解不出容器、音频解得出有效 AAC；归属问题 → **U-80** |
| P-11 的 alignment 疑点 / Q-7 | **F-060** | `alignment=2` + `transform≠0` 只匹配中心锚定 ⇒ 给 F-031 划适用域；判别样本 → **U-77** |
| P-20 / P-23 削顶 | — | 5/5 跑满刻度 ⇒ **U-78**（处置待成片或用户裁定） |
| P-06 / P-23 内存口径 | — | peak 1674 vs median 895 反向移动 ⇒ **U-79** |
| P-15（`pcm_s16be` 可解） | — | 现象关闭，无需新 F 号（属工具能力，非格式事实） |
| P-12 / P-18 / P-21 / P-22 | — | 纯实现缺陷与工具建设，留在本文件 |

下面 P-xx 段落保持**写作当时的口径**（含被后续推翻的话），推翻处就地标注，不改写历史。

---

## P-01 加密面比 `draft_content.json` 大

- **Evidence**：主轨三段画面对应的 `Resources/combination/<id>_video.mp4`（7.0 / 9.3 / 21.6 MB）
  首 12 字节无 box 头（`f9f9f9d99f8d8089…` / `a5a5a585c3d1dcd5…` / `d0d0d0f0b6a4a9a0…`），
  mediabunny 报 `Input has an unsupported or unrecognizable format`；
  同目录**配套**的 `<id>_video.mp4.alpha.mp4`（19.9–62.7 KB）是 `....ftypisom` 明文 MP4。
  用 `scripts/jy_crypto/worker.py` 的 `decrypt_bytes` 解这 5 个文件（3 视频 + 2 音频 `.aac`），
  `ok:True` 但输出是**无原子随机字节**，输出/输入比 ≈ **0.187**（5 个文件一致），
  4 KB 可打印率 0.378（随机基线 0.371）。
- **Finding**：草稿密文容器与媒体缓存容器**不是同一套**；`lvve::EncryptUtils` 的内存串 API
  解不开后者，且不解的原因未查（按 scope §3 不逆向算法）。副产品一条纪律：
  **`decrypt` 返回 `ok:True` 不等于解对了**——判据必须是内容形态（box 头 / JSON 可解析），
  这与 F-044「能力探测要用被测对象自己产出的配置记录」同型。
- **Path**：`temp/playback-test/media-dec/`、`temp/playback-test/result-media.json`、
  `scripts/playback_model.py::probe_container`。
- **证据等级**：**已验证**（自有字节扫描 + mediabunny 解封装 + DLL 解密输出形态三路一致）。

## P-02 复合片段可自包含重建，加密的渲染缓存一次都没用到

- **Evidence**：`materials.drafts[]` 6 条（`combination` 5 / `composition` 1），每条的
  `draft` 键**内联了子时间线的 `tracks[]` 与自己的 `materials{}`**；
  子片段 `material_id` 在父级 bucket 里的解析率实测 **0/1、0/4、0/8、0/12、0/4、0/4**
  （`extra_material_refs` 同样 0/6 … 0/97）。展开后 4 个复合片段共 28 个子片段，
  素材**全部可读**（`<NAS>/<NAS>/<素材语料>2026/<草稿A>/20261015_0910*.mp4`）。
- **Finding**：复合片段的正确读法是**递归展开子时间线**，子级自带 materials，
  因此**不需要** `subdraft/` 目录，也**不需要** P-01 那块加密渲染缓存。
  写回侧一条纪律：改复合片段必须同时动 `materials.drafts[]` 与
  `draft_virtual_store.json` 的父子索引（`write-rules.md` 已有），但**渲染读侧只需 drafts[]**。
- **Path**：`scripts/playback_model.py::Model.expand_composite`、
  `temp/playback-test/model.json -> tracks[0].segments[*].composite`。
- **证据等级**：**已验证**（结构清点 + 播放器实际重建出画面，截图核对通过）。

## P-03 素材编码面：这份草稿把 F-053 的三条都踩到了

- **Evidence**：48 份素材逐个过一遍解封装（页面内 evaluate，逐条 `getPrimaryVideoTrack`）：
  22 个相机片 `avc 1080x1920` + 音轨 **`pcm-s16be`**，解码帧内存格式 **`I422P10`**，
  `coded 1920×1080 / display 1080×1920`（容器旋转 90°，即 Sony 竖拍陷阱）；
  1 个 `IMG_7322.MOV` = `avc + aac`；20 个 `.mp3` 里 **3 个实为 aac**；
  NAS 素材元数据单读 **107–150 ms**（尾 moov）。
- **Finding**：① **MOV 首次实测通过**，`base-selection.md` 的「MOV 从未测」可以划掉；
  ② 旋转必须走 `VideoSample.rotation`，`createImageBitmap(vf, {imageRotation:'from-image'})`
  **不生效**（实测仍给 1920×1080）——竖拍片要么按 90° 交换缩放轴，要么画面就是横的；
  ③ 扩展名不可信，容器判定要看字节。
- **Path**：`temp/playback-test/playback-run.txt`（素材面段）、`scripts/media_probe.py`。
- **证据等级**：**已验证**（mediabunny 语义 + 自有 box 清点两路）。

## P-04 seek 与连续播放的瓶颈是 chroma profile，不是 GOP

- **Evidence**：同一支 C7881（18.72 s）四臂受控，同一条浏览器解码路径
  （`CustomSource` 闭区间 → `VideoSampleSink` → `toVideoFrame` → `createImageBitmap`）：

  | 臂 | profile | GOP | 位置 | 管道 fps | seek 中位 | seek 最大 | 首帧 |
  |---|---|---|---|---|---|---|---|
  | A | 4:2:2 10b | 1 s | NAS | 47.9 | 332.4 | 788 | 302 |
  | B | 4:2:2 10b | 1 s | 本地 | 102.4 | 143.4 | 364.5 | 126.9 |
  | C | 4:2:0 8b | 0.6 s | 本地 | 187.0 | 55.8 | 153.8 | 23.8 |
  | D | 4:2:0 8b | **1 s** | 本地 | **244.8** | **47.3** | 177.2 | 24.0 |

- **Finding**：**C vs D 判死短 GOP**（55.8 反而差于 47.3）；B vs D 同 GOP 只差 chroma ⇒
  seek 3.0×、管道 2.4×、首帧 5.3×。A vs B 给出 NAS 腿纯倍率 **2.1–2.4×**。
  这把 F-054「4:2:0 比短 GOP 更关键」从推断升级为实测，并给出代理配方定案：
  `h264_nvenc + yuv420p + 每秒一个关键帧 + faststart`（22 支 12.02 GB → 7.1 GB，409 s，0 失败）。
- **Path**：`temp/playback-test/ab-proxy.html`、`report-ab.jsonl`、
  `temp/playback-test/proxy/`、`make_all_proxies.py`。
- **证据等级**：**已验证**（单变量对照，四臂同素材同代码路径）。

## P-05 六条基座判据在真草稿上的首轮判定

- **Evidence**：同一 build 只切模型（代理 = 本地 4:2:0，原片 = NAS 4:2:2），机器空载：

  | 模型 | 合成 fps | rt | seek 中位 | 首帧 | 错误 |
  |---|---|---|---|---|---|
  | 原片 + 递归 + 混音 + 真字体 | 15.97 | 0.996 | 382.6 | 928.5 | 0 |
  | 代理 + 递归 + 混音 + 真字体 | **28.31** | 0.998 | **37.6** | **116.6** | 0 |

  判据：连续播放 ≥24 **达标** / seek ≤150 **达标** / 首帧 ≤300 **达标** /
  Range 流式 达标 / 编码面 达标（无静默黑帧）/ 内存见 P-06。
- **Finding**：三条原先不达标判据**单靠代理配方翻绿，播放器一行未改**。
  一条口径纪律：`painted` 数的是循环迭代，`fresh` 数的是各轨新帧，
  **判据只能用合成后的呈现帧率**；两次误读分别来自「时间线放完后原地重绘报 30 fps」
  与「把双轨吞吐当呈现率」，字段已改名 `composited_fps` / `fresh_track_frames_per_second`。
- **Path**：`temp/playback-test/report-playback-run*.jsonl`、`playback-run.txt`。
- **证据等级**：**已验证**（同机同 build 对照）。

## P-06 内存破线的是 GPU 进程，修法是按引用计数淘汰

- **Evidence**：620 s / loop=1 浸泡，进程树 RSS 按 Chrome `--type=` 分角色：
  pool=12 时 **peak 4216 MB**（mean 1544、median 1394、last 756，614 s 里 131 s 超 2048），
  峰值处 **gpu-process 1859 MB vs renderer 364 MB**；JS 堆全程 97–189 MB。
  pool 12→4 后 peak 2772 MB。接复合递归前同一窗口只有 **1210 MB**。
- **Finding**：① 破线来自**常驻解码器的显存面**，不是 JS；② 「每片段常驻一张 1080×1920 纹理」
  不可持续（≈8 MB/张，CPU+GPU 两份），已加纹理缓存淘汰（>6 即销毁最久未见）；
  ③ 淘汰必须**按引用计数**判占用：只查「泵表里还有没有」会杀掉刚被 kill、生成器尚未退出的流
  （实测一轮 11 次 `Input has been disposed`），且音频 job 不随片段结束摘除会让池冲破 cap。
  引用计数 + 音频 job 回收之后：pool 稳在 4、错误 0、fps 未退化。
- **归因更正（同日单变量实验，P-06 上一段的原因判断是错的）**：
  pool 12→4→2 只把峰值从 4216 压到 2772→2382 MB，边际递减，当时据此说是「解码器显存面」。
  真正的那一刀是**纹理复用**：把「每帧 `Texture.from(bmp)` + 销毁上一张」改成
  「同一 Texture 只换 `source.image` + 手动 `close()` 旧 ImageBitmap」，**同一 pool=4 配置下
  峰值 2772 → 1135 MB**（mean 682、median 596、134 s 里 **0 秒**超 2048），
  JS 堆 168 → 44.6 MB，峰值处角色分布变成 renderer 468 / gpu-process 401（此前 gpu 独占 2978）。
  ⇒ 涨的是**纹理分配抖动**，不是解码器驻留；pool 从 12 降到 4 是必要但不充分的。
  修完的读数：composited_fps 28.6 / rt 0.998 / seek 中位 31.8（最大 52.2）/ 错误 0。
- **Path**：`scripts/browser_soak.py`（分角色采样）、`temp/playback-test/rss-soak-{styled,pool4,roles,pool2,texreuse}.txt`。
- **证据等级**：**已验证**（三轮浸泡对照 + 分角色归因）。
- **待裁定**：`10 分钟会话 ≤ 2 GB` 沿用 F-038 的**峰值**口径则仍 FAIL（median 1.2 GB 过、
  peak 2.5–4.2 GB 不过）。口径是用户的线，不自行放宽。

## P-07 音频电平的真实载体是 `loudnesses[]`，不是 `audios[].volume`

- **Evidence**：37 条音频片段的 `audios[].volume` **全部为 null**；
  `loudnesses[]` 7 条，形如 `{enable:true, target_loudness:-12.0,
  loudness_param:{avg_loudness:-9.55, peak_loudness:-0.02}}`；`audio_fades[]` 4 条
  （`fade_in_duration` / `fade_out_duration` 各 1 s）。
  master 增益写死 1.0 时实测 `peak_rms` 达 **1.577 / 1.179**（数字域削顶），
  接上 `10^((target-avg)/20)` 归一 + 淡入淡出自动化 + DynamicsCompressor 后为 **0.445–0.645**。
- **Finding**：① 缺省音量按 1.0 读（`null` 不是 0，符合「键存在≠有值」纪律）；
  ② 电平归一的权威字段是 `loudnesses[]`，它挂在片段的 `extra_material_refs` 上（本草稿 3 条）；
  ③ 这份草稿音频素材**全是 mp3/aac**，`pcm_s16be` 一次未出现 ⇒ F-053 §4 的
  「翻端序直填 AudioBuffer」不在本项目关键路径上，需另找自带原声的草稿验证。
- **Path**：`temp/playback-test/probe_loudness.py`、`playback_model.py::ref_of`。
- **证据等级**：**已验证**（载体清点 + 改前改后 rms 对照）。

## P-08 两条与工具链有关的事实

- **rAF 不触发**：`document.visibilityState=visible` 且 `hasFocus()=true` 的 MCP Chrome 里
  `requestAnimationFrame` **0 帧**（600 s 窗口实测），播放腿必须定时器驱动；
  Pixi 自己的 ticker 走自适应回退所以仍能出画。先前 F-043 的多路合成读数来自自起 Chrome，
  两者不可混引。
- **keep-alive 的因果要重述**：24 个 64 KiB 闭区间请求，本地文件 keep-alive 与每请求新建连接
  差 ≤0.21 ms；**5.2 GB NAS 片上 keep-alive 20.87 ms/请求，反而比新建连接 12.96 ms/请求慢 7.90 ms**。
  ⇒ F-053 §3 那 +263 ms 不在 TCP 握手，而在服务端重开文件 + SMB。
  「keep-alive 是自建管线前置条件」这句需要改写；网关日志已能直接见证 `reused=yes`。
- **证据等级**：rAF **已验证**（多次一致）；keep-alive **单源待验证**（机制未查，
  候选：一连接一线程 + Nagle/延迟 ACK）。
- **Path**：`temp/playback-test/sp04-keepalive.txt`、`scripts/preview_gateway.py`。

## P-10 `draft_meta_info.json` 的目录记录是陈旧的，不能用来定位草稿

- **Evidence**：该文件本身是**密文**（首 12 字节 `if6Ct41h6J36`，非 `{`），经 `jy_crypto` 解密为
  946,457 B 明文。其中 `draft_fold_path = <DRIVE_D>/JianyingPro/<DRAFT_ROOT>/10月15日 (4)`、
  `draft_name = 10月15日 (4)`，而磁盘上的真实目录是 **`<草稿A>`**；
  `os.path.isdir(记录路径) == False`，`draft_need_rename_folder = false`，
  `draft_root_path` 与 `draft_id`（CF341D8D-…，又一个独立命名空间）正常。
- **Finding**：草稿被改名（人或工具）之后，`draft_meta_info.json` 里的路径与名字**不跟着更新**，
  且应用自己也不认为需要重命名。⇒ 三条纪律：① 定位草稿只能以**实际目录**为准，
  ② 写回时**不得**拿 `draft_fold_path` 当真相去校正目录名（那会把好草稿改坏），
  ③ 扫描器的目录归属应以磁盘遍历为唯一入口（`corpus_scan.py` 现在就是这样，此条为它补一个理由）。
  另记一条与 P-01 同型的判据：**`decrypt` 成功返回不等于内容是新的**——
  这份 meta 解出来是合法 JSON，但里面已有字段与磁盘状态矛盾。
- **Path**：`temp/playback-test/plain/draft_meta_info.dec.json`、
  `temp/playback-test/check_foldpath.py`（记录路径 vs 实际目录的核对）。
- **证据等级**：**已验证**（解密 + `isdir` 两路）。
- **归属**：M3 写回门禁（`write-rules.md` §1 选址一节应补这一条）。

## P-09 字体可以直读

- **Evidence**：`styles[].font.path` 指向资源缓存里的
  `HelloFont_ID_JianSong_95.ttf`（2,143,588 B），网关按 id 路由以 `font/ttf` 服务，
  页面 `new FontFace(...).load()` 注册 1/1 成功，字幕换成该面并带投影。
- **Finding**：预览的字形保真不需要装字体、也不需要系统字体回退——
  草稿自己记录了绝对路径，读它即可（与 F-036 三个基底同分那条结论一致，但这条是**用对字体**的前提）。
- **Path**：`playback_model.py::style_of`、`preview_gateway.py::build_manifest`。
- **证据等级**：**已验证**（截图核对）。

---

## P-11 封面当 oracle，一次抓到三个缺陷（L3 首轮）

- **Evidence**：`<DRIVE_E>/输出` 下没有这份草稿的成片，于是改用**剪映自己存的封面**
  `draft_cover.jpg`（1080×1920）。先确认封面属于这条时间线：封面上的金色字幕
  「你们这次去<素材语料>了吗？」在 `materials` 里只出现在
  `drafts[A29CC483]`（type `combination`）的**子 text 轨**（子时刻 0.00+3.00 s），
  该 drafts 条目被 **track[6] 的片段 DAC95A4C 以 `extra_material_refs` 引用**，
  而 T06 那一段 `target = 0.00+0.57 s` ⇒ 封面就是开头 0.57 s 内的一帧。
  用通道 2（`scripts/render_frame.py`）渲染 t=0.5 与封面比对，逐层暴露：
  1. **复合片段判据错**：递归的触发条件写成「自身素材不可解封装」，而 T06 这一段
     **根本没有 media**（`media: None`，只有 drafts 引用）⇒ 整条 5 轨子时间线被静默丢掉
     （封面字幕与 logo 都不在画面里）。这是内容丢失级缺陷，不是画质问题。
     改为「有 drafts 引用且没有可用的渲染缓存」才递归；模型里带 composite 的片段
     从 4 个变成 **5 个**。
  2. **图片容器被判不可读**：`probe_container` 只认 ISO-BMFF/MKV/MPEG 音频，
     logo 的 PNG（首 8 字节 `89504e470d0a1a0a`，正是 PNG 签名）被记成
     `readable:False, why:no-box-header` ⇒ 两条渲染链都跳过图片层，
     且 `media_unreadable` 计数虚高（4 → 修完 **3**，那 3 个才是真加密的 combination 渲染缓存）。
  3. **图片层被各向异性拉伸**：沿用视频层的「各轴填满画布」律，1242×330 的 logo 在
     1080×1440 的子画布里纵向放大 4.4 倍；且 `convert("RGB")` 把透明通道抹平，
     logo 的黑底盖住下面所有层。改为图片走 uniform-fit + 保留 RGBA。
- **Finding（仍未解决的那一半，量化）**：子时间线**自带画布**
  （`composite.canvas = {ratio:"3:4", width:1080, height:1440}`，而母时间线 1080×1920），
  子层坐标在子空间里；父片段 `clip` 为 `None`、`render_index=6`。
  实测偏差：**封面金色字幕中心在画面高度 0.746 处，我们渲染在 0.500**；
  logo 在封面里位于上方偏左、约占宽度 55%，我们 uniform-fit 后居中偏大。
  ⇒ 复合片段「子画布→父画布」的映射律与 `clip=None` 时图片的基准缩放/锚点**未标定**，
  现有证据只能排除「各向异性拉伸」和「子画布等于父画布」两种错法，定不出正确式。
  要定它需要**这条草稿的一次剪映导出**（GUI 操作归用户），或读到剪映自己排布 combination 子层的规则。
- **更正（2026-10-22，由 P-13 + P-14 关闭；上面两段里被推翻的部分就地标注）**：
  ① 「父片段 `clip` 为 `None`」是**模型**的假象——clip 挂在 segment 上而被读成了 material 的字段，
    真实值是恒等（`x=0, y=0, scale=1`），子层的 `clip.transform` 也一直都在（金色花字
    `x=0.129, y=-0.685, rotation=-0.184`）。② **不需要剪映导出**：封面 + 恢复后的 clip 通道
    就足以定式——「子画布按宽适配 + 垂直居中」把金色字幕四边对到封面 4–12 px 以内
    （封面 0.169–0.948 / 0.740–0.775，渲染 0.165–0.943 / 0.746–0.778）。
    ③ 「约占宽度 55% 的 logo 居中偏大」这一条仍**未标定**：logo 的基准缩放与锚点没有可用样本
    （封面上蓝色质心被展会背景污染），只有位置律由 ② 定了下来。
    ④ 本条原来那句「通道 2 与通道 1 在同一时刻的画面/字幕独立对上」请降级看：
    当时两条链**共享同一个 clip 通道为 null 的模型**，一致只能证明同源，不能证明对。
    真正的交叉验证是 P-14（两条链各自对封面）。
- **副产品一条工具事实**：`scripts/browser_soak.py` 的分角色采样把内存判据从「猜」变成「读」
  （纹理复用后峰值 5393 → **1383 MB**，620 s 窗口 0 秒超线，判据 PASS）；
  通道 2 与通道 1 在同一时刻的画面/字幕**独立对上**（同一支镜头、同一句字幕、同一位置），
  这是本项目第一次拿到两条渲染链的交叉验证。
- **Path**：`temp/playback-test/render-0.5.png`（修前/修后三轮）、
  `temp/playback-test/find_cover_caption.py`（封面归属定位）、
  `temp/playback-test/oracle/cover-search.json`（1 fps 搜索：最好 0.852@0 s、中位 1.273，
  无尖峰 ⇒ 归一化灰度 RMSE 对「缺图层」不敏感，需要按连通域/分层比对才有判别力）、
  `scripts/render_frame.py`、`scripts/playback_model.py::probe_container`。
- **证据等级**：缺陷 1/2/3 **已验证**（改前改后画面与计数都变了）；
  几何偏差当时**数值已测、正确律未定**——该律由 P-14 以封面为 oracle 单样本定下，
  图片基准缩放仍未标定（见上面的更正 ③）。

## P-12 浏览器链的三个「计数器正常、画面是黑的」缺陷（图片层补丁引出）

- **触发**：把 P-11 在通道 2 修掉的图片层搬到浏览器链（`temp/playback-test/player.html`）。
  补丁后 `node --check` 通过、判据电池全绿，但页面是黑的。
  **教训先说**：`composited_fps`、`decoded`、`requests/bytes` 这一整套度量对「像素到底有没有上屏」
  是盲的——三条缺陷没有一个能被计数器抓到，只有截图能。以后每轮改动必须出一张页面截图当完成证据。
- **缺陷 1｜Pixi 8 删掉了 `Texture.from(string)`**：图片分支 `await Texture.from('/media/'+id)`
  抛 `Cannot read properties of undefined (reading 'width')`，被 `.catch` 吞成日志行，
  logo 图层静默消失（同一时刻页面日志里 4 行 `! img`，两个 photo 段 × 两次 paint）。
  改法：按 id `fetch` → `createImageBitmap(blob)` → `Texture.from(bitmap)`，与视频走同一条只读路由。
- **缺陷 2｜`texture.source.image = bmp` 在 v8 里是一个不存在的属性**（这条最贵）。
  P-06 的省内存修法是「复用 Texture 对象、只换图」，写的是 `sp.texture.source.image = f.bmp`；
  v8 的 `TextureSource` 根本没有 `image` 访问器（`grep 'set image(' pixi.mjs` 零命中，
  真正的载体是 `.resource` + `.update()`），于是赋值只是挂了个野属性，
  GPU 仍绑着**上一帧的 bitmap**，而下一行 `stale.close?.()` 正好把它关掉 ⇒
  第一帧之后整个视频层什么都不画，画布只剩清屏色。
  现场特征：场景图里 sprite `visible=true`、`1080x1920`、`source.image` 是活的 ImageBitmap
  （2D 采样亮度 117/255），屏幕上却是纯黑——**「有图」和「上图」是两件事**。
  改法：`sp.texture.source.resource = f.bmp; sp.texture.source.update();`（`update()` 尺寸不变时
  只 emit `update` 触发重传，不新建 GPU 资源，因此 P-06 的收益保留）。
- **缺陷 3｜复合片段 group 双重居中**：`placeGroup()` 把容器放到画布中心 (540,960)，
  而子层 `place()` 自己也按画布中心定位 ⇒ 子层落到 (1080,1920)，正好在画布外。
  本草稿 12 个复合子段全部 `clip=null`，于是主画面、金色花字、logo 一起消失，
  只有主时间线自己的白字幕在。改法：容器 `pivot` 设到画布中心，
  这样 `clip=null` 时 group 是恒等变换，而 scale/rotation 仍绕画面中心。
  与 P-02/P-11 的关系：这条不是「子画布→父画布映射律」本身（仍未标定，见 Q-4），
  而是我们自己的实现把两次居中叠加了——先修实现，再谈律。
- **验证方式**（新增，可复用）：`app.renderer.extract.base64(stage)` 会把整棵 stage 连画布外的内容
  一起出图（本轮出成 1392×1958），会误导；**判据以 `take_screenshot` 的真实合成分辨率为准**，
  场景图与 bitmap 亮度只用来定位「断在哪一段」。
- **修后读数**（同一 build，`?model=model-proxy.json`，10 s 窗口 ×1、seek 12 次，
  `qmax=4 pool=4 loop=1`，30 fps 目标；计数口径见 P-05）：
  `composited_fps 27.3`（273 帧/10.001 s）、`rt 0.998`、`fresh_track_frames_per_second 49.6`、
  seek 中位 **29 ms** / 最大 53.2 ms（12/12 冷）、首帧 **116.4 ms**、
  `errors []`、`tick_errors 0`、混音 `peak_rms 0.445`、`loudness_applied 3` / `fades_applied 3`、
  10 s 取块 3585 次 / 178 MB。与 P-05 的修前基线（27.65 fps / 31.5 ms / 226.5 ms）同档，无回归。
- **内存判据复测**：`source.update()` 走的是重传而不是重建，但 P-06 的结论是用 620 s 窗口量出来的，
  所以必须重跑同一口径：`rss-soak-imgfix.txt`（600 s，tag `soak-imgfix`），
  对照基线 `rss-soak-600-texreuse.txt`（peak 1383 MB、median 990 MB、0/614 秒超 2048）。
- **Path**：`temp/playback-test/player.html`（`imageTexture`、`placeImage`、`placeGroup`、
  视频 sprite 的 `resource`+`update()` 交换）、`temp/playback-test/player.html.bak-images`（改前）、
  `temp/playback-test/browser-0.5-images.png`（extract 版，见上条陷阱）、
  `temp/playback-test/report-playback.jsonl`（本轮最后一行 = 修后电池）。
- **证据等级**：缺陷 1/2/3 **已验证**（改前改后页面截图对比：黑屏 → 画面+白字幕；
  再改 → 复合子层的 logo 与金色花字出现在画布内）；
  修后 build 的 600 s 内存判据**在测**，出数前不改 P-06 的结论。

## P-13 `clip` 挂在 segment 上，模型却从 material 里读：几何通道整条是空的

- **现象**：追 P-11 的封面字幕偏差时直接读解密稿，发现 `segments[].clip` 里有值
  （主时间线白字幕 `transform.y = -0.4427083333333333`，另一条字幕还有 `scale 1.2529916784854136`），
  而 `model.json` 里这些段的 `clip` 全是 `null`。原因在
  `scripts/playback_model.py`：`clip = mat.get("clip")`——读的是**素材**上的 clip，
  而这个 schema 里 clip 是**片段**字段。
- **影响面（计数口径：片段，含复合子层，136 段总数）**：修好后 99/136 段带几何
  （video 55/55、subtitle 40/40、text 2/2、photo 2/2、audio 0/37 —— 音轨本来就没有 clip）。
  在此之前，两条渲染链对 transform/scale/rotation **一个都没应用过**：
  字幕一律画在画布正中（`render_frame.py` 的 `x=(cw-total)/2, y=(ch-h)/2`），
  图片一律 uniform-fit 居中。P-11 记的「封面字幕中心 0.746 vs 我们 0.500」偏差，
  根因不是复合映射律，而是这条 clip 通道断了。
- **更要紧的一条（并号时定为 F-057 的第 ③ 点）**：这条律**不是本轮测出来的新东西**——
  `spec/panel-map.yaml:16` 早就写着 `segment.clip.transform.x/.y, conf: verified`，
  渲染律 `位移px = 值 × 该轴边长 / 2`、y 向上、锚点=字框中心出自 F-035（用户导出的成片实测）。
  也就是说规格是对的、我们是**没读规格**把自己的实现写歪了；这类缺陷只能靠
  「模型自报几何覆盖率」这种断言兜住（已加：`stats.geometry_segments`）。
- **同时纠正 P-11 的一句话**：当时写「主时间线自己的 text 轨在浏览器里看起来是对的」——
  那是「居中恰好看起来正常」的误判，白字幕真实位置在 0.721 高度（`y=-0.4427` 按 ±1=半画布解释）。
- **Path**：`scripts/playback_model.py`（clip 取值处）、
  `temp/playback-test/probe_geometry.py`（把段与素材上所有几何字段打出来）、
  `temp/playback-test/model.json`（重生成，L1 断言仍 0 错 0 警）。
- **防回归**：`stats` 新增 `geometry_segments / geometry_total`，模型自己就把这条通道当断言报出来
  （本草稿打印 `geometry 99/136`）；再有人把 clip 读错对象，数字会直接掉到 0。
- **证据等级**：**已验证**（同一支草稿，改前 clip 覆盖 0/136，改后 99/136；
  改前后 `render-0.5.png` 与 `render-0.5-clipfix.png` 画面差异肉眼可见）。

## P-14 复合子画布→父画布的映射律：按宽适配 + 垂直居中（封面给了 11 px 的判定）

- **待标的事**：本草稿的 combination 子草稿画布是 `1080x1440`（`ratio: 3:4`），
  父画布 `1080x1920`，而父片段 `DAC95A4C` 自己的 `clip` 是恒等
  （`x=0, y=0, scale=1, rotation=0`）——所以「子画布怎么贴到父画布」没有任何数据可抄，只能标定。
- **候选律与判别**（口径：金色字幕 `#FFDE00` 像素质心，全画布、每 2 列采一次，
  封面与渲染图同一判据）：
  | 律 | 预测质心 y | 与封面差 |
  | --- | --- | --- |
  | 拉伸到父画布（通道 2 改前） | 0.843 | 0.088 |
  | 按宽适配 + 垂直居中（letterbox 240 px） | **0.757** | **0.002** |
  | 按宽适配 + 顶部对齐 | 0.632 | 0.123 |
  封面实测 `(cx 0.537, cy 0.755)`；通道 2 用「按宽适配 + 垂直居中」重渲后实测
  `(cx 0.527, cy 0.761)`，金色像素数 12307 vs 封面 10716（差 15%，字体光栅差异量级）。
  **两轴残差都 ≈ 11 px（画布的 0.6%）**。
- **不算证据的一条**：logo 的蓝色质心（封面 0.379/0.285 vs 预测 0.337/0.250）不能用——
  背景里的展会蓝色展板同色域，被污染。logo 只能靠肉眼看图层关系。
- **仍未定的**：① 父片段 `clip` 非恒等时，law 里 clip 与 letterbox 的复合顺序（本草稿没有这种样本，
  5 个复合父段里 4 个 clip 恒等、1 个只有 `y=-0.0812`）；② 图片层 `clip.scale` 与
  「1242x330 的 PNG 在子画布里的基准缩放」是否同源；③ 字幕 `scale_x` 是缩放字号还是缩放整层
  （通道 2 按字号实现，浏览器按整层 Sprite.scale，两者在 scale≠1 时会有布局差）。
- **浏览器链同口径复测（已做，2026-10-22）**：修完 `drawText` 的单位错（它用模块级 `W/H` 而不是
  本次调用的 `size`，复合子层因此被按父画布居中，比律低 169 px）后，
  `t=0.3 s` 场景实测金色字幕包围盒中心 **(0.564, 0.757)**、白字幕 **(0.500, 0.721)**、
  两个 logo Sprite **(0.337, 0.250) / (0.332, 0.248)** —— 与 P-14 的预测值逐位吻合；
  页面截图与 `render-0.5-clipfix.png`、封面三方的图层关系一致（logo 在上方、两句字幕错落在下三分之一）。
- **修后判据读数**（最终 build，10.001 s 窗口 ×1、seek 12 次、`fps=30 qmax=4 pool=4 loop=1`）：
  `composited_fps 28.39`（285 帧）、`rt 0.995`、`fresh_track_frames_per_second 51.8`、
  seek 中位 **30 ms** / 最大 50.2 ms、首帧 **125.7 ms**、`errors []`、`tick_errors []`、
  `audio_errors 0`、`peak_rms 0.408`、heap 43 MB、10 s 取块 3603 次 / 180.0 MB。
  内存判据在同一 build 上重跑 600 s（tag `final-geo`）；
  上一 build（`imgfix`，只差字幕位置）实测 peak **1462 MB** / median 1064 MB / 0/595 秒超线，
  对照 P-06 基线 peak 1383 / median 990 —— 纹理换帧改的是 `resource`+`update()`，没有把
  每帧新建 GPU 资源的代价带回来。
- **Path**：`temp/playback-test/measure_cover_bands.py`（封面色带质心 + 三种律的预测对照）、
  `temp/playback-test/oracle/cover-bands.json`（封面与渲染图的 gold/blue 质心与 1–99 分位包围盒、
  四个子层的预测坐标；`blue.x_span` 封面 0.004–0.994 ⇒ 蓝色判据被背景吃掉的直接证据）、
  `temp/playback-test/render-0.5-clipfix.png`、`scripts/render_frame.py`（子层贴图改按宽适配居中、
  `draw_text` 应用 clip）、`temp/playback-test/player.html`（`childSize()` +
  `placeGroup(node, clip, child, size)` + `drawText` 单位与 alignment 分支）。
- **证据等级**：映射律**单样本已验证**（一份封面、一条 3:4 子画布，四边残差 4–12 px），
  且**两条渲染链独立对上**；`alignment` 的水平语义见 Q-7（本 draft 的反例）。

## P-15 相机原片的 `pcm_s16be` 音轨在浏览器链里能解（Q-5 关闭）

- **为什么要单独测**：判据电池的代理配方是 `-an`（SP-10 时混音还没接线），所以**混音器至今只吃过 mp3**；
  而这份草稿 25 个相机文件里 **18 个的音轨是 `pcm_s16be`**（XAVC，口径：文件级 ffmpeg 探测）。
  不单独喂原片，就等于从没在这条链上验证过相机声音。
- **做法**：`temp/playback-test/pcm-probe.html` 走与播放器**完全相同**的路由
  （网关 Range → `CustomSource` → `ALL_FORMATS` → `getPrimaryAudioTrack()` → `AudioBufferSink.buffers()`），
  只是把结果打出来；需要另起一个服务**原片**的网关（代理清单里没有原片）：
  `python scripts/preview_gateway.py --port 8791 --serve-dir temp --model temp/playback-test/model.json`。
- **读数**（每支取时间线前 0.5 s 的音频）：
  | 文件 | mediabunny 报的 codec | 采样率/声道 | 解出帧数 | 峰值 |
  | --- | --- | --- | --- | --- |
  | `C7502.MP4` | `pcm-s16be` | 48000 / 2 | 24024（1 个 chunk） | 0.8062 |
  | `C7573.MP4` | `pcm-s16be` | 48000 / 2 | 24024（1 个 chunk） | 0.7400 |
  | `IMG_7322.MOV` | `aac` | 48000 / 2 | 24576（24 个 chunk） | 0.2643 |
  | `0291b…dbd2.mp3`（对照） | `mp3` | 44100 / 2 | 20736（18 个 chunk） | 0.3296 |
  四支全部 `ok:true`，无异常、无削顶（峰值 <1.0）。⇒ **PCM 不是这条链的编码面缺口**；
  顺带纠正一处：Sony 那支 `.MOV` 的音轨是 **aac**，不是 PCM——P-03 记的「XAVC=PCM」只适用于 `.MP4` 那批。
- **副产品**：PCM 一次给 24024 帧一个大 chunk、AAC/MP3 给 18–24 个小 chunk ⇒
  混音侧 0.5 s 槽位的拼接逻辑对两种粒度都成立，但 PCM 路径下 `chunks` 计数会显著偏低，
  看这个数判断「有没有在解」会误判，应按 `frames` 看。
- **还欠的那一段**：播放**时**的相机声音（不是解复用）——要么给代理配方加一条音轨
  （`-c:a aac -b:a 160k`，代价是 25 支重转 + 判据需重测），要么让播放器在需要声音时
  回原片取音频（多一路 Range 流，内存判据要重看）。本轮**没有**改配方，以免让刚量完的
  `final-geo` 内存读数作废。
- **Path**：`temp/playback-test/pcm-probe.html`、`temp/playback-test/report-pcm.jsonl`、
  `temp/playback-test/gateway-orig.out`（8791 那个只服务原片的实例）。
- **证据等级**：**已验证**（四支文件各自独立解码成功，含两支 PCM）。

## P-16 图层掩码 IoU 把「位置对」和「字形对」分开量：通道 2 的字幕低了 12 px（PIL 锚点）

- **为什么要再量一次**：P-14 用质心判定字幕对上（残差 11 px），但把整帧按颜色掩码求 IoU，
  `gold ∩ / gold ∪` 只有 **0.2666** —— 质心说「盒子在位」，掩码说「笔画没叠上」。
  两个数不矛盾，是**两种判别力**；分开之后才知道下一步该标什么。
- **诊断**：对 ±12 px 平移搜最优，IoU 在位移 **(dx +4, dy −12)** 处升到 **0.7212**，
  与质心差 0.006×1920 ≈ 11.5 px 完全吻合 ⇒ 残差是**整体垂直偏移**，不是字形。
  根因在通道 2：PIL `ImageDraw.text` 默认锚在 **ascender 线**，而代码按 ink 高度 `h` 居中，
  于是墨迹整体下移 `box[1]`（本草稿 13 em × 1080 × K_EM ≈ 80 px 字高，偏移约 12 px，
  即 ~15% em）。浏览器链没这个毛病（Pixi 按排版盒居中，实测 cy 0.757 vs 封面 0.755）。
- **修后**（`render-0.5-inkfix.png`，同一判据、同一封面）：
  | 量 | 封面 | 修前 | 修后 |
  | --- | --- | --- | --- |
  | 质心 | 0.537 / 0.755 | 0.527 / 0.761 | **0.528 / 0.754** |
  | x 包围盒 1–99 分位 | 0.169–0.948 | 0.165–0.943 | 0.165–0.944 |
  | y 包围盒 1–99 分位 | 0.740–0.775 | 0.746–0.782 | **0.739–0.775** |
  | 零位移 IoU | — | 0.2666 | **0.5230** |
  | 最优平移 IoU（位移量） | — | 0.7212（+4,−12） | 0.7983（+4, 0） |
  ⇒ 垂直偏移被消掉（最优 dy 从 −12 变 0），IoU 翻倍，**字高两侧完全对上**（0.739–0.775 vs 0.740–0.775）。
- **剩下的那 0.2 不是我们的错**：金色像素数封面 21408 vs 渲染 24779（面积比 1.1575），
  但**包围盒高度一致** ⇒ 不是字号差（差 15% 面积若来自线性缩放需要 7.6% 的字高差，量不出来）。
  合理解释是封面是 JPEG：细笔画边缘被色度二次采样/压缩推出 ±46 的容差带，掩码**少算**了边缘像素。
  ⇒ 给 L3 定阈值时用：拿 JPEG 当参考时，细字图层的 IoU 上限就在 0.5–0.8 一档，
  **该用包围盒/分位数当判据，IoU 只用于「图层有没有画错位置」的粗判**；要量字形就得对 PNG 成片比。
- **Path**：`temp/playback-test/measure_cover_iou.py`（参数化，可对任意渲染图重算）、
  `temp/playback-test/oracle/cover-iou-render-0.5-inkfix.json`、
  `temp/playback-test/render-0.5-inkfix.png`、`scripts/render_frame.py::draw_text`（`tops` 与 `- top`）。
- **证据等级**：**已验证**（改前改后同一判据、同一封面的六个数都动了，且最优位移归零）。

## P-17 组合渲染缓存走 DLL 字符串 API：**音频解出来是对的，视频不是**（Q-1 的可用于判据的那一半）

- **动机**：想给 P-16 找一个「比封面更强」的原生 oracle。草稿里 3 个
  `Resources/combination/*_video.mp4` 是剪映自己排布 combination 子层的渲染缓存，
  如果能拿到它的帧，logo 基准缩放与子画布映射律就能直接对像素定案，不需要用户导出。
- **已做过的事**：`temp/playback-test/job-media.json` 里那次**合规**的 DLL 作业（`op: decrypt_bytes`，
  只读源、只写 `temp/`）早就把这 5 个 combination 文件（3 视频 + 2 音频）解到了
  `temp/playback-test/media-dec/`——所以不必绕任何算法，先看现成产物。
- **实测**（口径：pin 的 ffmpeg `-f <fmt> -i` 探测 + 字节级计数，逐文件）：
  | 产物 | 源字节 | 解出字节 | 比值 | 判定 |
  | --- | --- | --- | --- | --- |
  | `01400053…_audio.aac` | 528,593 | 93,041 | 5.68 | **有效 AAC**（Main，1.37 s，538 kb/s） |
  | `D5614490…_audio.aac` | 893,356 | 154,274 | 5.79 | 同上量级 |
  | `1ECF4DB3…_video.mp4` | 21,552,291 | 4,027,796 | 5.35 | 无容器结构，打不开 |
  | `7553BBFF…_video.mp4` | 9,336,700 | 1,747,230 | 5.34 | 同上 |
  | `D1F33107…_video.mp4` | 7,049,469 | 1,319,342 | 5.34 | 同上 |
  视频产物里 `ftyp`/`moov`/`mdat`/`avc1`/`00 00 00 01`/`00 00 01` 的出现次数**全为 0**，
  香农熵 7.95–7.96（与密文同量级）；`mp4`/`matroska`/`nut`/`h264` 四种 demuxer 全拒，
  `m4v`（裸 ES）报 `header damaged`。
- **结论（对判据有用的那半句）**：combination 的**视频**渲染缓存**不能**经字符串 API 变成可用帧
  ⇒ 原生 oracle 这条路在 M2 里走不通，L3 仍需一次导出。
  顺带把 Q-1 收窄：这些缓存**不是**草稿那一套（`probe_container` 看到的头是
  `f9 f9 f9 d9 …`，而 `decrypt_bytes` 出来的东西也不是 MP4），且**同一 API 对音频正确、对视频不正确**
  ——说明它按流类型走不同分支，或视频侧还有第二步没被这个 op 覆盖。
- **给 agent 的陷阱记录**：`decrypt_bytes` 对不支持的输入**不报错**，返回一段等长量级的高熵 blob。
  「API 成功返回」不等于「解出来的东西可用」；判定必须落在容器探测/可解码上。
  这一条正是判据 6（编码面不得静默黑帧）在服务端的同型问题。
- **未做的越界动作（需要用户解除禁令才做）**：三个视频密文的前 12 字节按 MP4 魔数做 crib，
  与单字节 XOR 完全自洽（`f9f9f9d99f8d8089908a9694` ⊕ `f9` = `00 00 00 20 ftyp isom`，
  另两支分别 ⊕ `a5` / ⊕ `d0` 同样得到 `ftyp isom`）。**本轮只记录观察，没有据此产出任何明文帧**——
  「加解密只走内存串 API、不做算法逆向」是用户划的线，要破此线需明确授权。
- **Path**：`temp/playback-test/job-media.json`、`temp/playback-test/media-dec/`、
  `scripts/jy_crypto/{client,worker,dll}.py`（作业通道本身没动）。
- **证据等级**：表格里的字节数/比值/计数与 ffmpeg 判定 **已验证**；
  「视频侧还有第二步」是**假设**，未验证。

## P-18 预览是「哑」的：混音器只走 audio 轨，相机口播的声音从没进过链路

- **缺陷**：`scheduleAudio()` 第一行就是 `if (track.type !== 'audio') continue;`。
  剪映里视频片段自带声音（不静音就播），所以口播草稿在预览里**听不到人声**——
  对「不开剪映看改完的效果」这个用途是硬伤。本轮之前所有电池都只混了 34 条 sound + 3 条 music
  的 mp3，`sample_rate` 读数一直是 44100（= 只有 mp3 进过链），这一点当时没人看出来。
- **测试夹具的连带问题**：SP-09 的代理配方是 `-an`，所以就算修了混音器也没东西可混。
  补一支 `temp/playback-test/add_proxy_audio.py`：视频流 `-c:v copy` 直接搬、只把原片音轨转成
  `aac 160k / 2ch` 封回去，25 支 30 秒完成，**画面字节不变**，因此 P-14/P-16 的像素结论继续成立。
- **`has_audio` 指望不上**：草稿里视频素材根本不写这个字段
  （按段计：`('video', None) 54`、`('video', False) 2`＝photo，音频轨 37 段也是 None）。
  于是改成**以解封装器为准**：`getPrimaryAudioTrack()` 为空就把该路径记进 `silentPaths` 跳过，
  不算错误、不重复尝试。
- **一个真竞态（这条最值钱）**：`streamFor()` 建好条目后**先不持引用**，调用方要等一个微任务才
  `hold()`；而 `scheduleAudio` 会被播放循环并发重入，于是 A 刚建的条目能被 B 的 LRU 淘汰并
  `input.dispose()`，A 随后拿着已销毁的流去 `buffers()` → `Input has been disposed`。
  三次尝试的读数：把 `hold` 挪到调用点 **9 → 4**（没治根）；淘汰时跳过「有活着的 audio job
  持有该 id」的条目 **9 → 4**（只挡住已注册的）；最终把所有权做进 `streamFor` 里
  （`own=true`，与插入同一个同步步）**→ 0**。全文件只有这一处 `dispose()`，所以窗口就是它。
- **修后读数**（`model-proxy-a.json`，10.001 s 窗口、12 次 seek、`fps=30 qmax=4 pool=4 loop=1`）：
  `audio_errors 0`、`errors []`、`chunks 3405`、`nodes 172`、`jobs 3`、
  `sample_rate 48000`（相机声确实进了混音）、`loudness_applied 6`、`fades_applied 3`、
  `composited_fps 28.23`、`rt 0.997`、seek 中位 30.4 ms、首帧 127.5 ms、heap 44.5 MB
  —— 与无声 build（28.47 fps / 32.9 ms / 126.7 ms）同档，**没有性能回归**。
- **要留个心眼的数**：`peak_rms` 从 0.4451 抬到 0.5487（+23% 余量被吃掉）。
  它是 RMS，**不是削顶判据**；P-9 当年用 peak_rms<1 收的「不削顶」结论，在多轨叠加后
  只说明平均能量没爆，不代表采样不触 1.0。真判据要另加 peak-full-scale 统计。
- **内存判据带声重测**：600 s、tag `audio`（`temp/playback-test/rss-audio.txt`），
  对照无声的 `rss-final-geo.txt`（peak 1343 MB / median 1025 MB / 0/594 秒超线）。
- **Path**：`temp/playback-test/player.html`（`streamFor(..., own)`、`silentPaths`、
  `scheduleAudio` 走 video 轨、淘汰的 job 守卫）、`temp/playback-test/add_proxy_audio.py`、
  `temp/playback-test/proxy-a/`、`temp/playback-test/model-proxy-a.json`、
  `temp/playback-test/report-playback.jsonl`（末行＝带声电池）。
- **证据等级**：混音走通与竞态修复 **已验证**（`audio_errors` 9→4→0、`sample_rate` 44100→48000、
  `chunks`/`nodes` 同步上升）；带声内存读数**在测**。

## P-19 几何通道一通，两处「只有画面会看出来」的错就露了：文字不缩放不旋转 + 阴影偏移翻倍

- **几何面普查**（口径：段，含复合子层；99 个带 clip 的段）：
  `x ∈ [-0.336, 0.380]`、`y ∈ [-0.721, 0.672]`、`scale ∈ [1.00, 5.83]`、
  `rotation ∈ [-0.184°, 16.321°]`、alpha 全 1.0、flip 全空、没有 |v|>1.2 也没有非正缩放。
  **只有 3 个段** scale>1.3 或 |rot|>1，全是文字：`F8ADA1E9` 3.82×（29.93 s）、
  `28D805BD` 5.83× 且 −16.32°（33.67 s）、`F927DA6E` 2.18×（5.40 s）——就是口播里那种「突然放大」的花字。
- **缺陷 A（浏览器）**：`drawText()` 设了 x/y/zIndex/visible，**从来没碰过 `group.scale` 与
  `group.rotation`** ⇒ 三个花字在预览里一律 1× 摆正，而通道 2 是按字号乘了 scale 的。
  补上后实测：`？` 那一组 `rotDeg -16.32`、`scale 5.83`、世界包围盒
  `[576,1124,338,493]` ⇒ 中心 (0.69, 0.714)，与通道 2 `render-33.67-rot.png` 同一位置同一倾角。
- **缺陷 B（通道 2）**：`draw_text` 里阴影用的是 `x + ox + shx`，而 `x` 本身已经是
  `(cw-total)/2 + ox` ⇒ clip 偏移被加了**两次**，花字的阴影与本体分开 `2·ox`（`28D805BD` 的
  `x=0.38` ⇒ 205 px）。改前那张 `render-33.67.png` 里白色大问号右边多出一个孤立的黑色虚影，
  就是这个。同时通道 2 完全没有旋转通路。
  改法：把「画本体+阴影」收进 `paint(dst)`，非零角度时先画到一张与画布同尺寸的 scratch，
  再 `rotate(-rot, center=墨迹中心)` 合成 ⇒ 阴影跟着一起转，坐标仍是画布系。
- **顺带又靠近封面一点**：阴影偏移修正后，`t=0.5` 金色字幕对封面的掩码
  IoU **0.5230 → 0.5394**、最优位移 IoU **0.7983 → 0.8329**、面积比 1.1575 → 1.1277
  （位移仍是 (dx +4, dy 0)，垂直已无系统偏差）。
- **Path**：`temp/playback-test/player.html`（`drawText` 的 scale/rotation）、
  `scripts/render_frame.py::draw_text`（`paint(dst)` + `layer.rotate(center=…)` + 去掉重复 `ox`）、
  `temp/playback-test/render-33.67.png`（改前，带孤立虚影）与 `render-33.67-rot.png`（改后）。
- **证据等级**：**已验证**（两条链在同一时刻的倾角、缩放、中心都量到了；改前改后图都在盘上）。

## P-20 混音确实削顶了：`peak_rms` 0.51 之下藏着 `peak_fs` 1.076

- **为什么之前看不出来**：P-9 收「不削顶」用的是 `peak_rms`（分析器窗口的均方根）。
  RMS 是能量量，**原理上答不了「有没有采样触到满刻度」**：本次带相机声后
  `peak_rms` 只有 0.499–0.549，看着很安全。
- **补的统计**：`measureAudio()` 顺手取窗口内 `max|x|` 记成 `peak_fs`，并数 `peak_fs ≥ 0.999`
  的窗口个数 `clipped_windows`。它只覆盖每 tick 抽到的那一个 `fftSize` 窗口，
  **是下界不是证明**（两次窗口之间的瞬态可能漏）。
- **读数**（`model-proxy-a.json`，带相机声，两轮电池）：
  | 轮 | peak_rms | peak_fs | clipped_windows |
  | --- | --- | --- | --- |
  | 10.001 s / 12 seeks | 0.508 | **1.0758** | **5** |
  | 6.0 s / 6 seeks | 0.499 | **1.0019** | **1** |
  ⇒ 主输出在数字域**过 1.0**，链路里已经挂了 DynamicsCompressor 也没挡住（压缩器有启动时间，
  快瞬态直接穿过去）。相机声进混音器之前（只混 mp3）从没出现过这个数。
- **没有就地「修」**：要压不削顶很简单（降 master gain / 加限幅），但**剪映自己的母带是不是也削顶**
  无从判断——草稿给每条素材写了 `loudnesses[]` 目标响度，若我们照实应用后仍爆，
  很可能原片就爆。在没有导出成片当参照之前，把峰值压下去会让预览**更不像**成片。
  所以本轮只把度量补上，处置等 L3 的参照物到位再定（见 Q-8）。
- **另一条要更正的读数**：首帧判据今天跑了 9 次：
  116.4 / 125.7 / 122.3 / 137.7 / 126.7 / 141.0 / 127.5 / 351.4 / 82.5 ms，
  **中位 127 ms、最好 82.5、最差 351.4**。判据 `≤300 ms` 按中位成立、按最差不成立（9 次里 1 次越线）。
  P-05 当时报的是单点读数，口径应改成「中位 + 最差」，Q-9 记着找那一次 351 ms 的成因
  （怀疑是冷文件缓存或首轮 seek 风暴，未验证）。
- **Path**：`temp/playback-test/player.html`（`peak_fs` / `clipped_windows`）、
  `temp/playback-test/report-playback.jsonl`（末三行＝带声三轮）。
- **证据等级**：削顶**已验证**（两轮独立复现）；成因（哪一路、哪一瞬态）**未定位**；
  首帧 351 ms 那次**未复现**。

## P-21 把判据 6 从「加密素材会喊」扩成「有图层没出图也要喊」，并用假阴性证明它真的会喊

- **动机**：P-12 那次整层视频黑屏，判据 6 的现有实现（不可解封装 → 角标）一声不吭。
  也就是说这条判据当时只是**纸面上的**：它检查的是「素材读不了」，不是「画面上没有东西」。
- **加的守卫**（`temp/playback-test/player.html::paint`）：每帧播完后，对每条视频轨当前生效的片段
  检查它在 `sprites` 里有没有一个 `visible` 的节点；连续 `BLACK_STREAK = 5` 帧没有就
  ① 亮角标 ② 记进 `blackSeen` ③ 电池里以 `black_streaks` 报数。
  跳过条件保持与既有语义一致：没有 media、文件不存在、容器不可读（后者走角标的另一条分支）。
- **第一版是假阴性，靠一个坏夹具才抓出来**：`stat.blackStreaks` 当时存的是**当帧快照**，
  电池在 12 次 seek 之后才上报，播放头早就离开出问题的那段，读数永远是 `[]`——
  一个「看起来通过、其实从没测过」的守卫，比没有守卫更危险。
  改成累计集合 `blackSeen` 之后才有判别力。
- **负例夹具**（可复用）：`temp/playback-test/model-blacktest.json` = 正常代理模型，
  只把 track 0 第一段 `25BAD37B`（0–6.6 s）的 `media.path` 换成一支 mp3（容器可读、但没有视频轨），
  于是 `streamFor(path,'video')` 抛 `no video track`、该层什么都不画。
  实测：`black_streaks ['25BAD37B']`、`errors 12`、`fps 29.9`
  —— **帧率正常而图层是空的**，正是这组计数器测不到的情形，守卫抓到了。
- **正例对照**（完整 build：几何通道 + 相机声 + 两个渲染器修正）：
  `black_streaks []`、`errors []`、`tick_errors []`、
  `composited_fps 29.55`（296 帧 / 10.001 s）、`rt 0.997`、`fresh_track_frames_per_second 54.01`、
  seek 中位 30.6 ms / 最大 48.6 ms、首帧 88 ms、heap 44.3 MB、
  音频 `chunks 3202 / errors 0 / peak_rms 0.443 / peak_fs 1.0604 / clipped_windows 4`、
  10 s 取块 4189 次 / 185.7 MB。六条判据在这一个 build 上同时成立（削顶那条按 Q-8 记为已知偏差）。
- **Path**：`temp/playback-test/player.html`（`missStreak` / `blackSeen` / `BLACK_STREAK` /
  `r.black_streaks`）、`temp/playback-test/model-blacktest.json`、
  `temp/playback-test/report-playback.jsonl`（末两行＝负例与正例）。
- **证据等级**：守卫**已验证**（负例触发、正例为空，两个方向都测过）；
  `BLACK_STREAK=5` 这个门限是**拍的**，没做过灵敏度扫描。

## P-22 四层门 `scripts/playback_check.py`：一条命令重跑 L1/L2/L4/L6，第一次跑就抓到一个视频侧的同型竞态

- **为什么要它**：这一天里五个缺陷（P-12 黑屏、P-13 几何通道全 null、P-16 字幕低 12 px、
  P-18 混音听不到相机声、P-21 守卫只会报假阴性）全都是**手工一次性检查漏掉的**，
  而且每一次检查当时都「看起来是绿的」。再靠自觉就会漏第六次，所以把四层钉成一条命令：
  `python scripts/playback_check.py --plain … --draft-root … --timeline … --model … --cover …`
  → L1 模型断言、L2 通道 2 出图对封面色层包围盒、L4 无头浏览器电池（六条判据）、
  L6 黑帧守卫**正反双向**（正常模型必须为空 + `model-blacktest.json` 必须非空），
  任一 FAIL 退出码非 0。网关由脚本自己起、跑完自己关。
- **第一次跑就 FAIL 了一条**：`L6 no silent black frame — black_streaks [], errors 12`。
  12 条 `! Input has been disposed.` 来自**视频腿**：`frameFor()` 在没有前向泵的时刻
  （暂停中、seek 之间）直接 `st.sink.getSample()`，全程**没有引用**，于是 LRU 能把流 dispose 掉。
  P-18 只把 `own` 修到了音频腿，视频腿的同一窗口一直开着。
  修法：`streamFor` 之后立刻 `hold(st)`，包住整个取帧，`finally` 里 `release(st)`（泵自己的引用另算）。
  连带症状：那一轮 `sample_rate` 只有 44100 —— 相机声根本没进混音器，因为它的视频流不断死。
- **顺手修掉两个度量自身的坑**：
  ① `audioStats.sample_rate` 是**最后写入者**，44100/48000 谁后写谁，用它判断「相机声有没有混」会误判
  ⇒ 新增 `audio_rates_seen`（本次跑出现过的所有采样率），门里直接打这个数。
  ② 门里读 `rss-check.txt` 找 `startswith("rss_peak_mb=")` 永远找不到（它在一行的中间），
  却把原因报成「没有 rss 文件」——**一句写错的判据比没有判据更坏**，改成子串匹配。
- **修后门的全绿读数**（`model-proxy-a.json`，10.001 s 窗口、12 次 seek、`fps=30 qmax=4 pool=4 loop=1`）：
  `composited_fps 28.8`、`rt 0.996`、seek 中位 30.3 / 最大 54.4 ms、首帧 204.4 ms、
  Range 3707 次 / 182.4 MB、`black_streaks []` `errors []` `tick []`、
  `audio_errors 0`、`chunks 2706`、**`rates_seen [44100, 48000]`**（mp3 与相机声都进了混音）、
  L2 对封面金色层六个量最大偏差 **0.008**（阈值 0.02）、90 s 窗口 RSS peak 1356 MB。
  负例：`black_streaks ['25BAD37B']` 而 fps 仍 30 —— 正是「计数器全绿、画面是空的」那种情形。
- **削顶是间歇的**：三次门/电池跑分别得到
  `peak_fs 1.0535 / clipped_windows 3`、`1.1779 / 7`、`0.8886 / 0`。
  ⇒ Q-8 的处置不能靠一次读数下结论，得先固定调度路径（同一 seek 序列）再谈阈值。
- **Path**：`scripts/playback_check.py`、`temp/playback-test/model-blacktest.json`、
  `temp/playback-test/player.html`（视频腿 hold/release 包住取帧、`audioRates`）、
  `temp/playback-test/rss-check.txt` 与 `rss-check-neg.txt`、`temp/playback-test/check-0.50s.png`。
- **证据等级**：门**已验证可用**（能 FAIL、修后能全 PASS、负例能触发）；
  它现在覆盖 L1/L2/L4/L6，**不覆盖** 600 s 内存判据与 L3 成片比对（脚本里已按 INFO 标明）。

## P-23 门跑 5 遍出分布：削顶是**系统性的**（5/5），首帧离散度在修好视频腿后收敛到 168–246 ms

- **做法**：`playback_check.py --repeat 5`（每条判据取 5 个独立无头电池的**中位数**判 PASS，
  同时打印 min/max 与「几次越线」）。之前所有单点读数的问题不是数错，而是**一个数被当成一个结论**。
- **Q-8 就此定案（现象层面）**：5 个独立跑的 `peak_fs` =
  **1.032 / 1.0512 / 1.1192 / 1.1255 / 1.3244**，`clipped_windows ≥ 1` 的跑数 **5/5**。
  上一轮那个 `0.8886 / 0 窗` 才是例外。⇒ 混音超满刻度**不是间歇抖动，是常态**；
  而 `peak_rms` 五次都在 0.41–0.59，再次说明 RMS 看不见它。
  处置仍然**不做**：草稿给素材写了 `loudnesses[]` 目标响度，照实应用后必然叠加过 0 dBFS，
  剪映母带大概率同样削顶；在没有成片参照前压增益只会让预览更不像成片（等 L3 的导出）。
- **Q-9 就此收敛**：首帧 5 跑 **168 / – / 189.7(中位) / – / 245.9 ms，0/5 越 300 线**，
  比修视频腿前（82–351 ms、1/9 越线）明显收紧。合理解释是那次 351 ms 出在
  `getSample` 被 dispose 后重新拉流的跑上（P-22 的同一 build），但**未做归因实验**，
  只记为「修后 5/5 达标」。seek 同理收紧：中位 33 ms、最差 36.9 ms。
- **其余各层的分布**（n=5）：`composited_fps` 中位 **29.52**（min 28.86）、
  Range 中位 **4159 次 / 10 s**、`black_streaks/errors` **0/5** 跑出现、
  `audio_errors` **0/5**、`rates_seen [44100, 48000]`（相机声与 mp3 都稳定进混音）、
  L2 对封面金色层最大偏差 **0.008**、该跑 90 s RSS peak 1209 MB。
- **600 s 内存判据在门通过的这一个 build 上**（tag `gate`，视频腿修后）：
  peak **1674 MB**（s=163，gpu-process 1281 + renderer 285 + browser 75 + utility 32 + crashpad 1）、
  median **895 MB**、mean 913、**0/592 秒超 2048** ⇒ PASS。
  注意方向：**中位数降了（1062→895）而峰值升了（1367→1674）**——
  视频腿现在会在整个取帧期间持有流，seek 风暴里同时活着的流更多，瞬时 GPU 分配抬高。
  离阈值还剩 374 MB，但这条正是 Q-3（判据按 peak 还是 median）会翻转的地方：
  按 peak 剩 18% 余量，按 median 剩 56%。
- **Path**：`temp/playback-test/rss-gate.txt`、`temp/playback-test/rss-check0..4.txt`、
  `temp/playback-test/report-playback.jsonl`（末 6 行＝5 次电池 + 1 次负例）。
- **证据等级**：分布**已测**（n=5，独立进程）；351 ms 与 1674 MB 峰值的**成因未做归因实验**。

## 交接：一条命令复现全部结论（2026-10-22，M2 播放通道停在 turn 预算用尽处）

**跑门**（约 3–5 分钟，自己起网关、跑完自己关；L2 的 oracle 已换成成片同帧，见 P-26）：

```
python scripts/playback_check.py   --plain "temp/playback-test/plain/<草稿A>__draft_content.json.dec.json"   --draft-root "<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>"   --timeline 017E2FEC-11D0-47d6-87C1-9709D2A2F18D   --model temp/playback-test/model-check.json   --media-model temp/playback-test/model-proxy-a.json   --oracle-mp4 "<EXPORT_DIR>\<EXPORT_NAME>.mp4" --pixel-t 1.0 --pixel-colour 255,255,255   --cover "<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>\draft_cover.jpg"   --cover-frame "<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>\Resources\cover\BA76BCB5-DF8C-40e0-B7DC-42A8BEA03BFB.jpg"   --video-scan 0.05:0.55:0.05 --repeat 5
```

**L3 整帧基线**（离线、不起浏览器；oracle 是一次解出的全 1108 帧 @216px）：

```
python scripts/export_compare.py --model temp/playback-test/model-check.json --frames-dir temp/playback-test/oracle/dense216 --from 0 --to 36 --step 1 --work-dir temp/playback-test/l3 --report temp/playback-test/l3/baseline-1fps.json
```

最后一次全绿读数（`--repeat 2`）：12/12 PASS，L1 0 错 0 警 / 几何 99/136、L2 对封面 0.008、
L3 视频带 corr@32px **0.789**、fps 29.6、seek 36.5 ms、首帧 201 ms、Range 3777 次/10 s、
`black_streaks`+`errors` 0/2、`rates_seen [44100, 48000]`。600 s 内存判据单独跑：
`python scripts/browser_soak.py --url <同上播放地址>&playms=600000&seeks=0 --seconds 600 --tag gate`
→ peak 1674 MB / median 895 MB / 0/594 秒超线（`temp/playback-test/rss-gate.txt`）。

**停在哪儿**（2026-10-22 更新，成片到位后）：**L3 已经不再停在半路**——成片
`<EXPORT_DIR>\<EXPORT_NAME>.mp4` 经封面 sha256 同字节确认为本时间线的原生导出（F-069），
整帧逐帧基线已落地成 `scripts/export_compare.py`：37 个位置中位 **0.986/0.983/0.979/0.973**
（16/32/64/128 px）、双判据 PASS，并用 5 变体 × 8 时刻负例矩阵定了判据的区分力边界（F-072）。
过程中成片抓到并修掉了一个真缺陷：`segments[].visible=false` 被 L1 丢掉 ⇒ 两条隐藏叠加层被画
（F-071，t=0 整帧 0.778 → 0.994）。复合子画布映射律也在成片上密集重验（F-074，0.962 @64px）。
**此前那段「机器上没有可比对的成片」是 F-062 扫描器只读前 2 MB 造成的假阴性**（98.3% 的导出
`moov` 在尾部），已就地更正。

**下一步的候选**（都不需要再等导出）：
① 混音标定 U-88——成片母带 −0.026 dBFS、零削顶、窗 RMS 最大 0.2891，我们 0.41–0.59 且 4/8 跑
越界（F-073）；先让播放器把 0.5 s 窗 RMS **数组**随 `/report` 交回，再与成片曲线配对拟合。
② 段边界那一帧 U-89（t=6.600 只有 0.802，两侧都 0.96+），在 6.55–6.65 以 1/30 s 步长看崩口宽度。
③ 口径裁定 U-79：600 s 内存判据按 peak（现 1674 MB，余 18%）还是 median（895 MB，余 56%）——
这条是用户的线，不自行放宽。
④ 提交：见下段，按仓库规矩需先获同意。

**未提交的改动**（按仓库规矩，提交需先获同意）：根仓库新增
`scripts/{playback_model,preview_gateway,render_frame,browser_soak,playback_check,export_compare}.py`；
docs 仓库 `evidence/findings.md`（+F-057…F-074）、`evidence/unresolved.md`（+U-76…U-89、
结案 U-77/U-82/U-83）、`evidence/playback-log.md`（未跟踪）。
`scripts/media_probe.py` 与空 `CLAUDE.md` 属并发会话，未触碰。

**磁盘占用**：`temp/playback-test/` 约 18 GB，几乎全是代理片
（`proxy/` 25 支 4:2:0，`proxy-a/` 25 支带音轨）。都可再生：
`python temp/playback-test/make_all_proxies.py`（约 10 分钟 GPU）与
`python temp/playback-test/add_proxy_audio.py`（约 30 秒，视频流直接 copy）。
删掉 `proxy-a/` 不影响门的其他层，只让 `--media-model model-proxy-a.json` 那一路失效。
草稿本体全程只读。**收尾时的写入证据**（2026-10-22 07:18）：
`draft_content.json` / `.bak` / `draft_meta_info.json` / `draft_settings` / `draft.extra` /
`Timelines/017E2FEC/draft_content.json` 的 mtime 全部是 **2026-10-15 16:59–17:03**，
本目标始于 2026-10-21，故**没有任何写入**；`.locked` 当前不存在（JianYing 未持有该草稿）。

---

## 并号时要带走的开放项（暂占本文件编号，不进 U 号段）

- **Q-1** `Resources/combination/*_video.mp4` 用的是哪套容器/密钥（不逆向，只记现象与判据）。
  **P-17 记了可安全断言的一半**：字符串 API 对同一目录的音频解出有效 AAC、对视频解出无结构高熵 blob ⇒
  原生渲染缓存在 M2 里当不了 oracle；XOR 观察已记录但**未使用**，是否授权破「不逆向」这条线归用户。
- **Q-2** 代理片若仍留在共享盘，首帧与 seek 的代价（本轮代理全在本地；NAS 倍率 2.1–2.4× 是原片测的）。
- **Q-3** `≤2 GB` 判据按峰值还是中位（P-06）。
- **Q-4**（**已由 P-13 + P-14 关闭**，保留原问题供并号时对照）字幕「居中」的垂直位置是否真是画布中心？
  答案：**不是**，而且这问题早在 U-08/F-035 就结案了（`位移px = v × 边长/2`、y 向上、锚点=字框中心），
  本轮只是发现我们的模型没把它接上。位置来自 `segments[].clip.transform`（±1 = 半画布、y 向上），
  白字幕实测在 0.721 高度而不是 0.5；复合子层再叠加「子画布按宽适配 + 垂直居中」的映射律。
  原判断里两处要一起改掉：① 「本草稿 alignment 全缺席」不对——主时间线的 subtitle 确实没写，
  但 combination 子层的 text 有 `alignment=2`（其水平语义另见 Q-7）；
  ② 「主时间线自己的 text 轨在浏览器里看起来是对的」是误判，那时 clip 通道整条是 null（P-13）。
- **Q-5**（**已由 P-15 关闭**）`pcm_s16be` 音轨被单独引用成音轨的草稿，其音频路径仍未验证。
  **2026-10-22 量化了缺口**（计数口径：**文件**级，pin 的 ffmpeg `-i` 探测，非片段数）：
  本草稿 25 个相机文件里 **18 个的音轨是 `pcm_s16be`**、4 个 aac，另有 20 个纯音频素材全是 mp3；
  片段口径为 55 video / 40 subtitle / 2 text / 2 photo / 34 sound / 3 music（含复合子层）。
  浏览器链的混音只吃过 mp3（代理配方 `-an` 把相机音轨整条丢了），所以
  `pcm_s16be → AudioBufferSink → BufferSource` 这一段**在电池里从未被执行过**。
  **P-15 已用同一路由单独喂原片把它验掉**（两支 `pcm-s16be` 各解出 24024 帧、峰值 0.81/0.74）；
  剩下的缺口只是「播放时」的相机声音，见 P-15 末段。
  顺带记一处读数陷阱：播放器里那个计数器原叫 `pcm_seen`，实际是 `catch` 里的失败计数，
  读成「没解到 PCM」是错的——已改名 `audio_errors`（本轮读数 0）。
- **Q-6** XAVC `elst` 那 1 帧偏移（U-67）——播放测试里没碰，属像素/帧级标定。
- **Q-7**（并号后 = **F-060 + U-77**）`texts[].alignment` 的**水平**语义（F-031 判为 0 左 / 1 中 / 2 右 / 3 顶 / 4 底）。
  本 draft 的反例：金色花字 `alignment=2`，若按「右边缘钉在 clip 变换处」渲染，整句中心落在
  cx 0.175；而封面实测包围盒 0.169–0.948（质心 0.537），只有「盒子中心钉在变换处」能对上
  （渲染 0.165–0.943，四边残差 4–12 px）。两种解释的差别需要一个**多行**或**已知盒宽**的样本才能分开。
  浏览器链已按证据改成中心对齐，`al=3/4`（顶/底）分支保留但本 draft 无样本。
- **Q-8** 混音削顶怎么处置（P-20，**P-23 定案现象、未定处置**）：n=5 独立跑 `peak_fs`
  1.032–1.324、**5/5 都有满刻度窗口** ⇒ 削顶是常态不是抖动。降增益或加限幅都能压住，
  但在拿到剪映成片之前，压下去等于让预览偏离成片——**剪映自己的母带是否也削顶**未知。
  需要：成片参照（或用户明确「就要不削顶的版本」）才能定。
- **Q-9** 首帧判据的离散度（P-20，**P-23 收紧**）：视频腿竞态修好后 n=5 得 168–245.9 ms、
  0/5 越线（修前 82–351 ms、1/9 越线）。判据仍应写成「中位 + 越线次数」而不是单点；
  那一次 351 ms 的成因**未做归因实验**。


## P-24 成片到位：身份锁定、F-062 的扫描盲区量化、对齐律与 `visible:false` 缺陷（2026-10-22）

- **触发**：用户给出 `<EXPORT_DIR>\<EXPORT_NAME>.mp4`。L3 整帧基线此前唯一的阻塞就是
  「没有成片」（F-062）。
- **身份**：导出目录的 `-封面.jpg` 与草稿 `draft_cover.jpg` **sha256 同字节**（`f9dcc459b28ebe63…`，
  215,713 B）；容器 1080×1920 / h264 Main + aac LC 48k / 30 fps / **1108 帧** / `mvhd` 36.949 s；
  `creation_time` 本地 17:01:18 落在草稿写入窗 16:59–17:03 内。时长单独**不足以**定身份
  （重扫后 <1.2 s 的有 65 个，最近的 Δ0.052 比本文件 Δ0.116 还小）——封面哈希才是判据。
- **F-062 的结论作废**：那条 `mvhd` 指纹扫描只读**前 2 MB**，而剪映导出不是 fast-start
  （本文件 `moov` 在尾部最后 30 KB）。按 head+tail 重扫 `<DRIVE_E>/输出` 2,396 个文件：
  **2,355 个（98.3%）`moov` 只在尾部**。上一轮的「`<DRIVE_E>/输出` 只有一个 37.30 s 文件」是假阴性。
  被 F-062 当作排除依据的 `机床蒋堂` 三支同样**前 2 MB 无 `mvhd`**（那 45.88 s 是另外用 ffmpeg
  逐支探的），所以扫描器的失效当时没暴露。
- **对齐律**（F-070）：`export_frame = round(t×30) + 3`，且**前 3 帧是封面静帧**（与
  `draft_cover.jpg` corr 0.998、彼此逐像素相同），不是时间线第 0 帧的重复。
  37 个位置的最优偏移 0/+1 对半开 ⇒ 1/30 s 已低于判据分辨率，比对器必须带 ±2 帧搜索窗。
- **抓到的缺陷**（F-071）：t=0 整帧只有 0.778。逐层删/加变体一次定位到 track5；
  草稿里 **104 段中恰好 2 段** `visible: false`（track5 `ri=7`、track6 `ri=6`，都活 0–0.567 s），
  `playback_model.py` 从未读这个键 ⇒ 两条隐藏叠加层被画了出来。修后 t=0 **0.994**。
  三处改动：模型加 `visible` 通道与 `stats.invisible_segments`（打印 `hidden 2`）、
  `render_frame.active_segment` 与 `player.html` 的 `active()` 各加一条 `!== false` 跳过。
- **音频侧顺带定案**（F-073）：成片母带峰值 **−0.026 dBFS、`|x|≥0.9995` 样本 0 个**，
  0.5 s 窗 RMS 最大 **0.2891**；我们 `peak_fs` 0.887–1.35、4/8 跑越界、窗 RMS 最大 0.41–0.59。
  ⇒ Q-8 搁置处置所依据的前提（「剪映母带大概率同样削顶」）**是错的**。
- **证据等级**：全部**已验证**；③ 的色调归因与 ⑤ 的增益拟合除外（→ U-88）。

## P-25 L3 整帧基线落地成一条命令，并用 5 变体 × 8 时刻负例矩阵定了判据的区分力边界

- **做法**：`scripts/export_compare.py`——渲染 → 对齐（lead+窗口搜索）→ 多尺度亮度相关 →
  中位数/最差/偏移直方图 → 判据。一条命令复现：

  ```
  python scripts/export_compare.py --model temp/playback-test/model-check.json \
    --frames-dir temp/playback-test/oracle/dense216 --from 0 --to 36 --step 1 \
    --work-dir temp/playback-test/l3 --report temp/playback-test/l3/baseline-1fps.json
  ```

  oracle 是 `ffmpeg -vf scale=216:-2` 一次解出的全 1108 帧（163 MB，`temp/playback-test/oracle/dense216/`），
  换 `--export` 时删掉该目录重抽即可。
- **读数**（n=37，修 `visible` 后）：中位 **0.986/0.983/0.979/0.973**（16/32/64/128 px），
  最差单帧 0.90 @64（t=4），`median ≥0.95` 与 `min ≥0.80` **双过**。
- **负例矩阵**（corr@64，8 个时刻）：删主轨 −0.90~−0.94、删 `flag=2` 叠加 −0.61~−1.13、
  强画隐藏层只在 t=0 掉 0.216、**删全部文字轨只掉 0.005–0.024**。
  两两自洽：删叠加崩的 4 个时刻（3/13/18/26）正是删主轨不动的 4 个时刻。
- **判据边界（这条最该记住）**：**整帧相关抓不到缺字幕**。字幕只占画面百分之几像素，
  整条文字轨删掉中位才掉 0.02。所以文字层必须继续用 F-064 的分层色带/连通域判据，
  整帧判据的阈值也不要抬到 0.99 去「顺便抓文字」。
- **残余低分不是缺陷**：t=18 的 0.909 肉眼是**色调/亮度**差（我们顶灯更爆、地面更亮）——
  调色本就在相位范围内明确跳过；t=2/3/4 是行人位移 + 亚帧对齐。
- **证据等级**：基线**已测**（n=37）；判据区分力**已验证**（负例矩阵）；色调归因是**肉眼判读**。


## P-26 L2 的 oracle 换成成片同帧：门 13/13，且看清了「判据的 oracle 选错会主动掩盖缺陷」（2026-10-22）

- **现象**：修完 `visible:false`（F-071）后门里 L2 反而 **FAIL**（对封面 max delta 0.536、
  只检测到 201 px）。不是修坏，是**基准不成立**——F-070 证明封面是独立静帧。
- **做法**：`playback_check.py` 加 `--oracle-mp4 / --oracle-fps / --oracle-lead`，按
  `round(t×fps)+lead` 用 `select=eq(n\,IDX)` 从成片抽**同刻那一帧**（全分辨率，缓存为
  `oracle-frame-<idx>.png`），`layer_metrics` 判据一字未改。
- **对照读数**（同一判据、同一函数）：对成片第 33 帧 **0.010 PASS**（139,936 / 145,175 px，
  质心差 0.001）；对 `draft_cover.jpg` 同色 **0.166 FAIL**（封面白层只到 y=0.566）。
- **Finding**：P-23 记的「L2 对封面 0.008」是**巧合通过**——t=0.5 在两条隐藏层的存活窗内，
  而封面正是「画了隐藏层」的那个状态，两边一起错所以对上。**oracle 选错时判据会掩盖缺陷**，
  这条比数值本身更值得记住。
- **门全绿读数**（`--repeat 2`，oracle=成片，`--pixel-t 1.0 --pixel-colour 255,255,255`）：
  **13/13 PASS** — L1 0 错 0 警 / 几何 99/136 / hidden 2、L2 0.010 over 139,936 px、
  L3 视频带 corr@32px 0.725、fps 29.3、seek 25.5 ms、首帧 139.2 ms（126.8–139.2）、
  Range 3702 次/10 s、`black_streaks`+`errors` 0/2、`audio_errors` 0/2、
  `rates_seen [44100,48000]`、RSS peak 1235 MB。
- **顺带一条 U-86 的新线索**：这三轮 `--repeat 2` 的 `peak_fs` 分别是
  [0.9143, 1.0414]（1/2 越界）、[1.3912, 1.6761]（2/2 越界）、[0.9186, 0.9189]（0/2 越界）——
  同一 build、同一参数，双峰依旧，且**越界跑数在 0/2~2/2 之间摆**，与 F-068 的 4/8 一致。
  现在有了成片母带（−0.026 dBFS、零削顶）作参照，该问题从「削顶是不是常态」变成
  「我们的混音比成片响多少、按什么律压」→ U-88。
- **Path**：`temp/playback-test/gate-export-oracle.txt`（末次全绿）、
  `temp/playback-test/gate-after-visible.txt`（换 oracle 前那次 FAIL）。
- **证据等级**：**已验证**（两 oracle 对照 + 门复跑）。


## P-27 「要不要压混音」是个假问题：差的是 `segments[].volume` 没进模型（F-076）

- **触发**：用户问「这个的区别是什么」。为回答它去查 `materials.loudnesses`，顺出三层事实：
  素材级 `volume` 全缺、**段级 `volume` 有 4 条非默认（音乐床 0.3981 = −8.0 dB）**、
  而 L1 模型压根没有 `volume` 字段。
- **结论**：不是电平选择、不是限幅、不是主增益标定——**是我们把草稿写的 −8 dB 丢了**。
  修前我们比成片热 3–6 dB 且有 +2.6~+4.5 dB 的热尾；修后热尾消失（`peak_fs` 0.889–1.111），
  门 **13/13**。
- **一次自我更正**：上一轮我说「`loudness_applied` 完美解释双峰」。**错**——那是共同因，
  修后四次配对（5/4/10/3 → 1.028/0.891/0.889/1.111）把可分性打碎了，且方向本就讲不通
  （7 条响度目标里 6 条是衰减）。U-86 重新回到开放。
- **踩坑**：重建 `model-proxy-a.json` 时先用原始路径覆盖了它 ⇒ 网关 404 ⇒ 黑帧守卫报警。
  这是**守卫第三次被证明有效**（它没有误报，是我们真的把媒体弄丢了）。已按段 id 复原
  50 条代理映射 + 25 条 media 条目，并加了一条自检：「段路径不在 `media[]` 里」必须为 0。
- **口径提醒**：`rms_windows` 整条算百分位不可用（电池只跑约 10 s，大半是静音窗，p10/p50 全 −180）。
  与成片比只能用**最响窗**（成片连续 73 窗，max −10.78 dBFS）。

## P-28 段边界不拥有那个崩口：t=6.600 实测 0.969，低点是 6.633 且带 +2 帧对齐偏移（2026-10-23）

- **触发**：U-89 挂着「t=6.600 整帧只有 0.802，两侧都 0.96+」，怀疑 `active_segment` 的半开区间
  在切点选错段。主轨第一段 target 0–6.600、第二段从 6.600 起，正好压在切点上。
- **测法**（离线、不起浏览器）：`export_compare.py --model model-check.json --frames-dir
  oracle/dense216 --from 6.50 --to 6.72 --step 0.0333`，即 1/30 s 步长扫过切点两侧各 ~1 s。
  口径：oracle 是成片逐帧解出的 1108 帧 @216 px，我们的帧由通道 2 合成；下表是**同一时刻**四个尺度上的 corr。

  | t | 对齐 off | @16 | @32 | @64 | @128 |
  |---|---|---|---|---|---|
  | 6.500 | +1 | 0.997 | 0.997 | 0.993 | 0.988 |
  | 6.533 | +1 | 0.998 | 0.997 | 0.993 | 0.988 |
  | 6.567 | +0 | 0.996 | 0.993 | 0.985 | 0.971 |
  | **6.600** | **−1** | 0.992 | 0.985 | **0.969** | 0.938 |
  | **6.633** | **+2** | 0.911 | 0.895 | **0.880** | 0.868 |
  | 6.666 | +2 | 0.941 | 0.933 | 0.924 | 0.914 |
  | 6.700 | +2 | 0.963 | 0.954 | 0.949 | 0.943 |

- **Finding（当时判为帧对齐，已被 P-29 改判）**：**U-89 的归属假设不成立**——切点本帧 6.600 是
  0.969@64（不是 0.802），低点在 6.633。但当时把 `off=+2` 读成「第二段头几帧对齐错」也是错的：
  `off` 是在 ±2 帧窗口里**搜**出来的，对一段**正在衰减的闪光**去搜偏移，得到的数字没有含义。
  固定帧号 + 逐轨平移（`scripts/cut_alignment.py`）判掉了这个解释：见 P-29。
  与 U-67（XAVC `elst` 那 1 帧偏移）同族，但这里的方向是 +2、且发生在段内而非素材首帧，
  所以不能直接记为 elst 结案。
- **口径提醒（就地更正的依据）**：本节全部读数来自 F-076 音量修复**之后**的 build 与
  `model-check.json` + `oracle/dense216`；F-074 那条「6.600 → 0.802」与它不同口径，
  引用前先确认是哪一轮。崩口宽度只有 1 个 1/30 s 采样，所以「两侧 0.96+」这种说法
  在 1 s 网格上不成立、在 1/30 s 网格上也只成立一半。
- **Path**：`temp/playback-test/l3/boundary-6600.json`（7 个时刻 × 4 尺度的原始读数）。
  复现：上面「测法」那条命令，约 25 s，不需要浏览器。
- **证据等级**：已验证（同机、同 oracle 帧集、单变量=时刻）。

## P-29 崩口的真因：入场动画「向上闪入」0.3 s，而 L1 把 65/104 段的动画全丢了（2026-10-23）

- **instrument**：`scripts/cut_alignment.py`。与 export_compare 的区别是关键：它**固定** oracle 帧号
  `round(t*30)+lead`，不再搜偏移（搜偏移会把平移实验的自由度吃掉），并且逐轨平移 `source.start_us`
  ±3 帧。口径：scale=64 px 的 luma Pearson，单条轨改、其余轨冻结。
- **读数一（平移全无效）**：t=6.600 基线 corr **0.099**；把主轨、叠加轨、文字轨、或**所有轨一起**
  平移 −3..+3 帧，corr 只在 0.094~0.100 之间动。⇒ 不是「我们对哪条轨的素材起点算错了 k 帧」，
  P-28 的 +2 帧解释到此为止。
- **读数二（成片自己在那一瞬剧变）**：oracle 帧 195..211 的均值亮度：112.5 / 112.7 / 112.3 →
  **帧 201 = 241.0** → 182.3 → 163.6 → 150.1 → 138.1 → 127.8 → 118.4 → 111.3 → 105.9 → 103.6。
  我们的同一批帧一直是 112.1 / 99.6 / 98.8。成片从 6.600 起**过冲到近白再 10 帧衰减回基线**，
  而 6.600 = 帧 201 = 三条段（主合成、flag=2 叠加、文字）共同的起点。
- **根因（草稿侧直连）**：那条 flag=2 叠加（seg `14D93F1F`，t0 6.600 s）的
  `extra_material_refs → material_animations(DBC932D4) → animations[]{type:"in",
  name:"向上闪入", duration:300000, category_name:"入场", panel:"video", material_type:"video"}`。
  **0.3 s = 9 帧**，与亮度衰减回基线的帧数逐位对上；同段还挂着 `light_sensation` value 0.2299 与
  `brightness`（属调色，按用户要求本就不渲染）。全时间线只有 1 个 `materials.transitions[]`
  （「炫光」，被 t=23.700 的第 19 段引用），**与 6.6 无关**——一开始我怀疑它，读数否掉了。
- **缺口的真实规模（2026-10-23 二次读数后就地更正口径）**：**65/104 段带
  `material_animations` 引用**，其中**真带动画条目的是 33 段**（其余 32 段那个 bucket 里是空容器），
  L1 对这 33 段一条都没解出来（`features.animation == []`）。分层计数别混：
  引用段 65 / 有条目段 33 / 条目总数 33（每段最多一条）。
  更正后仍然是本时间线最大的单类缺口：33 段全被画成静态态。
- **33 个动画包本机全存在**（`package_exists` 33/33）——与 U-21 预设包 36.6% 的覆盖率**不是同一口径**，
  动画走 `User Data/Cache/effect/<resource_id>/<md5>`，这条时间线上不缺包。
  这与 P-13（`clip` 没进模型）、F-071（`visible` 没进模型）、F-076（`volume` 没进模型）同型，
  只是这次是 63% 的段。
- **判据影响**：L3 基线里那些「residual 低分不是缺陷」的说法要分层了——t=18 那类是调色（故意不出），
  而 **6.6 这类是入场动画没实现**，是真缺口。`--from 6.5 --to 6.72 --step 0.0333` 那段现在应当作
  动画未实现的见证，而不是对齐噪声。
- **Path**：`temp/playback-test/l3/cut-6600.json`（平移矩阵与 native 下限）、
  `temp/playback-test/l3/cut-6600.txt`（人读表）。复现：
  `python scripts/cut_alignment.py --model temp/playback-test/model-check.json --frames-dir
  temp/playback-test/oracle/dense216 --times 6.600,6.633,6.700`（约 40 s，不起浏览器）。
- **证据等级**：已验证（固定帧号 + 逐轨单变量平移 + 草稿侧字段直连 + 时长逐位对上）。

## P-30 动画缺口的规模：窗内 40% 的时刻掉下 0.95，窗外只有 12%（2026-10-23，`scripts/animation_gap.py`）

- **测法**：33 段带动画条目（F-078），每条动画定义一个窗口（`kind=in` 取段头 `duration_us`，
  `kind=out` 取段尾），窗内步长 0.1 s、窗外从动画结束起按 0.25 s 步长最多取 2 s。
  每个时刻用**固定** oracle 帧号 `round(t*30)+3` 对同刻成片帧算 64 px luma 相关——
  不搜偏移，这是 P-29 的直接教训。阈值 0.95。
- **分布（口径：时刻数，不是段数）**：窗内 114 个时刻，中位 0.960，
  **低于 0.95 的 46/114 = 40%**；
  窗外 82 个时刻，中位 0.968，低于 0.95 的 10/82 = 12%。
  两个总体的**中位数只差 0.008**，尾部差 3 倍——整帧相关对「少了一个图层」本来就不敏感（F-072 的
  区分力边界），所以这里的信号在尾部与逐段配对里，不在中位数。
- **可归因（配对判据：窗内 < 0.95 且同段窗外全部 ≥ 0.95）**：**10/31 段**。
  这是把责任交给动画的那一类；窗内窗外都低的（如 t=17.03/18.23 的向下滑动 rest_min 也只有 0.886）
  不算，那是别的成因（调色/行人运动/该时刻本来就在动）。

  | t0(s) | 动画 | kind | 窗内中位 | 窗内最低 | 窗外中位 |
  |---|---|---|---|---|---|
|  20.23 | 打字光标 | in | 0.449 | 0.374 | 0.973 |
|  20.23 | 侧滑 | in | 0.524 | 0.374 | 0.973 |
|   6.60 | 打字光标 | in | 0.768 | 0.605 | 0.988 |
|  25.30 | 打字光标 | in | 0.786 | 0.592 | 0.959 |
|   5.40 | 放大震动 | in | 0.924 | 0.919 | 0.986 |
|   6.60 | 向上闪入 | in | 0.930 | 0.605 | 0.987 |
|  28.13 | 缩小 | in | 0.943 | 0.934 | 0.978 |
|  14.83 | 打字光标 | in | 0.949 | 0.949 | 0.956 |
|  29.03 | 向右模糊 II | in | 0.961 | 0.949 | 0.973 |
|  26.70 | 生长 II | in | 0.962 | 0.949 | 0.966 |
- **逐动画名（窗内读数汇总）**：

  | 动画名 | 中位 | 最低 | 时刻数 |
  |---|---|---|---|
| 侧滑 | 0.524 | 0.374 | 3 |
| 放大震动 | 0.924 | 0.919 | 5 |
| 向上闪入 | 0.930 | 0.605 | 3 |
| 模糊消失 | 0.931 | 0.912 | 4 |
| 生长 II | 0.934 | 0.922 | 15 |
| 缩小 | 0.943 | 0.934 | 5 |
| 渐显 | 0.946 | 0.940 | 5 |
| 向右模糊 II | 0.961 | 0.949 | 5 |
| 向上露出 | 0.962 | 0.954 | 5 |
| 打字光标 | 0.962 | 0.374 | 28 |
| 向下滑动 | 0.965 | 0.870 | 26 |
| 弹入 | 0.978 | 0.937 | 10 |
- **判读**：
  1. **位移/缩放类最伤**：「侧滑」（t0=20.23，窗内 0.524/最低 0.374）与「放大震动」
     （0.924）是内容**真的不在同一位置**的动画，整帧相关立刻塌——这类只要实现
     「按曲线改 transform」就能拿回大部分分数，不需要执行包内 shader。
  2. **文字类靠的不是像素而是有无**：「打字光标」14 段（时刻数最多，28），窗内中位 0.962 但
     最低 0.374——它和「侧滑」同一段（t0=20.23），所以那个 0.374 应归给侧滑，
     **逐名汇总在共享时刻上会互相污染**，引用时要带这句。
  3. **亮度爆闪类**：「向上闪入」0.930/最低 0.605，就是 P-29 帧 201 那个均值 241 的白闪，
     要复现得执行包内 `Exposure`（明文 `.frag`，F-078 第 4 条）。
- **顺序建议**（按「拿回分数 / 实现成本」）：先做位移缩放类（侧滑、放大震动、缩小、生长 II、
  向下滑动、向上露出、弹入、渐显 = 8 名 21 段次，只需曲线 + `clip` 变换）；
  再做打字光标（文字逐字揭示，14 段，纯前端可见性动画）；
  最后才是曝光/模糊类（要跑包内 shader）。
- **Path**：`temp/playback-test/animation-gap.json`（逐段逐名）、`animation-gap-summary.txt`。
  复现：`python scripts/animation_gap.py --model temp/playback-test/model-check.json
  --frames-dir temp/playback-test/oracle/dense216 --report temp/playback-test/animation-gap.json`
  （约 9 分钟，不起浏览器，机器空载时跑——同机同时跑门会污染 L4 的 timing 读数）。
- **证据等级**：已验证（同刻对同刻、固定帧号、配对判据排除了共成因）。

## P-31 门的 L6 又出现一次 `Input has been disposed`，取分布后判为既有离散，不是回归（2026-10-23）

- **触发**：给 L1 加 `animations` 字段后重跑门（`--repeat 2`）→ 12/13，
  `L6 ... 1/2 runs with black_streaks or errors; e.g. [] ['! Input has been disposed.']`。
  黑帧计数是 **0**，报的是**错误**，所以不是画面丢了，是流被提前释放。
- **判据**：本轮改动只往模型里**加**字段，播放器电池吃的是 `model-proxy-a.json`（旧 L1 建的，未重建），
  所以播放路径逐字节未变。用重跑取分布来定性，而不是靠推理：`--repeat 3` → **13/13**，
  `0/3 runs with black_streaks or errors`，同时 L4 seek 37.8 ms / 合成 29.13 fps / 首帧 170.4 ms
  （与今天上午 36.5 ms / 29.49 fps / 138.3 ms 同分布）。
- **结论**：`Input has been disposed` 与 P-22 抓到并修掉的 `streamFor` 归属竞态**同族、仍偶发**，
  今日累计 1/5 跑；不是这次改动引入。归到 U-86 那条「同参不同结果由什么决定」的离散账上，
  并新增一条待判：错误发生在**退出时**还是**播放中**（若是退出时则无害，若是播放中就是丢帧前兆）。
  读数 `temp/playback-test/gate-after-anim.txt`（12/13）与 `gate-after-anim-r3.txt`（13/13）。
- **证据等级**：已验证（同机同参两次跑，一 FAIL 一全过）。
- **一处会咬人的陷阱（记下来，别下次踩）**：门的 L4 电池吃的是 `model-proxy-a.json`，那份是**旧 L1** 建的，
  里面**没有** `mix_mode` / `animations` 字段。所以「模型加了新通道」不等于「播放器看得见」——
  一旦渲染器开始消费这些字段，必须先用 `--media-model` 指向的路径重建代理模型（代理只改素材路径，
  不该丢字段），否则浏览器通道会静默地按旧形状跑，而门的其他层全绿。


## P-32 门从 13 层加到 16 层：混合模式有了自己的接线层与 GPU 三方对照层（2026-10-23）

- **为什么加层**：F-079 的实现落在通道 2 与 L1，而本草稿 0 个 `mix_mode` 引用，
  原 13 层里没有任何一层会经过这条代码路径。这类「实现了但门看不见」正是 P-12/P-21 反复踩的形状，
  所以把它变成门的固定一层，而不是靠下次有人记得单独跑脚本。
- **新层**（`scripts/playback_check.py`）：
  - `L7 mixmode shipped GLSL` —— `mixmode_shaders.py` 重新切片出厂件，成功即 PASS（切片失败会抛，不静默）；
  - `L7 mixmode wiring (constructed fixture)` —— `mixmode_wiring_check.py` 6 项：
    存在可注入叠加段 / multiply 变暗 / screen 变亮 / 三模式互不相同 / 未知 md5 计入降级 / 降级形态等同普通合成；
  - `L7 mixmode GPU three-way (vendor GLSL = oracle)` —— 需 `--mixmode-gpu`，**读表判定**
    （`shipped_vs_vendor_max_abs_255 <= 1`、`numpy_vs_vendor_max_abs_255 <= 1`、
    `numpy_cells_over_tolerance == 0`，10 行齐），不解析 stdout。
- **本轮全绿读数**（`--repeat 1 --mixmode-gpu`，`temp/playback-test/gate-with-L7.txt`）：**16/16**。
  L4 合成 29.66 fps / seek 30 ms / 首帧 113.6 ms；L6 0/1；混音 `peak_fs [0.8925]`、
  **0/1 跑有满刻度窗**（U-86 那条离散今天第三次抽样：0/2、0/3、0/1 都干净，
  而 12/13 那次是 1/2 —— 仍是偶发，未定成因）；短程 RSS 峰 904 MB（600 s 判据另跑）。
- **How to apply**：以后任何「播放器加了一条新渲染路径但当前草稿不触发它」的改动，
  都要配一条构造样本的门层，否则门绿不代表那条路径活着。
- **证据等级**：已验证（门一次跑通，读数留档）。

## P-33 动画接进两条通道：整帧判据看不见它，图层级判据给出 22 更近 / 0 更远（2026-10-23）

- **做了什么**：L1 带 `segments[].animations[]`（含 `start_us`）；曲线值**从预设包内明文 lua 读**
  （`scripts/animation_curve.py`），导成 `temp/playback-test/animation-curves.json` 给浏览器用，
  JS 侧不重抄数字；通道 2（`render_frame.anim_value/apply_anim`）与浏览器通道
  （`player.html` 的 `applyAnim`，5 个钩子点：图片层、两个 composite 容器、字幕组、以及
  `placeImage` 之后）都接上。可求值覆盖：**3 个预设 / 8 段**（向下滑动 6、缩小 1、渐显 1，
  **全部是字幕段**）；其余 **9 个预设显式记为未覆盖**（侧滑、向上闪入、打字光标、生长 II、弹入、
  放大震动、向上露出、模糊消失、向右模糊 II）——它们走 AE 导出脚本或 `onUpdate` 显式数学，
  不假装覆盖。
- **判据一（整帧，A/B 同刻同模型只切开关）**：`--no-animations` vs 开启动画，
  8 段 × 窗内 108 个时刻：**inside 中位 0.9627 → 0.9627，逐段 Δ 全为 0.000**
  （`temp/playback-test/anim-ab-{off,on}.json`）。⇒ **不是代码没生效，是这把尺对字幕瞎**：
  F-072 早就量过删掉全部字幕轨整帧只掉 0.005~0.024。整帧判据不能用来判字幕动画。
- **判据二（接线，`animation_wiring_check.py`，5/5 PASS）**：动画期内 ON/OFF 同刻
  `Δmax` 最高 **255**、改变像素通道数 **111,231~185,144**；**动画期外 `Δmax=0`（逐字节相同）**
  —— 这一条专抓「曲线常驻」。读数 `temp/playback-test/animwiring/wiring.json`。
- **判据三（区域，`animation_region_check.py`）**：先把该段自己孤立渲染（画到黑底）取其横向占位，
  再在该列范围内与**成片同帧**比 RGB 平均绝对差（统一到 `--oracle-width` 尺度，用 BOX 降采样，
  与 `export_compare.luma` 同口径）。**32 个同刻比对：开动画更近 22 / 更远 0 / 不变 10**；
  MAD 中位 19.79 → 19.68。⇒ **方向与量级对了**（32 次里没有一次变远），
  但绝对改善小：那条列范围里大部分是背景，字幕墨迹只占一小部分。
- **判据四（作废并记原因）**：先试过全画面单色质心（借门里 L2 的 `layer_metrics`）——
  结果 更近 5 / 更远 3 / 不变 20，且逐行 ON/OFF 读数相同。原因：**淡出时字幕暗下去就掉出色彩掩膜**，
  质心被同色的另一条字幕接管。所以这条判据不可用，脚本留着但**不要拿它的数字下结论**
  （`temp/playback-test/anim-layer.json`）。
- **工具侧四条修正（都是本轮真实踩过的）**：
  ① 解码缓存无上界，一次 A/B 吃到 **4.2 GB RSS** 被中途停掉 ⇒ 现钳 64 帧（`--cache-cap`），
     一帧 1080×1920 约 8 MB；
  ② `global CACHE_CAP` 写在同名使用之后 = SyntaxError，两条腿当场崩而输出文件是空的 ⇒
     **测量脚本必须说清「为什么没有数据」**，不能一句 `no comparable samples` 退出；
  ③ 判据要求 inside 与 rest 两侧都有样本，`--rest-cap 0.5` 时稳态窗为空集 ⇒ 放宽为
     窗内即可判（动画头窗本身就是判据）；
  ④ 成片帧是 216 px 降采样，全分辨率直接相减广播失败 ⇒ 统一到成片尺度再比。
- **一处会咬人的陷阱**：门的 L4 电池吃 `model-proxy-a.json`，那份是旧 L1 建的、**没有**
  `animations`/`mix_mode` 字段。模型加了新通道 ≠ 播放器看得见；一旦浏览器开始消费这些字段，
  必须重建代理模型（代理只改素材路径，不该丢字段），否则浏览器静默按旧形状跑而门全绿。
- **Path**：`scripts/animation_curve.py`、`scripts/animation_wiring_check.py`、
  `scripts/animation_region_check.py`、`scripts/animation_layer_check.py`（作废判据，留档）、
  `temp/playback-test/{anim-ab-off,anim-ab-on,anim-region,anim-layer}.json`、
  `temp/playback-test/animwiring/`、`temp/playback-test/animation-curves.json`。
- **证据等级**：已验证（三条独立判据互相印证：接线像素差、区域 MAD 的方向一致性、
  整帧的「无变化」被 F-072 的敏感性边界解释）。

## P-34 代理模型补载体 + 跨通道曲线对数（门加到 17 层全绿），并记下两次「我自己制造的 FAIL」的成因（2026-10-23）

- **补载体**：`scripts/merge_model_carrier.py --target model-proxy-a.json --source model-check.json`
  把新 L1 的 `animations`/`mix_mode` 按段 id 搬进代理模型（**只搬白名单字段，不碰 `media.path`**
  —— 代理的意义就是换路径）。结果：改动 33 段、合并后带动画段 33（与源一致，脚本自带计数断言，
  数不对就非零退出），原子写 + `model-proxy-a.json.bak` 备份。这样浏览器才真的看得见动画字段。
- **门新增 L9（跨通道曲线对数）**：`player.html` 的 `applyAnim` 记下 `{id, name, alpha, s, dy, t_us}`，
  随 `/report` 交回；门用**同一个模型**在通道 2 重算同一时刻，逐段比 `alpha`/`scale`（阈值 0.02）。
  读数：**curves loaded=True，浏览器报了 7 段，不一致 0**（17/17 全绿，
  `temp/playback-test/gate-with-L9b.txt`：合成 29.34 fps / seek 33.7 ms / 首帧 170.7 ms /
  0 错 0 黑帧 / peak_fs [0.8902] 无满刻度窗 / 短程 RSS 峰 1000 MB）。
  **`dy` 故意不判**：JS 用节点高、Python 用墨迹高（P-16 的 PIL 升部陷阱同类），
  两个定义本就不同，拿它当判据只会假报警 —— 已写成注释而不是默默比。
- **我自己制造的两次 FAIL，都记成因（不是外部缺陷）**：
  1. `L9 curves loaded=False` 但同一份报告里 `last` 有 7 条。根因是我把 `anim` 写在报告对象**字面量**里：
     数组按引用（后续 push 看得见），布尔按值（永远停在创建时的 `false`）。
     ⇒ 自报字段必须在**发报告时**再取一次（`r.anim = {...}`），不能进创建时的快照。
  2. `L3 video band FAIL corr@32px 0.553`。这一次我**没有用交接文档里的完整命令**（漏了
     `--video-scan 0.05:0.55:0.05`），于是它只比 t=1.0 一个位置而不是扫描取最优。
     我先证明这不是回归：同一时刻动画开/关两帧**逐字节相同**（平均绝对差 0.00），
     同一带对成片 corr 0.956/0.965（t=1.0/1.033）；再用文档命令重跑 → 回到 0.725 PASS。
     ⇒ **门的默认参数 ≠ 交接命令**，L3 的带判据对参数敏感；重跑前先核对参数，再谈「是不是回归」。
- **还剩什么**（不写成已完成）：
  ① 9 个预设仍未覆盖（侧滑、向上闪入、打字光标、生长 II、弹入、放大震动、向上露出、模糊消失、
     向右模糊 II）——走 AE 导出脚本或 `onUpdate` 显式数学（U-91）；
  ② 两通道的**像素级**一致仍未判（L9 只到曲线值层面；解码器与字体度量差异另说）；
  ③ 混合模式的浏览器侧（U-92）；④ `≤2 GB` 口径由用户定（U-79）。
- **证据等级**：已验证（门 17 层一条命令复现；两次 FAIL 都做了「先证非回归再改参数」的对照）。

## P-35 三条判据各自的混淆项被逐个拆掉：混音按整条时间线测、L10 上线、内存中位数还没归因（2026-10-23）

- **U-86 设计实验（`scripts/mix_stability.py`）**：整条时间线（`playms=38333`、`seeks=0`）
  先 n=3 再 n=5：`peak_fs` = 0.9143/0.9922/1.0179（极差 0.1036）与 0.9284/0.9364/0.9667/0.9738/0.9863
  （极差 **0.0579**）。两批合起来 8 跑里只有 2 跑出满刻度窗。
  ⇒ 预登记的分支走到「**仍然飘 ⇒ 混音侧**」；且**「有 errors 的跑更容易爆」这条观察性关联没复现**
  （10 s 电池 n=56：errors>0 的 12/14 跑出过满刻度窗 vs errors=0 的 19/42；
  整条时间线里带 12 条 errors 的跑反而 0 个满刻度窗）——**这是本轮第二次「相关被实验否证」**，
  与 F-081/F-082 一起构成「U-86 与 P-31 大概率不同因」的证据。
  判据口径当场改掉：**混音峰值必须按整条时间线测**，10 s 电池连「有没有满刻度窗」都不稳。
- **L10 上线（浏览器把自己画的帧回传）**，首轮就逼出四个仪器修正，每个都改变结论：
  1. 门在**打印总结时被 GBK 控制台崩掉**（detail 里有中文/替换符）→ 改成按字节写并替换；
     已经跑完的 17 层结果差点因为最后一步 print 而全部看不到。
  2. 截图与目标时刻可能不同帧 → 页面回传 `__lastPaintUs`，判据端核验（修好后 t=1.0 仍是 0.948，
     于是确认那 0.05 是**内容差异**而不是采样）。
  3. 跨通道比对最初**两侧媒体不同**（浏览器吃代理、通道 2 吃原片）→ 通道 2 改用同一个代理模型，
     0.910 → 0.948：其中约 0.04 是管线外的东西，本来会被算成渲染分歧。
  4. 对成片不能用固定帧号硬对：**切点两侧是不同镜头**，差一帧 0.98 就读成 0.13。
     改成 ±3 搜最佳并**把偏移一起报出**（偏移本身是证据）；跨通道那条仍固定同刻，因为它没有对齐自由度。
- **L10 首轮的真实产出**：浏览器比通道 2 偏亮约 1.8 个码值，分带定位在视频区（MAD 12–15）而字幕带一致（2.9），
  且整帧对成片通道 2 更近（MAD 8.20 vs 11.06）→ 新开 **U-93**（三个候选机制与判据都写在 F-083/U-93）。
  另外 6.633 那帧对成片只有 0.898 且需要 +3 帧对齐，正是 `向上闪入` 白闪未实现的体现（P-29/P-30 的同类见证，
  这次是从浏览器侧看到的）。
- **600 s 内存判据**：新 build 读数 median **1166** / peak **1767** / 0/596 秒越 2048，
  角色峰值 gpu 1018 + renderer 496 + browser 158；旧读数 median **895** / peak 1674 /
  gpu 1281 + renderer 285 + browser 75。**两次之间不止差一个变量**（代码变了、模型也变了、
  峰值时刻 163 s vs 18 s），所以「我的改动让内存涨了」现在**不能写**。
  归因用 `scripts/rss_ab.py` 单变量跑（同代码只换模型 `.bak` vs 现行），读数待补。
- **U-91 的成本分层**（包内文件实测）：已实现的 3 个预设恰好就是「4 文件 + 1 lua + 无 shader」的纯
  `fromTo` 那批；其余 9 个带自定义 shader 或 AE 导出脚本，最大单项 `打字光标` 14 段是
  1 份 14 KB lua + 光标 frag + 贴图。
- **证据等级**：已验证（每条判据都给了读数与复现命令；未归因的内存项明确写「不能下结论」）。

## P-36 SP-04 的复用率有了真数字；同时冒出一条**可能是我自己引入的**内存越线（n=1/臂，正在三臂归因）（2026-10-23）

- **SP-04（keep-alive / 闭区间取块）不再是「单源待验证」**：直接数网关日志（`scripts/gateway_log_stats.py`，
  窗口 = 最近 30 分钟，覆盖真草稿的播放与 seek 负载）——**141,655 条请求，复用率 99.9%**，
  分素材看代理 mp4 与本机缓存 mp3 都是 99.9~100%。
  ⇒ F-054 把 keep-alive 从「优化项」升级成「前置条件」这一条，在**现行网关 + Chrome** 上是被满足的：
  浏览器确实在复用，且 seek/播放判据同时达标（L4 seek 30~39 ms）。
  **但**P-08 那个反直觉读数（NAS 大片上复用反而慢 7.90 ms/请求）**没有被推翻**，只是换不了口径：
  它测的是「每请求耗时的 A/B」，而网关此前**从不记 `ms=`**，所以真负载上无法复算。
  ⇒ 已给网关补上逐请求 `ms=`（`_ms()` 从进入取块分支起算），下一轮跑就能把
  「复用 vs 新建」两组延迟中位在**同一份日志**里对出来；`gateway_log_stats.py` 已支持读它。
- **一条自己踩到的工具坑（第二次）**：`gateway_log_stats.py` 打印末尾的中文注释时
  **被 GBK 控制台抛 `UnicodeEncodeError`**——和刚才门在打印总结时崩掉是同一个坑。
  这次不再一处一处修：19 个脚本统一 `sys.stdout.reconfigure(errors="replace")`
  （只改错误处理策略，不改编码），并把门的 `emit()` 保留。
  纪律：**读数算完之后的 print 不应该有能力吞掉读数**。
- **内存判据冒出一条必须直面的读数（`scripts/rss_ab.py`，两臂各 n=1，200 s）**：
  同一份播放器代码、同一网关、只差模型文件——
  旧模型（`.bak`，无 `animations`）median **1127 MB**、max **1540**、**0/199 秒越 2048**；
  新模型（含 `animations`，浏览器于是真的应用动画）median **1216 MB**、max **2809**、
  **10/199 秒越 2048**，角色峰值 `gpu-process 2151 / renderer 387`。
  ⇒ **可能是我这次改动引入的内存回归，且越过了 2 GB 判据线**。但每臂只跑一次，
  而 gpu-process 峰值本来就飘（历史读数见过 1018 / 1281 / 2151），所以**现在不写结论**。
  正在跑的三臂版把它分开：A 有动画（现状）/ B **同一模型但 `&anim=0` 不应用**/ C 旧模型——
  若 B 也越线，问题在「模型带字段 + 拉曲线表」而不是应用动画；若只有 A 越线，就是应用侧
  （每帧 `scale.set`/`alpha` 触发 Pixi 重建？）。读 `temp/playback-test/rss-ab3.txt`。
  顺手修了 `rss_ab.py` 两处解析缺陷：逐秒样本行没匹配上（于是 `样本=0`、`p95=None`），
  以及 `by_role` 之外的 `rss_peak_mb=1540` 被角色正则误抓成 `s=1540`。
- **判据口径提醒**：U-79（peak / median / p95 哪个算达标）**还没裁定**，而这条越线读数正好落在
  三个口径会给出不同答案的区间（median 1216 达标、peak 2809 不达标）。
  所以下面这类话要说全：**「按 median 达标、按 peak 越线，且越线只在新模型臂出现」**。
- **证据等级**：SP-04 复用率 已验证（141,655 条请求，可复跑）；内存那条 **未定案**
  （n=1/臂 + 工具解析缺陷刚修，三臂版在跑）。
- **单变量性已就地核验（2026-10-23 06:32，写归因之前先问「两臂真的只差一个东西吗」）**：
  逐段比较两臂模型的键与值——104 段同 id，差异**只有** `+animations`（33 段），
  没有任何其他键变化；顶层字段（`canvas/stats/media/...`）全等，`media[]` 路径列表逐位相同。
  ⇒ 上面那条「越线只出现在带动画的臂」是**单变量**结论，不是两个不同 build 的对比。
  （这也是为什么 B 臂用 `&anim=0`：同一模型、同一曲线表拉取，只关掉应用，
  把「模型带字段」与「浏览器真的应用」分成两个可分离的候选。）

## P-37 三臂归因否证了「我引入 2 GB 越线」；那条读数是未复现的离群点（2026-10-23 06:34）

- **单变量性先验过**（P-36 附注）：两臂模型逐段比键，差异只有 `+animations`(33 段)，顶层字段与
  `media[]` 完全一致 ⇒ 比的确实是一件事。
- **三臂读数（各 200 s、`playms=240000`、`seeks=0`、同一 build，`temp/playback-test/rss-ab.json`）**：

  | 臂 | 差别 | median MB | max MB | 越 2048 的秒数 | 角色峰值 |
  |---|---|---|---|---|---|
  | A 有动画 | 现状（模型带字段且应用） | 1007 | **1144** | **0/199** | renderer 544 / gpu 354 |
  | B 不应用 | 同一模型 + `&anim=0` | 1001 | 1262 | 0/199 | renderer 496 / gpu 308 / utility 272 |
  | C 旧模型 | `.bak`，无 `animations` | 1012 | 1191 | 0/199 | renderer 549 / gpu 391 |

- **Finding**：**没有越线，三臂彼此差在 ~5% 内；P-36 那条「max 2809、10/199 秒越线」没有复现**
  （那次是两臂各 n=1 的第一次跑）。按本项目自己的规矩处理离群点：不把它升格成结论，也不靠猜解释它——
  写「未复现」，并留下可复跑的命令（`scripts/rss_ab.py --arms "A=...,B=...?anim=0,C=....bak"`）。
- **但边界要说清，别顺手宣布内存没事**：这三臂每臂只跑 **200 s**，而判据是 **600 s**；
  200 s 下 gpu-process 只有 308~391 MB，而 600 s 跑里是 1018~2151 MB ⇒ **gpu 分配随会话长度增长**，
  所以「200 s 无差别」**不能**外推成「600 s 无风险」。600 s 判据目前的最好读数仍是
  median 1166 / peak 1767 / 0/596 秒越线（`rss-anim-soak.txt`，带动画的新 build）——
  它达标（按 median 与按 peak 都 < 2048），但 **U-79 的口径仍未定**（peak 余量 ~14%、median 余量 ~43%），
  而且旧 build 的 median 895 vs 新 build 的 1166 那次对比**不是单变量**（代码、模型、峰值时刻都变了），
  要判就得在 600 s 上重做一次单变量 A/B（下一件事，约 22 分钟）。
- **顺带修掉的两个仪器缺陷**（都是这轮真实踩到的）：`rss_ab.py` 的逐秒样本正则没匹配上（`样本=0/p95=None`）、
  `by_role` 之外的 `rss_peak_mb=…` 被角色正则误抓成 `s=1540`；以及 `player.html` 加了 `&anim=0`
  开关（同模型不同行为，B 臂就是靠它把「带字段」与「应用」分开的）。
- **证据等级**：已验证（三臂单变量 + 模型差异逐段核验）；「未复现」是**读数级别**的结论，
  不是「机制上不可能」——所以 600 s 单变量那一步留在待办里而不是结案。

## P-38 落地状态：门 18/20（一处是**我自己写的假红**，一处是**该红的 U-93**）（2026-10-23 06:39）

- **完整门 `--repeat 2 --mixmode-gpu`**（`temp/playback-test/gate-full-18.txt`）：**18 of 20，2 FAILED**。
  - `L10 browser pixels` **该红**：跨通道 0.910@t=1.0（阈值 0.95）、浏览器对成片在 20.23/6.633
    因未实现的 `侧滑`/`向上闪入` 而低 ⇒ 这是 F-083/U-93 的真实缺陷，不是判据毛病。
  - `L8 curves table rebuilt` 是**假红**：重导本身成功（`3 presets`、`覆盖 8/33 段`），
    但断言拿**中文子串**去匹配子进程 stdout，而 Windows GBK 下取回的是替换过的字节 ⇒ 一次成功被读成失败。
    已改成**按计数核**（`N presets` 对表内预设数、`X/Y 段` 的 Y 对 `stats.animation_segments`），
    独立验证为 True（presets 3、covered 8/33）。这与本轮早些时候「门在 print 时被 GBK 崩掉」
    是同一个失效面的第二种形态：**断言不能依赖被渲染过的文本**。
  - 修的过程中我把 `playback_check.py` 写坏过一次（heredoc 里的换行转义），已当场修回并 `ast.parse` 通过、
    `--help` 可跑。**教训**：往源码里注入含反斜杠的字符串，必须用编辑工具而不是 shell 内联脚本。
- **其余 18 层全绿**，含 L7 三层（GPU 三方对照 10 模式 0 越界）、L8 动画接线 5/5、
  L9 跨通道曲线一致 7 段 0 不一致；L4 seek 44.9 ms / 合成 29.63 fps / 首帧 134.5 ms / 0 黑帧 0 错。
  混音 `peak_fs [0.8913, 1.3247]`、1/2 跑有满刻度窗 —— 与 U-86「按整条时间线测」的口径改一致，
  10 s 电池的这个数**不再当判据用**。
- **排队未回的一条**：U-93 的两段式探针（`scripts/colour_range_probe.py`，读 `temp/playback-test/colour-probe.json`）
  跑完后先判 `d_browser_minus_ffmpeg` 是否 ≈ +1.8（解码侧）还是只有 `d_browser_minus_channel2` 显著（上屏侧）。
- **下一步顺序（不变）**：① 读探针结果并修 U-93；② 600 s 单变量内存 A/B（P-37 只覆盖到 200 s）；
  ③ U-91 的 T2 档（`打字光标` 14 段）；④ U-92 浏览器侧混合模式（Pixi 版需独立再验一次等价）；
  ⑤ 提交（等用户点头）。
- **证据等级**：门读数 已验证；「L8 假红已修」为已验证（独立核验 True），
  但**下一次全门跑之前**，18/20 里的这一项不应被引用为绿。

## P-39 U-93 探针首跑：两个腿回 null，原因可诊断（选错轨道——track0 的媒体是**加密合成缓存**）（2026-10-23 06:40）

- **读数**（`temp/playback-test/colour-probe.json`）：`channel2_luma=155.31`，
  而 `ffmpeg_luma.center/±1 = null`、`browser_luma = null`。
- **成因（不是「无差异」，别误读）**：探针默认取 `--track 0`，而主轨这段的 `media.path` 是
  `Resources/combination/1ECF4DB3-...-_video.mp4`——**F-059 已证那是不透明的高熵 blob**，
  ffmpeg 解不出帧 ⇒ 基线腿为空；通道 2 之所以有图，是因为它对 `readable=false` 的段**递归子时间线**，
  画的是明文素材而不是这个缓存文件。浏览器腿的截图没落盘（`shots=` 只传了 12.0 一个时刻，
  solo 模型下页面若把该段当加密缓存处理会走 badge 分支而不画它），所以也没有可比帧。
- **正确的下一步（一条命令的事，已验证为可跑的形状）**：把探针指向**有明文素材的视频轨**——
  本时间线的 flag=2 叠加轨（track1，素材是 `<NAS>/<NAS>/<素材语料>2026/.../C7573.MP4` 与其代理
  `C7573.420a.mp4`）：`python scripts/colour_range_probe.py --track 1 --t 7.0`。
  三腿（ffmpeg 基线 / 通道 2 / 浏览器）都取同一段的同一**源时刻**（脚本已按
  `source.start + (t - target.start)*speed` 换算，并带 ±1 帧防「差一帧冒充色彩偏移」）。
- **顺带确认的卫生**：本轮所有测量进程都已退出（`python.exe` 残留 0），
  Chrome 的 13 个进程是用户自己的浏览器，与我的独立 profile 无关；
  探针与门都在自己的 `finally` 里终止网关，不留驻。
- **证据等级**：这条记的是**仪器选错输入**的诊断，不是色彩结论；U-93 的定性仍未做（挂在下一次运行上）。


## P-40 U-93 反转：跨通道崩口的真因是通道 2 的字体静默回退，四层像素判据都没看见（2026-10-24 19:15）

- **触发**：上一轮的收尾读数（t=1.0 带 4 差 +10.27、`>200` 像素 浏览器 3545 vs 通道 2 89）与
  F-083「字幕带两边一致」直接矛盾。两边不可能都对，所以先造一台**不靠我猜带**的仪器：
  `scripts/caption_ink_check.py`（三腿同尺度 540×960，行窗由模型字幕几何定，横向由成片墨盒定）。
- **结论**：见 **F-084**。方向与 F-083 相反——t=1.0 上浏览器几乎逐像素复现了成片字幕（3544 vs 3476），
  偏离的是**通道 2**：草稿字体 `HelloFont_ID_JianSong_95.ttf` 的缓存目录已不在机器上，
  `load_font` 静默落到 `ImageFont.load_default()`（≈10 px 点阵，中文=豆腐块），
  于是这条时间线 42 条字幕样式**全部**按 1/4 字号画。
- **这一轮的门禁教训（比这个 bug 本身更值钱）**：L2 判的是白墨 mask 的**包围盒/质心** ≤0.02，
  小 4 倍的字幕照样居中 ⇒ 它一直绿。墨量从来没进过判据。**判据看不见那一层 ≠ 那一层没差**，
  与 `feedback-metric-sensitivity-before-no-effect` 同一族；已把「墨量」升为字幕判据的一等公民
  （`caption_ink_check` 报 `ink/ink220/bbox/corr/mad` 五项，且 `render_frame` 现在把回退字体数打到 stderr）。
- **顺带否证掉的两条**：① 「代理 vs 原片媒体不同」不是这条读数的解释（两份模型分别跑，
  通道 2 墨量 43 / 24，都是豆腐块）；② 「浏览器系统性偏亮 1.8 码值」连**符号**都不稳
  （t=1.0 通道 2 更贴近成片，t=7.0 反过来），U-93 已按此收窄成「素材层 ~1–2 码值、随时刻变号」的小残差。
- **新开的洞**：`browser_shot_check` 复跑时 t=12.0 跨通道 **−0.370**、对成片 −0.289（±3 搜过仍负）。
  两条通道在同一时刻画了**不同内容**，比色彩残差严重（预览在讲另一个故事）。已立 **U-94**。
  注意该次截图的 sidecar 是 `540×953`（其余是 540×960），所以**先排除截图几何**再谈内容。
- **复跑**：`python scripts/caption_ink_check.py --timestamps 1.0 --sweep-fallbacks`（回退字体标定）、
  `python scripts/browser_shot_check.py --model temp/playback-test/model-proxy.json`（L10 复跑）。
  全门回归（字体链改动会影响 L2/L3/L8/L9，因为它们量的就是通道 2）读数见下一条补记。
- **证据等级**：字体回退与修前/修后读数为**已验证**；U-94 目前只是**已观察**（一次读数，未归因）。

## P-41 F-084 的补记：字体是本次会话中途被剪映清掉的，两条通道各自换了字面；把回退标定统一到同一条之后 L10 回到 0.950（2026-10-24 19:29）

- **为什么要单独补这条**：P-40/F-084 首版把「浏览器对、通道 2 错」写成了一条跨通道结论，
  但它是在**两个条件**下取的数（门 03:18 重截之前 vs 之后）。这条把条件钉平。
- **环境事实**：草稿字幕用的 `Cache/effect/.../HelloFont_ID_JianSong_95.ttf` 在**本次会话中途**
  被剪映从机器上清掉了（不是我们删的，也不是代码改动）。证据链：
  ① 上一轮截图里浏览器字幕墨 **3544** ≈ 成片 **3476**（真面还在时的样子）；
  ② 通道 2 在 03:11 已经画成豆腐块（带内 43）；
  ③ 门 03:18 重截后浏览器自己只剩 **2221**（= 成片 64%，因为页面回退到 `sans-serif` → 雅黑常规）；
  ④ 载体里 `fonts[].exists` 仍写 `true`（那是建载体那一刻的快照），于是浏览器去取一个不存在的字体，
  报 `A network error occurred`，**L6 因此红**——不是混音、不是黑帧。
- **把两条通道接到同一条标定上**：通道 2 `FALLBACK_FONTS[0] = msyhbd.ttc`（P-40），
  浏览器 `textStyleOf` 的缺失面回退从 `'sans-serif'` 改成 `'Microsoft YaHei'` + `fontWeight:700`。
  同条件复测（t=1.0，成片帧 33，带内 >200 墨）：
  **浏览 4145 / 通道 2 3961 / 成片 3476**；t=7.0：**8973 / 8979 / 9324**（两通道差 6 个像素）。
  ⇒ 跨通道一致：t=1.0 **0.950**（判据线 0.95，刚好过）、t=7.0 0.983、t=12.0 0.988，
  对成片中位 0.965。**F-084 首版那个「0.898 回归」是换字面的中间态**，不是渲染回归。
- **两侧现在同向偏离成片约 +14~19% 墨量**（4145/3961 vs 3476）：重宋被粗体黑体替代后笔画更肥。
  这是**缺面的必然结果**，不是 bug；要结案只能找回 JianSong 95 本体（机器上已无，
  `Resources/Font`、`SystemFont`、`Cache/effect` 都翻过）。已在 U-93 记为保真上限。
- **判据卫生的两处改动（都由这次自己踩出来的）**：
  ① 我给 L2 加的「整帧墨量比」判据是**空的**（豆腐块负样本读 0.865），已回退成只报不判，
  并把负样本结论写进代码注释——**加判据前先造负样本**；
  ② `browser_shot_check` 现在按**过期**跳过截图（默认 >180 min），几何只在差 >2% 时才拒：
  第一版我写成「尺寸不等于画幅比例就跳过」，当场把 5 张**有效**截图误杀
  （`extract.pixels(stage)` 取的是 stage 内容包围盒，540 宽通常配 540×**953**，不是 960）。
  ③ 新增门层 **L1 carrier freshness**：载体的 `fonts[].exists` 与磁盘不符就红，
  并把原因说清楚（重建载体），不要让 L6 替它背锅。
- **复跑**：`python scripts/browser_shot_check.py --model temp/playback-test/model-proxy.json --max-age-min 60`；
  载体刷新是一次性的 `os.path.isfile` 复核（`.bak` 已留）。
- **证据等级**：已验证（同条件三腿复测 + 负样本 + 误杀被当场发现并改正）。

## P-42 L10 的门禁接线错了：通道 2 那一腿用的是**原片模型**，而浏览器播的是代理（0.912 vs 0.950 就是这么来的）（2026-10-24 19:35）

- **现象**：P-41 把两条通道的字体回退统一到同一条标定之后，手工跑 `browser_shot_check` 读到
  t=1.0 跨通道 **0.950**（过线），而门自己的 L10 同一批截图读到 **0.912**（不过线）。
  同一批截图、同一时刻、两个数 ⇒ 差在**判据端喂给通道 2 的是哪份模型**。
- **成因（一行代码）**：`playback_check.py` 调 `browser_shot_check.py` 时传的是 `--model args.model`
  （原片模型），而浏览器实际播的是 `--media-model`（代理）。**F-083 第③条早就量过这个混淆本身
  ≈0.04**（0.910 vs 0.948），当时只在手工跑里修掉了，**门禁接线没跟着改**——
  所以这条红是判据端的媒体不匹配，不是渲染回归。
- **修法**：L10 的通道 2 腿改用 `media_model`（与浏览器同一批媒体）。改后同条件读数：
  **t=1.0 跨通道 0.950 / 对成片 0.965**，t=7.0 0.983 / 0.976，t=12.0 0.988 / 0.945，
  三条全过（判据：跨通道 ≥0.95、对成片 ≥0.90）。
- **通用规约（这条值得记住）**：**判据端的两条腿必须来自同一批输入**，而且这件事要写在**门禁接线**里，
  不能只写在手工复现命令里——手工跑对了、门还是错的，等于没有。凡是「A 通道 vs B 通道」的层，
  都要问一句：B 那一侧喂的是 A 实际用的那份模型吗？
- **顺带**：`browser_shot_check` 的**过期截图跳过**会进 `problems`（所以「请求的时刻没截图」会红），
  这是有意的——判据端不接受来历不明的图；但**未被请求**的旧图不会被扫（`--timestamps` 先过滤），
  所以目录里留着上一轮的截图不会污染判据。
- **复跑**：`python scripts/browser_shot_check.py --model temp/playback-test/model-proxy-a.json`
  （门自己已经带对参数，不必手工传）。
- **证据等级**：已验证（同批截图、只换通道 2 的模型输入，0.912 → 0.950 单变量复现）。

### P-42 补记：改完接线的门读数 **14 / 14 全过**（口径：只跑了 L1/L2/L4/L5/L6/L10，L7/L8 与 L9 用 `--skip-mixmode --skip-animations` 跳过，`--repeat 1`）（2026-10-24 19:38）

- L10 首次转绿：**3 timestamps compared, 0 problems**（t=1.0 跨通道 0.950 / 对成片 0.965，
  t=7.0 0.983 / 0.976，t=12.0 0.988 / 0.945）。
- L6 也回到 0/1（字体网络错误随载体 `exists` 刷新而消失，见 P-41③），
  新增的 **L1 carrier freshness** 首跑即 PASS（`stale exists=true on 0`）。
- L2 读数里 `ink ratio 0.978` 现在**只报不判**，注释写明它在 F-084 负样本上是空判据。
- 同轮其它判据：连续播放中位 29.53 fps、seek 中位 21.2 ms、首帧 100.9 ms、
  Range 4346 请求/10 s、混音 0 audio_errors。
- **别把这条读成「全门 18 层绿」**：混合模式三层（L7）与动画两层（L8）+ 跨通道曲线（L9）这次被跳过，
  合入门禁前需要一次不带 `--skip-*` 的完整跑（P-38 那次是 18/20，两条红一条已随 L8 计数化改写解决、
  另一条就是本条修掉的 L10）。

## P-43 全门首次 21/21 全绿：L10 从 F-083 诞生起就红着，这次随字体回退统一 + 接线修正一起过了（2026-10-24 19:46）

- **口径（重要，别读成「所有判据都被反复测过」）**：命令是完整层集合（**不带** `--skip-*`，
  含 `--mixmode-gpu`），但 **`--repeat 1`** —— 所以 L4 的首帧/帧率、L5/L6 的混音类判据都是
  **单次跑**的读数，不是中位；那些「判据是区间不是数」的量（U-79 首帧、U-86 `peak_fs`）
  不能拿这次当分布用。跑法：
  `python scripts/playback_check.py … --repeat 1 --mixmode-gpu --shot-times 1.0,7.0,12.0`。
- **21 层全过**：L1×3（含新增 **L1 carrier freshness**）、L2、L3、L4×4、L5、L6×2（含 guard-has-teeth）、
  L7×3（出厂 GLSL / 接线 / GPU 三方 10 模式 0 越界）、L8×2（曲线表重建 8/33 段 / 真草稿动画接线 5/5）、
  L9（跨通道曲线 7 段 0 不一致）、**L10（3 个时刻 0 problems）**。
- **L10 的历史**：它诞生那天就是红的（F-083，P-38 那次 18/20 的一条红就是它）。红的原因**换了三次**
  才对：① 先判成「浏览器偏亮 1.8 码值」（分带网格是猜的，F-084 否证）；② 再判成「通道 2 没画字幕」
  （方向对了，但那是**跨条件**比较——字体是中途被剪映清掉的，P-41）；③ 最后发现**门禁接线自己**
  把通道 2 的输入喂成了原片模型，而浏览器播的是代理（P-42，同一批截图 0.912 vs 0.950）。
  ⇒ 一条红的判据能同时藏住**产品缺陷 + 判据缺陷 + 接线缺陷**三层，逐层剥开才见到绿。
- **同条件最终读数**（t=1.0 / 7.0 / 12.0）：跨通道 **0.950 / 0.983 / 0.988**，对成片
  0.965 / 0.976 / 0.945；字幕带内 >200 墨 浏览 4145 / 通道 2 3961 / 成片 3476（t=1.0），
  t=7.0 是 8973 / 8979 / 9324。两侧对成片都**多墨 14–19%**，这是**缺面的必然代价**，不是 bug（U-93②）。
- **还红着的东西：没有**。但**未覆盖**的仍然未覆盖：9 个动画预设（U-91）、浏览器侧混合模式（U-92）、
  调色/滤镜（spec 明确不在范围内）、以及 U-79 的判据口径（等用户定）。
- **同时在跑**：三臂 600 s 内存 A/B（`apply` 载体+应用 / `noapply` 同载体 `&anim=0` /
  `nocarrier` 用 `model-noanim.json`，实测该文件 `animations` 条目 **0** vs 载体 **33**，
  单变量干净）。这条补的是 P-37 的短板：200 s 不能外推到 600 s，而 895→1166 MB 那次中位漂移
  **从来不是单变量比较**。读数回来后接 P-44。
- **证据等级**：21/21 是**本次跑**的读数（n=1/层）；「L10 转绿」为已验证（同批截图单变量复现，见 P-42）。

## P-44 第一次「600 s 内存 A/B」其实是 38 s：判据端的解析静默回退，把时长不足的跑当完整跑报了出来（2026-10-24 19:54）

- **发现方式**：三臂 600 s 的 A/B 在**两分钟**内就报完成并给出 median 987/957/976、peak
  1127/1109/1134、越线 0/38。跑得快本身就是信号，于是去查子进程留下的原始文件。
- **两个独立缺陷叠在一起**：
  1. **我传的 `--playms 37000` 小于 `--seconds 600`** —— 页面放完一遍时间线就收工，soak 跟着结束
     （`wall_s=38.2 samples=38`）。`--seconds` 在 soak 里是**上限不是下限**，`loop=1` 也没把
     测量窗口撑住。⇒ 三臂各只跑了 38 s。
  2. **`rss_ab` 的逐秒正则失效**：`browser_soak` 现在只往 `rss-<tag>.txt` 写**汇总行**
     （`wall_s=` / `rss_*=` / `by_role`），不再写逐秒序列，所以 `re.findall(r"^\s*[\d.]+\s+(\d+)\s+\d+")`
     匹配到 0 个数 ⇒ `samples=0`、`p95=None`，而打印行的 `median or s.get('rss_median_mb')`
     **静默回退**到汇总值。回退本身是对的，错的是**没人核对这轮跑了多久**。
  ⇒ 两个缺陷合起来的效果：**一次 38 s 的跑被完整地标成「600 s 三臂 A/B」并给出看起来正常的数**。
- **修法**（`scripts/rss_ab.py`）：改成直接读 `wall_s=` / `samples=`，任何一臂 `wall_s < 0.8×--seconds`
  就打 `实跑=38s/600s <-- 臂作废` 并 **exit 1**；逐秒 median/p95/max 那三个字段不再假装存在
  （soak 不给序列就没有，别用回退值冒充）。
- **仍然有用的读数（口径：38 s，不是 600 s）**：三臂 median **987 / 957 / 976 MB**、
  peak **1127 / 1109 / 1134 MB**、越线 **0/38** 全部一致，角色峰值 renderer 479/464/493、
  gpu-process 406/402/398。`nocarrier`（模型里 `animations` 条目实测 **0**）与 `apply`（**33**）
  差 **−11 MB** —— 在 38 s 尺度上**没有任何「应用动画会抬高内存」的迹象**，
  与 P-37 的三臂 200 s 结论同向。但这**不能外推到 600 s**（gpu-process 随时长增长），
  所以修正参数后重跑：`--seconds 600 --playms 660000`，读数回来后写 P-45。
- **通用规约**：**凡是解析外部工具输出的判据，都要把「没匹配到」当成错误，而不是回退到别的字段**。
  静默回退 + 上限语义的 `--seconds` = 一个会把短跑报成长跑的仪器。
- **证据等级**：缺陷与修法是**已验证**（原始 `rss-*.txt` 里 `wall_s=38.2 samples=38` 直接可查）；
  600 s 的结论**未定**（重跑在飞）。

## P-45 动画欠口定档：`animation_tiers.py` 按段加权分层，并把自己五分钟前写的结论否掉了一半（2026-10-24 20:03）

- **动机**：U-91 一直记的是「9/12 个预设没覆盖」——那是**预设个数**。排产要看**观众看得见的段数**，
  而且要看**每个预设到底缺什么**。新仪器 `scripts/animation_tiers.py`（表
  `evidence/tables/animation_tiers.csv`）逐预设实测：包内 lua 数、frag 数、`.rt` 数、贴图、
  是否 AE/LightSpeed 导出件、曲线可否求值、**以及 frag 的语义**（采样次数 / 循环 / 邻域）。
- **终版分层（33 段口径）**：T0 3 预设 / 8 段（24%）；**T1 0 预设 / 0 段**；
  **T2a 2 预设 / 15 段（45%）**；T2b 1 预设 / 2 段（6%）；T3 6 预设 / 8 段（24%）。
- **两条否证**（都是我自己刚写下的）：
  1. 「再放宽曲线读取器就能多拿几段」——**T1=0**。九个未覆盖预设的 lua 里**一个 `fromTo` 都没有**
     （全文扫描，不是抽样），已覆盖那三个恰好是本时间线仅有的 fromTo 族；
  2. 「剩下 51% 需要执行包内 shader」——**分层只看文件计数会撒这个谎**。第一个被打开的 T2 预设
     （向上露出）frag 实测就是一句行遮罩
     `texture2D(_MainTex,uv0) * step(uv.y, 1-(1-height_cut)*0.4)`：**单采样、无循环**，
     两通道都能**不跑 GLSL** 实现（等价于一个随时间变长的裁剪框）。⇒ 加了语义判据后把它单独列成 T2a。
- **所以真正的阻塞点**：T2a 那 15 段缺的是 **lua 语义**，不是 shader——
  打字光标 是 `onUpdate` + `checkDirty`×2 + `seek` 的**逐字状态机**（另带一张光标 png），
  向上露出 只有 `seek` 一个入口但配一条**闭式贝塞尔**（`controls {0,0,.5,1}`，可直接移植）。
  施工顺序改为：**先移植 T2a 两个 lua 的语义**（mask 两侧各自实现），再评估 T2b/T3 那 8 段
  值不值得为它给通道 2 接 offscreen GL。
- **代价提醒**：T3 里最重的 向右模糊 II 是 **21 个 frag + 8 个 `.rt`**，侧滑 的 frag 内 **25 次采样**，
  模糊消失 带 `.lsanim/.lsproj/.jsdat`（AE 导出工程）——那是另一量级，别和「补一条曲线」混在同一张排产表里。
- **复现**：`python scripts/animation_tiers.py`（只读草稿与包目录，不写不回）。
- **证据等级**：分层读数**已验证**；「T2a 可用裁剪框等价」目前对**向上露出**是实测（frag 全文），
  对**打字光标**仍只是推断（它的 png 与逐字 alpha 通道还没验证等价性），实现时要逐条复测。

## P-46 600 s 单变量内存 A/B：**「我引入了动画内存回归」这条彻底否证**——应用动画那臂的中位数与漂移都是三条里最低的（2026-10-24 20:27）

- **设计（口径先写死）**：同一版 `player.html`、同一网关、同一 `--playms 660000`、`seeks=0`、
  三臂只差一件事：
  `apply` = 载体带 33 条动画且页面应用；`noapply` = **同一份载体** + `&anim=0`（载体在、不应用）；
  `nocarrier` = `model-noanim.json`（实测 `animations` 条目 **0**，其余键与载体逐键同）。
  每臂 600 s、598 个样本。**这是 P-37 那轮 200 s 的加长版**，专门用来回答「200 s 看不出来说明不了什么」。
- **读数**：

  | 臂 | median | mean | peak | last | 首60s→末60s | **漂移** | p95 | 越 2048 |
  |---|---|---|---|---|---|---|---|---|
  | apply | 1013 | 1009 | 1180 | 1077 | 1005.5→1024 | **+18.5 MB** | 1111 | 0/598 |
  | noapply | 1040 | 1034 | 1199 | 1090 | 996→1062 | +66.0 MB | 1133 | 0/598 |
  | nocarrier | 1027 | 1021 | 1189 | 1132 | 1012→1052 | +40.0 MB | 1126 | 0/598 |

  角色峰值（各自最大值）：renderer 437/453/467、gpu-process 434/438/449、browser 215/215/171 MB。
- **结论**：**「应用动画会抬高内存」被否证**，而且方向反过来——**应用动画那臂的 median 与漂移都是三条里
  最低的**。三臂 median 极差 26 MB（2.6%）、peak 极差 19 MB（1.6%），漂移排序
  （+18 / +66 / +40）**与「动画工作量」不单调**，所以那点差异是会话噪声而不是机制。
  600 s 内没有任何一臂接近 2048 MB 线。
  ⇒ P-36 记的那条「可能是我自己引入的越线回归」（首跑 max 2809、10/199 s 越线）**到此结案**：
  三臂 200 s 未复现（P-37）+ 三臂 600 s 未复现（本条），首跑那个数是离群点。
  也 ⇒ 之前那个「build 之间 median 895→1166 MB」的位移**从来不是单变量比较**，不能再当证据引用。
- **仪器修正两条（都在这轮踩出来）**：
  ① `--seconds` 是**上限不是下限**，页面放完 `playms` 就收工 ⇒ 上一版把 38 s 当 600 s 报了（P-44）。
    现在 `rss_ab` 读 `wall_s` 核对，不足即标作废并 exit 1；
  ② soak 自带的 `growth_mb_over_window` **不能用**：它是「末值 − 首值」，而首值永远是 Chrome
    还没起 renderer 时的 5 MB，于是每条臂都"增长 ~1000 MB"。已加 `drift_from()`：
    **末 60 s 中位 − 首 60 s 中位**（并给 p95），样本 <120 返回 None（短跑不给漂移，免得又拿噪声当结论）。
- **仍未决（不这条的范围）**：**≤2 GB 这条判据该按哪个口径算**（median / p95 / peak / 越线秒数）
  还是 U-79，等用户定。本条只证明「动画不是内存问题的来源」。
- **复现**：`python scripts/rss_ab.py --arms "apply=model-proxy-a.json,noapply=model-proxy-a.json?anim=0,nocarrier=model-noanim.json" --seconds 600 --playms 660000`（约 33 分钟，机器需空载）。
- **证据等级**：已验证（三臂同 build 单变量、598 样本/臂、漂移口径写明并给出计算函数）。
- **L10 逐时刻补记**（同轮 `temp/playback-test/browser-shots.json`）：
  t=6.85 跨通道 **0.978** / 对成片 **0.973**；t=7.2 跨通道 **0.982** / 对成片 **0.975**；
  t=1.0 跨通道 0.950 / 对成片 0.965。⇒ **打字窗口内那两个时刻的对成片数是本轮最高的**，
  截图与目标时刻差 0.0 s、偏移 0 帧，所以不是采样巧合。（仍受上面那条「整帧 corr 对单层不敏感」的限制，
  不能据此宣布律已验证。）

## P-49 时间轴修对之后重跑门：仍 20/20，且**打字窗口内跨通道从 0.978 升到 0.994**（2026-11-24 21:22）

- 上一轮那个 20/20 是带着**错的时间轴**（片段时长而非动画的 0.20 s）测的，所以必须重跑。
  修好后同口径重跑（`--shot-times 6.7,6.85,1.0`，两个打字窗口内时刻）：**20 of 20，0 problems**。
- L10 逐时刻：t=6.7 跨通道 **0.983** / 对成片 0.947；t=6.85 跨通道 **0.994** / 对成片 0.973；
  t=1.0 跨通道 0.950 / 对成片 0.965。
  ⇒ **跨通道那一栏是"两条通道现在算的是同一条律"的直接证据**（0.994 是本项目到目前为止最高的跨通道值）；
  它**不是**保真度证据——对成片那栏受整帧相关对单层不敏感的限制（F-072/F-080），
  逐字保真度仍按 U-95 走（干净样本 6 对/5 错、我们慢约一个字）。
- 卫生：本轮所有测量进程与网关都已退出（无残留 `python.exe`，端口无监听）。
- **证据等级**：无回归 + 窗口内跨通道一致 **已验证**；打字保真 **未定**（U-95）。

## P-50 逐字判据在这条草稿上**根本不可构造**：14/14 段找不到「该段不在场、且无别的字幕在场」的对照时刻（2026-10-24 21:43）

- 我把 f<0 有效性对照写进 `typing_extent_check` 之后，第一版**一段都没拒**——当时差点被读成
  「数据都干净」。加了一行把对照本身打出来才知道真因：**14 段全部 `对照=无`**，
  也就是在 `t0 − k·动画时长`（k=1..2.5）这些候选时刻，**总有别的字幕段活着**
  （本时间线 3 条文本轨、`clip.y` 全是 −0.4427，同一行）。
- **结论（口径级，不是待办级）**：在这条草稿上，**任何**「拿成片当参照识别这段字幕露了几个字」的判据
  都没有可用的阴性对照 ⇒ 逐字保真度**测不了**，不是"还要再修仪器"。
  一个没有阴性对照的判据，给出 27/43 这样的"干净读数"恰恰最危险（F-089 已经栽过一次）。
- **立为打字类动画的正式判据**：F-088 的**同刻开/关 MAD 对照**（`animation_region_check`，
  两臂只差这一条动画、不需要认字）：打字段 **23 近 / 19 远**，中位 MAD 开 24.23 vs 关 24.69。
  这是**弱正向**，能说的是「加上这条律之后，画面在统计上比不加更接近成片」，
  **不能**说「每个字出现的时刻与成片一致」。
- **时钟问题（`seek` 的 time 零点、0.20 s 是否真被引擎用满）就此挂起**：在没有阴性对照的前提下
  不再猜参数——那正是 F-089 那条假结论的产生方式。要重启这条路，需要一个**能构造阴性对照**的
  测试草稿（单条字幕轨、字幕不与别的层同 y），这属于 fixture 需求，不是代码需求。
- **仪器留用价值**：`typing_extent_check` 的 `R_k` 标定（前缀→右边缘，@216 宽
  `[-1,116,125,134,144]`）与背景相减做法是对的，且它现在**会打印对照是否存在**；
  在单轨 fixture 上可以直接复用。
- **证据等级**：「不可构造」**已验证**（14/14 计数，逐段可查）；开关对照读数**已验证**；
  逐字时钟**未判且本草稿不可判**。

## P-51 播放测试的**完成度审计**（对着目标逐条核，含两处我自己发现的证据缺口）（2026-10-24 21:47）

目标是「按计划在<草稿A> 上做播放测试」。逐条核对**当前证据**，不是核对工作量：

| 目标项 | 现状 | 证据在哪 | 还缺什么 |
|---|---|---|---|
| 浏览器能放这条时间线（NAS Range、路径宏、多轨合成、加密缓存降级） | **过** | 门 L4×4 + L5 + L6（P-43/P-49） | 无 |
| 画面与原生成片同刻可比 | **过**（对成片中位 0.965，跨通道 0.950–0.994） | L10 `browser-shots.json`、F-083→F-084→P-42 链条 | 素材层 ~1–2 码值残差（U-93①，随时刻变号） |
| 文本样式（字号/颜色/描边/阴影/多行） | **部分** | L2、F-035/F-036 的 em 律 | **字体缺失时只能替代**：重宋已不在机器上，两通道都比成片多墨 14–19%（U-93②，环境依赖） |
| 动画 | **T0 3 预设/8 段 + 打字光标 14 段已落地** | L8/L9、F-085/F-087/F-088、P-48/P-49 | T3 8 段（多 pass/RT 链、AE 工程）；光标叠加层；**逐字保真在本草稿不可测**（P-50） |
| 混合模式 | **离线两腿已三方验死** | L7×3（F-077/F-079） | **浏览器侧未接**（U-92）；本草稿 `mix_mode` 段数为 0，所以这条不影响本草稿读数，是**能力欠口** |
| 音频 | **过**（电平差已归因到 `segments[].volume` 并修） | L5、F-073/F-076 | `peak_fs` 的离散成因（U-86）与**判据口径**（U-79，等用户定） |
| 内存 ≤2 GB | **600 s 三臂未复现越线；动画不是来源** | P-46 | **见下面缺口 2** |
| 写回（M3） | **未开工** | — | 需要授权 + U-57/r4 重冻结 |

**我自己发现的两个证据缺口（不写出来就等于拿弱证据冒充强证据）**：

1. **所有"全绿"都是 `--repeat 1`**：L4 首帧/帧率、L5/L6 混音类判据每次只有 1 个样本，
   而本项目已经确立「判据是区间不是数」（U-79：首帧 168–246 ms；U-85：`peak_fs` 4/8 跑越界）。
   ⇒ 正在补：本轮 `--repeat 5` 完整跑（`temp/playback-test/gate-repeat5-typing.txt`，
   截图时刻含打字窗口 6.7/6.85/7.2），读数回来后本条的"过"才算带分布。
2. **600 s 内存 A/B 测的是**打字光标落地之前**的页面**（P-46 跑于 19:54–20:27，打字代码 20:33 之后才进）。
   那条"应用动画不抬高内存"的结论**不覆盖**新增的逐帧改 `node.text` 路径 —— 而改文本会触发 Pixi 重排字形，
   正是最可能涨内存的那类操作。⇒ 门跑完后需要一次**短 A/B**（同 build，`apply` vs `apply &tw=0` 或
   直接 nocarrier 对照）重测打字路径；在测出来之前，P-46 的结论只能引用到"fromTo 类动画"。
   这条是本轮审计的**主要产出**：我差点把一条已经不适用的结论继续挂在账上。

**结构性阻塞（不是待办，是依赖）**：逐字保真度要能量化，必须有一条**单字幕轨、字幕不与别的层同 y**
的成片做参照。成片只能由剪映导出 ⇒ 需要 (i) 造一条那样的草稿（写回/新建工程，属 M3 授权范围）
或 (ii) 用户手上已有类似草稿+导出。**在此之前 U-95 保持"待 fixture"，不要再猜时钟参数**（F-089 的教训）。

## P-52 缺口 1 补上：完整层集合 **`--repeat 5` 21/21**，判据第一次带分布（2026-10-24 22:03）

- 命令：完整层（含 `--mixmode-gpu`、`--cover*`、`--video-scan`）、**`--repeat 5`**、
  `--shot-times 1.0,6.7,6.85,7.2,12.0`（三个时刻故意落在打字窗口内）。读数 `gate-repeat5-typing.txt`。
- **结果 21 of 21**，且这些是**中位 + 区间**，不再是 n=1：
  - 连续播放 **中位 29.34 fps，最低 29.15**（n=5，判据 ≥24）
  - 首帧 **中位 102.9 ms，区间 96.8–134.4**，**0/5 越 300 ms**（比 U-79 记的 168–246 ms 更好，
    但口径不同：那批是旧 build，别混用）
  - seek **中位 26.1 ms，最差 28.5**；Range **中位 3403 请求/10 s**
  - **L6 0/5 跑有黑帧或错误** ⇒ P-31 那族偶发 `Input has been disposed` 这 5 跑没出现
    （**不等于已修**，只是 n=5 没撞上；别把这条写成结案）
  - L5 0/5 audio_errors；会话内存 **mean 772 / peak 957 MB**（600 s 那条判据另算，见 P-46 与缺口 2）
- **L10 五时刻 0 problems**：跨通道 `t=1.0 0.950 / 6.7 0.983 / 6.85 0.994 / 7.2 0.994 / 12.0 0.988`，
  对成片 `0.965 / 0.947 / 0.973 / 0.975 / 0.945`。
  **打字窗口内三个时刻的跨通道 0.983–0.994** 是「两条通道算同一条打字律」的最强证据。
  一处要注明：t=6.7 对成片那条**选了 +3 帧偏移**（0.947），落在 `向上闪入` 的白闪区，
  属于 F-072/P-28 那条「切点附近固定帧号不可比」的老账，不是打字造成的。
- **审计更新**：P-51 缺口 1 **已闭合**（全绿现在有 n=5 分布）；缺口 2（打字路径的内存/fps 代价）
  仍未闭合，正在补 `&tw=0` 开关后做两臂短 A/B。

## P-53 缺口 2 闭合：打字路径在 240 s 上**量不出内存代价**（两臂差 ≤2 MB 中位、漂移差 1 MB）（2026-10-24 22:17）

- **为什么要单独测**：打字光标落地后，页面每帧可能改 `node.text`（Pixi 改文本要重排字形），
  这是 P-46 那次三臂 A/B **之后**才出现的路径 ⇒ 旧结论不覆盖它（P-51 缺口 2）。
- **做法**：给 `player.html` 加 `&tw=0`（与 `&anim=0` 同族，**只关打字**、不动 fromTo——
  否则一关就把两种动画一起关了，测不出代价归谁）。两臂同 build、同模型 `model-proxy-a.json`，
  只差这一个开关：`rss_ab --arms "tw=…,notw=…?tw=0" --seconds 240 --playms 300000`。
  两臂都跑满 **241 s / 240 样本**（`实跑=` 那条守卫现在会拦时长不足的臂，P-44）。
- **读数**：

  | 臂 | median | mean | peak | p95 | 漂移(末60−首60) | 越 2048 |
  |---|---|---|---|---|---|---|
  | 打字开 | 994 | 995 | 1206 | 1109 | **+20.0** | 0/240 |
  | 打字关 | 996 | 993 | 1185 | 1087 | **+21.0** | 0/240 |

  角色峰值：renderer 578 vs 445、gpu-process 381 vs 430（**方向相反**，且这两项历史摆动很大，
  P-46 里三臂中位能差 26 MB 而无机制 ⇒ 角色峰值这次不作为判据）。
- **结论**：**没有可测量的打字路径内存代价**——中位差 −2 MB、漂移差 1 MB、峰值/p95 差 +21/+22 MB
  （约 2%），都落在 P-46 已确立的"臂间无机制散布"里。
  帧率侧另有一条独立证据：P-52 的 `--repeat 5` 是**带着打字路径**跑的，
  连续播放中位 **29.34 fps、最低 29.15**（打字落地前同类跑是 29.64/29.97），差值在 n=5 的散布内。
- **口径提醒（别外推）**：这是 **240 s**，不是 600 s；P-46 已经确立"短跑干净不能外推到长跑"。
  要拿这条当"打字不涨内存"的终局结论，还需要一次 600 s 两臂（约 22 分钟）。
- **证据等级**：240 s 两臂**已验证**（单变量、时长守卫通过、无越线）；600 s 外推**未做**。

## P-54 600 s 两臂补测：打字路径的内存代价**量不出来**（中位 +15 MB / 峰值 +1 MB，角色峰值几乎相同）（2026-10-24 22:44）

- 补 P-53 的外推缺口：**同一 build、同一模型，只差 `&tw=0`**，两臂各跑满 **600 s / 598 样本**
  （时长守卫通过，P-44 那条）。
- **读数**：打字开 median **1042** / mean 1036 / peak **1212** / p95 1138 / 漂移 **+32.5** MB；
  打字关 median **1027** / mean 1023 / peak **1211** / p95 1120 / 漂移 **+22.0** MB；
  **两臂都 0/598 秒越 2048 MB**。角色峰值：gpu-process 448 vs 447、renderer 433 vs 433、
  browser 239 vs 236 —— **三个角色都几乎相等**。
- **判定**：差值中位 +15 MB（1.5%）、峰值 +1 MB、p95 +18 MB，**与 P-46 三臂之间"无机制的臂间散布"
  （中位曾差 26 MB）同一量级**，且角色峰值几乎不动 ⇒ **打字路径（每帧改 `node.text`、Pixi 重排字形）
  在 600 s 上没有可测量的内存代价**。P-51 缺口 2 就此闭合。
- **唯一值得留一眼的量**：漂移差 **+10.5 MB/10 min**（开 +32.5 vs 关 +22.0）。
  它本身很小（占中位 1%），但两臂的漂移都还是正的、且方向一致，
  所以**如果将来把判据窗拉到 30 min 以上**，这一项要重测——不要在 600 s 上外推成长会话结论
  （P-44/P-46 同一条教训）。
- **口径**：`--playms 660000`（> 窗口，避免 P-44 那个"放完一遍就收工"）；机器空载；
  报告 `temp/playback-test/rss-ab-typing600.json`。
- **证据等级**：已验证（单变量、双臂各 598 样本、无越线、角色分解一致）。

## P-55 补上门禁缺的一层：打字光标的接线判据 `L8 typewriter wiring`（含两次自我发现的假绿）（2026-10-24 23:06）

- **为什么缺这层**：打字是本轮新落地的渲染路径，而**整帧类判据对"整句一次出现 vs 逐字露出"不敏感**
  （F-072/F-080 同族）。表从载体里丢了、`typewriter_truncate` 提前 return、样式 range 错位，
  画出来都是"整句出现"，**没有任何一层会变红**。这违反本项目规约
  「本草稿会触发的新渲染路径必须有自己的门层」（L7 当年就是这么补上的）。
- **新层**：`scripts/typewriter_wiring_check.py` → 门里 `L8 typewriter wiring (prefix law live on
  channel 2 + carrier)`。断言：
  - **A1 单调露出**：动画窗口内 f=0.15/0.5/0.9 三点，纯文字层墨的右边缘严格递增，末刻 == 全文右边缘；
  - **A2 与律同解**：每点的右边缘必须落在 `typewriter_prefix` 给出的那个 k 的**标定边缘**上
    （k=0..n 各画一遍纯文字层得到 `R_k`，不靠阈值猜）；
  - **A4 载体**：14 个打字段的 `animations[].tw` 必须都在、两张表各 14 项
    （浏览器读不到包内 lua，表丢了就只能画静态，而这件事只有这条能发现）。
- **实测读数**（`--segments 3`，1080 宽尺度）：
  - `937BB0D1` n=4：`R_k=[-1,585,630,678,724]`，开动画 `[585,678,724]` ⇒ 正好 k=1/3/4；
  - `812FC671` n=3：`R_k=[-1,580,630,678]`，开动画 `[-1,580,678]` ⇒ k=0/1/3（f=0.15 时**一个字都没画**）；
  - `9DBDD0D8` n=4：`[584,678,724]` ⇒ k=1/3/4。**19 条断言 0 问题**，门内该层 PASS。
- **两次自我发现的假绿（这两条比判据本身更值得记）**：
  1. **空对象假通过**：`--model model-noanim.json`（动画条目 0）时循环一条都不跑，
     脚本会打印"0 问题 PASS"。已加 **A0 非空判据**：没有打字段就 FAIL
     （`assertions=1 problems=1 segments=0`），负样本退出码 **1**、正样本 **0**（真实退出码已核，
     第一次我用 `| tail` 量 `$?` 量到的是 tail 的，差点把"退出码没接上"当成通过）；
  2. **中文 detail 在管道里被吞**：门取 detail 靠匹配"打字接线"，子进程中文经 GBK 管道变成 "?"
     后匹配不到，回落到 stdout 尾巴——实测那格只显示一个 `]`，**失败时会把现场擦掉**。
     已加 ASCII 标记行 `TYPEWRITER_WIRING assertions=… problems=… segments=… carrier_tables_ok=…`，
     门改成匹配它。这与 P-31/F-083"报告环节不许弄丢结果"同族。
- **A3 牙齿的真实强度**（不吹）：A3 是"关掉动画后右边缘恒定"，但被测对象是**剥掉视频的纯文字层**，
  恒定几乎是构造保证的 ⇒ 它防不住素材运动。**真正的牙齿在 A1/A2**：律若失效，右边缘会恒为全文值，
  A1 的不等式立刻破。这条按实际强度记，不按设计意图记。
- **复跑**：`python scripts/typewriter_wiring_check.py [--model …] [--segments 2]`；
  门内验证：`python scripts/playback_check.py … --repeat 1 --skip-browser-shots` → **19/19**。
- **证据等级**：已验证（正/负样本退出码都实测；标定边缘与律的 k 逐点对表）。

## P-56 U-92 第一步：Pixi 侧三方对照**没跑通**，但量到了真正的拦路石（出厂件的 I/O 契约），并留下两个我自己的作用域 bug（2026-10-24 23:14）

- **做了什么**：新仪器 `temp/playback-test/mixmode-pixi.html`，三条腿设计——
  A 参照 = 出厂件 `frags-shipped/<id>.frag`（GLSL1，F-079 已证与包内原文 maxΔ=0）；
  B 被测 = 同一函数体机械 GLSL3 化后包成 Pixi 8 `Filter`，背景走 `RenderTexture`；
  C 噪声地板 = A 跑两遍自比。**没有动 `player.html`**，所以本轮对已绿的门零风险。
- **量到的拦路石（这是本轮唯一但结实的产出）**：出厂件的 I/O 不是 Pixi 能白给的形状——
  `varying vec3 uv0`（**xy=坐标、z=除数**）+ `varying vec2 uv1`（背景采样坐标）+ 三个
  `int` 状态量（`blendAlphaState/fgAlphaState/bgAlphaState`，我们的 main 不用但声明在）。
  Pixi 8 的滤镜只给 `vTextureCoord`/`uTexture`，所以**「机械 GLSL3 化」在 I/O 边界上不存在**：
  必须**自写适配顶点着色器**（第一版 link 就报
  `FRAGMENT varying uv0 does not match any VERTEX varying`，改完 A 腿才编过）。
  ⇒ U-92 的真实工作量不是"多写 8 个模式"，而是**先定这套 I/O 约定**；
  而且约定一旦写错（uv 语义偏移），比出来的差会被当成数学不等价——**这正是本项目反复踩的假读数族**。
- **我自己的两个 bug（记下来，因为它们是同一类）**：把腿 B 包进 `try` 做失败隔离时，
  `fnName`、`maxB/cells` 的**定义留在了 try 块内**、`return` 在块外引用 ⇒
  `ReferenceError` 两次，整条读数一起丢。这与 P-31/F-083"报告环节不许弄丢结果"、
  P-44"静默回退"同族：**隔离失败的正确做法是把变量提到外面、只把可能抛错的语句包进去**。
  另外第一次修 `vs1` 我用 shell 字符串替换打补丁，转义被吃掉、补丁**没落上**却打印了"patched"——
  又是那条老规矩：**改源码用编辑工具，不用 heredoc**。
- **当前状态**：仪器未出数（A 腿已能编译，B 腿因上述作用域 bug 未跑到）；
  U-92 **保持未开工**，`player.html` 未接混合模式（本草稿 `mix_mode` 段数为 0，
  所以这不影响本草稿的任何像素读数，是**能力欠口**，不是回归）。
- **下一步（给接手的会话，省一轮重新推导）**：
  ① 把 `fnName/maxB/cells` 提到 try 外面；② A 腿先单独出数（噪声地板 + 出厂件自比），
  确认网格生成式与 `mixmode-eq.html` 一致；③ 再写 B 腿的适配顶点着色器，
  并**用一张已知平移的网格**先验证 I/O 约定本身不错位（先测几何，再测数学）；
  ④ 只有 B 与 A 逐格 maxΔ≤1 才谈接进 `player.html`，接完复跑门看 L4 的 fps/RSS 判据。
- **复跑**：起网关后
  `python scripts/browser_soak.py --url "http://127.0.0.1:<port>/playback-test/mixmode-pixi.html?tag=mixmode-pixi&modes=multiply_blend_mode,screen_blend_mode,soft_light" --seconds 45 --tag mmix`。
- **证据等级**：I/O 契约**已实测**（link 报错原文 + 出厂件声明）；Pixi 等价性**未测**（仪器未完）。

## P-57 U-92 仪器出数了：**参照腿噪声地板 = 0**，被测腿卡在 Pixi 8 的**自定义纹理资源 API 形状**上（不是数学）（2026-10-24 23:19）

- 修掉 P-56 记的三个作用域 bug（`fnName`/`maxB,cells`/`gotB` 都定义在 `try` 里、`return` 在外面读）之后，
  `mixmode-pixi.html` 第一次给出**分腿**结果：
  - **腿 A（出厂件 GLSL1，WebGL2 编译）**：`legA_self_noise = 0`（`multiply_blend_mode`、
    `soft_light` 各跑两遍逐字节自比，**maxΔ=0**）⇒ **读回与驱动不引入任何噪声**。
    这条本身有价值：以后 Pixi 腿只要差 1 个码值，就是**真差**，不用怀疑测量链。
  - **腿 B（Pixi 8 `Filter` + `RenderTexture` 背景）**：两模式同一句错
    **`Could not find a source type for resource: [object Object]`**
    ⇒ 卡在 `resources: { uSrc: { source: bgRT } }` 这个**形状**上，与着色器数学无关。
- **所以 U-92 的拦路石清单现在是两条、都不是数学**：
  ① 出厂件 I/O 契约（`vec3 uv0`（z 是除数）+ `vec2 uv1` + 三个 int 状态量）与 Pixi 只给
    `vTextureCoord`/`uTexture` 不对齐，需要自写适配顶点着色器（P-56）；
  ② Pixi 8 自定义**纹理 uniform** 的资源声明形状（本轮这条错）。
  ⇒ 结论性判断：**U-92 不是"把 8 个模式搬过去"的活，是先解决 Pixi 滤镜的输入输出契约**；
  在 ①② 没通之前谈"逐格等价"没有意义，我也**不打算靠连猜 API 形状**把它撞过去——
  每次猜错都要一整轮浏览器跑，而撞对了也可能只是把错位读成数学差（本项目最贵的假读数族）。
- **接手者的下一步（按成本排序）**：先查 Pixi 8 文档/源码里 `Filter` 的 `resources` 与
  `texture` uniform 的正确声明形状（一次检索就能定，不用试错），再补适配顶点着色器，
  然后**先用一张已知平移的网格验几何**，最后才比数学。参照腿已经证明噪声地板是 0，
  所以几何一错位就会立刻显形，不会被噪声藏住。
- **风险面**：`player.html` 仍未接混合模式（本草稿 `mix_mode` 段数 0 ⇒ 不影响任何已有读数）；
  门保持 P-52 的 **21/21 @ `--repeat 5`** 加 P-55 的新层。
- **复现**：起网关后
  `python scripts/browser_soak.py --url "http://127.0.0.1:<port>/playback-test/mixmode-pixi.html?tag=mixmode-pixi&modes=multiply_blend_mode,soft_light" --seconds 45 --tag mmix`，
  报告 `temp/playback-test/report-mixmode-pixi.jsonl`。
- **证据等级**：噪声地板**已验证**（两模式各自比 maxΔ=0）；Pixi 等价性**未测**，
  阻塞点**已定位到具体 API 形状**（错误原文在案）。

## P-58 Pixi 腿**跑通了但读数不可信**：maxΔ=255/287 格是我自己跳过了 P-57 规定的几何验证步（2026-10-24 23:26）

- 三条 API 障碍都清了，仪器现在端到端跑得出数：
  ① `Texture.from({width,height,pixels:Uint8Array})` **不是 Pixi 认的资源** ⇒ 换 `Texture.from(canvas)`；
  ② 滤镜的纹理资源直接给 `RenderTexture`，不要包 `{source: …}`；
  ③ **Pixi 8 的 `Filter` 没有可事后改的 `.fragment` 字符串**（构造后读它是 undefined）
     ⇒ 最终 GLSL 必须在构造前拼完整。三条都是**读本地那份 pixi.min.js 源码**定的，没靠试错猜文档。
- **第一次真读数**：`multiply` maxΔ **255**、287/289 格超阈；`soft_light` maxΔ 255、286 格；
  参照腿噪声地板仍是 **0**。
- **但这个数不能当 U-92 的答案**，证据就在同一行里：`sample:[0,0,0,0]` —— 我采的那个角上
  **两条腿都是 0**，而 287/289 格全差 ⇒ 这是**Pixi 腿整幅没画出来/透明**的形状，不是混合数学差。
  **正是 P-57 我自己写的"先验几何、再比数学"那一步被我跳过了。**
  跳过自己定的步骤，仪器就会把"我的腿是空的"报成"两条腿不等价"——**方向完全相反的结论**。
- **所以 U-92 仍是未解**，且现在障碍清单变成三条 API 形状（已解）+ **一条几何自检**（未做）：
  下一步是给 Pixi 腿加**已知平移网格**的断言（`uSrc` 用一张左半黑右半白的图，
  断言读回的分割列 == 期望列），先证明 Pixi 腿**画得出东西且坐标对**，再比 Δ。
- **本轮没有将错就错**：不拿 maxΔ=255 去写"Pixi 做不到包内数学"的结论，也不动 `player.html`。
  门仍是 21/21（`--repeat 5`）+ `L8 typewriter wiring`；本草稿 `mix_mode` 段数 0，无回归面。
- **证据等级**：三条 API 形状**已验证**（源码 + 跑通）；maxΔ=255 **不可用**（腿未验几何）；
  U-92 等价性**未判**。

## P-59 2026-10-25 按 P-58 的计划修仪器：几何自检先行，撞出 Pixi 8 四条事实（F-093），数学等价性仍未判

- **做了什么**：把 `mixmode-pixi.html` 按"Pixi 腿先自证画得出东西且坐标对"重写：
  ① 强制 `resolution: 1` 并把读回的 `width/height` 断言回来（DPR≠1 会让 17×17 读成 22×22，
  `getPixels` 是裸 `readPixels` 且不翻 y，54436 行）；② 朝向不假设，四候选全算并报亚军差距；
  ③ 直通腿（前景/背景各自单独采样）先于混合腿；④ **读数画成字符**（R/G 谁亮）进报告；
  ⑤ 控制台 warn 收进读数。另加一张四分叉诊断页 `px-readback-which.html`。
- **9 轮迭代每轮只改一个变量**，依次排掉：`pc_fragColor` 不存在（Pixi 8 全文 0 处）→
  自建 RenderTexture 作 target 画不出东西（V3 全 0，stage 路 V1/V2/V4 都 Δ=0）→
  `generateTexture` 产物 frame 不铺满 source（这条我先误判成池位复用，被下一轮否掉：
  换成 canvas 纹理后 g1 读数**一字不变**）→ **自定义 sampler 名根本不绑**（`uSrc` 读到前景）。
- **读数**（`report-mixpixi10.jsonl`）：`g0` 直通 **maxΔ=0**（Pixi 滤镜通道保像素，朝向 identity）；
  `g3` 背景直通仍读到前景（`id:285/191`）；`rename.math_identical=true`、4 行差异 = 两个改名；
  腿 A 自噪声 0，`first4=[0,0,32,255]` 与手算 multiply 一致（B=0.5×0.25×255=32）。
  `useBackBuffer:true` 生效后 `warns=[]` 且读数不变 ⇒ 开关不是拦路石。
- **中途被我自己写坏两次**：一次 Edit 的 old_string 截半导致文件里留下悬空语句和重复尾巴
  （`node --check` 抓到），一次 G3/B 两腿的 `resources` 改了一半。都靠语法检查 + 单变量重跑收回。
- **没做的事**：`player.html` 未动（门仍 21/21 + `L8 typewriter wiring`；本草稿 `mix_mode` 段数 0，
  无回归面）；两仓库改动仍未提交，仍等一句话。
- **下一步**（按成本排序）：① 把 uniform 描述符补 `type: 'float'`（`{_alpha: {value:1, type:'float'}}`）
  让腿 B 跑通；② 测 `groupMap: {0:{1:'uTexture',3:'uBackTexture'}}` 能否把背景钉进正确槽位，
  不行就退一步——**不依赖 Pixi 的背景槽位**，改为把"已合成的背景"作为我自己提供的纹理喂进去
  （需要同一套 groupMap 机制，或先合成到一张 canvas 纹理）；③ 逐格 maxΔ≤1 才谈接入。

## P-60 2026-10-25 U-92 判完：不修 uniform 管道，改走 Pixi 的模板注入点 —— 包内数学逐字节进浏览器（F-094）

- P-59 列的三步都跑了，结果**三步的答案是"都不必做"**：
  ① `type:'f32'`（写 `float` 抛 `Uniform type float is not supported`）—— 标量能绑了，但背景仍不通；
  ② `groupMap` 显式钉 (0,3) —— 读数一字不变；
  ③ 用 `uTexture`（唯一保证绑得住的名字）重验适配顶点着色器 —— **maxΔ=0**，
     于是 P-59 里我撤回的那句"g2 证明 uv0 路径正确"以正确的方式重新成立。
- 决定性的一步是 **G5**：同一个场景改用 Pixi 自己的 `blendMode='multiply'`，读回与腿 A 的
  出厂件参照**逐字节相等**（0/0）⇒ 背景这条路在厂商机器里是通的，坏的只是"我那个自定义滤镜
  的第二个 sampler 注册"。于是接入形状从"自己造 uniform 管道"换成"**把函数注进它的模板**"：
  `new BlendModeFilter({gl:{functions: <出厂件去掉声明行>, main:'finalColor = X(front, back);'}})`。
- **等价性读数**（`report-mixinject.jsonl`）：multiply 与 soft_light 两模式都 **orient id、
  max 0、cells 0**（289 格全过），通道对照腿 C 也 0/0。加上 F-079（出厂件 ≡ 包内原文），
  现在是**包内 GLSL == 裸 GL == Pixi 注入件**三方闭合。
- **能力矩阵**（`report-mixmatrix.jsonl`，10 模式 × 内建 blend mode）：**只有 1/10 能被内建
  精确覆盖**（multiply），其余 maxΔ 64~255 全不等价 ⇒ 剩余 9 个模式必须走注入通道，
  "给每个模式挑一个 CSS 名字"这条路是错的（与 F-082 的"包内叠加/强光是 CSS 同名反的"互证）。
- **接入前还欠的四件事**（都写进 F-094 了，别把本轮读成"接入完成"）：`player.html` 未动、
  门未复跑（L4 fps/RSS 未知）；等价是在 `_alpha=1` 下测的；U-90 的 alpha 支路仍未定；
  本草稿 `mix_mode` 段数 0，接上后要靠构造 fixture 进门。
- **仪器纪律**：本轮 4 次改文件都在跑前 `node --check`（抓到两次悬空/重复尾巴），
  一次把 G5 的判据直接复用腿 A 的参照（没有新造判据），读数一律画成字符。

## P-61 2026-10-25 浏览器通道接上混合模式（U-92 收尾）：注入件进 `player.html` + 新门层 `L7 mixmode browser wiring`，全门 21/22

- **改了什么**：`player.html` 取 `/playback-test/mixmode/manifest.json`（md5→nameId/premul_fn）
  和 `frags-shipped/<nameId>.frag`（切片），按包 md5 **缓存**一个
  `new BlendModeFilter({gl:{functions, main:'finalColor = X(front, back);'}})`，
  在 `paintTracks` 的段循环里 `mixRecord(seg)`、帧尾 `mixApply()` 幂等挂到活节点上；
  解析不出包的 md5 **显式降级**并计数（与通道 2 的 `MIX_DEGRADED` 同口径，不许静默当正常层）。
  切片读的就是通道 2 读的那批文件，浏览器侧不产生第二份数学。
- **新门层**（`scripts/mixmode_browser_check.py`，已挂进 `playback_check.py` 的 L7 段）：
  拿注入件跑**真无头浏览器**，三条判据都带分母，并带**反 fixture**：
  `B1 载体` loaded=true / packages=10 / known=1；`B2 挂载` 分母 `stats.mix_mode_segments=23`，
  该刻活节点 `applied_nodes=1`（23 个注入段在同一时刻只有一个在画）；
  `B3 反 fixture` 未知 md5 ⇒ `known=0, applied_nodes=0, degraded=[0000…]`。
  注入文本 `chars=622` —— 与 F-094 实测等价时那一份**一字同长**，所以播放器里的变换就是被测过的那个。
- **全门复跑**（真模型 + `--media-model model-proxy-a.json`，`--repeat 1`）：**21 of 22，1 FAILED**。
  唯一的红是 `L10 t=6.633 对成片 0.898 < 0.9`，三条都归清楚了，**不是混合模式带去的回归**：
  ① 跨通道那时刻 **0.979**（浏览器与通道 2 彼此同意）；
  ② **完全离线、不含任何浏览器与新代码的通道 2** 在同一窗也低：`t=6.632 @64px 0.877`（+2 偏移），
     6.5/6.533/6.566 都是 0.99 —— 低点是 6.632~6.731 这 5 帧的 `向上闪入` 白闪衰减区（P-28/P-29，U-91）；
  ③ 我这次**漏了 `--shot-times`**，落到门的默认时刻表（含 6.633）；文档里那几次绿的 21/21
     用的是 `--shot-times 1.0,7.0,12.0` / `1.0,6.7,6.85,7.2,12.0`（P-52/P-53），本来就不取这帧。
  其余无回归：L4 播放 29.97 fps、seek 20.6 ms、首帧 100.9 ms、Range 2769 req/10 s、
  L6 0 黑帧、L5 音频 0 错、L9 曲线 7 段 0 不一致、L8 打字 14 段 0 问题；
  会话内存 rss peak 924 MB / mean 789 MB。**没有为了让门变绿去动阈值**。
- **两个自己的坑，都记下来**：
  ① 计数器挂在 **`/report`**（battery 路径）那份 `r` 上，而 `?shots=` 只发 `/shot` ——
     新层第一版读了错的端点，报成"浏览器一条都没回"（读数错了不等于被测对象坏了，
     靠现场 `window.__player` 看到节点上真挂着 `BlendModeFilter/8001e07e…` 才定位到我自己的读法）；
  ② **在门跑着的当口改 `player.html`**（还连着两次改出括号错），只能作废重跑——
     播放器文件是共享状态，改它之前要先确认没有跑着的读数；`node --check` 抽模块是唯一便宜的护栏。
- **仍未判的**（别把这条读成"混合模式全好了"）：等价是在 `_alpha=1` 下测的，注入件没有
  `min(_alpha,1)` 这一步（前景不透明度在播放器里由 node alpha 承担，**这条没测**）；
  U-90（app 到底走 PreMul 还是 Straight 支）仍未定，这里注入 PreMul 支与 F-079 的包装一致；
  真实草稿 0 个 mix 段 ⇒ 这条路径在真人数据上仍只有构造件背书。
- **证据等级**：接线**已验证**（真浏览器 + 反 fixture + 长度对上 F-094 那份文本）；
  无回归**已验证**（跨通道 0.979 + 通道 2 同窗同低，L4/L5/L6/L8/L9 全绿）；
  L10 那一条红的归因**已验证到内容层**，但**不判**——它是 U-91 `向上闪入` 的可见症状。

## P-62 2026-10-25 P-61 留下的那条「`_alpha` 没测」补测完：浏览器与通道 2 的**图层不透明度口径一致**（maxΔ=1、289 格 0 超差）

- **要回答的问题**（P-61 我自己记的口子）：注入件里没有 `_alpha` 这一步，
  厂商/通道 2 是 `fg *= min(_alpha,1)`（颜色**和** alpha 一起缩，`mixmode_blend.blend:114`）
  ⇒ 前景不透明度在浏览器里由 `node.alpha` 承担，但 **Pixi 有没有在批处理里把 alpha 预乘进
  滤镜输入那张 RT** 是这条等价成立与否的关键，不测就是空白。
- **判据不自己推**（这是本轮最重要的自我纠正）：第一版我在 JS 里手算了一个「均值」参照
  `(fg+bg)/2`，读数 maxΔ=128/287 格不符，看起来像"浏览器口径错了"。
  **那是我的参照算错了**：`ba=1` 时预乘律的解是 `bg·(1-α) + α·fg·bg`，不是均值。
  改成拿**通道 2 自己的** `blend(mode, fg, bg, fg_alpha=0.5)` 现算一张 17×17 表
  （`temp/playback-test/mixmode/a50-ref.json`，由 `mixmode_blend` 生成）再逐格比。
- **读数**（`report-a51.jsonl`，opacity=0.5，multiply 腿）：
  vs 通道 2 不透明度律 **orient id / maxΔ=1 / 0 格超差**；
  对立假设「alpha 没进滤镜输入」（= 纯乘积，与 α=1 的腿 A 参照比）maxΔ=128 / **287 格不符**。
  首格 `[0,0,48,255]` 两边**完全相同**（手算通道 2 也是 48）。
  ⇒ **`node.alpha` 确实以预乘形式进了滤镜输入，浏览器这条路径就是厂商的 `_alpha` 律**；
  maxΔ=1 与 F-079 的 8-bit 容差同口径。**播放器不用改**，P-61 那条口子关闭。
- **教训入库**：跨通道判据的参照必须由**被对照的那条通道自己产出**，不能由我按公式现推——
  这次两个假设都能被一个错参照"证实"，只有换成通道 2 的函数才分得开（与
  「检查自己的规格再宣称发现」「先建反 fixture 再挂判据」是同一条纪律）。
- **把参照做成可复现的**（下一轮就该有人重跑它）：`scripts/mixmode_opacity_reference.py`
  生成 `mixmode/a50-ref.json`（10 个模式 × 17×17 × RGBA，`--opacity` 可调，原子写）。
  重跑后 multiply 那一栏与 P-62 判定用的表**逐字节相同**（已验证），所以这条结论不再是
  一次 `python -c` 的口头读数。
- **同一判据扩到全部 10 个切片**（`report-a52.jsonl`，α=0.5，注入件用各模式**自己的**函数体）：
  **9 个模式两通道一致（maxΔ≤1、0 格超差），0 个不符，1 个跳过**；
  每个模式的对立假设「alpha 没进滤镜输入」都是 maxΔ 32~128、252~287 格不符 ⇒
  不透明度口径的一致不是 multiply 的特例，机制确实是模式无关的。
  `B2(α=1)` 那列同跑 9/10 cells=0，与 F-094 单模式读数互相印证。
- **跳过的那个暴露了一个仪器缺陷（不是播放器缺陷，要说清）**：`color_dodge.frag` 一个文件里
  定义了多个 `*BlendPreMul`，我用"第一个匹配"当函数名 ⇒ 拿到 `NormalBlendPreMul`，
  而该文件 main 调的不是它 ⇒ 该模式 B2(α=1) 286 格不符、α 腿因参照表里没有 `normal` 键而跳过。
  **播放器不受影响**：它读的是 `manifest.json` 里每包权威的 `premul_fn`（不是正则首个匹配）。
  要补的是仪器侧取名法（从 main 反查，或直接用 manifest 的 premul_fn），补完再重跑这一腿；
  这条不做就是拿一个已知会挑错函数的抽取去宣称"10/10"。

## P-63 2026-10-25 修掉仪器取名法（#15）：注入等价性从 2 个模式扩到**全 10 个模式 maxΔ=0**

- **修法**：函数名按 `manifest.packages[].premul_fn`（播放器读的就是这个权威字段）取，
  并断言它在该切片里真存在（`vec4 X(` 命中）；取不到才退回 main 体反查、再退首个匹配。
  每模式报 `fn_src`，这轮 **10/10 全部 `manifest`**，没有一个走回退。
  `color_dodge` 由此从 `NormalBlendPreMul` 纠正为 `ColorDodgeBlendPreMul`。
- **读数**（`report-a53.jsonl`，α=1 与 α=0.5 两条腿 × 全 10 个切片）：
  - **α=1 注入等价 10/10：maxΔ=0、0 格不符**。这比 F-094 强一档：当时只测了
    multiply/soft_light 两个模式，现在是**每个出厂件模式**都证过"注进 Pixi 模板后
    与裸 GL 出厂件逐字节相同"。
  - **α=0.5 两通道不透明度口径 9/10 在容差内**（maxΔ≤1、0 格超差）；
    `color_dodge` **2 格不符、最大差 2 码值** —— 这是读数，不写成 0。
    合理机制（**未证**）：dodge 支含 `1-(1-fg)/(1-bg)` 类除法，网格右上角 `bg→255` 时
    除数撞 `Eps=1e-6` 夹取，通道 2 的 numpy 与 GL 在那个点可差 1–2 码值。
    要坐实就单看那 2 格的 (fg,bg) 坐标；本轮不追（真实草稿 0 个 mix 段，
    且 α=1 那条是逐字节全等）。
- **对 P-62 那句"9/10 + 1 跳过"的就地更正**：跳过不是机制的反例，而是仪器挑错了函数；
  挑对之后同一腿仍是 9/10 容差内 + color_dodge 2 格 2 码值。
  "机制与模式无关"现在由 **10 个模式的 α=1 全等 + 9 个模式的 α=0.5 容差内**共同撑着，
  剩下的口子只有 color-dodge 那 2 格。
- **证据等级**：α=1 全 10 模式等价**已验证**；α=0.5 的 9/10**已验证**；
  color_dodge 那 2 格**已观测、机制未证**。仪器取名法已改，`fn_src` 常驻读数。

## P-64 2026-10-25 交接：下一轮要跑的三条命令与一条踩坑提醒（写在这里，别让下一个人重新推导）

- **跑门一定要带 `--shot-times`**。门的**默认**时刻表含 `6.633`，那是 `向上闪入` 白闪衰减窗
  （P-61：通道 2 完全离线同刻也只有 0.877@64），拿默认表跑会多出一条与本轮改动无关的 L10 红。
  历史上可比较的绿跑用的是 `--shot-times 1.0,7.0,12.0` 或 `1.0,6.7,6.85,7.2,12.0`。
- **混合模式三条腿都可单独重跑**（都不依赖本会话的记忆）：
  ① `python scripts/mixmode_shaders.py` 重切出厂件；
  ② `python scripts/mixmode_browser_check.py --carrier temp/playback-test/model-proxy-a.json`
     真浏览器接线 + 反 fixture（ASCII 标记 `MIXMODE_BROWSER_WIRING ok`，判据带分母）；
  ③ `python scripts/mixmode_opacity_reference.py` 重生不透明度参照表（逐字节复现 P-62/P-63 的判据）。
  网格级两通道等价在 `temp/playback-test/mixmode-pixi.html?modes=<10 个切片名>`。
- **下一件实事是 #14 `向上闪入`**（L10 唯一红的成因）：读该包 lua 的语义 → 先在通道 2 做亮度项
  → 用 `animation_region_check` 的同刻同帧号 MAD 判 → 再两通道 + 复跑门。
  **禁止**为了变绿去动 0.9 阈值或把 6.633 从时刻表里删掉。
- **待用户决定的四项**（不是我能替判的）：≤2 GB 判据口径（U-79）、
  单子字幕轨成片 fixture 的写回/导出授权（U-95 与"混合模式在真人数据上"的验证都卡在这）、
  `blendAlphaState` 走 PreMul 还是 Straight 支（U-90）、以及两仓库改动的提交许可。

## P-65 2026-10-25 检查 #14 的计划，结果是把计划本身改写了（F-095）

用户让「检查下一步计划」。检查的方式不是复述计划，而是**先验证计划的前提**——
#14 写着「读该包 lua 的语义 → 先在通道 2 做亮度项（模糊可后置）」，两条前提一句话没验就开工，
正是这条线上犯过多次的毛病（[[check-own-spec-before-claiming-discovery]]、
[[feedback-metric-sensitivity-before-no-effect]]）。

- **前提①「lua 里读不到，要脚本运行时」——错**。包里 `SeekModeScript.lua` 就带明文
  `ae_attribute` 关键帧表（6 条 `ADBE_*`，每条 = 贝塞尔 + 帧区间 + 值区间），
  `seek()` 只做 `t = mod(time, dur+1e-4)/(dur+1e-4)` → `AEprogress = t*21/49` → 查表。
  新仪器 `scripts/ae_keyframe.py` 机械解析并按 lua 原文求值，覆盖率自证 6/6 属性、帧区间首尾相接；
  `21/49` 与 `1e-4` 都是从源码正则取出并断言存在（不誊写）。
  同族本机 **7/69** 个包有这张表——`animation_tiers.py` 的 `AE_MARKS` 只认
  `.lsanim/.lsproj/.jsdat` 扩展名，所以 CSV 里 `ae_export=0`：**那是标记集缺口，不是"没有 AE 导出"**。
- **前提②「duration 用它自己的」——由成片否掉两种写法**：段起点 6.600 = 帧 201（固定 lead +3）。
  用 `duration=0.3`（草稿 ref 的 300000 µs）则 E 在 0.3 s 归零、与成片 210 帧后平在 104 吻合；
  用包内 `extra.json animation_duration=0.7` 则 t=0.33 处 E 仍 1.10，不可能已经平。
  **而 lua 字面的 `mod` 会循环**（t=0.333 折回 0.033 ⇒ 帧 211 该再闪一次 E=1.74），
  实测 211..227 全平 ⇒ 入场动画结束后引擎不再驱动/夹紧，**我们实现时不能照抄循环**。
- **前提③「模糊可后置」——由梯度否掉**。帧 201 的垂直梯度 **0.40**，常帧是 **7.2~8.9**：
  那一帧被抹成近乎均匀（`Gaussian_Blur` 垂直强度 300→0 走完窗口前 71%），
  亮度只解释"有多亮"，不解释"没有结构"。同窗还叠着 `Position` y 1050→540（前 0.114 s 的向上滑入）、
  `Displacement_Map` 75→0、`Scale` 103→100。
- **成立的那半**：只看曝光、`duration=0.3`、不循环，`base·2^(E/2.2)` 对成片 202..210 的残差
  最大 **14 码值**（摆幅 137 码值 ⇒ ≈10%），衰减常数对得上；峰值帧 201 预测 187.8 实测 242.11，
  少的 54 码值正是"还要加模糊/加性项"的方向。⇒ **曝光律已被成片验证**；
  `GetVal` 的手移植**未经执行验证**（本机无 lua/luajit/lupa），这条要写进等级里，不能含糊。
- **计划改成什么**：#14 的真实成本不是"一个亮度项"，是"一段上的 5 条律 + 3 次 RT pass"，
  而这条族的**曲线读取**今天已经打通。所以顺序改成：
  ① 用 `ae_keyframe.py` 把 7 个同族包的曲线全解出来（廉价、复用面大）；
  ② 在**这一帧**上判定哪条律承重——判据是"梯度"这种可测的形态量，不是"加了像不像"；
  ③ 只把承重的 1~2 条接进通道 2（曝光已经够格；模糊要先读 `GaussianBlur.frag` 定 `u_Strength` 的量纲）；
  ④ L10 的 6.633 在此之前**照旧记红**，不动阈值、不删时刻。
- **本轮不做的事**：不实现 RT 链（13 轮预算内做不完，半途接进渲染器比不做更坏）；
  不动 `animation_tiers.py` 的 CSV 除非改标记集后重跑（改标记集 = 已排入，见任务清单）。

## P-66 2026-10-25 承重律判出来了（F-096），并且第一版仪器是两个坏读数而不是产品差

- **一句话**：`向上闪入` 这一窗里，**曝光**解释亮度（r=+0.9329，置换 0/200），
  **垂直模糊**解释结构（r=−0.7901，且 `1/(1+k·X)` 单参数下垂直 rms 0.0404 比水平 0.0917 好 2.3×），
  而 lua 字面的 `mod` **循环**在窗口外被成片否掉：夹紧 mse **0.3** vs 循环 mse **2040** 码值²。
  复跑：`python scripts/flash_attribution.py --report temp/playback-test/flash-attr.json`（约 30 帧解码）。
- **第一版的两个坏读数都要认账**（都不是播放器差）：
  ①`--lead 3` 解析了却没用 ⇒ 切点取成 198，把三帧常亮帧当"闪的开头"，亮度 r 冲成 **+0.0122**
  （置换 0.960）。看起来像"曝光律不成立"，其实是帧号错位。**死参数的代价是一轮误判**。
  ②基线取"末 6 帧"，而 `--post 14` 时末 6 帧（207..212）还在衰减尾巴里 ⇒ 基线 108.53 vs
  干净 104.54，残差整体抬高。现在基线只收 `t >= duration + 0.2 s` 之外的帧并报帧数。
- **判据选型的一条正例**：整帧相关看不了这一层（F-072），"两条都单调所以相关"也没有信息量
  ——真正定性的是**各向异性**：静态图 gradV≈gradH（7.44/7.34），窗内却只有**垂直**那条拟合得动，
  这是包内 V=300→0 / H=8→0 的独立预言，也是"形态量比均值敏感"的具体形态。
- **仍未做的**：峰值帧少 55 码值（201 预测 186.8 / 实测 242.1）未归因；位置 1050→540、
  位移噪声 75→0、缩放 103→100 三条**未判**（要该层独立质心，本窗拿不到）；
  `GaussianBlur.frag` **未读**——但 `gradV_ratio=1/(1+0.0552·V)` 这条经验式给了反向定 sigma 的路，
  所以下一步不必先啃 frag。
- **门的状态没动**：全门 21/22，L10 的 6.633 仍红；本轮**没有**为了变绿改阈值或时刻表。
  现场：无残留 python/chrome，草稿 `draft_content.json` mtime 仍是 2026-10-15 17:03（未写）。

## P-67 2026-10-25 曝光项进通道 2：窗内 9 帧全改好、0 帧变坏、预切点逐字节不动（F-097）

- **做了什么**：`render_frame.py` 接 `ae_exposure_at` + `apply_exposure`（逐字照
  `Exposure.frag` 的 `pow 2.2 → ×2^E → pow 0.454545454545`），只在 `depth==0` 做一次全画布后处理。
  判据不是"看着像"，是**同刻开/关 A/B**（`scripts/flash_channel2_ab.py`）：
  窗内 **9/9 帧 MAD 下降**（201：138.71→107.04；204：54.93→28.36），**0 帧变坏**，
  窗外 7 帧**逐字节相同**（这就是"没有误挂到别的时刻"的证据，等价于 L8 那条窗外不变的判据）；
  预切点 3 帧 mean 位移 **0.000 码值**（阴性对照）；降级 **0/16**。平均 MAD 34.98→24.35。
- **支路归属由残差判，不由默认值判**：`--gamma 1.0`（gamma 空间直乘）rms **100.6** vs
  线性光 rms **19.1**。`Exposure.material` 的 `use_linear_light: 0` 只是旁证。
- **结构项（垂直模糊）故意留着不做**：开了曝光后我们帧 201 的 gradV 是 **6.64**，成片 **0.40**
  ——变亮没变糊，正是第二条承重律缺席的签名。为什么不能顺手接：经验式
  `1/(1+0.0552·V)` 的 `base` 是**成片稳态帧**的梯度，渲染器一次只出一帧、**不知道自己窗口基线**，
  所以要先按我们自己的稳态帧标定 `sigma → gradV`（`GaussianBlur.frag` 仍未读，不能猜量纲），
  再逐帧反解。中途加过 `AE_BLUR_K`/`AE_VBLUR_ATTR` 两个常量，因没有可用标定步**已撤回**，
  不留无消费者的脚手架。
- **又踩了一次"管道吃掉退出码"**：第一次跑门我写了 `… > log 2>&1; tail -6 log` 并放后台，
  通知报 exit 0，我差点当成"门全过"。实际是门**参数不全直接 argparse 报错**（要
  `--plain/--draft-root/--timeline`），而整条 shell 的退出码来自末尾的 `tail`。
  这和 P-62 那条 `| tail` 是同一个坑的**第二个形态**：后台命令末尾接任何读文件/echo，
  都会把被测程序的退出码换掉。**规矩**：跑门只写门本身，退出码用 `echo "GATE_EXIT=$?"`
  **单独**取（且放在同一命令里而不是接在 tail 之后）。正确调用式已按 line 656 那条重跑。
- **下一步**（#14 剩余）：①稳态帧标定 `sigma→gradV`，再按 `1/(1+kV)` 反解逐帧 sigma 接垂直模糊；
  ②同一律接浏览器通道（Pixi 侧要做全画布后处理，是新欠口）；
  ③把 `flash_channel2_ab.py` 做成常驻门层（判据形态=窗内改善计数>0 且窗外逐字节相同且阴性对照通过）。

## P-68 2026-10-26 #14 步骤①判完并落进门；但用户两次现场反馈把仪器的盲区掀开了（F-098）

用户先说「你现在播放都是一顿的一顿的」，后说「把预览的音频录下来再检查，现在很奇怪」。
两条都不是新缺陷的**报告**，而是我们**判据看不见**的证据。本轮三件事。

### 一、#14 的垂直模糊项：判据通过，但中间那一版是我自己写坏的

- 计划步骤①（把 `1/(1+k·V)` 反解成逐帧模糊）已落地在 `render_frame.py`：不猜 `u_Strength` 量纲，
  改成**在我们自己这一帧上**试半径阶梯、取第一档达到目标比值的半径；`GaussianBlur.frag` 仍未读。
- 首版阶梯（0..24 单趟）在峰值帧够不到目标（V=300 要 17× 抑制，单趟上限只有 3.5×），
  而循环的早退写法是「够不到就一档不动」⇒ **最该糊的三帧（201/202/203）实测比值 1.000**，
  完全不糊。改成「第一档达到即停；整条阶梯都不够则重复最强一档（sigma 合成）」。
- 我中途还引入过一个**反向缺陷**：改成「取最接近目标的一档」后，选中了目标**之上**的那档，
  而我新加的重复循环条件是 `got > want` ⇒ 于是从"差一点"一路重复到最强档，206 帧过糊
  （预测比值 0.767、实测 0.308，MAD 16.0→21.7 变坏）。**这条已改回单调规则**：
  阶梯单调，就取第一档 ≤ 目标；够不到才叠加强度。判据形态本身（"糊变坏=0"）就是它被抓到的原因。
- 三臂同刻 A/B（`off`/`expo`/`both`，`scripts/flash_channel2_ab.py`，成片固定帧号）：
  **曝光 9 改好 / 0 变坏 / 7 持平；模糊 6 改好 / 0 变坏**；平均 MAD
  **off 34.51 → expo 23.89 → both 21.26**；预切点 3 帧 mean 位移 0.000、gradV 位移 0.000（阴性对照）；
  降级 0/16（分母报出）。峰值帧 201：MAD 137.8→94.7，gradV 5.44→1.41（成片 0.40）；
  **202 帧（= L10 的 6.633）gradV 1.41 vs 成片 1.19，结构这一项已经对上了**。
- 仍未归因：峰值帧成片均值 242.1 而我们 146.4 —— **还差 ~96 码值**，曝光×模糊都不解释
  （模糊是保均值的线性算子）。这是「向上闪入」里一个**加性项**（候选：包内 RT 链上还有一趟
  白色叠加/位移噪声），不是量纲问题。

### 二、门从 22 项到 24 项：L11 常驻 + 一条判尾部的帧预算层

- **L11 flash in/out A/B**（计划步骤③）已挂进 `playback_check.py`，判据是形态而不是数字：
  窗内两项各自单变量（曝光看 `off→expo`、模糊看 `expo→both`）**变坏=0**、窗外逐字节位移=0、
  降级=0 且报分母、**窗内必须同时看见曝光项和模糊项**（否则表里那条
  `ADBE_Gaussian_Blur_2_0001_2_3` 丢了这个层也不会红——空判据）。本轮读 **PASS**（16 帧，
  窗内 9：曝光 9 / 模糊 7）。
- 全门 2026-10-26 读数：**22/24**。两个红的归因：
  ①`L10 t=6.633 跨通道 0.889(<0.95)` —— 是**预期**的：通道 2 现在有闪、浏览器还没有（就是步骤②）。
  同刻**对成片** 0.877 → **0.898**（没动阈值、没删时刻）。
  ②`L8 typewriter wiring` —— 该层用 solo 模型（只放那一条字幕）出帧，**闪段不在里面**，
  所以不是我这次改动碰的；读数 `R_k=[-1,582,626,674,720]` 里第一个是 **−1（k=1 无墨）**，
  标定自身退化 ⇒ 是那条层自己的取景/`band()` 行窗问题，**未结案**（我先前的"同刻干扰"猜测是错的，
  solo 模型否掉了它）。
- 新增 **L4 frame budget (whole timeline, tail not mean)**：跑完整条时间轴一遍，判
  `p95 ≤ 33.4 ms`（30 fps 一帧）与 `max ≤ 150 ms`，并把「重复上一帧次数」和「新帧速率」一起报出来。
  阈值按产品口径定，不是照某一轮读数反推。

### 三、用户的两条现场反馈，量出来是这样

**卡顿**：第一次把**每帧从取数到画完的耗时按播放头**记下来（`frame_cost_ms`，整条 36.8 s，n=1109）：
p50=1 ms、p90=5–9、**p95=26–33、max=146–327 ms**，>33 ms 约 5%、>100 ms 6–7 帧。
而门一直报「median 29.27 fps」——两个理由使它看不见：①`composited_fps` 是**帧数÷墙钟的均值**，
一帧 1.2 s 的停顿摊进均值只剩 0.03 fps；②电池只跑 10 s 还带 seek，最坏那十帧落在 5.7–16.4 s，**从没被覆盖**。
整条时间轴单独跑，均值就只有 **21.73 fps**（rt 0.934、补帧跳过 29）。
最坏 10 帧里 **9 帧的 cost≈pump 等待**（131/131、120/119、107/106）⇒ 冻住的是**等解码帧**，不是画。
「段头假设」被否：只有 3/10 落在段头 50 ms 内（67 个段头/36.8 s 下随机也该 ~18%，不足以定）。
成因写在代码里：`takeFromPump` 的预算只在"队列仍然为空"时检查，所以一帧花 124 ms 送到时
**照样算命中并返回**，屏上明明已有画面却把循环冻住；超时那条还接一路 `sink.getSample()` 同步随机解码
（327 ms 那帧 = 101 押注 + ~226 同步解码）。修法=已有画面时给**等待本身**设上限并重复上一帧
（`&hold=0/1` 单变量开关）。**这轮 A/B 还定不了结论**：同一 hold=1 配置两次跑出
max 883 ms（fps 25.24、holds 193）与 max 151 ms（fps 29.9、holds 89）——n=1 不能判，需 `--repeat ≥3`。

**音频**：按用户的办法把预览**录下来**判（`player.html` 的 `startCapture` 旁路 tap →
网关 `/wave` → `scripts/audio_capture_check.py`）。为什么必须另起一路：现有 `peak_fs/rms_windows`
是 analyser 在 JS 循环里**轮询**取的，循环一冻几百 ms 缺席的正是这些采样——
**自报数字会被"它想测的那个故障"本身破坏**（和上面 fps 同一条教训）。
录到的是连续 37.21 s / 48 kHz / mono Int16（436 个 4096 样本块，块数×块长 = 墙钟，无缺块）。
读数（口径都写清楚）：

| 量（0.5 s 窗 RMS） | 预览录音 | 原生成片 |
|---|---|---|
| 最大窗 | −17.71 dBFS | −7.77 dBFS |
| 中位窗 | **−31.74 dBFS** | **−10.58 dBFS** |
| 有声占空比(>−40 dBFS) | **23.4%，100 个碎段（0.05–0.2 s）** | 连续（无静音段） |
| 削顶样本(float 域 ≥0.9995) | 22 | **7629**（峰值 +2.98 dBFS） |

包络相关（100 ms 窗、dBFS 域、±10 s 搜滞后）最佳只有 **0.096 @ +2500 ms** ⇒ 预览的响度轮廓
**根本不跟着成片走**。而"预览比成片低 21 dB"不是电平问题：**源就是碎的**——对照①这些片段自己的
占空比是 **1.0 / 0.69 / 1.0 / 0.75…且各只有 1 段**（连续），源峰值 −4.6~−5.7 dBFS；
对照②成片同一条时间轴是连续的 −10.58 中位。⇒ **交付被切碎**，不是增益律、不是限幅。
这条把 U-78/U-86/U-88 的前提改了：那些 `peak_fs` 离散度都是**在同一条碎流上取样的统计量**。

- **就地更正 F-073 的一条口径**：原记「成片 |x|≥0.9995 的样本 = 0、母带峰 −0.026 dBFS」是
  **解到 s16 的夹取口径**；ffmpeg 解 AAC 到 **f32 不夹取**，同一条音轨实测 7629 个样本 ≥0.9995、
  峰值 **+2.98 dBFS**（夹到 s16 边界 0.99995 的口径是 7594 个）。⇒ "削顶不是剪映的常态"这句
  **要带口径重述**：成片在浮点解码域本来就超满刻度，播放器输出会夹。U-78 的结论方向不变
  （我们不该主动压增益），但它引用的"成片 0 个削顶样本"不能再当无条件事实用。
- 仪器侧新事实（都进代码注释了）：①headless 与 Qoder 内置浏览器里 **rAF 一帧都不发**
  （`raf:false, frames:0`；实测 pos 45 s 不动、`paint` 从未进入）⇒ 真实帧节奏**目前无法自动测**，
  只能用同一 `paint()` 的电池路径取"每帧耗时"作代理；②网关按 tag 分文件写报告
  （`report-<tag>.jsonl`），我这次先读错文件、把一次成功的录音判成"没回来"；
  ③`tasklist | head -8` 截断让我误判"门挂了"——**缺席结论要证扫描覆盖**（本轮又犯第二次）。
- 下一步（按性价比）：①把音频**提前排入队列**（look-ahead），排期不靠每一帧的循环——
  这是碎流的直接修法，判据就用已经建好的录音通道量「占空比↑、碎段数↓、包络相关↑」；
  ②`hold` 的 A/B 补到 `--repeat 3` 再判；③L8 typewriter 那条 −1 无墨的取景问题单独归因；
  ④步骤②（闪的曝光/垂直模糊进浏览器）——它同时是 L10 6.633 那条红的正解。











## P-69 2026-10-26 音频这条：我提出的两条解释都被自己的实验否掉；站住的是「律对、浏览器交付不对」

顺序要如实写下来，因为每一步都是**仪器先错**：

1. **否掉「批间隔排期」**（P-68 里我写的 `at = Math.max(when, actx.currentTime)` 成因）。
   给 `flush()` 加夹取计数后跑一遍：274 个节点、5115 个 chunk，但**夹取只有 9 次、合计 1.4 s**
   —— 而录音里「成片有声、我方静音」合计 **23.0 s**。**夹取解释不了 94% 的静音。**
2. **否掉「批长 0.5 s 太短」**：把批长做成 `&audio_slot=`（0.5 = 旧口径）跑三臂，**方向相反**：
   0.5 s 占空比 35.0%，2 s 掉到 **10.3%**（窗中位 −93.6 dBFS），4 s 掉到 **8.1%**（−140 dBFS，几乎全哑）。
   攒得越多越不出声 ⇒ 不是排期节奏问题。**默认值已改回 0.5**，只留开关。
   若照 P-68 的思路直接动手做 look-ahead，会把预览做成哑的——这条要记进「猜错的修法比不修更坏」。
3. **P-68 那句「82/82 缺失段起点落在音频轨 span 内」是过度解读**：三条音频轨 span 的**并集覆盖
   36.8 s / 36.9 s 整条时间轴**，所以「落在 span 内」恒真、零信息量。分母口径要先问
   （[[feedback-prove-scan-coverage]]，这次是我自己踩的第二次）。
4. **站住的那条：律对、浏览器交付不对**（`temp/playback-test/mix_law_probe.py`，不碰浏览器：
   用模型的 `segments[].volume` × `loudnesses[]` + 淡入淡出，把 **37/37** 条音频段的源解码后按
   时间轴相加，量同一条包络）：

   | 口径（0.5 s 窗） | 离线合成（我们的律） | 浏览器录音（两次独立复现） | 原生成片 |
   |---|---|---|---|
   | 有声占空比（>−40 dBFS） | **92.5%** | **34.7% / 35.2%** | 98.9% |
   | 窗中位 | **−18.66 dBFS** | **−30.3 / −30.3 dBFS** | −10.58 dBFS |
   | 窗最大 | −8.56 | −19.2 / −17.7 | −7.77 |
   | 样本峰 | 1.694 | 0.916 / 0.924 | 1.410 |

   ⇒ 律这边密度基本是对的（92.5% vs 成片 98.9%）；**浏览器只把约 1/3 的音频真送到输出口**，
   且比离线合成再低 ~12 dB。两条独立缺口：交付少 ~58% 时长；电平即便交付修好也还差 ~8 dB。
5. **U-88 那半边钉住了一半**：离线合成中位 −18.66 vs 成片 −10.58 ⇒ 交付修好后仍差 **~8 dB**，
   而离线合成的峰 1.69 已超满刻度，**不可能靠一条全局 master 增益补齐**（会更削顶）。
   所以这 8 dB 更像成片侧另有一层**导出期响度目标**（草稿字段里没有记录）——
   正是 U-88 留的「需要先确认剪映是否还有一层全局响度目标」。
   现在有了量级：差的不是「有没有声音」（占空比已 92.5%），而是「整体推多少」。
6. **交付为什么少 58%：未结案。** 候选按「能否一刀分开」排，下一个实验必须先挑一个能区分的：
   ① **节点寿命**：`stopAudioJob` 在段尾 0.5 s 后打断 `for await`，若该段的泵还没排完就被打断，
      尾巴整段丢。判法：每段记「排完 / 被打断」并把秒数记账（分母 = 该段应有的秒数），
      把「被打断丢掉的秒数」直接和 23 s 对账。
   ② **增益自动化把节点压成 0**：`gainAt()` 的淡出阈值用 `segDur`（目标时长）而 `localT` 从
      `mediaStart` 的偏移起算，两者不等长时会在段中就 ramp 到 0。判法：把每段的 gain 曲线打表，
      与离线合成用的同一条式子逐段对数。
   ③ **池驱逐**：`pool=4` 且音频自己开流（own=true）时 LRU 是否中途换掉音频流
      （本轮 `audio_errors=0`，但 hold/release 账没打出来）。
   **禁止**在现有证据下直接动手：①②③的修法互不相同，猜错就是把另一个缺陷固化
   （[[feedback-research-before-code]]）。


## P-70 2026-10-26 音频碎流的排除链：五个成因被我用自己的实验否掉，现在定位到**图内的增益**，不是调度

P-69 说"交付少 58%"，但**交付账本身不支持"少交付"**。这一条把账目补齐，并记下五次否证
（每次都是先提出的解释被自己的下一个实验打死，顺序不要倒过来读）：

| 候选成因（我先后提出过的） | 判它的实验 | 读数 | 结论 |
|---|---|---|---|
| 排期被 `Math.max(when, currentTime)` 夹成静音 | 给 `flush()` 加夹取计数 | 275 批里**夹取 9–11 次、合计 1.4 s**，而静音 23 s | **否** |
| 批长 0.5 s 太短，攒久一点再排 | `&audio_slot=` 三臂 0.5 / 2 / 4 s | 占空比 35.0% → **10.3% → 8.1%**（方向相反） | **否**，默认已改回 0.5 |
| 泵被 `stopAudioJob` 打断、尾巴整段丢 | 每段秒数账（`exp_s / sched_s / lost_s / interrupted_jobs / dropped_samples`） | jobs 70、**应有 118.6 s / 排出 119.5 s**、lost 0.2 s、**interrupted 0、dropped 0** | **否**，一秒都没少交付 |
| 限幅支路把响的压成泵动 | `&comp=0` 旁路整条 DynamicsCompressor | 占空比 33.3% vs 33.9%、窗中位 −30.85 vs −32.53 | **否**，一模一样 |
| 代理文件里塞的是静音（素材缺） | 逐个代理解 a 轨量峰/占空比 | 25 个视频代理里 **18 个有真实响音**（峰 1.18–1.38、duty 0.997），4 个静音、3 个无音轨 | **否**（但记下 4+3 这 7 个是真实素材态） |
| 我们的混音律缺一层 | Python 按 `segments[].volume × loudnesses[] + 淡入淡出` 离线合成 37/37 段 | 占空比 **92.5%**、窗中位 **−18.66 dBFS**、峰 1.694 | 律基本对，但**仍比成片低 ~8 dB**（U-88 那半边） |

**剩下的定位**：浏览器自己报的**每一批排进图时的 RMS** 平均 **0.0429 = −27.4 dBFS**
（275 批里只有 59 批 < −80 dBFS，占 21.5%）。也就是说：东西都排进去了、也没被打断，
但**图里那一份信号本身就只有 −27 dBFS 这一档**，而同一批文件按同一条律在 Python 里加出来是
−18.66 dBFS 中位。⇒ **差在浏览器侧的增益施加（每节点 `g.gain` 的 setValueAtTime/ramp 那一段），
不在调度、不在限幅、不在素材。**

**下一条实验（先定好再动手，别再猜）**：逐段把"浏览器排出那一批的 RMS"与"Python 同一段的 RMS"
配成对，看 Δ 的分布——
· 若 Δ 是**一条近似常数**（全体低 ~8–12 dB）⇒ 图里有一层我们没算的全局因子
  （候选：多个并发 BufferSource 的求和方式、`master` 的默认值、`createBuffer` 的 rate 与
  `actx.sampleRate` 不一致导致的重采样口径）；
· 若 Δ **按段分档** ⇒ 是 `gainAt()` 的淡入淡出/`localT` 起点算错（`segDur` 用目标时长，
  `localT` 从 `mediaStart − source.start_us` 起算，两者不等长时会提前 ramp 到 0）。
两种情况修法完全不同，**在拿到配对分布之前不许改渲染器**（[[feedback-research-before-code]]）。

**仪器侧两条要复用**：①`ScriptProcessorNode` 的 `onaudioprocess` **在主线程**回调，
所以它量的是"图算出来的东西"，不能用来判主线程卡顿——两件事要分开测；
②录音判据的"有声/静音"阈值（−40/−50 dBFS）本身是**一条口径**，电平整体偏低时它会伪装成"碎流"。
本轮我先把它读成交付缺陷，就是吃了这个亏：**先问阈值的分母，再命名缺陷。**


## P-71 2026-10-26 音频这条结了：`copyFromChannel` 的第三个参数是**源偏移**，不是目的偏移——我们每批都在跳着读自己的音频

P-70 的排除链把五个成因都否掉之后，剩下能解释「都排进图了却只有 −27 dBFS」的只有**填进去的数据本身是零**。
把浏览器每批的 RMS **按段配对**（同一 `media_start`、同一秒数，Python 现解同一段作参照）之后，
形状自己跳出来：同一段里逐批 RMS 单调掉 **0.0322 → 0.0301 → 0.0132 → 0.0132**
——正好是「每批多跳过 `filled` 个样本、读到数组末尾补零」的样子。

**根因（一行）**：`buf.copyFromChannel(ch[c], c, filled)`。
mediabunny 的签名里第三个参数是**源**的起始偏移（`copyFromChannel(dest, channelNumber, startInChannel)`
的语义在它的 `AudioData` 上指源），旧写法把它当**累加器的目的偏移**传，
于是第 2 批起就从源的 `filled` 处开始读、写进 `ch` 的 0 位附近 ⇒ 累加缓冲里越往后越多零。
修法是不再依赖参数语义：**先把本批完整读进 `tmp`，再 `set` 到 `ch` 的 `filled` 处**
（`&copyfix=0` 保留旧写法做单变量对照）。

**A/B（同 build、同缓存、只改这一个开关，整条时间轴各一遍）**：

| 口径 | copyfix=0（旧） | copyfix=1（修好） | 成片参照 |
|---|---|---|---|
| Δ电平中位（逐段配对，浏览器 vs 同段现解） | **−20.89 dB** (n=61) | **−3.05 dB** (n=69) | 0（定义上） |
| 近零批 / 总批 | 59 / 283 | **8 / 279** | — |
| 录音 0.5 s 窗中位 | −30.64 dBFS | **−13.88 dBFS** | −10.58 dBFS |
| 录音 0.5 s 窗最大 | −17.76 | **−7.84** | −7.77 |
| 录音有声占空比 | 35.0% | **93.0%** | 98.9% |
| 「成片有声我方静音」 | 79 段 / 22.8 s / 61.8% | **1 段 / 2.1 s / 5.7%** | — |
| 视频侧（确认没连带伤） | fps 29.51 / p95 12 ms | fps 29.68 / p95 12 ms | — |

剩下那 1 段 2.1 s 就是时间轴结束后的尾垫（36.83 s 之后），不是缺陷。
**用户报的"很奇怪"到此有了闭环**：不是电平律、不是限幅、不是排期、不是素材，是**解码数据被逐批跳过**。

**新opened的问题（不要当已修）**：修好后录音**样本峰到 1.0000、削顶 325 个**，而中位仍比成片低
**3.3 dB** ⇒ 现在才真正进入 U-78/U-88 的议题：满刻度余量与全局响度目标。
此前这两个议题的所有读数都是在一条**低 20 dB 的碎流**上取的，全部要重测才能引用。

**方法教训（两条，都进 memory 级）**：
1. **聚合量会伪装成缺陷**：「占空比 35%」我先是当成"交付碎"，其实它是"电平低 20 dB 被 −40 dBFS
   阈值切出来的形状"。真正定位的是**按段配对 + 时长加权的每批 RMS**——先有逐段身份，才有形状。
2. **排除链本身是产出**：夹取(9 次/1.4 s)、批长(越攒越哑)、泵寿命(0 打断 0 丢)、限幅(旁路无差)、
   素材(18/25 有真响音)、字节传输(8/8 与磁盘逐字节相同)——六次否证把搜索面从"混音律"收窄到
   "填充路径"，一行 bug 才找得到。**先按顺序否，再动手**，比先改一版试试看便宜得多。


## P-72 2026-10-26 修好音频之后复跑全门：21/24，新加的帧预算层自己变红（p95 过了、max 没过）

全门（`--repeat 1 --shot-times 1.0,6.633,7.0,12.0`，音频 `copyfix` 已默认开）读数：

- **L4 帧预算（整条时间轴、判尾部）= FAIL**，但要点分开看：
  **p50=1 / p90=11 / p95=13 ms** ⇒ 33.4 ms 那条**过**（修 `hold` 之前是 26–33）；
  **max=252 ms** 不过 150 那条。最坏三帧 `[252@13.61s 等 251]`、`[179@25.33s 等 174]`、
  `[136@6.61s 等 118]`——**三帧全是等解码帧，不是画**。
  `重复上一帧 96 次`、`新帧 48.41/s`、fps 29.63 ⇒ hold 确实在生效，
  而且 p95 从 26–33 掉到 13 是它的账。
  **为什么 max 还是 250 ms**：hold 只在"这一段屏上已经有画"时才允许重复上一帧；
  一段**刚开始**的那一帧没有画（`sprites.get(id)._bmp` 为空）⇒ 走 FIRST_BUDGET=120 ms
  加同步 `getSample()` 那条腿。而一帧的耗时是**所有在场段里最慢的那条腿**
  （`Promise.all`），所以一个刚起头的段会把整帧拖住 250 ms。
  这不是回归——**这条判据是今天才加的，以前没有任何一层会因此变红**（同族规约：
  新渲染路径必须有自己的门层；这条是新**流畅度**路径有自己的门层）。
  下一步要动的形状：让新段的"第一帧"不阻塞整帧（先用别的段画这一帧，新段到货再补上），
  代价是那一段晚一帧出现——**这是产品可见的变化，先与用户确认再动**。
- **L10 = FAIL（三条，与 P-68 相同，未动阈值）**：t=1.0 跨通道 0.945（<0.95，n=1 的边际）、
  t=6.633 跨通道 0.889（通道 2 有闪、浏览器没有 ⇒ **计划步骤②**）、
  t=6.633 对成片 0.898（<0.9，差 0.002；峰值帧仍缺 ~96 码值的加性项，见 P-66/P-68）。
- **L8 typewriter = FAIL（未结案）**：读数形状 `R_k=[-1, 582, 626, 674, 720]` 而开动画右边缘
  `[720,720,720]`。`R_k[0] = -1` = **标定第 1 个字时窗内无墨** ⇒ 是这条层自己的行窗/取景问题
  （`band()` 用 `font_size` 推的上下边界），不是打字律坏了，也不是今天的模糊改动
  （该层用 solo 模型，闪段根本不在帧里——P-68 已就地更正过一次）。
- **L11 flash = PASS**（16 帧、窗内 9：曝光 9 / 模糊 7，四项计数全 0）。
- **音频侧的连带后果要如实记**：`L5 mixer` 仍 PASS（0 错），但 INFO 现在读
  **peak_fs 1.2556、1/1 跑有满刻度窗**——这是**修好 20 dB 之后的正常结果**：
  我们第一次真的把满电平混音送出去了。所以 U-78/U-86/U-88 之前所有"削顶/电平"读数
  都是在低 20 dB 的碎流上取的，**一律作废重测**（已开任务：修好后的流上重取 n≥3）。
  内存这条也没变差：rss_mean 790 / peak 915 MB。

**门为什么从 22/24 变 21/24**：不是退步——今天加了两层（L11 与 L4 帧预算），
分母从 22 涨到 24；新加的帧预算层第一次跑就抓出了 max=252 ms，
而那正是用户报"一顿一顿"的形状。**判据变严会让表上多一条红，这是产出不是回归**。


## P-73 2026-10-26 计划步骤②落地：入场动画的曝光+垂直模糊进浏览器，L10 的 6.633 两条腿一起过

**做法（不产生第二份数学）**：新脚本 `scripts/ae_table_export.py` 用**通道 2 同一个解析器**
（`ae_keyframe`）把包内明文 `ae_attribute` 表按 1/30 s 步长采样成 `ae-curves.json`
（读数：1 个包可求值 / 10 个不可求值并点名 / 覆盖 1 段），浏览器只查表插值。
导出侧打印 `AE_TABLE_EXPORT packages=1 degraded=10 segments=1` 给门当分母。

**曝光这条腿先证成"就是一个 γ 空间增益"**：`pow(v,2.2)·2^E` 再 `pow(1/2.2)` 与 `v·2^(E/2.2)`
在 0..255 全部 256 个输入上 **maxΔ = 0.000000 码值**（E=1.83/1.7383/1.0/0.3 四个点都核过）。
所以浏览器用内建 `ColorMatrixFilter` 的对角阵即可——**不自建 sampler**，正是避开 F-093 那条
"自定义 sampler 名一律不绑定"的坑。

**模糊这条腿的 k 是标定出来的**（五臂扫 `&aok=`，同一时刻只改一个量）：
浏览器 `ratio(px) = 1/(1+0.1273·px)`（aok=0.05 ⇒ px=6.65 ⇒ 比值 0.541），
对齐目标是**通道 2 实际达到的** gradV，不是理论值：
浏览器只曝光 gradV=7.128、通道 2 只曝光 gradV=7.109（**两通道基线差 0.3%**，
这本身就是"画面同源"的独立证据），通道 2 曝+糊后 1.407 ⇒ 需要比值 0.197 ⇒ px=31.9 ⇒ **k=0.2398**。

**读数（同刻 t=6.633）**：

| 量 | 改前 | 改后 | 判据线 |
|---|---|---|---|
| 浏览器 vs 通道 2（跨通道） | 0.889 | **0.9880**（本地代理口径）/ 门内 4 点均值 0.987 | ≥0.95 |
| 浏览器 vs 成片 | 0.898 | **过**（本轮 L10 该时刻两条腿都不再报问题） | ≥0.90 |
| gradV / gradH（曝+糊后） | — | 浏览器 1.790 / 4.120，通道 2 1.407 / 4.018 | 观测 |

`&ao=0` 留了旁路开关，`blurX=0` 经测量确认**确实只糊垂直**：两通道 gradH 只差 2.5%，
若浏览器两轴都糊，gradH 会明显低于只糊垂直的通道 2。
残余：浏览器 gradV 1.790 比通道 2 的 1.407 **略欠糊**（k 偏低约 0.05），
且两者都还没到成片的 1.19——**这条是"两通道一致"，不是"更像成片"**，写进注释里不许混。

**门内状态（`--repeat 5 --skip-flash`，2026-10-26 08:14）：19/23**。
今天加了两层（L11、L4 帧预算），分母从 22 涨到 23（本次跳过 L11）。四条红分别是：
- **L6 = 3/5 跑有 `! Input has been disposed.`** —— 这条**不是音频**：报错的 catch 行没有 `audio` 前缀，
  是**视频腿**那行。我先给音频加了宽限期（`stopAudioJob` 删作业早于生成器察觉），
  方向对但**这条腿不对**；补了视频侧的同款守卫并加了 `pool_stats.dispose_skipped_live` 计数
  （不驱逐活泵在读的流，宁可临时超上限；并把"真的差点误杀"数出来当证据）。
  **验证跑在四臂之后补记**，不在这里预告结论。
- **L4 帧预算 FAIL**：p95=17（过 33.4），**max=267 ms** 不过 150；
  最坏仍是 `[267@13.61 等 266]`——**新段第一帧没有可重复的画面**，走 120 ms 押注 + 同步随机解码。
  治它要让新段晚一帧出现，是**可见的产品变化**，等用户点头。
- **L10 = 1 条**：只剩 t=1.0 跨通道 0.945（<0.95，n=5 的边际），6.633 已不再报。
- **L8 typewriter = A4 那半**：标定 `R_k[0] = -1`（画第 1 个字时行窗内无墨）。
  本轮查了：14 段首字符都是真汉字、不是空格，字号 15、clip.y=-0.4427、
  按 `band()` 的行窗算 1310..1460 px 应该包住字高 93 px ⇒ **像是那条层自己的取景/索引错位**，
  不是打字律坏了（L9 跨通道曲线一致性 0 不一致、L10 打字段历史读数 0.983–0.994）。
  未结案，需要单跑一次它的内部量才能定。

**音频修好之后的电平口径（这次 n=5，可以当分布读）**：`peak_fs` =
**1.1191 / 1.126 / 1.1409 / 1.2425 / 1.3029**，**5/5 跑都有满刻度窗**，而 `L5 mixer` 仍 PASS（0 audio_errors）。
⇒ U-78/U-86/U-88 需要的"修好后的流上重测"第一次有了分布：**离散不是偶发，是常态**，
且整族数都 >1 ⇒ 我们现在**系统性过冲**，而不再是"有时削顶"。这是新开的量，不是旧读数的延续。


## P-74 2026-10-26 `Input has been disposed` 这条：两处守卫都确实生效，但只把 3/5 压到 1/6——根子在引用计数按 id 记、句柄却是对象

**做了什么**（都在 `player.html`，都有对应读数）：
1. 音频侧宽限期：`stopAudioJob/stopAudio` 把 `j.stId` 记入 `retiredStreams`（4 s），
   驱逐循环跳过仍在宽限期里的流。理由是该文件自己那条注释：被杀的作业"生成器晚一点才注意到"。
2. 视频侧守卫：驱逐前先看 `pumps` 里有没有 `stId===k` 的活泵；有就**既不驱逐也不 dispose**
   （宁可临时超上限），并计数 `dispose_skipped_live`。
3. 用前重取：paint 腿拿到句柄后若 `st.disposed` 为真，就 `release → 重新 streamFor → hold`，
   计数 `revalidated`。
4. 诊断：抛异常那行现在带 `[seg=… pooled=… refs=… disposed=… pump=live/none]`，
   外加 `pool_stats{evictions,dispose_skipped_live,revalidated,refs_live}`。

**六臂读数**（`playms=10000&seeks=12&pool=4&loop=1`，同 build 连续六跑）：

| 跑 | errors | skipped_live | revalidated | evictions |
|---|---|---|---|---|
| 1 | 0 | 1 | 1 | 5 |
| 2 | **1** | **0** | 1 | 6 |
| 3 | 0 | 1 | 0 | 4 |
| 4 | 0 | 1 | 0 | 4 |
| 5 | 0 | 1 | 0 | 4 |
| 6 | 0 | 1 | 0 | 4 |

改前（P-73）：**3/5** 跑出该异常；改后 **1/6**。方向对、两条守卫都在动，**但没根治**。

**为什么没根治（下一刀的落点，已可由读数指出）**：失败那跑仍然 `skipped_live=0`，
而报错句柄的上下文是 `pooled=false refs=0 disposed=evicted pump=live`，同时 `revalidated=1`
——说明"取到→用到"之间被换掉的，是**另一个同号句柄**。根子在这里：
`streamRefs` 的键是 **媒体 id**，而 `pool.map` 里的值是被 `dispose()` 的**对象**。
一个 id 的旧句柄被驱逐、新句柄随即建出来时，**新句柄继承旧句柄的计数**（`|| 1` 的兜底也是这个意思），
于是"谁还在读"这件事在 id 口径下是不可见的。
**对症的修法**：计数改为**按句柄对象**记（`WeakSet`/在 entry 上挂 `refs`），
驱逐只比对象身份（`p.st === v`），`disposed` 标志随对象走。这不是再补一条时间窗守卫——
时间窗守卫我已经补了两条，两条都被这条 id/对象错配绕过。

**顺带**：`refs_live` 六跑都=2、`pool` 恒为 12 ⇒ 没有引用泄漏的迹象（我先前的双 `hold` 笔误已改掉，
现在一次持用一次释放配平）。


## P-75 2026-10-26 两条"看着像回归"的红，一条是我的仪器读错，一条是机器把包清了

### 一、打字接线 L8/A4：**不是律坏了，是 19 个预设包被剪映清了**

上一轮我把这条红猜成"那条层的行窗问题"，**这个猜测是错的**，两处都错：
- `R_k[0] = -1` 是**合法读数**——那一项对应 `k=0`（空前缀），本来就该无墨；不是取景窗口错位。
- 真正的信号是**载体里 `tw` 全空**：今天重建的 `model-check.json` 有 33 条动画条目、
  **0 条带 `tw`**，而昨天的 `model-proxy-a.json` 有 **14 条**。

直接查盘即定案（不靠猜）：

| 预设 | 段数 | 包目录还在吗 |
|---|---|---|
| 打字光标 | 14 | **全部不在**（`Cache/effect/7237411357514011192/1219…`） |
| 生长 II | 3 | 不在 |
| 侧滑 / 向上露出 | 各 1 | 不在 |
| 向下滑动 / 渐显 / 缩小 / 向上闪入 / 模糊消失 / 放大震动 | — | 在 |

⇒ `load_typewriter()` 返回 None 是**正确行为**，通道 2 画不出逐字露出是**因为表读不到**，
浏览器侧也只能跟着画成静态。这与 **F-084 的字体被清是同一类环境事件**：
**剪映会在会话中途清掉它自己的缓存**，任何"依赖机器资产的判据"都会因此变红，
而红的原因不是产品变了。
**处置**：`typewriter_wiring_check.py` 的 A4 现在**分得开两种缺表**——
逐段查包目录是否存在，14/14 都不在就报
"**律未被检验（剪映清了缓存）**"，只有部分在才报"载体真的缺表"。
读数的分母与归属一起出，不再把环境问题读成产品回归。
**要恢复这条判据的可检验性需要素材动作**（重新导入/触发剪映把那批预设包产回来，
或把包做成随草稿的固定副本），不是再改代码。

### 二、`Input has been disposed`：按对象计数**没有消除**它，而我的诊断量本身有个错

按 P-74 的落点把 `streamRefs`（按媒体 id 计数）改成**挂在句柄对象上**的 `refs`，
驱逐的三条守卫全部改成**对象身份**比较（`j.st === v` / `p.st === v` / `v.retiredUntil`），
宽限期也随对象走。六臂验证：

| | 改前 | 加时间窗守卫 | 改成按对象计数 |
|---|---|---|---|
| 出异常的跑 | **3/5** | 1/6 | **1/6** |

没有再下降，而且失败那跑的新读数是
`[seg=FFD54320 pump=live **handle=STALE** pooled=false refs=0 **disposed=true** grace=-]`
——用的是一个**已经不是池里当前值**的句柄，且它确实被 dispose 过。
同时那跑 `dispose_skipped_live=0`。

**我的仪器有个错要先认**：`refs=0` 这条**不能当证据**——catch 是在 `finally { release(st) }`
之后才跑的，计数早就归零了，所以"当时有没有人持用"这个问题它根本答不了。
`pump=live` 同理是事后状态。
⇒ **读数时刻错了**：要在**用之前**记状态（frameFor 入口记 `refs` 与 `p.st === st`），
而不是在异常里记。
下一步先修仪器再谈修法；在此之前**不许**根据这条 `refs=0` 去改驱逐逻辑
（按 P-74 的假设改完已经证明它没消除问题，说明那条假设至少不完整）。

**当前定性**：驱逐只有一处（`pool.map.delete + input.dispose`），而失败用的句柄是 STALE 且
`disposed=true` ⇒ 一定经过了那处；那处当时的守卫读的是对象 refs。剩下的可能是
①**同一文件被并发取用两次**，其中一路在 `streamFor` 尚未把新句柄入池前就选择了受害者；
或②另一处我也没看到的释放路径。**这两种都能被"用前记账"直接区分**，所以先加那一个读数。

### 三、状态与账

- 门仍 **19/23**（`--repeat 5 --skip-flash`）；L8 打字这条现在**报的是环境缺失**，
  不再是"律坏了"的误导——红仍然是红（判据无法检验就是未通过），但**归因对了**。
- 本轮改的都在 `player.html`（句柄身份计数）与 `typewriter_wiring_check.py`（分因），
  都还没提交；`ae-curves.json` 是新的浏览器依赖载体（每次门应重建，见 P-73）。
- 素材性欠口新增一条：**预设包会被剪映清掉**，和字体同一族 —— 凡依赖
  `Cache/effect/<id>/<md5>/` 的判据都要带"包在不在"的分母。


## P-76 2026-10-26 用户第三句反馈「轨道没混合、部分没静音、部分没播放」：先否掉我自己刚做的一张表，再指出一条时钟矛盾

**先说仪器错**：我做了一张"逐段时刻偏差"表（34 段、中位 +0.5 s、±1.4 s），差点当成结论交出去。
**那张表不算证据**：成片包络在 98.9% 的 0.1 s 窗里都是"响"的，几乎是常数——
在近常数序列上做相关找滞后，最小二乘没有任何分辨力，网格只会挑出噪声的极值。
**否掉它的独立理由**：同一份录音在 200 ms 粒度上只有 1 个缺失段（2.1 s，还是时间轴尾部），
反向"该静音没静音"0 段。若真有 ±0.7 s 的逐段错位，必然出现成片静音/我方响（或反之）的成片段——没有。
（教训同前：**先问判据的分辨力，再命名缺陷**。）

**轨道级数据这条线查清了，用户怀疑的方向本身不成立**：
`tracks[]` 只有 `id/type/segments/is_default_name/flag/attribute`——**轨道层没有任何静音/音量字段**；
`segments[].volume` 非默认的只有 4 段（3 段音乐床 0.3981=−8 dB、1 段视频 0.001≈静音）；
`materials.videos[]` 27 个里 **26 个根本没有 `has_audio` 字段**、1 个写 `False`。
所以"该不该播摄像机声"草稿不决定，只能由成片判。

**层归因（离线三种混音假设 vs 成片，0.1 s dB 包络）**：

| 假设 | >−40dBFS 占比 | 中位窗电平 | vs 成片中位偏差 |
|---|---|---|---|
| A 只混 3 条音频轨（37 段，按 volume×loudness+淡入淡出） | 92.5% | −20.14 dBFS | **−8.64 dB** |
| B = A + 视频自带声（27 段） | 95.2% | −15.37 | **−2.97 dB** |
| C 浏览器实录（修好 copyFromChannel 之后） | 100.0% | −12.59 | **−2.06 dB** |

⇒ 摄像机声**是**成片响度的一部分（加上它，与成片的差距从 −8.6 dB 收到 −3.0 dB），
而我们已经把它算进来了（C 与成片只差 2 dB）。
**剩下的 ~2 dB 与"包络形状"这条，现有口径都判不了**：近常数包络无分辨力（见上）。

**真正找到的一条机制级线索——文件里自相矛盾的时钟权威**：
第 150 行注释写着「AudioContext is the clock authority」，但 `tick()` 用 `performance.now()`
差值推进播放头，而 `tick()` 里 `await paint()`。于是每次 paint 超预算，
**画面冻住、音频照播**，音频就净赚这段时间。实测整条时间轴的**超预算累计 = 942 ms / 21 帧过线**
（p95 16 ms、max 210 ms；另一跑 823 ms / 24 帧）——
即 37 s 走完时画面比自己的音频落后接近 1 s，且**逐段跳变**（每次停顿跳一点）。
这与"混合不对"的主观描述一致：不是音量、不是缺层，是**画追不上声**。

**已改**：播放头改跟**音频时钟**（`actx.currentTime - actxT0`），超预算时宁可少画一帧也不让两条时钟分叉；
`&avclk=0` 保留旧墙钟推进做单变量对照；顺手把 `frame_cost_ms.over_budget_ms`（Σ超预算）加进报告，
这条就是"画面落后音频多少"的直接读数，不需要可见窗口也能算。
**验证欠口要说清**：本环境的 headless 与内置浏览器 **rAF 一帧都不发**（P-68 已证），
所以这条改动**跑在自动判据够不到的那条路上**——电池路径自己按墙钟补帧、`measuring` 下 `tick()` 直接返回，
本轮复跑确认电池判据未受影响（fps 29.91、p95 16、max 118、Σ超预算 823 ms、audio_err 0、black 1、errors 0），
但**"音频不再跑到画面前面"这件事目前只能由人耳/真窗口确认**。已开任务：要么用户当场听，
要么我起一个带窗口的 Chrome 用录音+截图对同一事件做 A/V 偏差测量。


## P-77 2026-10-26 我把"音频跑到画面前面"这条**自己否掉了**：残差实测两臂相同；换来的是一个能量到的自动判据 L4 直播节奏

**我上一轮的说法要撤回**。我当时说：paint 超预算累计 942 ms ⇒ 音频比画面快约 0.9 s。
这条**是解释，不是读数**，而真正的读数打脸了它：

| 臂（25 s 直播，drive=timer，756 帧） | 帧间隔 p50 / p95 / max | paint p95 | **音频时钟 − 播放头 残差** |
|---|---|---|---|
| `avclk=0`（墙钟推进，原有行为） | 33 / 41 / **48 ms** | 31 ms | 中位 **−0.008 s**，最大 +0.026 s |
| `avclk=1`（音频时钟推进，我改的） | 33 / 42 / 49 ms | 30 ms | 中位 **−0.008 s**，最大 +0.021 s |

两臂残差**一样**（±0.03 s 内）⇒ 换时钟没有任何改善，因为**根本没有那个偏差可修**：
`pos += (t - lastWall)/1000` 用的是**相邻两拍的差**，一拍被 `await paint()` 挡住 200 ms，
下一拍的 dt 就把这 200 ms **一次补回来**。所以停顿的可见后果是**画面跳一下**（正是用户说的"一顿一顿"），
而**不是**音画分叉。942 ms 那个数是有效的**抖动**度量，我当时给错了它的意思。
（同族教训：先问"这个数只能由什么产生"，再解释它。）

**处置**：默认回到墙钟推进，`&avclk=1` 保留为**否证化石**（注释里写清实测残差相同、不许凭猜想再改一次时钟）。

**换来的是一个真的能用的自动判据**——`L4 live pacing (drive=timer, not real rAF)`：
- 本机三处实测 rAF **0 帧**：headless `--headless=new`、Qoder 内置浏览器、**我自己起的带头 Chrome
  且加了 `--disable-backgrounding-occluded-windows --disable-renderer-backgrounding
  --disable-features=CalculateNativeWinOcclusion`** 仍然是 0 帧（`setInterval` 正常，125 个时钟点都在）。
  ⇒ 真实 rAF 节奏在这个环境里**测不到**，这不是判据松，是环境不给。
- 但 `tick()` 本来就是 rAF **不等返回**的 fire-and-forget：用同帧率的定时器去敲**同一个函数体**，
  `await paint()` 挡住下一拍的效应完全一样 ⇒ 这条读数比电池那条（自己按墙钟补帧的循环）**更接近用户看到的路径**。
- 判据：帧间隔 p95 ≤ 50 ms、max ≤ 150 ms，并要求 `frames > 200` 作非空断言；
  报告里带 `driver` 与 `avclk` 两个字段，**明写这是 timer 驱动，不冒充真实 rAF**。
- 与 L4 帧预算（电池、整条时间轴、判尾部）是两条不同的路：那条今天抓到 max 143–267 ms，
  这条在 timer 驱动下 max 48 ms ——**这个差异本身就是信息**：
  100 ms 级的阻塞出现在电池的取帧路径上（同步 `getSample` 兜底那条），
  而不是 tick 循环被 paint 挡住时。修法因此应该朝"电池那条的同步兜底"去，
  而不是继续动播放头时钟。

**门内落地的新判据（2026-10-26 10:17 这一跑）**：
`PASS L4 live pacing + A/V residual (drive=timer, not real rAF)` —
n=1062 帧、gap p50=33 / p95=42 / **max=48 ms**、paint p95=25 ms、**音画残差 max=29 ms**（截到播放头走完为止）。
同跑里 `L4 frame budget`（电池那条路）却报 **max=307 ms**（最坏 [307@13.62，pump 等待 305]）。
⇒ **同内容、同 paint，两条路的尾部差 6 倍**：100~300 ms 级的停顿属于**电池的取帧路径**
（同步 `sink.getSample()` 兜底那条），不属于直播循环。
这条差异本身就是下一步该追的方向，也意味着：**用户看到的"顿"目前没有任何一条自动判据复现得了**
（真实 rAF 在本机三处都测不到），不能拿电池尾部冒充他的体验。
> **2026-10-26 更正（见 P-78）**：这段里"电池那条路的 100~300 ms 属于同步 `getSample` 兜底"是**推断**，
> 被随后的 `sync_fallbacks=0`（三跑）否掉；真正成因是**新视频文件第一帧的冷开流 + 首帧解码**，
> 已用视频侧提前量修掉（max 276→129 ms 中位）。"复现不了"这句也只对真实 rAF 成立——
> 电池那条路一直稳定复现着同一个尾部，并且现在用它判修复。

## P-78 2026-10-26 电池尾部收口：最坏帧 = 一个新视频文件的**第一帧**（冷开流 + 首帧解码）；视频侧补上提前量后压进 150 ms 线内

**逐腿墙钟计时（LEG）才是对的仪器**。上一版的 `waits_ms` 把同一帧里并发几条腿的等待**加总**，
所以"wait≈cost"根本不能证明是哪条挡住了整帧。改成就地各记自己的墙钟后：
239 ms 那帧 = 一条腿 187 ms + 另一条 51 ms，且大帧的 **top-2 腿占 93% 的时间**。

**匹配到的慢腿是同一种时刻**：`6BDF37C1` t0=13.600（`C7727.420a.mp4`，dur 1.233 s），
每次报到的年龄都是 **+0.007…+0.020 s** ⇒ **一个视频文件起步的第一帧**。
冷开流（HEAD 拿长度 + 起读 Range + `getPrimaryVideoTrack`）和首帧关键帧解码挤在同一帧的墙上。
> **2026-10-26 由 P-84 修正这半句**：真正压住播放头的是**首帧解码**。新加的第三臂"只提前开流、不预解码"
> 实测 max **259 ms**（与什么都不做的 276 落在彼此散布内），而"开流 + 预解码"是 ~105 ms
> ⇒ 收益全部来自预解码。修法不改（两半都做），但**下一手旋钮是预解码深度**（`QMAX` / 首帧解完就 park），
> 不是"要不要提前开流"。

**撤回 P-77 结尾那句推断**（"100 ms 级阻塞在同步 `sink.getSample()` 兜底那条"）：
三跑 `sync_fallbacks=0`，那条路**一次都没走**；开流本身也不贵（65 次开流最慢 107 ms）。
贵的是"开流 + 首帧解码"恰好落在**播放头已经站到切点上的那一帧**。

**修法：给视频补上音频早就有的提前量。** `warmAhead()` 挂在 `paint()` 末尾，对
`0 < t0 − pos ≤ VIDEO_LEAD(0.3 s)` 的段先 `streamFor()` 再 `makePump()`，泵打上 `warm` 标记，
因此不被"离场立刻停泵"那圈回收杀掉（到点转普通泵，越过段尾还没用上就是白热，照常回收并计数）。
封顶两处：预解码量 = `QMAX`（泵跑满队列就 park），并发 = `WARM_MAX=2`——池上限是 2 GB 那条设计约束，
预热不能把它绕过去。对照开关 `&warm=0`，可调 `&warm_lead=` / `&warm_max=`。

**A/B（整条时间轴 37.5 s，臂交替跑，n=3）**：

| 读数 | off（`&warm=0`） | on |
|---|---|---|
| 每跑 max 帧时 | 276 / 279 / 205 ms | **105 / 132 / 129 ms** |
| >100 ms 帧数（中位） | 6 | **1** |
| Σ超预算 | 1150 ms | **470 ms** |
| p95 | 17 | 16（没把常见帧拖慢） |
| 新帧/s | 48.6 | 49.3 |
| 重复上一帧次数 | 87 | 84 |
| RSS 峰值（同序号配对） | 1272 / 1326 / 1299 MB | **1138 / 1260 / 1178 MB** |
| 预热泵 used/started | — | 21/21 ×3（wasted 0、dropped 0、无报错） |

三对配对的 RSS **都是 on 更低**：省掉一次冷开流的临时解码缓冲，比多挂两个预热泵更贵。
max 从 205~279 降到 105~132，跨过 L4 帧预算那条 150 ms 线；p95 与新帧速率不变，
说明改善来自尾部而不是把整体放慢。

**这条腿自己带分母**：`started/used/wasted/dropped/open_ms_max` 进了 `r.play.warm`，
门的 L4 帧预算那行现在打印 `预热泵 used/started`——max 达标而 used=0 是另一回事（一条不报错但没跑的腿）。

**剩下的尾部没被这次改动解释**：on 臂最坏帧在 **t≈6.61**（「向上闪入」起点附近），
单腿 ~111 ms、当帧 171 次 Range 请求，时间上与 `flashApply` 第一次把 filter 挂到 `world` 同批。
**只是同一时刻的观察，不是结论**：n=1，且 6.61 恰好也是文本/合成层密集的时刻，未定责。

## P-79 2026-10-26 预热生效后的整门跑：22/25，**L4 帧预算首次转绿**（max 97 ms、>100 ms 0 帧、预热 21/21 被取用）；三条红的性质各自定到位

`playback_check.py … --repeat 1`（全层，无 skip）：**22 of 25 passed**。

绿的、值得记的读数：

| 层 | 这一跑 |
|---|---|
| L4 帧预算（整条时间轴、判尾部） | n=1126，p50=1 / p90=8 / p95=17 / **max=97 ms**，>33 ms 15 帧、**>100 ms 0 帧**，Σ超预算 **372.5 ms**，重复上一帧 84 次，新帧 **49.45/s**，**预热泵 21/21 被到点取用**（白热 0、废 0、开=True） |
| L4 直播节奏（drive=timer） | n=1062，gap p50=33 / p95=41 / **max=48 ms**，音画残差 max=29 ms（≤50），paint p95=19 |
| L4 连续播放 / seek / 首帧 | 29.98 fps、seek 中位 24.9 ms、首帧 99.1 ms |
| 会话内存 | RSS mean 797 / **peak 1036 MB**（P-68 之前同层量级 1.0–1.37 GB，没有变坏） |
| L11 闪入闪出 A/B | 16 帧：窗内 9/9 改善，窗外 7 帧逐字节相同，退化 0，降级 0/16 |

⇒ 帧预算这条从红到绿是 **P-78 的预热**带来的，不是把阈值挪了。直播那条路的读数与 P-77 一致
（gap max 48 ms），说明预热没把用户实际走的路改坏。

**三条红的，性质各自不同**：

1. **L6 `Input has been disposed`（真缺陷，未判根治）**。这次现场：
   `handle=STALE pooled=false disposed=true refs@catch=0 evictedAs=[refs0/pump0/job0/grace0@0ms ×2]`。
   **先纠正我自己差点写错的一句**：10 s + 12 seek 那条电池的 12 条错误**不是** 12 次驱逐，
   按原文分类是 **3 条 `no video track in …/Cache/music/0291b7204776` + 9 条
   `Cannot read properties of null (reading 'getSample')`**（`handle=current pooled=true disposed=false`），
   另有 `black_streaks ['25BAD37B']`；整条时间轴那条电池才是 1 条真驱逐。⇒ **这是两个不同的缺陷**，
   详见 P-80。
   先修掉**两个读数自身的缺陷**——
   (a) `evictedAs` 的 `at` 用 `winStart` 计算，而测量那条路把 `winStart` 归零，于是**每条驱逐都写成
   at=0**，"驱逐发生在我失败之前多久"这个最关键的问题答不了：改用页面单调时钟 `T0_PAGE`；
   (b) `refs@catch` 是在 `finally { release(st) }` **之后**才取的，永远读成 0（P-74 的"守卫当时看到
   refs=0"就是这么混过去的）：改成释放之前先记 `refs@release`，并给每个池条目一个递增 `born`，
   让我手里的对象和被驱逐的那次**直接对号**——原来只能比 `pool.map.get(id)`，条目已经不在池里就哑了。
   同时把**真窗口**堵上：视频这条腿是 `streamFor(path)`（`own=false`）之后再 `hold(st)`，中间隔着
   "我这次 await 的续延"那一拍，并发的 `streamFor` 完全可以在那一拍走到驱逐分支，看到的正是我刚插入、
   refs 还是 0 的条目。音频腿早已按 `own=true` 修过，视频腿漏了；现在四个调用点都在插入的同一个
   同步步里持用。**是否根治由跑次判，不由这段推理判。**
2. **L8 打字 A4：14 个打字段 0 个带 `tw` 表 = 环境**。磁盘核对：效果缓存根还在（528 个资源目录），
   但打字光标那个 resource id `7237411357514011192` **已不在机器上** ⇒ 剪映把资源包回收了，
   与本轮改动无关；P-76 加的"载体过期 vs 环境缺失"分流这次给了正确答案。
   恢复是**材料动作**（要重新取得该资源包），不是代码能补的。
3. **L10 t=1.0 跨通道 0.945（线 0.95）**。同一跑里 t=1.0 **对成片 0.965**、t=20.23 跨通道 0.989、
   t=6.633 跨通道 0.989（对成片 0.932）——只有 t=1.0 这一条腿在边界上，且历史读数是 0.948–0.950，
   所以这是**阈值边界抖动**，不是新出现的通道间分歧。不当通过处理，也不下调阈值：
   下一跑看两件事——它是否回到 ≥0.95，以及它是否随字幕兜底 face（F-084）的存在与否移动。

## P-80 2026-10-26 L6 的 12 条错误**不是** 12 次驱逐：一条视频轨上放着 mp3，同步兜底就摸到 null sink

追 P-79 那条 L6 时，我把 10 s + 12 seek 那条电池的 `errs 12` 当成"12 次驱逐"写了下去。
**按原文分类后才看见是两个缺陷**（`errors` 数组逐条读，别数长度）：

- 3 条 `! no video track in …/User Data/Cache/music/0291b7204776…`（`pump=none no-handle`）
- 9 条 `! Cannot read properties of null (reading 'getSample')`（`handle=current pooled=true disposed=false`）
- 外加 `black_streaks ['25BAD37B']`

**机制**：把 mp3 放到视频轨上（以及组合子时间线里的 BGM）是剪映的常规操作。解封装给这种文件的条目
`sink=null`（只有 `abSink`）。于是同一跑里两种表现都会出现：缓存**没命中**时 `streamFor(path,'video')`
抛 `no video track`；缓存**命中**时 `streamFor` 的命中分支不检查 `want`，直接把只有音频轨的条目交给
`frameFor`，同步兜底那行 `st.sink.getSample(mediaSec)` 就摸到 null。**同一时刻、同一缺陷的两种面孔**，
一个 throw 一个 null deref，被"12 条错误"这一个数字糊成了一团。

**改动（都在页侧，四处）**：
- `frameFor` 顶部：`if (!st.sink)` ⇒ 判定"这一段不成像"，记 `stat.no_video_media`，首次 `out()` 一行
  `· 素材无视频轨，按不成像处理：<file>`（用 `·` 不用 `!`，不再冒充错误），并把 path 进 `noVideoPaths`。
- 绘制腿开头与 `warmAhead` 候选过滤：`noVideoPaths.has(path)` 直接跳过 ⇒ 认一次就不再逐帧重开流。
- catch 里识别 `no video track` 文本 ⇒ 同样进 `noVideoPaths`（音频腿的 `silentPaths` 早就这么做了，
  视频腿没有对应物）。
- 黑屏守卫加豁免：路径在 `noVideoPaths` 里 ⇒ `missStreak.delete` 并 continue。
  **不设这条，"按不成像处理"会立刻变成"连续 5 帧黑屏"**——把内容事实误报成产品缺陷。
  判据的牙齿由另一条负样本 `model-blacktest.json` 保（L6 guard has teeth: PASS）。
- 报告新增 `no_video_media = {frames_skipped, paths[]}`：**这条腿自己带分母**，不然"错误没了"
  与"这条腿没跑"两种情况长得一样。

**同时堵掉的驱逐窗口**（P-79 尾）：视频绘制腿原本 `streamFor(path)`（`own=false`）之后在**下一个微任务**
里才 `hold(st)`，中间那一拍里并发的 `streamFor` 可以走到驱逐分支、看到我刚插入且 refs=0 的条目。
四个调用点现在都在"插入池的同一个同步步"里持用。

**读数**：
- 整条时间轴 4 跑（预热臂 2 + 对照臂 2）：`errors=0`，驱逐 0 次。改动前同一条路是 1/6 跑的速率
  ⇒ **4 跑干净不足以判根治**（若速率真是 1/6，4 跑全干净的概率还有 (5/6)^4≈0.48）。
  这条只算"窗口堵上后没再出现"，最终判定等整门跑次累计（P-81）。
- 瘦身门（`--repeat 1`，含 12 次 seek 的电池）：**L6 从 12 条错误 + black_streaks 变成 `0/1 runs`，PASS**；
  `no_video_media = {frames_skipped: 0, paths: []}`。
  **这个 0 我要留着不解释成"修好了"**：错误消失是真的，但我新加的证人计数器 `frames_skipped` 也是 0，
  说明这一段这一跑**根本没被走到**（`black_streaks ['25BAD37B']` 也一并消失）。
  两种可能都没被排除：①持用改动让它拿到了带视频轨的正确句柄，缺陷路径不再触发；
  ②这一跑的采样恰好绕开。下一跑（`--repeat 2`）用同一把尺子再看 `frames_skipped` 与 `errors` 是否**一起**动。

## P-81 2026-10-26 三件事收口：L6 转绿且**牙齿被我自己弄瞎过一次**；驱逐窗口 18 跑 0 次；混音的离散在**电平**不在交付量

**① 我自己加的豁免，被门的 `L6 guard has teeth` 当场抓住。**
P-80 给"素材没有视频轨"的段加了黑屏豁免，随后整门跑报
`FAIL L6 guard has teeth — fixture model-blacktest.json -> black_streaks [] (must be non-empty)`。
⇒ **判据没变松，是我把判据的负样本弄成瞎的**：负样本的段与那个 mp3-on-video-track 撞了同一个 id
`25BAD37B`，豁免一生效，负样本也一起被抹平。这正是"给判据加豁免必须先想清楚它会不会把自己的
负样本也豁免掉"。**处置**：撤销豁免，`noVideoPaths` 只用于"别逐帧重开流、别把一件事刷成 12 条错误"，
不再参与黑屏判定。撤销后同一条门位恢复
`PASS L6 guard has teeth — black_streaks ['25BAD37B']`，且真草稿这一跑 `L6 PASS（0 errors、0 black）`。
证人计数器现在真的在计数：`no_video_media = {frames_skipped: 202,
paths: ["0291b72047769e085e7595ce5d65dbd2.mp3"]}`——同一条腿 P-80 那跑读 0，是因为它**未被走到**，
不是"修好了"；两种情形过去长得一样，现在能分开。

**② 驱逐（`Input has been disposed`）：窗口堵上之后 18 跑 0 次，但仍不写"根治"。**
改动后累计零发生的跑：`warm_ab` 4 跑（两臂）+ 门内 6 跑（含 repeat=2 的电池/帧预算/截图）+
`mix_stability` 8 跑（整条时间轴、无 seek）= **18 跑**，`errors` 全为 0。
按改动前 1/6 的速率算，18 跑全干净的概率只有 `(5/6)^18 ≈ 3.8%` ⇒ **这是"没再出现"的强度，不是证明**。
新加的读数以后能把话说死：池条目带递增 `born`，驱逐账本记 `born/refs/pump/job/grace@at`
（`at` 改用页面单调时钟 `T0_PAGE`，不再恒 0），作业在**释放之前**记 `refs@release`。
下一次再出现时，"哪一次驱逐干掉了我这个对象、当时守卫看到什么"是可以直接对号的。

**③ 混音：窗口固定之后仍然飘，而且飘在电平上。**
`mix_stability.py --repeats 5`（`playms=38333`、`seeks=0`、rt≈0.999、`sec_adv=38.3 s` 五次**完全相同**）：

| 跑 | `peak_fs` | 满刻度窗 | `chunks` | `nodes` |
|---|---|---|---|---|
| 0 | 1.2129 | 30 | 5424 | 288 |
| 1 | 1.382 | 35 | 5520 | 294 |
| 2 | 1.1668 | 28 | 5500 | 293 |
| 3 | 1.4746 | 35 | 5425 | 288 |
| 4 | 1.1955 | 29 | 5238 | 279 |

⇒ **U-86 的"采样口径"解释被否掉**：交付量几乎不动（`chunks` 5238–5520，±3%），
`peak_fs` 却从 1.17 摆到 1.47（极差 0.31，≈2.4 dB），5/5 跑都有削顶窗。
中途我从 3 跑数据上得出"`peak_fs` 与 `chunks/nodes` 同向变化"，n=5 之后**这条撤回**：
corr(peak,chunks)=0.287、corr(peak,nodes)=0.248，而 `chunks` 的相对带宽只有 5%，
是"两个数一起抖"的假相关——**先问这个数的量程，再谈相关**。
还留下的机制候选（未判）：默认开着的 `DynamicsCompressor`（threshold −6 / ratio 4 / attack 5 ms）
的减益状态取决于各段到达的先后与重叠，实时调度抖一下就会换一条减益轨迹；
而成片那边是**响度归一**（峰值 −0.026 dBFS、包络平），不是限幅器。
**给用户的那两个数**（Q-8/U-78 的口径线，需要他定）：我们预览 5/5 跑超出满刻度（1.17–1.47，
即 +1.3…+3.4 dBFS），成片浮点解码峰值 +2.98 dBFS / 7629 个 ≥0.9995 的样本
（P-75 的口径纠正）——"削顶算不算剪映的常态"这个问题，两把尺子已经都在桌上。

## P-82 2026-10-26 两个"看着像结论"的东西被自己的实验否掉：闪入 filter 不是那 100 ms；t=1.0 的分歧在字幕带

**① `&ao=0` 把 P-78 结尾那条闪入嫌疑打掉了。**
`temp/playback-test/flash_cost_ab.py`（整条时间轴 3 对交替跑，一臂只关 `flashApply`）：

| 臂 | 每跑 max 帧时 | >100 ms | 6.35–6.95 s 窗口内最坏帧 | `flash.applied_frames` |
|---|---|---|---|---|
| `ao=0`（闪入关） | 127 / 100 / 104 | 1（中位） | **98, 101** | 0 |
| 默认（闪入开） | 98 / 92 / **156** | 0（中位） | **78, 83** | 9 |

⇒ **滤镜挂载不是那 100 ms 的成因**：关掉闪入，t=6.61 那一帧照样要 98~101 ms。
两臂的中位 max（104 vs 98）在彼此的单跑散布之内，所以这条实验同时**没发现闪入有可测的帧代价**
（applied 0 vs 9，其余读数同量级）。P-78 结尾我写的是"同批时刻、未定责"——现在定责完成：**不是它**。

**② 剩下的尾部不是"预热没覆盖到切点"，而是解码工作被搬到了切点之前。**
预热覆盖率是有分母的：可画视频段 **22 个切点**，`warm started=21 / used=21 / wasted=0 / dropped=0`
（每跑都是 21，缺的那个是播放起点自己——`firstPlayable` 已经站在它上面，没有"提前"可言）。
可是最坏帧的腿**对不上新的那个文件**：`fcflashoff1` 的 127 ms 落在 `555AA13A`，而 25.300 起步的段是
`89614BA4`。⇒ 挡住那一帧的不是"新文件的冷开流"（那条已经被搬到前面了），而是
**同一时刻仍在屏上的老段**取帧变慢。合理解释：预热的首趟解码与它抢同一批解码/网络资源，
把原来"一帧 250 ms"的账拆成了切点前后几帧各 90~150 ms。
这与我先前测到的改善并不矛盾：**p95 一直 16 ms、>100 ms 帧 6→1、Σ超预算 1150→470**，
但 **max 现在贴着判据线**：6 次整条时间轴读数是 92 / 98 / 100 / 104 / 127 / **156**，
156 那一跑已经越过 `frame_cost_max_ms_max=150`。
⇒ **不许把"L4 帧预算绿了"当成稳定结论**。把所有"预热开"的整条时间轴跑数放到同一把尺子上看
（`warm_ab` 三次调用共 6 次 on 臂 + `flash_cost_ab` 的 6 次——那条实验两臂都开着预热，
所以它的 `ao=0` 臂也算预热跑，合计 **12 次**）：
**89 / 92 / 98 / 100 / 104 / 105 / 121 / 127 / 127 / 129 / 132 / 156 ms ⇒ 11/12 过线，1 次越线（156）**。
门里那两跑读到 97 与 139，是同一分布的两次抽样。所以现在的判据状态是**边缘绿**：
要么继续压（下一手：让预热的趟解码给实时帧让路，别把 250 ms 拆成几段 100 ms），
要么如实把"边缘"写进门的历史读数——**不能反过来把线抬高**。

**③ L10 `t=1.0` 跨通道 0.945 定位到字幕带**（用那一跑的成对图 `browser-shot-1.png` vs `c2-1.png`）：

| 带 | MAD | 跨通道 corr | 亮度均值 browser / channel 2 |
|---|---|---|---|
| 全帧 | 10.65 | 0.924 | 116.6 / 114.5 |
| 视频带 0.02–0.42 | 12.44 | 0.927 | 153.5 / 152.2 |
| 中段 0.42–0.671 | 12.80 | 0.891 | 114.2 / 112.1 |
| **字幕带 0.671–0.771** | **15.34** | **0.726** | 95.4 / 90.3 |
| 下部 0.771–1.0 | 2.96 | 0.968 | 66.2 / 64.3 |

⇒ 分歧**集中在字幕带**（corr 比其余带低 0.17~0.24），browser 比 channel 2 亮 5 个 code（更重的墨）。
这与 F-084 的既有天花板同一件事：字幕 face 被剪映从本机回收后，两条通道各自兜底到
**同族但不同栅格化器**的 face（browser `Microsoft YaHei` + 700，channel 2 `msyhbd.ttc`），
字形边缘本就不会逐像素一致。**所以 0.945 不是新的通道分歧**，是字体天花板 + 阈值边界抖动；
不下调 0.95，也不把它写成"已修"。

**④ 我在这条线上先犯过一个可复现的方法错**：第一次比对时我把 540×960 的浏览器截图与
1080×1920 的 channel-2 图**直接取左上角相交**，于是读到 `corr −0.016 / MAD 79.6`，
看起来像"两通道几乎不相关"的大发现。**几何没对齐的相关性不是测量，是噪声**。
先归一尺寸（同宽同高、同一重采样）再谈 corr——这个错如果没被"形状不一致"提示拦住，
就会变成一条假 finding 写进 unresolved。

## P-83 2026-10-26 `&warm_max=1` 是一把**空开关**：这条实验没有分辨力，尾部机制仍然开着

P-82 把残余尾部指向"预热的趟解码与实时帧抢资源"，于是第一个单变量是并发上限：
`warm_ab.py 4 "&warm_max=1"`（整条时间轴 4 跑）对 P-82 那 12 跑基线。

| 读数 | `warm_max=1`（4 跑） | 基线 `warm_max=2`（12 跑） |
|---|---|---|
| 每跑 max 帧时 | 137 / 105 / 88 / 93 | 89…156（中位 104.5） |
| `warm started / used / wasted` | **21 / 21 / 0**（四跑全同） | 21 / 21 / 0 |
| >100 ms 帧数 | 2 / 2 / 0 / 0 | 同类量级 |
| RSS 峰值 | 1494 / 1334 / 1218 / 1280 MB，0/39 s 越 2048 | 1138–1260 MB（同一条判据也全过） |

**关键读数在第一列之外**：`started=21` 在两臂**一模一样** ⇒ **这个开关在本草稿上根本没改变行为**。
原因直接：22 个切点彼此间隔 > 0.3 s（`VIDEO_LEAD`），所以任一时刻最多只有 1 个预热泵活着，
`WARM_MAX=1` 与 `=2` 走的是同一条分支。⇒ **"尾部来自两个预热泵同时抢资源"这个假设没有被判真，也没被判假——它被判的是"这条仪器看不见"**。
按 [[feedback-instrument-resolution-before-no-effect]] 的规矩：**不许把"两臂读数相近"写成"并发无关"**。
要判并发，需要一个真能分开两臂的开关（例如把 `warm_lead` 拉到 1.0 s，让多个切点同时进窗），那是下一次实验。

**并到同一把尺子上的 16 个"预热开"整条时间轴 max**：
88 / 89 / 92 / 93 / 98 / 100 / 104 / 105 / 105 / 121 / 127 / 127 / 129 / 132 / 137 / **156**
⇒ 中位 113 ms，**15/16 过 `max≤150` 线**。判据状态仍是**边缘绿**，这条已经写进 P-82 与门的历史读数；
不抬线、也不把"绿"说成稳定。

**RSS 的一个观察（未追）**：这一批 4 跑峰值 1218–1494 MB，明显高于 P-78 那批 on 臂的 1138–1260 MB，
而两臂 `warm` 计数相同、开关行为相同 ⇒ **同一版页、同一判据下的峰值带宽就有 ~350 MB**，
`≤2 GB` 那条判据（U-79 的口径线）目前靠 0/39 s 越线通过，但**用单次峰值比较两臂没有意义**，
要比就配对比多次（与 P-78 用的配对法同规格）。

## P-84 2026-10-26 分辨力实验定案：**买到那 150 ms 的是"预解码"，不是"预开流"**（并就地修正 P-78 的措辞）

P-83 承认 `&warm_max` 是空开关之后，换了一把真能分开的开关：`&warm_predecode=0` ——
提前**只开流**（HEAD 取长度 + 解封装 + `getPrimaryVideoTrack`），**不建泵、不预解码**。
三臂各 3 次整条时间轴跑（同一版页，`temp/playback-test/warm_ab.py`）：

| 臂 | 每跑 max 帧时 | 中位 max | >100 ms 帧 | Σ超预算 | 预热腿的分母 |
|---|---|---|---|---|---|
| `&warm=0`（都不做） | 276 / 279 / 205 | 276 | 6 | 1150 ms | started 0 |
| `&warm_predecode=0`（只开流） | **260 / 259 / 216** | **259** | 5 | 1074 ms | `opened_only` 189/191/188，`started` 0 |
| 默认（开流 + 预解码） | 88…137（12–16 次跑，见 P-82/P-83） | ~105–113 | 0–1 | 470 ms | `started=used=21`，`wasted=0` |

⇒ **只开流几乎没买到东西**（259 vs 276，落在彼此散布内）；**全部收益来自把首帧解码搬到切点之前**。
所以 P-78 的措辞要就地改：**"冷开流 + 首帧解码挤在同一帧"里，真正压着播放头的是后半句**——
开流那 65–111 ms（`poolStats.open_ms_max` 一直在报）即便提前做了，尾部照样回到 ~260 ms。

**这条实验自身的两个限度，写清楚以免被误引用**：
1. `opened_only=189` 而不是 21：这个开关不建泵，于是 `pumps.has(seg.id)` 那道去重永远不成立，
   切点前 0.3 s 内**每一帧都重新"预开"一次**（同一批文件反复走 `streamFor`，全部池命中）。
   它足以证明"流确实提前打开了"，但它**不是一份等价的开流开销**——若有人想拿 189 次去算开流成本，
   那是这条仪器的副产物，不是产品行为。
2. 三臂差在 260 与 276 之间，而单跑散布本身有 ±70 ms：所以本条**只支撑"开流不是主因"这个方向**，
   不支撑任何小于 ~100 ms 的差值。

**为什么这条仍然值得做**：它把下一手的方向钉死了——尾部若是预解码带来的资源抢占，
可动的旋钮是**预解码的深度**（`QMAX` 只让泵预取 1 帧而非 4 帧，或首帧解完就 park 到切点前再续），
而不是"要不要提前打开文件"。这也与 P-82 的观察一致：切点那帧最贵的腿常常属于**已经在屏上的段**，
即抢占，不是没覆盖。

## P-85 2026-10-26 L6 的分母补上了"整条那一遍"；帧预算当场由绿翻红（max 153 ms，最坏帧在**播放起点**）

**① 一条被漏判的真缺陷**：上一版整门跑的 `jank`（整条时间轴）里
`black_streaks ['658C39C6']`——查模型：track 1（`flag=2` 叠层）、窗口 **10.733–12.467 s**、
文件 `C7817.420a.mp4`、`visible=True`、`readable=True`，即**它在屏上但该画的那几帧没出图**，
而 `L6` 报 `0/1` 通过。理由很朴素：**L6 的分母只有 10 s 电池那几条跑**，整条时间轴那一遍
（以及直播节奏那一遍）从来没进过这条 judge。用户说的"有部分没播放"正是这一类现象。

**② 修法是把分母补齐，不是新加判据**：`playback_check.py` 里 L6 现在读三路——
电池跑、`jank`（整条时间轴）、`livepacing`（drive=timer），并按路径标注，两个分母不混成一个数：
`0/1 电池跑 + 0/2 整条/直播跑 有 black_streaks 或 errors`。
`--skip-jank` 时那两个 dict 先初始化成 `{}`（否则 L6 引用不到名字）。
**这一跑的整条/直播两路都是干净的** ⇒ 658C39C6 那次是**间歇性**（约 4 次整条跑里出 1 次），
这条改动正是为它准备的牙齿；复发时会被 judge 到，而不是只在日志里漂过。

**③ 帧预算当场翻红，而且红得有价值**：同跑 `L4 frame budget` 报
`n=1120 p50=1 p90=9 p95=16 **max=153** >33ms 20 >100ms 2`，判据线 150 ⇒ **FAIL**。
这不是新恶化：P-82/P-83 已经写明它是**边缘绿**（16 次整条跑 max 88…156，中位 113，15/16 过线），
这次只是抽样抽到了线的另一侧。**不许抬线**；要动的是成因。

**④ 最坏帧的位置指出了下一个真旋钮**：worst = `[153, t=1.82, 142 ms, 腿 C3A2FDAE 79 + 1A13F3C5 61]`。
**t=1.82 就是播放起点**（`firstPlayable=1.81`，第一条可画段的第一帧）。预热的结构是
"切点前 0.3 s 开泵"，而播放起点**没有前面**可预热 ⇒ 那一帧必然吃满"首帧解码"的账。
与 P-84 定案一致：**承重的是预解码**，所以这里的修法是在**进入播放循环之前**
就把 firstPlayable 那一帧解出来（`liveplay`/`battery` 已经先 `await paint(firstPlayable)`，
泵与队列却是在那次 paint 里现建现解），而不是把 150 线抬高。

**⑤ 顺带一个可复现的判据卫生点**：同跑 `L6 no silent black frame` 与 `L6 guard has teeth`
读的是两回事——前者现在含整条/直播分母，后者仍走 `model-blacktest.json` 负样本
（这次 `['25BAD37B']` 非空，牙齿在）。**加宽分母之后必须重跑一次牙齿层**，
否则"更多路径"与"判据失灵"在两处读数上长得一样（P-81 的豁免事故就是同一族）。

## P-86 2026-10-26 起点预解码（prime）判完：**首帧 −54 ms 是真的，尾部没改善，P-85④ 的预测被打掉**

`&prime=1` 对 `&prime=0`，各 3 次整条时间轴跑，配对交替；读数都带这条腿自己的分母：

| 臂 | `primed` | `started/used` | **first_frame_ms** | 整条 max | >100 ms |
|---|---|---|---|---|---|
| `prime=1`（默认） | **1** | 22 / 22 | **97.6 / 93.1 / 115.2** | 113 / 112 / 114 | 2 / 1 / 1 |
| `prime=0` | 0 | 21 / 21 | **154.8 / 153.8 / 158.9** | 113 / 97 / 95 | 1 / 0 / 0 |

1. **首帧确实被买下来了**：配对 3/3 同向，约 **−54 ms（−35%）**。
   `primed=1` 说明起点只有**一个**段在场（`firstPlayable=1.81` 只落在一条视频段里），
   `started` 因此从 21 变 22 —— 这条腿是活的，不是装饰。
2. **尾部没有改善，方向上甚至略差**（中位 max 113 vs 97），但差值 ~15 ms
   落在单跑散布（±20~30 ms）之内 ⇒ **诚实的写法是"测不出尾部效应"**，
   既不写"治好尾部"，也不写"预热把尾部搞坏了"（n=3 撑不起那个结论）。
3. **P-85④ 的预测被否掉**：我当时说"最坏帧压在播放起点那一帧，所以下一手就是起点预解码"。
   `prime=1` 之后 `t≈1.82` 那几帧确实便宜了，可 `max` 仍然 112~114，
   最坏帧换到别的时间戳（3.86 / 30.54 / 13.61 这些普通切点）。
   ⇒ **播放起点只是"首帧解码"这笔账的一个实例，不是尾部那条线的瓶颈**。
   真正的瓶颈按 P-84 是**预解码本身占资源**，下一手应当是**预解码深度**（`QMAX`/首帧解完就 park），
   而不是继续找"哪里还没预热到"。
4. **计数器的取样时刻比数值更容易骗人**（这条改动本身就是一次现形）：
   `warmStats` 的归零原来放在测量窗口开头，而 prime 在那之前跑 ⇒ `primed` 报 0、
   `started` 少 2，差点把"这条腿跑了并生效"写成"腿没跑"。归零移到 prime 之前之后，
   `primed/started/used` 自洽（1/22/22）。**同族教训：一个计数器报 0，先问它在事件之后有没有被清零，
   再问事件有没有发生。**
5. **处置**：`prime` 保持默认开（首帧是用户"按下播放到看见画面"的真实体验，3/3 配对改善，
   且不把 `L4 first frame` 推近判据线——它现在 97~115 ms，线在 300）。
   `L4 帧预算` 仍是 **边缘绿**（P-82/83/85 三次写明，6 个新读数 95~114 ms 全部 <150，
   但上一版整门抽到 153 就是线的那一侧）。**不抬线。**

## P-87 2026-10-26 预解码深度 `qmax` 判完：**尾部不由深度决定**，但浅队列把"常见帧"整段抬起来

`warm_ab.py 3 "&qmax=4"` 对 `3 "&qmax=1"`，各 3 次整条时间轴跑（其余配置完全相同；
`warm_ab.py` 里那个会静默吞掉覆盖值的硬编码已在 P-86 后修掉，两边各自解析到 4 与 1，实测确认）。

| 读数 | `qmax=4`（默认） | `qmax=1` |
|---|---|---|
| 每跑 max 帧时 | 166 / 95 / 123（**1/3 越 150 线**） | 119 / 113 / 130（**3/3 在线内**） |
| **p95** | 16 ms | **3 ms** |
| >33 ms 帧数 | 19（中位） | 17 |
| >100 ms 帧数 | 2（中位） | **4** |
| Σ超预算 | 497 ms | **743 ms** |
| 重复上一帧 stale_holds | 82–96 | **16–20** |
| 新帧/s | 49.0–49.4 | **50.9–51.1** |
| first_frame_ms | 94.8 / 140.8 / 144.9 | 80.1 / 180.7 / 179.2 |

**三条结论，按证据强度排**：

1. **P-84/P-86 指的方向（"尾部是预解码深度造成的抢占"）被否掉**：把预解码深度从 4 降到 1，
   max 的中位几乎没动（123 → 119），尾部那 110~160 ms 仍在原地。
   ⇒ **尾部不来自队列深度**。目前仍站得住的只有 P-84 的"承重是首帧解码"——
   而它现在也只剩下"预热开/关差 150 ms"这一条支撑，深度这条轴已经排除。
2. **浅队列改善的是分布的主体，不是尾部**：p95 从 16 ms 掉到 3 ms（5 倍），
   `stale_holds` 从 ~86 掉到 ~17，新帧速率反而更高。合理解释：队列深 = 每一帧都在
   为一支"还在往后填"的队列付等待；队列浅 = 绝大多数帧直接命中，代价是切点附近更容易
   一次性空队（于是 >100 ms 帧 2 → 4、Σ超预算 497 → 743）。
3. **反面证据同样明确，不许只报好消息**：浅队列把"中等超额"的帧搬成了"大块超额"的帧，
   超预算总量翻倍还多，first_frame 两跑读到 180 ms（深队列最好 94.8）。
   ⇒ **这一条只有 n=3，且判据只看 p95/max 时会偏向 qmax=1**。

**处置（不改默认，先把风险判掉）**：`QMAX` 保持 4。要换默认需要先过两关——
①n≥5 的两臂对照，把 Σ超预算 / >100 ms / first_frame 一起判，而不只是 p95 与 max；
②整门跑一遍确认内容侧没退化：浅队列的"切点空队"会不会让 `L6` 黑屏守卫或
`L10` 像素层抓到缺帧（`stale_holds` 降 5 倍这点尤其要防"少画新帧却少报警"的反向读法——
新帧速率已经同向验证，但那条数只在电池那跑量过）。
**这条也解释了用户"一顿一顿"的另一种可能**：他感知的可能不是 150 ms 的孤立大帧，
而是每秒都在发生的 16 ms 级小踩点；如果是，那 p95 这条线（现在判 ≤33.4）才是该盯的位，
而浅队列正好动的是它。

## P-89 2026-10-27 用户听到「重音」：两条真成因（排期竞态 + 丢字段），一条我自己的读数假警报，外加一个新引入的错误

起因是我把"口播替换音源"（P-88 那条链：主轨是加密组合缓存，人声在子时间线指向的拍摄文件里）
设成了默认开，用户在页面上听到叠音。下面按**证据**排，不按发现顺序排。

### ① 真成因一：`scheduleAudio` 是 check-then-act 竞态（同族于 P-74 的池持用）
判据链：这段的音频作业表用 `audioJobs.has(seg.id)` 去重，但**检查之后**才
`await streamFor(...)`，真正 `audioJobs.set` 在 `pumpAudio` 里。`scheduleAudio` 每帧被调且**不串行**，
于是两次调用可以同时通过 `has()`，各自把**同一段**排进图 ⇒ 同一内容同时播两遍 = 重音。
**修法**：占位挪到任何 await 之前（`audioJobs.set(seg.id, {pending:true, seg, nodes:[], st:null, ...})`），
失败路径撤销占位；`stopAudioJob` 因此也要能吃下 pending 条目。
**读数（关闭口播那条腿，单变量只看这次竞态修复 + ②）**：一次电池的 `jobs_started` 74 → **63**，
`peak_fs` 1.30 → **1.16/1.13**，满刻度窗 33–42 → **10–15**。

### ② 真成因二：L1 把视频段引用的 `loudnesses` 整个丢了（又一次"丢字段"）
`materials.loudnesses[]` 里有 `enable:true, target_loudness:-12.0, avg_loudness:-9.26`，
且它的 `time_range.duration = 6.6 s` **正好等于主轨第一段的长度** ⇒ 归一对象就是烘焙进组合缓存的那条音频。
而 `playback_model.py` 只在材料桶是 `audios` 时建 `out["audio"]`（:251），所以**视频段读不到这份归一**；
替换音源按满增益进混音。修后子段 `base = 0.7296`（= −2.74 dB），不再是 1。
carrier 用 `merge_model_carrier.py --fields audio` 合进 `model-proxy-a.json` 与 `model-check.json`
（各 7 段变更，`.bak` 保留，计数断言通过）。
**注意副作用是好的**：顶层视频段/BGM 现在也吃到同一份归一，所以①里那条 `peak_fs` 下降是
①+②一起的功劳，不能只记给竞态修复。

### ③ 我自己的一次读数假警报（必须留档）
我一度把"`per_seg` 里同一 id 出现两次"当成"仍在双开"。两个理由各占一半地把它推翻：
(a) `per_seg` 的 id 被我截到 24 字符，而 GUID 的前 24 字符在**不同段**之间本来就会相同；
(b) 电池 URL 带 `loop=1`，播放头回绕后会**合法地**重排开头那段——重复项的 `t0` 恰是 1.80/3.23/3.83，
正是回绕覆盖的位置。核对模型：子段共 32 个、完整 id 全唯一、**8 字符前缀无碰撞**。
⇒ 结论是"回绕重排 + 截断读数"，不是产品缺陷。**教训同 P-74：截断后的 id 不能当身份用。**

### ④ 这条新链路引入的错误：子时间线里不只有影像段
门 L6 新报 `! audio stream Input has an unsupported or unrecognizable format.`。
成因：子段里有两条 `material_type:"photo"` 指向 `JianYing Presets/Combination/Resources/76cff6f9….png`，
它的容器在模型里 `readable:true`，但拿去当**音频源**时 mediabunny 直接拒。
**修法**：替换音源只取 `cs.media.material_type === 'video'` 的子段。
修后同一条腿：`priv_max` 12 → **1**（同时只有一条私有流），`page_errors` 0。

### ⑤ 现状与未结清的账
| 读数 | `&childaudio=0` | `&childaudio=1` |
|---|---|---|
| 一次电池 max 帧时 | 191 / 111 ms | 122 / 118 ms |
| p95 / >100 ms | 16 / 3，16 / 2 | 16 / 1，15 / 2 |
| `exp_s`（排进图的音频秒数） | 85.7 | **123.6**（+38 s = 人声） |
| `jobs_started` | 63 | 88 |
| `peak_fs` | 1.151 / 1.133 | 1.334 / 1.261 |
| 满刻度窗 | 15 / 10 | 152 / 124 |
| 音频错误 / 页面错误 | 0 / 0 | 0 / 0 |

⇒ **口播进来了、节奏没有变坏**（关闭臂自己就有一次 191 ms 的越线），但
**满刻度窗从两位数跳到 124–152**，`peak_fs` 高约 +1.7 dB。成片的浮点解码本身也削顶
（+2.98 dBFS、7629 个 ≥0.9995 的样本，P-75 的口径），所以"这算不算过大"是 Q-8/U-78 那条**用户线的口径**，
我不在这里替他定。
**因此 `CHILD_AUDIO` 现在是显式开启（`&childaudio=1`），默认关**：用户正在听的页面不能带一条
还没过门的链路。等⑤的门跑完 + 口径定下来，再决定默认值。

### ⑥ 顺带把 U-86 的机制候选落成了具体实例
U-86 一直写着"同一批音频块以不同到达顺序进入混音队列 ⇒ 转给 `streamFor`/节点归属那条线"。
①就是它的一个**可复现实例**（并发 `scheduleAudio` 双排同一段，跑与跑之间取决于交织 ⇒ 峰值离散）。
但 n=5 的离散读数是**修复前**测的，必须重测才能引用——这条不在这里下结论。

## P-90 2026-10-27 「重音」的真机制：同一盘录音在切点处被排前了约一帧（19 处 → 0），另把我自己的保守处置撤回

### ① 先撤我的错：口播不该默认关
P-89⑤ 我以"用户正在听的页面不能带一条还没过门的链路"为由把 `CHILD_AUDIO` 改成显式开启
（`&childaudio=1`），用户的下一句反馈就是「怎么音频又变回之前的样子了」——他听到的是**人声没了**。
⇒ 已恢复默认开（`!== '0'`），并把这段判断写进代码注释。
**教训**：保守处置也要算成本——我为了避开一个我自己引入的风险，把用户要的功能撤掉了，
而他并没有要求我撤；正确做法是把风险做成**可测的读数**，再决定默认值。

### ② 三个候选，前两个被自己的仪器否掉
| 候选 | 判据 | 结果 |
|---|---|---|
| A. 同一份录音被"顶层段"与"子段"各放一遍（id 不同，`has()` 拦不住） | `per_seg` 新增 `file` 字段，求两个集合的交集 | **否**：`shared with top-level files = []` |
| B. 同一 id 并发双排（竞态残留） | `per_seg` 新增 `ctx0/ctx1`（音频时钟窗），查同 id 重叠 | **否**：0 处；先前看到的"重复 id"是 `loop=1` 回绕后的合法重播（P-89③） |
| C. **同一文件的相邻两刀重叠** | 同文件、`ctx` 窗相交 | **是：19 处**，每处 ≤33 ms |

### ③ 机制与修法
`ctxAt = actx.currentTime + (t0 - posSec)` 是**按帧粒度**算的（33 ms 一拍），
于是切点处后一段的排期起点会比前一段已排的终点**早约一帧** ⇒ 同一盘录音的约 33 ms 被放两遍。
一条 37 s 的时间轴上有 19 个这种切点，每个都是一次短促的" flam/回声"——这就是重音。
**修法**：给每个媒体文件维护一条单调游标 `fileAudioEnd`，排期时
`ctxAt = max(现在算出的时刻, 该文件已排到的位置)`，并在 `stopAudio()` 里清空（否则暂停/seek 后会被推到很远的将来）。

**修后读数（两次整条时间轴）**：同文件重叠 **19 → 0**，且相邻切点间隙正好 **0 ms**
（既不叠也不留洞）；`exp_s` 仍 **123.6/123.7 s**（人声一点没少），max 帧时 105/112 ms，p95 15，
`audio_errors=0`、页面错误 0。

### ④ 仪器上补的两样东西（没有它们这条根本问不出来）
`audioStats.per_seg` 现在带 **`file`** 与 **`ctx0/ctx1`（音频时钟窗）**。
只按 id 记账永远分不清"**同时在放**"与"**回绕后依次重播**"——两者在 id 账目里一模一样。
（同一族的教训见 [[browser-chain-verify-with-screenshots]]：截断后的 id 不是身份；
这次再加一条：**时间轴位置也不是音频时钟**。）

### ⑤ 门与遗留的口径问题
这份页面（默认带口播 + 叠音消除）跑完整门：**23 of 25**，
`L4 帧预算 max=117 ms`（线 150）绿、`L6 no silent black frame` 两个分母都干净（0/1 电池 + 0/2 整条/直播）、
`L5 mixer` 0 错、预热泵 22/22 被取用。两条红仍是 L10 t=1.0（字幕带字体天花板）与 L8 打字 A4（资源包被回收）。

**遗留、要用户定的口径**：带口播后 `peak_fs 1.21–1.28`、满刻度窗 120–137，
而不带口播是 `1.13–1.15` / 10–15。成片的浮点解码自身也削顶（+2.98 dBFS、7629 个 ≥0.9995 样本），
所以"人声加进来后的和声超过满刻度算不算错"是 Q-8/U-78 那条**口径线**；
定了口径我才动增益结构（求和前归一 vs 加限幅 vs 认了），不在这里替他选。

## P-91 2026-10-27 U-15（叠序归属）在语料尺度上**判不了**：2218 份草稿、两律分歧 0 例；顺手补了 L1 丢的 `track_render_index` 与一个先证明自己是死的哨兵

用户先前那句「对多轨道的处理和轨道参数好像还没完成」里，叠序这条是能查的。
先明确两律：A = 渲染器现行做法（轨道在列表里的位置 → 段的 `render_index`）；
B = `render_index_track_mode_on:true` 字面主张的做法（段的 `track_render_index` → 段 `render_index`）。

### ① 本草稿不可判（探针先被自己的仪器骗了一次）
`temp/playback-test/u15_discriminability.py` 对**原始草稿**：80 个"≥2 段同时在屏"的瞬间，
两律次序 **80 相同 / 0 分歧**。原因很直白：每轨首个 `track_render_index` 是
`[None,1,2,3,4,5,6,7,8,9]` —— 主轨没有（落最底），其余**恰好等于列表位置的升序**。
> 我第一遍把这个探针跑在**播放模型**上，读出"80/80 一致"。那是假的：模型里
> `track_render_index` 有 **0/104** 条（L1 不复制它），于是 law B 退化成"所有轨并列、只按段
> `render_index` 排"——我拿稻草人证了个结论。**教训：比较两条律之前先确认两条律都拿到输入。**
> 采样充分性也交代清楚：在屏集合只在**切点**变化，而切点之后的集合必是"上一个切点集合"的子集，
> 母集合同序 ⇒ 子集合同序，所以只取 `t0` 就够。

### ② 语料尺度：没有可判对象
`temp/playback-test/u15_corpus_scan.py` 扫 `temp/corpus-scan/plain/`（已解密的批量草稿，无需重新解密）：

| 读数 | 值 |
|---|---|
| 读入并解析成功 | **2218 / 2218**（0 份解析失败） |
| `render_index_track_mode_on = true` | **1576** |
| 至少一段带 `track_render_index` | **1412** |
| tri 的稳定次序 ≠ 列表次序 | **1**（`9c7084584b06d1b6`：`[0,1,0,3,5,6,7]`，是**并列两个 0**，不是反转） |
| 存在某瞬间两律次序不同（**可判对象**） | **0** |

⇒ **U-15 不是"我们还没校准"，而是"这个语料里没有能分辨两律的草稿"**（与 U-95 同一处置）。
现行律在这 2218 份草稿上与轨模式律**同解**，所以它不是用户所担心的"多轨道处理没完成"的那一块。

### ③ L1 的两个补件（都不改渲染次序，只让它别悄悄失真）
- **字段**：段上现在带 `track_render_index`（实测本草稿 101/104、反转 fixture 102/104）。
  以前不带的后果不是画错，而是**下一条哨兵恒等通过**。
- **哨兵**：若某草稿"按 tri 稳定排序"与"按列表位置"不一致，L1 直接
  `warning: track_render_index order != track list order (mode_on=…) ⇒ 两律会分叉，U-15 需按成片重判`。
  门的 `L1 errors/warnings` 会因此变红——这是我要的：**真出现反例时由门叫停，而不是让渲染器照未证的律走**。
- **牙齿先自证**：第一版哨兵在人造反转 fixture 上**没有响**（因为字段没进模型，
  `_first_tri` 全拿到 `None`）；补字段后同一 fixture 报出该 warning，真草稿仍 `warnings 0`。
  顺序记下来：**先让守卫证明自己会红，再谈它保护了什么**。

### ④ 未做与不做
两律同解 ⇒ 这里**没有**改渲染次序的验证依据；改序属于"拿不可测的改动冒充进展"，不做。
将来若拿到一份 ②里 INSTANT_DIFF>0 的草稿（或其导出成片），判据已经备好：
`u15_discriminability.py <该草稿的 dec.json>` 报分歧瞬间，再走 `cut_alignment`/`export_compare` 的固定索引裁决。

## P-92 2026-10-27 空窗（"有部分没播放"）定案：不是流争用，是 **hold 到的帧被清扫成整层消失**；修完 19/19，负样本牙齿仍在

### ① 先给判据装上能问下一个问题的读数
上一版门把 `L6` 加宽到含"整条时间轴/直播"两路后，立刻抓到
`black_streaks ['C3A2FDAE']`、`['89614BA4']`、`['658C39C6']`，但**只有 id**——下一个问题
（发生在切点还是半路？泵在不在？）答不了。于是给守卫加现场：
`black_detail = {id, pos, age(段内毫秒), pump(q长度/done/err), warm, sprite, hold, priv_live}`，
并进了报告字段 `r.black_detail`。顺手纠正一处单位谎报：`age_ms` 我算的其实是 **µs**，
读数时按 /1000 换算（`temp/playback-test/black_attrib.py` 里已经修好口径）。

### ② 读数否掉了我自己的两个假设
现场：空窗都在**段内 377–777 ms**（不是切点！），`pump='q0'`（泵活着、队列空），`warm=0`，`sprite=1`。
⇒ ①P-85④ 那条"切点没预热"**不成立**（这次是半路断供）；
⇒ ②我随即假设"**同一条 Input 被视频泵与音频作业按不同位置并发拉，饿死解码**"
（支持证据一度很像：4/4 次空窗时刻同文件都有音频作业在播，`black_attrib.py`）。
**配对实验把它打掉了**：`&vidaudiopriv=0/1` 各 3 跑——
私有流臂空窗 2 次（共享臂 1 次），max 帧时 97/93/91 → **128/170/142 更差**，
而且空窗位置在两臂**完全相同**（`658C39C6@11.11`、`89614BA4@25.74`）。
⇒ 不是争用，是**位置相关的解码吞吐**（高运动段跟不上 30 fps），`qmax` 那次也说明预取深度不是解药。
`vidaudiopriv` 保留为**否证化石**（默认关）。

### ③ 真缺陷与修法：hold 的契约被清扫打破
`HOLD_ON` 的语义是"这一帧押不到就**重复上一帧**"，但绘制腿在 `frameFor` 返回 null 时直接
`return` ⇒ 这一段不进 `visibleThisFrame` ⇒ paint 末尾的可见性清扫把 `node.visible=false`。
于是**一次取帧延迟被放大成"整层消失 ≥5 帧"**——正是用户说的"有部分没播放"，也正是 L6 抓到的形状。
**修法**：屏上已有该段画面（`_bmp` 在且没被 close，因为没有新帧替换它）就算本帧可见。
```js
if (!f) { const held = sprites.get(seg.id);
          if (HOLD_ON && held && held._bmp) { visibleThisFrame.add(seg.id); held.visible = true; }
          return; }
```
**这改的是产品还是判据？** 两问分开答：
- 产品：屏上确实继续显示上一帧（不是把黑屏画出来），符合 hold 契约；
- 判据：**从没画面的段仍然会被抓**——它从来没有 `_bmp`，豁免条件不成立。
  实测门的 `L6 guard has teeth` 在 `model-blacktest.json` 上仍报 `['25BAD37B']`（非空）⇒ 没瞎。

### ④ 读数
| 项 | 修前 | 修后 |
|---|---|---|
| 空窗（3 跑整条时间轴） | 6 跑中 4 次，位置固定 | **0/3** |
| 帧时 p95 | 16 ms | **12 ms** |
| max | 91–170 ms | 97 / 116 / 91 ms |
| 重复上一帧次数 | 74–97 | 81–131（按设计上升：宁重复也不空） |
| 新帧速率 | 48–51/s | 48.0–49.6/s（没掉） |
门（`--repeat 1`，含 jank/live/负样本）：**19 of 19 全绿**，
`L4 帧预算 max=118 ms`、`L6` 两路分母干净、牙齿 `['25BAD37B']` 非空。

### ⑤ 附带：打字律第一次可判并且判绿
效果缓存里 `7237411357514011192`（打字光标）**已回到本机**（缓存目录 528 → 536），
我这次重建 L1 时把 `tw` 表重新 harvest 进两个载体 ⇒
`L8 typewriter wiring 14/14、carrier_tables_ok=True、problems=0`。
诚实记账：这是**环境恢复 + 重建载体**接上的，不是我修好的；但它意味着 P-55 那条判据第一次真正跑起来了。

### ⑥ 还欠的
`89614BA4@25.74`、`658C39C6@11.11` 这两个位置的**解码跟不上**仍在（现在只是不再表现为空窗，
代价是重复帧/延迟）。下一手按 P-84/P-92 的合流是：**代理的关键帧间隔 / GOP 结构**
（M1-D 那条 SP-09 结论：4:2:0 代理已定，短 GOP 被否），或者干脆承认
"这台机器实时解 1080×1920/30fps 多轨有上限"，把它写成判据的机器相关条款——两者都需要新证据，不在这个位置猜。

## P-93 2026-10-27 U-98① 「整条轨消失」从静默变成有分母的读数——顺带发现黑屏守卫**看不见非 video 轨**

用户说「对多轨道的处理和轨道参数好像还没完成」。普查（`temp/playback-test/track_param_census.py`，
2218 份草稿 / 10586 条轨）先给"轨道参数"定了边界：轨对象只有 `id / type / segments /
is_default_name / flag / attribute / name` 这几类键，**没有** mute/opacity/blend；语义"轨道级"的参数都写在段上。
真正没完成的是**轨类型覆盖**：类型分布 `video 3389 / audio 2702 / text 2567 / mixed 930 /
effect 426 / sticker 280 / adjust 223 / filter 69`，而画面腿只画 `video|text`
（`player.html` 的 `videoTracks/textTracks` 过滤）、声音腿只走 `audio|video`。
⇒ **含 `mixed` 轨的 355 份草稿（16%）会既看不见也听不见，而且不报错**；
`mixed` 的 2615 段里材料桶是 `videos 1723 / texts 848`，即**那是真内容不是特效容器**。

### 这一步只做"停止静默"（不改渲染次序）
- L1：`stats.track_type_segments`（按类型分组的段数）与 `stats.unrouted_track_segments`
  （没有任何一条腿路由的段数）。本回归草稿读出 `{video 27, text 40, audio 37}` / `unrouted=0`——
  **它恰好不含这几类轨，所以之前所有判据都看不见这个缺口**。
- 播放器：`UNCOVERED_TRACKS` 在载入时算，一次性 `·` 日志（不冒充错误）+ 报告字段
  `r.uncovered_tracks`。
- 判据卫生：**先让哨兵证明自己会响**（`temp/playback-test/u98_teeth.py`，把 text 轨改名造 fixture）：

| 探针 | `uncovered_tracks` | `black_streaks` | errors |
|---|---|---|---|
| 真草稿 | `{}`（不误报） | `[]` | 0 |
| fixture：`mixed` 32 段 + `sticker` 7 段 | `{"mixed":32,"sticker":7}` | **`[]`** | 0 |

**fixture 那一列还有个更硬的信息**：整条 `mixed` 轨（32 段，含真影像/字幕）从画面上消失，
黑屏守卫一声不响——因为它只遍历 `videoTracks`。也就是说 P-12 建的那道牙齿**覆盖不到非 video 轨**，
这类丢失此前不在任何判据的视野里。这不是把 U-98 判成"已修"，而是把它从"感觉没完成"
变成"有数、有哨兵、有明确剩余工作"。

### 门
`--repeat 1`（含 jank/live/负样本，跳掉像素与混模式层）**19 of 19**：
`L1 errors/warnings 0`、`L4 帧预算 max=131 ms`、`L6 0/1 电池 + 0/2 整条/直播`、
`L6 guard has teeth ['25BAD37B']` 仍非空。

### 剩余（明确、可开工，但需要材料）
`mixed` 按**段的材料桶**路由（videos→影像腿、texts→字幕腿）是下一步，但它有两个前置：
1. 拆一条 mixed 轨成两条伪轨会共享同一轨道位置 ⇒ 先用 `u15_discriminability.py` 证明**拆分不改变叠序**；
2. 需要一份**含 mixed/sticker 轨且媒体齐备**的草稿才能拿成片裁决——本回归草稿没有（`unrouted=0` 就是证据）。
   同 U-95 的规格：这是材料需求，不是再写代码能解决的。

## P-94 到货停顿的归因：先否掉我自己的"发现"，再修仪表（2026-10-27）

### 我写错的那条（就地更正，不删）
上一跑我记的是「原始素材 `C7727.MP4` 是 30 fps / 1083 帧，而我们的代理是 59.94 fps / 2160 帧
⇒ 做代理那一步把帧率翻倍了」。**错**。配对探测（`temp/playback-test/fps_census.py`，25 支逐一支
源↔代理）：`r_frame_rate` 不同 **0 支**、代理帧数 >1.5× 源 **0 支**，C7727 两边都是
2160 帧 / 60000/1001。那个「30 fps / 1083 帧」其实是我为对照临时做的 `proxy-b/C7727.30f.mp4`
**变体本身**的读数（1083 = 36.036 s × 30），被我记成了原始素材 —— 错法很具体：
**读数没有绑定它来自哪个文件**。

站得住的事实换成这样：素材本身就高帧率 —— 25 支里 **18 支 59.94、3 支 50、仅 4 支约 30**
（原始 `avg_frame_rate` 有 5 支 ≠ `r_frame_rate`，是 VFR）。时间轴 30 fps + 全 I 帧代理
⇒ 播放头每走 1 帧要解 ~2 帧。所以"抽稀到时间轴帧率"是配方的**可优化项**（省一半解码，
代价是取样时刻最多偏 1/60 s），不是配方的缺陷。

### 上一轮 A/B 的「停顿消失」是死腿假象
alt 臂三处独立证据：`warm.err="media … not served"`、6BDF37C1 **零条到货记录**、
`black_detail.sprite=0` ⇒ 那一段根本没在播。根因在仪表不在被测物：网关清单只按
`model["media"]` 建（`preview_gateway.py:62`），`fps_ab.py` 当时只改了 `segments[].media.path`。
修法是走本来就为 A/B 准备的 `--extra` 直供（`preview_gateway.py:344`），并同步 `media[]`。
顺带记一条别踩：`--measure` 会跑微基准并**退出**（`preview_gateway.py:367`），不能拿来重建清单。

**仪表自身的第二个错也一起修了**：`slowest_arrivals` 是**前 16 名**，「不在名单里」既可能是
没进最差 16、也可能是这条腿一次都没解帧 —— 我第一版的死腿检查正是用"不在名单"判的，
方向对但依据不成立。改成点名腿：`&probe=<id>` 让报告无条件回送该段（`player.html`
`probe_arrivals`），并把账本 `pushes` 从"第二次 push 才记"改成**第一次就记**
（旧写法下"只解出一帧"的腿在账上根本不存在）。判活标准：`pushes>0`；否则整条读数作废。

### 自伤记录：时序测量期间本机必须空载
soak 正在跑时我去做了 25 支 ffprobe（还走 X: 网络盘）⇒ 同一轮的 base-2 直接劣化：
`max 124→2649 ms`、`fresh/s 49.6→28.2`、`decoded 2985→1808`。这条以后写进纪律：
**任何节奏/延迟类 A/B 期间不做并发探测**，要并行的事等读数出来再做。

### 空载复跑：停顿在 base 臂可复现（n=2）
两臂都供到文件、`预热 used/started=22/22`、`泵命中≈1860`、无 `not served`：

| 跑 | 6BDF37C1 到货最大间隔 | 超 50 ms / push 数 | 源时刻 | 全跑 max | p95 | 空窗 |
|---|---|---|---|---|---|---|
| 60fps-base-1 | **379 ms** | 1/75 | 34.13 | 124 | 15 | 0 |
| 60fps-base-2 | **395 ms** | 3/74 | 34.13 | 122 | 16 | 0 |
| 30fps-alt-1 | 名单外（当时还不知道为什么） | — | — | 118 | 16 | 0 |
| 30fps-alt-2 | 名单外 | — | — | 85 | 16 | 0 |

停顿在空载下**稳定复现于同一 (文件, 源时刻)** —— 不是 seek 序列、不是机器抖。

### 同批落地的泵回收守卫（门复跑：21/21 绿）
`player.html` 的 paint 清扫原来按"本帧没在屏上 ⇒ 停掉这个泵"回收，于是**播放头还停在段内**、
只是这一帧没解出图的泵会被停掉，下一帧重新建泵、重新付一次首帧冷解——每帧重付，永远追不上。
新增豁免：`posUs` 落在该段 `[start, start+dur)` 内就不回收（预热泵越过剪切点仍照常计 `wasted` 回收）。
要看的读数：`warm.wasted`、`L4 帧预算`、`L6`、`L6 guard has teeth`。
本轮门（`--repeat 1 --skip-flash --skip-mixmode --skip-browser-shots`）：**21 of 21 全绿**。
关键三行：`L4 frame budget` p50=1 / p90=10 / p95=16 / **max=93 ms**（>33 ms 19 帧、>100 ms 0 帧，
重复上一帧 92 次、新帧 49.25/s、预热表 **22/22** 且 `wasted=0`）；
`L6 no silent black frame` **0/1 电池 + 0/2 整条/直播**；`L6 guard has teeth` 仍打到
`model-blacktest.json` 的 `['25BAD37B']`（豁免没有把负样本蒙掉——这条是 P-80 那次的直接回归检查）。
`L4 live pacing` gap p95=41 / max=54 ms、A/V 残差 max=42 ms。
⇒ 泵回收守卫**成立且无代价**：本帧没出图不再顺手停掉在段内的泵，帧预算尾巴从 131→93 ms，
`wasted=0` 说明豁免也没让预热泵变成常驻浪费。

### 还有一条没动的变量（跑之前发现，所以没造成误判）
`C7727.30f.mp4` 只有视频流，base `C7727.420a.mp4` 带 AAC 相机声 ⇒ 那一臂同时改了帧率**和**
音频腿（mixer 少一条腿、解码争用也随之变）。真单变量已重造：
`make_alt_f30.py` 从 **base 代理本身**出发 `-vf fps=30` 重编视频、`-c:a copy`，
自证 `r=30/1` 且恰好 1 条音频流才允许使用 ⇒ `proxy-b/C7727.30a.mp4`（1081 帧 / 36.033 s / 1080×1920 / aac，
比 base 短 3 ms：抽稀丢了最后一帧）。

### 单变量轮次：**帧率解释被否证**
`C7727.30a.mp4`（30 fps + 同一条 AAC）替掉 `C7727.30f.mp4` 后重跑，点名腿判活
（4/4 条读数可用、`预热 used/started=22/22`、无 `not served`、空窗 0）：

| 跑 | 文件 | 到货最大间隔 | 超 50 ms / push 数 | 源时刻 | 全跑 max | p95 | decoded |
|---|---|---|---|---|---|---|---|
| 60fps-base-1 | `C7727.420a.mp4` | 358 ms | 4/81 | 34.13 | 95 | 16 | 2989 |
| 30fps-alt-1 | `C7727.30a.mp4` | **336 ms** | 2/53 | 34.20 | 99 | 16 | 2963 |
| 60fps-base-2 | `C7727.420a.mp4` | 375 ms | 1/77 | 34.13 | 109 | 15 | 3005 |
| 30fps-alt-2 | `C7727.30a.mp4` | **375 ms** | 2/54 | 34.20 | 137 | 16 | 2964 |

⇒ **「代理 59.94 导致停顿」不成立**：把文件抽稀到 30 fps，停顿原地不动（336/375 ms），
位置只随帧栅格挪 1/60 s。附带把另一条推断也否掉：两臂 `decoded` 几乎相同（2989 vs 2963），
说明**文件帧率并没有让我们的解码量翻倍**——此前"每跑 decoded≈2990 而需要≈1110 ⇒ 多解一倍"
是拿整条时间轴的总量去比单段的需要量，口径本来就不对（本段只用到该文件 1.233 s，
60→30 fps 的差别是一个泵多解 ~37 帧，在 ~2990 的总量里根本看不见）。

> **[P-95 就地更正]** 本节下面那句「停顿是那个源时刻本身的属性」**是错的**，两条独立编码在同一
> 时刻都付 ~350 ms 不是因为内容贵，而是因为那笔间隔是由**剪切点**定义的（见 P-95 的帧栅格核对与
> ffmpeg 对照）。`slow_decodes` 这一刀的方向也随之作废——真正的成因在记时点，见 P-95。

停顿因此是**那个源时刻本身**的属性：两份独立编码（原代理 + 我重编的 30 fps 版）在同一时刻
都付 ~350 ms，且 `超50ms` 只有 1–4 次/push 数 53–81 ⇒ 不是普遍变慢，是**孤立一次**。
下一刀该怎么切已经明确：现在只有"两次 push 之间的墙钟间隔"，分不清这 350 ms 花在
**一次解码调用内部**还是**解码之后（上传/合成/GC）**。要在泵里记一条
`slow_decodes`（任何单次 `d0→now() > 100 ms` 的 (文件, 时间戳, ms)），
配合已有的 `pumpStats.decode_ms` 才能把"解帧慢"与"到货慢"分开——
在此之前**不改任何取帧策略**（P-92 那条"一帧 cost≈泵等待"只到定位，不到机制）。



## P-95 2026-10-28 「是不是 Python 这门语言的执行效率问题」——量完了：不是，而且 P-94 那笔 350 ms 是账本自己造的

用户给的题是：M2 的解码速度问题，先研究是否 Python 的执行效率。做法是先找出**浏览器播放这条热路径
上到底哪一段是 Python**（不是通道 2 —— 那条是离屏 PIL+ffmpeg，跟浏览器停顿无关）：答案是只有
`preview_gateway.py`（`ThreadingHTTPServer`，供 Range 字节 + 每请求写一行 `gateway.log`）。分三路量。

### ① 网关：376,323 次请求里服务端最大 18.59 ms，0 次超过 100 ms
`temp/playback-test/py_leg_probe.py --tail-mb 48`（口径：**日志尾部 48 MB 全量**，跨今天的
`lead_ab` 与 10-27 的 fps A/B 若干轮；日志只有 `HH:MM:SS`、无日期，所以这**不是**"那 350 ms 窗口内
的请求"，而是"这一批请求里没有一次接近 350 ms"）：

| 读数 | 值 |
|---|---|
| 带 `ms=` 的请求数 | 376,323 |
| 全部 p50 / p95 / p99 / **max** | 0.32 / 0.70 / 1.06 / **18.59 ms** |
| GET（n=361,039）p50 / p99 / max | 0.32 / 1.06 / 18.59 |
| HEAD（n=3,382）p50 / p99 / max | 0.10 / 0.27 / 0.65 |
| 复用 vs 新建连接 | yes n=365,073 p99 1.06 / no n=193 p99 1.65 ⇒ 复用没有异常尾巴 |
| **`ms>100` 的请求数** | **0 / 376,323** |

另一件必须单独量的事：`ms=` 是记到**发送循环结束**为止，而 `_note()` 在它**之后**跑
（[preview_gateway.py:220-248](../../scripts/preview_gateway.py)），所以"日志里 ms 都很快"这句话
对网关最大的嫌疑是瞎的。于是把 append 本身做了基准（`--bench-append 300`，写 temp 副本，**不碰真实
gateway.log**；该日志已长到 630 MB）：新建空文件 p50 241 µs / max 469 µs；**537 MB 已有文件
p50 234 µs / max 905 µs**；对照"单次 open 连写 300 行"= 0.3 ms 合计。⇒ 每请求 Python 侧总成本
≈0.55 ms，比 350 ms 差三个数量级；文件多大都不改变。附带一条与停顿无关但值得记的卫生问题：
630 MB 单文件日志。

嫌疑文件本身的位置也核了：`C7727.420a.mp4` 在 **C 盘本地** `temp/playback-test/proxy-a/`（184 MB），
不在 NAS ⇒ SMB 不是这条腿，P-08 那套 NAS 结论不适用于本次停顿。

### ② 那个"源时刻"不贵：ffmpeg 首帧在 5 s / 20 s / 34 s / 另一个文件的 43 s 上是同一个量级
`temp/playback-test/decode_cost.py`（每个时刻 3 次取中位数；**进程启动+seek+首关键帧解码**计入
`first_frame_ms`，Python 在这里只是起进程，解码是 ffmpeg 的 C）：

| 文件 | fps | 源起点 | first_frame_ms | per_frame_ms |
|---|---|---|---|---|
| C7727 | 59.94 | **34.067**（嫌疑时刻） | **123.2** | 1.28 |
| C7727 | 59.94 | 20.000（对照） | 125.3 | 1.37 |
| C7727 | 59.94 | 5.000（对照） | 130.2 | 1.32 |
| C7573 | 59.94 | 43.467（另一条"~300 ms"腿） | 120.5 | 1.11 |

⇒ 嫌疑时刻**没有任何额外成本**（它甚至是四个里最快的）。P-94 的"两份独立编码在同一时刻都付
~350 ms ⇒ 停顿是该时刻的属性"因此被否证：两臂之所以对上，是因为那笔间隔的位置由**剪切点**决定。

### ③ 记账错的位置核到了帧栅格，并用 `warm_lead` 做了因果实验
把每段最大间隔的落点 `at` 减去该段的 `source.start`：11 条腿全部落在 **+0.063…0.100 s**，
60 fps 臂是 `34.067+0.063 = 第 4 帧`，30 fps 臂同一段是 `34.067+0.133 = 第 4 帧` ⇒ 两臂"同一个时刻"
其实是**同一个相对剪切点的帧序号**。原因在代码里：
[player.html:717-733](../../player/player.html) 先取到货戳 `tArr = now()`、记 `p.lastArr = tArr`，
**之后**才 `while (p.q.length >= QMAX) await p.sleep()` ⇒ 队列满而 park 的那段墙钟时间被算进**下一帧**
的"到货间隔"。而"队列满"是**背压**（供给 > 需求：`fresh_track_frames_per_second` 48.7–49.3，目标 30 fps），
与"解码跟不上"正好是相反的状态。

因果实验（`temp/playback-test/lead_ab.py 2`，4 臂×2 轮、整条时间轴 `seeks=0`、~~臂序按轮交叉~~
**【就地更正 2026-10-28】那句"臂序按轮交叉"不成立**：`lead_ab.py:101-102` 写的是
`[(a, e) for i in range(REPEAT) for a, e in ARMS]` —— 每轮内部同序（lead300→lead050→lead005→nowarm 重复两轮），
**没有交叉**，所以"机器越跑越热"系统性偏惠 `nowarm`、亏待每轮第一臂 `lead300`。本条结论方向（park 随提前量塌）
后来被 P-96 的 `&split=1` 逐事件读数独立证实（wp 里 99.8% 是 `park_prev`、`await=0`），不依赖臂序；
但**臂与臂之间那 100–150 ms 量级的 `frame_cost.max` 差**可能含这个顺序效应。新的跑测器
`temp/playback-test/s1_split_ab.py` 按轮真交叉（r1: split1→split0，r2: split0→split1），
并加了两臂之间 12 s 空机等待（`S1_SETTLE`）——后者是 P-96 自伤一轮的直接产物：背靠背跑时第二臂撞在
第一臂 Chrome 正在被销毁的瞬间，`fc_max` 读到 1515 ms、网关 `ms=` 被顶到 286 ms。
每条臂带 `&probe=6BDF37C1,9F18A357,845C3CB8,14D93F1F` 判活 —— 死腿的"停顿消失"不算读数）：

| 臂 | 点名四条腿的 max_ms (ms) | 整条 arr_max | arr>100 的段数 | warm used/started | frame_cost max |
|---|---|---|---|---|---|
| `warm_lead=0.3`（默认） | 322–387 / 322–387 | 430 / 363 | 16 / 16 | 22/22 | 144 / 103 |
| `warm_lead=0.05` | 36–239 / 36–239 | 389 / 402 | 8 / 13 | 22/22 | 113 / 133 |
| `warm_lead=0.005` | 37–63 / 37–63 | 354 / 240 | 5 / 4 | 1/1, 2/2 | 155 / 302 |
| `&warm=0` | 35–102 / 35–102 | 279 / 316 | 5 / 7 | 0/0 | 249 / 203 |

⇒ **点名那几条腿的 ~350 ms 随提前量塌下来**（0.3→0.005 时 322–387 变 37–63），park 记账成立。
⇒ **但没有全塌**：每臂仍有 4–16 段 >100 ms 的间隔（`arr_max` 240–430），它们是**与提前量无关**的另一类，
P-94 把两类混成"一个停顿"了。
⇒ **真正会冻画面的那个数反而变差了**：`frame_cost_ms.max` 从默认臂的 103–144 ms 涨到 `&warm=0` 的
203–249 ms（与 P-78/P-84「买到尾巴的是预解码」一致）。⇒ 缩小提前量会让**难看的指标变好看、
可见的卡顿变严重**，所以任何按 `arrivals` 调取帧策略的做法都方向错了。

### 结论与下一刀
1. **不是 Python 的执行效率**：网关服务端 0/376k 超 100 ms、每请求 Python 成本 ≈0.55 ms；
   浏览器解码是 Chrome 的 WebCodecs，Python 不在那条腿里。这条**先结案**，别再往"重写网关"上花钱。
2. **也不是那个源时刻的内容成本**：ffmpeg 在 4 个时刻的首帧都是 120–130 ms。
3. 剩下的真问题是两类：**冷开剪切点**那一笔（`frame_cost.max` 100–150 ms，已由 warm-ahead 压过一半，
   P-84 定过"载荷是首关键帧解码"）与**与提前量无关的 >100 ms 到货**（新暴露，未归因）。
4. 下一刀（任务 #3）：把每次 push 拆成 `await_ms`（阻塞在 `sink.samples()` 内＝Chrome 的取字节+解封装+解码）、
   `convert_ms`（`toVideoFrame`+`createImageBitmap`）、`park_ms`（队列满），
   并用网关日志的时间戳问一句"这段 await 里到底有没有请求"——那是 Python 还能被牵连的最后一条路。

## P-96 2026-10-28 S1+S2 仪表落地：一次 push 拆成三段，网关按 epoch 毫秒逐窗相交

### 代码落点（在册文件）
`player/player.html` 1999 → 2136 行：`SPLIT_ON`（:706，`&split=0/1` 默认开）、
`slowLegs = {gaps, over, dropped, rows, cap:200}`（:712）、`makePump` 两条臂（:723-759 = **改前原样**，
冻结不动，当新通路自己的负样本；:760-848 = 手动 asyncIterator 三段拆分，`await_ms` 在 `it.next()` 上、
`convert_ms` 在 `toVideoFrame`+`createImageBitmap` 上、`park_ms` 在队列满等待上，:848 `finally { await it.return(); }`
复现 `for await` 在 break 时的清理语义）、双口径记账 `wp = tArr_i − tArr_{i−1}`（旧，逐毫秒可比）与
`np = wp − park_{i−1}`（新）+ `other = np − await − convert`（:793-827），
`np > slowleg` 的腿进名单并带 `w0/w1`、`aw0/aw1`、`pw0/pw1` 三个窗与 `gen`/`warm`/`push_idx`/`age_s`；
报告新增 `arrivals_np`（按 `max_np` **排序**后取前 16，:1938）、`slow_legs`（:1941）、`switches`
（生效值 + `location.search` 原文，:1948）、`epoch_base`/`epoch_sent`（:2003 与 :2126，battery 与 liveplay 两条报告都回送）。
`scripts/preview_gateway.py` 384 → 455 行：`_note()` 每行 `epoch=<毫秒.毫秒> <HH:MM:SS> [run=<id>] <正文>`
（:120-144，二进制写 + 显式 CRLF 与历史一致，改名归档在 `LOG_LOCK` 内），`/report` 那行抄进
`epoch_base/epoch_sent/split`（:236-255），新增 `--log` / `--log-max-mb`（默认 64）/ `--run-id`（:408-412，:442 生效）。
跑测件在 `temp/`：`s1_split_ab.py`（每轮独立端口 + 独立日志 + run-id、`sync_player()` 逐字节同步并打 sha1、
臂序**按轮真交叉**、两臂之间 `S1_SETTLE=12 s` 空机）、`s2_window_intersect.py`。

### S1 验收（空载 4 轮：`warm_lead=0.3` 默认、整条时间轴 `seeks=0`、4 臂 `alive=4/4`、`warm used/started=22/22`）
点名 4 腿在 `&split=1` 臂（口径 = **该腿自己相邻两次到货的墙钟间隔**，n = 每轮间隔样本 2859 / 2862）：

| 轮 | gap_with_park | 同一事件的 `park_prev` / `await` / `convert` | age_wp / 到货序号 | **gap_nopark** |
|---|---|---|---|---|
| r1 | 384.0 / 339.2 / 328.8 / 307.6 | 383.3 / 0.0 / 0.7 … 307.1 / 0.0 / 0.5 | 0.067–0.077 s / 第 6 次 | 43.9 / 1.1 / 2.0 / 1.6 |
| r2 | 317.8 / 293.3 / 336.4 / 329.7 | 317.2 / 0.0 / 0.6 … 328.9 / 0.0 / 0.8 | 0.067–0.077 s / 第 6 次 | 29.6 / 0.8 / 1.0 / 3.7 |

⇒ **P-95 那句"park 被记成到货延迟"从推断升级为逐事件直读**：那 ~350 ms 的 **99.8% 是 `park_prev`**，
`await` 恒为 0，转换 ≤0.8 ms。
⇒ `gap_nopark` 名单不再钉在剪切点后第 4 帧：r1 前 10 的段内年龄 `0.234, 0.367, 0.035, 0.235, 0.234, 0.067, 0.367, 0.300, 0.267, 0.367` s
（60 fps 下 = 第 14,22,2,14,14,4,22,18,16,22 帧）、本泵到货序号 3–16 散布；旧口径 4/4 条仍全在 0.067–0.077 s。
⇒ **`&split=0` 负样本同框**：wp = 315.3/347.0/344.5/346.9（r1）与 330.8/326.7/327.2/307.9（r2），
`arr_max_wp` 352.4–369.3。判据没被仪表扰动：`frame_cost_ms` p95 = 15/16、max = 97/102（split=1）对
16/15、94/102（split=0），`fresh/s` 49.72/49.71 对 49.55，`decoded` 1866 对 1860，
`errors/tick_errors/black_streaks` 全 0。开关到达性由 `switches.split` 回映证明。

### S2 验收（口径 = **本轮自己的日志**，不是 P-95 那 376k 的聚合）
时钟错位先过：页 `epoch_sent` − 网关写该行 = **4.8 / 4.7 ms**（smoke 那跑 6.8 ms）。分母：腿侧间隔样本 2859 / 2862，
`np>100` 命中 **2 / 3**，`dropped=0`；请求侧 9361 / 9326 行（media GET 9272 / 9236、HEAD 78 / 79、POST 2、其它 9）。

| 轮 | 腿 | np | await / convert / park_prev / other | 窗内请求 | 窗内服务端最大 | 判定 |
|---|---|---|---|---|---|---|
| r1 | 658C39C6 (`C7817.420a.mp4`) | 229.0 | 228.8 / 0.2 / 0.0 / 0.0 | 7（同文件 2） | 0.54 ms | 有请求 |
| r1 | 2ABFF80A (`20261015_091037.420a.mp4`) | 127.6 | 127.4 / 0.2 / 30.1 / 0.0 | 0（放 50 ms 后 8） | — | 无请求 |
| r2 | 846DA305 (`C7901`) | 126.2 | 125.8 / 0.4 / 30.2 / 0.0 | 3（同文件 0） | 1.29 ms | 有请求 |
| r2 | 89614BA4 (`C8248`) | 121.6 | 121.2 / 0.4 / 28.8 / 0.0 | 2 | 0.68 ms | 有请求 |
| r2 | 555AA13A (`20261015_091037`) | 116.7 | 116.5 / 0.2 / 0.0 / 0.0 | 2（同文件 2） | 0.68 ms | 有请求 |

⇒ 5 条 = **4 有请求 / 1 无请求**，窗内服务端最大 **1.29 ms**；压力校验用 smoke 那跑的 35 条 `np>100`：
34 有 / 1 无，窗内最多 347 个请求而服务端最大仍只 **4.33 ms**。
⇒ **P-95 第 4 条留的"Python 还能被牵连的最后一条路"到此逐窗关闭**：`>100 ms` 的 `np` 100% 落在 `await` 窗
（`convert ≤0.8`、`other = 0.0` ⇒ 转换/上传那堆实测为空），而 `await` 窗里的服务端成本 ≤1.29 ms。
滚动开关单测通过（4 次改名归档、启动即归档旧文件、失败退避一个上限的量、`OSError` 不崩线程）；
`py_leg_probe.py` **不加改动**照样解析新行（p50 0.32 / p99 0.90 / max 2.40 / `ms>100` = 0）；
630 MB 的 `temp/playback-test/gateway.log` 未被写过（642,535,947 B，mtime 10:04 不变）。

### 三条给 S3 的口径警告（本轮踩出来的）
1. **`ms=` 记到发送循环结束，客户端不排空会把服务端 `ms` 一起撑大** ⇒ "窗内服务端慢"不能直接算网关的账；
   背靠背自伤那一轮里网关 `ms=` 被顶到 286 ms，就是这个效应的实尺。
2. `--split=0` 臂里 `max_np=0` / `gaps=0` 的含义是**未测**，不是"没有 park"；只能靠 `switches.split` 区分。
3. Chrome 连接池排队在服务器窗**之外**，"取字节 vs 解封装解码"这一刀只能靠同文件计数 + 放窗（`--pad`）+
   同刻在飞请求数去逼近，不是直接测量。

### 本轮被否证/修掉的错（就地记录）
1. 第一版三段只挂在"np 最大那一腿"上，于是点名腿读出 `park=0`，被误当成"没有 park"；真相是它记的是
   max-np 腿，而 350 ms 那笔属于 max-**wp** 腿。补 `park_at_wp` 等 `_at_wp` 后缀字段后证据形态才成立。
2. **又自伤一次（违反 P-94 那条纪律）**：smoke 把两臂背靠背连跑，第二臂撞在第一臂 Chrome 正在销毁的瞬间，
   `fc_max` 读到 **1515 ms**、间隔 5113/4423/2441 ms。加 `S1_SETTLE=12 s` 后两臂回到同一框（94–102 ms）。
3. `lead_ab.py:101-102` 注释写"臂序按轮次交叉"但代码是轮内同序，**并没有交叉**——P-95 里那句已在原处更正。
4. `_note()` 第一版在文本模式里用 `fh.buffer.write`，换行约定与历史文件不一致；改成二进制 + 显式 CRLF，
   并补了「网关写行 → S2 解析器」的往返测试。

### 门的状态
判据一个字没动（`frame_cost` p95 ≤ 33.4 / max ≤ 150，`scripts/playback_check.py:70-71`）。本轮只是单点
（`--repeat 1` 级别的 A/B 读数，非分布）：p95 15/16、max 97/102。**全量门回归与包络记录留给 S5。**

### S4 前置测量：代理的关键帧栅格（计划里那句"改前先量关键帧间隔"，2026-10-28 空载时量）
对象是 P-96 里 `np` 最大的两条腿所在的文件（`ffprobe -select_streams v:0 -show_entries packet=pts_time,flags`，
按 `-read_intervals` 只开窗采样，**覆盖 = 4 个窗共 601 个视频包**（300+1+150+150），不是整支文件；
其中 `C7817` 的 `18%+5` 窗只返回 1 个包——该文件只有 6.006 s，窗起点 1.08 s 后 `+5 s` 越过片尾，
这条读数**不计入结论**）：

| 文件 | 时长 | 帧率 | 窗 | 视频包 | 关键帧 | K 比例 | 字节率 |
|---|---|---|---|---|---|---|---|
| `C7817.420a.mp4` | 6.006 s | 60 fps | 0–5 s | 300 | 300 | **1.000** | 4.42 MB/s |
| `20261015_091037.420a.mp4` | 35.467 s | 30 fps | 0–5 s | 150 | 150 | **1.000** | 6.80 MB/s |
| 同上 | | | 6.38–11.38 s | 150 | 150 | **1.000** | |

⇒ **【本表的 `K 比例` 一列作废，读数更正 2026-10-29】**"K 比例 1.000 ⇒ 代理是全 I 帧（GOP=1）"这句**错了**，
错在探测输出的**列位**：我用 `-show_entries packet=pts_time,flags -of csv` 后把第三列当 flags 做 `index($3,"K")`。
真答案不必猜——造代理的脚本就写着配方（`temp/playback-test/make_all_proxies.py:38-39`）：
`-c:v h264_nvenc -pix_fmt yuv420p -preset p4 -cq 23 -force_key_frames "expr:gte(t,n_forced*1)" -b_strategy 0 -sc_threshold 0`，
即 **每秒强制一个关键帧**（60 fps ⇒ GOP≈60；30 fps ⇒ GOP≈30），**不是每帧一个**。
5 s 窗里原理上只有 ~5 个 K，我却读到 300/300 ⇒ **原理与读数矛盾时先怀疑读数**，这次是列位错，不是文件特殊。
⇒ **S4 的方向因此改回计划原句**：杠杆是**加长 GOP / 去掉强制关键帧**（现在每秒都付一次 I 帧的解码与字节成本），
而不是我之前写的"代理已无帧间结构可加"。时长/帧率/字节率（4.42 与 6.80 MB/s）来自 `stat` 与 `format` 直读，**不受本次列位错误影响**，仍然成立。
重测要求：探测要**先自证列位**——同一支文件改用 `-show_entries packet=flags -of json` 取字段，
并断言"窗内 K 数 ≈ 窗秒数"（配方就是每秒一个），对不上就报"探测无效"，**不许出比例**。
另记一条代价事实（给"要不要全量重编"定价用）：`make_all_proxies.py` 全量约 **10 分钟 GPU**、
`add_proxy_audio.py` 约 **30 秒**（视频流 copy），25 支 ⇒ `proxy/` 与 `proxy-a/` 各一轮（见本文件 695-698 行）。
⇒ 顺带一条**材料不一致**：这两条腿一支 60 fps、一支 30 fps（P-94 的 25 支普查里 18 支 59.94），
说明代理是按**源帧率**做的、没有统一栅格 ⇒ 每帧解码预算随文件而变，臂间比较时不能把不同文件当同一材料。
覆盖度限制：只证了这两支的 4 个窗，没扫全 49 支。

### S3 臂间读数（P-96 仪表的第一批产出；2026-10-29 落档，跑于 10-28 15:34–15:44）
证据：`temp/playback-test/s3-arms-summary-1534.json`（`rows` 8 条 + `arm_merged` + `per_run_detail`）、
`s3-run-1534.out`、每臂独立 `s3-gw-s31534r1*.log`。口径：整条时间轴 `seeks=0`、`&slowleg=30` 建册、
**三堆归属只在 `np > 100 ms` 上计**（`thr_ms=100`），分母 = 每轮自己的 `slow_legs.gaps`；
每臂 `switches` 回映生效值、点名腿 `4/4` 判活、`skew_ms` 3.7–6.7 ms（同机正常）；单臂墙钟 **42 s**。

| 臂 | n | `gaps` 合计 | `np>100` | 三堆 | `fc p95` | `fc max` | fresh/s | warm used/started |
|---|---|---|---|---|---|---|---|---|
| `base`（默认） | 2 | 5718 | 7 | **解封装/解码 7／取字节 0／转换 0** | 16, 17 | **138, 123** | 49.36, 49.39 | 22/22, 22/22 |
| `warm_lead=0.005` | 2 | 5726 | 3 | 解封装/解码 3／0／0 | 15, 16 | 135, 198 | 49.55, 48.87 | 1/1, 1/1 |
| `warm=0` | 2 | 4806 | 3, **40** | 同上（但见判废） | 16, **31** | 155, **2668** | 49.06, **32.25** | 0/0 |
| `qmax=1` | 2 | 1945+1821 | 0, **5** | — ／0／0 | **3**, 12 | 187, **479** | 51.09, **47.75** | 22/22 |

1. **归因与阶段 A 一致，且现在是 8 轮里全部命中**：`np>100 ms` 的腿**全部**落在解封装/解码窗
   （取字节窗 0、转换/上传窗 0）。⇒ 计划 S4 里"落在取字节窗/转换窗"两个分支**被读数排除**，
   只剩材料侧解码成本这一支。
2. **`r2` 最先跑的两臂判废、不进结论**（纪律：抓不到的写"样本不足"，不自洽的写"无效待重测"）：
   `r2qmax1` 读到 `arr_max_np=1119.5 ms`、`fc max=479` 而 `r1qmax1` 是 35 / 187；`r2nowarm` 读到
   `fc max=2668 ms`、fresh/s **32.25**、`decoded` 1211（base 同轮 1853）、`gaps` 1943（base 2857）
   ⇒ 播放头没走完时间轴，**这一臂连分母都不齐**。P-95 的 `warm=0` 只读到 203–249 ms，与 2668 ms
   差一个数量级，不能当成"关预热会崩"的证据。
   候选成因两条，都还没排除：① 那两个臂正跑在 15:43–15:44，盘上同一时刻出现
   `chrome-soak-s31534r2base/optimization_guide_model_store/...` 与 `segmentation_platform/ukm_db`
   等**新 profile 首启后台任务**的写入；② 我这边当时并存两个 agent，计时轮次可能重叠（自伤那一族）。
   重测要求：同一 runner 各 +1 轮，跑前先把 soak profile 预热过一遍再计时。
3. **`slowleg=30` 与 `thr_ms=100` 是两个数**：册子按 30 ms 建（所以 `over30_recorded` 远大于
   `over100`），三堆占比只在 100 ms 上算；`per_run_detail` 里 `p95_of_recorded` 是对**册内条目**再算的，
   **不是**那 2.8k 个间隔的 p95（脚本自己在 `note` 里写了这条限制）。
4. `qmax=1` 那一臂重复了 P-87 的交换关系形态：`fc p95` 16→**3 ms**（躯体明显改善）但 `fc max` 反而
   187 ms 且 `over100` 帧数 3 —— 尾巴没买到，五个数要一起读。
5. 仪表本身在 8/8 臂上都工作：`split=true` 全部回映、`qmax=1` 的覆盖参数**没有被默认值遮蔽**
   （`switches.qmax=1` 且 `search` 尾部一致），`dropped=0` 全部通过。

## P-97 2026-10-29 S5 全量门回归 + 本 build 的包络（附 S3 判废两臂补测，与 `L4 live pacing` 那一红的归因）

跑次：**13:35:42–13:43 全量门**（不跳任何层、含 `--mixmode-gpu`、`--repeat 2`），
**13:27–13:33 一次 `--skip-jank --repeat 1` 短跑**（只为验证新加的三行 SKIP/分母牙齿），
之后是归因补测与阶段 B。成片 oracle 行内传（`JY_ORACLE_MP4` 在 User/Machine 两个作用域都是空的）。

### ① 门的逐层结果（`temp/playback-test/gate-p97-full.txt`，rc=1）

| 层 | 结果 | 关键分母 / 读数 |
|---|---|---|
| `L0 tracked player in place` | PASS | `player/player.html` → `temp\playback-test\player.html` 127,261 B，逐字节相同（sha1 `ea07bd08…`） |
| `L1 errors/warnings` | PASS | errors 0 / warnings 0 |
| `L1 geometry channel` | PASS | clip 99/136 段，104 段，49 个 media（missing 0、unreadable 3） |
| `L1 track coverage` | INFO | video 27 / text 40 / audio 37 段，未路由 0 |
| `L1 carrier freshness` | PASS | 1 个 face，`exists=true` 但盘上没有 0 |
| `L2 pixel layer` | PASS | `check-1.00s.png` vs `oracle-frame-33.png`：盒/心最大偏移 0.01（≤0.02）over 139,936 px；ink ratio 0.964（只观察不判） |
| `L3 video band` | PASS | `--video-scan 0.05:0.55:0.05`（11 个 t 取 argmax）t=0.05 corr@32px 0.725（≥0.6），corr@1px 0.461，未遮罩 0.628，rmse@32px 34.1 |
| `L4 continuous playback` | PASS | median 30 fps（≥24），min 29.62，**n=2** |
| `L4 seek` | PASS | 每跑 12 次 seek；per-run median 的中位 35.1 ms（≤150），worst 35.1，n=2 |
| `L4 first frame` | PASS | median 217.6 ms（≤300），spread 176.6–217.6，0/2 超线 |
| `L4 Range streaming` | PASS | median 3,350 个 Range 请求 / 10,000 ms 窗 |
| `L4 frame budget (whole timeline, tail not mean)` | PASS | n=1126 p50=1 p90=10 **p95=16 max=107**（线 33.4 / 150）；>33 ms 18 帧、>100 ms 2 帧；Σover-budget 553.6 ms；重复上一帧 94 次；新帧 49.21/s；预热泵 22/22 被到点取用（开=True 白热=0 废=0）—— **门内单点**，见 ② |
| `L4 live pacing + A/V residual` | **FAIL** | n=662 帧（正常 1060±）gap p50=33 p95=45 **max=796 ms**；音画残差 max 111 ms（线 50）；**paint p50=1516 / p95=17011 ms**；tick 错误 0 —— 归因见 ④ |
| `L6 no silent black frame` | **FAIL** | 0/2 电池跑 + **1/2 整条/直播跑**：`直播节奏: ['846DA305']`（同一条直播跑，见 ④） |
| `L5 mixer` | PASS | 0/2 跑有 audio_errors，rates_seen [44100, 48000] |
| `mix headroom (no agreed basis, Q-8)` | INFO | peak_fs [1.1415, 1.1891]；≥1 个满刻度窗的跑 2/2 |
| `session memory (600 s criterion is separate)` | INFO | rss-check0：first 4 / mean 786 / **peak 1016** / last 930 MB |
| `L10 browser pixels` | **FAIL** | `--shot-times` 用默认 **1.0, 6.633, 20.23**：t=1.0 跨通道 0.945（<0.95 ⇒ 红，F-084 字体天花板）、对成片 0.965；t=6.633 0.972 / 0.932（不红）；t=20.23 0.989 / 0.952 |
| `L6 guard has teeth` | PASS | `model-blacktest.json` → `black_streaks ['25BAD37B']`（非空＝牙齿还在），fps 仍 29.99 |
| `L9 cross-channel curve parity` | PASS | curves loaded=True，浏览器报 7 段，不一致 0 |
| `L7 mixmode shipped GLSL` | PASS | `MultiplyBlendPreMul` kept 771 B / shipped 1067 B / vendor `afcf75d2…` |
| `L7 mixmode wiring` | PASS | 6/6 |
| `L7 mixmode browser wiring` | PASS | 建出 1 个滤镜，23 个应挂段挂 1 个节点；未知包 md5 降级且不挂节点 |
| `L7 mixmode GPU three-way` | PASS（`--mixmode-gpu`） | 10 模式从表读，0 越界 |
| `L8 curves table rebuilt` | PASS | 预设 3，覆盖 8/33 段（`animation_segments=33`） |
| `L8 animation wiring` | PASS | 5/5 |
| `L8 typewriter wiring` | PASS | assertions 14 / problems 0 / segments 14 / carrier_tables_ok=True（**历史红 `A4` 本轮没出现**，那条素材资源项本轮成立） |
| `L11 flash in/out A/B` | PASS | 16 帧：窗内 9（曝光 9 / 模糊 7）、窗外 7；曝光变坏 0 / 模糊变坏 0 / 持平 0 / 窗外位移 0 / 降级 0 |

**计数怎么读**：脚本打的是 `25 of 28 checks passed, 3 FAILED`。这 28 = **22 条真判绿 + 3 条 INFO + 3 条红**，
`len(checks)-len(failed)` 把 INFO 也算进"通过"；这一跑 **SKIP 0 条**，所以"25/28"这一次确实等于"全部测过"。

**SKIP 牙齿的验证跑**（`gate-p97-skipcheck.txt`，`--skip-jank --repeat 1 --mixmode-gpu`，其余参数同上一字不差）：
`L4 frame budget` 与 `L4 live pacing` 各留一行 SKIP（`playback_check.py:482/528` 的文案在盘上对得上），
`L6` 打成 `0/1 电池跑 + 0/0 整条/直播跑 …；整条/直播跑缺 2 条（--skip-jank），分母随之缩小`（:536-546 的新牙齿）；
总计数 `27 of 28 checks passed, 1 FAILED` ⇒ 27 = 22 PASS + 3 INFO + **2 SKIP**，
**"27 未失败"不等于"27 测过"（真测过 22 条）**，这条差异就是要防的假绿。该跑红的也只有 `L10 t=1.0`。

### ② `L4 frame budget`：门里是单点，本轮补到 4 个点（`temp/playback-test/p97-jank-repeat.py`）

更正一条仪表事实：**`--repeat 2` 不重复这一层**——`battery(..., "jank")` 在 repeat 循环之外
（`playback_check.py:456-458`），`--repeat` 只把 10 s 电池跑两遍。所以门面上的帧预算是 `--repeat 1` 单点。
补测用同一个 URL 形态（`autostart=1&model=model-proxy-a.json&playms=37533&seeks=0&fps=30&qmax=4&pool=4&loop=1`），
每条臂前用 `about:blank` 预热本 tag 的 profile、臂间 settle 15 s：

| 跑 | n | p50 | p90 | p95 | max | >33 ms | >100 ms | Σover-budget | fresh/s | warm used/started（白热/废） | stale_holds | fc worst 帧的播放头 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 门 13:37 | 1126 | 1 | 10 | **16** | **107** | 18 | 2 | 553.6 | 49.21 | 22/22（0/0） | 94 | 107@22.51, 103@13.61, 96@1.81 |
| p97jank1 14:03 | 1126 | 1 | 9 | 16 | 110 | 19 | 1 | 499.3 | 49.44 | 22/22（0/0） | 85 | 110@1.82, 79@34.31, 78@3.84 |
| p97jank2 14:05 | 1126 | 1 | 10 | 16 | 109 | 15 | 2 | 501.5 | 49.50 | 22/22（0/0） | 83 | 109@1.81, 103@1.82, 90@30.55 |
| p97jank3 14:07 | 1126 | 1 | 9 | 16 | 101 | 16 | 1 | 397.2 | 49.73 | 22/22（0/0） | 74 | 101@1.81, 77@3.84, 77@18.24 |

判定：**连续绿**（4/4 过线，p95 恒 16 = 判据 33.4 的一半，max 101–110 距 150 还剩 40–49 ms，
`warm 白热=0 废=0` 说明不是"预热没跑"凑出来的达标）。
**字段口径（S5 要求把 `frame_cost` 的分布写清，这里把列名绑回报告字段）**：上表 n/p50/p90/p95/max/
`>33 ms`/`>100 ms`/Σover-budget 全部来自页面自报的 `play.frame_cost_ms`（对应键
`n, p50, p90, p95, max, over_33ms, over_100ms, over_budget_ms`，单位 ms；"fc worst 帧"是同一对象里的
`worst[]`，取 `frameCost` 按第 0 位降序前 10 条，位次语义照 `player/player.html:1891-1894`：
`[当帧耗时 ms, 播放头 s, Δrequests, ΔframesDecoded, ΔpumpStats.waits_ms, Δsync_fallbacks, 本帧最慢两条腿 [id, ms]]`
（**我第一版把第 3/4 位写成"重复上一帧次数/新到的腿数"，是照读数格式猜的，已按代码更正**）；fresh/s =
`play.fresh_track_frames_per_second`；warm 四个数 = `play.warm.{used,started,wasted,dropped}`；
stale_holds = `play.pump.stale_holds`。逐跑原始 JSON 在 `temp/playback-test/report-*.jsonl`
（按 tag 分文件），表由 `temp/playback-test/p97-jank-repeat.py` 汇总；**这些是"整条时间轴、`seeks=0`、
每跑 n=1126 帧"的分布，不是 10 s 电池口径**——两套口径不许混引。
**但同一份代码在仪表开满的配置里仍是边缘绿**：P-96 的 S3 `base` 臂（同播放器 + `&slowleg=30&probe=…`）
读到 max **123 / 138**，距 150 只剩 12 ms；150 这条线本轮一个字没动，也不许为过关上移。
最差帧的落点里有 `1.81/1.82`（剪切点首关键帧，P-84 定过载荷）也有 22.51/13.61/30.55 ⇒ 名单没有钉回"剪切点后第 4 帧"，S1 的验收形态在本 build 保持。

### ③ 两把尺子：`peak_fs`（照抄成片）与 RSS（按 peak）

**口径① 音频削顶**：不设 ≤0 dBFS 线、不加限幅、不写"电平已对齐"。
- 本 build 我方：整条时间轴那跑 **1.2938 = +2.20 dBFS**；门内电池两跑 1.1415 / 1.1891 = +1.14 / +1.50 dBFS；
  三次补测整条跑 1.2095 / 1.2702 / 1.2362 = +1.65 / +2.04 / +1.84 dBFS；`--skip-jank` 短跑 1.1452；负样本 fixture 1.471（不进包络）。
- 成片侧在册读数：**+2.98 dBFS**（linear 1.4099；7629 个 ≥0.9995 的样本）。
- **判定：与成片同向（5/5 都超刻度、都比我方"该不该削顶"的旧线之上），最响的那条腿差 0.78 dB（整条时间轴口径，我方更低）；10 s 电池口径差 1.48–1.84 dB。**
- 口径限制（必须一起读）：我方 `peak_fs` 是页内 analyser **轮询采到的样本峰**，`clipped_windows` 是 `pk ≥ 0.999` 的**窗计数**（本轮 36 / 47 / 126–147），与成片那次逐样本 `≥0.9995` 的 7629 不是同一把尺，**不能对数**；窗对窗（同窗 RMS/同窗峰）本轮没做，需要成片的 float 逐窗解码，留给下一刀。

**口径② 会话内存按 peak ≤ 2 GB**（不用 median / p95）：
| 读数 | peak MB | 判定 |
|---|---|---|
| 门 电池 check0 / check1（**n=2**，10 s 窗） | 1016 / 1075 | 绿 |
| 门 整条时间轴 jank | 1054 | 绿 |
| 补测整条时间轴 ×3 | 1202 / 1235 / 1229 | 绿 |
| 门 负样本 check-neg | 1482 | 绿 |
| 门 L10 shot | 806 | 绿 |
| S3 补测 nowarm / qmax1 | 1198 / 997 | 绿 |
| 独立 live 补测 split=0 ×2 | 1315 / 1194 | 绿 |
| 独立 live 补测 split=1（干净那跑） | 1248 | 绿 |
| **独立 live 补测 split=1（两次 stall 态）** | **2414 / 2918** | **破线** |
| **门内 live pacing 那一跑（污染态）** | **6251**（median 2409、24/48 s 超 2048、净增 3867 MB；renderer 4440 + gpu 1758） | **破线** |

判定：**13 个读数 ≤1482 MB（余量 ≥28%），3 个破线且全部落在 `drive=timer` 那条 live 路径的 stall 态**
（两次独立复现里膨胀的是 `gpu-process`：1792 / 2213 MB vs 干净跑的 390–547 MB）。
600 s 单跑的在册参考 1767 MB（余量 ~14%）**本轮没有复跑**（本轮最长窗 49.8 s），所以"600 s 会话 ≤2 GB"这条线
本轮**没有被证明也没有被推翻**，只是把风险点从"时长"挪到了"live 路径的 stall 态"。

### ④ 仪表改动是否带红了别的层：红了 `L4 live pacing` 与 `L6`，归因到"污染态 + 样本不足"

红的就是这两层，且是**同一跑、同一阶段**（`L6` 的 `['846DA305']` 来自 `L4 live pacing` 那条直播跑）。证据链：

1. **门内那一跑不可复现**。同 URL 形态在空载 + profile 预热 + 臂间 settle 下独立补测 5 次
   （`temp/playback-test/p97_live_ab.py`，臂序 split=1→0→1、再 0→1）：

| 跑 | frames | gap p50/p95/max | >100 / >200 ms 的 gap 数 | paint p50/p95/max | warm used/started（白热） | black_streaks | RSS peak |
|---|---|---|---|---|---|---|---|
| 门内 13:38（污染态） | 662 | 33 / 45 / **796** | 6 / 4 | **1516 / 17011 / 20952** | 7/24（**白热 16**） | `['846DA305']` | 6251 |
| live1a split=1 | 1040 | 33 / 42 / 776 | 1 / 1 | 2 / 31 / 119 | 21/21（0） | [] | 2414 |
| live0 split=0 | 1061 | 33 / 42 / 65 | 0 / 0 | 1 / 18 / 110 | 22/22（0） | [] | 1315 |
| live1b split=1 | 1051 | 33 / 44 / 254 | 2 / 1 | 2 / 46 / 955 | 22/22（0） | [] | 2918 |
| live0b split=0 | 1062 | 33 / 42 / 48 | 0 / 0 | 1 / 17 / 108 | 22/22（0） | [] | 1194 |
| live1c split=1 | 1062 | 33 / 42 / 48 | 0 / 0 | 1 / 17 / 107 | 22/22（0） | [] | 1248 |

2. **`&split=0` 是 P-96 冻在 `player.html:723-759` 的改前原样，天然负样本**（`switches` 全部回映、
   `search` 里 `split=` 只出现 1 次）。split=1 三次里两次带一条 >150 ms 的 gap（776、254），split=0 两次都干净（65、48）；
   但 2/3 对 0/2 的差异在 Fisher 上 p≈0.5 ⇒ **不足以定论"是仪表的尾巴成本"**，按纪律写**仍未归因**。
   `L4 frame budget` 那一层（同一批新代码、整条时间轴、4 个点 101–110 ms）没有对应的退化，
   所以这不是"新泵在整条路上都慢"，而是只出现在 `drive=timer` 的重入 tick 路径上。
3. **网关不是原因**：干净 5 跑的服务端最大 1.58–5.74 ms；门内污染跑那 48.4 s 窗内 6,845 请求、
   服务端最大 **148.30 ms**（4 条 >50 ms），且最后 9 s 请求流几乎断流（0–5 请求/s、最大空档 3.62 s）。
   这是 P-96 警告①的反证形态（客户端不排空把服务端 `ms` 一起撑大），不是服务端成本；判据 `arrivals` 依旧不作数。
4. **【就地更正 2026-10-29 17:45】我上一条写的"门自身的结构问题＝阶段之间没有 settle"被 #6 的 A/B 否证**：
   定点小跑 20 次（两段链与四段链复刻门序，各 5 对 5），**0 次**复现 P-97 的污染态
   （662 帧 / paint p50 1516 ms / warm 7/24），交界探针 `pre_alive_procs_at_B_start` **恒为 0**——
   因为 `browser_soak.py:124-134` 的 terminate 与子进程回收是**同步**的。
   ⇒ "没有 settle"**不是那三红的充分原因**；settle 只剩"降低顺序耦合"的防御价值，**牙齿未证明**。
   那三红现在的状态：`L4 live pacing` 与 `L6` 在**两次全量门复跑里都绿**（`gate-t6-full2.txt`
   **27 of 28、1 FAIL、SKIP 0**，真测过 24 条；live pacing n=1062、gap 33/43/48、paint p50 1；
   L6 0/2 电池 + 0/3 整条/直播，且 `L6 guard has teeth` 仍打到 `['25BAD37B']`），
   唯一稳定红仍是 `L10 t=1.0` 0.945（字体天花板，线不动）；`L7 mixmode GPU` 在第一跑红一次、
   单跑 rc=0 且第二跑 PASS ⇒ 一次性失败，**未归因**。
   教训：**负样本探针从不触发的 A/B 什么也没排除**——它只证明了"我造不出那个条件"，
   而不是"那个条件无关"（同族：P-80 守卫自蒙、P-55 零断言真空通过）。

**一句话结论**：S1+S2 的仪表改动**没有把别的层带成真实回归**——`L4 live pacing` / `L6` 那两红钉在"污染态 +
样本不足"（独立复测里 split=1 也有一次全绿 48 ms），`L4 frame budget` 与其余各层在改后仍绿，
`L6 guard has teeth` 的负样本仍打得响（`['25BAD37B']`），唯一"新红且不是仪表的账"的是 `L10 t=1.0`（F-084 字体天花板，行不在我方）。

**外部负载声明（空载的边界）**：本机 15.8 GB RAM。阶段 A 与两次归因补测期间，一个**非我启动**的
`<DRIVE_D>/Agents\<外部进程>` uvicorn（PID 31360，13:31:53 起，累计 173 s CPU）一直存在，所以"机器空载"只对
"我这边不并发 ffprobe/ffmpeg/别的探测"成立，对整机不成立——这也是那两次 `gpu-process` 膨胀不能全部记到仪表头上的理由之一。
另有 10-26 遗留的三个 idle `preview_gateway.py`（8826/8827/8828，WorkingSet 已为 0），按"只停自己启动的 PID"没动它们。
本轮我启动的 Chrome / 网关 / ffmpeg 在收尾时计数为 0。

### ⑤ 阶段 B：S3 判废两臂各补 1 轮（跑前预热 soak profile）

同一个 runner `temp/playback-test/s3_arms_ab.py`，为补测加两个**默认关闭**的环境变量（历史行为不变）：
`S3_ARMS="nowarm,qmax1"`（只跑点名的臂）与 `S3_PREWARM_S=30`（计时臂之前用**同一个 `chrome-soak-<tag>` user-data-dir**
以 `about:blank` 空跑 30 s，把新 profile 首启的后台任务——`optimization_guide_model_store/…`、
`segmentation_platform/ukm_db`——挪出计时窗），臂后仍走 `S3_SETTLE=15`。
命令：`S3_ARMS="nowarm,qmax1" S3_PREWARM_S=30 python temp/playback-test/s3_arms_ab.py 1 1410`；
臂形参与 1534 那跑一字不差（整条时间轴 `seeks=0`、`&slowleg=30`、`&probe=6BDF37C1,9F18A357,845C3CB8,14D93F1F` 判活 4/4、
`switches` 回映、单臂墙钟 42 s、`skew_ms` 4.1 / 3.8 ms）。

| 臂 | 本轮（1410，预热+settle） | 1534 的**有效轮** | 1534 的**判废轮** | 判定 |
|---|---|---|---|---|
| `nowarm` | gaps 2864、decoded 1846、fresh/s 49.15、fc p95 16、**fc max 147**（`over_100` 4 帧）、np>100 = 2（134.0 / 120.6）、`arr_max_np` 134、warm 0/0、三堆 `fetch 1 / demux_decode 1` | r1nowarm：2863 / 1842 / 49.06 / 16 / 155 / 3 条（135.7, 118.2, 107.3）/ 135.7 / 全 demux_decode | r2nowarm：1943 / **1211** / **32.25** / 31 / **2668** / 40 条（top 3367.7） | **有效**（分母与有效轮同框） |
| `qmax1` | gaps **1942**、decoded 1915、fresh/s 51.00、fc p95 **3**、fc max 138（`over_100` 3 帧）、np>100 = **0**、`arr_max_np` 40.5、warm 22/22、三堆空 | r1qmax1：1945 / 1919 / 51.09 / 3 / 187 / 0 条 / 35.1 / 空 | r2qmax1：1821 / 1793 / 47.75 / 12 / **479** / 5 条（1119.5） | **有效**（与 r1 同框） |

1. **两条判废读数被确认为污染**：预热 + settle 后两臂都回到有效轮的同一框（147 vs 155；138 vs 187；
   `arr_max_np` 134 vs 135.7、40.5 vs 35.1）。⇒ 2668 / 479 / 3367.7 **不能**当"关预热会崩"或"qmax=1 会崩"的证据；
   反过来也不能用它证明 `warm=0` 安全。
2. **修掉 P-96 的一条判读规矩**：那句"`gaps` 必须与 base 同量级（≈2.8k）才算有效"在 `qmax=1` 这一臂上是错的——
   它的**有效轮**本来就 1945、判废轮 1821（同一臂的两个轮子都是 ~1.9k），所以 `gaps 1943` 本身不是"播放头没走完"的证据。
   本轮改成 **`gaps` + `decoded` + `fresh/s` 三件同时对齐**才判有效（r2nowarm 的 decoded 1211 / fresh/s 32.25 才是实质缺失）。
3. **三堆占比更新（累计 15 条 `np>100` 的腿）**：`demux_decode 14` / `fetch 1` / `convert 0`。
   唯一那条 fetch 是 nowarm 补测里的 `C3A2FDAE`（`IMG_7322.420a.mp4`，np 134.0、await 133.7、convert 0.3、
   窗内 139 个请求、**服务端最大 1.51 ms、合计 71.4 ms**）。`s3_classify.classify_leg()` 的规矩是
   `Σ服务端 ms ≥ 0.5×np` 就判取字节窗（:142-143），而 139 个**并发**请求的"和"当然接近窗长，单请求并不慢 ⇒
   这条应按 P-96 警告③读作"连接池/并发排队"，不是网关成本。**规则本身要修**（改用 max 或按请求数归一），
   S4 动手之前定；本轮不动它，读数照实记。
4. `warm=0` 在有效样本上现在是 **3 个点**：155 / 147（与 P-95 的 203–249 同向）——"关预热让尾巴变长"成立，
   "关预热会崩（2668）"不成立。`qmax=1` 重复的是 P-87 的交换形态：`fc p95` **3 ms**（躯体最好）但 max 138 ms、
   `over_100` 3 帧 ⇒ 五个数一起读，尾巴没买到。

### ⑥ 哪些数是 `--repeat 1` 单点、哪些是分布（S5 要求明写）

- **n=2 分布**（门的 `--repeat 2` 覆盖的那批）：`L4 continuous playback` / `L4 seek` / `L4 first frame` /
  `L4 Range streaming`、`L5 mixer`、`L6` 的电池侧（0/2）、INFO 行的 `peak_fs [1.1415, 1.1891]`、RSS check0/check1。
- **n=4 分布**：`L4 frame budget` 的 p95 / max / Σover-budget / fresh-s / warm used+started+wasted（门 1 + 补测 3）。
- **n=5 分布**（独立补测，非门内）：live pacing 的 frames / gap p50-p95-max / paint / warm；门内那一跑是第 6 个点，
  属污染态，**不进稳态包络**，只在 ④ 单列。
- **n=2 有效**（阶段 B 之后）：`nowarm`、`qmax1` 各有两个有效轮（1534 r1 + 1410 补测），另有各一个判废轮在册。
- **单点（n=1）**：`L2` 像素、`L3` band（11 个 t 取 argmax，是**扫描**不是时间分布）、`L10`（3 个时刻各 1 帧）、
  `L11`（16 帧）、`L7` GPU 三方（读表）、`L8` 三层（非计时）、S3 两臂的三堆占比、每个阶段的 RSS。
- **本轮没有复跑**：600 s 会话内存判据、`--repeat 5` 级别的分布。

### ⑦ 本轮被否证 / 修掉的错（就地记录）

1. **630 MB 的 `temp/playback-test/gateway.log` 被工具自己的 S2 滚动改名了**（我没整读、没删、没当分母）：
   为确认"门起网关时会不会在 `configure_log()` 里崩"，我跑了一次 3 s 的网关 smoke（13:27:18），
   `configure_log()` 在启动时发现 642,535,947 B > 默认 64 MB 上限 ⇒ `_roll()` 把它**改名**成
   `gateway.20261029-132718.339.log`（字节数 642,535,947、mtime 2026-10-28 10:04:16 都没变，历史完整）。
   我的判断缺口：**明知有 `--log-max-mb` 的启动即归档行为，还在门前面用默认路径起了一次网关**。
   此后所有计时轮次都走独立 `--log`（`p97-gw-*.log`、`s3-gw-*.log`），只有门本身仍写默认路径（不改判据层代码）。
2. **`--repeat 2` ≠ 帧预算跑两遍**（见 ②）。我在计划里把 S5 的 `--repeat 2` 当成了 `L4 frame budget` 的两个点，
   实际门内只有 1 个；本轮补跑到 4 个点才敢说"分布"。
3. **P-96 的判废理由之一被否证**：`gaps 1943 ⇒ 分母不齐`（见 ⑤ 第 2 条）。
4. **"np>100 全部落在解封装/解码窗"这句太强**：补测后是 14/15，那 1 条还是 `Σ服务端 ms` 规则的产物（见 ⑤ 第 3 条）。
5. **归因 A/B 跑测器的第一版开关拼接有死开关形态**：`P97_ARMS` 解析曾把输入拼成 `&split=&split=0`
   （同名两次 = P-83/P-87 那一族）。跑之前发现并改成 `tag=0/1` 白名单 + 重复 tag 直接 `SystemExit`；
   实际用的两轮里 `split_count_in_search` 全是 1，已写进 `p97-live-ab*.json`。
6. **没有需要作废的自伤轮次**：阶段 A 与阶段 B 期间我这边没有并发 ffprobe/ffmpeg/别的探测。
   但 ④ 的门内 live 那一跑**是我的读数历史里第一个"由门的阶段间隔没有 settle 造成的污染态"**，
   它已在 ③④ 里按污染态处理（不进包络、只单列），不作为"回归证据"，也不作为"无回归证据"。
7. 只读核实：`<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>\draft_content.json` 1,048,432 B、
   mtime 2026-10-15 17:03:19，本轮未变（草稿只读约束保持）。

### ⑧ 证据文件（全在 `temp/`，不进代码历史；文档本条待用户同意后才提交）

`gate-p97-full.txt`（末行 `RC=1`）、`gate-p97-skipcheck.txt`、`p97-baseline.json`（跑前快照：`report-playback.jsonl` 192 行、
`report-livepacing.jsonl` 17 行、`run_t0=1793252142.463`）、`p97_envelope.py` + `p97-envelope.json` + `p97-envelope.txt`、
`p97_jank_repeat.py` + `p97-jank-repeat.json` + `report-p97jank{1,2,3}.jsonl` / `rss-p97jank{1,2,3}.txt` / `p97-gw-p97jank{1,2,3}.log`、
`p97_live_ab.py` + `p97-live-ab.json` / `p97-live-ab2.json`（+ 两个 `.out`）+ `report-{live1a,live0,live1b,live0b,live1c}.jsonl`
+ `rss-*.txt` + `p97-gw-*.log`、`s3-run-1410.out` + `s3-arms-summary-1410.json` + `s3-gw-s31410r1{nowarm,qmax1}.log`
+ `report-s31410r1{nowarm,qmax1}.jsonl`、`browser-shots.json`（mtime 13:40:21）、`gateway.log`（13:27 之后新写，约 5.98 MB）
与归档 `gateway.20261029-132718.339.log`。

**下一刀（S4）的读法已经定了**：三堆里只剩材料侧解码成本（`qmax=1` 不买尾巴、`warm=0` 让尾巴更长），
所以 S4 只能动材料侧（代理的 GOP/码率/空间分辨率，见 P-96 的 S4 前置测量），
并且**先给门补相邻阶段的 settle**，否则下一次 `L4 live pacing` 的红还是要靠人肉复测来定性。
