# 剪映草稿格式总表（一页可读版）

本文件把 M1 实测到的草稿格式事实**归并成一份能从头读到尾的说明书**。它**不新增任何结论**：
每条都指向权威落点（`spec/*.yaml`、`spec/crypto.md`、`spec/write-rules.md`、`spec/panel-map.yaml`）与
证据出处（`../evidence/findings.md` F-xx、`../evidence/unresolved.md` U-xx）。**与本文件冲突时以那些文件为准**，
因为它们是逐字段维护的那一份；本文件是它们的索引与读法。

- 语料基准：r3 快照 2026-10-16 —— 1,475 个草稿目录、2,215 份 `draft_content.json`、**2,050 份去重内容**（F-015）。
  所有频次按去重内容计，「出现在多少份内容中」与「在内容里出现多少次」不可互换（F-019/F-020）。
- 剪映版本：本机 `11.6.0.14552`（DLL 备用 `11.1.0.14287`）。构造样本（`差分样本 10月18日`、`10月19日 (2)`）不在语料频次口径内。
- 记法：verified=≥2 路独立证据；single=单源待验证；open=未解决（见 U-xx）。
- 维护规则：`spec/` 任一条的**等级或数字**变了，本文件对应行必须同日改；`python scripts/check_doc_counts.py`
  会扫本文件引用的数字是否能在冻结证据里找到。
- 轨道/时间线层的**完整报告**在 `../evidence/track-layer-report.md`（F-047/F-048）：八类轨道 × 键值域、
  `track.type → bucket.type` 映射表、片段形状双态、`render_index` 逐带表，以及与本总表逐位对账的结果。
  派生表可用 `python scripts/track_matrix.py` 重生成（只读，按 manifest 的 content key 取数）。

## 0. 读一个草稿的七步（渲染与写回共用）

| 步 | 做什么 | 关键事实 | 出处 |
|---|---|---|---|
| 1 | **能力探测判布局**，不查版本号 | 有 `Timelines/project.json`=hybrid；只有 `draft_content.json`=legacy；`draft_info.json` 单草稿架构=r3 语料已无；两者都无=no-content（235 个目录） | `layout.yaml` F-015 |
| 2 | **定活动时间线** | `main_timeline_id` 为准 + 过滤 `is_marked_delete`；时间线名（「时间线01」）是用户标签，不可当标识 | `layout.yaml` verified |
| 3 | **判编码并解密** | 首字节 `{`+可解析=明文；`{`+解析失败=**损坏**（不是加密）；非 `{`=密文→子进程调 `videoeditor.dll` 的**内存串** `decrypt` | `crypto.md` §1/§3 F-003 |
| 4 | **按 content-id 认领副本** | 逐个候选解密，比顶层 `id` 是否等于目标 timeline id；**绝不按文件名认身份**（`.bak`/`template*.tmp` 都是完整副本） | `layout.yaml` F-025 |
| 5 | **建引用索引** | `segment.material_id`→bucket 条目（实测 **0 处悬挂**）；`extra_material_refs`→辅助 stub（**10 处悬挂**，记 warning 不报错）；**容忍 `tracks` 缺席（278 份）与 28 条没有 `segments` 键的轨道**；片段的**语义类型看 bucket 的 `type`，不看 `track.type`** | `materials.yaml`、`track_matrix` 表 F-004/F-048 verified |
| 6 | **展开与归一化** | 路径宏 `##_draftpath_placeholder_<uuid>_##/` = **草稿自身目录**；`texts.content` 是 **JSON 字符串**要二次解析；`styles[].range` 按 **UTF-16 code unit**；派生缓存一律**读源字段** | F-024/F-027 F-023 |
| 7 | **算渲染换算** | 位移 = `值 × 该轴边长 / 2`（y 向上）；`em_px = size × width × 0.00574`；时间=微秒；层级由 `track_render_index`+`render_index` 决定 | F-035/F-005/F-007 |

## 1. 容器层：目录、副本、锁与噪声

- **四种布局**（verified，r3 目录级，出处 `temp/corpus-scan/manifest.json` 2,450 条记录）：仅根内容 **833** / 有 `Timelines` 且带根镜像 **349** / **只有时间线副本 58** / 无内容 **235**（后两类合计 = 含 `Timelines` 的 407 个目录；四类相加 = 1,475）。
  内容文件按文件口径 = hybrid 1,033 + legacy 833 + 根镜像 349 = 2,215；按内容口径 hybrid 1,028 / legacy 831 / 仅根镜像 191。
  **注意那 407 里只有 229 个能枚举到 `Timelines/<id>/draft_content.json`**，另 120 个只枚举到根镜像（U-57）→ 写回选址不能假设「有 Timelines 目录就有点对得上的副本」。
- **副本是多点写入**：`draft_content.json`、`.bak`、`template.tmp`、`template-2.tmp` 各有根与时间线双份；
  扫描器只跟主文件，所以 `.bak` 2,803 / `template-2.tmp` 2,888 / `template.tmp` 1,800 是**未被解析的普查下界**（F-025）。
- **判分叉只能用解密后的内容**：重加密**等长而摘要不同**（容器带随机熵）。长度不同⇒内容不同；**等长而摘要不同⇒不能判**（F-003/F-025/U-20）。
- **根镜像**：hybrid 草稿在根目录留一份活动时间线镜像；写非活动时间线**不会**自动刷新它（single，同步时机 U-17）。
- **`.locked` = 该草稿正被剪映编辑**（实测：打开期间存在，关闭时间线时删除，同时 `.backup/` 写 3 份 `.close.bak` 而内容零变化）→ 写回门禁（F-028/U-46）。
- **`.backup/` 不是备份，是事件流水**：`<YYYYMMDDHHMMSS>_<hash>.<load|save|close>.bak`，每个事件同时写 3 个镜像位置，单调增长，**不得**当回滚来源。
- **一次「打开→改→保存」的真实足迹**：改写 **15 个**文件、新增 **24 个**（含 `draft.extra`、`draft_meta_info.json`、`draft_settings`、两个 `*.db`、`timeline_backup_manifest.json`）→ 快照必须覆盖整个草稿目录（F-028）。
- **剪映自己认定的草稿 JSON 标准成员是 5 个**（安装包内 agent 常量，非推断）：`draft_info / draft_meta_info / draft_content / draft_virtual_store / draft_agency_config`。
  其中 **`draft_virtual_store.json` 此前不在本规格里**（1,184/1,475 个目录存在，与 `draft_content.json` 的 1,190 几乎同数），它是 `subdraft/` 的**父子索引**（`child_id`/`parent_id`），复合片段与嵌套草稿解析要用它（F-047 → `layout.yaml -> container_json_set`）。
