# FrameDescriptor IR — `jy-preview/framedesc@1`

单位约定：时间一律 **int 微秒**；几何一律 **float CSS px（画布坐标系）**；颜色 `#rrggbb` + 独立 alpha。
Python 算出所有数值，前端只 apply，因此 `/api/frame?t_us=N` 是纯函数，可作回归基线；
`/api/frame?window_us=` 是同一函数的窗口形态（见下），确定性同样成立。

## 顶层

```jsonc
{
  "schema": "jy-preview/framedesc@1",
  "draft":    {"id": "<did>", "name": "…", "path": "D:\\…", "layout": "hybrid"},
  "timeline": {"id": "…", "name": "时间线01", "encoding": "jianying-dll",
               "content_file": "Timelines/<tid>/draft_content.json",
               "source_sha256": "…", "replica_drift": false, "mirror_drift": false},
  "canvas":   {"width": 1080, "height": 1920, "ratio": "9:16", "background": "#000000"},
  "fps": 30.0, "duration_us": 57766666,
  "time":     {"t_us": 1700000, "frame_index": 51, "frame_start_us": 1699998, "frame_dur_us": 33333},
  "layers":   [ … ],              // 后→前有序，renderer 顺序 append
  "audio_labels": [ {"segment_id","track","track_index","volume","muted","fade_in_us","fade_out_us","badges"} ],
  "fonts":    [ {"family","resource_id","title","src","source"} ],   // 供 /api/fonts.css 与"字体回退"统计
  "warnings": [ … ],
  "stats":    {"layers_total","media_missing","fonts":{"exact_path":3,…},
               "labels":{"exact":1,"approx":2,"placeholder":5},"flowers":1}
}
```

## 窗口模式（`?window_us=` / `?from_us=&to_us=`）

点帧 IR 回答"t 这一瞬间屏幕上有什么"，窗口 IR 回答"这一整段里**曾经**出现过的所有图层是什么"。
浏览器播放只吃窗口 IR：一次请求把整段建成图层池，之后片段切换/字幕变化/上层素材滚动都是已存在
DOM 节点上的 CSS 开关，播放期间零请求。

| 项 | 契约 |
|---|---|
| 参数 | `window_us=<长度>`（配合 `t_us=<from>` 当起点）或 `from_us=`+`to_us=`；长度上限 `MAX_WINDOW_US = 120s`，超出按 120s 截断 |
| `window` | `{"from_us","to_us","sample_us"}`，**半开区间** `[from, to)`；`sample_us` 只记录调用方传的 `t_us`（可能落在窗口外），不是每个图层的取样点 |
| 选层规则 | `target_start < to && target_start + target_duration > from` —— 与窗口**相交**即入选，**不做**点帧的 `is_visible` 过滤，也不要求 `t_us` 在该层区间内 |
| `time.local_us` / `progress` / `source_time_us` | 按 `_sample_inside(start, duration, window)` = `clamp(window[0] → [start, end-1])` 取样，保证落在这层自己的区间内；浏览器每帧用 `target_start_us`/`source_start_us`/`speed` 重算，所以这三个值只需**有代表性**，不需精确 |
| `stats.mode` | `"window"`（点帧为 `"point"`），另给 `stats.window_layers` = 入选图层数 |
| 复合片段 | 外层窗口经 `source_timerange`/`speed` 映射成内层窗口后递归；内层子层的 `time` 仍是**内层时间线秒数**，要靠 `nest.scale_to_parent` 与父片段 `target_start_us` 换回外层 |
| 不变式 | 对窗口内**任意** t：点帧 IR 的图层集合 == 窗口池在该 t 可见的图层集合。已用 `python -m jypreview.tools.audit_playback` 在真机播放中逐采样比对（5 份草稿、含跨窗口与复合片段，缺/多/空白均为 0） |

```jsonc
"window": {"from_us": 8000000, "to_us": 28000000, "sample_us": 8000000},
"stats":  {"…": "…", "mode": "window", "window_layers": 25}
```

## layer

