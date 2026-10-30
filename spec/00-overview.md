# 剪映草稿格式规格（M1 产出）

目的：让一个 Web 剪辑软件在**不打开剪映**的情况下，把剪映草稿读成可渲染、可编辑、可安全写回的形式。
工程格式就是剪映草稿本身，不设中间格式；因此本规格 = 我们解析器与渲染器的唯一真相源。

范围约定：phase-1 只做**字幕**与**画面**，**调色跳过**（见 `scope-and-phases.md`）。

## 当前进度（2026-10-21）

| 里程碑 | 状态 | 产出物 |
|---|---|---|
| M0 授权与只读基线 | **完成** | `../evidence/scope.md`（含四路证据纪律）、40 文件 sha256 只读证明、两道硬门脚本 |
| M1 格式规格 | **完成，持续修订** | 本目录 `spec/*`（权威）+ `format-reference.md`（总表）+ `../evidence/tables/`（派生表），r3 冻结口径 1,475 目录 / 2,050 份去重内容 |
| M1-D 渲染基座 | **定案：双通道**（2026-10-21 用户裁定**保留 web 方案**：seek 不达标不改评服务端播放通道，改由素材侧可硬解 profile 达标） | `../base-selection.md`（候选与许可核验、四条已测轴、§定案、依赖清单） |
| M2 渲染实现 | **首轮已落地，但门当前不是全绿**（2026-10-22/23；门已加到 18 层，L9 跨通道曲线一致 PASS、**L10 浏览器像素判据为红**——浏览器比通道 2 亮 ~1.8 码值，见 F-083/U-93；另有一条疑似我自己引入的 2 GB 越线在归因中，P-36） | 前置条件：① 要求 1 的混合模式数值等价（**已闭合于通道 2：F-077 判定 + F-079 实现与双向验证，门 L7 三层 16/16**；浏览器侧待接 U-92）；② **seek 达标路径**——F-054 已把答案从「关键帧索引」改判为「把素材搬进可硬解的 profile（代理 4:2:0）」，索引改记为首帧与尾部 moov 的手段；**SP-09（代理片能否把 seek 压进 150 ms）自 2026-10-21 用户裁定起是唯一达标路径**，未测即开工 M2；③ **网关 keep-alive / 多端口**（**已测，SP-04 结案**）：单次 seek 触发 11–62 个闭区间请求，而真负载最近 30 分钟 **141,655 条请求里复用率 99.9%**（代理与本机缓存都 99.9~100%），L4 seek 同时达标 30~39 ms ⇒ 前置条件由现行网关+Chrome 满足；**多端口不再需要**（未做也无从触发）。P-08 的「NAS 上复用反而慢」未被推翻，缺的是逐请求延迟——网关已补 `ms=`，下轮可复算；④ **多轨混音器**（用户裁定预览就要全混音；相机片音轨是未压缩 PCM，`AudioDecoder` 不接，须按样本翻端序直接填 `AudioBuffer`，F-053 §4） |
| M3 写回 | **未开工** | 依据 `write-rules.md` + `crypto.md` §5；先决条件是 U-57 的候选名修补与 r4 重冻结（需用户同意）。**2026-10-28 已在草稿副本上做过一次受控写入**（转场 / 第二条 video 轨 / 片段级 `audio_fades`）：结构校验与回读通过、画中画有通道 2 像素证据，**剪映重开是否报修复仍未验**（`../evidence/writeback-experiment.md`） |

**基座六条判据现状（2026-10-21 按 F-053/F-054 更新）**：连续播放 / 内存 / Range / 多路合成 **达标**
（后两条见 F-043，带 GPU 才算），**只剩 seek 不达标**，且现在**两条解法都被实测证伪了一半**：
服务端改响应头/缓存/钳位无效（F-045），播放器换成「sample table + 闭区间取块 + WebCodecs」也无效
（F-054：相机片 207.6 / 257.8 ms，与裸 `<video>` 同量级）⇒ 成本是 `GOP/2 ÷ 管道fps` 的**结构项**
（GOP 实测 1 秒、moov 13/13 在尾部，F-053），达标的杠杆是**可硬解的 profile** 而不是索引。
**首帧**从 85–110 ms 刷新到 **2.7–35.7 ms**（F-054）；**U-59 结案**：NAS 首帧不是取数字节的问题
（首帧本来就 2 个请求、0.5–5.9 MiB），是每请求重连 + SMB 重开文件。
HEVC 原判「不可用」由 F-044 更正为可用，但 F-054 加回一条限定：**只在有硬件通路时可用**——
无通路时不是慢而是**直接抛** `cannot be decoded in this environment`（容器解析照常成功），
这反而是本项目第一次拿到的显式能力信号。