- **主轨 = 首条 `type=="video"` 的轨道，且它的 `flag ∈ {0, 缺席}`**（verified，F-047 + F-050 两条通道）：r3 抽样里含 video 轨的草稿 **370/370** 都是 `tracks[0].type=="video"`，206/370（55.7%）还有更多 video 轨（画中画）；安装包内 agent 同样把 `tracks[0]` 当视频主轨，取不到就报错。**`tracks[].flag` 已结案（U-61，F-050）**：它是官方轨道内容类别枚举（7 值），全量交叉表零例外 —— 首条 video 轨 575 写 `0` / 958 整键缺席 / **0 条写 2**，非首条 video 轨 **1,662 条全是 `2`**；`flag==1` = 字幕轨（971/1,004 = 96.7% 装 `texts.type=="subtitle"`）；`0` 与缺席等价（F-047 那句「不是主轨标记」是只做了排除法、没读出正面语义）（`layout.yaml -> main_track.flag_axis`、`tables/track_flag_semantics.csv`）。
- **版本轴与身份块**：桌面剪映写的草稿根 `version` 恒为 `360000`、`new_version` 是随 `platform.app_version` 单调的字符串（11.1.0→"179.0.0" … 11.6.0→"189.0.0"）；**同一安装包的内置 agent 写 `400000`**、并把 `platform` 写成 `os=web / app_id=348188`（桌面实测 `windows / 3704 / app_source=lv`）。`platform` 是八字段身份块（`os os_version app_id app_version app_source device_id hard_disk_id mac_address`），写回整块不动；stamp 哪个归 U-60（F-047 → `layout.yaml -> version_axis / platform_block`）。
- **绝不写入**：`deepagent/ subdraft/ Resources/ matting/ adjust_mask/ common_attachment/ .backup/ *.db crypto_key_store.dat*`。

## 2. 加密层：只调用，不逆向

- **唯一可用面 = 内存串 API**：`decrypt`(带 `ok` 出参优先) / `encrypt`（调用前必须 `enable(true)`）/ `enable` / `isEnable`，
  `this` 传 NULL，`std::string` 按 MSVC x64 布局（16 字节 SSO + size + capacity）。符号用 PE 导出表**按子串模式匹配**，
  不硬编码 mangled 名（`pe.py` 直读导出表得 32,996 个符号、`EncryptUtils@lvve` 家族 14 个，出处 `../evidence/crypto-probe-log.md` F-003）。
- **路径级 API 已探测不可用并整体删除**（`decryptFile`/`encryptFile`/`decryptFileBytes`/`isFileEncrypted` 8 变体全 `status=1`、0 字节）——
  删除理由是它们把草稿原始路径交给方向未证实的导出，是本项目唯一可能让 DLL 写进草稿的调用点（U-16 定案）。
- **副作用隔离**：DLL 约 72 MB、加载即冲 stdout、每次调用泄漏一个堆块（未导出 `~basic_string`）→
  **主进程绝不加载 DLL**；子进程 worker + 结果写文件 + `TerminateProcess`；**≤40 文件/批**；产物只进 `temp/`（`cache.py` 硬写围栏）。
- **三条门禁**：等长 + 语义回环（`decrypt(encrypt(plain))==plain`）+ 与外部 oracle 的明文 sha256 一致（≥20 份）。
  **明确不作要求**：`encrypt(decrypt(cipher))==cipher` —— 该等式在本格式下不可能成立（20/20 实测等长而摘要不同）。
- 平台仅 Windows；macOS / CapCut 不在范围（U-19）。

## 3. 骨架层：时间、ID、bucket

| 主题 | 事实 | 等级 |
|---|---|---|
| 时间单位 | **微秒**整数；`duration` 位数集中在 7–9 位 | verified F-005 |
| timerange | `target_timerange` 恒有（51,718）；`start` 缺席 4,284 条（8.3%）⇒ 读时补 0，**写回不得新增该键** | verified F-005 |
| 变速 | 权威在 `segment.speed`；`target = source / speed`；`materials.speeds[].speed` 是**忠实镜像**（11,680 / 11,680 无例外，可整键缺席） | verified F-023/C-011 |
| fps | 顶层 `fps` 在 1,365 份内容里缺席 ⇒ **不得假设 30fps**，需显式回落并记录来源 | open（回落值待标定） |
| ID | `str(uuid.uuid4()).upper()`；常规保存不改既有 ID；克隆只生成一个新 ID + **整值精确匹配**递归替换，禁止全局文本替换；ID 无语义 | verified/single |
| bucket | 实测 **42 个**，非封闭集合；phase-1 只需 12 个（`videos texts canvases material_animations drafts effects(mix_mode) transitions common_mask masks speeds(镜像) video_shadows video_strokes`） | verified F-015 |
| 轨道与片段 | 8 类轨道共 **9,990** 条、顶层片段 **51,718** 个（2026-10-20 独立全量重跑逐位复现，含 `track.attribute` 直方图与逐类型引用桶）。片段**没有 `type` 键**；形状是**双态**：全语料只有一种 45 键完整形（6,004 段，audio/text/video/effect/adjust/sticker/filter 都有），同类型里另有 8~15 键最小形（video 竟有 524 种键集） | verified F-048 |
| bucket 的 `type` 枚举 | 取值全在 `../evidence/tables/material_type_enums.csv`（91 行）。最常踩的三条：图片 = `videos.type == "photo"`（1,230 条，不另设 bucket）、字幕/文字/歌词 = `texts.type`（subtitle 17,718 / text 3,307 / lyrics 60）、`material_animations[].type` **恒为 `sticker_animation`**（真分类在 `animations[].type`） | verified F-048 |
| 引用完整性 | 5 条硬规则（material_id 可解析 / extra refs 可解析 / 同 bucket 内 id 唯一 / 复合片段自成一体 / `local_material_id` 空需回填）；text 轨道实测 10 个悬挂引用 ⇒ **解析记 warning，不得当硬错误，写回不得丢弃未知 id** | verified |
| 顶层键覆盖 | 40 个顶层键里 37 个已逐条解释；bucket 内 718 个键名记录 74%（缺口集中在 phase-2/3 素材细键） | `coverage.md` |

## 4. 层级：绘制次序不由数组顺序决定

