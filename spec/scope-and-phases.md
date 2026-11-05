# 阶段划分（phase 1 = 字幕 + 画面，调色跳过）

判据来自 2050 份去重内容的实测频次（`../evidence/tables/`，r3 快照 2026-10-16，口径见 F-019、批次见 F-020）与「用户要求前期只解决字幕与画面处理（调色跳过）」。

## phase 1 —— 字幕 + 画面（本项目近期目标）

必须渲染正确：

- 轨道与片段：`tracks[]` / `segments[]` 的 `target_timerange`、`source_timerange`、`material_id`、`extra_material_refs`
- 画面几何：`clip{transform{x,y}, scale{x,y}, rotation, alpha, flip}`、`crop`（四角点）、画幅 `canvas_config{width,height,ratio}` 与 `canvases`（背景模糊/颜色/图）
- 时间：`segment.speed`（`target = source / speed`）
- 不透明度与**混合模式**：`effects[type=mix_mode]`（去重内容里 166 次 / 82 份内容）→ 10 个 `*BlendPreMul` GLSL 函数（`../evidence/tables/mixmode_glsl.csv`）
- 蒙版：`common_mask`（196 份内容 / 390 条目）+ `masks`（21 份内容 / 46 条目），含 `invert`/`feather`/`roundCorner`/`aspectRatio`/`contour_path`
- 转场：`transitions`（703 份内容 / 2184 种具名转场）
- 关键帧（画面侧）：`KFTypePositionX/Y`、`KFTypeScaleX/Y`、`KFTypeRotation`、`KFTypeGlobalAlpha`、`KFTypeAlpha`、蒙版系列
- 字幕：`texts.content`（JSON 字符串）→ `styles[]{range,size,font,fill,strokes,shadows,effectStyle,bold,italic,underline,useLetterColor}`、扁平回退字段、`background_*`、`check_flag`
- 字幕动画：`material_animations` 的 `in/out/loop`；优先做 `../evidence/findings.md` F-012 列出的 top 预设（r2 去重内容口径、按频次排序：向上弹入 717、日出 443、左移弹动 246、弹簧 229、弹入 227、收拢 225、波浪弹入 220、缩小 II 182、颤抖 III 148、左上弹入 141、向上翻转 140）
- 合成顺序：`track_render_index`（轨道级）+ `render_index`（分带）+ `render_index_track_mode_on`（97% 为 true）
- 复合片段：`materials.drafts[]`（1260 份去重内容含）递归展开

phase 1 的显式近似（允许降级但需标注）：

- 缺失预设包时按名称关键词近似动画
- `useLetterColor`（逐字配色：r3 有 10,637 个 styles 条目带该键，且**带键即 true**）先支持整体色，逐字色随后
- 转场效果先做窗口与方向正确性，逐种转场内核按 top 频次补

## skip —— 调色（**除 `brightness` 外仍按用户要求跳过**）

**2026-11-05 变更**：`effects.type == brightness` 从「只记录不渲染」变成**已实现并被成片验**——
律逐字取自装机包内明文 GLSL `AmazingFeature_adjustColor/xshader/colorAdjust.frag`，参数就是草稿里的原值；
两条通路**同批**作用（通道 2 `render_frame.apply_color_adjust` ＋ 页内 `COLOR` 走普通
`Filter`+`GlProgram`，P-133；`BlendModeFilter` 那条槽不执行，见 F-094 更正），
负样本是 `COLOR` 关掉 / `&color=0`——关掉要逐位回到改前（P-132 验的就是这个）。
整轴实测 `<0.90` 的点 13/37 → 7/37、
`|1−亮度比|` 中位 0.024 → 0.013（读数见 evidence/playback-log.md P-130/P-131，
出处 `temp/playback-test/luma-scan*.json`）。
**其余调色项仍 skip**：它们的滑杆→uniform 映射**还没有被成片验过**
（contrast 的 `pivot/xFactor`、black→`slope/bias`、`clear`/`light_sensation` 需要 17³ LUT，
`fade_max.texture`、`lightSensation_min/max.png` 在包里是**有**的，但取用与求值都没验）。

只记录、不渲染，且不得在写回时破坏：
`material_colors`（2670 份）、`hsl`（1970）、`color_curves`（240）、`log_color_wheels`（20）、
`primary_color_wheels`（6）、`hsl_curves`（2）、`effects.type ∈ {brightness, contrast, saturation, temperature,
sharpen, clear, shadow, highlight, light_sensation, black, white, color_correct, tone, natural_saturation, lut,
smart_color_adjust, vignetting}`、`segment.enable_lut / enable_adjust / enable_hsl` 开关、`KFType{Brightness,Contrast,Hue,Filter,ColorMatch,SmartColorAdjust,ChromaIntensity,LightSensatione,Sharpen}`。
`video_radius`（圆角，6 份）暂归 skip，待确认它属画面几何还是调色。

## phase 2 —— 音频

`audios`（2706）、`audio_fades`（1932）、`loudnesses`（1688）、`realtime_denoises`（742）、
`sound_channel_mappings`（3940）、`vocal_separations`（3940）、`beats`（2686）、`vocal_beautifys`（292）、
`audio_effects`（52）、`audio_pitch_shifts`（2）、`KFTypeVolume/LastVolume`。
注：音频 material 的 `type` 值为 `music`（不是 `audio`）——写回时必须遵守（`write-rules.md`）。

## phase 3 —— 特效 / 贴纸 / 其它画面能力

`effects.type ∈ {figure, text_effect, makeup_root, …}`（figure 高达 36,599 次）、`video_effects`（365 份内容）、
`stickers`（382）、`text_templates`（450）、`shapes`（22）、`chromas`（28）、`video_trackings`（42）、
`manual_deformations`（10）、`smart_relights`（10）、`smart_crops`（4）、`placeholder_infos`（3046，语义未定）。
`KFType{TextColor,BorderAlpha,BackgroundAlpha,ShadowAlpha,Fade}` 与 `effects_adjust_*` 系列。

## 每阶段验收口径

| 阶段 | 验收 |
|---|---|
| phase 1 | 选定草稿的**字幕与画面**与剪映成片逐帧比对：位置/缩放/旋转误差 ≤ 标定阈值，字幕字高与描边宽度经 U-07 标定后误差 ≤ 2%，混合模式与 `BlendPreMul` 参考实现数值一致，蒙版边缘羽化方向正确 |
| skip（调色） | 不渲染即不引入色差：跳过调色字段时成片比对需在**未使用调色**的草稿上做，或比对时显式关闭调色。
**2026-11-05 补**：`brightness` 实现之后，这句话对**其余**调色项依然成立——这条草稿剩余 7/37 个点
仍 `<0.90`，且全落在只有 `contrast/clear/shadow/black/light_sensation` 的段上。
**`corr()` 类判据看不见乘性偏差**（P-129：暗 36 % 的帧相关度仍读 0.94），
所以比对口径必须带**亮度比**这一列（`browser_shot_check.py` 现在每时刻都报） |
| phase 2 | 波形/音量/淡入淡出与剪映导出音频一致（相关性阈值另定） |
| phase 3 | 每个新支持的预设/特效类别都需一条 E→F→P 证据与一条成片比对 |
