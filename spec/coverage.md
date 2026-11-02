# 规格覆盖清单（实测字段 vs 规格记录）

复现（一次跑完，顺序不能换）：`python scripts/corpus_scan.py --limit 0` → `python scripts/corpus_detail.py` →
`python scripts/spec_audit.py` → `python scripts/build_evidence_tables.py`（把 `temp/spec-audit/spec_coverage.csv`
镜像到 `../evidence/tables/`）→ `python scripts/check_doc_counts.py`（文档数字↔证据对齐）。判定方式：把语料实测到的
每个字段名拿去 `docs/spec/` 全文里查是否出现。
基数：**r3 = 2050 份去重内容 / 2215 份内容文件**（快照 2026-10-16；`stats.json -> corpus.snapshot_date` +
`manifest.json` 的 sha 是唯一对齐锚）。r1 曾把频次按文件计且被根别名翻倍（F-019），r2→r3 的差异是一次草稿删除
造成的真实漂移（F-020）。

## 覆盖率

| 类别 | 实测字段数 | 规格已记录 | 覆盖率 |
|---|---|---|---|
| material bucket | 42 | 42 | **100%** |
| `styles[]` 键 | 15 | 15 | **100%** |
| 关键帧 `property_type` | 70 | 70 | **100%** |
| `clip` 字段 | 6 | 6 | **100%** |
| 枚举取值（bucket.field=value） | 616 | 615 | **100%** |
| 轨道字段 | 7 | 7 | **100%** |
| segment 字段 | 52 | 52 | **100%** |
| 顶层键 | 40 | 37 | 92% |
| bucket 内键名 | 718 | 531 | **74%** |
| 合计未记录 | — | **191**（r2 时是 357） | — |

结论：**类别级覆盖已完整，字段级缺口从 357 降到 192**，剩下的集中在「phase-2/3 素材的细键」（音频、贴纸、模板、
调色、AI 元数据）——这些按 `scope-and-phases.md` 归 skip/2/3，登记即可，不影响 phase-1 正确性。
本轮补齐的主要是**真正影响画面与写回**的那一批：`hdr_settings`、`caption_info`（恒 null）、`color_correct_alg_result`、
`render_timerange`、`keyframe_refs` 等 segment 键（`spec/picture.yaml` 的 `segment_extra_fields` / `preserved_segment_keys`）、
70 种关键帧 `property_type` 全量、以及 `draftpath` 宏与三条派生缓存等式（F-023/F-024）。

> 编号说明：U-24…U-32 已被面板标定工作占用，本清单的新项从 **U-33** 起。

## A. 本轮已补录（此前缺、且影响 phase-1 渲染）

| 项 | 实测结论 | 落在 |
|---|---|---|
| 关键帧记录与曲线形状 | `{id, left_control{x,y}, right_control{x,y}, values[], time_offset, curveType?, graphID?, string_value?}`；`curveType ∈ Line/FreeCurveIn/FreeCurveOut/CurveInOut`，44% 才带该键 | `spec/keyframes.yaml`（关闭 U-14） |
| `extra_material_refs` 引用组成 | 按轨道类型逐一实测（见下） | `spec/materials.yaml`（把原「single」推断升级为 verified） |
| `responsive_layout` | **三种形态**：`{}` 34,926 / 五键默认 16,689 / 缺席 103；五键形态实测五键全为默认（`structures.json -> responsive_layout_values_top`） | `spec/picture.yaml`（关闭 U-06；旧表述「16,689 条全部」由 F-020 更正为「两种写入形态都只有默认值」） |
| 转场记录形状 | `duration` **100% 存在**（2343/2343）、`is_overlap` 75%（1765）、`effect_id/resource_id/path/category_id/category_name/request_id/third_resource_id/source_platform` | `spec/picture.yaml` |
| 内置蒙版形状词表 | `common_mask.type ∈ {mask, none}`；`name ∈ 矩形150 / 镜面104 / 线性74 / 圆形46 / 钢笔9 / 抠像3` | `spec/picture.yaml` |
| 轨道字段 | `track.attribute`（0:3231 / 1:170 / 2:38 / 4:10 / 6:8 / 3:4 / 16:2 / 8:2 / **17:1**，旧行漏 17）；`is_default_name` 值域 **true 9,898 / 缺席 82 / false 10**；`name` 只出现在 3,365 条轨道上且 **mixed 从不写**；`flag` 按类型分岔（video/mixed 用 2、text 用 1、其余只 0 或缺席） | `spec/picture.yaml -> tracks.track_fields`（F-048 全量重跑，八类轨道条数与旧行逐位一致） |
| 轨道类型 ↔ 素材类型 | 八类轨道的 `material_id` 各自落到哪个 bucket.type：video→`videos.{video,photo,image}`、audio→`audios.{sound,video_original_sound,music,text_to_audio,extract_music}`、text→`texts.{subtitle,text,lyrics}`+`text_templates.{…, _subtitle, _lyrics}`、sticker→`stickers`+`shapes`、effect→`video_effects.{video_effect,face_effect}`、filter→`effects.filter`、adjust→`placeholders.adjust`、**mixed→多类混指** | `spec/picture.yaml -> tracks.track_type_material_map`、`spec/materials.yaml` 各 bucket note（F-048；mixed 归 U-62） |
| 片段键集形状 | **形状不由轨道类型决定**：全语料只有一种 45 键完整形（6,004 个片段，audio 2,244 / text 2,237 / video 1,233 / effect 109 / adjust 78 / sticker 58 / filter 45），另有 34 键形与各类型的最小形（video 竟有 524 种不同键集） | `spec/picture.yaml -> segment_shapes`（F-048） |
| `render_index` 分带 | 主带 0 / 10000 / 11000 / 14000 之外，实测还有 `15000-15999` 254、`16000-18999` 29、`19000+` 207（全在 text/sticker），且 **mixed 跨四个带** | `spec/picture.yaml -> compositing_order.bands_measured`（次带归 U-63、mixed 归 U-62，F-048） |