- 轨道类型实测条数（去重内容）：video 3,195 / audio 2,582 / text 2,439 / mixed 825 / effect 410 / sticker 277 / adjust 194 / filter 68；轨道与片段都**没有显式 z**。
- `track_render_index` 在轨道内恒定（8,584 恒定 / 1 变化）→ **轨道间**次序；`render_index` 按元素类别**分带** → 同带内片段次序：
  主带 video/audio/adjust `0-999`、filter `10000-10999`、effect `11000-13999`、text/sticker `14000-14999`（text 带 19,467 次）。
  **两处旧说法已更正**（F-048 全量重跑，逐带表在 `picture.yaml -> compositing_order.bands_measured`）：
  ① `mixed` 不是 14000 带专属，它跨 `0-999`/`10000+`/`11000+`/`14000+` 四个带（257/1/26/757），因为它本来就是混合内容轨；
  ② 主带之外还有 `15000-15999` 254、`16000-18999` 29、`19000+` 207（共 496 段，全落在 text/sticker）→ 次带语义 U-63。
- **轨道类型不决定片段形状，也不决定素材类型表**（F-048）：八类轨道的 `material_id` 各自落到固定 bucket（`picture.yaml -> tracks.track_type_material_map`），
  其中**图片 = `videos[].type=="photo"`**（1,230 条，不另设 bucket）、字幕/文字/歌词 = `texts[].type`、调色轨 = `placeholders[].type=="adjust"`；
  而同一种轨道里 8~15 键的最小形与 45 键的完整形并存（全语料只有一种 45 键形、6,004 个片段），解析必须按「键是否存在」而不是按类型写分支。
- 数组顺序与层级相关但**不是权威**：归一化均值 video 0.266 → text 0.468 → audio 0.863，而「text 先于 video」占 27.7%；轨道内 `render_index` 单调仅 2,070 / 不单调 589。
- **升序是更靠上还是更靠下仍未定**（U-15，必须由成片判定）；`render_index_track_mode_on` true 1,978 / false 63。

## 5. 字幕链（权威：`spec/text.yaml` + `panel-map.yaml` 的文本各节）

### 5.1 载体与二次解析

`segment.material_id → materials.texts[]`；`texts.content` 是**字符串**，内含 `{"text","styles":[…]}`，必须二次 `json.loads`。
**`texts[].type` 才是字幕/文字/歌词的判别字段**（此前规格漏记，F-048）：`subtitle` 17,718 / `text` 3,307 / `lyrics` 60 / `none` 1；
同一条 text 轨道可混着三种，而 **mixed 轨道也指向 subtitle/text**（564 / 233）⇒ 「字幕在 text 轨上」不成立，判语义类型要看 `texts[].type` 而不是 `track.type`。
`styles[]` 键实测频次（r3）：`fill 24,085 / range 24,085 / size 24,075 / font 23,875 / shadows 14,510 / useLetterColor 10,637 / strokes 6,222 / effectStyle 1,784 / bold 484 / italic 453 / underline 209 / bloom 68（全为 null）/ inner_shadows 28 / line_spacing 9 / select 3`。

- `range` 有**两种落盘形**：数组 `[start,end]`（24,075）与空格串 `"0 10"`（10 条）；旧文档写的字典形在语料里一条都没有。
- `range` 单位 = **UTF-16 code unit**（构造样本 `测试A😀B中🎉C` = 8 码点/10 code unit，整段样式 `[0,10]`）；
  emoji 原样存、不做代理对转义 ⇒ 按「字符数」算下标的语言（Python str、JS `Array.from`）都会切错样式（F-027，结案 U-01）。

### 5.2 字号：两处写、只有一处权威

`styles[i].size` 是权威（1:1 无换算，配 `range` 可分段不同）；顶层 `texts.font_size` **只是镜像**：4.8% 整键缺席、
两键都在时 97.2% 等于 `styles[0].size`、232 条等于其它段、**317 条与所有段都不等**、471 条反过来只有 `font_size`（F-034，表 `font_size_mirror.csv`）。
→ 写回**不得**为「补齐」而给没有该键的字幕新增 `font_size`，也不得用它覆盖分段字号。

像素换算：`em_px = size × canvas_config.width × 0.00574`（带宽 0.00574~0.00578；两画幅实测 6.20 px/单位 @W=1080、11.02 @W=1920，过原点线性）。
参考文档的 `W/100` 与 `W×0.00625` 都不对（后者方向对、系数偏 9%）（F-035/F-036，U-07 只剩「精确形式」）。

### 5.3 开关判据：看数组载体，不看位、不看扁平字段

| 想判 | 正确判据 | 不能用 |
|---|---|---|
| 描边 | `styles[].strokes[]` **非空** | `border_*`（恒写）、`check_flag` 单独 |
| 阴影 | `styles[].shadows[]` **非空** | `has_shadow`（728 条 true 却无数组、160 条 false 却有权、973 条缺席，U-48）、扁平 `shadow_*` |
| 发光 | 片段 `extra_material_refs` 引用到 `effects[type=="bloom"]`（带 `panel_id=="tool_text_glow"`） | `styles.bloom`（68 条**全为 null**）、`bloom_params` 键在（19,492 条里 19,491 条是占位，F-022） |
| 背景 | `background_*` 已设 | `check_flag` bit16（置位 129 条确实都设了背景，但已设的 8,964 条里 8,835 条不置位；且 bit16 会**单独翻转**，U-47） |

`check_flag` 位（17,454 条字幕 material，因果由各一次翻转观测成立）：**bit3(8)=描边、bit5(32)=阴影、bit6(64)=发光**，
bit0/1/2 恒置（值 4 仅 1 条例外）⇒ 参考文档的「7=基础」是把常量当位；**共同形态是「置位 ⇒ 特征存在，反向不成立」**
（bit8 置位者 1,293/5,457 无 strokes）→ 渲染不能靠位、写回不能只改位（F-029/F-030）。

### 5.4 位置与对齐

- `texts.alignment` 是**单字段互斥枚举**（不可拆 x/y 两轴）：左 `0`、右 `2`、上 `3`、下 `4`，**两枚居中按钮都不写值（整键消失）**；
  `1` 是老写入器（≤8.0）的水平居中显式编码（带键材料里 ≤8.0 占 96.99%、≥8.7 占 3.06%、11.6.0 的 3,513 条字幕里 `1`=0）
  ⇒ **读时 `absent` 与 `1` 都按居中；写回不得把 `1` 规范化成删键**（F-031，表 `alignment_by_version.csv`）。
- `segment.clip.transform{x,y}`（无 z）：**渲染位移 = 值 × 该轴边长 / 2**，原点=画布中心、**y 轴向上为正（负值向下）**、锚点=字框中心；
  **面板显示值 = 值 × 边长**，即面板单位是真实画布像素的 **2 倍**（为何 2× 未定，U-51）。整数按**各轴自己的边长**（不是固定 1920）。
