# 语料扫描方法与结果摘要（M1 基准，r3 修订）

工具：`scripts/corpus_scan.py`（一级，全语料）、`scripts/corpus_detail.py`（二级，按内容去重后深挖 + 派生缓存 join）、`scripts/spec_audit.py`（覆盖台账）。
原始数据：`temp/corpus-scan/`、`temp/corpus-detail/`（`temp/` 被根仓库忽略，不进历史）；
可入库的派生表：`tables/`（只含键名、枚举值、频次与包内函数名，不含用户内容与路径）。

> **口径（r2 起统一，r3 沿用）**：所有频次表按**去重内容**计（`sha256(解码后的 draft_content.json)`，r3 n=2050），
> 不是按文件计。原因见下面「基准修订」。规格与证据里凡引用频次，单位都是「出现在多少份去重内容中」
> 或「在去重内容中出现的次数」，两者不可互换（一个 bucket 在一个内容里只计 1 次，一个键可能出现多次）。
> **r3 另加两条纪律**：①「键存在」不等于「有值」——`stats.json -> field_states` 逐字段记 present/null/absent/空对象；
> ② 任何 `bucket_enum_values` 表都被截到 `most_common(40)`，**不得当封闭集合引用**。

## 采集方式

1. 只读遍历 `<DRIVE_D>/JianyingPro\<DRAFT_ROOT>` 全部 1,475 个目录（1,240 个有内容、235 个无内容）；按是否存在 `Timelines/`、`draft_info.json` 归类。声明的根在 `cache.py` 里 resolve 后**按序去重**，重复路径计数写入 `stats.json -> corpus.duplicate_paths_skipped`。
   **这条口径到 2026-10-22 才补全**：本机其实有**第二个草稿根** `<DRIVE_E>/JianyingPro\<DRAFT_ROOT>`（注册表 629 条指它），r1…r3 从未扫到；实测 E 根 486 个内容文件里 **480 个与 D 根逐字节同摘要**，是镜像而非新料，所以 r3 的**频次结论不失真**（去重内容只 +6）。细节、双根实验与漂移归因见 F-056。
   另：`JY_DRAFT_ROOTS` 原来只能给**一个**根（`_roots()` 把整串当一个路径），已改为按 `os.pathsep` 切分，双根扫描才跑得起来。
2. 每个 `draft_content.json` 用首字节判编码：`{` 起头 = 明文，否则 = 密文。
3. 密文经自研子进程 worker（`scripts/jy_crypto/`）调用剪映自带 `videoeditor.dll` 解密，明文只写 `temp/corpus-scan/plain/<sha256前16>.json`；**r3 起明文草稿也复制一份到这里**，因此整轮快照自包含；**不写入任何草稿目录**（`cache.py` 硬围栏）。
4. 逐份解析、增量聚合（一次只在内存里一份，避免累积）。40 文件/批起一个新 worker；明文缓存命中的文件不再送解密。
5. 一级统计：布局、编码、顶层键、轨道/片段字段、42 个 material bucket 的键与枚举值、动画/转场/特效/贴纸的 (name,id,category) 频次、关键帧 property_type、`clip` 字段、画幅比例。
6. 二级统计（r3 的 2050 份去重内容）：根开关取值分布、`render_index`/`track_render_index` 关系与数组顺序一致性、嵌套结构形状（`common_mask.config`、`videos.crop`、`fill/strokes/shadows`）、字幕 `content` 内 `styles[]` 键、动画时长域、派生缓存等式。**r2 起不再截断**（旧版每个 bucket 只看前 20 条、每层只看前 4 个元素，所以形状类计数是下界）。
7. 补充：值驱动搜索（找「值等于中文混合名」的键路径）、剪映安装内资源包直读（`Resources/MixMode/*` 的 GLSL、`Cache/effect/*` 的 Lua/prefab/extra.json）、`ressdk_db/rp.db` 只读打开（结论：表空）。