引用组成（verified，`drafts` 键数即「多少条 segment 引用了该 bucket」）：

- **video**：effects 66,237、speeds 15,081、canvases 14,988、sound_channel_mappings 14,988、vocal_separations 14,988、placeholder_infos 11,444、material_animations 11,397、material_colors 9,754、hsl 9,114、loudnesses 2,751、drafts 2,694、transitions 2,050
- **audio**：speeds 12,742、sound_channel_mappings 12,742、vocal_separations 12,742、beats 12,714、placeholder_infos 11,091、realtime_denoises 2,124、vocal_beautifys 1,442、audio_fades 1,109、loudnesses 1,030、time_marks 266、drafts 138、audio_effects 108
- **text**：material_animations 21,223、effects 3,028、video_trackings 52、**`<未解析>` 10**
- **adjust**：effects 3,101、hsl 866、color_curves 45、common_mask 44、primary_color_wheels 2、log_color_wheels 2
- **sticker**：material_animations 156、video_trackings 10
- **mixed**：material_animations 1,916、speeds/placeholder_infos/canvases/sound_channel_mappings/material_colors/vocal_separations 各 1,555、effects 1,494、hsl 930、drafts 542、transitions 297、audio_fades 256

## B. 待补录（影响 phase-1 正确性，尚未展开）

| 项 | 为什么影响画面 | 处理 |
|---|---|---|
| 顶层 `keyframe_graph_list` + 关键帧内 `graphID` | 关键帧曲线的图结构容器，可能承载整组曲线的编辑信息 | 新增 U-34，M2 前实测 |
| `segment.string_value` 型关键帧的含义 | 1739 个控制点用字符串承载值（疑为颜色/文本） | 新增 U-33 |
| 控制点首尾之外的钳制规则 | 直接决定动画首尾帧是否正确 | 新增 U-35 |
| `enable_mask_shadow` / `enable_mask_stroke`（segment 级）与 `videos.video_mask_shadow/stroke` | **蒙版**描边/阴影的开关与参数体（顶层带键各 8,505 条，其中占位 8,498/8,489、带参数 7/16）；**与画面侧无关** —— 画面侧阴影是 `materials.video_shadows[]` | 已定案：`spec/picture.yaml`、F-021；开关与参数的配对**非双向**，残余因果留 U-38 |
| `placeholder_infos.*`（1,401 份内容、video 引用 11,444 次） | 语义未知但出现率极高；r3 首见 `meta_type: "none"` | 新增 U-36（仍开放）；与 `placeholders`(153 份) 区分 |
| `track.attribute` 位含义 | 疑为轨道能力位（0 为主，少量 1/2/4/6/8/16） | 新增 U-37 |
| 顶层 `mixed_track_mode_on` / `free_render_index_mode_on` | 与合成顺序开关同族，可能改变层级解释 | 并入 U-15 一并判定 |
| `relationships` / `mutable_config` / `business_info` / `extra_info` / `draft_type` / `lyrics_effects` / `is_drop_frame_timecode` / `last_modified_platform` / `color_space` | 元数据类，不影响像素但影响解析器容错与写回保留 | 归入「保留不解释」清单，写回时必须原样保留 |

## C. 明确不补（超范围，登记即可）

- **调色类（用户要求跳过）**：`enable_color_curves`、`enable_color_wheels`、`enable_hsl_curves`、
  `enable_smart_color_adjust`、`enable_color_match_adjust`、`enable_color_adjust_pro`、
  `enable_color_correct_adjust`、`color_correct_alg_result`、`material_colors.*` 细键、`hsl.*` 细键、
  `log_color_wheels.*`、`primary_color_wheels.*`，以及 KFType{Brightness,Contrast,Hue,Filter,ColorMatch,
  SmartColorAdjust,ChromaIntensity,LightSensatione,Sharpen,Vignetting}。
- **phase-2 音频**：`audios.ai_music_*`、`aigc_*`、`cloned_model_type`、`formula_id`、`copyright_limit_type`、
  `sound_channel_mappings.*`、`vocal_separations.*`、`loudnesses.*`、`realtime_denoises.*`、`beats.*`、`time_marks.*`。
- **phase-3 特效/贴纸/模板**：`stickers.*`、`text_templates.*`、`video_effects.*`、`shapes.*`、
  `manual_deformations.*`、`smart_relights.*`、`smart_crops.*`、`video_trackings.*`、`chromas.*`。
- **AI/云素材元数据**：`videos.aigc_type`、`is_ai_generate_content`、`material_url`、`request_id`、
  `object_locked`、`cartoon_path`、`intensifies_path` 等，不影响几何与样式。

## 维护规则

新增实测字段时：先补 `../evidence/tables/`，再决定归入 A/B/C 哪一档；归入 C 的必须在
`scope-and-phases.md` 里有对应 phase 条目。规格与实测不一致时以实测为准，冲突写进 `conflicts.md`。
本清单每次跑完 `spec_audit.py` 后应更新覆盖率一行的数字。
