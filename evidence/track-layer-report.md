# 时间线与轨道层完整报告

日期：2026-10-20 ｜ 里程碑：M1（轨道层收尾）｜ 证据条目：F-047、F-048 ｜ 开放项：U-60…U-63
权威落点：`spec/picture.yaml`（轨道/片段/层级）、`spec/text.yaml`、`spec/materials.yaml`、`spec/layout.yaml`；
派生表：`evidence/tables/{track_types,segment_shapes,track_material_map,material_type_enums,render_index_bands_by_type}.csv`；
生成器：`../scripts/track_matrix.py`（根仓库）。

**计数口径（全文统一）**：按 **去重内容** n=2,050（r3 冻结，快照 2026-10-16）里的**轨道条数 / 片段条数 / 素材条目数**计，
不是「多少份内容带该键」。只读 `temp/corpus-scan/manifest.json` 列出的 content key，
`plain/` 目录里多出的 **28 份历史残留**（F-030）自动排除；本轮共 9,990 条轨道、51,718 个顶层片段。

---

## 0. 方法与工具通道

| 通道 | 内容 | 结论可用性 |
|---|---|---|
| 自研全量重跑（第二遍独立测量） | `scripts/track_matrix.py` 读冻结明文 | 本报告全部数字的出处 |
| 剪映自己的草稿层（安装包内，只读） | `<JY_INSTALL>\11.6.0.14552\Resources\canvas_agent`：协议 `xmldraft/v1`（SKILL+10 references 132,883 B、146 个属性名）+ `runtime/app-server.mjs`（9,206,933 B，含 `wl0()` 草稿构造器、`gh1` 平台常量、草稿文件清单常量） | 第二方见证：主轨、单位分层、`ratio=original`、`sound_channel_mappings.type=none`、`platform` 八字段 |
| REA（`rea-agents@6.5.0`，白名单内） | `analyze-javascript-application` | **只能给清单/模块图**：默认 1 GB worker heap 在 9.2 MB bundle 上堆耗尽；`--max-heap-mb 6144` 解析完（2,163,421 AST 节点、4,391 边）但语义关系被父进程结果预算丢掉（relations=0）；本机无 native provider |
| `videoeditor.dll` | 未逆向（本机无 Ghidra/JDK/objdump/rizin，且不打算装） | `xmldraft → draft JSON` 的映射读不到；本项目不经 XML 层，故不构成缺口 |

---

## 1. 时间线在容器里的位置（与轨道有关的部分）

- 多时间线索引：`<draft>/Timelines/project.json`（明文），活动时间线取 `main_timeline_id` 且 `is_marked_delete == false`；
  每条时间线的草稿在 `Timelines/<timeline_id>/draft_content.json`，hybrid 草稿另外在根目录留一份**根镜像**（写非活动时间线不刷新它）。
- 剪映自己认定的草稿 JSON 标准成员是 5 个（内置 agent 常量）：`draft_info / draft_meta_info / draft_content / **draft_virtual_store** / draft_agency_config`。
  `draft_virtual_store.json` 存在于 **1,184/1,475** 个草稿目录，内容形如 `{draft_materials:[], draft_virtual_store:[{type, value:[{child_id, parent_id, sort_type, filter_type, import_time_us,…}]}]}`
  ⇒ 它是 `subdraft/`（226 个草稿有）的**父子索引**，复合片段/嵌套草稿必须靠它，此前规格漏记（F-047）。
- **主轨判据 = 位置**：含 video 轨的草稿里 **370/370** 都是 `tracks[0].type == "video"`；内置 agent 也断言 `tracks[0]` 是视频主轨（取不到即抛「成片草稿缺少视频主轨」）。
  `flag` 已被排除为主轨标记（唯一 `flag==2` 落在首条 video 轨的比例 **0/206**）。协议侧把主轨列为一等公民：唯一 `main` 容器、只承载 video/image、按文档顺序连续，往主轨开头插入会把副轨片段整体后移。