**挂着的活**（按性价比排序，2026-10-21 按 F-053/F-054 重排）：

1. 混合模式与 `*BlendPreMul` GLSL 的数值等价（要求 1，M1 唯一未证的基座判据；`.frag` 明文与 `pixi.js@8.22.0` 都已就位）。
2. **网关 keep-alive / 多端口对照实测**（SP-04，F-054 把它从优化项升级为自建管线的前置）：
   现 `media_server.py:119` 每响应都 `Connection: close`，而闭区间取块**单次 seek 就是 11–62 个请求**；
   顺带这是 NAS 首帧 +263 ms 的落点（F-053 §3 已排除"字节数"解释）。
3. **多轨混音器可行性**（SP-10，用户裁定"预览就要全混音"）：模板取已归档的 `opencut-classic`
   `core/managers/audio-manager.ts`（时钟权威 = `AudioContext`、per-chunk BufferSource→gain→master、
   2 s 前瞻 + `waitUntilCaughtUp` 背压、generation counter 合并 seek）；**障碍已实测**：相机片音轨是
   `pcm_s16be` 未压缩 PCM，WebCodecs `AudioDecoder` 不接，必须按样本翻端序填 `AudioBuffer`（F-053 §4）。
4. 扫描器卫生（`scripts/corpus_scan.py` 的 `iterdir` 守卫、`.bak`/`template.json` 候选名、零行 hybrid 目录显式归类）
   + U-57 落正式结案条目 + 更正 F-033 里 `10月19日 (2)` 的时间线条数（磁盘实测与文档记数不一致）。
5. 帧工具开工（把 `temp/px-probe/spike_pipeline_rate.py` 的通道升级成 `scripts/` 里的正式工具；
   后端已按 F-042 定为 pin 路径的 ffmpeg.exe + `hevc_cuvid` 优先、软解回退、PyAV 备胎）；
   还欠 F-042 自记的那一项：**`hevc_cuvid` 只测过 `-f null` 解码上限，从未测过带消费者的端到端**（SP-07）。
   清点侧已有新工具 `scripts/media_probe.py`（标准库走 box + PyAV 取编码语义），SP-11 只差扩大样本面。
6. 可推迟：U-58（硬解与硬栅分离——F-054 已给出不经过 WebGL 的探针，只剩光栅那一格未单测）、
   SP-05 的 `nvidia-smi utilization.decoder` 直接见证、SP-12 的用户真机一分钟自检。
   ~~U-59（NAS 首帧预热窗口）~~ **已结案**（F-053 §3 + F-054：预取 MiB 的问法被证伪）。

**工件位置**：清点/解密/门禁工具在 `scripts/`（含 `jy_crypto/` 子进程 worker）；
探针 harness 与行值全在 `temp/px-probe/`（`temp/` 不入库，数字要能被 `check_doc_counts.py` 读到才落 `.txt`/`.json`）；
文档在独立的 `docs/` git 仓库里，提交用 `git -C docs`。

**唯一回归测试**（本仓库没有 pytest）：`python scripts/check_doc_counts.py`（exit 0；引用数必须能在冻结证据里找到，
找不到的要显式标口径）与 `python scripts/check_spec_yaml.py`；动扫描器后再加一条
`stats.json -> read_only_proof.unchanged == true` 与 `corpus` 自检。

## 阅读顺序

0. `format-reference.md` —— 上面这些文件的一页可读**总表**（按「读一个草稿的七步 → 容器 → 加密 → 骨架 → 层级 → 字幕 → 画面 → 预设 → 面板换算 → 写回 → 开放项 → 三十条不要用」归并）。
   它不新增事实：每条都指向下面的权威落点与 `../evidence/` 的 F-xx / U-xx 编号，**冲突时以那些文件为准**。改 `spec/` 的等级或数字时，本文件对应行必须同日改。