## 结果（快照 2026-10-16，r3；r2 值留在括号里）

| 项 | 按文件 | 按去重内容 |
|---|---|---|
| 内容文件 / 解析成功 / 失败 | 2215（2216） / 2215 / **0** | 2050（2052） / 2050 / **0** |
| 编码 | 密文 1876 / 明文 339（1877/339） | 密文 1713 / 明文 337（1715/337） |
| 布局 | hybrid 1,033 / legacy 833 / 根镜像 349 | hybrid 1,028 / legacy 831 / 根镜像独有 191 |
| 同一内容的文件份数 | 1 份 1,887 / 2 份 162 / 4 份 1（r3 实测见 `corpus.content_multiplicity`） | — |
| 未解析的副本普查 | `.bak` 2,803、`template-2.tmp` 2,888、`template.tmp` 1,800 | 只数不解析，故上表是**下界**（F-025） |

目录级分布（按 `manifest.json` 的 2,450 条记录归到 **1,475** 个目录）：仅根内容 833 / 含 `Timelines` 407 / 无内容 235；
那 407 个里 349 个有根 `draft_content.json`、58 个只有时间线副本；再细看，**只有 229 个能枚举到 `Timelines/<id>/draft_content.json`**，
另 120 个虽然建了 `Timelines/` 却一条都枚举不到（只有根镜像进表）—— 这是副本普查的第二个下界，见 F-025 与 U-57。

| 项 | 值 |
|---|---|
| material bucket | **42 个**（r1 记 39；r2 新增 `audio_pannings`、`video_shadows`、`video_strokes`；r3 无新增） |
| 动画条目 / 预设 distinct | 10,565 条；**417**（键 = `(type,name,id)`）；含 `category_name` 的四元组是 **606**；条目 `type` 有 **5** 类（in/loop/out/caption/group），容器 `type` 恒为 `sticker_animation` |
| 转场 distinct | **2193**（键 = `(name,id,category)`） |
| 特效去重元组 | 71,414 个 `(name,id,category)`；**记录总数 73,972 条**（r1 把 70,718 误标为「记录条目总数」，见 C-010） |
| 关键帧 property_type | **70 种**（r1 记 50）；控制点 8,447 个（顶层口径），其中 43.7% 带 `curveType` |
| `##_draftpath_placeholder_##` 宏 | 1,311 / 2,050 份内容、58,108 次（`stats.json -> path_macros`；语义见 F-024） |
| 画幅取值 | 9:16 870 / original 341 / 3:4 123 / 16:9 95 / 1:1 4 / 4:3 3 |
| worker 批次 | ≤40 文件/批（r3 几乎全部命中明文缓存，实际解密 0 份新内容） |
| 明文体积 | 317 MB 级（temp/ 内，未入库；r3 起**明文的原始文件也冻结一份**，见下） |

## 只读证明

- 扫描开始时**随机**抽样 40 个内容文件（按布局分层，`random.Random(0)`）记录 sha256，结束时重算：**40/40 逐字节不变**（`stats.json -> read_only_proof`，`unchanged: true, mismatched: []`）。r1 取的是排序后的前 20 个，实际只覆盖十来份草稿，证明力不足，已改。**2026-10-22 两条腿各自重跑都通过**（D 单根与 D+E 双根，各 40/40 不变、`drafts_failed: 0`）；抽样按**布局**分层而非按根，
按 `Random(0)` 复现两份名单：控制腿 40 份全在 D 根，实验腿 **31 份 D + 9 份 E** ⇒ 双根那次确实把 E 根文件也纳入了只读证明。
- crypto 门禁另有独立证明：20 份样本（10 legacy + 10 hybrid）在「解密 → 重加密 → 再解密」全流程后源文件 sha256 **20/20 未变**，且等长/语义回环/外部 oracle 三项 20/20 通过（`temp/gate20-r2.log`，r2 删除路径级绑定后复测）。
- 全程未创建/修改草稿目录内任何文件；未新增 `.jypreview/`（语料中 75 个草稿有历史遗留的该目录，本项目不碰）。
- 自检：`stats.json -> corpus` 里 `content_files == distinct_content_files` 且 `drafts_parsed == distinct_contents`，不成立时 `corpus_scan.py` 返回非 0。本仓库无测试基建，这条就是回归测试。

