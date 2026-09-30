# 实测草稿 JSON 字段与坑

以本机 645 个草稿目录（639 份 content：316 加密 / 323 明文）实测为准。
**与 `jianying-editor-skill/references/*` 或 `jianying-draft-batch-edit/references/material-structures.md`
冲突时，以本文件（即以真实草稿）为准。**

## 布局

| 布局 | 判据 | 注意 |
|---|---|---|
| `legacy-single` | 只有根 `draft_content.json` | 时间线 id 取内容里的 `id`，可能为空 → 别名 `legacy-root` |
| `multi-timeline` | `Timelines/project.json` + `Timelines/<tid>/draft_content.json` | |
| `hybrid` | 上两者 + 根文件 | **根 `draft_content.json` 是镜像**，可能陈旧：`draft-mirror-drift` 根文件字节等于 `<timeline id 甲>` 而 `timeline_layout.json:activeTimeline` 是 `<timeline id 乙>` |

active 判定顺序（与 editor skill 的 `active_evidence()` 一致）：
`timeline_layout.json:activeTimeline` → 根内容 `id` → `project.json:main_timeline_id` → 唯一未删除时间线。
全部落空时**必须返回 None**，让调用方显式选时间线（`selfcheck` 用 `~/.jypreview/fixtures/ambiguous-draft` 这个合成草稿验证）。

不可当内容解析的运行时产物：`deepagent/`、`agent_adoption_ledger.db`、`subdraft/`、
`crypto_key_store.dat`、`Resources/`、`matting/`、`smart_crop/`、`qr_upload/`、`.backup/`、
`attachment_pc_common.json`、`draft.extra`。语料根目录要跳过 `.recycle_bin`、`.workbuddy`、
`.cloud_cache_*`、`__pycache__`、`.jypreview`。

## 时间

微秒。剪映会按帧量化边界（计划 `0.767s` 存成 `766667`），所以按 µs 精确匹配会失败，
editor skill 默认 ±40ms 容差。`target_timerange` 可能**省略 `start`**（等价 0）。
`fps` 在剪映自己生成的加密草稿里**经常缺失** → 默认 30 并写进 `warnings`。

## tracks / segments

- `tracks[]` 常见键：`id,type,name,segments`，另有 `render_index?`、`attribute`(静音位)、`flag`、`is_locked`、`muted`、`group_setting`、`segment_inputs`。
- 轨道类型实测：`text 426, audio 379, video 378, sticker 31, effect 20, filter 12, adjust 10`。
- 片段常见键（该草稿 实测）：
  `id, material_id, target_timerange, source_timerange, clip, uniform_scale, extra_material_refs,
   render_index?, track_render_index?, volume?, speed?, visible?, reverse, responsive_layout,
   render_timerange, hdr_settings, enable_*, keyframe_refs, cartoon, caption_info, group_id,
   template_id, template_scene, is_placeholder, intensifies_audio, last_nonzero_volume`
- `clip = {scale{x,y}, transform{x,y[,z]}, rotation, alpha, flip{horizontal,vertical}}`；
  `flip` 常是空对象 `{}`，`transform` 常缺 `z`，`uniform_scale` 常是 `{}`（不是 `{on:true}`）。
- **`visible: false` 很常见**（模板留下的隐藏文本），必须排除，否则会画出重复字幕。
- `speed` 以 segment 为准；`materials.speeds[]` 在本语料里只有 `{id,type:"speed"}`（**没有数值**），别去那里取。
- `volume` 是 float（可到 ~6），不是对象。
- `common_keyframes` 有数据（本语料 23 条：`KFTypePositionX/Y`、`KFTypeRotation`、`KFTypeScaleX`），
  但 `materials.keyframes.*` 与 `keyframe_graph_list` 全为空。

## materials.texts（最关键）

外层是 ~70 个扁平字段 + `content`（**JSON 字符串**）。真实形状：

```jsonc
{"id","type":"subtitle|text","content":"{\"text\":\"…\",\"styles\":[…]}"}
```

`styles[i]`：`range` 是 **`[start,end]` 字符下标数组**（`material-structures.md` 写的 `{start,end}` 字典形式只在旧数据出现，两种都要吃）；
`size` 是剪映 UI 字号（如 8、15、22.907）；`fill.content.{render_type,solid|gradient|texture}`；
`strokes[]`/`shadows[]` 是**复数数组**；`effectStyle={id,path}`；`font={id,path}`。