1. `layout.yaml` —— 目录布局、版本判别、活动时间线、副本与根镜像、绝不写入的目录
2. `crypto.md` —— 密文判定、DLL 发现与调用规格、副作用隔离、三条门禁
3. `timebase.yaml` —— 微秒、`target=source/speed`、ID 规则、帧量化容差
4. `materials.yaml` —— 实测 42 个 material bucket 与 phase 归属、引用完整性
5. `text.yaml` —— 字幕属性 → 渲染（含 `content` 二次解析、styles/fill/strokes/shadows/花字/动画）
6. `picture.yaml` —— 画面属性 → 渲染（clip、crop、speed、opacity、**混合模式**、蒙版、转场、关键帧、合成顺序）
7. `animations.yaml` —— 预设频次与预设包结构（曲线在明文 Lua + GLSL 里）
8. `write-rules.md` —— 写回不变式与事务（M3 实现依据）
9. `scope-and-phases.md` —— 阶段划分

支撑材料：`../evidence/findings.md`（Evidence→Finding→Path，F-001…**F-054**；F-019 是 r2 计数口径修订的根因条目，F-020 是 r3 复测批次与冻结，F-027 是 2026-10-18 构造样本差分批次（结案 U-01/U-26/U-39/U-42），F-028 是一次保存的文件级足迹，F-029 是样式开关载体与 `check_flag` 位表，F-030 是 `plain/` 残留明文抬高派生表分母的口径根因，F-031 是「居中」的两种落盘编码（结案 U-30），F-032 是位置的整数 px↔浮点换算律（结案 U-08），F-033 是它的成对观测与 per-timeline 画幅（结案 U-49，重键还原亦在其中观测），F-034 更正字号载体（`font_size` 只是镜像），F-035 用导出实测推翻 F-032 的渲染解释（位移是面板值的一半、y 轴向上），F-036 是渲染基座 spike 的字形轴（三基底都落在 ≤2 px 墨迹盒，字形保真不构成选型轴），F-037 立起服务端 PIL+ffmpeg 出图通道，F-038 判完浏览器解码轴的六条阈值（四条达标），F-039 就地更正 F-037 的两个数字（漏算 ffmpeg、把中位数当速率），F-040 是浏览器轴的体积与取块口径，F-041 把目录/副本普查三口径重排到 r3 并暴露 120 个「有 `Timelines/` 却枚举不到时间线副本」的草稿，F-042 更正服务端解码后端的依赖与速率口径（PATH 上已无 ffmpeg、硬解只认 `*_cuvid`、qsv 挂到超时，速率数必须带二进制路径/重复次数/分母口径），F-043 量完多路合成轴（判定配置带 GPU 59.98 fps / 1.29 GB 达标，软件光栅 14.95 fps 只是下界，瓶颈在帧到达而非合成），F-044 更正 F-038 的 HEVC 阴性（`--disable-gpu` 与 4 字节假 `description` 两个混淆，真 hvcC 下四个 `hvc1` 串全 True，能力探测必须用被测对象自己产出的配置记录），F-045 证伪 seek 的服务端两条候选（缓存与预取钳位都不改中位延迟，成本在关键帧定位与解码前进，U-55 收窄为播放器实现项），F-046 成对量完 NAS 轴（连续播放零退化、seek 只是加性上涨、首帧 2.7 倍破 300 ms 阈值 → 新开 U-59），F-047 用安装包内剪映自己的草稿层（`Resources/canvas_agent`，协议 `xmldraft/v1` + `wl0()` 草稿构造器）与 r3 规格做三方核对（对得上的 26 个同名字段全一致、0 冲突；补出 `draft_virtual_store.json`、「主轨 = `tracks[0]`」、版本轴与 `platform` 身份块两套 stamp → 新开 U-60/U-61），F-048 对冻结语料做独立全量重跑并深挖轨道/时间线层（八类轨道条数、51,718 片段、attribute 直方图、逐类型引用桶**逐位复现**；新测出「片段形状不由轨道类型决定」「素材语义在 bucket 的 `type` 上」「`render_index` 还有 15000/16000/19000 三个次带且 mixed 跨带」；就地更正 `picture.yaml` 的 clip/segment 计数、`common_keyframes` 数、U-14 陈旧标记与 `materials.yaml` 的 audios 类型误记 → 新开 U-62/U-63）、F-049 是 2026-10-21 深度发现批次（用安装包内 agent 文档层与前端 JS chunk 裁定：MixMode 资源索引一次闭合 U-12、阴影模糊 ÷600 由协议值域印证结案 U-03、fill 两个 alpha 从不相离结案 U-02、裁剪与蒙版归一化判死、并从两个 chunk 里抽出官方 draft 模型层 132 条字段表与默认值 → 新开 U-64/U-65，就地更正 4 处旧数），F-050 用「首条 video 轨从不为 2」与「flag=1 有 96.7% 装字幕」两个方向互为蕴含的全量交叉表结案 U-61，并读出 mixed 的两种形态改写 U-62），F-051 清点版本轴地基（13 个版本名目录里 12 个是更新载荷、只剩 2 个完整安装，agent 层是 11.6 新增 → 新开 U-66，就地更正 toolchain/scope 的「14 个版本目录」），F-052 读出 `RenderIndexUtils` 全文（六族分配基座与步长 +2、`free` 分支在语料里从不为真、`mixed` 不在厂商 TrackType 词表且只活在 11.1.0~11.4.2）⇒ 排除两条次带解释、U-62/U-63 改写），F-053 一次量清**素材索引形状**（新工具 `scripts/media_probe.py`：标准库走 box + PyAV 取编码语义；实测 **GOP = 1 秒**、**moov 13/13 在文件尾零 faststart**、相机片是 `XAVC` **H.264 High 4:2:2 + 未压缩 PCM 音轨**、`elst` 单条目但 `media_time` = **正好 1 帧**、`ctts` 重排 3 帧、手机 HEVC 是 **VFR**）⇒ **U-59 结案**（NAS 首帧不是字节数问题）、U-55 收窄、新开 U-67，F-054 把浏览器解码轴从 `<video>` 换成 **mediabunny + WebCodecs** 实测（**索引 + 闭区间取块救不了 4:2:2 的 seek**：207.6 / 257.8 ms 与 `<video>` 同量级；成本模型 `seek ≈ GOP/2 ÷ 管道fps`；首帧刷新到 **2.7–35.7 ms**；无硬件通路时 HEVC **直接抛异常**而不是慢；单次 seek 触发 **11–62 个闭区间请求**）⇒ U-55 判定改口径、U-54 加限定、U-58 拿到不经过 WebGL 的探针）、
`../evidence/conflicts.md`（与外部资料的冲突裁定，C-001…**C-013**；C-012 把「Chrome 不支持 HEVC」连同本项目 F-038 的读数一并推翻，C-013 推翻 `MixMode.json` 的 nameId 可 join 性）、
../evidence/unresolved.md`（U-01…**U-67**（24 结案 / 43 开放）；U-01/U-26/U-39/U-42 由 F-027 结案，U-28 由 F-029 结案，U-30 由 F-031 结案，U-08/U-49 由 F-032/F-033/F-035 结案，U-52 由 F-035 结案，U-53 由 F-038/F-040 结案并拆出下级 U-54/U-55/U-56，U-54 由 F-044 结案、U-56 由 F-046 结案并新开下级 U-59、U-58 由 F-043 新开，U-55 由 F-045 收窄为实现项，U-60/U-61 由 F-047 新开，U-62/U-63 由 F-048 新开，**U-02/U-03/U-12 由 F-049 结案**，U-10/U-15/U-27/U-37/U-51 由 F-049 改写或加证，U-64/U-65 由 F-049 新开，**U-61 由 F-050 结案**（`tracks[].flag` = 官方 7 值轨道内容类别枚举）且 U-62 由 F-050 改写，U-60 由 F-051 加硬约束、U-66 由 F-051 新开，**U-59 由 F-053 结案**（"预取多少 MiB"的问法被实测证伪），U-55 由 F-053 收窄、由 **F-054 改判达标路径**（关键帧索引 → 可硬解 profile 的代理片），U-54 由 F-054 加「仅在有硬件通路时可用」限定，U-58 由 F-054 拿到不经过 WebGL 的探针（只剩光栅那一格），**U-67 由 F-053 新开**（XAVC `elst` 的 1 帧偏移是否已被剪映折进 `source_timerange`））、`../evidence/tables/`（可入库频次/形状表）、
`../evidence/{crypto-probe-log,corpus-scan,toolchain,scope,cross-reference}.md`；
`../evidence/case-crosscheck.md`（**n=1 案例观测**：一条已导出成片与 r3 规格的逐条对表，补出 `transitions` 三键、
`audio_fades` 的三空键、同名不同 `resource_id` 三条规则；口径上不进 r3 频次、只记 `single`）；
轨道/时间线层的完整报告（八类轨道 × 键值域、`track.type → bucket.type` 映射、片段形状双态、`render_index` 逐带表、与本报告的对账与更正）在 `../evidence/track-layer-report.md`。

## 记法

- 每个文件顶部或行内标注证据等级：`verified`（≥2 路独立证据）/ `single`（单源待验证）/ `open`（未解决，见 U-xx）。
- **`single` 不是事实**，只是尚未被反驳的工作假设；实现时若与成片冲突，以成片为准并回来修订本规格。
- **两路证据分场景为准（2026-10-21 定调，细则见 `../evidence/scope.md` §6.1）**：
  字段的**名称 / 合法取值 / 可写面 / 单位定义**以**剪映程序自己**（安装包内代码与协议 schema）为准；
  **实际缺省值 / 频次 / 值域 / 本机是否真用过**以**r3 语料实测**为准。三条附则：
  ① 引程序侧要写到 `文件:行号`，引语料侧要写计数口径；
  ② `Resources/canvas_agent` 是 11.6 新增的 web/agent 写入面（自报 `darwin-arm64`、写 `os="web"`），
     **它的默认值禁止回填桌面老草稿**（反例：`check_flag` 模型 63 vs 语料众数 39；`alignment` 模型 1 vs 桌面删键）；
  ③ 两边对不上时结论是「还有没找到的写入者」，**不许**据此把语料里真实存在的值判成非法再规范化掉
     （`render_index` 次带就是这种情形，U-63）。
- `open` 项都有判定方法，M2 的像素标定是绝大多数项的裁判。
- 数值语义（坐标符号、em 系数、裁剪范围、透明度与混合的先后）在 M1 **全部未标定**，不写进规格当事实。
- **计数口径（r2 起强制，r3 沿用）**：频次一律按**去重内容**（`sha256(解码后的 draft_content.json)`，r3 n=2050，快照 2026-10-16）计，不按文件计——一份 hybrid 草稿的内容同时存在于时间线副本与根镜像。写数字时要说清是「出现在多少份内容中」还是「在内容里出现多少次」，两者不可互换；引用外部工具（`scripts/spec_audit.py`、`corpus_presets.py`）的计数时注意它们**含嵌套草稿**，与顶层 bucket 口径不可直接比较。根因与换算关系见 `../evidence/findings.md` F-019，r2→r3 的真实漂移见 F-020。
- **「键存在」≠「有值」≠「非默认」**：凡「全部 / 恒为」类断言，先查 `stats.json -> field_states`（present/null/absent/空对象四态）。三个真实反例：`responsive_layout` 有 2/3 是 `{}`、`caption_info` 13,835 条全为 null、`bloom_params` 19,492 条里 19,491 条是占位（F-020/F-022/F-024）。
- **枚举字段不许单样本外推**：凡 `type` / `mode` / `category` 这类取值字段，登记前先查 `stats.json -> bucket_enum_values`（42 个 bucket 的取值全在那里），
  不许从一份草稿的一个条目推成「该 bucket 的 type 值是 X」。真实反例：`materials.audios` 曾被记成「type 值为 music」（实际五种，music 只 1,302 条，
  最多的是 sound 与 video_original_sound），F-048 就地更正。
- 语料是活的（剪映会在编辑过程中写草稿），所有计数都是快照。r3 起 `temp/corpus-scan/plain/` **同时冻结明文草稿**，所以同一轮内重跑可复现；跨轮必须带 `stats.json -> corpus.snapshot_date` **与轮次号**对齐。`scripts/corpus_scan.py` 的 `read_only_proof` 与 `corpus` 自检是本项目唯一的回归测试。
  轨道层另有一条独立复核：`scripts/track_matrix.py` 只按 `manifest.json` 的 content key 取数（自动排除 `plain/` 的 28 份历史残留），重生成 `evidence/tables/{track_types,segment_shapes,track_material_map,material_type_enums,render_index_bands_by_type}.csv`（F-048）。

## 文件清单

- 频次与形状表：`../evidence/tables/` —— **目录实测共 45 张 CSV**（`ls` 计数，含下列各批次的全部产物；
  2026-10-28 复核：git 已跟踪 44 张，正文此前记 40 张是漏更，非新增漂移）。
  口径分四层，不可混用：① 按 r3 重生成的基础表 **12 张**（`mixmode_glsl.csv` 来自资源包直读、`spec_coverage.csv` 来自 `scripts/spec_audit.py`；
  r3 新增 `animation_timing.csv` 与 `relations.csv`）；② F-048 的轨道/时间线层 **5 张**
  （`track_types / segment_shapes / track_material_map / material_type_enums / render_index_bands_by_type`）；
  ③ 2026-10-21 本轮三批共 **11 张**：F-049 的 `mixmode_packages / mixmode_draft_paths / shadow_style_keys /
  video_crop_census / fill_alpha_pairing / segment_index_keys / js_model_keys`（7 张，`scripts/{mixmode_join,field_census,js_model_extract}.py`）、
  F-050 的 `track_flag_semantics`（1 张，`scripts/track_flag_census.py`）、
  F-052 的 `render_index_allocators / render_index_subbands / track_type_by_app_version`（3 张，`scripts/render_index_allocators.py`）；
  ④ **2026-10-28 的单例交叉核对 `case_hf_draft_crosscheck`（1 张）** —— n=1 案例观测，**不进 r3 频次口径**，
  不能与前三层加减（口径见 `../evidence/case-crosscheck.md`）。
  其余是 F-020~F-035 时代留下的早期表（`clip_fields / field_states / position_quantum / font_size_mirror / check_flag_* / shape_* / order_agreement` 等），
  它们的计数口径见各自生成脚本，**不要与上面四层的数字互相加减**
- 派生规格：`keyframes.yaml`（关键帧记录/控制点形状）、`panel-map.yaml`（UI 面板控件 ↔ 字段对照）、`coverage.md`（规格↔实测覆盖矩阵）

## 与废弃方案的关系

`jianying-preview-old` 已废弃，本规格**不引用其代码、常数与结论**；其中的标定系数一律重测（U-07）。

## 与第三方资料的关系

- 只读参考、不复制不依赖：`jianying-editor-skill`（MIT）的 `scripts/`、`references/`、`rules/`。
- 交叉参考需署名：`renezander030/capcut-cli` `docs/draft-schema/*`（MIT）、`GuanYixuan/pyJianYingDraft`（Apache-2.0）。
- 冲突一律以本机语料实测裁定，记录在 `../evidence/conflicts.md`。

## 格式选择说明

计划原写「结构化数据用 YAML」。这里沿用 YAML，但有一个约束：Python 环境有 `yaml` 模块可直接校验，
浏览器侧不引入 YAML 依赖——由本项目自研的 Python 网关在加载时把规格转成 JSON 再供前端消费。
**硬门（提交前必过）**：`python scripts/check_spec_yaml.py` —— 校验全部 `docs/spec/*.yaml` 可解析、
无重复键（并发合并最常犯），并对「列表项以 `*`/反引号开头」这类历史踩坑直接报错。
  **实现状态（2026-10-23，F-078/F-080/P-33）**：L1 已带 `segments[].animations[]`（含 `start_us`）；曲线值从预设包内明文 lua 读（`scripts/animation_curve.py`）。测试时间线上 **14 个预设 / 33 段**里，可求值的是 **3 个预设 / 8 段**（全是字幕：向下滑动 6、缩小 1、渐显 1），其余 9 个预设走 AE 导出脚本或 `onUpdate` 显式数学，**显式记为未覆盖**；通道 2 已生效并有门层 L8（含「动画期外逐字节相同」），**浏览器通道已接并做到曲线值层面**：`scripts/merge_model_carrier.py` 把 `animations` 补进代理模型，门 L9 拿浏览器自报的 `{alpha,scale}` 与通道 2 逐段对数（7 段、0 不一致，F/P-34）。**两通道的像素级一致仍未判**，`dy` 也不在判据内（JS 用节点高、Python 用墨迹高，定义不同）。