- **改画幅不重写已存浮点**：9:16 键入的 `100/1080`、`-850/1920` 到 16:9 逐位不变，面板只是乘新边长再**就近取整**（177.7778→178、−478.125→−478、−637.5→−638 进位）；
  把 178 原样键回，剪映自己还原成 ≈177.7778/1920 ⇒ **面板整数不是存值，未经用户真改的 `transform` 必须原样搬运**（F-032/F-033/F-035，结案 U-08/U-49）。
- `canvas_config{width,height,ratio}` 是 **per-timeline** 的（同一草稿可 9:16/16:9/3:4 并存，根镜像只代表 `main_timeline_id`）→ 渲染与写回都要取**目标时间线**的画幅。

### 5.5 样式细节与卡拉 OK

- `fill.content{render_type∈solid|gradient|texture, solid{color[R,G,B] 0..1, alpha}}`；`render_type` 可缺席（4,972 条）⇒ 按 solid 兜底；`fill.alpha`（3,240）与 `solid.alpha`（4,291）**在同时出现的 3,214 例里逐位相等、0 例外** ⇒ 优先关系不可观测，载体是 `solid.alpha`（它能单独存在 1,077 例，`fill.alpha` 单独只有 26 例）；读侧 solid 优先、缺则回退，写侧两处同步（**U-02 结案，F-049**）。
- `shadows[]`：`distance/angle` 与 UI **1:1**（5↔5、−45↔−45°）、`alpha` 0..1↔百分比 ⇒ 推翻参考文档「em 相对且 /100」；`diffuse` = **面板模糊 ÷ 600**（12,874/13,032 = 98.8% 落在整数面板值上，且协议写死引擎值域 0..约 0.1667 = 100/600；**U-03 结案，F-049**）；同对象还有 `feather`(1,518) 与 `strokes`(22) 归属未定（U-64）；
  `thickness_projection_enable` 带键 5,368 条**全为 false**（语料从未启用，渲染可恒等处理但保留字段）；同一 UI 距离 5 在 `shadows[0].distance` 是 `4.999999523162842`（float32 往返）、在扁平 `shadow_distance` 是精确 `5.0` ⇒ **跨路径比较必须带容差**。
- `strokes[]` 可多条；`mode` 带键的 666 条**全是 0** ⇒ 语料判不了（U-24）；`width` UI 40↔draft 0.08 为单样本候选系数 500。
- 花字 = `styles[].effectStyle{id,path}` → `Cache/artistEffect/<rid>/<md5>/effectStyle.json`；气泡 = `texts.combo_info{text_templates[]}` ↔ `materials.text_templates`。
- 逐字配色 `styles[].useLetterColor`（带键 10,637 条**全部为 true**，缺席即 false）。
- 卡拉OK：`texts.words` **不是条目数组**，而是 `{start_time[], end_time[], text[]}` 三个等长平行数组（微秒，前几项常 0=缓存未填）；
  同族 `texts.ktv_color`（7,568 条带，`""` 7,262）、`segment.lyric_keyframes`（6,178）；逐字高亮的渲染语义 open（U-05）。
- 弯曲 = `texts.text_curve{enable, angle}`（angle 直接给度数）。

## 6. 画面链（权威：`spec/picture.yaml`）