---

## 2. 轨道层：八种类型与各自的键

八类轨道共 9,990 条。**每条轨道必有 `id` 与 `type`**；`segments` 有 9,962 条（缺席 28 = video 25 + mixed 3，即「有轨道壳但没写片段数组」）。

| track.type | 轨道 | 片段 | `name` | `attribute` | `flag` | `is_default_name` true/false |
|---|---|---|---|---|---|---|
| video | 3,195 | 15,081 | 1,158 | 1,257 | 2,237 | 3,156 / 5 |
| audio | 2,582 | 12,742 | 866 | 867 | 860 | 2,577 / 0 |
| text | 2,439 | 19,978 | 963 | 947 | 1,612 | 2,422 / 3 |
| mixed | 825 | 2,390 | **0** | 16 | 510 | 796 / 0 |
| effect | 410 | 545 | 143 | 144 | 143 | 410 / 0 |
| sticker | 277 | 398 | 140 | 140 | 140 | 275 / 2 |
| adjust | 194 | 473 | 44 | 44 | 44 | 194 / 0 |
| filter | 68 | 111 | 51 | 51 | 51 | 68 / 0 |
| 合计 | 9,990 | 51,718 | 3,365 | 3,466 | 5,597 | **9,898 / 10**（缺席 82） |

值域（首次实测，此前规格只列键名）：

- `flag`：video `2:1,662 / 缺席 958 / 0:575`；text `1:1,004 / 缺席 827 / 0:606 / 3:2`；audio **只有** 缺席 1,722 / 0:860；
  mixed `2:510 / 缺席 315`；effect 缺席 267 / 0:143；sticker 0:140 / 缺席 137；adjust 缺席 150 / 0:44；filter 0:51 / 缺席 17。
  ⇒ `2` 只出现在 video 与 mixed，`1` 只在 text，其余类型从不写非零值。语义 **U-61**。
- `attribute`：0:3,231 / 1:170 / 2:38 / 4:10 / 6:8 / 3:4 / 16:2 / 8:2 / **17:1**（旧行漏 17）。语义 **U-37**。
- `is_default_name`：true 9,898 / false 10（video 5、text 3、sticker 2）/ 缺席 82。
- `name`：**mixed 从不写** ⇒ 任何判据不能依赖 mixed 的 `name`。

---

## 3. 轨道类型 ↔ 素材类型（本次最大的补漏）

**片段自身没有 `type` 键**（51,718 个片段全测恒缺）。真正的语义类型有两处载体：`track.type`（容器种类）与 **`material_id` 指向的 bucket 的 `type`**。后者此前规格完全没记。

`track.type → material_id` 实测落点（按片段计）：

| track.type | 落到的 bucket.type | 片段数 |
|---|---|---|
| video | `videos.video` / `videos.photo` / `videos.image` | 13,893 / **1,186** / 2 |
| audio | `audios.sound` / `video_original_sound` / `music` / `text_to_audio` / `extract_music` | 7,069 / 3,062 / 1,302 / 1,143 / 166 |
| text | `texts.subtitle` / `texts.text` / `texts.lyrics`；`text_templates.text_template` / `_subtitle` / `_lyrics` | 17,016 / 2,077 / 50；804 / 30 / 1 |
| sticker | `stickers.sticker`；`shapes.shape` | 377；21 |
| effect | `video_effects.video_effect` / `face_effect` | 466 / 79 |
| filter | `effects.filter` | 111 |
| adjust | `placeholders.adjust` | 473 |
| **mixed** | `videos.video` 1,511、`videos.photo` 44、`texts.subtitle` 564、`texts.text` 233、`video_effects` 26、`placeholders.adjust` 10、`text_templates` 1 | 合计 2,390 |

要点：

