# 单例交叉核对：一条成片 vs r3 规格（2026-10-28）

**口径先写清楚**：本文件是 **n=1 的案例观测（case-derived）**，样本是一条已经剪完并导出过的成片草稿，
**不在 r3 语料里**（r3 = 2,050 份去重内容，快照 2026-10-16）。因此：

- 这里的任何数字**不得**写进 `spec/*` 的频次口径，也**不得**与 r3 的计数相加或相减（F-019 的教训）；
- 每条只能记 `single`，它的作用是把「规格怎么说」和「剪映实际写下什么」对一次表，**不构成 verified**；
- 要升 verified 仍需第二路独立证据（另一条草稿 / 安装包内代码 / 成片比对），按 `scope.md` §6.1 的分配原则。

明细表：`tables/case_hf_draft_crosscheck.csv`（12 条）。本文件只写读法与动作。

## 被观测的草稿

| 项 | 值 |
|---|---|
| 草稿 | 恒锋齿条丝锥访谈成片（本机 `<DRAFT_ROOT>` 下，已导出过） |
| 时间线 | 「成片」活动时间线，97.860 s，画幅 9:16（1080×1920），fps 50 |
| 轨道 | 11 条：video 2（104 段 + 20 段画中画）/ adjust 2 / text 5（125 段，可见 76 行）/ audio 2（配乐 2 + 音效 48） |
| 素材 | 文字 76 行（52 行带入场动画）、转场 1、effects 56、`audio_fades` 2、`material_animations` 容器 242 |

选它的理由：它是本机少数**同时**具备字幕动画、转场、配乐淡入淡出、画中画、以及大批量音效的草稿，
一次核对能覆盖规格里 phase-1 与 phase-2 的接缝。

## 对上的（不需要改规格）

| 条 | 规格说法 | 成片实况 |
|---|---|---|
| C-01 | 主轨 = `tracks[0]`，flag ∈ {0, 缺席} | `tracks[0]` 是 video、`flag` 整键缺席 |
| C-02 | 非首条 video 轨必然 `flag==2` | 唯一一条非首条 video 轨（20 段画中画）正是 `flag=2` |
| C-04 | 转场挂**前一个**片段的 `extra_material_refs` | 挂在轨 0 段 8 上，`materials.transitions[]` 只 1 条 |
| C-05 | 转场不改变片段时长 | 下一段起点减本段终点 = 0.000 s，相邻段仍首尾相接 |
| C-12 | `version=360000` + `platform{windows,3704,lv}` | 逐字段一致，`new_version=189.0.0` |

C-05 值得单独说：`picture.yaml` 把 `window_hypothesis`（`[cut−d/2, cut+d/2]` 且不改时长）整体标了 `single`。
这条成片只支持**后半句**——片段没被吃掉 `d/2`；**半窗落在切点哪一侧仍无观测**。所以规格里改成
「不改时长这一半有成片支持，半窗待 M2」，而不是整体升 verified。

## 规格漏记的（已补）

| 条 | 漏了什么 | 补到哪 |
|---|---|---|
| C-06 | `transitions[]` 的 `resource_id` / `path` / `is_overlap` 三键，以及 `duration(待确认)` 与总表「100%（2,343/2,343）」自相矛盾 | `picture.yaml -> transitions`、`format-reference.md` §6 |
| C-07 | `audio_fades` 只有 `fade_in_duration` / `fade_out_duration` 载值，`fade_type` / `in_type` / `out_type` **整键缺席**（不是 null；全 materials 搜不到），且引用挂在**片段**的 `extra_material_refs` 上 | `panel-map.yaml -> 音频.基础` |
| C-08 | 同名 ≠ 同一预设：`渐显` 在 sticker 族（`6724916044072227332`，包内 `Appear.lua`）与 video 族（`6798320778182922760`，包内 `Transform.lua` + `filter.material` + `xshader`）是两个预设 | `animations.yaml -> name_is_not_identity`、`format-reference.md` §7 |
| C-09 | `material_animations` 容器数 ≠ 动画条目数：242 个容器里 188 个没有 `animations[]` | 本文件（仅登记，未改规格） |

C-08 是这次最值钱的一条：`animations_top60.csv` 里同名 `渐显` 本来就占三行（69 / 66 / 51 条），
但规格正文从没立过「必须按 `resource_id` 匹配」的规则，读侧很容易按名字合并。补进规格后，
`jianying-packaging` 的 `validate capabilities` 那条「按 `resource_id` + `md5` 匹配、不按名字」才有据可依。

## 与规格优先级相左的（只登记，未改 phase）

| 条 | 规格 | 成片 |
|---|---|---|
| C-10 | 混合模式列为 phase-1 重点（166 次 / 82 份内容） | 这条成片 `mix_mode` **0 条** |
| C-11 | `figure` 归 phase-3 | `effects` 56 条里 `figure` 15 条、`smart_color_adjust` 22 条 |

这两条**不推翻任何 spec 结论**：r3 的频次是真的，phase 划分只是「先做字幕与画面」的排序选择。
但一个真实成片里两类都没按预期出现，说明**排序依据应该是用户实际会用的层，而不是语料频次**。
真要动 `scope-and-phases.md`，需要的不止这一例——所以这里只登记，不动规格。

## 没有做的事

- 没有在这条草稿上写任何字节（本次核对全程只读，草稿 sha256 未变）；
- 没有把 76 行字幕的排版档位、48 段音效的对齐偏差写进规格：那些是创作决策，不是格式事实；
- 没有把 C-09 的空壳比例写进 `materials.yaml`：单例的 78% 不能当 r3 口径，要等 `corpus_detail` 出桶级统计。