| 主题 | 事实 | 等级 |
|---|---|---|
| 画面素材类型 | video 轨的 material 是 `materials.videos[]`，其 `type ∈ {video 15,402 / **photo 1,230** / image 2}`（含嵌套口径另见 `gif` 1）⇒ **图片与视频共用同一 bucket 与同一条渲染链**，不另设轨道类型；`mixed` 轨也指 `videos.video`(1,511)/`videos.photo`(44) | verified F-048 |
| `clip` | 带键片段 42,135（另有 4,325 条整值 null）；子键 `transform(37,890) flip(37,890) scale(32,855) rotation(13,505) alpha(12,586)`；**无 z**；缺席默认 transform/scale/rotation/alpha/flip = 0/1/0/1/false（open，需成片确认） | verified F-010 |
| 等比缩放 | `uniform_scale` 在 **segment** 上不在 `clip` 内（C-001）；四形态并存 `{}` 18,010 / `{on:true,value:1.0}` 12,467 / null 4,325 / `{on:false}` 35；**`on` 缺席=true**，`value == x/y` 是比例缓存（12,465 命中 / 8 过期）且只在等比开着时维护；开着且 x≠y 时渲染读哪轴判不了（U-44） | verified F-027 |
| 裁剪 | `materials.videos[].crop` 是**四角多边形** 8 键，**16,634** 个视频 material 全带该键，但 **11,589 个是 `{}` 空占位**、4,955 个满形里 **4,875 恰等于满框恒等** `(0,0)(1,0)(0,1)(1,1)` ⇒ **真裁剪只 80 条**。归一化已判：**源素材 [0,1]、左上原点、y 向下**；上限仍 open（U-10 已收窄）。`crop_ratio` 是**字符串**（`free` 4,914 / 16:9 51 / 9:16 17 / 3:4 6 / 4:3 5 / 1:1 2）、`crop_scale` 4,949/4,950 恒 1.0（占位）；`corner_pin` 是**另一套归一化**（11 条，观测值全 −1.0） | verified F-049（旧 single F-009 已被实测替代） |
| 混合模式 | **不是 segment 字段**：`effects[type=="mix_mode"]`（166 次 / 82 份内容）→ `name` 中文名 + `resource_id` → `Resources/MixMode/<md5>`；10 个内置包的 frag 尾行是 `*BlendPreMul(fg,bg)` ⇒ **全部按预乘 alpha**（10 包 `config.json` 的 `alphaState` 全为 2）；「正常」= 该 effect 不存在；键名扫描证实语料里没有任何 blend/mix 字段。**直连方法是 `Resources/MixMode/MixMode.json`**（10 条 `{nameId, effectId, resourceId, path=md5}`），r3 全量 join **166/166 命中、0 未匹配** ⇒ 10 个包的中文名与 GLSL 函数一次闭合（**U-12 结案**）；但协议枚举有 **12** 个模式、本机只有 **10** 个包 ⇒ **差值 / 颜色滤镜 没有本地资源包**，必须显式降级；`nameId` 不可 join（C-013） | verified F-006/C-005/F-049 |
| 蒙版 | 两个 bucket：`common_mask`（196 份内容 / 390 条目，内置形状，`config{width,height,centerX,centerY,feather,rotation,invert,roundCorner,aspectRatio,expansion}` + `contour_path` + `text_config`）与 `masks`（21 / 46，资源型）；判别是 `category`（video 321 / adjust 70），`type ∈ mask|none|""`（空串那 2 条要当「无」）；**config 是归一化值，两轴均按画布宽度归一**（px = value × `canvas_config.width`，与 transform 的「各轴自己边长」除数不同）；`segment.enable_adjust_mask` **不是**蒙版开关（U-13 否定） | verified F-008/F-018 |
| 转场 | 挂在**前一个**片段的 `extra_material_refs` → `materials.transitions[]`；具名 2,193 种；键为 `{name,id,category_name,effect_id,resource_id,path,duration,is_overlap}`，`duration` **100% 存在**（2,343/2,343）⇒ 时长是资源自带而非反推，**`resource_id` + `path` 是复现内核的唯一入口**（与动画同构，`Cache/effect/<rid>/<md5>`）；`is_overlap` 只 75% 带；窗口 `[cut−d/2, cut+d/2]` 且不改片段时长 = single —— **「不改片段时长」这半边已有一条成片支持**（转场挂在切点前一段，下一段起点减本段终点 = 0.000 s，2026-10-28 单例，见 `../evidence/case-crosscheck.md`），半窗仍在 M2 判 | single F-024 |
| 画面阴影 | 载体 `materials.video_shadows[]`（12 键），模糊度键名是 **`ambiguity`**（不是 blur）、`distance = UI/100`；与 `videos.video_mask_shadow`（键名用 `blur`）是**两回事** | verified F-021 |
| 画面描边 | **资源包效果**：类型选「无」时条目只有 `{id,type,enable_video_stroke,resource_id:"",path:""}`（语料「只有开关」的真相）；选样式后补 `resource_id/path/color/adjust_params[]`；`color==[1.0,R,G,B]`（**首位不是 alpha**）、`effects_adjust_size/alpha = UI÷100`、`min_scale` UI 不暴露（默认 320.0）、每项 `default_value` 恰等 UI 默认 ⇒ 可当校准锚点；**类型不是枚举字段**，复现必须解析 `Cache/effect/<rid>/<md5>` | verified F-027 |
| 关键帧 | `segment.common_keyframes[]` 记录 `{id, material_id, property_type, keyframe_list}`；控制点 `{id,left_control,right_control,values[],time_offset(87%),curveType(44%),graphID,string_value}`；`curveType ∈ Line/FreeCurveInOut/FreeCurveIn/FreeCurveOut/CurveInOut`，**无 Hold/Smooth/Beizer**（C-009）；实现只需「有控制柄走三次贝塞尔，否则线性」；`property_type` 70 种；`material_id` 空串=作用于片段自身，非空时指向某条目的 **`constant_material_id`**（228 命中 / 161 两边都命不中，U-43） | verified F-014/C-009 |
| 骨架陷阱 | 没做过动画的片段可带 **31 条单帧骨架轨道**（`keyframe_list` 长 1、无 `time_offset`、控制点 `(0,0)`）；改 `clip.scale.x` 会同步改 `KFTypeScaleX` 的帧值；等比关闭会**新建** `KFTypeScaleY`、开回来会**删除**它 ⇒ 只改标量不改骨架即与剪映不一致，创建/删除时机 open（U-45） | verified 现象 |
| 派生缓存 | 三条等式都成立且**只读源字段**：`speeds[].speed==segment.speed`（11,680/11,680）、`uniform_scale.value==x/y`（12,465/8）、`shadow_point` 模 `==0.18×distance`（19,847/963/266）且方向 `==(cos,sin)(angle)`（20,834/21）；写回要么同步要么整键删除 | verified F-023 |
| 必须保真的杂项键 | `hdr_settings`（`{mode:1}` 10,980 / `{intensity,mode,nits}` ≈4,903）、`render_timerange`（**6,009 条真有两键内容**，不能当占位）、`caption_info`（13,835 条**全为 null**，别写分支）、`color_correct_alg_result`（键名带官方拼写错误 `*IntensityFisrt`）、`source`（只见 `segmentsourcenormal`）、`keyframe_refs/template_id/track_attribute/visible/reverse/…` 见 `picture.yaml -> preserved_segment_keys` | verified F-024 |

## 7. 预设与资源解析（权威：`spec/animations.yaml`、`panel-map.yaml`）

- 容器 `material_animations[].type` **恒为 `sticker_animation`**（34,821/34,821），字幕动画与视频动画也叫这个名 ⇒ **绝不用容器 type 筛类别**，用 `animations[].material_type` 与 `animations[].panel`。
- 动画条目 `type` 有 **5 类**：`in 8,388 / loop 1,587 / out 303 / caption 158 / group 129`（`caption`=字幕动画子 tab，`group`=视频动效「组合」；旧规格只记三类）。
- **非零 `start` 只出现在 out(108) 与 group(10)**；in/loop/caption 的 `start` 缺席或 0。缺 `duration` 键时回落到预设包 `extra.json.setting.animation_duration`（**单位秒**）。
- 大量条目**没有 name**（空串 in 1,418 / loop 867 / out 25，另有 `null` 的 caption 56 / out 53 …）⇒ 不得假设 name 存在，也不把「无 name」当错误。
- **曲线是可读的**：包内 `config.json / content.json / extra.json / anim.prefab(YAML) / <Name>.lua（明文 UTF-8）/ gles2_*.vert|frag / Sprite2D.xshader`，
  Lua 首行用 `--@input float duration = 1.5{"widget":"slider","min":0.1,"max":6.0}` 声明可调参数与区间 ⇒ **不需要从成片反推**，成片只用于校验（C-007）。
- 解析链（顺序即优先级）：展开路径宏 → `animations[].path` → `Cache/effect/<resource_id>/<md5>/` → 用 `(resource_id, md5)` 目录名补 → **按 basename 重查**（path 常指向另一台机器的旧安装位置）→ 按 name 关键词近似并**标注「近似」**。
- 本机实体包只覆盖可定位预设的 **36.6%**（46,233 / 126,225，含嵌套口径的一次性清点）⇒ 「按名近似」是**常规路径**而非常态异常（U-21）。
- `category_name` 混了中文名/空串/拼音/英文/繁体五种写法 ⇒ 匹配不得假设单一语言，`""` 与缺席都当「未分类」。
- **同名不是同一预设**：`name` 只是显示文案，身份是 `resource_id` + `path` 尾段 md5。r3 里 `渐显` 一个名字就有 3 个不同 id（69 / 66 / 51 条），包内实现不同；一条成片可以同时用两族（字幕族 `Appear.lua`、视频族 `Transform.lua` + shader）。按名匹配只能当**近似**并标注，能力证明必须落在 id 上（`../evidence/case-crosscheck.md`）。
- 资源字典 `ressdk_db/<account>/rp.db` 在本机**表结构在、rows=0** ⇒ 命名一律取草稿内联 `name`（F-013）。