- 颜色是 `[r,g,b]` **0..1 浮点**，不是 0..255。
- 描边 `width` 与阴影 `distance` 是 **em 相对**；阴影 `distance` 还要再 `/100`（`distance:5` + `em:86` ≈ 4.3px 位移）。
- 外层扁平字段（`text_color:"#FFFFFF"`、`font_size`、`border_width`、`border_color`、
  `has_shadow`、`shadow_{angle,distance,color,alpha,smoothing,point}`、`background_*`、
  `font_resource_id`、`font_path`、`font_title`、`line_spacing`、`line_max_width`、`check_flag`、
  `words`（卡拉OK逐字时间））只在 `styles[]` 缺项时兜底。
- `line_spacing` 是小数（默认 `0.02`），不是整数 UI 值 → 行高 `em × (1 + line_spacing)`。
- `check_flag` 位标：基 `7`，`+8` 描边、`+16` 背景、`+32` 阴影、`+4` 混合、`+64` 发光。
- `font_title` 在部分草稿里是乱码（剪映自己写坏的），显示名要靠对照表。

## 特效/转场/动画

| 桶 | 形状 | 备注 |
|---|---|---|
| `transitions[]` | `{id,name,effect_id(短),resource_id(19位),duration,is_overlap,path,category_id,category_name,request_id}` | 挂前一片段；实测相邻片段 `gap=0`，转场**不缩短**时间线 |
| `video_effects[]` | `{name,effect_id,resource_id,type:"video_effect|face_effect",apply_target_type:2,value,adjust_params[{name:"effects_adjust_*",default_value,value}],path}` | |
| `effects[]` | 混合桶：`figure`(美颜,无 id 只有 path)、`text_effect`(**花字在这**)、`filter`、`lut`(有真 `.cube` 路径)、`brightness/contrast/…` | `flowers[]` 在本语料**恒为空** |
| `material_animations[]` | 容器 `{id,type:"video_animation|sticker_animation",animations:[{id(短码!),name,resource_id,duration,start,type:"in|out|loop",category_id:"ruchang",path,anim_adjust_params:null}]}` | 靠 `segment.extra_material_refs → 容器.id` 关联；**动画短码存在 `id` 而不是 `effect_id`** |
| `stickers[]` | `{name,resource_id,path,icon_url,preview_cover_url}` | 唯一带 CDN URL 的桶，签名 URL 会过期 |
| `text_templates[]` | `{name,effect_id,resource_id,path,resources:[{panel:"flower|fonts|sticker|text",resource_id,path}],text_info_resources,non_text_info_resources}` | 桶内自带 rid→路径映射 |

`path` 规范化模板：

```
…/User Data/Cache/effect/<短effect_id>/<md5>[/字体文件名]     转场/动画/画面特效/字体
…/User Data/Cache/artistEffect/<19位rid>/<md5>                花字/滤镜/贴纸/文字模板
…/User Data/Cache/music/<md5>.mp3                             音频
…/User Data/Resources/Lut/<Name>/<Name>.cube                  LUT
##_draftpath_placeholder_<guid>_##/…                          算法产物/子草稿（需按草稿根解析）
```

`Cache/effect` 目录**同时按 effect_id 和 resource_id 建**，所以字体精确路径只命中 ~39%，
补上按两种 id 找 + basename 兜底后接近 100%（残余是系统默认 `zh-hans.ttf`）。

## 素材路径恢复阶梯

1. 原样 `Path(raw).is_file()`
2. `##_draftpath_placeholder_<guid>_##/rest` → `<draft>/rest`
3. 相对路径 → `<draft>/<rel>`、`<draft>/materials/<name>`、`<draft>/media/<name>`
4. `X:/JianyingPro Materials/…` → `X:/JianyingPro/JianyingPro Materials/…`
5. 草稿目录内按 basename 递归找一次（带缓存）
6. 失败 → `exists:false` + 占位瓦片（**老草稿大量命中这条**：323 份明文草稿的 2,505 个 `videos[].path` 只有 84 个还在）

## 其他

- `canvas_config` 只有 `{width,height,ratio}`；背景色/模糊在 `materials.canvases[]`（每个视频一条）。
- `render_index_track_mode_on:true` 时按全局 `render_index` 排序，否则先按轨道顺序。
- `key_value.json`（草稿根）是 UUID → `{materialName, materialCategory, is_vip, searchKeyword}` 的**每草稿一份**小字典，适合做查表兜底。
- 音频 `audios[]` 里 `tone_speaker`、`wave_points:[]`；`audio_fades[]` 的淡入淡出是 µs。