## 基准修订：r1 的一级频次恰好翻倍（2026-10-16，r2）

- **根因**：`cache.py` 的默认草稿根同时声明了 `<DRIVE_D>/JianyingPro\<DRAFT_ROOT>` 与
  `%LOCALAPPDATA%\JianyingPro\<DRAFT_ROOT>`，后者是指向前者的 junction；`_roots()` 对每个根做
  `resolve()` 后两者变成同一目录，`enumerate_corpus()` 于是把语料走了两遍。
  实测 r1 的 `manifest.json` 有 4900 条记录、只对应 2215 个不同路径（r1 原始件已留在
  `temp/baseline-r1/` 供核对）。
- **影响面**：一切来自一级 CSV 的频次（`buckets`、`bucket_keys`、`clip_fields`、`text_style_keys`、
  `text_flat_keys`、`keyframe_types`、`enum_values`、`animations`、`transitions`）以及引用它们的规格行，
  统统**恰好 ×2**（同一条记录被重放两遍，所以倍数对每个键一致：r1 值 ÷ 2 = 按文件口径的真值）。
- **不受影响**：二级 `corpus_detail` 一直按 content key 去重（2051），所以 `timebase.yaml` 的
  segment 计数、`canvas_ratios.csv`、`render_index_bands.csv`、`order_agreement.csv`、根开关分布、
  F-007 的合成顺序统计都是按内容口径的，只有语料漂移带来的小幅变化。
  集合类指标（bucket 个数、distinct 预设数）对重复本身也不敏感。
- **同时修的**：二级形状统计的 `[:20]` / `[:4]` 截断（r1 的形状类计数是下界，
  例如 `videos.crop` 13,828 → 16,585，`fill.content.solid.alpha` 1,413 → 4,283，
  并且解封后新暴露出 `common_mask.text_config.font_*`、`masks.config.width/height/invert` 等键）；
  `70,718` 的标签错误（C-010）。

## r3 增补：冻结、清点与三件新工具（2026-10-16）

- **明文冻结**：`encoding=="plain"` 的草稿原来**每轮都从草稿目录实时再读**，于是同一份 spec 的数字会随用户编辑漂移（实测一小时内 `videos.smart_motion` 带键数 4,856→4,858）。现在明文也复制一份进 `temp/corpus-scan/plain/<key>.json`，`corpus_detail` 与 `spec_audit` 一律优先读冻结副本 → 同一轮内重跑完全可复现。
- **present / null / absent 三分**（`stats.json -> field_states`、`tables/field_states.csv`）：30 个关键字段各记「缺席 / null / 空对象 / dict(n) / list(n)」。这一项直接推翻了「99.8% 的 segment 都带 responsive_layout」式的读法（其中 2/3 是 `{}`），也是 `caption_info`（13,835 条全 null）与 `bloom_params`（19,492 条里 19,491 条是占位）的正确解释方式。
- **新清点**：`path_macros`（`##_draftpath_placeholder_##` 的内容数与出现次数）、`corpus.replica_census_not_parsed`（`.bak` / `template*.tmp`，**只数不解析**）、`check_flags`（text/video 逐位）、`keyframe_control_points`（控制点总数，用来算 `curveType` 缺省率）、`bucket_enum_values` 改按**点路径**建键（修掉 `material_animations.type` 把容器 `sticker_animation` 与条目 `in/out/loop/caption/group` 混成一张 6 值枚举表的缺陷）。
- **新链接**（`corpus_detail.py`）：`animation_timing.csv`（各动画类型的时长域与 `start` 非零率）、`relations.csv`（三条派生缓存等式 + 关键帧 `material_id` 的 join 命中率，逐条 ok/stale 计数，M3 写回不变式直接依赖它）。
- **两张硬门脚本入库**：`scripts/check_spec_yaml.py`（spec 可解析 + 重复键 + 「列表项以 `*`/反引号开头」）、`scripts/check_doc_counts.py`（文档里引用的每个数必须能在冻结证据里找到，找不到的必须显式标口径；本轮 587 个引用数、18 个未绑定，全部为求和值、外部一次性清点或已标注的旧口径）。
- **r2→r3 漂移**（`temp/drift-r2-r3.txt`）：期间 `中智矩阵 10月13日 (1)-副本` 的时间线 `E9A3E52A…` 被删 → 内容文件 2,216→2,215、去重内容 2,052→2,050，其余计数普遍下移 0.6–0.9%（最大相对变化 `texts.operation_type` −3.8%）。**结论方向无一被推翻**，改的是量纲、形态范围与出处。