## 8. 面板 ↔ 字段 换算速查（权威表是 `panel-map.yaml`，逐控件）

| 控件 | 字段 | 换算 | 等级 |
|---|---|---|---|
| 字号 | `styles[i].size`（顶层 `font_size` 仅镜像） | **1:1** | verified F-034 |
| 位置 X/Y | `clip.transform.x/.y` | 面板 px = 值 × 该轴边长；**渲染位移 = 面板 px ÷ 2**；y 向上为正 | verified F-035 |
| 缩放 | `clip.scale.x/.y` | UI% ↔ 倍率（100% = 1.0）；UI 整数值不保证落成整浮点（200%→`1.9999999999999998`） | verified |
| 等比 | `segment.uniform_scale` | `on` 缺席=勾选；`value=x/y` | verified F-027 |
| 不透明度 | `clip.alpha` | 50% ↔ 0.5，域内从不 >1 | verified |
| 混合模式 | `effects[type=="mix_mode"]` 的 `name/resource_id`（或 `effect_id`、`path` 尾段 md5） | 「正常」= 条目不存在；线性加深 = `linear_burn`（旧注「线性减淡(添加)」错） | verified F-006/F-049 |
| 旋转 | `clip.rotation` | 度数，实测域 −215..360 | verified |
| 描边（字幕） | `styles[].strokes[].{content.solid.color,width,alpha}` | `width` UI 40↔0.08（候选系数 500，单样本） | verified/单样本 |
| 阴影（字幕） | `styles[].shadows[]` | 颜色/不透明度(×100)/距离/角度 **1:1**；模糊度 **÷600**（面板 0..100 → 引擎 0..1/6）；协议缺现值参考 距离 8 / 角度 −45 | verified F-049 |
| 发光（字幕） | `effects[type=="bloom"].bloom_params` | 强度 30↔`strength 0.3`、范围 20↔`range 0.2`（÷100）；11.6 面板**没有角度控件**，`dir_x/dir_y` 恒 0.5（U-27） | verified F-017/F-022 |
| 描边（画面） | `video_strokes[].adjust_params` | ÷100；`color==[1.0,R,G,B]` | verified F-027 |
| 阴影（画面） | `video_shadows[].{alpha,ambiguity,distance,angle}` | 30%↔0.3、10%↔`ambiguity 0.1`、距离 5↔`0.05`、角度 1:1 | verified（系数单点）F-021 |
| 蒙版 | `common_mask.config.*` | **两轴都按画布宽度归一**；`centerX/centerY∈[-1,1]`、`rotation` 度数、`feather` 0–1、`roundCorner` 0–0.88 | verified F-018 |
| 对齐（6 按钮） | `texts.alignment` | 0/2/3/4 + **两种居中编码（`1` 与缺席）**；`clip.transform` 不随之改变 | verified F-031 |
| 动画 | `material_animations[].animations[].{type,name,resource_id,path,duration,start}` | 时长微秒；`start` 只在 out/group 非零 | verified F-020 |

## 9. 写回：门禁 → 事务 → 不变式（权威：`spec/write-rules.md` + `crypto.md` §5）

1. **只读期结束的条件**：三条 crypto 门禁通过 + 目标 sha256/指纹快照可用 + **回滚实测可用**。
2. **九步事务**：预检指纹 → crypto 门禁 → 快照（整目录，`temp/` 内带时间戳）→ 只在内存改 → 结构校验 →
   同目录 `mkstemp`+`fsync`+`os.replace` → **逐副本回读做语义比对** → 复验 → 失败全量回滚。
   多副本之间存在被硬杀的混合窗口 ⇒ **先写非活动副本、最后写活动副本**，并把「已写清单」落盘。
3. **并发**：写前重算指纹，与预检不符即停止上报；`JianyingPro.exe` 在跑只告警不阻断（完整快照+写后回读+明示覆盖风险）；
   `.locked` 在 ⇒ 默认**拒绝**写入并要求显式批准（其写入侧后果仍 open，须在副本草稿上做受控实验，U-46）。
4. **必须同步的三处**（改源即改缓存，否则静默不一致）：`speeds[].speed`、`uniform_scale.value`、**单帧骨架帧值**（`KFTypeScaleX/Y…`）。
5. **不得改写**：`##_draftpath_placeholder_<uuid>_##/` 整串原样搬运（uuid 身份未知，U-41）；缺失的 `timerange.start` 不得补写；
   居中态的 `alignment:1` 不得规范化成删键；未动过的 `transform` 不得做 px 往返；不得给无 `font_size` 的字幕补该键。
6. **要容忍的应用自归一化噪声**（别当回归）：`type:""`→`"none"`；`Cache/effect/…`→`Cache/artistEffect/…`（同资源换缓存根）；
   浮点末位 ULP 漂移；`extra_material_refs` 数组**顺序轮换**；UI 整数不保证落成整浮点。
7. **最终验收**：剪映能正常打开、时间线可见、**不出现修复/重建提示**。

## 10. 尚未标定的（读之前必须知道的坑）