1. **图片不另设 bucket**：`videos[].type == "photo"`（1,230 条素材），轨道仍是 video。含嵌套口径里另见过 `image`、`gif` 各 1。
2. **字幕 / 普通文字 / 歌词的判别字段是 `texts[].type`**（subtitle 17,718 / text 3,307 / lyrics 60 / none 1）。
   同一条 text 轨可混三种；**字幕也可以不在 text 轨上**（mixed 指 subtitle 564 次）⇒ 渲染器不能按 `track.type` 分派。
3. **复合片段有两种**：`materials.drafts[].type` = `combination` 4,657 / `composition` 439（条目口径）。递归展开前要看这一位。
4. **名字会骗人**：`material_animations[].type` **恒为 `sticker_animation`（34,828 条无一例外）**，真正的动画分类在 `material_animations[].animations[].type` = in 8,388 / loop 1,587 / out 303 / caption 158 / group 129。
5. 其余枚举：`canvases.type` = canvas_color 14,879 / canvas_blur 1,620 / canvas_image 33 / none 9；
   `sound_channel_mappings.type` = none 26,011 / 空串 3,272（内置 agent 造草稿时直接把全部 mapping 写成 none，两方同向）；
   `placeholder_infos.type` = placeholder_info 24,068 / none 20；`common_mask.type` = mask 321 / none 68 / 空串 2；
   `speeds.type` = speed 29,376；`transitions.type` = transition 2,347；`stickers.type` = sticker 377；`beats.type` = beats 12,927；
   `vocal_separations.type` = vocal_separation 29,283；`vocal_beautifys.type` = vocal_beautify 1,561；`realtime_denoises.type` = realtime_denoise 3,285；
   `audio_fades.type` = audio_fade 1,972；`audio_effects.type` = audio_effect 115；`audio_pannings.type` = audio_panning 4；
   `video_trackings.type` = video_tracking 91；`video_radius.type` = round_radius 28；`smart_relights.type` = smart_relight 52；
   `manual_deformations.type` = manual_deformation 5；`chromas.type` = chroma 29；`masks.type` = mask 46；`shapes.type` = shape 21；
   `color_curves.type` = color_curves 335；`hsl.type` = hsl 10,910；`log_color_wheels.type` = log_color_wheels 33；
   `primary_color_wheels.type` = primary_color_wheels 4；`hsl_curves.type` = none 2 / 空串 1；`smart_crops.type` = smart_crop 3；
   `video_shadows.type` = video_shadow 2；`video_strokes.type` = video_stroke 2；`placeholders.type` = adjust 483；
   `effects.type` 33 种（其中 6 种单样本，U-40），`audio_pitch_shifts` 无 `type` 枚举记录。
   全表见 `tables/material_type_enums.csv`（91 行）。

---

## 4. 片段层：形状不由轨道类型决定

**这是规格此前完全没有的维度。** 同一类型轨道里并存「最小形」与「完整形」：

- 全语料**只存在一种 45 键的完整形**（逐类型比对无任何第二种 45 键变体），共 **6,004 个片段**带它：
  audio 2,244 / text 2,237 / video 1,233 / effect 109 / adjust 78 / sticker 58 / filter 45。
  它比常见形多出 `caption_info, color_correct_alg_result, desc, digital_human_template_group_id, is_loop, lyric_keyframes, raw_segment_id, state` 与一批 `enable_*`。