| 字段 | 含义 |
|---|---|
| `layer_id` | = `segment.id`，跨帧稳定，是 `ir-diff` 的主键 |
| `kind` | `video` `photo` `text` `sticker` `effect` `filter` `adjust` `subdraft` `audio` |
| `track` | `{id,index,name,type,flag,attribute,render_index,segment_count}` |
| `z` | `{global, tie, source, label, order}`；`source ∈ {segment.render_index, track.render_index, default:video…}` |
| `time` | `{target_start_us,target_duration_us,end_us,local_us,progress,source_start_us,source_time_us,source_duration_us,speed,reverse}` |
| `media` | `{material_id,material_type,material_name,family,path_raw,path,exists,how,recovered,material_duration_us,probe{codec,width,height,duration_us,frame_rate,audio_codec},placeholder_reason}` |
| `rect` | `{cx_px,cy_px,w_px,h_px,rotation_deg,flip_x,flip_y,alpha,scale_x,scale_y,z_px}`（w/h 为**旋转前**尺寸） |
| `css` | `{width,height,transform,transform-origin,opacity}`，前端直接用 |
| `text` | 见下 |
| `labels[]` | `{bucket,kind,name,effect_id,resource_id,render_class,params[],value,bundle,category_name,apply_target_type}` |
| `transition` | `{name,effect_id,resource_id,duration_us,window{start_us,end_us},cut_us,is_overlap,side,render_class,approx{impl},bundle,category_name}` |
| `animation` | `{name,anim_type,effect_id,resource_id,start_us,duration_us,inside,render_class,material_type,approx{impl,from,to},at_t{opacity,scale,translate_offset_px,rotation_deg,blur_px},bundle}` |
| `keyframes` | `[{property,from,to,values,curve,raw,time_offset_us}]`，来自 `segment.common_keyframes` |
| `applies` | `"algorithm"` 表示剪映专有算法（美颜/人脸），不渲染 |
| `canvas_fill` | 背景填充 `{type:"canvas_blur"|"canvas_color",blur,color,ratio}` |
| `nest` | `{depth,embeddable,reason,canvas,scale_to_parent,duration_us,layers[],warnings[]}` |

## text

```jsonc
{"material_id","type":"subtitle|text","text":"…",
 "font":{"family","resource_id","title","src","source"},
 "size":{"font_size","em_px","basis":"width","scale_factor":0.01},
 "box":{"anchor":"center","cx_px","cy_px","rotation_deg","alpha","max_line_px","line_height_px",
        "vertical":false,"alignment":"center","w_px","h_px","em_px","line_count",
        "lines":[{"text","start","end","width_px","spans":[{"i","advance"}]}], "metrics":"font|estimated"},
 "deco":{"background":{...}|null,"has_shadow","global_alpha","letter_spacing_px","line_spacing_raw",
         "alignment","vertical"},
 "runs":[{"start","end","text","size_raw","em_px","bold","italic","underline",
          "fill":{"render_type":"solid|gradient|texture","css","alpha","angle","mode","stops":[{offset,css,alpha}]},
          "strokes":[{"width_em","color","alpha"}],
          "shadows":[{"distance_em","angle_deg","alpha","diffuse","feather","color"}],
          "inner_shadows":[…],"use_letter_color":false,
          "flower":{"resource_id","md5","name","render_class","recipe","bundle"}|null,
          "font":{…}}]}
```

`box.lines` 是 Python 用真实字体度量（Pillow）算好的换行结果，`spans` 给每字符推进量，
所以前端不再测量、换行结果可被 agent 直接断言。

## 解析规则（谁算什么）

| 主题 | 规则 |
|---|---|
| 可视性 | `0 ≤ t − target_start < target_duration`；`visible:false` 排除 |
| 同轨重叠 | 不假设互斥，各出一层再按 z 排序 |
| speed | 以 segment 为准：`source_time = source_start + local×speed`；`reverse` 同函数内处理 |
| 转场 | 挂在**前一个** segment 的 `extra_material_refs`；窗口 `[cut−d/2, cut+d/2]`（target 时间）；**绝不改 `duration_us` 或片段区间** |
| 全局 z | `seg.render_index ?? track.render_index ?? DEFAULT_RI[type]` 升序；`DEFAULT_RI = {video:0,audio:0,effect:10000,filter:11000,sticker/adjust:12000,text:14000}` |
| transform | `cx = W/2 + x·W/2`，`cy = H/2 − y·H/2` |
| 绘制尺寸 | `contain(media → canvas)`（旋转前）× `clip.scale`，再旋转、再平移 |
| 文字尺寸 | `em_px = font_size × W/100`（`Config.text_size_basis/scale_factor` 可调） |
| 描边/阴影 | em 相对；阴影 `distance/100 × em`，`angle` 度 → dx/dy（CSS y 向下取反） |
| 花字 | `styles[].effectStyle` → `Cache/artistEffect/<rid>/<md5>/effectStyle.json`，与内联样式同构 |
| `materials.drafts` | 递归（内嵌完整 draft），`max_nest_depth=2`，按子画布比例缩放 |
| `responsive_layout` | 语料内全 `enable:false` → 忽略 |
| `keyframes{}` / `keyframe_graph_list` | 语料内为空 → 不支持 |