## r4 双腿重扫：镜像根与六天漂移分开归因（2026-10-22，F-056）

同一脚本两条腿各跑一次全量，每腿自带随机分层 40 份的 sha256 只读证明（两腿都 `unchanged: true`）：

| 快照 | 日期 | 根 | 内容文件 | 去重内容 | 目录记录 | 明文/密文（按内容） | 落点 |
|---|---|---|---|---|---|---|---|
| r3（**在册基准**） | 2026-10-16 | D | 2,215 | 2,050 | 2,450 | 337 / 1,713 | `temp/corpus-scan/`（已还原为 r3 原件） |
| r4-d 控制腿 | 2026-10-22 | D | 2,268 | 2,089 | 2,503 | 335 / 1,754 | `temp/corpus-scan-r4d/` |
| r4-de 实验腿 | 2026-10-22 | D+E | 2,754 | **2,095** | 3,134 | 335 / 1,760 | `temp/corpus-scan-r4de/` |

- **为什么基准不换**：把在册基准换成 r4 会同时改动 `docs/evidence/tables/` 全部派生表与 1,339 处数字引用，
  且会把「E 根覆盖」与「六天漂移」两件事混成一个差值。两条腿分别存盘、`scripts/corpus_diff.py` 做归因，
  引用时带 `corpus.snapshot_date` —— 与 r2→r3 那轮同法。三个快照目录都已进 `check_doc_counts.py` 的可绑定证据清单。
- **E 根的实际增量 = 6 份去重内容**（486 个文件里 480 个与 D 根同摘要）；实验腿相对控制腿的数字叶子变化 1,173 项，
  多为 `+0.7–1.0%`，其中 `bucket_keys.effects.*` 齐涨 **+523** 由**那 6 份里的一份**带 523 条 effects 造成。
- **D 根六天漂移 = 数字变化的主因**：added 66 / removed 13 / 内容改写 94 个文件（14 个草稿目录），
  数值叶子变化 1,975 项，文本侧若干键下移 4.5–18.1%（`recognize_model`、`group_id`、`subtitle_keywords`、
  `base_content`、`type==subtitle` 同幅联动 ⇒ 少数字幕大户草稿改写/离场，不是普遍退化）。
- **副本普查按双根口径上涨**：`.bak` 2,854→3,342、`template-2.tmp` 2,939→3,431、`template.tmp` 1,815→2,461
  （r3 → r4-de）。这三个数是「扫到多少算多少」的**只数不解析**普查，双根后必然包含镜像副本，
  **不得**当独立草稿数引用。
- 布局/编码口径在 r4-de：hybrid 1,074 / legacy 832 / 根镜像独有 189（按内容首次出现位置归属），
  `content_multiplicity` 从**控制腿**的「1 份 1,912 / 2 份 176 / 4 份 1」变成**实验腿**的「1 份 1,521 / 2 份 531 / 3 份 1 / **4 份 42**」
  —— 那个 4 就是「hybrid 双副本 × 双根」（r3 单根时是 1 份 1,887 / 2 份 162 / 4 份 1）。