- 另有一种 **34 键形**（缺上面那批音频/歌词族与占位键）在 video/effect/sticker/filter/text 的主干上；33 键形是 video 的最常见形（10.1%）。
- 每类的**键集种数**：video **524**、mixed 104、text 32、audio 31、adjust 26、sticker 20、effect 13、filter 10。
- 每类 top 形状（占比，条数）：
  video 33 键 10.1% (1,520) / 13 键 9.9% (1,486) / 34 键 8.6% (1,290) / 45 键 8.2% (1,233)；
  audio 13 键 43.1% (5,489) / 14 键 20.8% (2,649) / 45 键 17.6% (2,244)；
  text 15 键 34.7% (6,940) / 14 键 19.1% (3,825) / 45 键 11.2% (2,237)；
  mixed 15 键 30.5% (729) / 13 键 10.0% (239)；effect 12 键 46.6% (254) / 45 键 20.0% (109)；
  sticker 34 键 25.4% (101) / 45 键 14.6% (58)；adjust 8 键 18.4% (87) / 9 键 16.7% (79) / 45 键 16.5% (78)；
  **filter 以完整形为主**：45 键 40.5% (45/111)。
- 各类型自己的最小形（高频）：audio 13 键（enable_*/id/material_id/两个 timerange/render_timerange/responsive_layout/source/track_render_index 等）、
  adjust 8 键（只有 extra_material_refs/id/material_id/render_timerange/responsive_layout/source/target_timerange/track_render_index）、effect 12 键。
- 全表见 `tables/segment_shapes.csv`（48 行，含每种键集成员）。

**规约影响（硬）**：解析必须按「键是否存在 + `field_states` 四态」写，不能按「轨道类型 → 固定字段表」写；
写回时**不得**因为片段是 audio 就补出 video 侧的键，也不得因为片段是 45 键形就假定 34 键形「缺了 11 个键」需要补齐。

---

## 5. 时间与层级

- **单位 = 微秒**（verified，F-005）。内置协议文档独立印证分层：`xmldraft/v1` 明文写「所有时间属性只接受不带单位后缀的裸数字，统一按毫秒解释，`us/ms/s/min/m` 后缀均非法」，
  即 XML 层用毫秒、JSON 层用微秒，两层相差 1000 倍；本项目直接读写 JSON，不涉及该换算。
- `target_duration == source_duration / speed`（verified，复现 990000 / 0.9 = 1100000）；`materials.speeds[].speed` 是 `segment.speed` 的**忠实镜像**（11,680/11,680 无例外，C-011）。
- `timerange.start` 在 51,718 个片段里缺席 4,284（8.3%）⇒ 读作 0，写回**不得**补回该键。
- `render_timerange` present 40,934：`{}` 34,925 / 缺席 10,784 / **两键有值 6,009**（真有内容，不能当占位忽略）。
- **层级不由数组顺序决定**：`track_render_index` 在轨道内恒定（8,584 恒定 / 1 变化）→ 轨道间次序；`render_index` → 同带内片段次序。
  归一化数组位置均值 video 0.266 → adjust 0.346 → effect/mixed 0.406 → filter 0.432 → sticker 0.448 → text 0.468 → audio 0.863；
  但「text 先于 video」占 27.7% ⇒ 数组顺序只是相关。轨道内 `render_index` 单调 2,070 / 不单调 589。**升序靠上还是靠下仍未定（U-15）**。
- 逐类型 × 逐带实测（本轮新测，`tables/render_index_bands_by_type.csv`）：

| track.type | 0-999 | 1000-9999 | 10000-10999 | 11000-13999 | 14000-14999 | 15000-15999 | 16000-18999 | 19000+ | 带内合计 |
|---|---|---|---|---|---|---|---|---|---|
| video | 7,288 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 7,303 |
| audio | 3,920 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3,920 |
| text | 0 | 1 | 0 | 0 | 19,467 | **254** | **29** | **207** | 19,958 |
| mixed | **257** | 0 | 1 | 26 | 757 | 0 | 0 | 0 | 1,041 |
| effect | 3 | 0 | 0 | 542 | 0 | 0 | 0 | 0 | 545 |
| sticker | 0 | 0 | 0 | 0 | 392 | 6 | 0 | 0 | 398 |
| adjust | 290 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 290 |
| filter | 0 | 0 | 106 | 0 | 0 | 0 | 0 | 0 | 106 |

  主带仍是「元素类别」带（0 画面 / 10000 滤镜 / 11000 特效 / 14000 文字贴纸），两处旧说法被更正：
  ① `mixed` 不是 14000 带专属，它跨四个带；② 主带之外还有 15000-15999 / 16000-18999 / 19000+ 三个次带（496 段，全在 text 与 sticker，值高度聚集，像按序号分配）。