| 影响 | 开放项 | 一句话 |
|---|---|---|
| 预览与导出一致性 | **U-51** | 面板单位为什么是真实像素的 2 倍（半像素标度 vs 2× 设计空间）—— 一次 2160×3840 导出即可分开 |
| 字号精度 | **U-07** | `0.00574` 有无精确形式（按带宽用，别当精确值） |
| 图层次序 | **U-15** | `render_index` 升序是靠下还是靠上 |
| 缩放语义 | **U-44** | 等比开着且 x≠y 时渲染读哪一轴 |
| 写回正确性 | **U-45 / U-46**（U-57 只读普查已做、待落 F 条目） | 骨架轨道的创建/删除时机；`.locked` 在时写盘会怎样；120 个 hybrid 草稿有 `Timelines/` 却枚举不到时间线副本（普查结论：里面确实没有 `draft_content.json`，根镜像是唯一活副本；扫描器候选名与零行归类待修，见 `unresolved.md`） |
| 写回 stamp 与轨道语义 | **U-60**（F-047 新开，F-051 加硬约束）/ ~~U-61 已结案~~（F-050） | 本机只剩 2 个完整安装（12 个版本名目录是更新载荷，F-051）⇒ 对照实验必须用 `11.1.0.14287 - 副本`，且 agent 层是 11.6 新增；版本轴有两套 stamp：桌面剪映恒 `version=360000` + `platform{windows, 3704, lv}`，**同一安装包的内置 agent 写 `400000` + `platform{web, 348188, "15.4.0"}`** —— 该跟着哪一边、11.6 读回 400000 会不会重写都没测；另：`tracks[].flag` 的语义**已结案**（U-61，F-050，轨道内容类别枚举 7 值） |
| 资源可用性 | **U-21 / U-22 / U-41** | 预设缓存只 36.6%；贴纸与文字模板目录缺失；路径宏 uuid 身份 |
| 版本序列重建 | **U-66**（F-051 新开） | 跨版本对照面实测只有 2 个安装，而语料 `platform.app_version` 覆盖 4.8~11.6 （含本机不存在的安装根）⇒ 版本序列必须从草稿字段分桶重建，不能靠安装目录 |
| 样式判据 | **U-47 / U-48 / U-24 / U-38** | `check_flag` bit16 含义；`has_shadow` 谁权威；`strokes[].mode` 语料判不了；蒙版描边侧因果 |
| 画面语义 | **U-02 / U-04 / U-09 / U-10 / U-11 / U-12 / U-23 / U-40** | fill 两级 alpha 优先级；混合位 +4；`original` 画幅来源；裁剪值域；不透明度与混合先后；MixMode 10 包全对应；effects 33 种 type（其中 6 种单样本）；蒙版/关键帧首尾钳制（U-35） |
| 播放器架构 | **U-55 / U-58 / U-67**（上级 U-53 与下级 U-54/U-56/**U-59** 已结案） | 六条判据里只剩 **seek** 不达标：服务端解法已证伪（F-045），**播放器侧的「关键帧索引 + 闭区间取块」也已被实测证伪**——自建 mediabunny+WebCodecs 管线在相机片上仍 207.6 / 257.8 ms，与 `<video>` 同量级 ⇒ 成本是 `GOP/2 ÷ 管道fps` 的**结构项**（GOP 实测 1 秒，F-053），达标的杠杆是**把素材搬进可硬解的 profile**（F-054）。首帧已不是问题（2.7–35.7 ms）；NAS 首帧的病因也不是取数字节而是每请求重连 + SMB 重开（U-59 结案，F-053/F-054）⇒ keep-alive/多端口成自建管线前置。**HEVC 可用但只在有硬件通路时**（F-044 + F-054：无硬件通路 mediabunny 直接抛异常，不是慢）；多路合成带 GPU 达标（F-043），且 F-054 给出**不经过 WebGL 的探针**用来分离硬解/硬栅（U-58 剩光栅一格）。新开 U-67：XAVC 的 `elst` 有**正好 1 帧**的非零 `media_time`，剪映的 `source_timerange` 是否已折进去未判 |

## 11. 三十条「不要用」（每条都有过现场事故）

1. 不要用 `isFileEncrypted` 判加密（对已确认可解密的密文恒 false）——用首字节 + JSON 解析。
2. 不要用「密文→明文→密文逐字节相同」当门禁（容器带随机熵，不可能成立）。
3. 不要按文件名认副本身份，也不要按 mtime 判「哪个是当前状态」——解密比 content-id。
4. 不要把「等长而摘要不同」当内容分叉的证据（方向只能反过来用）。
5. 不要用 `font_size` 当字号权威（分段样式与整键缺席都会错）。
6. 不要用 `check_flag` 判样式开关（单向蕴含，且 bit16 会单独翻转）。
7. 不要用 `bloom_params`/`panel_id` 键在判发光（19,491/19,492 是占位外壳）。
8. 不要用扁平 `shadow_*`/`border_*`/`background_*`/`text_color` 判开关（恒写镜像，读它们一律得「开」）。
9. 不要用 `tracks[]` 数组顺序当绘制权威（27.7% 反例）。
10. 不要用容器 `material_animations[].type` 筛动画类别（恒 `sticker_animation`）。
11. 不要把面板显示的整数当存值搬运（是 round 过的显示值；改画幅也不重写已存浮点）。
12. 不要按「字符数」算 `styles[].range`（UTF-16 code unit）；也不要在主进程加载 `videoeditor.dll`，
    或给本地 headless Chrome 传**相对** `--user-data-dir`（会被忽略并附着到你正在用的浏览器会话，退出码 21、什么都不渲染）。
13. 不要把 `--disable-gpu` 下的读数当浏览器的能力（F-043/F-044）：它同时关掉媒体硬件解码与 WebGL 光栅，
    HEVC 的「完全不可用」和多层合成 14.95 fps 都是这一列造成的**下界**，不是上限。
14. 不要在 `VideoDecoder.isConfigSupported` 里传合成的 `description`（F-044）：一个 4 字节假值 `00 00 00 01`
    单独就能让本来支持的配置报 False。能力探测必须用**被测文件里取出的真实配置记录**（本例是从 MP4 取 hvcC）。
15. 不要裸调 `ffmpeg`（F-042：PATH 上那个安装已消失，旧 spike 脚本按现状跑会直接失败），也不要把
    `-hwaccel cuda` 当硬解（本机初始化失败后**静默回落软解**，速率看不出来），更不要用 `*_qsv`
    （无核显时不是快速失败，而是**挂到超时**）。
16. 不要引用没写分母口径的速率数（F-039/F-042 同族事故）：`-f null` 的解码上限与 ffmpeg→PIL 的端到端管道
    是两个量；没有重复次数与区间的单次读数（本例首跑 18.2、复跑 26.9）不得进选型依据。
17. 不要在两个探针 run 之间共用同一个 `--user-data-dir`（F-043 第 5 条）：会附着上一个还没死透的会话，
    并把两份结果**交错写进同一个 jsonl**（本仓库已留下一行撕裂的记录，标为不可引用）。
18. 不要用 `track.type` 分派「字段表」或「语义类型」（F-048）：片段没有 `type` 键，而 `texts.subtitle` 有 564 次是被
    **mixed 轨**引用的——「字幕一定在 text 轨上」不成立；语义要看 `material_id` 指向的 bucket 及其 `type`。
19. 不要按「本类型通常有这些键」补键（F-048）：8 键的 adjust 最小形与 45 键的完整形在语料里都是合法状态，
    补齐会凭空造出 `caption_info`/`lyric_keyframes` 这类占位；新建片段应复制同类型的**最小形**。
20. 不要用 `audios[].type == "music"` 认音频素材（F-048 作废旧规则）：`music` 只 1,302 条，
    多数是 `sound`(7,069) 与 `video_original_sound`(3,062)，配音是 `text_to_audio`、提取音乐是 `extract_music`。

21. 不要 join `Resources/MixMode/MixMode.json` 的 `nameId` 来定混合模式语义（F-049/C-013）：它把既是
    `ScreenBlendPreMul`、又被草稿写成「滤色」的包标成了 `color_filter`。可直连的是 `resource_id`/`effect_id`/`path` 尾段 md5。
    更不要假设 12 个协议模式都有本地包——**差值 与 颜色滤镜 无包**，遇到必须显式提示降级，不许静默按 normal 渲。
22. 不要拿 `tables/js_model_keys.csv`（剪映自带 agent 的 draft 模型层默认值）回填桌面草稿的缺省（F-049）：
    `check_flag` 模型默认 63 而语料众数 39（11,180 次），`alignment` 模型默认 1 而 11.6 桌面**整键缺席**。
    它只能当「字段名与合法性白名单」用；「官方 agent 不写某键」也**不等于**「草稿不该有该键」。
23. 不要指望从任何字段推出叠放次序（F-049 加强 U-15）：协议确有 `z_order`（「数值越大越靠前」，且只有 `<video>` 有、`<image>` 没有），
    但剪映自己的草稿写入层 `app-server.mjs` 里 `z_order`/`zOrder`/`z_index` **0 命中**，自带工具链的 layer-planner
    明写 `z_order_is_design_intent_only` 与「空间重叠要靠实测遮挡次序」。既不要把 XML `z_order` 当 `render_index`
    的别名来排层，也不要按 `tracks[]` 数组位置排层。
24. 不要用「键存在」证明裁剪/阴影/填充被设置过（F-049 再证）：`videos[].crop` 有 **11,589 个 `{}`**，
    满 8 键的 4,955 个里 **4,875 个就是满框恒等**；`styles[].shadows[]` 有 14,552 条但 `feather` 只 1,518 条；
    `fill.alpha` 与 `solid.alpha` 同时存在的 3,214 例里**永远相等**。判「设过没有」要看值与形态，不能看键。

25. 不要把 `tracks[].flag` 的「整键缺席」与 `flag:0` 当两种状态，也不要把「非首条 video 轨」误写成「主轨标记」（F-050 结案 U-61）：
    `flag` 是官方轨道内容类别枚举（`FlagNone=0 / FlagTextSubtitle=1 / FlagSubVideo=2 / FlagTextLyric=3 / FlagVideoSubtitle=4 /
    FlagAudioSubtitle=5 / FlagAiScriptSubtitle=6`），桌面写入器只用 0/缺席/1/2/3；
    **`flag==2` 的含义是「不是首条 video 轨」**（首条 1,533 条里 0 条写 2，非首条 1,662 条全写 2），
    `flag==1` 是「字幕轨」（971/1,004 = 96.7% 装 `texts.type=="subtitle"`）。
    同时不要把 `flag` 缺席的 **mixed** 轨当混装容器——那批 298/315 只装 `videos.video`、一条文字都没有，实质是另一种视频轨（U-62）。

26. 不要把 `segment.render_index` 当叠放次序的唯一真相源（F-052）：贴纸与文字模板落地时同一个值**还会写进两处**
    —— `clip.filter.filterLayer = BigInt(renderIndex)` 与 `clip.layer = BigInt(v)`；改一处不改另两处就是静默不一致。
    也不要为了「对齐基座」去打开 `free_render_index_mode_on`：桌面语料 2,050 份里**从不为真**（缺席 1,402 / false 648 / true 0），
    打开会把基座换成 video 2000 / adjust 7000 / effect 11000 / text&sticker 14000+count+2，造出桌面不会产生的值。
    它和 `render_index_track_mode_on`（true 1,978 / false 63）是**两个不同的根键**，别混用。

27. 不要把 seek 慢归因于取数（F-045 + F-054 两轮各自证伪一半）：服务端改响应头/缓存/钳位无效（F-045），
    播放器侧换成「sample table + 精确闭区间取块 + WebCodecs」**同样无效**——自建管线在相机片上中位
    207.6 / 257.8 ms，与裸 `<video>` 的 266.7 / 278.2 同量级。真实成本是 `GOP/2 ÷ 管道fps` 的**结构项**
    （GOP 实测 1 秒，F-053）⇒ 想压进 150 ms 要换**可硬解的 profile**，不是换索引或换预取量。
    但也不要据此认为关键帧索引没用：它负责的是**首帧**（实测 2.7–35.7 ms）与**尾部 moov**
    （13/13 素材 moov 在文件尾、零 faststart，不预读索引就得做一次远距离读）。
28. 不要把 `--disable-gpu` 下 HEVC 的失败读成「素材坏了」或「Chrome 不支持 HEVC」（F-054 给 F-044 加限定）：
    无硬件通路时 HEVC **不是慢，是根本没有解码器**——mediabunny 抛
    `This video track cannot be decoded in this environment`，而**容器/元数据那段照常成功**（22.4 ms）。
    ⇒ 「解封装成功」不等于「能解码」；能力判定必须在上屏前做，并把这类异常映射成显式的
    `hw_decode_unavailable` 标注，绝不允许落成一层的空白（这是本项目第一次拿到可依赖的显式信号）。
29. 不要在 `Connection: close` 的网关上做闭区间精确取块（F-054）：实测**单次 seek 触发 11–62 个请求**，
    一整轮 1,887 请求 / 195 MB；每请求重做 TCP 握手、再叠上 Chromium 约 6 连接/源的上限，
    就是旧方案「17–82 个元素在同一源上互相排队」那条失败的量化形态。⇒ keep-alive / 多端口是
    自建管线的**前置条件**，不是优化项（NAS 首帧的 +263 ms 也记在这里，不在字节数上，F-053 §3）。
30. 不要拿 `stts` 第一条 delta 当平均帧率（F-053）：手机 HEVC 录屏是**变帧率**（`stts` 条目 76–209），
    首条 delta 折算出 10–12 fps 的假值，而真实平均是 57.9–59.1 fps ⇒ 「帧号↔时间」必须查 `stts`，
    也不能把这类素材标成「4K60p」写进规格（F-042/F-038 沿用的 60p 说法需按此更正）。

| 合成次序 | `render_index` 六族分配器已读出（JS 原文）：filter 10000 / videoEffect 11000 / pluginEffect 15000 / text&sticker 14000 步长 **+2**，video 与 adjust 无基座（`max+1`）⇒ 主带对上；`free_render_index_mode_on` 语料**从不为真** ⇒ free 分支只在 agent 面出现（F-052） |