## 已知偏差与限制

- 频次按**去重内容**，因此同一份内容既作时间线副本又作根镜像时只计一次；「按文件」口径见上表，两列不要混用。
- 布局归属按该内容**首次出现**的文件位置判定（时间线副本先于根镜像），所以「根镜像 192」指的是内容只出现在根镜像里。
- 语料是活的：剪映会在编辑过程中写草稿，目录级与计数会漂移（r1→r2 之间 `root+Timelines` 343→350、密文文件 1876→1877、bucket 39→42、关键帧类型 51→70）。所有计数都是**快照**，引用时带上 `stats.json -> corpus.snapshot_date`。
- `effects` 频次把嵌套草稿（`materials.drafts[].draft.materials.effects[]`）与外层合并计数，复合片段占比不低（1260 份含 `drafts` bucket），M2 建模需分开展现。
- 二级形状统计只遍历顶层 `materials.<bucket>[]`，**不含嵌套草稿内部**；`scripts/spec_audit.py` 的同类计数含嵌套，因此两处数字不可直接比较（例如 `videos.video_mask_shadow`：顶层带键 8,505（r3），旧稿的「顶层 8,456 / 含嵌套 19,348」两个数都未按 r3 重取）。
- 频次来自单一用户语料，不代表全体剪映用户的使用分布；作为「先实现哪些属性」的排序依据够用，作为「属性全集」依据不足——因此规格另用键名递归清点（覆盖面为全部出现过的键）。

## 差分样本草稿（2026-10-18，构造样本不在语料统计口径内）

`<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\差分样本 10月18日` 是 10月16日 草稿的**副本**，由 Computer Use 驱动剪映做了
描边/等比/emoji 字幕/字号/对齐共 13 次保存（方法与结论见 `findings.md` F-027、F-028，逐条记录在
`temp/diff-samples/NOTES.md`）。它是**构造样本**，用途是给「语料判不了」的项一个见证，不是自然使用痕迹：

- 下一次重跑扫描（r4）时它会进目录计数（草稿目录 +1、内容文件 +2、去重内容 +1），
  但**不得**把它当作用户使用频次的一部分来排序 phase-1 覆盖面；引用它的数字必须标注「构造样本」。
- 它同时把 F-025 的「副本普查下界」变成实测：一次保存改写 15 个文件、新增 24 个（含 `.locked` 与 18 份 `.backup` 事件流水）。
- 原草稿 `10月16日` 全程未动（保存前后 `draft_content.json` 与其时间线副本都是 `d4807d15…`），
  只读门禁另有一份 40 文件随机抽样复核（`stats.json -> read_only_proof`）。
- 2026-10-19 又在该副本上追加了两批差分（对齐 6 按钮 × 6 条字幕、开关位逐位因果），见 F-029、F-031。
- 2026-10-19 又新增一份构造样本 `10月19日 (2)`（四条时间线：9:16 与 16:9 各两条，专门做「改画幅 ↔ 位置像素」成对观测，见 F-033）。它现在**就在草稿目录里**，r4 重跑会把它算进所有频次 —— 引用它的数字必须标注「构造样本」。
- **这条口径此前被静默违反过一次**：`plain/` 里积了 **28 份不属于 r3 清单**的明文（全部 11.6.0 内容、814 条字幕），
  凡直接 glob 该目录的派生表都把构造样本算进了分母（18,077 应为 17,454 等，根因与纠正见 F-030）。
  现在 `build_evidence_tables.py -> frozen_contents()` 只认 `manifest.json` 的 2,050 个内容键，并打印排除数；
  r4 重跑时要从源头把 `差分样本 *` 与这些临时解密一起排除。