---

## 6. 与既有报告的对账

**逐位复现（说明 r3 的轨道层统计不是单遍采样误差）**：八类轨道条数 3,195/2,582/2,439/825/410/277/194/68 ✓；
顶层片段 51,718 ✓；带 `clip` 42,135、`clip` 整值 null 4,325 ✓；`track.attribute` 直方图 ✓；`track_render_index` 8,584/1 ✓；
text 14000 带 19,467 ✓；音频/歌词族键各 6,178 ✓；逐类型引用桶（video→effects 66,237、audio→beats 12,714、mixed→material_animations 1,916…）与 `coverage.md` 逐项相同 ✓；
`material_id` 悬挂引用 **0** 处（规格记的 10 处悬挂在 `extra_material_refs`，两者不同层次）✓。

**补漏（此前根本没测的维度）**：bucket 的 `type` 枚举（§3）、片段键集形状双态（§4）、`render_index` 次带与 mixed 跨带（§5）、
轨道级值域 `is_default_name` / `name` / `flag`（§2）、`draft_virtual_store.json` 与主轨判据（§1，F-047）。

**就地更正的旧错误 4 处**：

| 位置 | 旧 | 新 | 性质 |
|---|---|---|---|
| `picture.yaml` clip 行 | 42,215 / segment 总数 51,784 | **42,135 / 51,718** | 笔误/口径，与 `text.yaml`、`format-reference.md` 自相矛盾 |
| `picture.yaml` keyframes 行 | 带 `common_keyframes` 的 segment 17,408 | **17,411**，并补「非空仅 836」 | `keyframes.yaml` 一直是对的 |
| `picture.yaml` `curve_fields` | 仍标 `open U-14` | 指向 `keyframes.yaml`（U-14 已结案） | 文件没跟上结案 |
| `materials.yaml` `audios` | 「material type 值为 music 而非 audio（single）」 | 五种取值，music 仅 1,302，最多是 sound/video_original_sound；`audio` 是轨道类型名 | **单样本外推**；`stats.json -> bucket_enum_values` 早就有全枚举 |

第 4 条的纪律已写进 `spec/00-overview.md`：**枚举字段登记前必须查 `bucket_enum_values`，不许由单样本外推**。

---

## 7. 对 M2 / M3 的硬约束

1. 渲染器与写回**不能按 `track.type` 分派字段表或语义类型**；语义看 `material_id` 指向的 bucket 及其 `type`。
2. 片段读法只看「键在否 + 四态」；写回不得补齐「本类型通常有而本片段没有」的键（45 键形与 13 键形都是合法状态）。
3. `mixed` 未定性之前，任何「按类型建分支」的架构都会在这 825 条轨道上失败（U-62）。
4. 绘制次序 = `track_render_index`（轨道间）+ `render_index`（带内），方向仍未定（U-15），次带语义未定（U-63）。
5. 写回的版本/身份 stamp 有两套（桌面 `version=360000` + `platform{windows,3704,lv}`；内置 agent `400000` + `{web,348188,"15.4.0"}`），未判前默认不动 `platform`（U-60）。
6. 复合片段展开要同时读 `materials.drafts[]`（区分 combination/composition）与 `<draft>/draft_virtual_store.json` 的父子索引；`subdraft/` 目录仍属绝不写入路径。

## 8. 复现

```bash
python scripts/track_matrix.py --json-out temp/track-probe/matrix.json   # 重生成 5 张表（只读）
python scripts/check_spec_yaml.py && python scripts/check_doc_counts.py  # 两道门
```
