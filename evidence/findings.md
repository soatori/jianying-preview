# 发现日志（Evidence → Finding → Path）

证据等级：**已验证** = ≥2 路独立证据；**单源待验证** = 仅一路；**未解决** = 见 `unresolved.md`。
本文件只记事实与出处，不记实现细节。原始数据在 `temp/`（不入库），派生表见 `docs/evidence/tables/`。

---

## F-001 路由选择（reverse-skill，只读）

- **Evidence**：读 `temp/vendor/reverse-skill/skills/MASTER-ROUTING.md`（140 行）与 `skills/js-reverse/SKILL.md`（215 行）、其 `AGENTS.md`。
- **Finding**：`js-reverse` 明确把「二进制 / PE / DLL」目标转交给 `ida-reverse`/`radare2`/`reverse-engineering`，且默认绑定浏览器侧 MCP（`js-reverse_*`、jshookmcp）。我们的目标是本地 JS 包 + 只调用 DLL，故 PRIMARY 取 **R0 `reverse-engineering/`（triage→static→synthesis）**，只借它的 Observe-first / Evidence-first 与证据链纪律。
- **Path**：**未执行该仓库任何脚本**（其 `AGENTS.md` 规定读文件不等于授权执行、首次副作用前列出命令与写入项）。选路由读表完成，零副作用。

## F-002 REA 的能力边界：应用图 ≠ 字段清点

- **Evidence**：`npx -y rea-agents@6.5.0 analyze-javascript-application "...\Resources\models\SegmentJS" --json` → 93,282,810 B 证据（`temp/rea/segmentjs.json`），`graph.nodes=42`（10 个 javascript-module、25 个 endpoint、3 artifact、2 source-map、2 asset）；对整份证据统计 `blend_mode/render_index/KFType/materials/...` 出现次数 **全为 0**。
- **Finding**：REA 的 JS 工作流回答的是「模块图 / Electron 边界 / IPC」问题（summary 里 browser_windows=0、ipc.operations=0），**不做字符串清点**。同时 `SegmentJS/main.js` 实测**不是混淆**：`"use strict"` 开头、4211 个 ≥6 字符标识符、含 `textComp`/`ClipName`/`animingMap`/`widget`，即 camelCase 的 **Lynx UI 组件包**，其中不含 snake_case 草稿字段名。
- **Path**：格式知识不在 JS 侧（见 F-005 起：全部来自语料 + 资源包 + 成片）。清点字段用直接遍历，不用 REA。已验证（REA 证据 + 直接 grep 两路一致）。

## F-003 crypto：内存串 API 是唯一可用面

- **Evidence**：`docs/evidence/crypto-probe-log.md`；`scripts/jy_crypto/pe.py` 解析导出表得 32,996 个符号、`EncryptUtils@lvve` 家族 14 个；`temp/crypto-probe/probe-log.json`、`gate20.json`。
- **Finding**：① 路径级静态 API（`decryptFile`/`isFileEncrypted`）对草稿密文副本**全部失败**（8 变体 status=1、0 字节，`isFileEncrypted` 恒 false），已记为未解决并停止试探；② 内存串 API 可用；③ 重加密**等长但摘要不同** → 容器含随机熵（导出表另有 `calcEntropyDynamicString`），**字节级回环不可能成立**。
- **门禁实测（20 份：10 legacy + 10 hybrid）**：等长 20/20、语义回环 20/20、外部 oracle sha256 一致 20/20、源文件未变 20/20。已验证（自有回环 + 独立 oracle 两路）。
- **r2 复测（2026-10-16，删除路径级绑定之后）**：同一 20 份样本再次 20/20 全通过（`temp/gate20-r2.log`），证明只保留内存串 API 不影响正确性；同批 `pe.py` 改为 mmap 读取（不再整读 66.0/72.5 MB 的 DLL），符号解析仍是 32,996 个导出、`?decrypt@` 两个重载 + 单一 `?encrypt@` + `?enable@`。
- **Path**：`docs/spec/crypto.md` 的门禁定义为「等长 + 语义回环 + 外部对照」；作废「字节回环」。所有调用在子进程，主进程不加载 DLL。

## F-004 存在没有 `tracks` 的空草稿

- **Evidence**：20 份门禁样本中 2 份解密后仅 922 B，顶层键含 `is_minimal_draft`，无 `tracks`；r3 的 **2,050** 份去重内容中 `is_minimal_draft=True` 有 **278 份（13.6%）**（`temp/corpus-detail/root_flags.csv`；旧稿写「2052 份 / 13.5%」是 r2 分母，2026-10-20 按 r3 重排）。
- **Finding**：「有 `draft_content.json`」不等于「有时间线内容」。
- **Path**：解析器不得假设 `tracks` 存在；`docs/spec/layout.yaml` 记录。

## F-005 时间基准与变速

- **Evidence**：`temp/corpus-detail` 统计：顶层 `duration` 数字位数分布 7–9 位（如 3,813,333）；6 个非 1 倍速样本的 `target_timerange.duration / source_timerange.duration` 与 `1/speed` 吻合（speed 1.3 → 0.769231；speed 0.8749998 → 1.142857）；`segment.target_timerange.start` 在 51,718 个 segment 中出现 47,422 次（**8.3% 缺省**，r3），键存在但无 `start`）。
- **Finding**：单位为**微秒**；`target = source / speed`；`start` 可缺省且含义为 0。已验证（比例实测 + 与 editor-skill 文档一致）。
- **Path**：`docs/spec/timebase.yaml`。缺省 `start` 读时补 0，序列化时**不得写回**该键。

## F-006 混合模式不是 segment 字段，而是 `type=mix_mode` 的特效

- **Evidence**：① 遍历 2051 份草稿找「值等于中文混合名」的键路径：`materials.effects[].name`（变亮 65 / 滤色 34 / 亮度 12 / 变暗 3 / 叠加 3 / 正片叠底 2…）与 `materials.drafts[].draft.materials.effects[].name`（复合片段内，158 次）；② 取出的完整对象含 `"type": "mix_mode"`、`resource_id`、`effect_id`、`path` 指向 `Resources/MixMode/<md5>`；③ `materials.effects[].type` 频次：`mix_mode` **166 次，落在 82 份去重内容里**（`tables/effects_type_values.csv`，r1 记 332 次，属翻倍口径）；④ 10 个 MixMode 包的 `Library/ShaderData/*/shaderGLES/*.frag` 明文 GLSL 尾行分别为 `SoftLight/Darken/LinearBurn/Multiply/HardLight/Lighten/ColorBurn/Screen/Overlay/ColorDodge BlendPreMul(fg, bg)`。
- **Finding**：**已验证**。混合模式 = 特效资源（10 种内置），且**全部按预乘 alpha 混合**（函数名后缀 `PreMul`）；草稿里不存在 `blend_mode`/`mix_mode` 字段（键名扫描的唯一 `blend` 命中是 `video_algorithm.motion_blur_config.blend`，一个 0.01–1.0 的运动模糊参数，无关）。
- **Path**：`docs/spec/picture.yaml` 用 `effects[type=mix_mode] → name/resource_id → CSS mix-blend-mode` 建模；数值以剪映自带 GLSL 为准（可逐式核对），不用浏览器默认非预乘语义。

## F-007 合成顺序：轨道级与片段级两个索引，数组顺序不是权威

- **Evidence**：`render_index_track_mode_on` 在 r3 的 2,050 份去重内容中 True=1,978 / False=63（本条原写 2052 份 / True=1980，2026-10-20 按 `root_flags.csv` 的 r3 值重排）；`track_render_index` 在轨道内**恒定**（8584 恒定 vs 1 变化）；`render_index` 按元素分类分带：video/audio/adjust ≈0 带、filter 10000 带、effect 11000 带、text/sticker 14000 带（`render_index_bands.csv`：text 14000=19596、video 0=7271、effect 11000=540、filter 10000=105）；轨道内 `render_index` 单调者 2070、不单调者 589（27%，判据为轨道内 ≥2 个带该键的片段；取 ≥3 则是 1523/510）；轨道归一化数组位置均值 video 0.266 < adjust 0.346 < effect/mixed 0.406 < filter 0.432 < sticker 0.448 < text 0.468 < audio 0.863，`video before audio` 5864 对 vs 反向 9 对，`video before text` 4729 vs `text before video` 1814（27.7%）。以上均为二级（按内容去重）口径，r2 重跑只带来漂移级变化。
- **Finding**：**单源待验证（方向未定）**。结构是：`track_render_index` 决定轨道间次序（每轨道一个值），`render_index` 决定同带内片段次序并按元素类别分带；`tracks[]` 数组顺序与视觉层级相关（视频靠前、音频垫底）但**存在 27% 的反例**，故数组顺序不能当绘制权威。
- **Path**：`docs/spec/14-compositing-order.md` 记录上述三个事实 + 待 M2 用 `<DRIVE_E>/输出` 成片判定的「升序=更靠上还是更靠下」。

## F-008 蒙版有两个不同 bucket

- **Evidence**：bucket 频次 `common_mask` **196 份内容 / 390 个条目**、`masks` **21 份内容 / 46 个条目**（去重内容口径；r1 的 412/42 是翻倍值，见 F-019）。字段形状（`shape_common_mask.csv`、`shape_masks.csv`，r2 起不再截断）：`common_mask.config.{width 390, height 315, centerY 250, centerX 206, feather 172, rotation 140, invert 94, roundCorner 65, aspectRatio 42, expansion 34}` + `text_config`（除 `align_type` 390 外还带 `font_name/font_path/font_resource_id` 35、`bold_width/char_spacing/content/font_size/has_underline/italic_degree/line_gap/scale` 33）+ `contour_path`(38) + `loader_work_space`/`track_segment` 36 + `is_old_version` 35；`masks.config` 的 7 个键（含 `width/height/invert/rotation/roundCorner`）在 46 个条目上全部出现 + `position_info` + `resource_id`。关键帧类型侧佐证：`KFTypeCommonMask{PositionX,PositionY,Feather,SizeWidth,SizeHeight,Rotation,Expansion,RoundCorner}`（59/59/54/48/48/43/25/15）与 `KFTypeMask*`、`KFTypeContourPath`（35；r1 记 70 属翻倍口径）。
- **Finding**：**已验证**（bucket 形状 + 关键帧类型两路）。内置形状蒙版 = `common_mask`（含 `invert`、`roundCorner`、`aspectRatio`，且支持轮廓路径 `contour_path`）；资源蒙版 = `masks`（走 `resource_id`）。两套关键帧前缀（`KFTypeCommonMask*` 与 `KFTypeMask*`）并存。
- **Path**：`docs/spec/materials.yaml` 两个 bucket 分别建表；`docs/spec/picture.yaml` 蒙版段落。

## F-009 裁剪在 material 上，是四角多边形

- **Evidence**：`videos.crop` 出现在 **16,585 个**视频 material 上（= 顶层 `materials.videos[]` 的全部条目，即未裁剪时也带该键，默认值语义待标定）；子键 `crop.{upper_left_x 4987, upper_left_y 4992, upper_right_x 5010, upper_right_y 4992, lower_left_x 4987, lower_left_y 4991, lower_right_x 5010, lower_right_y 4991}`，另有 `videos.crop_ratio`(4995)、`videos.crop_scale`(4950)（`shape_videos.csv`，仅顶层 bucket，不含嵌套草稿内部）。r1 的 13,828 是「每 bucket 只采样前 20 条」造成的下界。
- **Finding**：单源待验证（数值语义/坐标范围未标定）。裁剪是 material 级四角点，不是 segment 级 rect。
- **Path**：`docs/spec/picture.yaml` 记字段；范围与方向待 M2 标定。

## F-010 `clip` 无 z；`uniform_scale` 是 segment 级字段

- **Evidence**：`clip_fields.csv`（去重内容口径）：`transform`(37,890) / `flip`(37,890) 总是成对出现，`transform` 子键恒为 `x,y`（**无 z**）；`scale` 32,855、`rotation` 13,505、`alpha` 12,586。带 `clip` 键的 segment 共 42,215 个（其余只带 `clip` 的空壳或无 clip）。segment 级字段统计含 `uniform_scale` 34,843 次（r3；缺席 16,872、值为 null 4,325），而 `clip` 内从未出现该键。（r1 值 82,484/72,308/27,278/25,276 与 35,132 属翻倍口径，见 F-019。）
- **Finding**：**已验证**（与 capcut-cli 文档冲突，见 `conflicts.md` C-001）。
- **Path**：`docs/spec/picture.yaml`：`clip.transform={x,y}`；`uniform_scale` 与 `responsive_layout`（r3：present 51,612 / 缺席 103，共 51,718 个片段）属 segment。`clip` 本身也有 4,325 条写成 null（`field_states.segment.clip`），所以「带 clip 键」同样不等于「有变换数据」。

## F-011 字幕样式实测清点

- **Evidence**：`text_style_keys.csv`（去重内容口径）：`fill`(24,306) `range`(24,306) `size`(24,296) `font`(24,096) `shadows`(14,485) `useLetterColor`(10,721) `strokes`(6,226) `effectStyle`(1,774) `bold`(471) `italic`(443) `underline`(199) `bloom`(68) `inner_shadows`(28) `line_spacing`(9) `select`(3)。嵌套形状（r2 去截断后的真值，r1 因采样前 20 条而显著低估）：`fill.content`(24,306) 内 `{render_type 19,344, solid{color 23,903, alpha 4,283}, gradient 191{angle,color,alpha,percent,mode,style}, texture 336{range,path,scale,angle,blend,alpha,flip,playSpeed,stretchMode,wrapMode}}`；`strokes[]{content 6,202, width 6,202, alpha 1,595, mode 670}`；`shadows[]{content 14,527, distance 14,527, angle 14,527, alpha 14,418, diffuse 13,017, thickness_projection_{angle,enable,distance} 5,360, feather 1,508}`。
- **Finding**：**已验证**。字幕渲染必需字段清点完整；`useLetterColor`（逐字色，10,721）、`bloom`、`inner_shadows` 是既往资料未提的项。`shadows[].thickness_projection_*` 与 `shadows[].feather`、`strokes[].mode` 是 r2 去截断后才稳定显形的键，M2 渲染需决定是否支持。
- **Path**：`docs/spec/text.yaml`。

## F-012 动画预设的曲线是可读 Lua + GLSL，不是二进制

- **Evidence**：预设对象含 `resource_id` 与 `path`（如 `Cache/effect/7237411357514011192/12196518...`）；包内文件 `config.json`、`content.json`、`anim.prefab`（YAML Prefab，`ScriptComponent path=TextAnim.lua, className=TextAnim`）、`extra.json` = `{"setting":{"animation_duration":2.0}}`、`TextAnim.lua` **14,106 B 明文 UTF-8、566 行**，首两行是参数声明 `--@input float duration = 1.5{"widget":"slider","min":0.1,"max":6.0}`、`--@input float time = 0.0{...}`，随后是可调常量（`spriteScaleConst=0.7`、`spriteRotateSpeed=-250`、`charScale=0.6`、`charOffset=-0.6`）；`gles2_*.frag` 明文 GLSL（`c*curalpha`，边缘 `smoothstep` 羽化）。
- **Finding**：**已验证**（目录实测 + 文件内容直读）。预设动效以**随资源包分发的脚本与着色器**形式存在，可读；时长参数在 `extra.json.setting.animation_duration`（单位秒），且带 `--@input` 声明的可调参数。
- **Path**：`docs/spec/animations.yaml` 的曲线来源改为「解析预设包」，无需从成片反推（成片仍用于校验）。风险：资源包未必本机已缓存（F-014）。

## F-013 资源字典 `rp.db` 在本机是空的

- **Evidence**：6 个 `ressdk_db/<account>/rp.db`（77–257 MB），只读打开后 40+ 张表结构存在（`effect(id,category_id,category_name,effect_type,source,title,description,md5,effect_id,third_resource_id,aspect_ratio,extra,…)`、`loki_effect(effect_id,name,md5,file_uri,effect_type,…)`、`category_effect`、`preview_video_table`、`mask_video_table`），但抽查 3 个库的 `effect`/`loki_effect`/`category_effect` 等表 **rows=0**。
- **Finding**：单源。`rp.db` 当前不能作为 ID→名称 的解析来源；而草稿本身**内联携带名称**（`effects[].name`、`animations[].name`、`transitions[].name`），故命名不依赖它。
- **Path**：`docs/spec/resources.yaml` 记 schema 与「按需回退到草稿内联名称」。

## F-014 画幅取值与 fps 缺省

- **Evidence**：`canvas_ratios.csv`：`9:16`(867) `original`(341) `3:4`(123) `16:9`(95) `1:1`(4) `4:3`(3)；`root_flags.csv`：`fps` 在 2052 份去重内容中 **1367 份不存在**，存在时 30.0(646)/50.0(25)/60.0(11)/30(2)/24.0(1)；`color_space` 0=1808、-1=69、67=1。关键帧 `property_type` 实测 **70 种**（r1 记 50，是早期小样本遗留）。
- **Finding**：单源待验证（`original` 的确切渲染含义待标定）。画幅可为 `original`；fps 常缺省，渲染需回落策略。
- **Path**：`docs/spec/picture.yaml` 画幅段 + `unresolved.md`。

## F-015 语料规模与结构分布（M1 基准数，r3）

- **Evidence**：`temp/corpus-scan/{manifest.json,stats.json}`；`temp/corpus-scan-run-r3.log`、`temp/corpus-detail-run-r3.log`；修订过程见 F-019，冻结与漂移见 F-020，方法与限制见 `corpus-scan.md`。
- **Finding**：**1,475 个**草稿目录（1,240 个有内容、235 个 `no-content`）→ **2,215 份** `draft_content.json`（按文件；另有 `.bak` 2,803 / `template*.tmp` 4,688 未解析，见 F-025），按内容去重 **2,050 份**，解析成功 2,050、失败 0；文件口径布局 hybrid 1,033 / legacy 833 / 根镜像 349（合计 2,215），内容口径 hybrid 1,028 / legacy 831 / 仅存在于根镜像 191；目录口径 1,475 = legacy 833 + 含 `Timelines/` 407 + 无内容 235，而 407 里只有 229 个能枚举到 `Timelines/<id>/draft_content.json`、**120 个只枚举到根镜像**（新开 U-57）；编码（文件）密文 1,876 / 明文 339，（内容）1,713 / 337；material bucket 实测 **42 个**（r1 记 39，r2 新增 `audio_pannings`/`video_shadows`/`video_strokes`）；动画条目 10,565 条（r3 为 10,565）、预设 **417** 种（键 `(type,name,id)`；把 `category_name` 计入则是 **606**）、转场 **2,193** 种、特效去重元组 **71,414** 个 / 记录 **73,972** 条；关键帧 `property_type` **70** 种；顶层 segment **51,718** 个、视频 material 16,634 个、字幕 material 21,086 个。相对 r2（2,052 份内容 / 51,784 片段）的普遍下移由**一次草稿删除**解释，不是测量噪声（`temp/drift-r2-r3.txt`）。
- **Path**：M2 的 phase-1 覆盖优先级按此频次表排；引用任何计数都要带上 `stats.json -> corpus.snapshot_date` **与轮次号**（r1→r2 是口径修正，r2→r3 是真实漂移）。

## F-016 UI 面板 ↔ 字段对照与首批换算系数（用剪映「文本-基础」面板实测）

- **Evidence**：用户提供的剪映文本面板截图（位置 Y `-850`、缩放 100%、等比缩放开、不透明度 50%、描边 100%/粗细 40、阴影 90%/15%/5/-45°、背景 100%/0%/14%/14%/50%/50%、发光 30/20/0°/0°、弯曲 72°、字号 10、字间距 0、行间距 0）；据此在解密语料中按「阴影 distance≈5 且 angle≈-45 且 alpha≈0.9」检索，命中 11,819 个 text material（r2 检索当时的数，未按 r3 重取），其 `canvas_config={width:1080,height:1920,ratio:null}`、`clip.transform.y=-0.4427083333333333`、`clip.scale={1.0,1.0}`、`uniform_scale={}`、`shadows[0]={distance:4.9999995, angle:-45, alpha:0.8999999, diffuse:0.025}`、`line_spacing:0.02`、`background_*` 全为 null、`font.path` 指向 `Cache/effect/<rid>/<md>/字由墩墩体.ttf`。
- **Finding**（逐项，已验证除注明外）：
  1. **位置单位 = 全画幅归一**：`-0.4427083333333333 × 1920 = -850` 与 UI 精确吻合 → `px = transform × canvas_config.{width,height}`，符号与 UI 一致。U-08 的单位部分解决。
  2. **阴影 `distance`/`angle` 与 UI 1:1、`alpha` 为 0..1**（0.9↔90%）→ 参考文档「em 相对且 distance/100」被推翻；`diffuse 0.025 ↔ UI 15%` 给出候选系数 ×6（单样本，U-03 残留）。
  3. **背景面板显示值在 draft 中为 null** → 14%/50% 这类值是**由文字度量推导的默认**，不是存储值；渲染器需内置同一默认，否则未设背景的文本会多出背景块。
  4. **`uniform_scale` 在「等比缩放」开启时为空对象 `{}`** → 印证 C-001（它是 segment 级字段）。**形态部分更正（F-023/U-42）**：`{}` 只是四种写入形态之一——r3 实测 `{}` 18,010、`{on:true,value:1.0}` 12,467、null 4,325、缺席 16,872、`{on:false}` 35、仅 `value` 若干；capcut-cli 说的 `{on:true,…}` 形态**确实存在**，所以「与 capcut-cli 不符」这半句作废，位置之争才是不符的那半。`value` 是 `clip.scale.x / clip.scale.y` 的缓存（12,465 命中 / 8 过期），不是开关。
  5. **描边**：`strokes[]{content.solid.color, width, alpha, mode}`；`alpha` 仅 278/1183 显式出现 → 缺省即 1，与 UI 100% 一致；`width 0.08 ↔ UI 40` 为单样本候选系数 500；另有 UI 无对应控件的 `mode` 字段（U-24，当时误记为 U-21）。
  6. **弯曲**：`texts.text_curve{enable, angle}`，angle 直接给度数（样本 83.265）→ 与 UI「弯曲程度 72°」同型。
  7. **对齐**：`texts.alignment` 取值域实测 `{0,1,2,3,4}` + 缺省（r3：21,086 个字幕 material 里只有 **7,729** 条带该键，取值 1 占 7,158、0 460、2 61、3 42、4 8）。**「对应面板 6 个按钮的水平/垂直组合」当时是猜测，且 5 个取值对不上 6 个按钮**——按钮↔取值的对应仍是 U-30，未结案。
  8. **字体**：`styles.font{id, path}`，path 为 `Cache/effect/<资源id>/<md5>/<字体名>.ttf` → 字体解析链 verified；`fonts` 键在样本中未以容器形式出现。
  9. **未对应项：发光**。`styles.bloom` 全语料只出现 **68 次且 68 次全为 null**（r3 复核，`temp/check-1016/probe8.txt`；当时只数出手工样本里的 12 次），无法承载 UI 的颜色/强度/范围/垂直角度/水平角度。当时记为「新增 U-22」，因两会话撞号实际登记为 **U-25**，已由 F-017 关闭、F-022 补充：承载者是 `effects[type=="bloom"]`，而 `bloom_params` 键本身在 19,491 个非发光条目上是 null 占位，不能当指示器。
  10. **字号**：截图 10 与命中样本 13 不一致（可能非同一 segment）→ 新增 U-26，不做无据换算。
- **Path**：全部写入 `docs/spec/text.yaml` 的 `ui_panel_mapping`（含 controls / unmatched / calibration_leads 三节）；`unresolved.md` 更新 U-03、U-08，新增 U-24、U-25、U-26（因两会话编号冲突而用后段号）。后续 M2 标定优先复用这条「UI 数值 → 语料检索」路径，它比逐帧像素比对便宜得多。

## F-017 差分实验：用户新加「文本发光」→ 定位 bloom 承载字段与 panel_id

- **Evidence**：用户在 `电商断刀 10月15日 (5)` 新建时间线并给文本加发光。只读解密该草稿全部 14 份 `draft_content.json*` 副本（产物进 `temp/bloom-probe/`，源文件未动）。`Timelines/project.json`（明文）给出 `main_timeline_id` 与 4 条时间线；发光出现在非活动时间线 `E5EE1E48…`（1 video + 1 text 片段，duration 39.2 s）。该文本 material 的 `check_flag=71`、`border_width=0.08`、`shadow_distance=5.0`、`shadow_angle=-45.0`、`shadow_point={x:0.6364,y:-0.6364}`（**向量**）、`text_color:"#FFFFFF"`（十六进制串）、`font_path` 指向安装内 `Resources/Font/SystemFont/zh-hans.ttf`。发光本体是一条 effect：
  `{"name":"外发光","type":"bloom","effect_id"/"resource_id":"7202576698775179837","panel_id":"tool_text_glow","bloom_params":{"color":"#FFFFFF","strength":0.3,"range":0.2,"dir_x":0.5,"dir_y":0.5},"path":"Cache/effect/7202576698775179837/13fd5bb6c22236bb299c266428395180"}`
  对照截图：强度 30 ↔ `strength 0.3`、范围 20 ↔ `range 0.2`、垂直/水平角度 0° ↔ `dir_y/dir_x = 0.5`。
  语料侧统计（当时口径：1714 份**明文**、按文件）：`panel_id` 与 `bloom_params` 共出现 21,433 次、分布在 210 份文件，但**全部为 `""` / `null`**；`"type":"bloom"` 0 次；`video_shadows` 仅以空数组出现 1 次。**r3 全量复核**（`stats.json -> bucket_keys.effects`）：`panel_id`/`bloom_params` 各存在 **19,492** 条，其中 19,491 条是 `""`/null；唯一 `panel_id` 非空的条目现在是 **10月16日 草稿的「轮廓光」**，本条当初那条「外发光」已随其时间线不在快照里（F-022）。
- **Finding**：
  1. **发光的承载者是 effect，不是文本样式**（U-25 关闭）。`styles.bloom` 恒 null 是 schema 占位字段，据此判「无承载字段」是错的——已修正 `spec/text.yaml`。
  2. **`effects[].panel_id` 是面板身份**。语料里它总是空串（因为绝大多数 effect 不是从面板加的），一旦非空即给出「控件 ↔ 字段」的直接连接（`tool_text_glow`）。这是目前最直接的一条 UI 映射线索，值得作为后续映射的主键。
  3. **`bloom_params`/`panel_id` 是 effect 的固定 schema 字段**，出现次数等于 effect 条目数，不能把「键存在」当「功能被使用」——这条对全部 schema 字段成立，是清点方法上的教训。
  4. **新 bucket `video_shadows[]`**（画面侧「阴影」面板）：r3 实测真实键集是 `{id, type:"video_shadow", enable_video_shadow, resource_id, resource_name:"阴影", path, source_platform, color, alpha, distance, angle, **ambiguity**}` —— 当时顺手记下的 `cache_time_range` **并不存在**（那是 `smart_relights` 的键），也漏了 5 个参数键。r1 语料里该 bucket 只以空数组出现 1 次 → **bucket 清单并未闭合**，已并入 `spec/materials.yaml`（U-29）；r2 重扫测得 2 份内容非空，同批又暴露 `video_strokes[]`、`audio_pannings[]` → bucket 总数 39 → **42**（见 F-019、U-39）。当时据此否掉另一会话「画面阴影 = `videos.video_mask_shadow`」的推断方向**正确**，但「`video_mask_shadow` 只是另一处并存字段」的说法太弱：它是**蒙版**阴影/描边的参数体，且带参数与 `enable_mask_*` 只是单向配对——完整的裁定、键名差异（`ambiguity` vs `blur`）与 caveat 见 **F-021**。
  5. **换算系数复现**：同一草稿上 `border_width 0.08 ↔ UI 描边 40`（系数 500 在第二个独立样本上复现，F-016 的候选得票+1）；`shadow_distance 5.0 ↔ UI 5`、`shadow_angle -45 ↔ UI -45°` 再次 1:1。
  6. **两套颜色编码并存**：扁平字段用 `"#RRGGBB"` 串（`text_color`、`bloom_params.color`、`albedo_color:"#FFFFFFFF"` 8 位），`styles.fill/strokes/shadows` 用 `[r,g,b]` 0..1 数组。渲染层必须都吃。
  7. `check_flag=71`（=1+2+4+64）是该位表里 bit6=64 的**首次出现**（r1 语料从未有 64 位；r2 未专门重测该位分布）→ U-28，疑与发光/阴影子系统相关。
- **Path**：`spec/text.yaml`（resolved_by_differential_experiment）、`spec/materials.yaml`（video_shadows）、`unresolved.md`（U-25 关闭，新增 U-27 dir→角度、U-28 bit64、U-29 bucket 清单未闭合）。
  方法论：这类「用户改一个控件 → 我只读解密做 diff」是成本最低的判定手段，后续 U-26（字号）、U-27（角度）、U-28（bit64）、U-06（responsive_layout）都适合用它，一次一个控件。

## F-018 两个蒙版入口共用一个 bucket，靠 `category` 区分；蒙版参数是归一化值

（编号说明：此条原与「差分实验：文本发光」同为 F-017，两会话并发改号撞车；按引用面把发光条保留 F-017，本条改为 F-018。）

- **Evidence**：388 个 `common_mask` 条目（2051 份去重草稿）中 `category` = `video` 319 / `adjust` 69，`type` = `mask` 319 / `none` 68；`category_name` = 基础 208 / 全部(对应Loki All分类) 66；`text_config` 388 全带、`contour_path` 9、`track_segment` 3。config 数值分布：`centerX` n=206 ∈ [-1,1]（中位 0.000）、`centerY` n=250 ∈ [-1,0.783]（中位 0.018）、`rotation` n=140 ∈ [-360,325]、`width` n=388（min 0.001 / **中位 0.500** / max 3.122）、`height` n=313（中位 0.498 / max 1.352）、`feather` ∈ [0,1]、`roundCorner` ∈ [0,0.88]；完整键组合含 `expansion`。用户提供的两张面板截图给出「调整→蒙版：线性/镜面/圆形/矩形/文字 + 两个画笔；位置 X0 Y0、旋转 0.0°、大小 宽540 高538、羽化0、圆角0；跟踪方向 双向跟踪」与「色轮：log色轮、强度100、阴影/中间调/高光/偏移 四盘 R/G/B」。
- **Finding**：**已验证**。① 画面→蒙版 与 调整→蒙版 是同一 `common_mask` bucket 的两个 `category` 分支，不是两套结构；② 面板「无」= `type:none`；③ 「文字」蒙版由 `text_config` 承载、画笔自定义轮廓由 `contour_path` 承载、跟踪由 `track_segment` + `video_trackings` 承载；④ **蒙版尺寸两轴均按画布宽度归一**：540/1080=0.5、538/1080=0.498 与实测中位数逐位吻合，故 `px = value × canvas_config.width`（注意与 F-013/位置单位「按对应轴尺寸」除数不同）；⑤ `rotation` 单位是度，`feather`/`roundCorner`/`centerX/Y` 是归一化比例；⑥ config 里的 `expansion` 对应面板未在此截图展开的「扩展」，与 `KFTypeCommonMaskExpansion` 一致；⑦ 色轮面板下拉「log色轮」即 `log_color_wheels`，`intensity` 对应「强度 100」，四盘名 `shadow/midtone/highlight/offset` 与 UI 逐字对应。
- **Path**：写入 `docs/spec/panel-map.yaml`（画面.蒙版 tab、画面.蒙版参数单位、调整.蒙版、调整.色轮）；`enable_adjust_mask`/`enable_video_mask` 不得用作蒙版生效判据（U-13 关闭）。M2 渲染实现按 `category` 分流：`video` 参与画面合成，`adjust` 只约束调色范围（本项目 phase-1 跳过调色，故 `adjust` 分支只需保真读写、不需渲染）。
- **r2/r3 计数校正（仅条目数，不改结论）**：去截断重跑后 `common_mask` 条目 388 → **390**（r3 **391**）、`config.width` 388 → 390（r3 391）、`config.height` 313 → 315、`roundCorner` 63 → 65、`feather` → 172、`contour_path` 9 → **38**、`track_segment` 3 → **36**、`loader_work_space` → 36（旧值是「每 bucket 只采样前 20 条」的下界，见 F-019）。**`type` 有第三个取值**：r3 实测 `mask` 321 / `none` 68 / **`""` 2**，`category` = `video` 321 / `adjust` 70 —— 那 2 条 `type:""` 都来自 10月16日 草稿的 `adjust` 蒙版，所以「面板选『无』= `type:none`」之外还有一种「整值留空」的写入形态，渲染层要把 `""` 也当「无」处理（`temp/check-1016/probe7.txt`）。`category`/`type` 的分布来自 `scripts/spec_audit.py`（含嵌套草稿口径）时与顶层口径的 `shape_common_mask.csv` 不可直接互比；本条的中位数/极值类换算结论（`width` 中位 0.500、按画布宽度归一）待用新表重算一次再引用。

## F-019 一级语料频次被完整重放两遍（根别名），r2 起统一按去重内容计

- **Evidence**：`scripts/jy_crypto/cache.py` 的默认草稿根声明了 `<DRIVE_D>/JianyingPro\<DRAFT_ROOT>` 与 `%LOCALAPPDATA%\JianyingPro\<DRAFT_ROOT>`；后者是 junction（`Target = C:\JianyingPro\<DRAFT_ROOT>` → `<DRIVE_D>/JianyingPro`），两者 `.resolve()` 后是同一个目录（实测相等）。`corpus_scan.enumerate_corpus()` 对 `draft_roots()` 逐个遍历，于是整份语料被走两遍：r1 的 `temp/corpus-scan/manifest.json` 有 **4900 条记录但只有 2215 个不同路径**，每个 content key 的出现次数是 2（1889 个）、4（161 个）、8（1 个）（r1 原始件留在 `temp/baseline-r1/`）。
- **Finding**：
  1. 一切来自一级 CSV 的频次**恰好 ×2**（同一条记录被重放两遍，倍数对每个键一致），因此 `r1 值 ÷ 2 = 按文件口径真值`；换算到**去重内容**口径还要再除掉「同一内容有多个副本」的那部分（2216 文件 vs 2052 内容），所以比值不是严格 2（例如 `clip.transform`：82,484 → ÷2 = 41,242（按文件）→ 37,890（按内容））。
  2. **集合类指标不受影响**：bucket 个数、distinct 预设/转场/元组数对重复本身不敏感；二级 `corpus_detail` 一直按 content key 去重，所以 `timebase.yaml` 的 segment 计数、`canvas_ratios`、`render_index_bands`、`order_agreement`、F-007 的合成顺序统计、F-016/F-017/F-018 的标定数字都只是语料漂移级的小变化（逐条核对后保留）。
  3. 顺带暴露两处**方法性**缺陷：`corpus_detail` 的 `items[:20]` / `node[:4]` 截断让所有形状类计数变成**下界**（`videos.crop` 13,828 → 16,585，`fill.content.solid.alpha` 1,413 → 4,283，`shadows[].feather`、`strokes[].mode`、`masks.config.width/height/invert`、`common_mask.text_config.font_*` 是去截断后才显形的键）；只读证明当时取排序后前 20 个文件（实际只覆盖十来份草稿），已改为按布局分层的随机 40 样本。
  4. `70,718` 从来不是「特效记录条目总数」，而是去重 `(name,id,category)` 元组数（记录总数 73,915，按文件 74,431）——见 conflicts C-010。
- **Path**：`cache.py::_roots()` resolve 后按序去重；`enumerate_corpus()` 另加路径去重 + `duplicate_paths_skipped` 计数；`stats.json -> corpus` 记录 `snapshot_date / content_files / distinct_contents / content_multiplicity / encoding_by_file / encoding_by_content / counting_basis`，且 `records != unique_paths` 或 `drafts_parsed != distinct_contents` 时扫描**返回非 0**（本仓库无测试基建，这条自检即回归测试）。`corpus_scan.py` 聚合改为按 content key 去重，`corpus_detail.py` 去掉截断。`tables/` 里 12 张表与 8 个规格/证据文件的计数已按 r2 重生成。结论方向（F-006/F-008/F-012/F-003/F-005）无一被推翻，改的是量纲与出处。

## F-020 复测批次：一份「尽量打开所有样式」的草稿，外加语料冻结（r3 起为基准）

- **Evidence**：用户 2026-10-16 手工造的 `10月16日` 草稿（`platform.app_version 11.6.0`、`app_id 3704`、`new_version "189.0.0"`、`version 360000`），1 个 video + 1 个 text 片段，根镜像与时间线副本**密文逐字节相同**（sha256 前缀 `d4807d15`，各 62,768 B）；`extra_material_refs` 52 + 2 条**全部可解析、0 悬挂**，跨 24 个 bucket。产物：`temp/check-1016/{timeline_copy.json,buckets.json,probe6.txt,probe7.txt,probe8.txt}`。同一时间给扫描器加了冻结与清点：明文草稿也复制进 `temp/corpus-scan/plain/`（r2 时 337 份明文是每次从草稿目录**实时再读**，一小时内 `videos.smart_motion` 4,856→4,858 就是这种漂移），`corpus_detail.py`/`spec_audit.py` 优先读冻结副本；新增 `stats.json -> field_states / path_macros / check_flags` 与 `temp/corpus-detail/{animation_timing.csv,relations.csv}`。r2→r3 全量漂移见 `temp/drift-r2-r3.txt`：期间**少了一份内容文件**（`中智矩阵 10月13日 (1)-副本` 的时间线 `E9A3E52A…` 被删），于是 2,216→2,215 份文件、2,052→2,050 份内容，其余计数普遍下移 0.6–0.9%（单个键最大相对变化 `texts.operation_type` −3.8%）。
- **Finding**：**已验证**。① r3 基准数 = 2,050 份去重内容 / 51,718 个顶层 segment / 16,634 个视频 material / 42 个 bucket / 70 种关键帧 `property_type`；② 这份草稿**单独**把 6 种 `effects.type` 带进语料（排除它 33→27 种，见 U-40），所以它是双刃剑：既暴露最多，也最容易让规格把一次实验当成常态；③ 方法论修正——凡是「全部 / 恒为 / 都有」的断言，必须先用 `field_states` 的 **present / null / absent 三分**核一遍再写，「键存在」不等于「有值」，「有值」不等于「非默认」（`caption_info` 就是 13,835 条全 null 的反例，见 F-024）。
- **Path**：从本条起，`docs/` 引用的每个计数都必须能指到 `stats.json`、`relations.csv`、`animation_timing.csv` 或 `probe6/7/8.txt` 之一；`evidence/corpus-scan.md` 增设 r3 段与漂移说明；`spec/*.yaml` 全部改引 r3。

## F-021 画面侧「阴影」载体定案，与蒙版阴影/描边分离（两会话之争结案）

- **Evidence**：语料里只有 **2** 条带参数的 `materials.video_shadows[]` 条目，分属两份互不相关的草稿——`10月16日`（`d4807d15`）与 `电商断刀 10月15日 (5)`（`ca332262`，时间线 `58441AA1`）——**除条目自身 uuid 外逐字段同值**：`{type:"video_shadow", enable_video_shadow:true, color:"#000000", alpha:0.30000001192092896, ambiguity:0.10000000149011612, distance:0.05000000074505806, angle:-30.0, resource_id:"7564727861634944292", resource_name:"阴影", path, source_platform:1}`（12 键，含 `id`）。另一会话从面板截图读到的正是「不透明度 30% / 模糊度 10% / 距离 5 / 角度 -30°」→ **距离 = UI/100、模糊度的键名是 `ambiguity`**（全语料此前零记录）。同期 `videos.video_mask_shadow` 在 16,634 个视频 material 上缺席 8,129、只带 `{path,resource_id}` 占位 8,498、带 `{color,alpha,blur,distance,angle}` 仅 **7** 条，且这 7 条里 6 条才对应 `segment.enable_mask_shadow=true`；它用的键是 `blur` 而不是 `ambiguity`，数值也是 0.9/0.15/-45 而非面板那组。`video_strokes[]` 两条都只有 `{id,type,enable_video_stroke,path:"",resource_id:""}`，**没有任何参数**。
- **Finding**：**已验证**（两份草稿 + 键名差异 + 与面板读数逐位吻合，三路一致）。裁定：**画面侧「阴影」= `materials.video_shadows[]`**；`videos.video_mask_shadow/stroke` 是**蒙版**的阴影/描边参数体，绝大多数时候只是资源占位（`enable_mask_*` 开关在 51,718 个片段里只有 17 个带，见 U-38）。另一会话把面板判给 `video_mask_shadow` 的唯一理由「该对象恰带那 5 个参数」在两份样本上都不成立。**caveat（必读）**：两份样本同机、同 11.6.0、参数完全相同，很可能是同一组**面板默认值**被写了两次，而不是两次独立观察；因此「`distance = UI/100`」这条换算仍是单点，`ambiguity = 模糊度` 则是键名事实、不受此影响。描边那半边没有结案：画面侧参数体根本没找到（U-39）。
- **Path**：`spec/panel-map.yaml` 的 画面.基础.描边（画面侧）/阴影（画面侧）两行按此改判并删掉「待用户裁决」；`spec/materials.yaml` 的 `video_shadows`/`video_strokes` 行补真实键集；U-29 关闭、U-38 半关、U-39 收窄。

## F-022 文字发光在 r3 快照里只剩一个样本，而 `bloom_params` 不是发光的指示器

- **Evidence**：`effects[].type=="bloom"` 全快照 **1 条**，是 `10月16日` 草稿的「轮廓光」`resource_id/effect_id=7202575978646737469`，带 `panel_id:"tool_text_glow"` 与 `bloom_params{color:"#000000", strength:0.5, range:0.4, dir_x:0.5, dir_y:0.5}`，由 text 片段 `extra_material_refs` 引用（`probe6.txt`）。F-017 那条「外发光」`7202576698775179837` 在 `resource_id/effect_id/third_resource_id` 上 **0 命中**，其所在时间线 `E5EE1E48…` 已不在盘上，只剩 `temp/bloom-probe/` 里的历史产物。外壳键（内容级）：`panel_id` 与 `bloom_params` 各存在 **19,492** 条，其中 `panel_id` 19,491 条是 `""`、`bloom_params` 19,491 条是 `null`（挂在 `figure` 8,984 / `brightness` 1,577 / `makeup_root` 1,251 / `contrast` 1,234 … 这些**与发光无关**的条目上）；`apply_target_type`/`enable_skin_tone_correction`/`formula_id`/`time_range` 各 19,491，`covering_relation_change` 8,084。
- **Finding**：**已验证**。① 判「有发光」只能看 `type=="bloom"`（或 `panel_id` 非空）；**按 `bloom_params` 键存在来判会误报 19,491 次**——它和 `panel_id` 一样是 effect 条目的固定 schema 占位，这条把 F-017 item 3 的方法论教训量化了；② ×100 换算在第二个独立样本上复现（`strength 0.5 ↔ UI 50`、`range 0.4 ↔ UI 40`），但 `dir_x/dir_y` 仍是 0.5 中点，U-27 没有推进；③ 面板两枚样式现在各有一个 resource_id（外发光 / 轮廓光），`panel-map.yaml` 那条「第二枚需再取样本」可以合上，只是外发光那枚在当前快照不可复核；④ F-017 的「21,433 次 / 210 份文件」是 r1+按文件口径，内容级真值是 19,492。
- **Path**：`spec/panel-map.yaml` 发光.样式两枚 / 发光.面板身份、`spec/text.yaml` 的 `resolved_by_differential_experiment`、U-25 保持已结论、U-28 收窄、U-40 加单样本脚注。

## F-023 三个「源字段 + 派生缓存」等式（写回必须同步，渲染只读源）

- **Evidence**：`temp/corpus-detail/relations.csv`（r3，逐片段 join 实测，脚本 `scripts/corpus_detail.py::mine_relations`）：`speeds[].speed == segment.speed` **11,678 / 11,678**（`speed != 1` 的片段**全部**有 speeds 镜像；无镜像的 7,923 个片段倍速都是 1）；`uniform_scale.value == clip.scale.x / clip.scale.y` **12,465 命中 / 8 过期**，`{on:false}` 35 条全部 `x != y`，`{on:true,value:1.0}` 全部 `x == y`；`|shadow_point| == 0.18 × shadow_distance` **19,847 命中 / 963 不符 / 266 无可用距离**，方向 `== (cos,sin)(shadow_angle)` **20,834 / 21 不符**；同时 `|point| == shadow_alpha` 也"命中"15,621 次——那是 **alpha 常等于 0.18×distance 的巧合别名**，不是公式。
- **Finding**：**已验证**（同一脚本可重跑，异常样本数已量化）。① 这三对都是「源 + 派生缓存」，缓存会过期（8 / 963 / 21 条实测），所以渲染层必须只读源字段，写回必须同步或删除缓存键；② `shadow_point` 的系数是 **0.18 × 距离**，此前 `panel-map.yaml` 写「角度×距离 的预计算」不准（距离只出现在标量里、且与 alpha 撞值）；③ `uniform_scale.value` 是**比例缓存**而非开关，`on` 才是锁（勾选态↔形态仍有残留，见 U-42）；④ `speeds[].speed` 是 `segment.speed` 的镜像，"speeds 是 stub" 的说法作废（C-011）。
- **Path**：`spec/write-rules.md` §3 新增三条同步不变式；`spec/picture.yaml` 新 `derived_caches:`；`spec/text.yaml`、`spec/panel-map.yaml` 的阴影/等比行；`evidence/conflicts.md` C-011。

## F-024 一批「渲染或解析必须处理、规格此前零记录」的字段

- **Evidence**：`stats.json -> field_states / path_macros / bucket_enum_values`、`temp/check-1016/probe6.txt`、`probe7.txt`、`probe8.txt`。逐项（r3 计数）：
  1. **路径宏 `##_draftpath_placeholder_<uuid>_##/`**：1,311 / 2,050 份内容、共 **58,108** 次；展开后指向**草稿自身目录**（`Resources/videoAlg/d0765d…_0_990000.mp4`、`video/figure_algorithm/<video material id>`、`Resources/audioAlg/…wav` 都在草稿目录里命中；`matting/<md5>` 是尚未生成的缓存）。该 uuid 既不是顶层 `id`（= timeline id）也不是 `Timelines/project.json` 的 `id`（U-41）。
  2. `segment.hdr_settings`：缺席 23,454 / null 11,879 / `{mode:1}` 10,980 / `{intensity:1.0,mode:1,nits:1000}` 3,490 / `{mode:4}` 499 / `{intensity,mode:4,nits:1000}` 1,347 + 二十余种 intensity 变体。
  3. `videos.corner_pin`（角钉/透视）：11 条带键（10 dict + 1 null），`{enable_corner_pin, id, corner_pin_info{upper_left_x, upper_left_y, upper_right_y, lower_left_x[, lower_left_y]}}`，未动过的角写 **-1.0**；与 `videos.crop`（16,634 条全带，未裁剪时是 `{}` 11,589 或 8 角点 4,955）是**两套东西**。
  4. `segment.caption_info`：37,880 缺席 + 13,835 **全为 null**，没有一条有值 → schema 占位，解析器不要为它写分支。
  5. `segment.color_correct_alg_result`：6,011 个片段带，是**又一个「JSON 塞在字符串里」**的字段，键名带官方拼写错误 `*IntensityFisrt`（`whiteIntensityFisrt`、`brightnessIntensityFisrt`…）。
  6. `effects[].intensity_key` 38,918 条存在（28,411 在 `figure` 上），取值是 `face_adjust_*` / `body_adjust_*` 参数身份名（`face_adjust_NasolabialFolds`、`body_adjust_SlimWaist`…），另有 `adjust_params[]{name,value,default_value}` 30,889、`face_adjust_params[]` 21,112、`exclusion_group[]` 21,113、`item_effect_type` 35,663、`algorithm_artifact_path` 41,193、`lumi_hub_path` 31,456（指向包内一个同名文件）。
  7. `videos.smart_motion` 4,858 条带键，其中 **4,855 是 null**，只有 3 条有内容（`motion_mode:-1`，另两条带 `motion_rotate/scale/shift/beat_type/source_recog_beats/source_recog_body_motion`）。
  8. `hsl[]` 条目的 `hue/saturation/lightness` 是**整数**（取值可到 ±100，如 `saturation=-100` 229 条）；`hsl_curves` 除 `hue_hue` 外还有 `hue_lum`/`hue_sat`（各 1 条，且都由这份草稿带入）。
  9. **动画容器与条目**：`material_animations[].type` **恒为 `sticker_animation`**（34,821 / 34,821，视频和字幕动画也叫这个名字，别按它筛类型）；`animations[].type ∈ in 8,388 / loop 1,587 / out 303 / caption 158 / group 129`；条目键集 `id/type/resource_id 10,563、path 10,553、material_type 10,514、duration 10,354、name 9,393、category_name 8,877、category_id 8,846、source_platform 8,707、third_resource_id 8,253、request_id 5,004、panel 4,006、start 3,577、platform 3,529、anim_adjust_params 3,523（**全部为空**）`；`category_name` 取值混了五种写法（`收藏 3,626 / "" 2,411 / 入场 1,978 / ruchang 128 / in 126 / group 88 / 字幕动画 52 / 組合·進場` 等）。
  10. `styles[].range`：24,075 条是 `[start,end]` 数组、**10 条是空格分隔字符串** `"0 10"`，**字典形一条都没有**（`text.yaml` 原记「数组形与字典形并存」不成立）。
- **Finding**：单源待验证（除第 9、10 两项有全语料支撑）。共同点是它们都**不在面板↔字段主清单里**，但解析器要么吃下、要么原样保留：宏路径关系到资源能不能找到，`caption_info`/`smart_motion` 这类「键在值为 null」关系到「键存在 ≠ 功能开启」的判读，动画 `duration/start` 是渲染时序的必需输入（`animation_timing.csv` 现在给出各类型的时长域：in 33,333–4,200,000 µs、out 0–3,100,000、loop 0–5,000,000、group 100,000–4,700,000、caption 533,333–3,000,000；**非零 `start` 只出现在 out 108 条与 group 10 条上**）。
- **Path**：`spec/animations.yaml`（容器↔条目分离、键集、计时）、`spec/text.yaml`（range 两形）、`spec/picture.yaml`（新字段块）、`spec/materials.yaml`（`effects`/`videos` 细键）、`spec/layout.yaml`（宏路径落点目录）、`spec/write-rules.md`（宏的写回规则）。

## F-025 副本普查是个下界：扫描器只跟 `draft_content.json`

- **Evidence**：`stats.json -> corpus.replica_census_not_parsed` = `{draft_content.json: 2,215, draft_content.json.bak: 2,803, template-2.tmp: 2,888, template.tmp: 1,800}`（清点草稿根目录与 `Timelines/<id>/`，**不解析**）。10月16日 草稿实测：根目录与其时间线目录里 `draft_content.json`、`draft_content.json.bak`、`template-2.tmp` 三个都是 62,768 B，其中 `template-2.tmp` 与主文件**密文逐字节相同**、`.bak` 等长而摘要不同（`d4807d15` vs `f237e3df`）；`template.tmp` 只在时间线目录里，3,984 B，是另一份内容。
- **Finding**：已验证（清点 + 逐文件 sha 对照）。① 语料的「内容文件数」2,215 是**下界**，同一内容另有 `.bak` 与 `template-2.tmp` 两级副本；② **密文 sha 不同不能当内容分叉的证据**——容器每次重加密都带随机熵（F-003/U-20），必须先解密按 content-id 判定；③ 写回选址必须把这两类副本纳入候选（现在只按文件名猜会漏），但本项目 M1 只读，未做任何同步实验（U-17）。
- **Path**：`spec/layout.yaml` 的 `replicas.observed_candidates` 与 `file_counts_by_layout` 加注「普查下界」；`spec/write-rules.md` §1 第 3 条；`evidence/corpus-scan.md`。

## F-026 语料判不了的三项：把「缺席」写成结论而不是留空

- **Evidence**：`temp/check-1016/probe8.txt`。① 20,606 份含字幕的内容里**没有一个非 BMP 字符** → `styles[].range` 到底是字符索引还是 UTF-16 code unit（U-01）**无法从语料判**；② `styles[].strokes[].mode` 带该键的 666 条**全部是 0**、其余 5,532 条整键缺席 → U-24 无法判；③ `styles[].shadows[].thickness_projection_enable` 只有 `absent`(9,184) 与 `False`(5,366) **从未 True**，`feather` 带值时以 0.055556 为主（1,193 条）→ 面板上没有对应控件的「厚度投影」在语料里从未被启用过。
- **Finding**：已验证（全量清点，不是抽样）。这三项的共同点是「语料里没有反例也没有正例」，所以正确的登记方式是**改判定方法为「需构造样本」**，而不是继续把它们写成「语料可判、待办」——原文档正是这么错的（U-01/U-24 都标着「M2 前（纯语料可判）」）。另一条可复用的读法：`shadows[].feather` 的 0.055556 众数（≈1/18）与 `useLetterColor` 带键即 true（10,637 条、无一 false）说明**「键出现」本身就是状态开关**，缺省值要按众数而非 0 来猜。
- **Path**：`evidence/unresolved.md` U-01、U-24 改标注；`spec/text.yaml` 的 `range_semantics` 与 `styles.useLetterColor`。

## F-027 差分实验批次（构造样本，经剪映 UI 代打）：四项结案、一项部分、两项阻塞

- **Evidence**：`<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\差分样本 10月18日` —— 10月16日 草稿的**副本**（302 文件基线 sha 清单 `temp/diff-samples/baseline.sha256`），由 Computer Use 驱动剪映 11.6.0.14552 做 UI 操作，每次 Ctrl+S 后只读解密比对。逐条记录在 `temp/diff-samples/NOTES.md`，密文快照 `temp/diff-samples/enc-*.bin`。原草稿全程未动：`10月16日/draft_content.json` 与其时间线副本保存前后都是 `d4807d15…`。
- **Finding**：
  1. **画面侧「描边」是资源包效果，不是标量字段**（结案 U-39）。选「单层描边」+ 颜色 `#12AB34` + 大小 27 + 不透明度 60 后，`video_strokes[]` 从 5 键占位长成 `{…, resource_id, path, resource_name, source_platform:1, color, adjust_params[]}`；`color == [1.0, R, G, B]`（`0x12/0xAB/0x34 ÷ 255` 逐项吻合，**首位不是 alpha**）；`adjust_params` 里 `effects_adjust_size=0.27`、`effects_adjust_alpha=0.6`、`min_scale=320.0`（UI 不暴露）→ **UI 值 ÷100**，且 `default_value` 恰等于 UI 默认（10→0.1、100→1.0）。语料里「只有开关落盘」的真相是**类型仍选着「无」**。
  2. **等比缩放结案 U-42**：`on` 用「缺席」表示 true；`uniform_scale.value` 是 `x/y` 派生缓存，**只在等比开着时维护**（关掉时 102 个各向异性样本的 `value` 恒为 1.0）；切换等比**不改写 `clip.scale`**（UI 单滑杆读写 x，y 留旧值）；200% 落成 `1.9999999999999998`（按 old×200/130 算）。
  3. **新增一条写回不变式**：该片段带 31 条**单帧关键帧骨架轨道**（每个可动画属性一条，`keyframe_list` 长度 1、无 `time_offset`、控制点 `(0,0)`）。改 `clip.scale.x` 时 `KFTypeScaleX` 的帧值同步变化；等比关闭时应用**新建** `KFTypeScaleY` 轨道，恢复等比时又**删除**它。→ 只改标量字段不改骨架帧，就会与剪映不一致（语义未定，开 U-45）。
  4. **`styles[].range` 是 UTF-16 code unit**（结案 U-01）：`测试A😀B中🎉C` = 8 码点 / 10 code unit，整段样式的 `range == [0, 10]`；emoji 在 `content.text` 里**原样存**，不做代理对转义。
  5. **字号 1:1**（结案 U-26）：UI 13→24 同时写 `texts.font_size`（`13.0`/`24.0`）与 `content` 内 `styles[].size`（`13`/`24`），**两处都要同步**。
  6. **字幕位置只由 `texts.alignment` 承载**（U-30 部分）：点 6 枚对齐按钮的 13 次采样里，唯一变化的字段是 `alignment`，`clip.transform` 恒 `{0,0}`；观测到写入 `0`/`2`/`3` 与「键删除=缺省」，与语料域 `{0,1,2,3,4}+null`（6 状态 ↔ 6 按钮）吻合。**按钮↔取值未钉死**：Qt 面板无 accessibility 树、命中区约 25 px、注入落点有系统偏差。
  7. **两项阻塞**（U-27、U-28）：11.6 的文本面板**没有**发光/阴影/描边参数控件（`基础` 只有 字体/字号/样式/颜色/字间距/行间距/对齐/预设样式/位置大小；`气泡`/`花字` 是在线预设画廊）。草稿里那条发光是 `effects[CE685039] type=bloom name=轮廓光 panel_id="tool_text_glow"`，挂在文本片段 `extra_material_refs` 上 → 参数面板要先让特效资源面板出现。
- **Path**：`evidence/unresolved.md`（U-01/U-26/U-39/U-42 结案，U-30 收窄，U-27/U-28 改判定方法，新增 U-44/U-45/U-46）；`spec/picture.yaml`（描边、等比、骨架同步）；`spec/text.yaml`（range 单位、字号双写）；`spec/write-rules.md`（§1.3 实测副本清单 + 新不变式）。

## F-028 一次「打开→改→保存」的文件级足迹：15 改 24 增，另有 `.locked`

- **Evidence**：副本目录基线 302 文件 → 会话后 326 文件；`sha256sum -c baseline.sha256` 只有 **15** 项 FAILED，其余 287 项逐字节不变。
- **Finding**：已验证（一次真实会话的逐文件对照）。改动的 15 项 = `draft_content.json` 与 `.bak`、`template.tmp`/`template-2.tmp`（根 + 时间线双份）、`draft.extra`（根 + 时间线）、`draft_meta_info.json`、`draft_settings`、`draft_biz_config.json`、`agent_adoption_ledger.db`、`deepagent/deepagent.db`、`.backup/timeline_backup_manifest.json`。新增 24 项 = **`.locked`（草稿在编辑器中打开期间存在的锁标记）** + 18 份 `.backup/<时间戳>_<hash>.<load|save|close>.bak`，每个事件同时写 **3 个镜像位置**（`./.backup/`、`./.backup/<timeline_id>/`、`./.backup/projectBackUp/`），本次 6 事件 × 3 = 18；`projectBackUp` 的 hash 恒定（那是 `project.json` 的副本）。这把 F-025 的「普查下界」从推断变成实测：**只备份 `draft_content.json` 不够**，且 `.backup/` 会单调增长。

**关闭时间线的补充实测（2026-10-19）**：`.locked` 被删除，`.backup/` 三个镜像位各写一份 `<ts>_<hash>.close.bak`，而 `draft_content.json` **内容零变化**（与关闭前最后一次点击的快照逐字段相同，0 处差异），只是重加密：密文 sha `12d01d1d`→`7bd5bc7c`、长度仍是 63,536 B。这把 F-025 的判据从推理升级为直接观测——**等长而摘要不同 = 重加密熵，不是内容分叉**；反过来，任何「草稿被人改过」的判定都必须先解密比 content-id，只看 mtime 或密文 sha 会误报。

- **Path**：`spec/write-rules.md` §1.3（副本候选与事务边界）、`spec/layout.yaml`（`.locked` 与 `.backup` 事件命名）、`evidence/unresolved.md` U-17 加注、U-46（`.locked` 与写回的关系）。

## F-029 文本样式开关的载体与 `check_flag` 位表（25 个自动保存快照还原时序，逐位因果）

- **Evidence**：副本草稿 `差分样本 10月18日` 里 5 条字幕（原条 + 4 条拷贝各关若干开关）。用户手改、剪映自动保存，
  只读观察器把每一次落盘都留了密文快照（`temp/diff-samples/auto/`，25 份），逐份解密还原成操作时序；
  终态与逐条差分见 `temp/diff-samples/variants.json`、`temp/diff-samples/NOTES.md`。语料侧独立复核：
  `temp/corpus-scan/plain/` 里 **按 manifest 过滤后的 17,454 条**带整型 `check_flag` 的 text material（2,050 份冻结明文；原先误把 `plain/` 全部 2,078 份当分母，多出 623 条构造样本 → F-030），交叉表已落成 `tables/check_flag_carriers.csv`（由 `scripts/build_evidence_tables.py` 的 `check_flag_carriers()` 生成，可复算）。
- **Finding**：
  1. **三个开关位逐位因果成立**（每次翻转都与载体同步，共 8 次单向观测）：
     `bit3(8) ⟺ styles[].strokes[] 非空`、`bit5(32) ⟺ styles[].shadows[] 非空`（同时带 `texts.has_shadow`）、
     `bit6(64) ⟺ 片段 extra_material_refs 里引用了 effects[type=="bloom"]`。
     时序样例：`127→111→79→71`（关发光、关阴影、关描边各一次）、`127→111→47→39`、`127→119→55→23`。
     **U-28 结案**：bit64 就是发光开关，且关发光**不写任何 texts 字段**，只动 `check_flag` 与 effects 引用。
     `bit0/1/2(1+2+4)` 在全部 17,454 条里 100% 置位（值 4 只有 1 条例外：17,453/17,454），是恒置基位（U-04 关心的 +4 位在此无任何区分度）。
  2. **扁平字段不是载体，是恒写的遗留镜像**：5 条字幕的 `shadow_alpha/shadow_angle/shadow_color/shadow_distance/
     shadow_point/shadow_smoothing`、`border_color/border_width`、`background_color/background_style/
     background_round_radius`、`text_color` **逐项完全相同**，与三个开关的状态无关。
     权威载体只有 `styles[]` 内的数组与 `effects[]` 引用。读扁平字段判开关会一律得到「开」。
  3. **`texts.has_shadow` 是粘性近指标，不是开关**：语料 17,454 条里 `true`+有数组 12,081、`false`+无数组 3,512（这两类即一致，15,593 = 89.3%），
     **`true` 但没有 `shadows[]` 的 728 条**、`false` 却有权的 160 条、整键缺席 973 条（863 无数组 + 110 有权）（`tables/check_flag_carriers.csv`）→ 一致率约九成，判开关只能看 `shadows[]` 非空。
  4. **`bit4(16)` 是反例，登记为新 open**：本批有两次「只清 bit16、五个字段纹丝不动」（`127→111`），
     而它在语料里只有 129/17,454 = **0.74%** 置位、且在各样式分组里按组规模等比分布（与描边/阴影/发光无关）。
     → **`check_flag` 不是样式字段的纯函数**，不能当样式指纹用（U-47）。
  5. **同一数值两条路径精度不同**：UI 距离 5 在 `styles[].shadows[0].distance` 里是 `4.999999523162842`
     （float32 往返），在扁平 `shadow_distance` 里是精确 `5.0`。任何跨路径相等判定必须带容差。
  6. **换算复现**：描边 `styles[].strokes[0].width == 0.08` ↔ UI 40（÷500，第三个独立样本）；
     阴影 `alpha 0.9`↔UI 90%、`angle -45`↔UI -45°、`diffuse 0.025`↔UI 15%（×6 候选，仍单样本系数）；
     发光 `strength 0.5`↔UI 50、`range 0.4`↔UI 40（÷100 第二个同样本）。
     `strokes[0].mode` 仍是 `0`，本批没产生第二值 → **U-24 原地不动**。
  7. **发光没有角度控件**：11.6 的 `tool_text_glow` 面板只有 颜色/强度/范围 + 两枚预设瓦片，
     `dir_x/dir_y` 恒 0.5 且无输入口 → U-27 改判为「需要带角度控件的那个版本」（F-016 截图读的是四格 30/20/0°/0°）。
- **Path**：`evidence/unresolved.md`（U-28 结案、U-27 改判、U-24 不动、新增 U-47/U-48）；
  `spec/text.yaml`（`style_carriers` 块与 `has_shadow`）；`spec/panel-map.yaml`（描边/阴影/发光三组行改判扁平镜像 + 精度注）。

## F-030 `plain/` 的 28 份残留明文抬高了派生表分母（口径根因，2026-10-19）

- **Evidence**：`temp/corpus-scan/manifest.json` 去重后是 **2,050** 个内容键（`stats.json -> corpus.distinct_contents` 同数），
  而 `temp/corpus-scan/plain/` 实际有 **2,078** 份文件。差出的 28 份 mtime 分两批——27 份在 2026-10-15 15:30/15:31（r2 时代），
  1 份（`19797fc616f0b339`，15.17 s / 5 轨 / 27 条字幕，content-id `9DDA75B6…`）在 2026-10-16 13:28，即 r3 聚合完成 7 小时之后，
  来自 check-1016 那轮临时解密（与 `temp/check-1016/timeline_copy.json` 的 `507C0096…` 同草稿族、不同时间线）。
  **28 份全部是 11.6.0 写入的内容**，共带 814 条 text material，其中 623 条带整型 `check_flag`。
- **Finding**：任何「直接 glob `plain/`」的派生统计都会把这 28 份构造/临时样本算进分母，而它们不属于 r3 快照，
  等于让当前版本被系统性高估（与 `corpus-scan.md` 里「差分样本不计入使用频率」的口径冲突）。
  受影响的实测数字（错 → 对）：带 `check_flag` 的 text material **18,077 → 17,454**；
  `has_shadow=true`+有数组 **12,680 → 12,081**；整键缺席 **997 → 973**（863 无数组 + 110 有权）；
  `bit16` 置位 **140 → 129**（0.77% → 0.74%）。未受影响：3,512、728、160（残留里没有任何 `false` 行）。
  已修：`build_evidence_tables.py` 新增 `frozen_contents()`，派生表只认 manifest 里的 2,050 份，
  并在运行时打印「已排除 N 份非本快照的残留明文」；`check_flag_carriers.csv` 与新表 `alignment_by_version.csv` 都走这条通道。
- **Path**：F-029 的分母与三处数字按此改判；`unresolved.md` U-47/U-48 同步；`spec/text.yaml`、`spec/panel-map.yaml` 的分母同步；
  r4 重跑扫描时要按同样口径排除 `差分样本 *` 与这些临时解密（现在只是靠过滤补救，源头没清）。

## F-031 `texts.alignment` 的「居中」有两种落盘编码，按保存版本划界（U-30 结案，2026-10-19）

- **Evidence**：① 差分 E5——副本草稿 `差分样本 10月18日` 新建 6 条字幕、各点一枚对齐按钮，
  只读观察器留了 57 份密文快照（`temp/diff-samples/auto2/`），逐份解密看终态；
  ② 语料侧按 `last_modified_platform.app_version` 交叉统计，落成 `tables/alignment_by_version.csv`
  （43 行 = 2 个时代汇总 + 逐版本；r3 口径，`build_evidence_tables.py -> alignment_by_version()` 可复算）。
- **Finding**：
  1. **按钮 ↔ 取值**：左 = `0`、右 = `2`、上 = `3`、下 = `4`；**两枚「居中」按钮都不写值**——11.6 上点居中的结果是**整键消失**，
     且六次点击里 `segments[].clip.transform` 恒 `{x:0,y:0}` 不动。所以这是一个**单字段互斥枚举**，渲染器不能拆成 x/y 两轴，
     必须自己按取值算版面位置。
  2. **`1` 是老写入器的「水平居中」显式编码**（likely，非直接观测）：带键材料里 `1` 的占比按时代是
     ≤8.0 **7,147/7,369 = 96.99%**，≥8.7 **11/360 = 3.06%**，而 11.6.0 的 3,513 条字幕里 `1` = **0 条**（11 条残留全部来自 10.5.0）。
     反向证据是键的缺席率：≤8.0 时代 7,500 条只缺席 131 条（老写入器总写一个值），≥8.7 时代 13,586 条缺席 13,226 条（97.4%）。
     两时代的 `0/2/3/4` 都存在且都是少数，所以差异只在「居中怎么写」。
  3. **`absent` 与 `1` 是同一个版面状态**（居中）。渲染器必须两者都按居中处理：把 `1` 当成第三种位置会让老草稿（4.6.1–8.0.0，451 份）整体错位；
     反过来，写回时也不要把 `1` 规范化成删键——那会改变老版本剪映读到的值。
  4. **垂直方向没有「居中」编码**：域里只有 `3`=上、`4`=下，垂直居中同样靠删键表达 → `1` 只承载水平居中，不与 `3/4` 复合。
- **Path**：`spec/text.yaml` 的 `对齐方式` 行与 `style_carriers`；`spec/panel-map.yaml` 的 `对齐方式` 行；`unresolved.md` U-30 结案。

## F-032 位置的「整数 px ↔ 浮点」换算律：按该轴画布边长归一，且浮点冻结在写入当时的画幅（2026-10-19）

- **Evidence**：r3 冻结明文（按 manifest 的 2,050 份）里全部非零 `segments[].clip.transform.{x,y}`，
  对每个候选除数测「值 × 除数 是否精确落在整数上（容差 1e-9）」，按 (轨道类型, 轴, 画布尺寸) 分组落成
  `tables/position_quantum.csv`（30 行，`build_evidence_tables.py -> position_quantum()` 可复算）。
  直接锚点仍是 F-027 那一对：UI 位置 Y = `-850` ⟷ 存 `-0.4427083333333333`。
- **Finding**：
  1. **除数是「该轴的画布边长」**，不是固定的 1920（**注意：本条说的是「面板显示值 ↔ 存值」的算术，
     不是渲染位移；渲染位移是它的一半，见 F-035**）：`text.y` 在画布 1080x1920 上 52.09%（14,388 个非零值）
     满足 `y × 1920 ∈ ℤ`，在 1920x3414 上 64.59% 满足 `y × 3414 ∈ ℤ` 而同组按 1920 只有 8.99%。
     x 轴同理用 `canvas_config.width`。所以**面板显示值 = transform.x × width、transform.y × height**（原点在画布中心）。**注意这只管面板，不管渲染**：真实位移是它的一半、且 y 轴向上（F-035 已改判，本条原文曾据此写过「px = … 负=上」，是错的）。
  2. **是 double 精确，不是 float32 往返**：命中整数的那批偏差约 1e-15（`float32(k/D) == value` 只解释 6.9%），
     与阴影距离那种 float32 抖动（`4.999999523162842`）**不是同一回事** —— 位置没有经过 float32。
  3. **浮点冻结在写入当时的画幅上**，改画幅不会重写它：`text.y` 在 1080x1440 画布上只有 3.47% 满足 `× 1440 ∈ ℤ`，
     却有 46.35% 满足 `× 1920 ∈ ℤ` → 这些草稿是从 1080x1920 改成 3:4 的，存的仍是 `k/1920`。
     同一个浮点在新画幅下对应的像素是 `k × 1440/1920 = 0.75k`，**不再是整数**，UI 只能四舍五入显示 →
     这就是「草稿存 ±1 的浮点数、UI 显示整数、不同比例下有区别」的机制（不是标定基准变了，是显示被 round 了）。
  4. **x 轴的整数率远低于 y**：`text.x` 在 1080x1920 上只有 12.84% 整数，`video.y` 10.69% →
     水平位置大多不是手打像素（与 F-031「水平版面由 `alignment` 承载」吻合），画面侧则多为拖拽/自适应产生的自由浮点。
  5. **恢复出来的整数是干净的 UI 数值**：众数 `y = -850`（4,309 次）、`-800`（1,291）、`-900`（619）、`-700`、`-600`，
     3:4 画布的众数是 `-800`（227 次），1920x3414 是 `-1500`（193 次）→ 这些是面板里键入的整数，不是渲染中间量。
- **写回推论**：要保住「用户看到的整数像素」，必须按**当前** `canvas_config` 的对应边长归一化写入；
  读回显示值必须做 `round(value × 边长)`，且不能假设跨画幅草稿仍满足整数性（第 3 条）。
- **Path**：`spec/picture.yaml -> coordinates`（改写为实测律）、`spec/panel-map.yaml` 两处 `位置X/Y` 行、
  `spec/text.yaml` 的 `位置X/Y` 与 `calibration_leads`、`spec/write-rules.md` §3、`evidence/unresolved.md` U-08 结案 + 新增 U-49。

## F-033 成对观测钉死换算律：改画幅不重写浮点，面板整数是 round 出来的；画幅是**每条时间线各自**的（2026-10-19，结案 U-49）

- **Evidence**：用户新建草稿 `<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\10月19日 (2)`（专做这一步实验，不是语料的一部分），
  四条时间线同一份「默认文本」：01/03 是 9:16（1080×1920）、02/04 是 16:9（1920×1080）。
  只读解密每条 `Timelines/<id>/draft_content.json`（明文留档 `temp/px-probe/tl-<id8>.json`，草稿零写入），
  与面板截图逐条对照：

  | 时间线 | 画布 | 面板显示 | 存值 x | 存值 y | 存值等于 |
  |---|---|---|---|---|---|
  | 01 `FBF874A5`（= `main_timeline_id`，也是根镜像） | 1080×1920 | X 0 / Y -850 | 0.0 | -0.4427083333333333 | `0/1080`、`-850/1920` 精确 |
  | 03 `A25D69E0` | 1080×1920 | X 100 / Y -850 | 0.09259259259259259 | -0.4427083333333333 | `100/1080`、`-850/1920` 精确 |
  | 02 `75A0AA86` | 1920×1080 | X 0 / Y **-478** | 0.0 | **-0.4427083333333333（一字未改）** | 仍是 `-850/1920`；×1080 = -478.125 |
  | 04 `8244F958` | 1920×1080 | X **178** / Y -478 | 0.09259259259259259（未改） | -0.4427083333333333（未改） | 仍是 `100/1080`；×1920 = 177.777… |
- **Finding**：
  1. **F-032 的算术升级为直接观测**：面板显示值 = `x × canvas_config.width`、`y × canvas_config.height`，
     各轴用自己那条边（9:16 上面板 100 是 `100/1080`，不是 `100/1920`）。
     **但这条说的是面板算术，不是渲染位移** —— 位移是它的一半、且 y 轴向上，见 F-035。
  2. **改画幅不重写浮点**：02/04 的存值与 01/03 **逐位相同**，面板只是把同一个浮点乘上新边长再舍入显示：
     -478.125 → **-478**、177.7778 → **178** → 舍入规则是**就近取整**（两个方向的偏差分别是 0.125 与 0.222，都不是截断）。
  3. **画幅是 per-timeline 的**：同一份草稿里四条时间线两种比例并存（`canvas_config` 各写各的），
     根镜像只反映 `main_timeline_id` 那一条（这里是 9:16 的时间线01）。
     → 渲染与写回都必须按**目标时间线**取 `canvas_config`，用草稿级/根镜像的画幅会把 16:9 时间线的像素算错 1.78 倍。
  4. **面板整数不是真值，重键会被还原**（用户随即在同一草稿上做了这一步）：在 16:9 的时间线04 上把显示的 `178` 原样键回并等自动保存，
     存值从 `0.09259259259259259` 变成 `0.0925925925925926` —— **不是** `178/1920 = 0.09270833333333334`，
     而是回到 ≈`177.7778/1920`，即**内部浮点赢，面板显示的整数被丢弃**（用户描述为「位置会还原」）。
     两值相差 **1 个 ULP**，我用四条候选算式都没复现出这一位（`×1920/÷1920` 回环、`float32` 往返、显示整数回写、按 1080 重归一），
     所以「剪映怎么算出这一位」留作 U-50；**结论不依赖它**：写回侧绝不能把面板整数当目标值，否则每次触碰都漂 ≈0.22 px。
  5. 该 1-ULP 值又随新建的 3:4 时间线（1080×1440）继续传递：`x = 0.0925925925925926` → ×1080 = `100.00000000000001`，
     而 `y = -0.4427083333333333` 仍不变 → ×1440 = **-637.5 整**，正好落在 `.5` 上。面板读数（用户回报）：**X 100 / Y -638**
     → `100.00000000000001 → 100`、`-637.5 → -638`，**排除向零截断**，`.5` 是进位的（就近一侧）。
     「远离零」与「银行家舍入」在这一格给同一个答案，要分开需要 `-638.5` 这类样本，属 0.5 px 以内的边角问题（U-50 只剩这一条 + 那 1 个 ULP 的算式）。
- **Path**：`spec/picture.yaml -> coordinates`（补 per-timeline 与舍入规则）、`spec/layout.yaml`/`spec/write-rules.md` §3
  （画幅按时间线取、别把显示整数当存回值）、`evidence/unresolved.md` U-49 结案。

## F-034 `font_size` 不是字号权威，只是 92.9% 存在的镜像；权威是按段存取的 `styles[].size`（2026-10-19，更正 F-027）

- **Evidence**：r3 冻结明文 2,050 份里的 21,086 条字幕 material，逐条比较顶层 `font_size` 与 `content.styles[].size`，
  落成 `tables/font_size_mirror.csv`（8 行，`build_evidence_tables.py -> font_size_mirror()` 可复算）。
  触发这次复测的是 2026-10-19 的新样本 `10月19日 (2)`：四条时间线的「默认文本」`styles[0].size = 15.0` 而 **`font_size` 整键不存在**。
- **Finding**：
  1. **`font_size` 会缺席**：1,009 条（4.8%）没有 `font_size` 但有 `styles[].size`；另有 9 条两键都没有。
     所以「读 `font_size` 拿字号」在 1/20 的字幕上直接失败，新建的 11.6 字幕就是这一类。
  2. **两键都在时也不是恒等**：等于 `styles[0].size` 的 19,048 条、等于**其它段**的 232 条、与**所有段都不等**的 317 条（三者相加即两键都在的全集），
     另有 471 条反过来只有 `font_size` 而没有 `styles[].size`。
  3. **根因是分段样式**：2,381 条（11.3%）的 `styles` 有多段（`range` 给不同字符段不同字号），
     单个 `font_size` 表达不了一行里的多种字号 → 它只能是某一段的镜像（实测多为第一段），不是权威。
  4. **判读规则**：字号一律逐段读 `styles[i].size` + `styles[i].range`（range 单位是 UTF-16 码元，见 F-027/U-01），
     `font_size` 只当「整行统一字号时的快捷镜像」用，缺席与不一致都是正常态。
     这与 F-029 的扁平字段、F-031 的 `check_flag` 是同一类陷阱：**顶层单值键承载不了分段/开关的真实状态**。
- **Path**：`spec/text.yaml` 的字号行与 `style_carriers`、`spec/panel-map.yaml` 的字号行、`spec/write-rules.md` §3 的字号不变式、
  `evidence/unresolved.md` U-26 加注（317 条与所有段都不等，原因未解释）。

## F-035 导出实测推翻 F-032 的渲染解释：位移是 `v × 边长 / 2`、y 轴向上；面板单位是 2× 真实画布像素（2026-10-19）

- **Evidence**：用户导出 `10月19日 (2)` 的三条时间线（`X0 Y0.mp4`、`时间线 01.mp4`、`时间线03.mp4`，均 1080×1920 / 30 fps / 90 帧，
  黑底白字，`clip.scale` 恒 1.0、无 `global_scale`）。取第 45 帧，阈值 `luma>=200` 量墨迹包围盒，与存值逐条对照
  （`temp/px-probe/export-measure.txt`，脚本 `temp/px-probe/read_exports.py`）：

  | 导出 | 存值 x / y | 面板 X / Y | 墨迹中心（行, 列） | 相对画布中心 | 预测 `v × 边长/2` |
  |---|---|---|---|---|---|
  | X0 Y0 | 0.0 / 0.0 | 0 / 0 | (959.5, 539.0) | (−0.5, −1.0) | (0, 0) |
  | 时间线01 | 0.0 / -0.4427083333333333 | 0 / -850 | (1384.5, 539.0) | (**+424.5**, −1.0) | (**+425.0**, 0) |
  | 时间线03 | 0.09259259259259259 / -0.4427083333333333 | 100 / -850 | (1384.5, **589.0**) | (+424.5, **+50.0**) | (+425.0, **+50.0**) |
- **Finding**：
  1. **渲染位移 = 存值 × 该轴边长 ÷ 2**，不是 F-032 写的「× 边长」。x 分量 50.0 px 与预测**逐位相同**，
     y 分量 424.5 vs 425.0（差 0.5 px = 墨迹中心与 em 中心的固有差）。
  2. **y 轴向上为正**：`y = -0.4427` 把字推到中心**下方** 425 px → 之前记的「负=上」是反的，
     参考文档的「半画幅归一 + y 向上」这两条**本来就是对的**。
  3. **锚点 = 字框中心**（`X0 Y0` 的墨迹中心 959.5/539.0 就是画布中心 960/540），
     且 `alignment` 缺席=居中时整行以该点为中心（时间线03 的 X=100 面板值 → 真实右移 50 px，整行中心从 539 移到 589）。
  4. **面板单位不是画布像素**：面板显示值 = `v × 边长`（F-033 逐位验证过的算术），而真实位移是它的一半
     → **面板 1 个单位 = 0.5 个导出像素**。两种解释在本组数据里等价：① 面板按「半像素」显示；
     ② 剪映的设计空间是当前画幅的 2 倍（1080×1920 ↔ 2160×3840），导出到 1080×1920 时位移减半。
     用一次 2× 分辨率导出即可分开（U-51）。
  5. **字号→像素（U-07）第一次量出来**：size 15 的「默认文本」墨迹盒 86×363 px；用草稿自己记录的字体
     （`11.6.0.14552/Resources/Font/SystemFont/zh-hans.ttf`）逐 em 渲染比对，最佳匹配 **em ≈ 92~94 px → 6.2 px/字号单位**。
     独立复核：fixture `1012-1626`（size 10）的边缘拟合给出 62 px → 同系数 6.2。
     **参考文档的两个候选都不对**（`W/100` = 10.8、`W×0.00625` = 6.75），6.2 也不等于 1080/160=6.75；
     系数是否随画幅变（W=1920 时是 6.2 还是 11.0）还没测（U-52）。
  6. **第二个画幅复核（同一条时间线原地 9:16 → 16:9，导出 1920×1080）**：存值仍是 `100/1080` 与 `-850/1920`
     （面板按新边长显示成 X 178 / Y -478，F-033 的算术再次成立），而导出里墨迹中心落在 (行 778.0, 列 1048.5)，
     即 **+238.0 / +88.5**，与「值 × 边长 / 2」的预测 +239.1 / +88.9 吻合（≤1.1 px），
     「值 × 边长」的预测 +478.1 / +177.8 被整整 2 倍否掉 → **F-035 的渲染律在两种画幅下都成立**。
  7. **em 随画布宽度线性缩放**：同一份 `size=15` 的「默认文本」墨迹高 86 px（9:16）→ 153 px（16:9），
     比值 **1.779 ≈ 1920/1080**；于是 em/size = 6.20 @W=1080、11.02 @W=1920，两点过原点 →
     **`em_px = size × width × 0.00574`**（U-52 结案）。参考文档的 `W×0.00625` 方向对（随宽缩放）但系数偏 9%，
     `W/100` 完全不对；0.00574 的「漂亮形式」仍未定（U-07 只留这一条）。
- **根因（我错在哪）**：F-032/F-033 的「px = v × 边长」是从**面板值与存值之间的精确算术**反推的，
  那个算术本身没错（`100/1080`、`-850/1920` 逐位成立），但我把「面板单位」当成了「画布像素」，
  并且**从未与一次真实渲染对过**。方向（负=上）同样是从截图位置脑补的。
  → 教训：**凡是渲染语义的结论，必须至少过一次真实渲染**；这正是渲染基底 spike 该产出的第一件东西。
- **Path**：`spec/picture.yaml -> coordinates`（按本条重写）、`spec/panel-map.yaml` 两处 `位置X/Y` 行、
  `spec/text.yaml` 的 `位置X/Y` 行与 `calibration_leads`、`spec/write-rules.md` §3 位置不变式、
  `evidence/unresolved.md`（U-08 的结论改判、U-07 收窄、新增 U-51/U-52）。

---

## F-036 渲染基底 spike 的字形轴：三种基底对同一条导出都落在 ≤2 px 墨迹盒，选型不受字体渲染约束（2026-10-19）

- **Evidence**：ground truth = 桌面 `X0 Y0.mp4` 第 45 帧（画布 1080×1920、黑底白字「默认文本」、
  `styles[0].size=15`、`transform` 0/0），墨迹盒 **高 86 宽 363**，`luma>=200` 白像素 9645。
  三个候选用**同一份**草稿记录的字体 `11.6.0.14552/Resources/Font/SystemFont/zh-hans.ttf` 各画一次
  （脚本 `temp/px-probe/spike_base.py`，全部行值在 `temp/px-probe/spike-report.txt` / `spike-result.json`）：

  | 基底 | em | 四边偏差（上/下/左/右） | 质心偏差 | 整帧 RMSE | 字迹区 RMSE | 单帧墙钟 | 峰值内存 |
  |---|---|---|---|---|---|---|---|
  | PIL/numpy | 94 | 0 / 0 / -1 / +2 | 0.5 / -0.4 px | 3.05 | 22.35 | 5 ms | 54 MB |
  | headless Chrome canvas2d | 94 | 0 / 0 / -1 / +2 | 0.5 / -0.3 px | 2.86 | 20.93 | 609 ms | 594 MB |
  | headless Chrome DOM 文本 | 94 | 0 / 0 / -1 / +2 | 0.5 / -0.3 px | 2.86 | 20.93 | 629 ms | 546 MB |

  最佳 em 都是 94（扫 90/92/93/94/95/96），且 em 律在第二个画幅上独立复核：9:16 拟合最优 em 93.0
  → k=0.005741，16:9 最优 em 166.5 → k=0.005781，两画幅系数一致到 0.7%。
- **Finding**：
  1. **字形保真不构成选型轴**。三个基底对真实导出的墨迹盒偏差都在 2 px 内、字迹区 RMSE 相差 1.4 以内，
     所以「不用原生引擎就画不像剪映」这个担忧是错的；剩下的差别只在混合模式/蒙版/解码（见 `base-selection.md` 要求 1/2/3/4/5）。
  2. **canvas 与 DOM 逐行同分**（同一次扫描里 90/92/94/96 四个 em 的墨迹盒完全一致）→ Chrome 内部是同一套
     Skia 光栅，网页编辑器里字幕层选 DOM/CSS 还是 canvas 绘制，只影响实现便利性，不影响与剪映的像素一致性。
  3. **headless Chrome 不该当渲染服务器**：每帧冷启动 ~0.6 s、驻留 ~590 MB，而字形上并不比 PIL 好。
     它的正确位置是 M2 的标定仪（截图比对）与页面自动化。
  4. 墨迹高度对 em 是量化的（1 px 高 ≈ 1.5 px em），所以 em 92~95 都能对上 86 px 高；
     引用系数时要带上这个带宽，别把 0.00574 当成精确值。
  5. 踩到的环境坑：Chrome 的 `--user-data-dir` 给**相对路径**时会被丢掉并回落到用户真实 profile，
     于是进程附着到已开的浏览器会话、退出码 21 且什么都不渲染 —— 本地渲染必须用绝对 profile 路径。
- **Path**：`base-selection.md` 的 §spike 结果 与 §决定；`spec/text.yaml -> em_px_formula_status`；
  `evidence/unresolved.md` U-07 的带宽改写 + 新增 U-53（浏览器侧解码指标仍未测）。

---

## F-037 「服务端解码路线不可接受」是口径错误：PIL+ffmpeg 管道比 MLT 低一个数量级（2026-10-19；本条原始数字 0.08 GB / 10.7 ms 已由 F-039 更正为 233~606 MB / 26.3~55.3 fps）

- **Evidence**：`temp/px-probe/spike_footage.py` —— 从 fixture 的 4K 素材（3840×2160，4.2 s）连续取
  30 帧，ffmpeg 子进程管道输出 `scale=1080:1920:force_original_aspect_ratio=decrease + pad` 的 rgb24，
  Python 侧逐帧 `Image.frombytes` → `alpha_composite` 叠一层字幕。
  结果（**数字已由 F-039 就地更正**）：同一通道按均值/进程树重测 = 读均值 27.1 ms + 合成均值 8.6 ms、
  **稳态 26.3 fps**、**进程树（含 ffmpeg 本体）峰值 606 MB**；原先写的「中位 5.1+5.6 ms、80 MB」里，
  中位数把管道阻塞帧藏掉了、80 MB 又漏算了 ffmpeg。出处 `temp/px-probe/pipeline-rate.txt`。
- **Finding**：`base-selection.md` 要求 6 原先写「**服务端解码路线**已知不可接受（4.9 fps）」，那是拿
  **MLT 会话**的量级（230 ms/帧、11.4~13.6 GB 常驻）当成服务端路线的全体。同一台机器、同一份素材上
  ffmpeg 管道 + PIL 合成是它的一个数量级之外的好结果（606 MB 对 11.4~13.6 GB），所以该否决的是 MLT
  （以及任何「整条时间线常驻解码器」的图），不是服务端出图本身。校验通道（无浏览器、agent 侧出 PNG）据此成立。
  **但达标不等于够用**：4K HEVC 只有 26.3 fps，追不上 30 fps 连续预览，见 F-039 第 3 条。
  **（口径已由 F-042 更正）**：26.3 是**软解上限**，同一素材 `-c:v hevc_cuvid` 实测 125.8 fps；
  且这批数当时用的裸 `ffmpeg` 现已不在 PATH 上，重跑必须先 pin 二进制绝对路径。
- **根因（我错在哪）**：把「唯一试过的服务端实现」当成了「服务端实现的类别属性」写进硬要求，
  并且那句 4.9 fps 来自 memory 里的 MLT 时代结论，落笔时没有重新测一条替代实现。
- **Path**：`base-selection.md` 要求 6 改写 + §决定（双通道）。

---

## F-038 浏览器解码轴实测：首帧/实时/10 分钟浸泡全达标，深跳 seek 267~278 ms 超阈值，HEVC 一行像素都没出（U-53 部分结案，2026-10-19）

- **Evidence**：`temp/px-probe/media_server.py`（只绑 127.0.0.1、白名单根、GET/HEAD、支持 `bytes=` 区间并逐条记日志）
  喂 fixture 素材，`temp/px-probe/decode-probe.html` 用 `requestVideoFrameCallback` 打点，
  `temp/px-probe/run_browser_probe.py` 起 headless Chrome 并按秒采样**进程树** RSS。
  行值 `temp/px-probe/browser-report.jsonl`（**17:07:56~17:08:45 那轮，分母已修正**）与
  `browser-report-1.jsonl`（17:06 归档，含浸泡行），取数日志 `media-server.log` / `media-server-1.log` / `soak-run.log`。
  环境：HeadlessChrome 155.0.0.0、12 核、`VideoDecoder` 存在，但 `--disable-gpu` →
  WEBGL unmasked renderer 是 `ANGLE (Microsoft, Microsoft Basic Render Driver … Direct3D11)`，即**软件光栅**。
  `VideoDecoder.isConfigSupported`：`avc1.640028` ✓、`avc1.f40028`（High 4:2:2 10bit）✓、`avc1.f40034`（10bit 4K）✓、
  **`hvc1.1.6.L93` ✗、`hvc1.2.4.L153` ✗**、`vp09` ✓、`av01` ✓。

  | 素材 | 编码 | 首帧 | 连续播放（按实际播放窗） | 丢帧 | seek 中位（8 跳） |
  |---|---|---|---|---|---|
  | `b168bb76.mp4` 0.7 MB | H.264 High 8bit 1080x1920 30p 1.57s | **85.2 ms** | 46/47 帧 / 1,566 ms = **29.38 fps** | 0 | 25.0 ms |
  | `20261012_104307.mp4` 32 MB | HEVC Main 8bit 3840x2160 60p 4.2s | **无**（`0x0`，0 帧） | 0 | — | 0.4 ms（**无渲染的假数**） |
  | `C7459.MP4` 269 MB | H.264 High 4:2:2 **10bit** 1920x1080 60p 28s | 96.8 ms | 148 帧 / 2,459 ms = **60.18 fps**，realtime 0.981 | 0 | **266.7 ms** |
  | `C7463.MP4` 1.6 GB | 同上 220s（4 次**深跳**） | 110.2 ms | **59.69 fps**，realtime 0.977 | 0 | **278.2 ms** |

  浸泡（`browser-report-1.jsonl` 第 9 行 + `soak-run.log`）：600.2 s、**596 次 seek**（每秒 +0.7 s）、presented 2,293 帧、
  total 21,819 帧、**丢帧 8**；Chrome 进程树**峰值 RSS 956 MB（0.93 GB）**。
  Range 侧：每条媒体 GET 都带 `bytes=<start>-` 并回 206，1.6 GB 那份**从未被完整取回** —— 单条实发最多 103,809,024 B，
  多数在 22,282,240 B 量级就以 `aborted=ConnectionResetError/ConnectionAbortedError` 结束（播放器主动掐连接是常态，不是故障）。
- **Finding**（对着 `base-selection.md` 的阈值逐条判）：
  1. **首帧 ≤300 ms：过**。85.2~153.5 ms（两轮各四次命中，含 1.6 GB 深跳素材）。
  2. **连续播放 ≥24 fps：过**。30p 素材 29.38 fps、60p 素材 60.18/59.69 fps 且 `realtime_factor` 0.977~0.981、丢帧 0；
     10 分钟浸泡只丢 8 帧。
  3. **seek ≤150 ms：不过（真实素材）**。短素材 25.0 ms 达标，但 269 MB/28 s 是 266.7 ms、1.6 GB 深跳 278.2 ms，
     上一轮复现值 269.3/282.4 → **约 0.3 s 的拖动延迟是这条链的固有量级**，靠 `<video>` 原生 seek 达不到阈值；
     要走 mediabunny 解封装 + WebCodecs 自建按关键帧 seek，或把交互改成「预取邻近帧」。
     **（F-045 已定案）**服务端两条候选（允许 HTTP 缓存、钳短开区间预取）实测都不改中位延迟 ⇒ 只能在播放器里解决。
  4. **10 分钟会话 ≤2 GB：过**。0.93 GB 峰值（软件光栅下的保守读数），比 MLT 时代的 11.4~13.6 GB 低一个数量级。
  5. **10-bit 不是问题**：High 4:2:2 10bit 在浏览器里实时解码（`isConfigSupported` 与实解一致），比预期好。
  6. **HEVC 是硬缺口**：`isConfigSupported` 两种 profile 都 false，实解 `videoWidth×videoHeight = 0x0`、零帧 —— 但**demux 正常**
     （duration 4.213 s 照读）。⇒ 降级路线（服务端 ffmpeg 预转码 / ffmpeg.wasm 兜底）从「风险」升为**必须有实现项**（新增 U-54）。
     **（本条已被 F-044 推翻）**：假阴性有两个独立成因——`--disable-gpu` 关掉硬件通路，且 `description` 传的是
     4 字节假值 `00 00 00 01`。用文件里取出的真 hvcC 在带 GPU 的 Chrome 里重测，四个 `hvc1` 串全 True、
     `<video>` 真解出 241 帧 ⇒ 降级从「必须实现」降为「边界处理」。
  7. **两个读数的坑**：① HEVC 那行的 seek「0.4 ms」是**没有任何渲染**时 `seeked` 立即触发的假数，不得当 seek 证据；
     ② `soak-samples.json` 现在的内容是**后一次 49 s 全量跑**的采样序列（峰值 731 MB），浸泡的 956 MB 只在 `soak-run.log` 里 ——
     两者都叫「峰值」但不是同一次运行，引用时必须带运行号与时间窗。
  8. **本轮全部数字都在 `--disable-gpu`（软件光栅）下测得**：它只会让首帧/seek/内存**偏悲观**，
     所以第 3 条的「不过」需要在带 GPU 的真实浏览器会话上复测才能定案（已写入 U-53 残留）；
     第 6 条的 HEVC 阴性**同样可能被 `--disable-gpu` 关掉了硬件解码通路而加重**，不能据此断言「Chrome 永远解不了 HEVC」。
     **（已定案，F-043/F-044）**：同一套 headless 探针去掉该 flag 就能带 GPU（ANGLE 报 GTX 1650），不必等真实浏览器会话；
     `--disable-gpu` 那一列现在只作**下界**引用。
- **根因（口径错法，与 F-019/F-030/F-037 同类）**：第一版探针把 `delivered_fps` 的分母取成**整条 5.5 s 采样窗**，
  于是 1.567 s 的素材被算成 8.34 fps，看起来像「不达 24 fps」；改成按**实际播放窗**归一（补 `window_ms` 与 `realtime_factor` 两列）后是 29.38 fps、丢帧 0。
  → 教训：**指标必须写明分母**，否则一条 1.5 秒的素材能被自己的统计口径判死。落盘顺序也因此改成
  「先修分母、再跑全量」，两处 jsonl 因此分属不同口径。
- **Path**：`base-selection.md` §未测 → 新「已测：浏览器解码轴」小节 + 要求 4/5/6 的判据状态 + §定案（路线 A 的生效条件收窄为「seek 与 HEVC 降级」两项）；
  `evidence/unresolved.md` U-53 改写为「已测部分结案 + 残留（seek、带 GPU 复测、真 NAS、MOV）」并新增 U-54（不支持编码的降级验收）；
  `spec/format-reference.md` §10 的浏览器解码轴一行。

---

## F-039 更正 F-037 的两个数字：80 MB 漏算了 ffmpeg，10.7 ms 是把中位数当成了速率（2026-10-19）

- **Evidence**：`temp/px-probe/spike_pipeline_rate.py` 重测同一通道（60 帧窗口、报均值与 p50/p90、
  进程树含 ffmpeg 本体），出处 `temp/px-probe/pipeline-rate.txt`：

  | 素材 | 首帧管道 | 读均值 | 合成均值 | 稳态 | 进程树峰值 | ffmpeg 自报 |
  |---|---|---|---|---|---|---|
  | HEVC 4K60 | 208.8 ms | 27.1 ms | 8.6 ms | **26.3 fps** | **606 MB** | 0.405× 实时 |
  | H.264 10bit 1080p60 | 217.5 ms | 6.8 ms | 11.3 ms | 48.6 fps | 327 MB | 2.09× |
  | H.264 8bit 1080x1920 30p | 78.8 ms | 4.7 ms | 9.1 ms | 55.3 fps | 233 MB | 25.9× |

- **Finding**：
  1. **F-037 的 80 MB 只统计了 Python 进程**：采样函数取的是 `python.children()`，而 ffmpeg 是 `Popen` 的
     **本体**而不是子进程，于是 300~600 MB 的解码器常驻被整个漏掉。改成语义正确的采样后是 **233~606 MB**。
  2. **10.7 ms/帧不成立**：`ff.stdout.read()` 的分布是双峰的（管道里有帧就 ~3-5 ms，没有就整块阻塞），
     中位数把阻塞帧的成本藏掉了。按均值/墙钟算，**HEVC 4K 只有 26.3 fps**，即软件解 4K HEVC 追不上 30 fps。
  3. 结论修正但方向不变：服务端通道仍在 2 GB 天花板内（606 MB 对 MLT 的 11.4~13.6 GB），
     但**不能声称「~90 fps 稳态」**；且 4K HEVC 时间线的服务端连续预览到不了 30 fps，
     需要代理片或降分辨率解码 —— 与 F-038 第 6 条（HEVC 硬缺口）在浏览器侧的结论是同一个素材问题的两面。
- **根因（我错在哪）**：一是**把采样对象选错了进程**却没核对「谁在真正吃内存」；二是**用中位数代替吞吐**，
  对一个双峰分布的阻塞读尤其致命。→ 规矩：**管道/异步读数一律先报均值与墙钟，再报分位数**；
  内存必须报**进程树**并写明包含哪些进程。
- **Path**：`base-selection.md` 要求 6 与 §定案 第 2 条（数字就地更正）、`evidence/findings.md` F-037。

---

## F-040 浏览器解码轴的体积口径：Range 取块占比、`no-store` 反复重取与 seek 的成因（2026-10-19，U-53）

> 与上一条 **F-038 是同一次测量**：F-038 记判据读数与分母口径的根因，本条补它没有的**服务端字节账**
> （每条素材取回整片的百分之几、被播放器掐断的请求数）与 seek 的**取块成因**。
> 两条都是 2026-10-19 并发写入时留下的编号冲突，就地把我这条改成 F-040、**未改动 F-038 一个字**。

- **Evidence**：`temp/px-probe/` 的三件套 —— `media_server.py`（127.0.0.1 白名单只读、Range/206、`POST /report` 落盘）、
  `decode-probe.html`（`?autostart=1` 自动跑 env+codecs+probe+soak）、`run_browser_probe.py`（自起 headless Chrome、
  绝对 `--user-data-dir`、每秒采样进程树 RSS）。汇总出处 `temp/px-probe/browser-probe-report.txt`，
  逐行原始值 `browser-report.jsonl` + `media-server.log`。被测素材 = fixture 里 4 份真实片。
  环境：HeadlessChrome/155、12 逻辑核、GPU 渲染器 `ANGLE (Microsoft Basic Render Driver … D3D11)`（**软件光栅，无硬件解码器**）。

  | 素材 | 编码 | 首帧 | 连续播放 | seek 中位/最大 | 备注 |
  |---|---|---|---|---|---|
  | b168bb76.mp4 | H.264 High 8bit 1080x1920 30p 0.7 MB | 85.2 ms | 29.38 fps 丢帧 0 | 25 / 29.2 ms | 30p 片实测就是 30p |
  | 20261012_104307.mp4 | HEVC Main 8bit 4K60 32 MB | **无首帧** | 0 fps | 0.4 / 2.4 ms | `intrinsic 0x0`，**不报错**，却把整片 32.5 MB（104.9%）拉完 |
  | C7459.MP4 | H.264 High 4:2:2 **10bit** 1080p60 269 MB | 96.8 ms | **60.18 fps 丢帧 0** | 266.7 / 378.6 ms | seek 超阈值 |
  | C7463.MP4 | 同上 220 s 1.6 GB | 110.2 ms | 59.69 fps 丢帧 0 | 278.2 / 286.5 ms | 深跳可用 |

  WebCodecs `isConfigSupported`：`avc1.640028` / `avc1.f40028` / `avc1.f40034`(4K 10bit) / VP9 / AV1 = **true**；
  `hvc1.1.6.L93`、`hvc1.2.4.L153` = **false**。浸泡 600.2 s、596 次 seek：解码 21819 帧、丢帧 8（0.04%），
  进程树峰值 RSS **956 MB**，内存轨迹 773 MB(1s) → 806 MB(6s) → 358 MB(605.7s)，**没有增长**。
  Range：C7463 用 6 个请求取到整片的 16.4%，12 个请求的 C7459 取到 116.9%（反复 seek 会重取，因为服务端发 `no-store`）。
- **Finding**：`base-selection.md` 的六条浏览器侧阈值，判据结果如下。
  1. **首帧 ≤300 ms：达标**（85~110 ms；metadata 11~35 ms）。
  2. **连续播放 ≥24 fps：达标**，1080p60 的 10-bit 4:2:2 也能满帧 60 fps 且零丢帧（软件解码路径）。
  3. **10 分钟会话 ≤2 GB：达标**，单路视频 0.93 GB 峰值且内存回落，无泄漏迹象。
  4. **seek ≤150 ms：不达标**。小片 25 ms 过关，269 MB/1.6 GB 的相机片**中位 267/278 ms、最大 378 ms**。
     成因不是网络而是取块策略：Chrome 每次 seek 发 `bytes=<offset>-`（开区间）并无上限预取，
     服务端日志里 12 个请求有 11 个是被播放器**主动掐断**的。要达标必须自己掌握关键帧索引
     （mediabunny 的 sample table）或预生成代理片，而不是让 `<video>` 裸奔（转 U-55）。
  5. **编码支持率：H.264 全档可用**（连 10-bit 4:2:2 都能解，这条推翻「浏览器只吃 8-bit 4:2:0」的常见假设）；
     **HEVC 在本机软件路径完全不可用**，而且是**静默失败**：拿到 metadata、不触发 `error`、`videoWidth=0`、0 帧，
     同时把 32 MB 整片下载完。这正是要求 5 警告的「静默黑帧」，必须先落一条显式降级判定（转 U-54：
     有 GPU 的真实浏览器里 HEVC 是否可用，本会话未测）。**（F-044 结案：能解，本条阴性是探针传参与 flag 的假阴性）**
  6. **Range 流式：达标**（206 + 任意偏移深跳可用，1.6 GB 片只取 16.4%）。NAS 的**时延**这一腿没量：
     本会话的工具策略拒绝访问 `X:` 网络盘（转 U-56）。**（F-046 结案：`X:` 后续可读，成对实测——连续播放零退化、
     seek 只是加性上涨 +24~27%、首帧 2.7 倍破 300 ms 阈值 → 转实现项 U-59）**
- **Path**：`base-selection.md` §spike 结果（新增浏览器解码轴）与 §定案（改成带条件的结论）、
  `evidence/unresolved.md` U-53 结案 + 新增 U-54/U-55/U-56。

---

## F-041 目录口径重排到 r3 时，暴露出「有 `Timelines/` 却枚举不到时间线副本」的 120 个草稿（2026-10-20，新开 U-57）

- **Evidence**：把 `temp/corpus-scan/manifest.json`（r3 冻结，2,450 条记录 / **1,475** 个不同 `draft` 目录）按目录重新归类，
  再与 `stats.json -> corpus`（`content_files` 2,215 / `distinct_contents` 2,050 / `layouts` 1,028-831-191 /
  `content_multiplicity` 1,887-162-1）与 `temp/corpus-detail/root_flags.csv`（`is_minimal_draft=True` 278、
  `render_index_track_mode_on` 1,978/63）对齐，逐条比对文档里在用的数字。判据取自 `corpus_scan.py -> enumerate_corpus`：
  目录含 `Timelines/` 时逐 `Timelines/<sub>/draft_content.json` 记 `hybrid`，根文件另记 `hybrid-root-mirror`。
- **Finding**：
  1. **文件口径是 hybrid 1,033 / legacy 833 / 根镜像 349**（合计 2,215），文档此前写 1,034/833/**348** —— 两个分法总数相同、
     差在把一份镜像错记成了时间线副本，属手抄而非重算；`layout.yaml` 的 349 反倒一直是对的。
  2. **目录口径 1,475 = legacy 833 + 含 `Timelines/` 407 + 无内容 235**；407 里 349 个有根镜像、58 个只有时间线副本
     （此前文档写 348/59，同样差 1）。`layout.yaml` 头部那批 r2 值（1,531 目录 / 463 含 Timelines / 2,216 文件 / 2,052 内容）已就地重排。
  3. **新事实**：那 407 个中只有 **229** 个能枚举到 `Timelines/<id>/draft_content.json`，另 **120** 个只出现根镜像记录 ——
     即「建了 `Timelines/` 但里面没有任何按当前候选名可枚举的副本」。这是 F-025 副本普查下界的**第二个**来源，
     直接影响 M3 写回选址（按现在的面名去找活动副本会整批漏掉）→ 新开 U-57，判定只要对 2~3 个目录只读列一层 `Timelines/`。
  4. 顺带把同族的 r2 残留改到 r3 并注明分母：`is_minimal_draft` 278/2,050（13.6%，原写 2052/13.5%）、
     `render_index_track_mode_on` 1,978/63（原写 2052 份里 1980/63）、`content_multiplicity` 1,887/162/1（原写 1890/160）、
     根镜像独有内容 191（`layout.yaml` 原注释 192）、`write-rules.md` §1 第 4 条的「698 份内容」标为 r1 翻倍口径。
     `spec/keyframes.yaml` 的 8,395/2,869 **没有**重测，只把分母标注成 r2（不能一边引用旧测量一边写新分母）。
- **根因（我错在哪）**：F-020 的 r3 重跑只重排了**频次表**（bucket / 键 / 枚举），目录与副本普查被认为「结构性的、不会变」而没跟着重算；
  于是 layout 族数字停在 r2，且 hybrid/根镜像的分栏在某个文档里被手工凑成总数对上，误差 1 就此留在体系里。
  → 规矩：**凡是「按目录 / 按文件 / 按内容」三口径并存的计数，重排时必须三口径一起从 manifest 重算**，
  并让 `check_doc_counts.py` 能读到 `manifest.json`（本轮已加入 EVIDENCE_FILES），别靠总数对得上就放行分栏。
- **Path**：`spec/layout.yaml`（头部、`layout_detection.kinds.hybrid`、`file_counts_by_layout`、`minimal_drafts`、`root_mirror`）、
  `evidence/corpus-scan.md`（结果表与目录级分布）、`evidence/findings.md` F-004/F-007/F-015、`spec/write-rules.md` §1、
  `spec/keyframes.yaml` 分母标注、`evidence/unresolved.md` 新增 U-57、`spec/format-reference.md` §1/§10、
  `scripts/check_doc_counts.py`（证据集加 `manifest.json`）。

---

## F-042 服务端解码后端的真实依赖：PATH 上没有 ffmpeg，NVDEC 只认显式 `*_cuvid`，qsv 会挂死（2026-10-20，为 S10 帧工具定后端）

- **证据等级：已验证**（同一通路 3 次重复 + 两个独立实现〔自带 ffmpeg.exe / PyAV〕交叉）。
- **Evidence**：`temp/px-probe/run_decode_backend_probe.py`（每条通路重复 3 次，报中位与最小/最大；
  输出 `temp/px-probe/decode-backend.txt` 与 `decode-backend.json`）。
  环境清点：`shutil.which("ffmpeg")` = **None**，而 PATH 里那条
  `…\WinGet\Packages\Gyan.FFmpeg_…\ffmpeg-8.1.2-full_build\bin` 目录**已不存在**；
  可用的是剪映自带 `<JY_INSTALL>\11.6.0.14552\ffmpeg.exe`，版本串
  `ffmpeg version 21.7.0-9c087b133d`，configure 含 `--disable-ffmpeg --disable-ffprobe`（**同目录没有 ffprobe**）但 CLI 实测可跑；
  Python 3.14.5 + **PyAV 18.0.0**（libavcodec `(62, 28, 102)`）；GPU `NVIDIA GeForce GTX 1650, 610.88, 4096 MiB`；
  CPU i5-12400F（**无核显**）。素材 pin 绝对路径：`<DRIVE_E>/fixtures\1012-1626-fixture\media\20261012_104307.mp4`
  （HEVC Main 8bit 3840x2160 60p，取 80 帧）与 `…\C7459.MP4`（H.264 High **4:2:2 10bit** 1920x1080 60p，`-ss 2` 起取 200 帧）。

  | 通路 | 中位 fps | 重复区间 | ffmpeg 自报 fps | 峰值 maxrss |
  |---|---|---|---|---|
  | 软解 4K HEVC（默认解码器） | 23.5 | 23.3~26.8 | 24/23/27 | 717,796 KiB |
  | `-hwaccel cuda` | 27.7 | 26.9~28.1 | 27/28/28 | 874,836 KiB（stderr `Failed setup for format cuda` ⇒ **实为回落软解**） |
  | `-c:v hevc_cuvid`（NVDEC） | **125.8** | 124.6~126.4 | **0.0（自报数不可用）** | 627,308 KiB |
  | `-c:v hevc_qsv` | — | 120.013 s 被脚本超时杀掉（`Error initializing a MFX session: unsupported (-3)` 之后**挂住**） | — | — |
  | 软解 1080p60 10bit | 223.0 | 221.0~230.7 | 0.0 | 328,184 KiB |
  | `-c:v h264_cuvid`（4:2:2 10bit） | — 快速失败 `not supported`，rc=4294967274，0.22 s | — | — | — |
  | PyAV 软解 4K HEVC | 24.4 | 23.7~24.5 | — | — |
  | PyAV 软解 10bit | 254.8 | 248.4~258.3 | — | — |

- **Finding**：
  1. **硬解可用，但只认显式解码器名**。`-hwaccel cuda` 在本机初始化失败并**静默回落软解**，回落后的速率与软解同区间
     （23.3~28.1）——只看退出码和速率会误判成「已经在硬解」。这是**静默降级**的第二例（第一例是 F-038 第 6 条 HEVC 在浏览器里静默黑帧）。
  2. **4K HEVC 软解天花板约 24 fps**（自带 ffmpeg 23.5 与 PyAV 24.4 同量级），
     所以 `base-selection.md` 硬要求 6 里「只有 26.3 fps，够不到 30 fps 连续预览」这句**只对软解成立**：
     加 `-c:v hevc_cuvid` 后是 125.8 fps（**5.4 倍**），解码侧不再是瓶颈。
  3. **10-bit 4:2:2 不能硬解**（cuvid `not supported`），但软解本身已 223~254 fps，根本不缺算力
     ⇒ 路由规则是**按 profile 选通路**（HEVC→cuvid，10-bit 4:2:2→软解），不是一律硬解。
  4. **qsv 在本机是死路，且不是快速失败**：MFX init 报 unsupported 之后进程挂到脚本 120 s 超时才被杀。
     任何「按退出码逐条试」的降级逻辑都会先卡两分钟 ⇒ 后端必须用**白名单**列可用通路，禁止运行时逐个试错。
  5. **依赖真相**：服务端出图通道**不依赖 PATH 上的 ffmpeg**（现在根本没有）。F-036/F-037 那批速率是在当时 PATH 上还
     存在的 ffmpeg 8.1.2 full build 上取的，该安装已消失，旧 spike 脚本调的是裸 `ffmpeg`，**按现状直接重跑会失败**。
  6. **两个读数坑（同 F-038 第 7 条族）**：`-c:v *_cuvid` 与高码率快解路径上，ffmpeg 末尾 stats 行的 `fps=` 自报 **0.0**，
     只有按 `bench: rtime` 计算的速率可信；而首跑（单跑、冷缓存）与复跑差 47%（18.2 vs 26.9），单次读数不可用。
- **根因（口径错法，与 F-019/F-030/F-037/F-038 同类）**：F-036/F-037 的速率取自**一次性手敲的裸 `ffmpeg` 命令**，
  既没记二进制绝对路径与版本串，也没做重复次数，等到要复用时才发现依赖已经消失、且首跑复跑差一半。
  → 规矩：**速率数必须同时落 (a) 二进制绝对路径与版本串、(b) 重复次数与区间、(c) 分母口径（解码上限 `-f null` vs 端到端管道）**，
  缺任一项不得进选型依据。本轮 harness 已把三项写进输出。
- **Path**：`base-selection.md` 硬要求 6 的「26.3 fps」句改为分软解/硬解两行、§依赖清单 增「pin 绝对路径的 ffmpeg.exe + PyAV 备胎，
  非 PATH 依赖」、§风险 增 qsv 挂死与 cuvid profile 限制；`evidence/toolchain.md` §2 运行时表补 PyAV 与 ffmpeg 实况；
  S10 帧工具的后端定案（`hevc_cuvid` 优先 → 软解回退 → PyAV 备胎，**禁** `-hwaccel cuda` 与一切 qsv）。

---

## F-043 多路合成实测：软件光栅 3 层只有 14.95 fps，同一配置带 GPU 是 59.98 fps、峰值 1.29 GB（M1-D 的「多路」缺口结案，2026-10-20）

- **证据等级：已验证**（同一配置在两条渲染通路上各测一次，且渲染耗时与帧到达率可互相印证）。
- **Evidence**：`temp/px-probe/multi-probe.html` + `temp/px-probe/run_multi_probe.py`
  （行值 `browser-report-multi.jsonl`、汇总 `multi-report.txt` / `multi-samples.json`、取数日志 `media-server.log`）。
  6 个配置 × 2 条渲染通路：**软件光栅**（`--disable-gpu`，与 F-038 同口径，ANGLE 报 `Microsoft Basic Render Driver`）
  与**带 GPU**（去掉该 flag，ANGLE 报 `NVIDIA GeForce GTX 1650 (0x00001F0A) Direct3D11`，同轮 `navigator.gpu` 存在）。
  画布 1080x1920，预热 1200 ms 后计 3000 ms；分母 = 实际渲染窗（沿用 F-038 的 `window_ms` 修正）。
  素材 pin 绝对路径自 `<DRIVE_E>/fixtures\1012-1626-fixture\media`。
  驱动方式：主层每到一个 `requestVideoFrameCallback` 才 `app.render()` 一次 ⇒ `composite_fps` 是**合成帧到达率**，
  与 F-038 的「`<video>` presented fps」不是同一个口径，**不可直接比大小**。

  | 配置 | 软件光栅 fps | 带 GPU fps | GPU 轮 render p50/p95 | interval p95 | 该配置时刻 RSS |
  |---|---|---|---|---|---|
  | L1 单路 C7459 | 29.061 | 未测 | — | 41.3 ms（软件） | 1238 MB |
  | L2 两路视频 | 16.098 | 57.756 | 0.1 / 0.3 ms | 17.8 ms | 936 MB |
  | **L3 两路 + 字幕（判定配置）** | **14.95** | **59.98** | 0.1 / 0.2 ms | 17.3 ms | 1060 MB（该轮峰值 1322 MB） |
  | L4 判定 + HEVC 4K 层 | 12.65（HEVC 层 0 帧） | **60.055**（HEVC 层 241 帧） | 0.1 / 0.2 ms | 17.3 ms | 1142 MB（该轮峰值 1447 MB） |
  | L5 判定 + 手机竖屏第三路 | 11.261 | 未测 | — | 115.8 ms（软件） | 1447 MB |
  | L6 四路 + 字幕 + Multiply | 12.961 | 未测 | — | 89.8 ms（软件） | 1444 MB |

  纹理上传随层数线性增长（`texSubImage2D` 131/262/390/500/632/777），而 JS 堆只有 4.1~5.0 MB ⇒ RSS 全在媒体与 ANGLE 缓冲侧。
- **Finding**：
  1. **判定配置在带 GPU 的通路上三条判据全过**：59.98 fps ≥24、render p95 0.2 ms ≤20 ms、峰值 1.29 GB ≤2 GB；
     再加一层 4K HEVC（L4）仍是 60.055 fps / 1.41 GB ⇒ **多路合成不构成路线 A 的反证**，`base-selection.md` §定案 的生效条件少一项。
  2. **同一配置在 `--disable-gpu` 下塌到 14.95 fps**，连单路也只有 29.061 ⇒ F-038 那一整轮是**下界**而非典型值；
     文档里凡引用浏览器轴数字必须写明是哪条渲染通路，两套数不得混排。
  3. **瓶颈在视频帧到达，不在合成**：`app.render()` 只花 0.1~0.3 ms，而 interval p95 从 17.3 ms（GPU）恶化到 41~116 ms（软件）
     与 fps 同步 ⇒ M2 可以放心把合成层做重（遮罩、滤镜、渐变字幕），基底不是瓶颈。
  4. **残留（新开 U-58）**：本 harness 用一个 flag 同时关掉硬解与硬栅，**没法把两者分离**；
     要拆只能经 WebCodecs 单独喂帧（不经过 `<video>` 的媒体管线），本轮未做。
  5. **两条 harness 坑**：① `browser-report-multi.jsonl` 第 15 行是**撕裂写入**（并发 run 共用同一个 `--user-data-dir`
     会附着旧会话并交错写报告），该行不得引用，之后每个 run 用独立 profile；
     ② base64 里的 `+` 直接拼进 query 会被解成空格，必须 percent-encode。
- **Path**：`base-selection.md` §spike 结果 新增「已测：多路合成」表、§仍未测 删去多路合成一项、
  §定案 第 1 条条件句改写、要求 6 补多层 RSS；`evidence/unresolved.md` U-53 下级口径更新 + 新增 U-58；
  `spec/format-reference.md` §10 浏览器解码轴同步。

---

## F-044 更正 F-038 的 HEVC 结论：阴性来自 `--disable-gpu` 与一个假 `description`，真 hvcC 下四个串全 True（U-54 结案，2026-10-20）

- **证据等级：已验证**（能力探测与实际解码两路独立：`isConfigSupported` 矩阵 + `<video>` 真解出帧）。
- **Evidence**：用 PyAV 从 fixture `20261012_104307.mp4` 取出**真实 hvcC**（113 字节，头 14 字节 `01 21 60 00 00 00 b0 00 00 00 00 00 00 99 f0`，
  解析得 profile_idc=1、tier=1、compat=`0x60000000`、level_idc=153 ⇒ 本流的规范串是 `hvc1.1.60000000.L153`），
  percent-encode 后经 `?hvc=` 传入 `multi-probe.html`；对 4 个 codec 串 × 3 种 `description` 形态
  （真 hvcC / 不传 / F-038 用的 4 字节 `00 00 00 01`）跑 `VideoDecoder.isConfigSupported`。
  行值 `browser-report-multi.jsonl` 的 `codec_probe_hvc` 两行（GPU 轮、软件轮）。
  同页同轮里 `<video>` 实际解这条 4K HEVC：`arrived_frames` 241、`video_size` 2160x3840、dropped 10 / total 260（F-043 的 L4）。

  | 渲染通路 | 真 hvcC | 不传 description | F-038 的 4 字节假值 |
  |---|---|---|---|
  | 带 GPU（ANGLE = GTX 1650） | **True ×4** | **True ×4** | **False ×4** |
  | `--disable-gpu` | False ×4 | False ×4 | False ×4 |
- **Finding**：
  1. **F-038 第 6 条「HEVC 是硬缺口」被推翻**：启用硬件通路后，F-038 原测的 `hvc1.1.6.L93`、`hvc1.2.4.L153`
     与本流真串 `hvc1.1.60000000.L153`（以及 `hvc1.1.60000000.L93`）全部 supported=True，`<video>` 也真解出了帧。
  2. **两个混淆各能单独造成假阴性**：① `--disable-gpu`（软件轮 12 项全 False）；② `description` 传一个不合法的 4 字节
     （GPU 轮也全 False）。F-038 同时踩了两个，所以那条「Chrome 永远解不了 HEVC」的读法从来就不成立。
  3. **不传 `description` 也是 True** ⇒ 「HEVC 必须带 hvcC 才判得出来」的猜测不成立，profile 串本身足够。
  4. 于是「不支持编码的降级」从**必须有实现项**降为**边界处理项**：仍要保留「解码器报不支持时显式提示、不许静默黑帧」这条路，
     但 HEVC 不再是需要预转码的主力场景；路线 A 的 HEVC 前提成立，§定案 的生效条件只剩 seek（U-55）。
  5. **残留**：本机是 GTX 1650 + 驱动 610.88 的 Windows；换一台没有硬件 HEVC 解码器的机器结论可能不同，
     用户真实浏览器默认是否启用硬件解码仍未直接观测（S7 的一分钟检查仍然值得做，但只作确认，不再是判定项）。
- **根因（口径错法，与 F-019/F-030/F-037/F-038/F-039/F-042 同类）**：F-038 把**探针传参的形状**当成了**浏览器的能力**——
  用一个 4 字节的假 `description` 去问「支持吗」，并用一个关掉被测能力的 flag 去问。
  → 规矩：**能力探测必须用被测对象自己产出的配置记录**（这里是文件里取出的 hvcC），
  且报告里要把「参数不合法」与「不支持」分成两列，不能共用一个 `supported=false`。
- **Path**：`evidence/unresolved.md` U-54 结案（留一句跨机确认）、U-53 的下级列表更新；
  `base-selection.md` 要求 5 与 §定案 的 HEVC 措辞、§已测：浏览器解码轴 的 HEVC 行标注「软件光栅下」；
  `spec/format-reference.md` §10 同步；`evidence/conflicts.md` 若外部资料仍说「Chrome 不支持 HEVC」需在此裁定。

---

## F-045 seek 的服务端两条候选实测无效：缓存与预取钳位都不改中位延迟，成本在关键帧定位与解码前进（U-55 收窄为实现项，2026-10-20）

- **证据等级：已验证**（同一素材 6 轮，含 F-038 原轮复现；三档服务端配置各自独立成轮）。
- **Evidence**：`temp/px-probe/media_server.py` 新增三档开关 `JY_PROBE_CACHE` / `JY_PROBE_CLAMP` / `JY_PROBE_NAS`，
  每轮启动把配置写进取数日志的 `serving [...] cache=… clamp=…` 行；跑法与 F-038 完全同一探针页
  `decode-probe.html?autostart=1&only=2,3`（即 C7459 269 MB 与 C7463 1.6 GB），headless Chrome 同一 profile。
  行值在 `temp/px-probe/browser-report.jsonl`（**追加写**：F-038 引用的原有记录已另存副本
  `browser-report-f038.jsonl`，今后引用旧数一律指副本，避免与本轮混读）。

  | 轮 | 服务端配置 | C7459 seek 中位 | C7463 深跳中位 | 播放 fps | 丢帧 |
  |---|---|---|---|---|---|
  | F-038 原轮 | `no-store` | 266.7 | 278.2 | 60.18 / 59.69 | 0 |
  | 复现轮 | `no-store` | 252.1 | 298.2 | 59.46 / 59.49 | 0 |
  | 缓存轮一 | `public, max-age=3600` + ETag | 248.5 | 292.7 | 59.96 / 60.15 | 0 |
  | 缓存轮二（同 profile 已暖） | 同上 | 256.0 | 306.9 | 59.72 / 59.19 | 0 |
  | 钳位轮一 | 缓存 + `bytes=a-` 响应钳到 32 MiB | 255.6 | 295.1 | 57.6 / 60.2 | 0 |
  | 钳位轮二 | 同上 | 250.4 | 317.3 | 59.43 / 59.2 | 0 |

- **机制指纹**：C7459 的 seek 目标按时间在文件上均匀分布，延迟**随目标位置单调上升**
  （101 → 145.7 → 194.4 → 206.6 → 252.1 → 299.8 → 379 → 412.1 ms）；
  C7463（220 s 片）靠前的两个目标 77.4 / 106.1 ms，靠后的两个 298.2 / 323 ms。
  ⇒ 成本是「定位到前一个关键帧 + 解码前进到目标帧」，不是取数——与「网络/缓存」这一类解释不相容。
- **Finding**：
  1. **候选 (iii)「允许 HTTP 缓存 / 保留已取块」证伪**：开启可缓存响应头并在同一 profile 上再跑一轮，
     中位仍是 248.5~306.9 ms，与 `no-store` 基线同区间。原因是 Chrome 每次 seek 请求的是**不同偏移**的
     开区间 `bytes=<offset>-`，cache key 与本就没命中过，缓存策略再好也无从复用。
  2. **候选「钳短开区间预取」同样无效**（250.4~255.6 与 295.1~317.3 ms）。
  3. ⇒ U-55 只剩 **(i)**：mediabunny 自己读 sample table 拿关键帧偏移、按**精确闭区间**取块，再用 WebCodecs
     从关键帧解到目标帧；**(ii)** 低码率代理片作兜底。**服务端改响应头不可能把 seek 压进 150 ms**，
     这条不再是配置项，而是播放器实现项（M2 的第一个真实工程决策）。
  4. **两条口径纠正**：① 首帧延迟这 6 轮里散布在 108.9~228 ms（F-038 记 96.8~110.2），
     阈值 ≤300 ms 仍过，但**轮间有两倍散布**，引用时不得只挑小的那个；
     ② 播放 fps 与丢帧在 6 轮里稳定（57.6~60.2 fps、丢帧 0）⇒ 连续播放这条判据可复核，F-038 的结论保留。
- **Path**：`evidence/unresolved.md` U-55 改写（三条候选 → 只剩实现项）；`base-selection.md` §定案 第 1 条与
  §已测：浏览器解码轴 的 seek 行补「header 侧无解」；`temp/px-probe/media_server.py` 保留三档开关
  （默认仍是 `no-store`，与 F-038 口径兼容）。

---

## F-046 NAS 素材成对实测：连续播放零退化，但首帧翻倍并破 300 ms 阈值，seek 再涨约四分之一（U-56 结案，新开 U-59，2026-10-20）

- **证据等级：已验证**（同一素材在本地与 NAS 上字节数与 mtime 一致，成对、同服务器配置、同浏览器 profile 先后跑）。
- **Evidence**：`media_server.py` 的 `JY_PROBE_NAS=1` 挂上 `<NAS>/<NAS>/<素材语料>2026/2026.10.12/<素材语料>客户素材/尼那空镜`
  （**按全路径挂根，不按 basename 查找**——同名不同内容的 `C7459.MP4` 在 `E:`/`Z:` 至少还有几份）；
  探针页 `decode-probe.html` 的 FILES 增两条 NAS 条目，先跑 NAS 轮再跑本地轮，服务器配置相同（`no-store`、不钳）。
  汇总落 `temp/px-probe/nas-pair.txt`，行值 `temp/px-probe/browser-report.jsonl`。
  `\\192.168.0.247` 映射盘本轮可读（此前 U-56 记的「工具策略拒绝 `X:`」已过时）。

  | 素材 | 位置 | 首帧 ms | seek 中位 ms | seek 最大 ms | 播放 fps | 丢帧 |
  |---|---|---|---|---|---|---|
  | C7459（28 s） | 本地 E:（同轮） | 158.8 | 257.0 | 378.1 | 59.01 | 0 |
  | C7459 | **NAS X:** | **422.1** | 326.5 | 429.4 | 58.39 | 0 |
  | C7463（220 s，深跳） | 本地 E:（同轮） | 111.6 | 273.7 | 284.5 | 59.96 | 0 |
  | C7463 | **NAS X:** | 228.7 | 338.8 | 346.6 | 60.08 | 0 |

  本地轮的历史散布（F-038 起共 7 轮）：C7459 首帧 96.8~228、seek 中位 248.5~266.7；C7463 首帧 108.9~206.2、中位 273.7~317.3。
- **Finding**：
  1. **首帧是 NAS 腿唯一破线的判据**：`422.1 ms` 超阈值 300 ms，且比同轮本地值高 2.7 倍；
     C7463 也是翻倍（111.6 → 228.7）。但**仍落在本地轮的历史散布边缘之内**，所以「NAS 一定破线」说得太死，
     准确说法是**首帧代价约 +110~270 ms，足以把原本压线过关的素材推过阈值**。
  2. **连续播放与丢帧完全不退化**（58.39 / 60.08 fps，丢帧 0）⇒ 1 Gbps 链路对 58 Mbps 码率有富余，
     **抖动不是这条链的问题**；「NAS 会造成黑帧假象」的历史教训在本次成对跑里没有复现
     （`duration_s` 与 `intrinsic` 都正常读到）。
  3. **seek 只再涨约四分之一**（+27.1% 与 +23.8%），且 NAS 轮同样呈「延迟随目标位置单调上升」的指纹
     ⇒ 与 F-045 一致：seek 的主导成本仍是关键帧定位与解码前进，网络只是加性项。
  4. 于是 M1-D 的浏览器路线对 NAS 素材**不需要改评**（判据 2/3/4 仍过），但要新增一条实现要求：
     **首帧预热**（新开 U-59）。可选实现：起播前预取头部固定 MiB、按 `##_draftpath_placeholder_##` 解析后
     优先走 `<draft>/materials/` 本地缓存、或让用户先把素材落本地。
- **Path**：`evidence/unresolved.md` U-56 结案 + 新增 U-59（NAS 首帧预热策略）；
  `base-selection.md` §仍未测 删去 NAS 一项、§风险 的 NAS 条改写为「已量：首帧 +2.7 倍、播放零退化」；
  要求 4（素材来自 NAS 与草稿本地缓存）补一句实测口径。



## F-047 剪映自带的草稿处理层与 r3 规格三方核对：对得上的 26 项全一致、0 冲突；容器层漏 1 个文件、版本轴与主轨判据各有一条分歧（新开 U-60/U-61，2026-10-20）

- **证据等级：已验证**（两条独立通道：安装包内剪映自己的协议文档与草稿构造代码 ↔ r3 冻结普查 `stats.json` / 冻结明文）。
  「agent 写 `version=400000`」是源码字面量级；但「11.6 能否读回 400000 草稿」**未实测**，归 U-60。

- **Evidence**：
  - **新目标**：`<JY_INSTALL>\11.6.0.14552\Resources\canvas_agent`（235 MB，239 个 js/mjs，只读）。
    这是 11.6 自带的 agent 运行时，**剪映自己写草稿的代码与协议都在这里**：
    `skills/jianying.hub.studio_lyra_xml_timeline_builder_v2/`（协议 `xmldraft/v1`；SKILL.md sha256 `75d2a317…`，
    `references/timeline.md` sha256 `8897a067…`，SKILL+10 个 references 共 132,883 B、属性表 274 行、去重 **146 个属性名**）；
    `runtime/app-server.mjs`（9,206,933 B，sha256 `4f027a06…`，内含 `wl0()` 成片草稿构造器与 `gh1` 平台常量）；
    `runtime/videoeditor-service.mjs`（128,669 B）只有导出/渲染作业、**不含任何草稿字段**；
    `skills/studio.edit.speaker_cut/`（15 MB、91 个 mjs）走自己的中间模型，同样不碰 draft JSON。
  - **REA 跑法**（白名单内，未跑 `setup`/`install.sh`）：
    `npx -y rea-agents@6.5.0 analyze-javascript-application "<canvas_agent>" --artifact-format directory --source-path runtime/app-server.mjs --max-heap-mb 6144 --analysis-timeout-ms 600000 --json`。
    默认 `--max-heap-mb 1024` 时 worker 在这个 9.2 MB 文件上**堆耗尽**（`parsed_javascript_files:1`、`modules:0`、`visited_ast_nodes:35,156`）；
    提到 6144 MiB 才解析完（`visited_ast_nodes:2,163,421`、`findings:3,426`、应用图 1,229 节点 / 4,391 边），
    但**语义关系被父进程结果预算丢弃**（`coverage.status=partial`、`truncated=true`、`relations:0`）。
    `rea providers` 实测本机**没有任何 native provider**（Ghidra/Hopper/IDA 未配置，`objdump`/`readelf`/`rizin` 不存在）
    ⇒ `videoeditor.dll` 里的 xmldraft→JSON 映射读不到。产物：`temp/rea/{app_server_h6144.json 18.5 MB, canvas_agent_runtime.json 42 MB, providers-1020.txt}`。
  - **三方核对**（`temp/rea/{diff_xmldraft_attrs.py, three_way_check.py}` → `temp/rea/xmldraft_attrs_3way.csv`）：
    146 个协议属性里 **26 个**在真实草稿里存在同名字段，这 26 个**全部已被 `docs/spec` 记录，0 遗漏、0 语义冲突**：
    `background_color blur category color content crop duration font_size height id intensity language letter_spacing line_spacing mode reverse size speed text_alpha text_color tracker_type type value volume width`。
    其余 120 个是 XML 层别名（`material_start`↔`source_timerange.start`、`duration/start`↔`*_timerange`、
    `crop_position/crop_rotation`↔`clip.crop.*`、`max_width/max_height/overflow`↔`line_max_width`+`force_apply_line_max_width`、
    `loudness_normalize`↔`materials.loudnesses[]`）。本项目工程格式就是 draft JSON，**不经过 XML 层，所以这张别名表不构成缺口**。
  - **一致项逐条**（agent 写 ↔ r3 实测）：`canvas_config.ratio="original"` ↔ `canvas_ratios.csv` original 341；
    `sound_channel_mappings[].type="none"` ↔ 枚举 none 26,011 / "" 3,272；`render_index_track_mode_on=true` ↔ 2,041/2,050 为 bool；
    `platform` 八字段名（`os os_version app_id app_version app_source device_id hard_disk_id mac_address`）与实测逐字段相同；
    `tracks[]` 的 `id type name is_default_name segments attribute` ↔ `track_field_keys`；
    协议明文「时间属性一律裸数字、按毫秒解释，`us/ms/s/min/m` 后缀非法」↔ JSON 侧微秒（`timebase.yaml` 不改，但这条现在是第二方证据）。
  - **agent 私有记账不是原生格式**：`segment.videoEdit` 与 `video-edit:<id>:<n>` 这套 track 命名在 2,050 份去重内容里 **0 命中** ⇒ 规格不写它是对的。

- **Finding**：
  1. **草稿格式判定：两条通道能对上之处 100% 一致**，没有发现 `docs/spec` 与剪映自身实现互相矛盾的字段。
     REA 对字段级事实仍无产出——与 10-15 的基座判断一致，这次给出量化理由（worker heap 与父进程结果预算两道墙），
     且本机无 native provider。结论：**字段清点继续用自研脚本，REA 只用它给的清单/模块图与可复现摘要**。
  2. **容器层漏一个文件**：`draft_virtual_store.json` 在 1,475 个草稿目录里存在 **1,184** 个（`draft_content.json` 是 1,190，几乎同数），
     而剪映自己的草稿理解模块（常量 `custom-agent.jianying-draft-understanding.v1`）把 5 个 JSON 列为草稿标准成员：
     `draft_info / draft_meta_info / draft_content / draft_virtual_store / draft_agency_config`。`layout.yaml` 的目录成员样本里没有它。
     内容形如 `{draft_materials:[], draft_virtual_store:[{type, value:[{child_id, parent_id, sort_type, filter_type, import_time_us, …}]}]}`
     ⇒ 它是 `subdraft/`（226 个草稿有）的**父子索引**，复合片段/嵌套草稿要靠它，不能只当噪声。
  3. **版本轴分歧**：桌面剪映在 693 份抽样（步长 `[::3]`）里 `version` 恒为 `360000`，`new_version` 是与 `platform.app_version`
     单配的字符串（配对取自 300 份交叉表，步长 `[::5][:300]`：11.1.0→"179.0.0"、11.2.0→"181/183/189.0.0"、11.3.0→"183/185.0.0"、11.4.x→"185.0.0"、11.5.0→"187.0.0"、11.6.0→"189.0.0"；每个 app_version 在交叉表里只对应 1~3 个取值。693 份里 `new_version` 共 36 个不同值），
     `app_id=3704`、`app_source="lv"`、`os="windows"`；**同一个安装包里的 agent 构造器写 `version=400000`、`app_id=348188`、`app_version="15.4.0"`、`app_source=""`、`os="web"`，且不动 `new_version`**。
     规格里版本轴此前只有 F-016 那一份草稿的单点记录，没有一般化断言 ⇒ 写回该 stamp 什么版本是 M3 门禁问题（U-60）。
  4. **主轨判据：agent 用位置，语料支持位置、排除 `flag`**。agent 断言「`tracks[0]` 必须是视频主轨」（缺则报 `成片草稿缺少视频主轨`），
     协议还把主轨当一等公民（唯一 `<main>`、按文档顺序承载 video/image、往主轨开头插入会自动把 multi 片段整体后移）。
     实测 370 份含 video 轨道的草稿里 **370/370 条 `tracks[0].type=="video"`**，其中 206 份（55.7%）有多条 video 轨（画中画）；
     而 `flag` 不是主轨标记：唯一 `flag==2` 的轨道落在首条 video 轨的比例 **0/206**，`flag==2` 在 164 份草稿里一条都没有。
     `docs/spec` 此前**完全没有「主轨/副轨」这条结构轴**（`主轨`、`tracks[].flag` 在 `docs/spec/` 全文 0 命中）⇒ 补进 `layout.yaml`，`flag` 语义转 U-61。

- **Path**：
  - `spec/layout.yaml`：目录成员样本补 `draft_virtual_store.json`；新增 `container_json_set`（剪映自己的 5-JSON 枚举 ↔ r3 目录计数）、
    `platform_block`（八字段名 + 桌面值 + agent 差异值，stamp 问题指向 U-60）、`main_track`（位置判据 + 370/370、206/370、`flag` 排除）；
    `version_axis` 把「桌面恒 360000 / agent 写 400000 / `new_version` 随 app_version 单配」记成实测事实。
  - `spec/format-reference.md` §1 加对应条（同日）、§10 加 U-60/U-61 行。
  - `evidence/unresolved.md` 新增 U-60（版本轴与平台身份 stamp）、U-61（`tracks[].flag` 语义）。
  - `evidence/toolchain.md`：§1 记这次 REA 跑法与 heap/预算两道墙，§3 把 `Resources/canvas_agent` 登记为只读分析目标，
    §明确不执行 补「不装 Ghidra/JDK/native provider」。



## F-048 时间线与轨道深挖：八类轨道在独立全量重跑上逐位复现，但片段形状、素材类型判别字段与分带规则各漏了一条（新开 U-62/U-63，就地更正 4 处数字，2026-10-20）

- **证据等级：已验证**（对冻结 r3 语料做**独立第二遍全量重跑**，与 `stats.json`/`coverage.md`/`picture.yaml` 的既有断言逐项对账；
  形状与类型枚举是本轮新测的维度）。

- **Evidence**：
  - 口径纪律：只读 `temp/corpus-scan/manifest.json` 列出的 **2,050 个 content key**，其余 `plain/` 副本一律排除——实测目录里有
    **2,078 份明文，其中 28 份是 F-030 说的历史残留**（`temp/track-probe/build_track_matrix.py`）。全部数字按**片段/轨道条数**计，
    不是「多少份内容」；引用时必须带这个basis。
  - **逐位复现**（说明既有规格不是猜的）：八类轨道条数 video 3,195 / audio 2,582 / text 2,439 / mixed 825 / effect 410 /
    sticker 277 / adjust 194 / filter 68 ✓；顶层片段总数 51,718 ✓；带 `clip` 键 42,135、`clip` 整值 null 4,325 ✓；
    `track.attribute` 直方图 0:3,231 / 1:170 / 2:38 / 4:10 / 6:8 / 3:4 / 16:2 / 8:2 ✓；`track_render_index` 恒定 8,584 / 变化 1 ✓；
    text 的 14000 带 19,467 ✓；音频/歌词族键各 6,178 ✓；逐类型引用桶（video→effects 66,237、audio→beats 12,714、
    mixed→material_animations 1,916…）与 `coverage.md` 的「引用组成」表逐项相同 ✓。
  - **新测维度 1：片段键集不由轨道类型决定。** 全语料**只存在一种 45 键的「完整形」**（无第二种 45 键变体），
    共 6,004 个片段带它，且横跨 audio 2,244 / text 2,237 / video 1,233 / effect 109 / adjust 78 / sticker 58 / filter 45；
    它比常见最小形多出 `caption_info, color_correct_alg_result, desc, digital_human_template_group_id, is_loop, lyric_keyframes, raw_segment_id, state` 与一批 `enable_*`。
    各类型自己的最小形：audio 13 键 43.1%（5,489）、text 15 键 34.7%（6,940）、mixed 15 键 30.5%（729）、effect 12 键 46.6%（254）、
    adjust 8 键 18.4%（87）、sticker 14 键 13.6%（54）、video 13 键 9.9%（1,486）。**不同键集种数**：video 524、mixed 104、text 32、
    audio 31、adjust 26、sticker 20、effect 13、filter 10。
  - **新测维度 2：素材的语义类型在 bucket 的 `type` 上，不在 `track.type` 上。**（此前规格只记 bucket 名，没记 `type` 枚举）
    `texts.type` = **subtitle 17,718 / text 3,307 / lyrics 60 / none 1**（字幕 vs 普通文字 vs 歌词的判别字段）；
    `audios.type` = **sound 7,069 / video_original_sound 3,062 / music 1,302 / text_to_audio 1,143 / extract_music 166**；
    `videos.type` = video 15,402 / **photo 1,230** / image 2（图片不另设 bucket）；`drafts.type` = **combination 4,657 / composition 439**；
    `canvases.type` = canvas_color 14,879 / canvas_blur 1,620 / canvas_image 33 / none 9；
    `material_animations.type` **恒为 sticker_animation（34,828 条无一例外）**，真正的分类在 `animations[].type` = in 8,388 / loop 1,587 / out 303 / caption 158 / group 129；
    `text_templates.type` = text_template 805 / text_template_subtitle 30 / text_template_lyrics 1；
    `placeholders.type` 恒 `adjust`（483）；`video_effects.type` = video_effect 687 / face_effect 84；
    `sound_channel_mappings.type` = none 26,011 / 空串 3,272（与 F-047 里 agent 写 `none` 同向）。
    `track.type → material_id 落在哪个 bucket.type` 的完整映射见 `picture.yaml -> tracks.track_type_material_map`。
  - **新测维度 3：`render_index` 的分带比规格细。** 逐类型落带（`temp/track-probe/bands_and_shapes.py`）：
    video 0-999 7,288 + 1000-9999 15；audio 0-999 3,920；adjust 0-999 290；filter 10000-10999 106；effect 11000-13999 542 + 0-999 3；
    text 14000-14999 19,467 + **15000-15999 254 + 16000-18999 29 + 19000+ 207** + 1000-9999 1；sticker 14000-14999 392 + 15000-15999 6；
    **mixed 跨带** 0-999 257 / 10000-10999 1 / 11000-13999 26 / 14000-14999 757。
  - **新测维度 4：轨道级值域首次实测。** 轨道总数 9,990；`id`/`type` 各 9,990、`segments` 9,962（缺席 28 = video 25 + mixed 3）、
    `is_default_name` **true 9,898 / 缺席 82 / false 10**、`name` 3,365（video 1,158 / text 963 / audio 866 / effect 143 / sticker 140 /
    filter 51 / adjust 44 / **mixed 0**）、`flag` 5,597（完整分岔见 U-61）、`attribute` 3,466（直方图多出一档 **17:1**）。

- **Finding**：
  1. **既有规格在轨道这一层经受住了独立重跑**：所有可对账的计数逐位相同，说明 r3 的轨道/片段统计不是单遍采样误差。
     规格的问题是**维度缺失**而不是数值错——「形状」「bucket 的 type 枚举」「次带」这三件事此前根本没测过。
  2. **`track.type` 不能用来分派渲染分支**（推翻规格默认的隐含假设）：字幕可以在 mixed 轨上（texts.subtitle 被 mixed 指 564 次），
     同一类型轨道里片段形状可以是 8 键也可以是 45 键。可读判据只有「键在不在 + field_states 四态」，
     写回时**不得**因为片段属于 audio 就补写 video 侧的键。
  3. **规格里有 4 处数字与实测不符，已就地更正**（不是新事实，是旧行的口径/笔误）：
     ① `picture.yaml` 的 clip 行写 42,215 / segment 总数 51,784 → 应为 **42,135 / 51,718**（与 `text.yaml`、`format-reference.md` 一致）；
     ② `picture.yaml` 的 `common_keyframes` 写 17,408 → 应为 **17,411**（`keyframes.yaml` 是对的），并补「其中非空仅 836」；
     ③ `picture.yaml` 的 `curve_fields` 仍标 `open U-14`，而 `keyframes.yaml` 第 1 行已宣布 U-14 结案 → 本文件没跟上，改为指向 `keyframes.yaml`；
     ④ `materials.yaml` 的 `audios` note 写「material type 值为 music 而非 audio（single）」 → **错**，`music` 只占 1,302，
     实际五种取值里最多的是 `sound` 与 `video_original_sound`；`audio` 是**轨道类型名**、从来不是 material type 值。
     根因：这条是早期从单份草稿的一个 bucket 样本外推的，登记后没被后续普查回扫——`stats.json -> bucket_enum_values` 其实一直有这个枚举，只是没人去读。
     **纪律补一条**：凡是 `type`/`mode` 这类枚举字段，登记前必须查 `bucket_enum_values`，不许由单样本外推。
  4. **`mixed` 与三个次带是新开的两个开放项**（U-62、U-63）：前者决定「能不能按轨道类型分派」这个架构问题，
     后者与 U-15 一起决定同层片段谁压谁。两者都能在 M2 用少量草稿判定。

- **Path**：
  - 可重跑工具与派生表：`scripts/track_matrix.py`（只读冻结语料，按 manifest 的 2,050 个 content key 取数）生成
    `evidence/tables/track_types.csv`（八类轨道 × 键存在数 / `is_default_name` / `flag` / `attribute` 分岔）、
    `segment_shapes.csv`（每类前 6 种键集与占比）、`track_material_map.csv`（`track.type` × bucket.type 引用数）、
    `material_type_enums.csv`（42 个 bucket 的 `type` 取值与条数）、`render_index_bands_by_type.csv`（八带 × 八类轨道）。
    本轮新数字一律以这五张表为出处；旧的 `render_index_bands.csv` 保留不动。
  - `spec/picture.yaml`：新增 `tracks.track_type_material_map`、`tracks.segment_has_no_type`、`segment_shapes`、
    `track_fields.key_presence / is_default_name_values / flag_values_by_type`（并把 `attribute_values` 补上 `17:1`）；
    `compositing_order.bands_measured` 换成逐带表；更正 clip、`common_keyframes`、`curve_fields` 三处旧行。
  - `spec/text.yaml`：新增 `location.material_type_field`（`texts[].type` 四种取值 + 引用侧分布），`text_segment_band` 补次带。
  - `spec/materials.yaml`：`videos / texts / audios / drafts / canvases / material_animations / sound_channel_mappings /
    video_effects / text_templates / placeholders` 十处 bucket 补 `type` 枚举与条数，`audios` 的错误 note 就地改写。
  - `spec/coverage.md`：轨道字段行补值域，新增「轨道类型↔素材类型」「片段键集形状」「次带」三行。
  - `spec/format-reference.md` §4/§5：同日改写分带行、补 `texts[].type` 与「类型不决定形状」两条。
    同日再扫：§0 第 5 步（`material_id` 悬挂 0 / stub 悬挂 10 / 28 条无 `segments` 轨道 / 语义看 bucket 的 `type`）、
    §3 新增「轨道与片段」「bucket 的 `type` 枚举」两行、§6 新增「画面素材类型」（图片 = `videos.type==photo`）、
    §11 从十七条扩到**二十条**（新增：不按 `track.type` 分派、不按类型补键、不要用 `audios.type==music` 认音频）。
  - `spec/write-rules.md` §3：作废旧行「音频 material 的 type 必须是 music」，新增五条不变式
    （`audios.type` 五取值、不按 `track.type` 分派、不按类型补键、主轨插入需自行重算副轨区间、
    复合片段要同时动 `drafts[]` 与 `draft_virtual_store.json`、`platform`/版本 stamp 只搬运不改写）。
  - `spec/timebase.yaml`：微秒单位补上第二方见证（内置协议用毫秒，两层 ×1000）。
  - 汇总报告：`evidence/track-layer-report.md`（轨道/时间线层完整报告，含与既有规格的逐位对账表）。
  - `evidence/unresolved.md`：新增 U-62（mixed 含义）、U-63（render_index 次带），并把 U-61 的 `flag` 数字升到全量口径。





## F-049 深度发现批次：MixMode 资源索引一次闭合 U-12、阴影模糊换算由源码值域印证、裁剪与 fill 的「键存在≠非默认」再证，另起出安装包里的草稿模型层（结案 U-02/U-03/U-12，收窄 U-10/U-51/U-15，新开 U-64/U-65，2026-10-21）

- **证据等级：已验证**（U-12 / U-03 / U-02 / U-10 的归一化部分 = 语料实测 + 安装包内官方声明两路一致；
  U-51 的存储侧几何 = 导出实测 F-035 + 官方 schema 两路，**面板 2× 的导出问题仍未判**）。单源之处逐条写明。

- **Evidence**：

  ### 靶面 C（agent 文档层，明文 md，本轮主要裁定来源）
  - `Resources/canvas_agent/skills/jianying.hub.studio_lyra_xml_timeline_builder_v2/references/` 11 份 +
    `Resources/canvas_agent/skills/skill-creator/references/editing/` 9 份。后者是**同一 schema 的中文显示名生成物**
    （`SKILL.md:9` 「此目录由基础协议、宿主规则与展示 schema 生成」），所以两份**算一路证据**，不是两路。
  - **混合模式中文名单**（`skill-creator/references/editing/segment-visual.md:69`）：
    「支持正片叠底、叠加、滤色、变暗、变亮、柔光、强光、颜色加深、颜色减淡、线性加深、差值、颜色滤镜或关闭」，
    与 `…/references/segment-visual.md:205` 的英文枚举
    `multiply, overlay, screen, darken, lighten, soft_light, hard_light, color_burn, color_dodge, linear_burn, difference, color_filter, off`
    **同项数、同顺序**。
  - **几何与单位声明**（`…/references/transform.md`）：`:92` x「0 为画布中心、-1 为左边界、1 为右边界，0.5 为从中心向右移动画布宽度的**四分之一**。不是像素」；
    `:93` y「0 为画布中心、1 为上边界、-1 为下边界，-0.5 为从中心向下移动画布高度的四分之一」；`:83` offset_y「正值向上」；`:89` rotation「逆时针为负、顺时针为正」；
    `:73/:74/:75` `crop`（比例串）/`crop_position`（8 个锚点枚举）/`crop_rotation`（度，默认 0）；`:11-12` `deform` 固定 `corner_pin`、四角成组、**text 与 subtitle 必须阻断**。
  - **蒙版像素换算式被显式写出**（`…/references/segment-visual.md:142`）：
    「w=width*canvas_width，h=height*canvas_height，cx=canvas_width/2+center_x*canvas_width/2，cy=canvas_height/2-center_y*canvas_height/2」，
    `:150-151` 「±1 对应画布左右边缘」/「0 居中，正上负下」；`:76` 画布背景模糊「0 至 1 裸数；四档参照 0.0625 / 0.375 / 0.75 / 1，未指定时运行时默认 0.75」；
    `:33` alpha「50% 不透明度写 value="0.5"，不写 50」；`:253` volume「0 静音、100 保持原始音量、200 为两倍幅度，范围 0–1000，默认 100」。
  - **阴影**（`…/references/segment-text-sticker.md:135/:167`）「text_shadow_smoothing……**不使用底层 0 至约 0.1667 的引擎数值**」；
    `:116/:148`「缺少现值时分别参考 **8** 和 **-45**」；`:131/:163` shadow_alpha 是百分制滑杆（30% 写 30）。
    **发光只有四件套** `text_glow_{ref,color,strength,range}`（`:126-129`），**协议层没有角度字段** ⇒ F-019 的「11.6 UI 无角度控件」第一次拿到官方侧见证（U-27）。
  - **不支持清单**（`…/references/no-support.md:9-20`，9 项）：`element:application_params / plane / runtime_target / text_style`、
    `property:keyframe / keyframes`、`segment:motiongraph_effect`、**人声分离**、**人声美化**；`SKILL.md:57` 要求命中即停。
    关键帧在协议层是**明确不支持**，而 r3 语料里带 `common_keyframes` 键的 segment 有 17,411 个 ⇒ 该禁令只约束 agent 写入面，不是格式面。
  - **文档层对 U-61/U-62 无信息**：XML 只有 `element:main`（唯一主轨，最多 1 个）与 `element:multi`（副轨容器，最多 1 个）两个容器，
    **没有 `track_index`、没有轨道类型概念、「mixed」在 references 与 prompts 里 0 命中**（唯一命中是 `skills/script-logic/SKILL.md:17` 的 `focus` 默认值）。
    ⇒ 不许拿这套文档去裁 `tracks[].flag` 或 `mixed`。

  ### 靶面 A（编辑器前端 JS chunk）
  - `app/static/js/` 实测 **76 个 `.js`、16 MB**（不是任务书写的 50 个：顶层 43 个 + `async/` 33 个，另有 `.LICENSE.txt`）。
  - 标记扫描（`temp/rea/js_markers.py`）：`canvas_config` 35、`render_index` 49、`track_render_index` 7、`font_size` 23、
    `target_timerange` 17、`letter_spacing` 6、`mix_mode` 3 次命中，集中在 `ai-creation~7/10/11/12` 与 `async/2142`；
    `corner_pin` 作为独立标记 0 命中（只以 `videos[].corner_pin` 对象出现在模型层）。
  - **`ai-creation~10.0176e5c4.js` 与 `ai-creation~11.aa2812ea.js` 内嵌一份完整的 draft JSON 模型层**：
    生成式逐类字段表 `{common:[…],bigint:{…},array:{…},object:{…}}` + 构造器给每个键赋默认值。
    抽取器 `scripts/js_model_extract.py`：**268 条原始记录 → 132 条去重记录 → 880 个不同键**，全表落 `evidence/tables/js_model_keys.csv`。
  - 与 r3 语料的**全量递归键集**（981 个）对差：**模型独有 303 个、语料独有 404 个**（`temp/rea/js_model_diff.json`）。
  - 关键默认值（模型层）：segment `render_index=0 / track_render_index=0 / track_attribute=0 / visible=true / volume=1 /
    last_nonzero_volume=1 / speed=1 / enable_adjust_mask=true / enable_smart_color_adjust=false`；
    text material `font_size=15 / alignment=1 / line_spacing=0.2 / letter_spacing=0 / border_width=0.06~0.08 /
    shadow_alpha=0.8 / shadow_angle=-45 / shadow_smoothing=0 / background_width=0.14 / background_height=0.14 / check_flag=63`；
    video material `check_flag=65535 / crop_ratio="free" / crop_scale=1 / has_audio=true / live_photo_timestamp=-1`；
    mask config 全 0 + `invert=false`；shadow 类 `{alpha,angle,color,distance,enable,feather,feather_use_diffuse,strokes}` 默认全 1/关；
    stroke 类默认 `width=0.2, alpha=1, enable=false`。
  - **`z_order` 在 `runtime/app-server.mjs`（9.2 MB，草稿写入层）0 命中**，`zOrder`/`z_index` 也 0；
    而 `skills/studio.edit.speaker_cut/scripts/semantic-pipeline/lib/vendor/layer-planner.mjs:47` 明写
    `layering_policy` 为 `z_order_is_design_intent_only; no native text attribute; spatial overlaps require measured occlusion order`，
    `:173` 记 `native_z_order_emitted:false`。
  - `Resources/MixMode/MixMode.json`（**顶层索引，此前完全没被登记**）给出 10 条
    `{nameId, effectId, resourceId, path=包 md5}`；每条的 `path` 与 `tables/mixmode_glsl.csv` 的 `package_md5` 逐一对齐。

  ### 语料实测（`scripts/mixmode_join.py`、`scripts/field_census.py`，均只按 `manifest.json` 取数）
  - **mix_mode 全量 join：166 次 / 82 份内容，命中 166 / 166，未命中 0**。有草稿见证的 6 个包：
    变亮 `b0e90c43…` = LightenBlendPreMul（99 次 / 56 份）、滤色 `d9c1d4ca…` = Screen（37 / 22）、
    线性加深 `655f3590…` = LinearBurn（17 / 16）、正片叠底 `8001e07e…` = Multiply（6 / 3）、
    变暗 `420c92a2…` = Darken（4 / 2）、叠加 `e6a48579…` = Overlay（3 / 2）；
    语料从未引用的 4 个包：SoftLight（`042aa15b…`）、HardLight（`840ca85a…`，nameId=glare_pc）、
    ColorBurn（`b76087cd…`，nameId=darken_color）、ColorDodge（`f979dd10…`）。
    表：`tables/mixmode_packages.csv`、`tables/mixmode_draft_paths.csv`。
  - **`styles[].shadows[]` 实测 10 个键**（14,552 条阴影条目 / 571 份内容）：
    `alpha 14,443 / angle 14,552 / content 14,552 / distance 14,552 / diffuse 13,032 /
    thickness_projection_{angle,distance,enable} 各 5,368（206 份）/ feather 1,518（86 份）/ strokes 22（15 份）`。
    `diffuse`：14 个不同值、0..0.055、众数 0.025（12,697 次）；**按 面板 ÷ 600 检验，12,874 / 13,032（98.8%）落在整数面板值上**；
    `feather`：0..0.16667，但只有 247 / 1,518 落在整数面板值上 ⇒ **不是**面板滑杆的直接载体。
    `angle` -180..134.5、众数 -45（14,417）；`distance` 0..25.96、众数 5.0（12,915）。
    规范形取值是 **float32**：`alpha 0.899999976158142 / distance 4.999999523162842 / diffuse 0.02500000037252903`。
  - **`videos[].crop`**：16,634 个视频 material 里 `{}` 空占位 **11,589**、8 键 **4,955**（其中 **4,875 恰等于满框恒等**
    `upper_left(0,0) upper_right(1,0) lower_left(0,1) lower_right(1,1)`，只有 **80** 是真裁剪）、4 键 68、2 键 21、6 键 1。
    8 键全在 **[0,1]**、左上为原点、y 向下。`crop_ratio` 是**字符串**：`free` 4,914 / 16:9 51 / 9:16 17 / 3:4 6 / 4:3 5 / 1:1 2；
    `crop_scale` 浮点且 4,949 / 4,950 为 1.0；`corner_pin` 仅 11 例，形如 `{id, enable_corner_pin, corner_pin_info{…}}`，观测值全 **-1.0**（另一套归一化）。
  - **`styles[].fill`**（24,085 个带 fill 的 style）：`fill.alpha` 3,240、`fill.content.solid.alpha` 4,291；
    两者同时出现的 **3,214 例中 3,214 例完全相等（>1e-9 的差异 0 例）**；只有 `solid.alpha` 的 1,077 例、只有 `fill.alpha` 的 **26** 例、两者都无的 19,768 例。
    另有 `fill.content.render_type` 19,113、`solid.color` 23,682、`texture` 343、`gradient` 198。表：`tables/fill_alpha_pairing.csv`。

- **Finding**：
  1. **U-12 一次结案，而且判定方法比原计划便宜得多**。原方法（「用更多草稿的 name 与 path 配对逐包锚定」）不需要：
     `Resources/MixMode/MixMode.json` 就是官方资源索引，`effect_id`/`resource_id`/`path` 三个键都能和草稿直连，
     **166/166 全命中、0 未匹配**。中文显示名来自展示 schema 的中文名单，且英文枚举与中文名单**同序**；
     语料里 6 个有草稿见证的模式（正片叠底/叠加/滤色/变暗/变亮/线性加深）**独立验证了这个按位配对**，
     于是柔光/强光/颜色加深/颜色减淡/差值/颜色滤镜 6 项可以顺推。
     同时暴露两处旧错：① `picture.yaml` 把 `linear_burn` 注成「线性减淡(添加)」，官方中文名是**线性加深**；
     ② 旧 `evidence` 行把 `亮度`/`饱和度` 当混合模式名 —— 实测它们的 `effects[].type` 是 `brightness`（12 次）与 `saturation`（7 次），属调色，不是 mix_mode。
     ③ 协议枚举 12 个模式，本机 `Resources/MixMode/` 只有 10 个包 ⇒ **差值(difference) 与 颜色滤镜(color_filter) 无本地资源包**，M2 遇到这两个模式必须显式降级。
     nameId 的陷阱另记 C-013。
  2. **U-03 结案（阴影模糊换算）**：`diffuse = 面板模糊 ÷ 600`。两路一致 ——
     语料侧 98.8%（12,874/13,032）的取值在 ÷600 后落在整数面板值上、众数 0.025 = 面板 15（就是原来那个单样本）；
     官方侧声明引擎值域「0 至约 0.1667」，而 100 ÷ 600 = **精确的 1/6**。U-03 残留清零。
     但同批**新查出 `shadows[]` 里还有一个 `feather`（1,518 次 / 86 份，值域 0..1/6）**，它不符合 ÷600，
     而模型层的 shadow 类恰好带一个 `feather_use_diffuse` 开关 ⇒ 「模糊到底是哪个键」并未因此变成显然，转 **U-64**。
     同批登记 `thickness_projection_*`（5,368 次）与 `shadows[].strokes`（22 次）三个此前没记过的键。
  3. **U-02 结案，结论是「问题本身不成立」**：两个 alpha 在 3,214 个同时出现的样本里**从不相离（0 例外）**，
     所以「谁优先」在语料里不可观测。可以定的是**载体**：`fill.content.solid.alpha` 能单独存在（1,077 例），
     `fill.alpha` 单独存在只有 26 例（0.8%）⇒ 读侧以 `solid.alpha` 为准、缺则回退 `fill.alpha`；写侧两处都要写
     （与 `font_size` 与 `styles[].size` 的双写同型，见 U-26）。
  4. **U-10 归一化已判、范围仍小样本**：裁剪是**源素材归一化 [0,1]、左上原点、y 向下**，满框 = 恒等八元组；
     这与官方 `brush point.x/y`「左上角 (0,0)、右下角 (1,1)」的声明（`segment-packages.md:24-25`）同向。
     真裁剪条目只有 **80** 条（+ 89 条部分形），所以极值只是**观测下界**，不能说协议上限；按规矩保留为收窄后的 open。
     顺带判掉两件小事：`crop_ratio` 是字符串枚举且默认 `"free"`（与模型层默认逐字相同，两路一致），
     `crop_scale` 在 4,949/4,950 里恒为 1.0 ⇒ 是占位不是缩放载体。
  5. **U-51 拆成两半，几何半边结案**：官方把存储侧语义写死了 ——
     x/y 的 ±1 对应画布边界、`0.5` = 画布宽度的**四分之一**、y 向上为正、且明说「不是像素」，
     蒙版那条换算式 `cx = canvas_width/2 + center_x*canvas_width/2` 把 `/2` 直接写进公式。
     这与 F-035 的导出实测 `位移 = v 乘边长除以 2` **两路一致** ⇒ 「真实位移要除以 2」现在是源码级事实。
     剩下的只是显示层：面板把同一个 v 乘了**整个边长**，所以面板读数 = 真实像素的 2 倍；
     「2× 分辨率导出时位移跟着翻倍还是不变」仍然只有导出实验能判，U-51 据此**改写为只剩这一问**。
     附带产出：渲染器现在可以**直接照抄**蒙版中心的像素换算式（原来 `picture.yaml` 只能「按 config 推断」）。
  6. **U-15 拿到一条反向证据**：`z_order` 确实存在于协议（且**只有 video 有、image 没有**，
     `segment-visual.md:237-240` vs `:254`），但剪映自己的草稿写入层 `app-server.mjs` 里 `z_order`/`zOrder`/`z_index` **0 命中**，
     而自带工具链的 layer-planner 明确写着 `z_order_is_design_intent_only` 与 `native_z_order_emitted:false`，
     并要求「空间重叠要靠实测遮挡次序」。⇒ **官方自己也不靠任何草稿字段决定叠放**，U-15 不但没结案，
     反而多了一条「不要指望从字段推 draw order」的实现警告。同时否定一种偷懒做法：按 `tracks[]` 数组位置或 `render_index` 升序直接排层。
  7. **靶面 A 的最大产出不是某个常数，而是一整层官方字段表 + 默认值**。
     但要立刻钉一条**反用**纪律：`js_model_keys.csv` 的默认值**不能当桌面写入的缺省值回填** ——
     文本 material 的 `check_flag` 模型默认 **63**，而语料 `stats.json -> text_check_flags` 的众数是 **39**（11,180 次），63 只有 87 次；
     `alignment` 模型默认 **1**，而 11.6 的桌面写入**整键缺席**（U-30）。
     这层是 canvas_agent（web 面）的模型，与 F-047 发现的 `version=400000 / os="web"` 属同一套身份，不是桌面编辑器。
     它的正确用法是：**字段是否合法、叫什么名、初值长什么样**的官方白名单，用来给写回做「可写字段」边界。
  8. **U-37 补一条**：`track_attribute` 不只存在于轨道上，**segment 也有同名镜像键**（模型层 segment 表里
     `track_attribute` 默认 0，与 `track_render_index` 并列）。此前规格只在 `tracks[]` 记了 `attribute`。
  9. **文档层不能用来裁轨道**：XML 只有 main/multi 两个容器、没有轨道类型与 `track_index`，
     「mixed」在 references 与 prompts 里 0 命中 ⇒ U-61/U-62/U-63 的证据面仍然只有语料与成片，**本轮零进展**（这是结论，不是遗漏）。
  10. **协议层的「不支持」不等于格式层的「不存在」**：no-support.md 把 `keyframe` 列为不支持写入，
     而 r3 语料里带 `common_keyframes` 键的 segment 有 17,411 个。写回规则里要把「官方 agent 不写」与「草稿格式不允许」分清。

- **Path**：
  - 结案：`evidence/unresolved.md` 的 **U-12**（MixMode 全对应 + 判定方法改写）、**U-03**（`diffuse = 面板 ÷ 600`）、
    **U-02**（两者从不相离，载体是 `solid.alpha`）。
  - 改写：`U-10`（归一化已判、范围只剩 80 条真裁剪的观测下界）、`U-51`（只剩导出分辨率一问）、
    `U-15`（补「官方自己也不写 z_order」的反证与实现警告）、`U-37`（segment 级 `track_attribute` 镜像键）、
    `U-27`（发光协议层无角度字段 → 从「本机 11.6 判不了」升级为「协议也不暴露」）。
  - 新开：`U-64`（`shadows[].feather` / `thickness_projection_*` / `feather_use_diffuse` 三族键到底谁承载模糊）、
    `U-65`（`js_model_keys.csv` 里模型独有 303 键 / 语料独有 404 键的归属：web-agent-only、桌面版本差异，还是规格漏项）。
  - 冲突：`evidence/conflicts.md` 新增 **C-013**（`MixMode.json` 的 nameId 与 GLSL 函数名、草稿中文 name 冲突）。
  - `spec/picture.yaml`：`blend_mode` 段改成「按资源索引直连」的判法、补 10 包全表与两个无本地包的模式、改 `mapping_to_css` 的
    线性加深误注；`opacity`/`mask` 补官方像素换算式；`crop` 补归一化与 `{}` 占比；`compositing_order` 补 z_order 反证；
    `tracks` 补 segment 级 `track_attribute`。
  - `spec/text.yaml`：阴影段补 10 键全表 + `diffuse = 面板 ÷ 600` + float32 形态；`fill` 段写死「solid.alpha 为载体」。
  - `spec/panel-map.yaml`：登记本轮拿到的面板与字段换算（volume 0-1000 默认 100、filter intensity 百分制、
    canvas blur 四档 0.0625/0.375/0.75/1 默认 0.75、描边 0-100、抠像 feather/expand 双量纲 0-100 与模板槽 0-1000）。
  - `spec/write-rules.md`：补「模型默认值不等于桌面缺省，禁止按 `js_model_keys.csv` 回填」与
    「协议层 no-support 不构成格式禁令」两条；十七条不要用（现二十条）追加两条。
  - `spec/format-reference.md` 与 `spec/00-overview.md`：同日同步（F-049 入册、U 数与结案列表、表数 12 → 18）。
  - 工具：`scripts/mixmode_join.py`、`scripts/field_census.py`、`scripts/js_model_extract.py`（新）；
    派生表 `tables/{mixmode_packages,mixmode_draft_paths,shadow_style_keys,video_crop_census,fill_alpha_pairing,segment_index_keys,js_model_keys}.csv`（新 7 张；
    `segment_index_keys.csv` 顺手量出片段级次序键的键存在数：`render_index` 33,561 / `track_render_index` 42,407 / `track_attribute` 18,188 /
    `group_id` 16,691 / `template_id` 17,699 / `visible` 18,621（均在 51,718 个顶层片段中））；
    临时件 `temp/rea/js_markers.py`、`temp/rea/js_model_diff.json`、`temp/rea/F-049.md`。
  - `evidence/toolchain.md`：新增「REA 复跑记录（2026-10-21）」—— `--max-semantic-nodes(-per-file)` 与
    `--token-limit/--filter-output` 是 F-047 没发现的可调预算；`analyze-web-bundle` 因需要活的 CDP 端点（会让目标页面自己发请求）
    越 `network_profile`，列入明确不执行。


## F-050 `tracks[].flag` 是官方枚举，语义由「首条 video 轨从不为 2」与「flag=1 有 96.7% 装字幕」双向定死（U-61 结案，U-62 拿到新判别式，2026-10-21）

- **证据等级：已验证**（两路独立：安装包前端 chunk 里读出的**枚举定义**，与 r3 全量语料里该字段的**分布/内容相关性**，
  两边互相预测成立）。

- **Evidence**：
  - **枚举本体**（`app/static/js/` 反直觉地用 `e[e.Name=digit]` 反向映射写死，`grep -oE '"?Flag[A-Za-z]+"?[=:][0-9]+'`）：
    `FlagNone=0`、`FlagTextSubtitle=1`、`FlagSubVideo=2`、`FlagTextLyric=3`、`FlagVideoSubtitle=4`、
    `FlagAudioSubtitle=5`、`FlagAiScriptSubtitle=6`。
  - **官方模型层把 `flag` 当枚举字段声明**：`ai-creation~11.aa2812ea.js` 的 track 类构造器写
    `e.type=a.HQ.TrackTypeNone, e.segments=[], e.flag=a.JO.FlagNone, e.attribute=0, e.name="", e.isDefaultName=!1`。
  - **官方自己的写入规则**（同一批 chunk 里三处）：
    `track.type === TrackTypeVideo && track.flag === FlagNone` 时**改写为 `FlagSubVideo`**
    （`ti.flag = e.flag===FlagNone ? FlagSubVideo : e.flag`，另两处同型）⇒ 2 是「副视频」，由插入新 video 轨时补上。
  - **语料交叉表**（`scripts/track_flag_census.py` → `tables/track_flag_semantics.csv`；
    2,050 份内容、9,990 条轨道、3,195 条 video 轨）：

    | video 轨位置 | flag=0 | flag=缺席 | flag=2 |
    |---|---|---|---|
    | **首条 video 轨** | 575 | 958 | **0** |
    | 非首条 video 轨 | 0 | 0 | **1,662** |

    即 1,533 份有 video 轨的内容里，**主轨的 flag 只会是 0 或整键缺席（1,533/1,533），其余 video 轨 100% 是 2（1,662/1,662）**。
  - **text 轨按「装了什么素材」反验**：`flag=1` 的 1,004 条里 **971 条（96.7%）** 装 `texts.type=="subtitle"`；
    `flag=0` 的 606 条里只有 61 条（10.1%）装字幕，**111 条装的是 `text_templates.text_template`（文字模板/花字轨）**；
    `flag` 缺席的 827 条里 657 条纯装 `texts.text`、字幕只占 110 条（13.3%）。`flag=3` 全语料只有 2 条且都不带可解析片段。
  - **mixed 轨的 flag 只有两种形态，且与内容强相关**：`flag` 缺席的 315 条里 **298 条纯装 `videos.video`**（+7 `videos.photo`）、
    **一条都不装文字**；`flag=2` 的 510 条里 227 条装 `texts.text`、206 条装 `videos.video`、34 条装字幕、13 条 `videos.photo`、
    9 条 `video_effects`、8 条 `placeholders.adjust`。mixed 从不写 1/3/4/5/6。
  - audio / effect / sticker / adjust / filter 五类轨道的 `flag` 只有 0 与缺席两种形态（缺席数分别 1,722 / 267 / 137 / 150 / 17），
    与非零值零出现一致 —— 枚举里 4/5/6（视频字幕、音频字幕、AI 脚本字幕）**在本机 2,050 份内容里一次都没写过**。

- **Finding**：
  1. **U-61 结案，而且答案是「两者都对一半」**：`flag` 既不是主轨标记，也不是笼统的「轨道类型 tab」，
     而是官方的**轨道内容类别枚举**（7 值）。对桌面写入器实际生效的只有三条：
     **1 = 字幕轨（FlagTextSubtitle）**、**2 = 副视频轨（FlagSubVideo，即"不是主轨的那条 video 轨"）**、
     **3 = 歌词轨（FlagTextLyric，语料仅 2 条，属推断级）**；0 与整键缺席都表示「没有类别标记」。
  2. **这顺带把 F-047 的「主轨 = `tracks[0]`」加强成一条可直接用的判据**：主轨 = **首条 `type=="video"` 的轨道，且它的 `flag ∈ {0, 缺席}`**；
     反过来 `flag==2` 就是「画中画/副视频」的充分必要标记（语料 1,662 条无一例外）。
     原 F-047 的「唯一 `flag==2` 落在首条 video 轨的比例 0/206」是同一件事的抽样版本，现在是全量 0/1,533。
     **写回侧新增一条不变式**：新建 video 轨必须写 `flag=2`，且**不得**给首条 video 轨补 `flag=2`。
  3. **官方 chunk 里的归一化规则解释了为什么 video 轨的 0 与缺席并存**：agent 层在插入时把 `FlagNone` 主动改写成 `FlagSubVideo`，
     而桌面编辑器对主轨干脆**不写这个键**（958/1,533）或写 `0`（575/1,533）⇒ 读侧必须把「缺席」与 `0` 当同一状态，
     这正是本项目「键存在 ≠ 有值」纪律的又一个实例。
  4. **U-62（mixed）拿到一条可操作的判别式，但仍不结案**：mixed 的两种 flag 形态对应两种完全不同的内容构成 ——
     **缺席 = 纯视频容器（298/315 只有 `videos.video`，零文字）**，**2 = 真混装容器（45% 装文字、40% 装视频，还会装 video_effects/placeholders/photo）**。
     这比「mixed 是一条装多种内容的轨」更精确：**`flag` 缺席的 mixed 其实不是混装，是另一种视频轨**，
     把它和 `flag==2` 的 mixed 当成同一类去分派渲染会错。另注意 mixed 从不写 `name`（F-048），
     所以这两类在面板上都没有可显示的轨道名。判定方法改为：取 `flag` 缺席的 mixed 轨与 `flag==2` 的 mixed 轨各一条，在剪映里看面板归属。
  5. **枚举 4/5/6（视频字幕 / 音频字幕 / AI 脚本字幕）在桌面语料里零出现，但 chunk 里有定义** ⇒
     它们是 agent/云侧写入面的类别（对应 `subtitle_recognize` / `lyric_recognize` 产出的轨道），
     规格要登记为「合法但本机语料未见」，M3 写回时**不要主动产生**它们，也不要因为不认识就改写掉。
  6. **方法学收获**：F-047 只读了 `runtime/app-server.mjs`，而**枚举与默认值在 `app/static/js/` 的 chunk 里**（`ai-creation~5/10/11`）。
     这层用 `grep -oE '"?EnumName[A-Za-z]*"?[=:][0-9]+'` 就能直接抠出枚举全集，不需要 REA、不需要 native。

- **Path**：
  - `evidence/unresolved.md`：**U-61 结案**（枚举 7 值 + 桌面只用 0/1/2/缺席 + 主轨加强判据），
    **U-62 改写**（`flag` 缺席的 mixed 是另一种视频轨，不是混装；判定方法换成两条轨的面板归属对照）。
  - `spec/layout.yaml`：`main_track` 判据从「`tracks[0].type=="video"`」升级为「首条 video 轨且 `flag ∈ {0, 缺席}`」，
    并把 `flag` 的枚举全集与逐值证据登记进去。
  - `spec/picture.yaml`：`tracks.flag_values_by_type` 补枚举名与 4/5/6 零出现的说明；新增 mixed 的 flag/内容双形态。
  - `spec/write-rules.md` §3：新增「新建 video 轨写 `flag=2`、首条 video 轨不得写 2」与
    「缺席与 0 等价，禁止为补齐而写 `flag:0`」两条不变式。
  - `spec/format-reference.md`：轨道层与写回两节同日同步；「不要用」清单追加第 25 条（不要把 `flag` 缺席与 `flag=0` 当两种状态，
    也不要把 `flag` 缺席的 mixed 当混装轨）。
  - 工具与产物：`scripts/track_flag_census.py` → `docs/evidence/tables/track_flag_semantics.csv`（三段：
    video 按位置 × flag、逐轨道类型按「装的素材类型」× flag、枚举定义出处）。


## F-051 版本轴实地清点：「13 个版本目录」里 12 个不是安装，是更新载荷；可用的只有 11.1.0（在「- 副本」里）与 11.6.0 两个完整安装（就地更正 toolchain/scope 的版本目录数，给 U-60 加一条硬约束，2026-10-21）

- **证据等级：已验证**（纯只读清点：逐目录 `find -type f` 计数 + `Resources/`、`JianyingPro.exe` 存在性 + 文件名后缀形态 +
  一份 374 B 的 `JianyingProPacket.xml` 直读 + 两个 `MixMode.json` 的 sha256 比对）。

- **Evidence**：`<JY_INSTALL>\` 下共 **15 个子目录**（13 个版本名 + `11.1.0.14287 - 副本` + `202687173850092_1`）：

  | 目录 | 文件数 | `Resources/` | `JianyingPro.exe` | 带 `_d_<hex>` 后缀的顶层项 |
  |---|---|---|---|---|
  | 10.5.0.13988 | 37 | 无 | 无 | 26 |
  | 10.6.0.14057 | 77 | 无 | 无 | 66 |
  | 10.7.0.14095 | 77 | 无 | 无 | 66 |
  | 10.8.0.14162 | 77 | 无 | 无 | 66 |
  | 10.9.0.14199 | 77 | 无 | 无 | 66 |
  | **11.1.0.14287 - 副本** | **4,052** | **有** | **有** | 0 |
  | 11.1.0.14287 | 64 | 无 | 无 | 62 |
  | 11.2.0.14339 | 77 | 无 | 无 | 66 |
  | 11.3.0.14362 | 37 | 无 | 无 | 26 |
  | 11.4.0.14410 | 37 | 无 | 无 | 26 |
  | 11.4.1.14443 | 63 | 无 | 无 | 61 |
  | 11.4.2.14459 | 37 | 无 | 无 | 26 |
  | 11.5.0.14471 | 37 | 无 | 无 | 26 |
  | **11.6.0.14552** | **5,192** | **有** | **有** | 0 |
  | 202687173850092_1 | 2,468 | 无 | 无 | 0（只有 `JYPacket/` + `JianyingProPacket.xml`） |

  - `202687173850092_1/JianyingProPacket.xml` 直读：`<cid cid="jianyingpro_0"/>`、`<appver value="11.2.0"/>`、
    `<full_appver value="11.2.0.14339"/>`、`<verify enable="1"/>`、`<release_type value="release"/>`、
    `<item path="\\JYPacket" filetype="4"/>` ⇒ 它是 **11.2.0.14339 的下载/更新包暂存目录**，不是版本安装。
  - `Resources/` 顶层差集（`11.1.0.14287 - 副本` → `11.6.0.14552`）**只有新增、没有删除**，新增 **7 项**：
    `canvas_agent`、`agent_runtime`、`agent_runtime_env`、`matting_config`、`rule_adjust_mask`、`vip_redeem`、
    `image_h5_smart_voiceover_script_v3`。
  - `Resources/MixMode/MixMode.json` 两处 **sha256 相同 = `ad19693613adcaf33e528b89ac1b96ae92e44807ed968b97cecf9e88e1497b71`**，
    两边都是 10 个包目录（两个都只有 2,055 B）。
  - `Resources/canvas_agent/package-manifest.json`（11.6）自报：`name="custom-agent-macos-arm64-20261008-161642"`、
    `platform="darwin-arm64"`、`canvasAgentVersion="1.0.0"`、`build_ts/packageStamp="20261008-161643"`、
    `git_hash="30ca035fa5eefa90967895c3813ca5f16ef6bbb8"`，且 `tools` 声明自带 `lark-cli / rg / jq / fd` 四个外部件。
  - 11.6 新增的两个小目录：`rule_adjust_mask/algorithm_{custom_lockon,surface,surface_win}.json`（958–1,209 B）与
    `matting_config/`（`ai_matting / ai_matting_gru / ai_matting_video_object / custom_matting` 各自的
    `algorithmConfig.json` + `config.json`）⇒ 是**算法配置**，不含草稿字段。

- **Finding**：
  1. **靶面 B 的前提被推翻：不存在「13 个版本 = 免费的时间轴」**。13 个版本名目录里 **12 个是更新载荷**
     —— 每个只有 37~77 个文件、顶层项普遍带 `_d_<7位hex>` 后缀、既没有 `Resources/` 也没有 `JianyingPro.exe`。
     真正可用于跨版本对比的只有 **两个**：`11.1.0.14287 - 副本`（4,052 文件）与 `11.6.0.14552`（5,192 文件）。
     `compare-application-versions` / `compare-bundles` 这类工具在剩下的目录上只会得出「这版没有这个资源」的假结论，
     因为它们根本不是安装。⇒ **本轮把靶面 B 收缩成「11.1.0 ↔ 11.6.0 一对」**，并给出这对的实际产出（下面 2~4 条）。
     根因：此前 `toolchain.md` §3 与 `scope.md` §1 写的「14 个版本目录 / 13 个真实版本」是按**目录名**数的，
     没有验完整性 —— 已就地更正为「15 个子目录，其中 2 个完整安装」。
  2. **`11.1.0.14287` 这个"正主"目录已经退化成更新残留，可用的 11.1.0 在 `- 副本` 里**（它才有 `Resources/MixMode/`，
     正主没有）。⇒ **U-60 的对照实验必须指定 `11.1.0.14287 - 副本`**，否则会把「11.1 没有这个资源」当成版本差异。
     顺带说明：`layout.yaml` 的版本判别不能依赖安装根目录名，只能依赖草稿内的 `platform.app_version` / `new_version`。
  3. **agent 层是 11.6 才引入的**：`Resources/` 差集里 `canvas_agent`、`agent_runtime`、`agent_runtime_env` 三项都只存在于 11.6。
     这给 F-049 第 7 条（**模型层默认值不等于桌面写入缺省**）补上了机制解释 —— 我们挖的协议与模型层是
     **11.6 新增的 web/agent 面**，不是历代桌面写入器的代码。
     由此给 F-047/F-049/F-050 的全部「官方声明类」证据加一条适用性边界：**它们描述的是 11.6 的 agent 写入面**，
     对语料里 4.8~11.5 的草稿只能作为旁证，不能作为「桌面编辑器当年就是这么写的」的断言。
  4. **混合模式的包集合在本机可验证的版本跨度内是稳定的**：`MixMode.json` 在 11.1.0 与 11.6.0 逐字节相同、
     两边都是 10 包 ⇒ U-12 的结案不依赖版本，M2 可以把它当不变量。
     （语料里 mix_mode 的 `path` 指向 8.0.0 / 9.4.0 / 10.3.0 / 11.2.0 等**本机不存在的安装根**，
     说明这些草稿来自另一台机器；那部分只能算「同包 md5 在别机历代也成立」的观测，不是本机验证。）
  5. **11.6 内嵌的 agent 包自报 `platform="darwin-arm64"`**（Windows 安装里的 macOS ARM 构建）。
     本轮没有因此少读任何东西（全程只读文件），但它意味着：**任何"让内置 agent 跑起来当 oracle"的想法在这台机器上不可行**，
     也再次说明 agent 层与桌面写入器是两套代码。记入 `toolchain.md` 的供应链侧。
  6. **`rule_adjust_mask` 与 `matting_config` 是 11.6 新增的算法配置**，与 U-13（`enable_adjust_mask`，已否定为蒙版开关）
     和抠像面有关，但里面没有草稿字段 ⇒ 归 phase-3 线索，不进 M1 规格事实。

- **Path**：
  - `evidence/toolchain.md` §3：「安装根（14 个版本目录）」改为「15 个子目录，其中**只有 `11.1.0.14287 - 副本` 与 `11.6.0.14552` 是完整安装**，
    其余 12 个版本名目录是更新载荷（37~77 文件、`_d_<hex>` 后缀、无 `Resources/`）」；
    `202687173850092_1` 登记为「11.2.0.14339 的更新包暂存目录」；
    新增一行 `canvas_agent` 的 `package-manifest.json` 自报身份（`darwin-arm64`、`git_hash`、自带 `rg/jq/fd/lark-cli`）。
  - `evidence/scope.md` §1：授权对象里的「14 个版本目录」同步更正（同一根因）。
  - `evidence/unresolved.md`：**U-60 补一条硬约束**（对照实验只能用 `11.1.0.14287 - 副本`；
    且 agent 层是 11.6 新增，故 `version=400000` 那套身份是 web/agent 面的、不是历代桌面行为）；
    给 F-047/F-049/F-050 的官方声明类证据统一加**适用性边界**（11.6 agent 写入面）。新开 **U-66**：
    本机只剩 2 个完整安装，跨版本对照面实际很窄，需要从语料 `platform.app_version` 轴（而非安装目录）重建版本序列。
  - `spec/layout.yaml`：版本判别一节补「安装根目录名不可当版本用」这条否定结论，避免 M2/M3 再踩。
  - `spec/format-reference.md`：版本轴与开放项两节同日同步（U-66 入表）。


## F-052 `render_index` 的分配器规则被整层读出来了：六个族各有基座、`freeRenderIndexModeOn` 在语料里从不为真，而次带**不能**由这套规则产生（U-63 收窄并排除两条解释，U-62 拿到「mixed 不在厂商词表里」，2026-10-21）

- **证据等级：已验证**（分配器规则 = 安装包 JS 源码原文，一次独立通道；分支是否被走到、次带的奇偶 = r3 全量语料，另一条通道。
  两者**结论是「对不上」**，所以本条的主要产出是排除而不是确认）。

- **Evidence**：
  - **`RenderIndexUtils` 全文**（`app/static/js/ai-creation~15.f6ca3ef2.js`，261,147 B；抽取器
    `scripts/render_index_allocators.py` → `tables/render_index_allocators.csv`）。七个分配函数，JS 原文照抄（`e3`/`e4` 是科学计数法）：

    | 分配函数 | `freeRenderIndexModeOn` 为真时 | 否则 | 无 free 分支 |
    |---|---|---|---|
    | `nextVideoRenderIndex` | `2e3 + getVideoCount(true) + 2` | `getMaxVideoRenderIndex + 1` | 轨道类型未知时 `return g`（哨兵） |
    | `nextVideoRenderIndexWithTimeRange` | — | 从 `max(layer)+1` 起，只要 `layerHasEnoughSpace(上一层, 区间)` 就**往下塌一层复用** | 同上 |
    | `nextFilterRenderIndex` | 无 | `max===0 ? 1e4 : max + 1` | **基座 10000** |
    | `nextAdjustRenderIndex` | `7e3 + getAdjustCount(true) + 2` | `getMaxAdjustRenderIndex + 1` | free 基座 7000 |
    | `nextVideoEffectRenderIndex` | `11e3 + count + 2` | `max===0 ? 11e3 : max + 1` | **基座 11000** |
    | `nextPluginEffectRenderIndex` | 无 | `max===0 ? 15e3 : max + 1` | **基座 15000** |
    | `nextTextAndStickerRenderIndex` | `14e3 + getStickerCount() + 2` | `max===0 ? 14e3 : max + 2` | **基座 14000，步长 +2** |

  - **text 与 sticker 共用同一个分配器**（函数名就叫 `nextTextAndSticker`，`getMaxStickerRenderIndex` 是它的唯一输入）
    ⇒ 这就是 F-048 里「text 与 sticker 同占 14000 带」的机制。
  - **`render_index` 会同时写进 clip 的 `layer` / `filter.filterLayer`**：`async/2142.1b79d57f.js` 里贴纸与文字模板的落地代码是
    `y.renderIndex = new RenderIndexUtils().nextTextAndStickerRenderIndex(draftView)` 之后
    `t.filter.filterLayer = BigInt(y.renderIndex)` 与 `r.layer = BigInt(v)`，而 `addTrack(TrackTypeString.EffectTrack, -1)`
    ⇒ 同一条片段上 **render_index 与 layer/filterLayer 是两个写入点，必须同步**。
  - **`[-1,1] 归一化 → 像素` 的换算在同一个 chunk 里以代码形式出现**：贴纸包围盒读取后做
    `left/2 + .5, right/2 + .5, top/2 + .5, bottom/2 + .5` ⇒ 归一化盒是 **[−1,1] 映射到 [0,1]**，
    即 1 个单位 = 半个画幅（F-035 的 `/2` 与 F-049 的协议声明之外，这是**第三条**独立见证，而且是代码不是文档）。
  - **厂商 `TrackType` 词表有 13 项**（扫全部 76 个 chunk 得到 `Name="wire值"`）：
    `none video audio sticker text effect filter adjust text_to_video_text text_to_video_text_audio composition plugin_effect adcube`。
    语料的 8 个值里 **7 个逐字命中**（`video audio text sticker filter effect adjust`），**唯独 `mixed` 一个都不命中**。
  - **`mixed` 只存在于一个闭合的版本区间**（`tables/track_type_by_app_version.csv`，
    逐内容统计 2,050 份内容 / 9,990 条轨道 × `platform.app_version`）：
    `11.1.0` 165 条、`11.2.0` 355 条、`11.3.0` 301 条、`11.4.0` 3 条、`11.4.2` 1 条，**共 5 个版本、825 条**；
    `11.5.0` 与 `11.6.0` 有 video 143/62、audio 81/26、text 102/46 条轨道，**但 `mixed` 是 0**。
    对照 `adjust` 覆盖 4.7.2→11.6.0（29 个版本）、`effect` 30 个版本 ⇒ 不是样本稀疏造成的空洞。
  - **`free_render_index_mode_on` 在 2,050 份内容里从不为真**：整键缺席 1,402 份、`false` 648 份、**`true` 0 份**
    （注意它和 `render_index_track_mode_on` 是**两个不同的根键**，后者 true 1,978 / false 63，`picture.yaml` 记的是那个）。
  - **次带（15000+）的奇偶与空洞**（`tables/render_index_subbands.csv`）：按千位段 × 轨道类型统计，
    `15000` 段 text 254 + sticker 6、`16000` 段 text 14、`17000` 段 text 15、**`18000` 段 0 条**、`19000` 段 text 207。
    合计 text **even 261 / odd 229**、sticker even 3 / odd 3。
    且**同一份草稿的 19000 段里同时有 29 个偶数与 22 个奇数**（表里逐内容那几行）。

- **Finding**：
  1. **主带全部对上**：`10000 filter`、`11000 video effect`、`14000 text&sticker` 三个基座与 F-048 的逐带表一致；
     video 与 adjust 的分配函数**没有非 free 基座**（`max + 1`），正好对应语料里 video/audio/adjust 落在 `0-999`。
     这是「元素类别决定带」这一旧结论第一次拿到**机制**而不是统计。
  2. **`free` 分支整条被排除**：语料里 `free_render_index_mode_on` 从不为真 ⇒ 六个分配函数里只有「否则」那一支
     对桌面草稿生效，`2000/7000/11000/14000 + count + 2` 这套基座**只在 agent/web 面会出现**。
     规格与渲染器都不该按 free 分支解释语料值，但 M3 写回时要认得它（内置 agent 造出来的草稿会落在这套基座上）。
  3. **U-63 的次带不能由 text/sticker 分配器产生**（这是本轮最硬的否定结论）。该函数在非 free 分支是 `max + 2`、
     起点 `14000`，从偶数出发只会得到**偶数**，且必然**连续填满 14000..19000**。而语料次带里
     **text 有 229 个奇数**、`18000` 段**一条都没有**、同一份草稿的 19000 段里奇偶并存（29 even / 22 odd）。
     ⇒ 排除两条解释：① 「+2 溢出」不成立（奇偶与空洞都对不上）；② 「`nextPluginEffectRenderIndex` 的 15000 基座溢出」也只可能对 `15000` 段成立，
     解释不了 `19000` 段那 207 条。剩下唯一可辩护的读法是 U-63 原本的猜测——**按模板/组序号分配**，
     但分配者不在这七个函数里（候选：桌面 Qt 侧写入器，本机读不到）。所以 **U-63 保持 open，但判据从「找共同特征」升级为「奇偶 + 空洞」这种可证伪的形式**。
  4. **U-62 拿到一条词表级证据**：`mixed` 既不在厂商 `TrackType` 的 13 个 wire 值里，又只出现在 11.1.0~11.4.2 这个闭合区间，
     而 `11.5.0/11.6.0` 的其他轨道类型都还在写 ⇒ **`mixed` 是那三个版本里一个具体功能的落盘名，不是一个通用容器概念**；
     按排除法它在 11.6 词表里最可能对应 `composition`（语料 `materials.drafts[].type=="composition"` 有 439 条，同域名支持；
     F-050 又给出 `flag` 缺席的那批 mixed 其实是纯视频轨）⇒ **「mixed = 一条装多种内容」这句要降级**，
     它至多描述 `flag==2` 的那一半。判定方法改成：查 11.1.0~11.4.2 区间里 mixed 轨是否与 `drafts[]`/`compound` 关联。
     同时排除一种偷停：不许把 `mixed` 当 `composition` 直接改名写回，因为两者是否同一值**未被任何一侧证过**。
  5. **`layer`/`filterLayer` 是 `render_index` 的第二写入点**，此前规格里没有。
     写回只改 `segment.render_index` 会造出「片段索引与 clip 层级不一致」的静默错误 —— 归入 M3 不变式。
  6. **`[-1,1] → [0,1]` 的 `x/2+0.5` 以代码形式第三次印证了 `/2`**（F-035 导出实测、F-049 协议声明、本条源码）。
     U-51 的几何半边现在有**三条**独立见证；剩下的仍然只有「导出分辨率翻倍时位移是否跟着翻倍」。

- **Path**：
  - `evidence/unresolved.md`：**U-63 改写**（判据换成奇偶/空洞的可证伪形式，排除 +2 溢出与 plugin 基座两条）；
    **U-62 改写**（`mixed` 不在厂商词表、只活在一个闭合版本区间，"混装容器"降级）；
    **U-15 补第三条旁证**（分配器一律 `max+1`/`max+2` ⇒ 新片段索引更大，配合 `z_order`「越大越靠前」，
    方向性证据从 0 条升到 2 条，但仍非成片实测，不结案）。
  - `spec/picture.yaml`：`compositing_order` 新增 `allocator_rules`（七函数 × 两分支 × 基座，标 JS 出处）、
    `free_mode_never_used`（缺席 1,402 / false 648 / true 0）、`subband_falsification`（奇偶与 18000 空洞）、
    `second_write_point`（`clip.layer` / `filter.filterLayer`）；`tracks` 补 `track_type_wire_values`（13 值 + mixed 不在其中）。
  - `spec/write-rules.md` §3：新增两条不变式——「改 `render_index` 必须同步 `clip.layer`/`filter.filterLayer`」，
    「`free_render_index_mode_on` 桌面从不为真，写回不得开启它，但读侧要认得 free 基座」。
  - `spec/format-reference.md`：轨道与合成两节同日同步；「不要用」清单追加第 26 条（不要把 `render_index` 当单一真相源，
    `layer`/`filterLayer` 是第二写入点）。
  - `spec/panel-map.yaml`：`agent_declared_units` 里给「±1 对应画布边缘、1 单位 = 半画幅」补**第三条**见证，
    且是代码不是文档：贴纸包围盒读回后做 `left/2+.5 / right/2+.5 / top/2+.5 / bottom/2+.5`（`async/2142.1b79d57f.js`），
    即归一化盒 `[-1,1]` 线性映射到 `[0,1]`（F-035 导出实测 + F-049 协议声明 + 本条源码）
  - 工具与产物：`scripts/render_index_allocators.py`（新增）→ `tables/{render_index_allocators,track_type_by_app_version,render_index_subbands}.csv`
    （新 3 张 ⇒ 表总数 20 → 23）。

## F-053 素材索引形状一次量清：GOP=1 s、moov 13/13 在尾部、相机片是 XAVC 4:2:2 + PCM 音轨（U-59 结案、U-55 收窄、新开 U-67，2026-10-21）

**口径**：`<DRIVE_E>/fixtures\1012-1626-fixture\media` 全部 13 个视频文件、每文件 1 条视频轨、单次读数、
2026-10-21；结构层（`stss/stts/ctts/elst/moov`）由新增 `scripts/media_probe.py` 用标准库走 box，
编码语义（codec/profile/pix_fmt/音轨布局）由已备案的 PyAV 18.0.0 给（`docs/evidence/toolchain.md:57`）。
浏览器侧的尾读区间取自既有 `temp/px-probe/media-server.log`（F-038/F-045/F-046 原始日志，**零新跑**），
分析器 `temp/px-probe/firstframe_window.py` → `temp/px-probe/nas-firstframe-window.txt`；
JSON 落 `temp/media-probe/fixture-census.json`。**这是 docs/ 第一次有 GOP 与 moov 位置的实测**，
而 U-55/U-59 两条的路线全压在它们上面。

1. **关键帧间距 = 1 秒**（此前零清点）。相机片（brand `XAVC`，59.94p）**GOP 60 帧 = 1001 ms**、
   50p 两片 **48 帧 = 960 ms**、GOP 字节 5.50–5.96 MB、平均帧 96–117 KB；手机 HEVC 5 片 **60 帧**、
   GOP 字节 7.51–8.09 MB；预设片 b168bb76 **14 帧 = 467 ms**、0.34 MB。
   ⇒ 按 F-042 的每帧成本折算「从 IDR 解到目标」的**前向解码**：4:2:2 1080p 平均 30 帧 ×4.5 ms ≈ **134 ms**
   （最坏 264 ms）；4K HEVC 平均 30 帧 ×8.0 ms（`hevc_cuvid`）≈ **239 ms**。**两条都够不到 150 ms**，
   而 4:2:2 那一路连硬解都没有（F-042 `h264_cuvid` not supported）。
   ⇒ U-55 的两条候选因此**分工改写**：关键帧索引负责首帧与加载，**代理片负责 seek**，且代理的关键
   不是低码率而是「短 GOP + 可硬解的 4:2:0」。判据不变（中位 ≤150 ms），数值待 SP-03 实测替换本条推算。
2. **moov 13/13 在文件尾，零 faststart**。相机片 moov 4–131 KB；手机 HEVC **330–482 KB**（被 `udta`
   元数据撑大）；预设 3 KB。⇒ 任何播放器解第一帧前都必须做一次**远距离尾部读**。
   ⇒ **两条独立仪器互证**：日志里尾读请求 `GET /media/C7459.MP4 range=bytes=268697600-` 传出 **28,785 B**，
   本脚本测得该文件 moov 起点 = **268,697,600**（逐字节相同）、moov 本体 18 KB、moov→EOF 28 KB；
   C7463 尾读 **141,683 B** ↔ 脚本 `to_eof_bytes` 141 KB。
   ⇒ 实现纪律：开区间 `bytes=<moov起点>-` 取的是 **moov 到 EOF 整段**，索引产物按 `to_eof_bytes` 定价，
   不按 moov 本体。
3. **首帧取数窗口 = 恰好两个请求，NAS 首帧的真凶不是字节数**（U-59 结案）。8 轮既有日志逐请求复原，
   形态完全一致：head（起点 0 的开区间，传出 0.50–5.75 MiB 后被播放器掐断）+ tail（moov，完整读完）。
   窗口墙钟：本地 C7459 **0–7 ms**、C7463 **2–5 ms**；NAS C7459 **42 ms**、C7463 **24 ms**。
   ⇒ **原推测「代价在起播前的元数据+首簇取数」被否**：+263 ms（F-046 的 158.8 → 422.1）里取数只占约
   十分之一，差额指向**每请求重连 + 在 SMB 共享上重开文件**（网关对每个响应都发 `Connection: close`，
   `media_server.py:119`）⇒ 处理办法转给 keep-alive/多端口的对照实测（SP-04），预取窗口按常数取即可：
   `min(6 MiB, 一个 GOP)` + `to_eof_bytes`。
   ⇒ 读数纪律：日志时间戳记在响应完成/被掐断的时刻，两个请求走并发连接时先后会互换（有一行出现
   tail 早于 head），所以「墙钟间隔」列是**下界**；请求数、字节数、偏移量可靠。
4. **相机片音轨是未压缩 PCM**：7 条 XAVC 的音频 handler 是 `twos` = `pcm_s16be`（大端 16-bit）48 kHz
   立体声；手机 HEVC 与预设是 aac。⇒ WebCodecs `AudioDecoder` **没有 PCM 这条 codec 串**，主力素材的
   预览音频不能走解码器，必须**按样本取字节 → 翻端序 → 直接填 `AudioBuffer`**（零解码成本、可样本级精确）。
   这条与「预览要多轨混音」的新要求直接相关，见 U-55 旁边的播放器设计记录。
5. **`elst` 单条目但 `media_time` 非零 = 正好 1 帧**：7 条 XAVC 均 `elst` 1 条、`media_time` = 1001
   （59.94p，ts=60000）/ 1000（50p）、rate 1.0；手机 HEVC **无 elst**；预设 1 条 `media_time=0`。
   ⇒ 此前担心的「多条目编辑列表被只认第一条」在这批素材上不成立，但**这一帧偏移必须应用**，
   否则整条时间线偏一帧；而剪映自己的 `source_timerange` 是否已经把它算进去 —— 新开 **U-67**。
6. **B 帧重排深度 3 帧**：XAVC 7 片都有 `ctts`（条目 200–8,800），offset 上限 3003 = 3×1001 ⇒ 从 IDR
   解到目标要按 `G + 3` 计，不能「解到目标就停」。手机 HEVC 无 `ctts`（无 B 帧）。
7. **手机录屏是变帧率**：5 片 `stts` 条目 76–209（平均 57.9–59.1 fps，而 `stts[0]` delta 折算出
   10–12 fps 的假值）。⇒ 「帧号↔时间」必须查 `stts`，不能乘名义帧率；F-042/F-038 里「4K HEVC 60p」
   的说法应更正为**平均约 59 fps 的 VFR**，本条顺带修掉一个自测口径坑（新工具第一版就踩到了，
   修后 `gop_ms` 从 4987 ms 变为 1015 ms）。

**本条判掉/收窄的记录**：判掉 U-59 选项①「按 MiB 预取头部」是 NAS 首帧的解；判掉「本批素材有多条目
edit list」这一风险（跨语料待 SP-11 复量）；收窄 U-55 为「索引 ≠ seek 的解」；给 F-042 的 HEVC 素材
描述补 VFR 更正。

**回写**：`evidence/unresolved.md`（U-55 判定方法改写、U-59 结案、新开 U-67）；
`base-selection.md` 的「仍未测」里 seek 一条挂到 SP-03/SP-04/SP-09。

## F-054 把解码轴从 `<video>` 换成 mediabunny+WebCodecs 实测：索引取块救不了 4:2:2 的 seek，但首帧与能力判定两件事从此有了着落（U-55 判定改口径、U-54 加限定、U-58 拿到无光栅的探针，2026-10-21）

**口径**：`temp/px-probe/webcodecs-probe.html`（新）+ `run_multi_probe.py --page … --tag wc`，
headless Chrome 155（`CHROME = C:/Program Files/Google/Chrome/Application/chrome.exe`），
媒体经既有 `media_server.py`（`cache=False clamp=0`，即 `no-store`）；seek 用**与 F-038/F-045
同一条目标公式** `d*(0.05+0.9*((i*7)%8/8))`、n=8、**窗分母取实际渲染窗**；每格单次读数（无重复，
散布待补），峰值 RSS 由启动器 1 Hz 进程树采样。原始行 `temp/px-probe/browser-report-wc.jsonl`，
汇总 `wc-report.txt`/`wc-samples.json`。取数两模式：`url` = mediabunny `UrlSource`
（开区间 `bytes=pos-`、自带 64 MiB 缓存、parallelism 2）；`custom` = 自研 `CustomSource.read(start,end)`
闭区间精确取块 + 32 MiB 缓存 + 自己计数字节/请求。

| 素材 | 模式 | 元数据 ms | 首帧 ms | 管道 fps | seek 中位 / 最大 ms |
|---|---|---|---|---|---|
| b168bb76 预设 8bit 1080x1920 30p | url | 63.1 | **42.6** | （短素材不计量） | **22.1** / 42.1 |
| HEVC 4K 手机片（带 GPU） | url | 68.1 | 24.6 | **369.93** | **58.3** / 158.8 |
| HEVC 4K 手机片（带 GPU） | custom | 28.0 | 35.7 | **379.34** | **60.7** / 145.4 |
| C7459 XAVC 4:2:2 10bit（带 GPU） | url | 52.0 | 14.7 | 163.14 | **216.8** / 426.4 |
| C7459 同上 | custom | 21.1 | **2.7** | 147.43 | **207.6** / 455.2 |
| C7459 同上（`--disable-gpu`） | custom | 26.5 | 5.1 | 149.90 | **206.7** / 441.0 |
| C7463 1.6 GB（带 GPU） | url | 48.3 | 14.3 | 164.71 | **277.1** / 444.7 |
| C7463 同上 | custom | 24.1 | 12.5 | 148.46 | **257.8** / 454.8 |
| **HEVC 4K（`--disable-gpu`）** | custom | 22.4 | **抛错，无首帧** | — | — |

1. **U-55 的 (i)「关键帧索引 + 闭区间取块」被实测否证为 seek 的解**：C7459 中位 216.8 → 207.6 ms、
   C7463 277.1 → 257.8 ms，只比 `<video>` 的 266.7 / 278.2 ms 好 4–20%，**仍远超 150 ms**。
   ⇒ F-040 归因于「`<video>` 开区间预取」的取数解释**不是主因**；F-045 的「定位关键帧 + 解码前进」指纹
   在自建管线上原样复现，说明这是**素材结构 + 解码后端**的成本，换播放器不换不掉。
2. **成本模型被两列数据钉住：`seek ≈ (GOP/2) ÷ 管道fps + 取数`**。4:2:2 软解管道 147–165 fps ⇒
   GOP 60/2=30 帧 ≈ **182–204 ms**（实测 207/258）；HEVC 硬解管道 370–379 fps ⇒ 同结构 GOP 只要
   **≈ 79 ms**（实测 58–61，**达标**）。⇒ **seek 的杠杆是解码后端（profile 是否可硬解），不是索引**。
   ⇒ 代理片的规格因此有可判目标：**4:2:0（可硬解）比短 GOP 更关键**——即使保持 60 帧 GOP，
   370 fps 的管道也已把中位压到 ~80 ms。U-55 判定改口径为此。
3. **首帧判据被大幅刷新**：2.7–35.7 ms（闭区间模式 2.7/5.1/12.5 ms），而 `<video>` 是 85.2–110.2 ms
   （F-038）、F-045 六轮散布 108.9–228 ms。阈值 300 ms 的余量从「~2–3 倍」变成「~10–100 倍」。
   ⇒ **U-59 的 NAS 首帧 422 ms 破线问题因此有了新解法**：不是预取更多 MiB，而是**换成闭区间精确取块**
   （元数据 21–28 ms，且不再开区间乱序预取）。与 F-053 §3（连接开销）合并进 SP-04 一起验。
4. **静默黑帧第一次拿到显式信号**：无硬件通路时 mediabunny 直接抛
   `This video track cannot be decoded in this environment. Make sure to check decodability before
   using a track.`，且**容器/元数据那一段照常成功**（22.4 ms）⇒ 失败点精确落在解码能力，不在解封装。
   ⇒ 这修正 F-044 的表述：软件通路上 HEVC **不是"慢"而是"不可解"**（F-038 的 0 帧不是探针错觉的一半）；
   同时降级阶梯的「能力判定先于上屏」第一次有可依赖的 API，而不是靠 `videoWidth==0` 反推。
5. **闭区间取块很"话痨"**：单次 seek 触发 **11–62 个请求 / 0.65–6.5 MB**，一整轮（3 素材）打出
   **1,887 请求 / 195 MB**；在 `media_server.py:119` 的 `Connection: close` 下每请求一次新连接。
   ⇒ 这把旧方案「17–82 个元素在同一 HTTP/1.1 源上排队」的失败**量化到了每次 seek**，
   并让 **keep-alive / 多端口从"优化项"升级为"自建管线的前置条件"**（SP-04，现为 M2 门禁）。
   ⇒ 一次 seek 里出现 `[7.71 s, 0 字节, 0 请求]` 是 32 MiB 缓存命中，属正常。
6. **U-58 拿到一个不含光栅变量的探针**：WebCodecs 的 seek/管道读数**根本不经过 WebGL**，
   所以「硬解 vs 硬栅」可以这样分离——同素材同模式只切 `--gpu`：C7459（4:2:2，本来就软解）
   **206.7 vs 207.6 ms、149.9 vs 147.4 fps，纹丝不动**；HEVC 4K 则是「能解 58 ms」vs「直接抛错」。
   ⇒ 这实证 F-043 那两列的差**不是解码器差**（4:2:2 一路两列同速），并给出 U-58 的结案工具。
7. **层数准入由此得出**：软件 4:2:2 聚合 147–165 fps ⇒ 60 fps 播放只养得起 **≈2.5 路**；
   硬解 HEVC 370–379 fps ⇒ ≈6 路。而 F-053/语料侧同屏层数 p99=6、max=12 ⇒
   **瓶颈正是"不能硬解的那一类素材"**，T3 的准入上限必须按 profile 算而不是按常数算。
8. 内存：三轮峰值 RSS **1,026–1,062 MB**（阈值 2 GB），JS 堆仅 35.7–103.5 MB ⇒ 与 F-043
   「RSS 全在媒体/ANGLE 侧」同向，自建管线没有把它推高。

**本轮踩到的探针坑（必须记，否则会误读）**：`run_multi_probe.py` 先拼 `playms=<默认 2500>` 再拼
`--extra`，URL 里出现两个 `playms`，`URLSearchParams` **取第一个** ⇒ 我传的 `playms=2000/1000`
全部无效，八格读数实际都是 **2500 ms 窗**（彼此仍可比，但不要拿 `window_ms` 去反推参数）。
另：`--only 1,2` 那次 HEVC 行没有 seek 数据，因为它走了 error 分支（见第 4 条），不是掉数。

**回写**：`unresolved.md` U-55（判定改口径）、U-54（加"软件通路不可解"限定）、U-58（结案工具）；
`base-selection.md` 的「仍未测」seek 一项按本条更新，判据不变（seek 中位 ≤150 ms）。

## F-055 原生只读静态逆向批次（N-01…N-21）：桌面草稿层的名字、地址与序列化架构一次拿到，`draft_store` + 1,102 对 `to_json`/`from_json` + 292 类补丁三件套（新开 U-68…U-72、U-74，2026-10-22）

**口径**：目标 `videoeditor.dll` 11.6.0.14552（72,547,608 B，sha256 `8cfcbb61…`，与 `toolchain.md` 逐字节一致）。
两路通道：① `scripts/pe_harvest.py`（标准库、mmap **只读**，不加载不执行）；② REA 6.5.0 的 Ghidra 12.1.4 provider
经 **MCP stdio 活会话**（`scripts/rea_session.py`），四次会话共 129 步。逐条见证、方法与五次方法错误记在
[`native-re-log.md`](native-re-log.md)（N-01…N-21），本条只记结构级结论。
**边界**：全程只读静态；未取任何算法/密钥；伪代码只落 `temp/rea-native/`（不入库），docs 只留结构与格式结论（scope §1.1）。

1. **草稿 JSON 的字段名是这块 DLL 自己的字面量** ⇒ 按 §6.1 分工，「字段叫什么、哪些值合法」这一类问题从此
   **原生二进制也是权威源**（此前只有 `canvas_agent` 的 agent 面 + 语料）。
   见证：语料四组键表 98 个键里 **97 个**能在 `.rdata`+`.data` 的 20,470 个标识符形字面量里命中（N-02）。
   **短键是弱见证**（`id`/`name`/`type`/`text`/`video` 到处出现），强见证是长键
   （`uneven_animation_template_info`、`auto_sort_affected_tracks`、`render_index_track_mode_on`）；不要把 97/98 当逐键等权。
2. **唯一缺席的键是 `business_info`，且升级为双路确认**（N-02 字节级 + N-13 镜像级 124,028 条字符串清点，两种分母口径都是 0）
   ⇒ 11.6 桌面 `videoeditor` **根本不写这个键**，存在第二个写入者（候选 agent 面 / 云端回灌）。
   这是「有第二个写入者」的证据，不是语料错误（§6.1 第 3 条）。新开 U-68。
3. **框架分层由 mangled 类型名直接给出**（34,703 个 `.?A` 名字，按最外层命名空间）：
   `std` 18,653 / global 9,530 / **`lyra` 3,930**（编辑器主域）/ **`lvve` 1,957**（草稿+加密层，黑盒调的 `EncryptUtils@lvve` 在此）/
   `CryptoPP` 213 / `clipflow` 129 / `vesdk` 129 / **`draft_store` 18 个类型名** / `nlohmann` 11。
   另有 `lyra::reqMakerImpl<Req,Resp>` 成批的**操作词汇表**（N-04）与 24 张 `const char*` **反射表**（N-05）。
   反射表是 **agent/协议写入面**的 schema（含 `auto_sort_affected_tracks`/`remove_empty_tracks`/`return_affected_segments`
   这类请求参数），**不是**桌面草稿序列化表；指针表顺序=声明顺序，故表内字段次序可用。
4. **桌面草稿持久层的真名是 `draft_store`**（N-11 导出表 + N-12 Ghidra 全量分析两路一致）：
   导出名含 `draft_store` **860** 条；Ghidra 解粘后 `draft_store` **771 个函数**，按类为
   `DraftStore` 213 / `StoreWrapper` 205 / `DraftUploadCloudStore` 69 / `DraftRestoreCloudStore` 49 /
   `DraftStoreManager` 44 / **`DraftMaterial` 41**（语料 42 个 bucket 的程序侧对应物，按 `MaterialType` 枚举分桶）/
   **`MultiTimelineContext` 21**（本项目主场景）。
   ⇒ N-07 第 2 问结案：**序列化不在 `nlohmann` 层**（它只有 11 个类型名，规模不符），而在 `draft_store`。
   关键地址：`ReadDraftMetaJsonMaterials` `0x1812b2d20`、`FillDraftMetaJsonMaterials` `0x1812af7b0`、
   `CreateDraftMetaJsonString` `0x1812ae9a0`、`getDraftMetaJsonFile` `0x1812be140`。
5. **单条素材元信息的键面是闭合可枚举的 18 个**（N-20，`ReadDraftMetaJsonMaterials` 全量伪代码 47,236 code units / 24 页）：
   `ai_group_type create_time draft_materials duration enter_from extra_info file_Path height import_time
   import_time_ms item_source material_color_tag metetype roughcut_time_range start sub_time_range value width`，
   调用面 120 点 / 28 个被调函数。其中**按键读取绑 17 个键、按键写入只绑 9 个**
   （`create_time duration enter_from file_Path height import_time import_time_ms item_source width`）
   ⇒ **读写面不对称**，M3 不能假定「读得到就写得出」。新开 U-69/U-70/U-71。
   命名要**照抄不规范化**：`file_Path` 的 `P` 是大写、`metetype` 没有下划线（§6.1 第 3 条）。
6. **草稿 JSON 的序列化架构 = nlohmann ADL 自由函数重载集 + 一层补丁三件套**（N-21，来自 116,637 行函数表）：
   `lvve::to_json` **1,102** 个实例（族共 1,110）、`from_json` **1,159**，**一类型一对**；其上另有
   `patch_from_json` **292**、`to_patch_json` **281**、`dirty_node_to_patch_json` **293**（每类一个成员）。
   把 N-16 的 556 个字段名引用点落到函数（`procedures.tsv` 115,800 行，以下一个入口为排他界的区间近似）：

   | 字段 | 引用点 | 不同函数 | 分布要点 |
   |---|---|---|---|
   | `material_id` | 235 | 174 | to_json 45 / from_json 42 / patch 18 |
   | `check_flag` | 127 | 74 | to_json 17 / patch_from_json 16 / to_patch_json 16 |
   | `uniform_scale` | 85 | 32 | **to_json+from_json 为 0**，全在补丁三件套 |
   | `responsive_layout` | 49 | 21 | 同上，只在补丁面 |
   | `draft_content`（文件名） | 2 | **1** | `draft_store::StoreWrapperInitInfo::StoreWrapperInitInfo` |

   ⇒ **要写回草稿，该对标的是这 292 类补丁三件套，不是那 1,100 对全量序列化器**；
   片段级字段（`uniform_scale`/`responsive_layout`/`mix_mode`）**属补丁面**，全量面上一个引用都没有。新开 U-72。
7. **文件名字面量里出现两个本项目没见过的注册表文件**：`root_meta_info.json`、`root_draft_meta_info.json`（N-14 第 4 条）。
   `draft_meta_info.json` **不是新发现**（F-028 写入足迹 + `spec/format-reference.md` + `spec/write-rules.md` 早已记录），
   本条只贡献**第二路独立印证**（这些名字由原生代码引用，不只出自 `canvas_agent` 常量）。
   源码树泄露 `C:\32139\videoeditor\lyra\trash_src\draftstore\draft_store_manager.cpp` ⇒ 模块布局 `videoeditor/lyra/<模块>/…`，
   且 **draftstore 挂在 `trash_src` 下**。
8. **成本与可复用性判定**（N-09/N-10/N-12/N-20/N-21，决定以后怎么用这条通道）：
   全量 auto-analysis 实测 **3,101.5 s / 2,976.1 s / 2,632.6 s**（三次会话各付一次，**没有一次能省**）；
   付完之后**每个查询 0.0–3.6 s** ⇒ 「一次分析批量取证」成立。
   但 snapshot 与 retained evidence **都不跨会话**（`cli.md:200-206`「cached observations, not a saved provider database」；
   实测 `evidence_integrity_mismatch`），会话 4 因此又付了一遍 2,632.6 s 才拿到两张全表。
   ⇒ **结论：一次会话问完 + 把地址→函数映射落成 `temp/rea-native/procedures.tsv` 离线复用**（已落，556 个引用点→函数零成本）。
   斜率 ≈34 s/MiB；`.text` 50.7 MB、`.rsrc` 仅 480 B（⇒「资源段里藏 schema」这条路不存在）。
9. **RTTI 继承图没有建立**（N-06 撤回记录）：容器格式的真正形状（基类/字段偏移）仍是 Ghidra 侧未做的活，新开 U-74。
   两轮判据都错（「前置两个零字」0/34,703；CFG `EncodedTypeDescriptor` 假设解引用落到 `api-ms-win-*` UTF-16 串池），
   脚本里已删除该判据，只留中性观察值 `leading_qword_observation`。

**Path**：`temp/rea-native/`（`harvest-report.json`、`rtti.json`、`literals.json`、`name-tables.json`、`cross-check.json`、
`session-videoeditor/` 22 份、`session-deep/` 88 份 146 MB、`session-tables/` 48 份、`bundle-tables.json` 78,572,639 B、
`procedures.tsv` 115,800 行、`field-referrers.json`、`tables-summary.csv`）；脚本 `scripts/pe_harvest.py`、`scripts/rea_session.py`。
逐条 Evidence/Path/等级见 `native-re-log.md`。

**回写**：`unresolved.md` 新开 U-68…U-72 与 U-74，并给 U-16 加一条「围栏变了但绑定不恢复」；
`toolchain.md` §1/§2/§4 补 Ghidra+JDK 溯源、四次会话时间账与白名单命令；`corpus-scan.md` 按 F-056 更正采集口径。

## F-056 E: 草稿根不是覆盖缺口，是**逐字节镜像**：486 个内容文件里 480 个与 D: 同摘要；真正让 r3 数字动的是 6 天漂移（就地更正 N-19 的分母推断，2026-10-22）

**口径**：同一台机、同一套脚本（`scripts/corpus_scan.py`），两条腿各跑一次全量，**每次自带 §4 只读证明**
（随机分层 40 份内容文件全文件 sha256，起止重算）——两腿都 `unchanged: true`、`mismatched: []`、`drafts_failed: 0`。
按内容去重（`sha256(解码后 JSON)`，密文按密文摘要），引用时带 `corpus.snapshot_date`。
r3 仍是**在册基准**（`temp/corpus-scan/` = 10-16 那一份原样还原），两次重扫另存
`temp/corpus-scan-r4d/`（漂移控制腿）与 `temp/corpus-scan-r4de/`（双根实验腿），三者都进了 `check_doc_counts.py` 的可绑定证据清单。

| 快照 | 日期 | 根 | 内容文件 | 去重内容 | 目录记录 |
|---|---|---|---|---|---|
| r3（在册基准） | 2026-10-16 | D 单根 | 2,215 | **2,050** | 2,450 |
| r4-d（控制腿） | 2026-10-22 | D 单根 | 2,268 | **2,089** | 2,503 |
| r4-de（实验腿） | 2026-10-22 | D+E | 2,754 | **2,095** | 3,134 |

1. **N-19 的推断按内容口径作废一半**：它按「目录数少 629 / `draft_content.json` 少 416」推出
   「r3 分母系统性偏小约 19%」，那是**把文件数当内容数**。实测 E: 的 486 个内容文件里
   **480 个的摘要与 D: 某个文件逐字节相同**，只有 **6** 个是新内容。
   ⇒ 去重内容 2,050 → 2,095（**+2.2%**），其中 **+39 来自 D 根 6 天漂移、+6 来自 E 根**。
   一切引用 r3 频次的结论**不因 E 根而失真**；失真风险来自漂移（下一条）。
2. **漂移才是主因**：10-16 → 10-22 的 D 根单腿就有 added 66 / removed 13 / **内容变了 94 个文件**（14 个草稿目录），
   数值叶子变化 **1,975 项**，个别文本键下移最多 **−18.1%**（`texts.recognize_model` 4,976→4,077、
   `group_id` 16,726→15,827、`subtitle_keywords` 16,690→15,802 同幅联动 ⇒ 是**少数几份字幕大户草稿**改写/离场，
   不是普遍退化）。实验腿相对控制腿只有 **1,173 项**变化，且绝大多数是 `+0.7–1.0%` 的 effects 侧
   （`bucket_keys.effects.*` 齐涨 **+523** = 那 6 份新内容里的一份带 523 条 effects）。
   ⇒ **交付表不能靠「换基准」来吸收漂移**：一换就要重生成 `docs/evidence/tables/` 全部 CSV 并让 1,339 处引用重新过账，
   代价大且会把「漂移」与「覆盖」两件事混在一起。做法是**引用带快照日期 + 用差分说明量纲**（与 r2→r3 那轮同法）。
3. **对 M3 的真风险不是覆盖，是同名双根副本**（注册表 `root_meta_info.json` 只读清点，2,126 条）：
   D 根 **1,497** 条、E 根 **629** 条，其中 **628 组的草稿目录名在两个根同时存在**，
   而两遍的 `draft_id` **无一相同**（0 组同 id，628 组异 id），且 580/628 组的 `tm_draft_create`/`tm_draft_modified`
   **逐位相同** ⇒ E 侧是**整目录复制后重新注册**的一批，另有 42 组 E 更新、6 组 D 更新。
   ⇒ **按草稿名定位会有 628 个歧义**，写回前必须用「注册表条目 + `draft_fold_path` 的根」而不是名字。
   `tm_draft_removed` 为真的一侧 D 126 / E 27。新开 U-73。
4. **注册表承载版本字符串，但不是桌面那一段**（就地更正 N-18）：`draft_new_version` **不是全空**——
   1,798 条空、**328 条有值**（`114.0.0` 82、`164.0.0` 80、`129.0.0` 40、`93.0.0` 29、`106.0.0` 28、`97.0.0` 20、`163.0.0` 10、
   `110.0.1` 10、`139.0.0` 8、`87.0.0` 4、`133.0.0` 3，其余零散），而 U-60 在桌面草稿里观测的
   `new_version` 区间是 **179.0.0…189.0.0**（11.1.0→11.6.0）⇒ 注册表里这批**低于桌面当前区间**，
   是老草稿/别的产品线留下的，不能与草稿内 `platform.app_version` 混用。`draft_type` 仍 2,126 条全空（原判定不变）。
   `tm_draft_modified` 单位是**微秒**（跨度 2023-10-25 → 2026-10-22，本轮当天仍在被写）。新开 U-75。
5. **修扫描器的不是数据而是一个 bug**：`cache.py::_roots()` 把 `JY_DRAFT_ROOTS` 整串当**一个**路径
   （`values = [override]`），所以「设两个根」从来只有第一个生效——本条实验腿能跑出双根，是因为已改为
   按 `os.pathsep` 切分（Windows 上即 `;`）。N-19 原文「修法不需改代码」同步就地更正。

**Path**：`temp/corpus-scan-r3/`、`temp/corpus-scan-r4d/`、`temp/corpus-scan-r4de/`（各含 `stats.json`/`manifest.json`/`csv/`，
实验腿另有 `e-root-check.txt`、`registry-root-check.txt`、`registry-probe2.txt` 三份一次性清点输出）；
差分 `temp/diff-r3-to-r4d.txt`；脚本 `scripts/corpus_diff.py`（新，manifest 模式算覆盖/漂移归因、stats 模式算数字叶子）、
`scripts/jy_crypto/cache.py`（双根切分）、探针 `temp/e_root_check.py`、`temp/registry_root_check.py`、`temp/registry_root_probe2.py`。

**回写**：`corpus-scan.md` 采集口径第 1 条改为「两个根 + 镜像关系」并加 r4 双腿小节；
`native-re-log.md` N-19 与 N-18 就地更正；`unresolved.md` 新开 U-73（双根哪侧活）、U-75（注册表版本值域）；
`scope.md` §1 的「数据对象」已把 **E: 根**与**注册表清点**写进在册项（E 根凭用户 2026-10-22 批准「按 N-19 建议起双根重扫」纳入，
注册表凭 2026-10-21 的只读分析授权；`com.lveditor.*` 的精确口径由 N-23 补成「8 个目录 / 5 个含 `root_meta_info.json` / 3 个为空」）。



## F-057 `clip` 挂在 segment 上这件事，`spec/panel-map.yaml` 早已 `conf: verified`；是我们的模型没读规格，把 99/136 段的几何静默丢光（播放通道 P-13/P-16 复核，2026-10-22）

- **Evidence**：只读解密目标草稿并用 `temp/playback-test/probe_geometry.py` 逐段打印几何载体：
  `segments[].clip = {scale, transform, rotation, alpha, flip}` 有值，而 `materials.texts[]` 里**没有** `clip` 键。
  同时 `docs/spec/panel-map.yaml:16` 早已写着 `位置大小.位置X/Y → segment.clip.transform.x/.y, conf: verified`，
  并引 F-035（导出实测）给出渲染律 `位移px = 值 × 该轴边长 / 2`、y 轴向上、锚点=字框中心。
  把取值来源从 material 改回 segment 后，136 段里 **99 段带几何**（video 55/55、subtitle 40/40、
  text 2/2、photo 2/2、audio 0/37），L1 断言仍 0 错 0 警。
  独立复核：白字幕 `transform.y = -0.4427083333333333` 经**两条渲染链**各自出图，
  中心都落在高度 **0.721**（= (960+425)/1920），与 F-035 当年从导出成片量的 424.5 px 差 0.5 px。
- **Finding**：① 字段归属确认无误：`clip` 是 **segment** 级，按 material 读会**静默**退化成「全部默认」，
  而且现有计数器（fps / 解码帧数 / 取块字节）一个都发现不了——本轮就是这样把整条几何通道丢了很久；
  ② F-035 的归一化律在**另一份草稿、另一条测量路径**（浏览器世界包围盒 + PIL 墨迹盒 + 封面色带质心）
  上第三次命中，可从「导出实测」升级为多路已验证；
  ③ 流程教训：`docs/spec/*.yaml` 里 `conf: verified` 的条目是实现的上游依据，
  实现没读规格而自行猜载体，是本可避免的缺陷类别。为此把几何覆盖率变成模型自报断言
  （`stats.geometry_segments / geometry_total`，读错对象会直接掉到 0）。
- **Path**：`temp/playback-test/probe_geometry.py`、`temp/playback-test/model.json`、
  `scripts/playback_model.py`（clip 取值处与 `count_geometry`）、`temp/playback-test/render-0.5-inkfix.png`、
  `docs/evidence/playback-log.md` P-13/P-16/P-22。
- **证据等级**：**已验证**（解密稿直读 + 两条独立渲染链 + 与 F-035 的导出实测对齐）。

## F-058 复合子草稿自带画布，映射律是「按宽适配 + 垂直居中」：封面四边残差 2–12 px（新开 U-76，2026-10-22）

- **Evidence**：目标草稿 track 6 的片段 `DAC95A4C` 引用的 `materials.drafts[]` 子草稿
  自带 `canvas_config = {ratio:"3:4", width:1080, height:1440}`，父画布 1080×1920，
  父片段 `clip` 是**恒等**（`x=0,y=0,scale=1`，注意不是缺席——之前记成 `None` 是 F-057 那个 bug 的假象）。
  子层金色花字 `clip.transform = {x:0.1289, y:-0.6855}`。三种候选律对封面实测质心 `cy=0.755` 的预测：
  拉伸到父画布 **0.843**、按宽适配+顶部对齐 **0.632**、**按宽适配+垂直居中（240 px letterbox）0.757**。
  通道 2 按第三种重渲后，金色层六个量（质心 cx/cy 与 1–99 分位包围盒 x0/x1/y0/y1）
  对封面的最大偏差 **0.008**（画布的 15 px 内），浏览器链同口径实测中心 **(0.564, 0.757)**。
- **Finding**：复合片段渲染必须两步：子层在**子画布单位**里布局，再由 group 做
  「子画布按父画布宽等比缩放、垂直居中」的映射；把子层直接按父画布布局、或把子画布拉伸成父画布，
  都会把花字推到 0.632 / 0.843 高度（差 23–88 px）。
  同一条律也解释了为什么 `clip=None` 的复合子层此前「看起来居中就对」——那是 F-057 把位移丢了之后的巧合。
- **Path**：`temp/playback-test/measure_cover_bands.py`、`temp/playback-test/oracle/cover-bands.json`、
  `temp/playback-test/render-0.5-clipfix.png` / `render-0.5-inkfix.png`、
  `scripts/render_frame.py::collect`、`temp/playback-test/player.html`（`childSize()` + `placeGroup(node, clip, child, size)`）。
- **证据等级**：**单样本已验证**（一份封面、一条 3:4 子画布、两条渲染链各自对上）；
  父 `clip` 非恒等时的复合顺序无样本 → U-76。

## F-059 combination 渲染缓存：字符串 API 对**音频**解出有效 AAC、对**视频**解出无容器结构的高熵 blob（收窄 Q-1，2026-10-22）

- **Evidence**：`temp/playback-test/job-media.json` 那次合规 DLL 作业（`op: decrypt_bytes`，只读源、只写 `temp/`）
  产出在 `temp/playback-test/media-dec/`。逐文件量（口径：字节数 + pin 的 ffmpeg 四 demuxer 判定 + 标记计数）：
  | 产物 | 源字节 | 解出字节 | 比值 | 判定 |
  | --- | --- | --- | --- | --- |
  | `01400053…_audio.aac` | 528,593 | 93,041 | 5.68 | **有效 AAC**（Main / 1.37 s / 538 kb/s） |
  | `1ECF4DB3…_video.mp4` | 21,552,291 | 4,027,796 | 5.35 | `ftyp`/`moov`/`mdat`/`avc1`/start-code 计数**全 0**，`mp4`/`matroska`/`nut`/`h264` 全拒，`m4v` 报 `header damaged` |
  | `7553BBFF…_video.mp4` | 9,336,700 | 1,747,230 | 5.34 | 同上 |
  | `D1F33107…_video.mp4` | 7,049,469 | 1,319,342 | 5.34 | 同上 |
  密文头 `f9 f9 f9 d9 9f 8d 80 89 …` 与 MP4 魔数按单字节 XOR 自洽（⊕`f9` = `00 00 00 20 ftyp isom`），
  另两支分别 ⊕`a5` / ⊕`d0` 同样得到 `ftyp isom`。**本轮只记录观察，未据此产出任何明文帧**
  （「加解密只走内存串 API、不做算法逆向」是用户划的线）。
- **Finding**：① combination 的视频缓存**不走**草稿那套字符串解密，`decrypt_bytes` 对不支持的输入
  **不报错**、返回一段同量级高熵 blob ⇒ 「API 成功返回」不等于「解出来的东西可用」，判定必须落在容器探测上；
  ② 因此剪映自己的 combination 渲染缓存在 M2 里**当不了像素 oracle**，L3 仍需一次真实导出；
  ③ 同一目录内音频正确、视频不正确 ⇒ 该 API 按流类型分叉，或视频侧还有第二步（未验证）。
- **Path**：`temp/playback-test/media-dec/`、`temp/playback-test/job-media.json`、
  `docs/evidence/playback-log.md` P-17。
- **证据等级**：表格内的字节/比值/计数与 ffmpeg 判定 **已验证**；③ 的成因是**假设**。

## F-060 真样本反证：`alignment=2` 且 `clip.transform` 非零时，封面只匹配「字框中心钉在变换处」，不匹配右缘锚定（给 F-031/U-30 补边界，新开 U-77，2026-10-22）

- **Evidence**：F-031/`panel-map.yaml:64` 的钉法是「六枚对齐按钮只写 `texts[].alignment`，
  那六次点击里 `segments[].clip.transform` 恒 `{0,0}` ⇒ 版面位置由 alignment 单字段承载」。
  目标草稿里存在**同时**满足 `alignment=2` 与 `clip.transform={x:0.1289, y:-0.6855}` 的真实字幕
  （combination 子层的金色花字）。两种读法各自预测的整行中心：
  右缘锚定（把框右边缘放到变换处）→ **0.153**；中心锚定（把框中心放到变换处）→ **0.565**。
  封面实测质心 **0.537**、1–99 分位包围盒 **0.169–0.948**；通道 2 按中心锚定渲染得
  **0.527 / 0.165–0.943**（四边残差 4–12 px）。
- **Finding**：`alignment` 的水平取值在**该样本上不移位**——它承载版面位置的前提是 `transform` 为零
  （F-031 的实验正是那种情形）。两者同时非默认时，观测支持「transform 定位、alignment 只管框内对齐/流向」。
  这不推翻 F-031，而是给它划出适用域：**`clip.transform` 恒零**时才谈得上「alignment 单字段承载位置」。
  渲染器若照 F-031 的字面把 `alignment=2` 实现成右缘锚定，会在真样本上错 0.41 个画布宽（≈440 px）。
- **Path**：`temp/playback-test/model.json`（该段的 `text.alignment` 与 `clip`）、
  `temp/playback-test/measure_cover_bands.py`、`temp/playback-test/oracle/cover-bands.json`、
  `temp/playback-test/player.html::drawText`（已按中心锚定实现并留注释）。
- **证据等级**：**单源已验证 + 反例明确**（一份封面、一条样本段；需要多行/已知框宽的样本才能彻底分开两种读法 → U-77）。


## F-061 combination 缓存的加密是**逐文件**的：RGB 是密文，同目录的 `.alpha.mp4` 兄弟是明文 MP4——但它是**恒 255 的平 alpha**，当不了几何 oracle（收窄 U-80，2026-10-22）

- **Evidence**：目标草稿 `Resources/combination/` 八个文件逐个读头 12 字节分类：
  | 文件 | 字节 | 头部判定 |
  | --- | --- | --- |
  | `1ECF4DB3…_video.mp4` | 21,552,291 | 密文，与单字节 XOR 自洽（⊕`f9` = `00 00 00 20 ftyp isom`） |
  | `1ECF4DB3…_video.mp4.alpha.mp4` | **62,718** | **明文 `ftyp` MP4**，h264 Main / yuv420p / 1080×1920 / 30 fps |
  | `7553BBFF…_video.mp4` / `.alpha.mp4` | 9,336,700 / 26,170 | 同上（XOR ⊕`a5` / 明文） |
  | `D1F33107…_video.mp4` / `.alpha.mp4` | 7,049,469 / 19,892 | 同上（XOR ⊕`d0` / 明文） |
  | `01400053…_audio.aac` / `D5614490…_audio.aac` | 528,593 / 893,356 | 非 XOR 的其他密文（`other-crypto`） |
  三个 alpha 兄弟按 `mvhd` 解出时长 21.53 / 8.70 / 6.60 s，各取 5 帧（0、25%、50%、75%、末帧）**min=max=mean=255**。
- **Finding**：① 剪映对 combination 缓存**只加密 RGB 那一路**，同目录的 alpha 兄弟原样落盘 ⇒
  「加密面」的粒度是**单个文件**而不是目录/素材类型，P-01/F-053 那条「加密面比 `draft_content.json` 大」
  需要补这一句反面：**也不是目录里所有文件都加密**；
  ② 这些 alpha 是**恒不透明占位**（20 kb/s、几十 KB），所以**不能**拿它当叠加层的几何/形状 oracle——
  本来指望它免解密给出 logo 与花字的落点，此路不通（U-76 的 photo 基准缩放仍开放）；
  ③ 顺带定到一个尺寸事实：alpha 缓存是 **1080×1920 父画布**尺寸，不是子草稿的 1080×1440
  ⇒ 剪映自己把 combination **渲染到父画布再缓存**，与 F-058 的映射律同向（旁证，非新证据）。
- **Path**：`<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>\Resources/combination/`（只读），
  `temp/playback-test/alpha-*.png`（15 张采样帧），分类器为一次性内联脚本（判据 = 头 12 字节 + XOR crib）。
- **证据等级**：① **已验证**（逐文件头字节 + ffmpeg 探测两路一致）；② **已验证**（15 帧恒 255）；
  ③ **单源旁证**（只有尺寸这一项，且来自缓存而非实时渲染）。

## F-062 机器级扫描证明这条时间线在机器上**没有成片**：8,394 个媒体文件按 `mvhd` 时长比对，无 36.83 s 命中（把 P-11 的断言换成读数，2026-10-22）

- **Evidence**：纯 Python 解析 `mvhd`（timescale+duration，不解码、不读整个文件，只读前 2 MB）
  扫 `<DRIVE_E>/输出`、`<DRIVE_D>/JianyingPro`、`E:ixtures` 三个根下全部 `.mp4/.mov/.m4v`
  共 **8,394 个文件 / 211.5 s**，取 |时长 − 36.83| < 1.2 s 者：
  命中 16 个，**全部在草稿目录内部**（源素材 `materials/video/C*.MP4`、
  别的草稿的 `Resources/combination/*.alpha.mp4`、`User Data/Cache/MotionBlurCache/`），
  `<DRIVE_E>/输出` 下只有一个 37.30 s 的 NINA断刀 文件（不同品牌）。
  同品牌 `<DRIVE_E>/输出\机床蒋堂\` 10-20 的三支（`1020-1628`、`1020-1643`、`1020-1649`）
  实测 **45.88 s** / 1080×1920 / h264 Main / aac LC 44.1 kHz，取 t=0.5 帧做金色掩码
  （`|ΔRGB| < 46` vs `#FFDE00`）得 **gold px 0**，而本草稿的渲染与封面分别是 24,141 / 21,408 px ⇒ 不是同一条时间线。
- **Finding**：「需要一次剪映导出」不再是推断而是**穷举结论**：这台机器上不存在可比对的成片，
  L3 的整帧像素基线**只能等导出**（或等用户授权在克隆草稿上驱动剪映导一次）。
  同时给出一条可复用的搜索手段：按 `mvhd` 时长做**指纹搜索**，211 s 扫完 8,394 个文件，
  比逐个 ffmpeg 探测快两个量级，适合「这条时间线有没有成片」这类问题。
- **Path**：一次性内联扫描脚本（判据：`mvhd` timescale/duration + 金色掩码像素数），
  `temp/playback-test/export-1020-1628-0.5.png`、`export-1020-1643-0.5.png`。
- **证据等级**：**已验证**（时长指纹 + 像素层排除两条独立判据）。


## F-063 `alignment` **不**把字框钉到画布边缘：2,071 份冻结草稿上 `transform.x` 的分布直接否掉边缘锚定读法（结案 U-77 的主问，2026-10-22）

- **问的是**：F-031 说「版面位置由 `texts[].alignment` 单字段承载，渲染器要自己算」——那 `alignment=0/2`
  到底是把**字框的左/右边缘**放到 `clip.transform.x` 处，还是 `transform.x` 永远是框中心、
  `alignment` 只管框内行流向？F-060 的封面反例只能否证「右缘锚定」这一条，且是单样本。
- **不用像素也能分开两种读法**：若 `alignment` 真把框钉到画布边缘，那么用户做出「左对齐」这个动作
  就是在说「贴左边」，存下来的 `transform.x` 必须靠近 **−1**（半画布归一化的左边界）；右对齐靠近 **+1**。
  若 `x` 只是框中心，`alignment` 不参与定位，那么 `x` 的分布应当与 `alignment` **无关**（都围着 0）。
  两种读法对 `|x|` 分布的预测是**互斥**的，且不需要知道字号、框宽或 em 律。
- **Evidence**（口径：`temp/corpus-scan/plain` 全部 2,071 份冻结明文，含 `materials.drafts[]` 子层，
  只统计写了 `clip.transform.x` 的 text 段）：
  | `alignment` | n | mean x | \|x\| p50 | \|x\| p95 | 贴边比例 \|x\|>0.5 |
  | --- | --- | --- | --- | --- | --- |
  | 0 左 | 271 | −0.024 | **0.075** | 0.468 | 9/271 = **3.3%** |
  | 1 中（含键缺席） | 25,456 | 0.001 | 0.000 | 0.340 | 2.8% |
  | 2 右 | 187 | +0.109 | **0.533** | 0.538 | 122/187 = **65.2%** |
  | 3 上 | 86 | +0.818 | **1.427** | 1.427 | 81.4% |
  | 4 下 | 5 | +0.245 | 0.213 | 0.808 | 40.0% |
  左对齐的 `x` 中位数只有 **0.075**（几乎就在中间），贴边比例 3.3% 与居中组（2.8%）**没有区别**；
  右对齐确实整体右移（p50 0.533），但**远不到 +1**，而且是挤在 0.533–0.538 的一个尖峰上
  （p50≈p95），那是**预设/花字模板的固定值**，不是「贴右边缘」。
- **Finding**：① `alignment` **不承载画布边缘锚定**——若承载，al=0 的 `|x|` 必须靠近 1，实测 0.075；
  ② `clip.transform.x` 在全部取值下都是**框中心**，与 F-060 的封面反例同向，
  于是渲染器**不该**按 `alignment` 把框边挪到变换处（我们浏览器链原来的 `size.w - w` 右缘分支就是这种错法，
  改成中心对齐后与封面四边对上）；
  ③ 但 `alignment` 与落点**并非无关**：al=2 明显右移、al=3 的 `|x|` p50 高达 **1.427（超出画布半宽）**——
  后者说明「上对齐」那批走的是另一套约定（竖排？还是 x 被当成别的轴？n=86 未查），
  这条留给 U-81，不影响 ①② 的结论；
  ④ 对 F-031 的修正是**限定而不是推翻**：它的差分实验里 `transform` 恒 `{0,0}`，
  所以「六枚按钮只改 `alignment`」依然成立；错的只是把它推广成「版面位置由 `alignment` 承载」。
- **Path**：`temp/playback-test/alignment_anchor_test.py`（同一判据的可复跑版本）、
  一次性内联普查（本轮表格；口径同上，含子层）。
- **证据等级**：① **已验证**（2,071 份草稿、271+187+25,456 段，与 F-060 的独立封面反例同向）；
  ③ 的 al=3 异常**未解释** → U-81。


## F-064 草稿里其实有**多个**封面渲染：第二帧把**主时间线白字幕**对到 2 px，L3 不必全等导出（新开 U-82，2026-10-22）

- **发现**：`Resources/cover/` 里除了与 `draft_cover.jpg` 同摘要的三份拷贝
  （`draft_cover.jpg` = `Timelines/017E2FEC/draft_cover.jpg` = `Resources/cover/BA76BCB5….jpg`，md5 `63d77e51`），
  还有两帧**不同**的 1080×1920 渲染：
  `3E1C3523…jpg`（md5 `3dd58214`，金色字幕 22,783 px，与主封面同一画面的另一次编码）、
  `69DA0439…jpg`（md5 `7e48d619`，**金色字幕 2 px ≈ 没有**）。
  ⇒ 剪映把历次生成的封面都留在 `Resources/cover/` 下，这是一个**免费的天然 oracle 库**，
  不必等导出就能拿到时间线上别的时刻的合成结果。
- **第二帧是 t ∈ (0.57, 1.80] 的画面**：combination 段（父时间线 0–0.57 s）已经消失，
  而主时间线的白字幕（`CBDFC7CF`，0–1.80 s）还在。该帧**下半部被截断损坏**
  （右侧大片白横纹、左侧纯黑），但字幕所在的 y 0.70–0.74、x < 0.46 区域完好。
- **Evidence**（口径：亮度 > 200 的连续行团，x 限定在损坏边界以左 `x<0.46`，两侧同一窗口）：
  | 量（白字幕「大家好我们逛了<素材语料>」） | 第二封面 | 通道 2 @ t=1.0 | 差 |
  | --- | --- | --- | --- |
  | 上沿 y | 0.707 | 0.706 | 0.001 ≈ 2 px |
  | 下沿 y | 0.735 | 0.735 | 0.000 |
  | 字高 | 56 px | 56 px | **0** |
  | 左端 x | 0.214 | 0.216 | 0.002 ≈ 2 px |
  | 带内宽度 | 265 px | 263 px | 2 px |
  预测值来自 `clip.transform.y = -0.4427083333333333` → 中心 **0.721**，实测两侧都是 **0.721**。
- **Finding**：① F-057 的位移律与 em 字高律在**第二帧、第二层**（主时间线字幕，第一张封面完全测不到它）
  上再次命中，四边与字高残差 ≤ 2 px ⇒ L3 的**文字图层**已有天然基线，不再整体依赖导出；
  ② 修正 F-062 的口径：「没有成片」仍然成立，但**不等于没有原生渲染帧**——
  做像素校验时应先翻 `Resources/cover/`，那里可能有若干帧真实合成结果；
  ③ 这些封面帧**有损坏风险**（本例下半部截断），所以只能当**局部** oracle，
  按可用区域取判据，不能整帧比对。
- **Path**：`<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>\Resources\cover\*.jpg`（只读），
  `temp/playback-test/render-1.0-clipfix.png`，一次性内联色带测量（判据同上表）。
- **证据等级**：**已验证**（两帧独立原生渲染 × 两条不同图层，且与模型预测三方对齐）；
  封面帧的时间戳归属是**区间推断**（靠图层存活窗口夹出来），非记录值 → U-82。


## F-065 第二张封面**只能当文字层的 oracle，不能当视频层的**：字幕四边 2 px 命中，视频带在任何朝向/时刻下都不相关（给 F-064 划边界，新开 U-83，2026-10-22）

- **要判的事**：F-064 那张 `69DA0439…jpg` 能不能免导出当**整帧**基线用（那样 L3 的视频层就不必等导出了）。
- **视频层比对（左半带 x∈[0,0.5]、y∈[0.02,0.42]，13 个时刻 t=0.55…1.75 逐 0.1 s）**：
  | 量 | 结果 |
  | --- | --- |
  | 均值 | 封面 137.8 vs 我们 134–141（**只差 1–3 个点**） |
  | RMSE | 全程 **102.5–105.6**，曲线几乎平（最优 t=1.45 s 也只到 102.5） |
  | 相关系数 | **−0.18 ~ −0.25**（负相关，均值却几乎相同 ⇒ 结构对不上，不是曝光差） |
  | 换朝向 | `fliplr` 最好 +0.42 但 RMSE 反而升到 112；`flipud` +0.41；`rot90/270` 形状不符 ⇒ **不是镜像也不是旋转** |
  | 噪声地板 | 封面自身平移 1 px 自比 RMSE 21.65 ⇒ 102 的残差是地板的 **4.7 倍** |
  行剖面（带内 8 分位）：封面 `[204,213,216,209,188,192,176,172]` vs 我们 `[120,137,154,158,154,153,180,167]`
  —— **顶部四行差 60–80 个点**（封面那几行接近过曝白），到带底部才收敛到 4–8 个点。
- **同一条帧上的文字层却是精确的**（F-064 表）：白字幕上沿 0.707/0.706、下沿 0.735/0.735、
  字高 56 px/56 px、左端 x 0.214/0.216 ⇒ 位置与字高**四边 ≤ 2 px**。
  这两件事不矛盾：字幕是**独立图层**，它的几何对不代表底下视频对。
- **Finding**：① 这张封面**只能当文字/叠加层的局部 oracle**，不能当整帧基线；
  拿它做视频层比对会得出「均值对、结构错」的误导性结论——**只看 RMSE 会误判，必须同时看相关系数**
  （这里就是均值差 1–3 点而 corr 为负的典型）；
  ② 顶部过曝 + 结构不相关，最可能的解释是**封面取帧的视频内容不是这个镜头的这个时刻**
  （或剪映生成封面时另有一次裁剪/缩放），但**未定案** → U-83；
  ③ 对 L3 的净影响：视频层的原生像素基线**仍未拿到**，L3 仍需要一次导出；
  文字层（主时间线字幕 + combination 花字）已在两张独立封面上各测到 2–12 px。
- **Path**：`temp/playback-test/coversearch-*.png`（13 帧）、
  `temp/playback-test/cover_video_band_search.py`（带内 RMSE 搜索）、一次性内联朝向/剖面比对。
- **证据等级**：负结果**已验证**（13 个时刻 × 4 种朝向，判据为均值/RMSE/相关系数/自比地板四项）；
  成因未定 → U-83。


## F-066 视频层拿到**免导出的正向验证**：同一时刻的原生封面与我们的渲染在 32 px 尺度上 corr +0.75，而两张原生封面相隔 1 s 互相比对是**负相关**（结案 U-83，2026-10-22）

- **要分的岔路**：F-065 里「第二封面的视频带与我们不相关」有两种可能——(a) 我们的视频层错了；
  (b) 那条比对本来就不该有相关性（两张封面拍的是不同时刻）。
  分开它俩只需要一个**对照**：拿两张原生封面互比，看「原生 vs 原生」是什么水平。
- **Evidence**（口径：左半带 x∈[0,0.5]、y∈[0.02,0.42]，BOX 降采样到 k×k 像素后算 luma 的
  相关系数与 RMSE；k 从 1 px 到 32 px）：
  | 比对 | corr @1px | corr @8px | corr @32px | RMSE @1px | RMSE @32px |
  | --- | --- | --- | --- | --- | --- |
  | **封面A vs 我们@t=0.5（同一时刻）** | **+0.452** | **+0.552** | **+0.748** | 66.7 | **33.7** |
  | 封面A vs 我们@t=1.0（差 0.5 s） | +0.219 | +0.277 | +0.433 | 78.0 | 49.6 |
  | **封面A vs 封面B（两张原生，差约 1 s）** | **−0.195** | −0.237 | **−0.320** | 105.8 | 89.1 |
  | 封面B vs 我们@t=1.45 | −0.181 | −0.210 | −0.282 | 103.3 | 89.4 |
  单调性是关键：**同刻对的 corr 随尺度变粗一路上升（0.45→0.75）、RMSE 一路降**；
  错时刻对在所有尺度上都钉在负值。也就是说这个度量确实能分辨内容对齐，
  而「两张原生渲染互相比对」的**基线就是负的**——这台机器的这段素材手持 + 人物走动，
  差 1 s 就已经不相关了。
- **Finding**：① **我们的视频层是对的**：与封面A 同刻比对的得分，高于任何一对跨时刻的比对，
  包括**原生 vs 原生**这种天然满分对照；这是不依赖导出拿到的视频层正向证据。
  ② **结案 U-83**：F-065 的「自相矛盾」不是矛盾——负相关是这段素材跨 1 s 的**常态基线**，
  封面B 从一开始就不可能当视频层 oracle（它的时刻与任何我们渲染的 t 都不同）。
  ③ **给 L3 定方法**：单张封面只能验证**它自己那个时刻**的画面，而封面不记时间戳（U-82），
  所以拿封面做视频层判据必须先做**时刻对齐**，否则会把「时刻不同」误读成「渲染错误」；
  并且这类比对**必须同时报相关系数**，只看 RMSE 会在跨时刻对上得到 105 这种看似「略高」的数，
  在同刻对上得到 66 这种看似「仍很高」的数，两者都不说明问题。
  ④ 残留：同刻 +0.75 而非 ~1.0，可解释的部分是封面A 那条带里含 combination logo 叠加
  （y≈0.25、x 0.17–0.5）、JPEG 有损、以及 t=0.5 未必正是取帧时刻；**未逐项拆**。
- **Path**：`temp/playback-test/check-0.50s.png`、`render-1.0-clipfix.png`、`coversearch-1.45.png`、
  `Resources/cover/BA76BCB5….jpg`（= `draft_cover.jpg` 同字节）与 `69DA0439….jpg`；
  一次性内联多尺度比对（判据同上表）。
- **证据等级**：①②③ **已验证**（四对 × 六个尺度的单调分离，含原生-原生对照）；
  ④ 的分解**未做**。


## F-067 视频带相关系数的**内部峰值**给封面定了时间戳（±0.05 s），并拆掉 U-84 的一大半（结案 U-82，收窄 U-84；判据已进 `playback_check.py`，2026-10-22）

- **做法进工具**：`scripts/playback_check.py` 新增 **L3 video band** 层
  （`--cover-frame` / `--band` / `--band-x1` / `--band-mask` / `--video-scan a-b:step` / `--video-corr-min`），
  判据是「左半带、BOX 降采样到 32 px、掩掉叠加层后的 luma 相关系数」，PASS 阈值 0.6。
  从此这条不是手工算一次的东西，而是门里的一行。
- **Evidence｜时刻扫描**（`t=0.05…0.90` 步长 0.05，18 帧，corr@32px、已掩 y 0.17–0.33 的 logo 带）：
  ```
  t  0.05  0.10  0.15  0.20  0.25  0.30  0.35  0.40  0.45  0.50  0.55 | 0.60  0.65  0.70  0.75  0.80  0.85  0.90
  +  0.708 0.706 0.696 0.696 0.710 0.731 0.761 0.778 0.775 0.773 0.789 | 0.645 0.623 0.616 0.599 0.590 0.586 0.579
  ```
  峰值 **+0.789 在 t=0.55 s**，是**内部峰**（左端 0.708、右端 0.579），过 0.57 s 后**断崖下跌**（0.789 → 0.645）。
  0.57 s 正是两个复合段（`6B591400`、`DAC95A4C`）在父时间线上的结束时刻。
- **Finding**：① **结案 U-82**：封面不记时间戳，但**相关系数的峰值可以把它定到 ±0.05 s**——
  方法就是把我们的渲染在候选区间上扫一遍取 argmax，且峰值与「图层存活窗口」的边界独立吻合
  （层判定 t∈(0,0.57]，峰值落在 0.55，断崖正好在 0.57 之后），两路互证；
  ② **收窄 U-84**：同一条带上，掩掉 logo 后 corr 从 0.761 升到 0.789（**+0.028**），
  即叠加层只占「离 1.0 还差 0.211」里的约 **12%**；剩下的大头不是我们的几何，
  而是封面 JPEG 有损 + 取帧时刻与 30 fps 栅格的对齐（0.55 s 处 1 帧 = 33 ms，仍在 ±0.05 s 分辨率内）；
  ③ 视频层的正向基线成立：同刻 **0.789**，而两张原生封面跨约 1 s 互比是 **−0.20~−0.32**（F-066），
  所以这个数不是「勉强算像」，是显著高于天然对照的水平。
- **门的这一轮全绿**（n=2 电池 + L3 扫描）：L1 0 错 0 警、几何 99/136、L2 对封面最大偏差 0.008、
  **L3 video band PASS corr@32px 0.789（阈值 0.6）**、fps 中位 29.6、seek 中位 36.5 ms、
  首帧中位 201 ms（0/2 越线）、Range 中位 3777 次/10 s、`black_streaks`+`errors` 0/2、
  `rates_seen [44100, 48000]`、`peak_fs [0.8873, 0.9651]` 且 **0/2 跑出现满刻度窗口**
  （注意：这与 F-063/P-23 的 5/5 削顶**互相矛盾地并存**——说明削顶是否发生取决于具体 seek 序列，
  U-78 的处置前必须先固定调度路径），90 s 窗口 RSS peak 1593 MB。
- **Path**：`scripts/playback_check.py`（`video_band()` / `parse_ranges()` / L3 层）、
  `temp/playback-test/bandx-*.png`、`bandscan-*.png`、`bandsingle-0.50s.png`。
- **证据等级**：①②③ **已验证**（18 点扫描 + 掩码开/关 + 原生-原生对照三组独立数据）；
  ②里「30 fps 栅格对齐」这一项**未单独测**。


## F-068 n=8 定下两件事：削顶是**约一半概率**的（推翻我上一轮「5/5 即常态」的读法），首帧判据是**中位过、尾部不过**（1/8 越线）

- **Evidence｜同一 build、同一参数、8 次独立无头电池**（`--repeat 8 --skip-negative`，
  `--battery-ms 10000 --seeks 12 fps=30 qmax=4 pool=4 loop=1`）：
  - `peak_fs` 八次 = **0.8873 / 0.8885 / 0.8899 / 0.8925 / 1.0316 / 1.0829 / 1.1688 / 1.3483**
    ⇒ `clipped_windows > 0` 的跑数 **4/8**。分布明显是**双峰**：四个 ≈0.89 不越界，四个 1.03–1.35 越界。
  - 首帧八次 = 中位 **235.9 ms**，散布 **150.4–348.7 ms**，**1/8 越 300 ms 线**。
  - 其余：seek 中位 34.8 ms（最差 52.5）、Range 中位 4169 次/10 s、
    `black_streaks`+`errors` **0/8**、`audio_errors` **0/8**、`rates_seen [44100, 48000]`、
    90 s 窗口 RSS peak 1747 MB。门 **11/11 PASS**。
- **Finding**：① **推翻我自己在 P-23/F-063 段落写的「5/5 跑满刻度 ⇒ 削顶是常态」**：n=8 显示是
  **约 50% 的抛硬币**，既不是常态也不是偶发。之前的 5/5 与紧随其后的 0/2 都是小样本假象——
  这正是「一个数被当成一个结论」的复发，只是这次犯在我身上。⇒ U-78 的处置前提变了：
  不是「要不要压掉一个必然发生的削顶」，而是「同一份草稿为什么有时爆有时不爆」，
  这更像**混音路径的启动顺序/哪几条轨先拿到流**决定的，属可查的确定性问题（U-86）。
  ② **首帧判据必须改写成中位+尾部**：`≤300 ms` 按中位（235.9）过、按尾部（348.7，1/8）**不过**。
  现在门里报的是「median + 越线次数」，判据文本本身（P-05 的单点口径）该同步改掉 → U-79。
  ③ 顺带一条工具事实：删掉 `proxy-a/` 之后门是**崩在 `max(空列表)`** 而不是给出可读结论，
  已加空序列守卫与「媒体缺失」的定向提示；但更该记住的是**我删的正是文档里那条复现命令依赖的东西**——
  清理自己的临时产物前，先确认没有已写下的命令依赖它（现已重新生成，7.5 GB）。
- **Path**：`temp/playback-test/report-playback.jsonl`（末 8 行）、`scripts/playback_check.py`
  （空序列守卫 + 媒体缺失提示）、`temp/playback-test/add_proxy_audio.py`（重跑一次即恢复）。
- **证据等级**：①② **已验证**（n=8 同参数独立复跑，双峰分布肉眼可分）；
  ① 的**成因未查** → U-86。


## F-069 成片到位并锁定身份：`<EXPORT_DIR>\<EXPORT_NAME>.mp4` 就是本时间线的剪映导出（推翻 F-062 的「穷举结论」，2026-10-22）

- **要分的岔路**：F-062 判定「这台机器上不存在可比对的成片」，用户随后给出一个 46 MB 的 mp4。
  要么它确实是本草稿的导出（L3 立刻解锁），要么是别的品牌/别的时间线的成片（拿它当 oracle
  会把几何标定整体带偏）。**时长不能定身份**：按 `mvhd` 重扫 `<DRIVE_E>/输出` 后，
  与 36.833 s 相差 <1.2 s 的有 **65 个**文件，最近的 36.781 s（Δ0.052）比本文件的 36.949 s
  （Δ0.116）还近。
- **Evidence**：
  ① **同字节封面**——导出目录里的 `<EXPORT_NAME>-封面.jpg` 与草稿根下的 `draft_cover.jpg`
  **sha256 前缀同为 `f9dcc459b28ebe63`、同为 215,713 B**。导出时剪映把工程封面原样拷进输出目录，
  跨草稿撞出同一张图的概率为零。
  ② 容器签名：1080×1920、h264 Main + aac LC 48 kHz 立体声、30 fps、**1108 帧**，
  `mvhd` 36.949 s；时间线声明 36.8333 s = **1105 帧**，1108 = 1105 + 3（→ F-070）。
  ③ 时间窗：`creation_time 2026-10-15T09:01:18Z`（本地 17:01:18），落在草稿自己的写入窗
  16:59–17:03 内（`draft_cover.jpg` 17:00、`draft_local_cover.jpg` 17:01、`draft_content.json` 17:03）。
  ④ 导出侧元数据 `Hw: 1`、`bitrate: 12000000`、`te_is_reencode: 1` 与剪映硬编导出一致。
- **Finding**：**F-062 的「穷举」其实是近乎零覆盖**。那条 `mvhd` 指纹扫描只读文件**前 2 MB**，
  而剪映导出**不是 fast-start**——本文件的 `moov` 在 46,392,040 / 46,421,807 B（尾部最后 30 KB）。
  按 head+tail 重扫 `<DRIVE_E>/输出` 全部 2,396 个媒体文件：**2,355 个（98.3%）的 `moov` 只在尾部**，
  即上一轮「`<DRIVE_E>/输出` 下只有一个 37.30 s 的 NINA断刀文件」是**扫描盲区**造成的假阴性，
  不是事实。F-062 里被当作排除依据的 10-20 三支 `机床蒋堂` 成片，实测同样**前 2 MB 无 `mvhd`**
  ——那 45.88 s 是当时另外用 ffmpeg 逐支探出来的，不是扫描器给的，所以扫描器的失效没被发现。
  教训与「先查我们自己的判据」同型：**一次「穷举证明不存在」的结论，先要证明穷举真的覆盖了**。
- **Path**：`temp/playback-test/probe_export.py`（head+tail 容器签名）、
  `temp/playback-test/scan_exports.py` + `temp/playback-test/scan-exports.log`（重扫 2,396 文件）、
  `scripts/export_compare.py`（L3 整帧比对，F-070/F-072）。
- **证据等级**：**已验证**（同字节封面 + 帧数算术 + 时间窗三条独立判据；扫描盲区已量化）。


## F-070 导出的**前 3 帧是封面静帧**，不是时间线内容：对齐律 `export_frame = round(t×30) + 3`

- **Evidence**：导出第 0/1/2 帧**彼此逐像素相同**，且与 `draft_cover.jpg` 在 64 px 尺度上
  **corr 0.998**；第 3 帧起才与我们的 t=0 渲染相符（修完 F-071 后 0.994）。
  帧数算术自洽：时间线 36.8333 s × 30 = 1105 帧，导出 1108 帧，**多出正好 3 帧**。
  37 个位置（1 fps）在 ±2 帧窗口里的最优偏移直方图 = **0×16、+1×20、−1×1**（相对 lead=3）。
- **Finding**：① 对齐律成立，但它**不是**「剪映把时间线第 0 帧重复了三遍」——那三帧画的是
  **封面状态**（金色字幕「你们这次去<素材语料>了吗？」），与时间线 t=0 的白色字幕
  「大家好我们逛了<素材语料>」**不是同一个画面状态**。所以封面既不是 t=0 也不是任何时间线时刻的
  截图，而是一条**独立渲染的静帧**；这解释了 F-065/F-066 里「封面文字层能对上、视频层对不上」
  的自相矛盾（U-83 结案的另一半）。
  ② 偏移直方图在 0/+1 之间**对半开**，说明这个量级（1/30 s）已经**低于本判据的分辨率**：
  比对器必须带 ±2 帧搜索窗，否则会把亚帧对齐读成渲染缺陷（本轮 t=2/3/4 的 0.82–0.89@128px
  残差正是这样被排除的）。
- **Path**：`temp/playback-test/oracle/dense216/`（全 1108 帧 @216px）、
  `temp/playback-test/l3/sbs-t0.png`、`temp/playback-test/l3/strip-lead.png`。
- **证据等级**：**已验证**（帧数算术 + 逐像素相同 + 与封面 0.998 三条互相独立）。
- **裁定（2026-10-23，用户）**：「成片输出是带有封面添加至首帧，这个预览不用」——前置封面是
  **导出侧产物**，预览**不跟随**。所以 `--lead` 永远只是**比对时对齐 oracle 的偏移**，
  不是播放起点、也不是「t<0 先画三帧封面」的功能。已把这句话写进
  `export_compare.py` 与 `playback_check.py --oracle-lead` 的注释，防止以后有人照成片把 pre-roll 补进播放器。
  播放器现状本就如此（从未实现过 pre-roll），此条为**确认**而非改动。


## F-071 `segments[].visible = false` 被 L1 整条丢掉 ⇒ 两条**隐藏**叠加层被我们画了出来（成片 oracle 抓到的第一个真缺陷）

- **要分的岔路**：整帧比对在 t=0 只有 0.778（其余位置 ≥0.95）。要么 t=0 的取帧/对齐有问题，
  要么我们多画了东西。用「逐层删/加」的变体一次跑开：
  删 track5 → **0.948**；删 track0 → 0.605；删全部文字轨 → 0.665（不变）。
  ⇒ 责任层是 track5，与文字、与主轨都无关。
- **Evidence**：解密后的草稿里 **104 段中恰好 2 段**写了 `visible: false`，都在 t=0.000–0.567、
  都是 `flag=2` 视频轨：track5（`render_index=7`、素材与主轨同一个 combination 缓存但
  `source.start=1.4 s`、`transform.y=-0.0812`、`volume=0.001`）与 track6（`render_index=6`、
  `material_id` 指向空素材）。`playback_model.py` 从未读这个键，两条渲染链都照画。
  修后 t=0 整帧 corr@64px **0.778 → 0.994**。
- **Finding**：① 这是**封面 oracle 结构上不可能发现**的一类缺陷——隐藏层只活 0.567 s，
  而封面恰好就是那三帧之一的状态（F-070），拿封面当基准反而会把它读成「对的」。
  ② 字段语义：`visible` 缺省即可见（另外 102 段根本不写），所以判据必须是
  `=== false` / `is False` 而不是 falsy，否则 102 段全被隐藏。
  ③ 隐藏层**没有**从音频侧一并排除：track5 自带 `volume=0.001`（已近乎静音），
  所以「隐藏层该不该出声」这条**没有证据**，不改（见 U-87）。
- **Path**：`scripts/playback_model.py`（`visible` 通道 + `stats.invisible_segments`，打印 `hidden 2`）、
  `scripts/render_frame.py:204`（`active_segment` 跳过）、`temp/playback-test/player.html:448`（`active()` 跳过）、
  `temp/playback-test/l3/neg.png` 变体实验。
- **证据等级**：**已验证**（删/加两个方向都复现，且只影响 t=0 一个时刻）。


## F-072 L3 整帧逐帧基线成立，并给判据定了**逐层区分力**：缺主轨/缺叠加一眼可见，缺字幕只有 0.02

- **Evidence**：37 个位置（0–36 s，1 fps）对成片，多尺度亮度 Pearson 相关，中位数
  **0.986 @16px / 0.983 @32 / 0.979 @64 / 0.973 @128**，最差单帧 0.90 @64（t=4），
  门判 PASS（`median ≥0.95`、`min ≥0.80`）。负例表（corr@64，±2 帧搜索，8 个时刻）：

  | 变体 | t=0 | t=3 | t=5 | t=13 | t=18 | t=26 | t=31 | t=36 |
  |---|---|---|---|---|---|---|---|---|
  | 全画（修后） | 0.994 | 0.923 | 0.993 | 0.989 | 0.909 | 0.985 | 0.993 | 0.994 |
  | 强画隐藏层 | **0.778** | 0.923 | 0.993 | 0.989 | 0.909 | 0.985 | 0.993 | 0.994 |
  | 删全部文字轨 | 0.977 | 0.895 | 0.985 | 0.970 | 0.904 | 0.979 | 0.970 | 0.975 |
  | 删 `flag=2` 叠加 | 0.994 | **0.217** | 0.993 | **−0.141** | **0.319** | **0.205** | 0.993 | 0.994 |
  | 删主轨 | **0.057** | 0.923 | **0.039** | 0.989 | 0.909 | 0.985 | **0.082** | **0.081** |
- **Finding**：① 判据有**方向正确的区分力**且两两自洽：删叠加崩的时刻（3/13/18/26）正好是
  删主轨不动的时刻——叠加在那四处盖住了主轨，两条判据互相印证而不是各说各话。
  ② **字幕层的天花板是 0.005–0.024**（8 个时刻全部下降，方向一致但幅度小），因为字幕只占
  画面百分之几的像素。⇒ 整帧判据**不能**用来抓缺字幕，抓字幕仍须 F-064 的分层色带/连通域判据；
  这条限制已写进 `export_compare.py` 的判据说明，避免以后有人把阈值提到 0.99 去「抓文字」。
  ③ 残余低分**不是缺陷**：t=18 的 0.909 肉眼比对是**色调/亮度**差（我们的顶灯更爆、地面更亮），
  属相位范围内明确跳过的调色；t=2/3/4 是行人位移 + 亚帧对齐（F-070 ②）。
- **Path**：`scripts/export_compare.py`、`temp/playback-test/l3/baseline-1fps.json`（逐位置读数）。
- **证据等级**：基线**已测**（n=37 位置）；② 的量化**已验证**（5 变体 × 8 时刻负例矩阵）；
  ③ 的色调归因是**肉眼判读**，未做数值分离。


## F-073 成片母带**不削顶**、且比我们低 3.5–6 dB：Q-8「压增益会让预览更不像成片」的前提被实测推翻

- **要分的岔路**：U-78/Q-8 一直搁置处置，理由是「草稿写了 `loudnesses[]` 目标响度，照实应用
  必然叠加过 0 dBFS，**剪映母带大概率同样削顶**」——压增益等于偏离成片。这个「大概率」是
  唯一没被验证的前提，而成片一到手就能直接量。
- **Evidence**：把导出音轨解到 f32（48 kHz 立体声，1,773,568 样本 / 36.95 s）：
  **峰值 0.9970 线性 = −0.026 dBFS**（`astats` 在码流域给 −0.006 dBFS），
  **`|x| ≥ 0.9995` 的样本数 = 0**（一个都没有），0.5 s 窗 RMS：整体 0.2058、中位 0.2092、
  **最大 0.2891**。我们浏览器链（F-068/P-23 同参数）：`peak_fs` 0.887–1.35、
  **4/8 跑越满刻度**、`peak_rms`（窗最大）0.41–0.59。
- **Finding**：① 剪映的母带**顶到满刻度但不过**（−0.026 dBFS、零削顶样本）——它带了导出限幅
  或归一化。② 我们的混音**既越界又更响**：窗最大 RMS 0.41–0.59 对成片 0.2891（**+3.0~+6.2 dB**）。
  ③ 因此「不压才像成片」是**反的**：削顶是我们的偏差，不是剪映的常态。U-78 的**事实半边定案**，
  剩下的是一次主增益/限幅标定（把我们的窗 RMS 曲线拟合到成片那条，看单一生增益能不能同时
  满足 RMS 与不越界）。
- **Path**：一次性内联统计（`ffmpeg -f f32le` + numpy 窗 RMS），成片 `<EXPORT_DIR>\<EXPORT_NAME>.mp4`。
- **证据等级**：成片侧**已验证**（两条独立解码路径：`astats` 码流域 / f32 样本域）；
  我方侧沿用 F-068 的 n=8 读数；**拟合律未做** → U-88。


## F-074 复合子画布→父画布映射律**用成片验掉了**（0.962 @64px 密集基线），U-76 的适用域问题不再是「等导出」

- **要分的岔路**：主轨 3 段全是加密 combination 缓存（U-80 不可解），播放器走的是**展开子时间线
  重画**这条路。子画布 1080×1440（`ratio:"3:4"`）嵌在 1080×1920 父画布里，此前只有
  「按宽拟合 + 垂直居中」这一条**猜出来的**律（P-14），依据是封面金色字幕落在 0.755。
  F-070 已证明封面是独立静帧、不能当同刻基准 ⇒ 那条律的证据基础塌了，必须重验。
- **Evidence**：`export_compare.py --from 0 --to 6.6 --step 0.2`（34 个位置，整段覆盖第一段
  复合子时间线的存活期）：中位 **0.990 @16px / 0.974 @32 / 0.962 @64 / 0.942 @128**，
  双判据 PASS；偏移直方图 0×17、+1×16（对半开，与 F-070 ② 同型）。
  最差单帧 **t=6.6 = 0.802**，正是该复合段的**结束边界**（下一段从 6.600 起）。
- **Finding**：① 「按宽拟合 + 垂直居中」（1080×1440 → 上下各 240 px letterbox）在**真 oracle**
  上成立到 0.962，且这是在主轨素材完全不可解、只能靠子层重画的前提下拿到的——**降级路径的
  像素正确性就此被独立确认**（此前只有截图判读，P-11/P-14）。
  ② 边界时刻（段切换的那一帧）是本判据的**已知弱点**：t=6.6 掉到 0.802 不是画错，而是
  「父段 target 末尾」与「子时间线最后一帧」谁有效没定。要判它，得单独在 6.55–6.65 以 1/30 s
  步长看两侧各画哪一段 → U-89。
  ③ U-76 剩下的**只有** `photo` 素材的基准缩放/锚点（本段没有 photo 样本），映射律部分结案。
- **Path**：`temp/playback-test/l3-child/rows.json`、`scripts/export_compare.py`。
- **证据等级**：**已验证**（n=34 密集位置，独立于此前所有封面判读）。


## F-075 L2 像素层的 oracle 从封面换成**成片同帧**：同一判据在两个 oracle 上一个过一个崩，封面此前在**掩盖**缺陷

- **要分的岔路**：修完 F-071 后，门里 L2（我们的 t=0.5 渲染 vs `draft_cover.jpg` 的金色文字层）
  从 PASS 变成 **FAIL，max delta 0.536、只检测到 201 px**。要么修坏了，要么这条判据的基准本身
  不成立。F-070 已经给出答案：封面是独立静帧，不是任何时间线时刻。
- **Evidence**：把 oracle 换成成片同帧（`--oracle-mp4`，取 `round(t×30)+3` 那一帧）后，
  同一条判据、同一个 `layer_metrics`：

  | 比对 | 检测像素 | 质心 Δcx/Δcy | 包围盒最大边差 | 判定 |
  |---|---|---|---|---|
  | 我们的 t=1.0 vs **成片第 33 帧**（白字幕层） | 139,936 / 145,175 | 0.001 / 0.001 | **0.010** | PASS |
  | 我们的 t=1.0 vs `draft_cover.jpg`（同色） | 139,936 / 142,975 | 0.017 / 0.030 | **0.166** | FAIL（封面白层只到 y=0.566，我们到 0.732） |

  门全绿读数（`--repeat 2`，oracle=成片）：**13/13**，L2 `max delta 0.01 over 139936 px`、
  fps 29.3、seek 25.5 ms、首帧 139.2 ms、Range 3702 次/10 s、`black_streaks`+`errors` 0/2、
  `rates_seen [44100, 48000]`、RSS peak 1235 MB。
- **Finding**：① 成片 oracle **更严也更好过**：白字幕层的质心与包围盒六项读数全部 ≤0.010
  （1% 画幅 ≈ 11–19 px），这是「我们画的字幕和剪映画在同一处、同一大小」的最强单点证据；
  而封面在同一判据下差到 0.166，说明**封面根本不该当同刻基准**。
  ② 此前 L2 对封面的 PASS 读数（P-23 记的 0.008）是**巧合通过**：t=0.5 落在两条隐藏叠加层的
  存活窗（0–0.567 s）内，而封面正是那三帧「画了隐藏层」的静帧状态（F-070/F-071）——
  我们错画、封面也含错画，两边一起错就对上了。**判据的 oracle 选错时，它会主动掩盖缺陷**。
  ③ 换 oracle 带来一条新约束：`--pixel-colour` 必须是**该时刻真活着**的层，否则报
  「layer missing on one side」（金色花字只在封面状态里，成片 t=1.0 只有白字幕）。已写进用法注释。
- **Path**：`scripts/playback_check.py`（`--oracle-mp4/--oracle-fps/--oracle-lead`，
  单帧 `select=eq(n\,IDX)` 抽取并缓存为 `temp/playback-test/oracle-frame-<idx>.png`）、
  `temp/playback-test/gate-export-oracle.txt`。
- **证据等级**：**已验证**（同一判据、两个 oracle 的对照读数，且门 13/13 复跑通过）。


## F-076 「混音比成片响 3–6 dB」不是电平选择，是 L1 丢了 `segments[].volume`：音乐床该 −8.0 dB，我们按满电平放（修后门 13/13，热尾消失）

- **要分的岔路**：成片母带 −0.026 dBFS / 零削顶 / 窗 RMS 最大 −10.78 dBFS，我们 0.41–0.59 且时有越界。
  三种解释没分开：① 缺一个主增益级（标定问题）；② 成片是限幅出来的（动态处理问题）；
  ③ 我们某条增益口径用错（缺陷）。**答案 ③**，而且不需要引入任何新的电平处理。
- **Evidence**：
  ① `materials.audios[].volume` 在 **37 条素材上全部缺失** ⇒ 播放器里 `aud.volume ?? 1` 恒为 1。
  ② `segments[].volume` 在 104 段里 100 段缺省、**4 段写非默认值**：track8 三条贯穿全片的
  音乐段都是 **0.3981 = 精确 −8.0 dB**，另一条是隐藏层 track5 的 0.001。
  ③ L1 模型段字段里**根本没有 `volume`**（只有 `audio/clip/extra_refs/features/id/material/
  media/render_index/source/speed/target/text/track/visible`）⇒ 段电平从未到达任何渲染链。
  ④ 逐段合算：track8 三段各带响度增益 −2.45 / −4.41 / **+6.22 dB**，成片应有的总增益是
  −10.4 / −12.4 / −1.8 dB，我们实际只有 −2.45 / −4.41 / +6.22 —— **三段整齐地差 +8.0 dB**。
- **修法**：`playback_model.py` 加 `volume` 通道与 `stats.volume_segments` 自证（打印
  `level-set 4`，与几何/hidden 同一族守卫）；播放器 `base` 改成
  `seg.volume ?? aud.volume ?? 1`（段优先），并把逐窗 RMS 数组 `rms_windows` 随 `/report` 交回。
- **修后门 13/13**（`--repeat 3`，oracle=成片）：fps 29.49、seek 36.5 ms、首帧 138.3 ms、
  Range 4959 次/10 s、`black_streaks`+`errors` 0/3、RSS peak 926 MB。
  **`peak_fs` 热尾消失**：修前 16 次跑 0.887–**1.68**、10/16 削顶；修后 0.8885 / 0.8913 / 1.0282 /
  1.1112，**4 次里 2 次削顶但幅度只剩 +0.02~+0.11 dB**（不再是 +2.6~+4.5 dB）。
  最响窗 RMS 从 −7.4 到 −12.2 dBFS，成片是 −10.78 —— **量级已经对上，离散还没收**。
- **更正我上一轮的因果读法（重要）**：修前 16 次跑的 `loudness_applied ≤4 ⇒ 0 削顶、≥5 ⇒ 削顶`
  是**完美可分**的，我据此说「双峰由响度增益应用条数决定」。**这个因果方向是反的、结论也不成立**：
  那 7 条响度目标里 **6 条是衰减**（−0.92…−4.41 dB）、只有 1 条是 +6.22 dB 抬升，
  所以「吃到的响度校正越多」应当**更轻**才对。修后重测四次：`loudness_applied` 5/4/10/3 对应
  `peak_fs` 1.028/0.891/0.889/1.111 —— **可分性直接碎了**（应用最少的那次反而最热）。
  真实关系是**共同因**：跑得越完整的批次，同时开着的流越多、应用到的响度条目也越多，
  两件事都由「这次调度抢到了什么」决定。U-86 的双峰因此**没有**被上一条解释掉，仍是开放问题。
- **读数陷阱（记下来）**：拿 `rms_windows` 整条算百分位**没有意义**——电池只跑约 10 s 且到处 seek，
  数组里大半是静音窗，p10/p50 全是 −180 dBFS。可比的统计量是**最响窗**（max / top-N），
  成片的包络是连续 73 窗，两边口径必须一致才能比。
- **Path**：`scripts/playback_model.py`（`volume` 通道 + `volume_segments`）、
  `temp/playback-test/player.html`（`base` 段音量优先、`rms_windows`）、
  `temp/playback-test/gate-segment-volume.txt`。
  过程中踩到一次自伤：重建 `model-proxy-a.json` 时先按「原始路径」覆盖了它，导致网关 404、
  黑帧守卫**正确地**报警（守卫有效第三次得到证明）；已按段 id 把 50 条代理映射与 25 条 media
  条目一并复原，并核对「段路径不在 media[] 里」= 0。
- **证据等级**：①②③④ 与修后读数 **已验证**；「共同因而非因果」是**已验证的反证**（修后配对打碎
  了可分性）；U-86 真因**未查**。

## F-077 混合模式的数值等价：5 个模式可用标准式，`叠加/强光` 是 CSS 那一对的反面（2026-10-23，要求 1 首轮判定）

**证据来源**：`<JY_INSTALL>	.6.0.14552\Resources\MixMode`（10 包全明文 GLSL，
`MixMode.json` sha256 前缀 `ad19693613ad`）；GPU 读数在
`ANGLE (NVIDIA GeForce GTX 1650, Direct3D11 vs_5_0 ps_5_0)` 上取，WebGL1、`RGBA8` 纹理、NEAREST、
逐 texel 比对。抽取与比对口径见 `scripts/mixmode_extract.py` / `scripts/mixmode_equivalence.py`。

**oracle 不誊写**：比对台直接编译包内 `.frag` 原文（sha256 记在 `tables/mixmode_frag_manifest.csv`），
对照腿是独立写的 W3C Compositing-and-Blending 可分离式（不看包内代码）。两条腿吃**同一份 8-bit 输入字节**，
所以差值只可能来自公式与 GPU 精度，不可能来自量化口径。网格 17×17（x=前景亮度级、y=背景亮度级，
k/16 全部可被 8 bit 精确表示）× alpha 对 6 组 × `_alpha` ∈ {1.0, 0.5} × 分支 {1=预乘, 2=直通}，
每模式 24 个 pass、27744 次通道比较。**判据 1/255 = 量化下界，不是缺陷**。

| nameId | 草稿名 | 预乘分支 maxΔ(8bit) | 直通分支 maxΔ | passes | 通道比较数 | 越容差次数 |
|---|---|---|---|---|---|---|
| color_filter | 滤色(=Screen 包) | 1 | 1 | 24 | 27744 | 0 |
| dark_en | 变暗 | 1 | 1 | 24 | 27744 | 0 |
| bright_en | 变亮 | 1 | 1 | 24 | 27744 | 0 |
| multiply_blend_mode | 正片叠底 | 1 | 1 | 24 | 27744 | 0 |
| linear_deepening | 线性加深 | 1 | 1 | 24 | 27744 | 0 |
| soft_light | 柔光 | 11 | 11 | 24 | 27744 | 375 |
| over_lay | 叠加 | 255 | 255 | 24 | 27744 | 9021 |
| glare_pc | 强光 | 255 | 255 | 24 | 27744 | 9021 |
| color_dodge | 颜色减淡 | 255 | 255 | 24 | 27744 | 72 |
| darken_color | 颜色加深 | 255 | 1 | 24 | 27744 | 36 |

**四条结论**：
1. **等价（可直接用标准式/CSS）**：`screen`(color_filter 包)、`darken`、`lighten`、`multiply`、
   `linearBurn` 五包两分支 maxΔ ≤ 1。
2. **`叠加`/`强光` 是 CSS 同名模式的反面**（源码级判定，不只是读数）：包内
   `OverlayPreMul` 分支条件是 `2.0 * bc < ba`（**看背景**），`HardLightPreMul` 是 `2.0 * fc < fa`
   （**看前景**）；而 W3C 的 Overlay 看源、HardLight 看背。所以剪映「叠加」= CSS `hard-light`、
   剪映「强光」= CSS `overlay` —— `spec/picture.yaml` 原 `mapping_to_css` 的这两行**是错的**，
   就地更正。两模式 maxΔ=255 的来源就是这一个「fg/bg 交换」，不是精度。
3. **柔光用经典 `sqrt` 形式，不是 W3C 的多项式形式**：maxΔ=11（约 4%），出现在
   `cs>0.5` 那半支；包内 `SOFT_LIGHT` 注释还留着被注释掉的宏。差异量级足以被像素比对看见，
   所以柔光必须移植包内数学，不能用 CSS `soft-light`。
4. **`颜色减淡`/`颜色加深` 的包内预乘支与标准式在极值点系统性相反**（maxΔ=255），且
   `darken_color` 的**直通分支只差 1** ⇒ 差异**只出现在包内预乘支**，属该分支自身的归一化/特判约定
   （`fc == 0.0`、`bc == ba` 这类 float 相等特判 + `Eps` 钳位），不是模式定义不同。
   这一条留给 U-90：要在**同一次浏览器会话**里按 (fg,bg) 定位崩口，并确认引擎实际给
   `blendAlphaState` 送哪个值。

**顺带定掉的旧悬念**：包内 `main()` 走哪条分支由 uniform `blendAlphaState` 决定，而
`blend.material` 的属性表只有 `inputWidth inputHeight _alpha baseTex _MainTex`（10 包同形）——
**`config.json` 的 `alphaState: 2` 不是这个 uniform**，`picture.yaml` 那句「与『预乘』一致，但含义未证」
应改为「与 shader 的 alpha 分支无直连证据」。frag 自带注释给的是 `1: pre-multiplied, 2: straight`。

**对本机的影响**：测试草稿 0 个 `mix_mode` 引用，所以这条判据只能在合成网格上证（本 F），
不能靠成片比对；播放器与通道 2 目前都**未实现混合模式**（`player.html` 全文 0 处 blend、
`render_frame.py:14` 明写不处理），要求 1 由「未测」变为「已测 + 已知实现路线」。

**复现**：`python scripts/mixmode_equivalence.py`（自起网关与 headless Chrome，约 20 s；
读数落 `temp/playback-test/mixmode-verdict.json`，表落 `docs/evidence/tables/mixmode_equivalence.csv`）。

**证据等级**：已验证（oracle 为包内原文编译执行，独立实现腿不看包内代码，单变量=公式）。

## F-078 `material_animations` 的实际形状是 `animations[]`，L1 按 `{in/out/loop:{actions}}` 取所以整条通道为空（2026-10-23，P-29 的因）

- **Evidence**：`<草稿A>` 时间线 `017E2FEC`，段 `14D93F1F`（flag=2 叠加、t0=6.600 s、
  34 个 extra refs）。其 `materials.material_animations[]` 条目实测为
  `material_type` 等键）；而 `scripts/playback_model.py` 旧 `features()` 取的是
  `(a.get("in") or {}).get("actions")` 那一形，对本草稿 65 个引用段**恒为空**。
- **更正（本 F 第一版把责任归错了）**：我最初写成「规格记的是 `{in/out/loop:{actions}}` 那一形」。
  **权威规格是对的**——`spec/animations.yaml:13-18` 逐字段列了
  `animations[]{id, type, resource_id, path, material_type, duration, name, category_name, panel, start, …}`
  （连 r3 每个键的出现次数都统计过），`:19-20` 给了 `types: [in, out, loop, caption, group]` 与计数，
  `:32-40` 的 `timing` 段明写「渲染必需，此前规格完全没记」并给了 `duration_ranges`。
  ⇒ **不是规格错，是代码没按自家规格取数**（与 P-13「`clip` 挂在 segment 上却被从 material 里读」同型）。
  `scope-and-phases.md:17` 那句「`material_animations` 的 in/out/loop」是简述，不是形状声明。
- **Finding**：
  1. **形状**：本机 33 条全部走 `animations[]`（= `spec/animations.yaml:13-18` 的权威形）；代码里保留的
     `{in/out/loop:{actions}}` 分支只是「不丢弃未知形」，本草稿**零出现**。
     **引用计数必须分层**：引用段 65 / 真带动画条目段 33 / 条目总数 33（每段最多一条），其余 32 段那个 bucket 里是空容器。
  2. **规模与归属**：`material_animations` 是 phase 1 明列项（`spec/00-overview.md`、`spec/animations.yaml`
     整份就是它的规格），所以这不是范围外，而是**实现没按规格取数**。
     P-29 那个 6.6 s 的 0.3 s 白闪就是它的第一条见证。
  3. **动画名分布（33 条，按出现次数）**：打字光标 in 0.2 s ×14（入场）、向下滑动 in 0.5 s ×4、
     生长 II in 0.5 s ×3、弹入 in 0.5 s ×2、向下滑动 in 0.3 s ×2、向上闪入 in 0.3 s ×1、
     侧滑 in 0.3 s ×1、模糊消失 **out** 0.4 s ×1、缩小 in 0.5 s ×1、向上露出 in 0.5 s ×1、
     放大震动 in 0.5 s ×1、向右模糊 II in 0.5 s ×1（其余为长尾）。
     **本时间线的动画主力是文字侧「打字光标」（14/33），画面侧只有 19 条**。
  4. **曲线不在草稿字段里，在包内 lua 里**（规格 `animations.yaml` 此前也没有这条）：形如
     `fromTo(target, {["localPosition"]=Amaz.Vector3f(0.0, 2.66 * textureH / screenH, 0.0)}, {…},
     0.1, Amaz.Ease.quadOut, …)`。三个后果：① **tween 时长（0.1 s）≠ `duration`（0.5 s 预设槽长）**，
     按 0.5 s 窗量会把 3 帧的差摊到 15 帧（P-30 第一版就摊了，所以中位数只动 0.008）；
     ② `textureH` 是 sprite 纹理高、`screenH` 是输出高 ⇒ 位移量随层尺寸变；
     ③ 本时间线 14 个预设里**只有 3 个**用 `fromTo` 声明（向下滑动/缩小/渐显），
     其余走 AE 导出脚本或 `onUpdate` 显式数学，**不能假装覆盖**。
  5. **可渲染性**：动画包在 `User Data/Cache/effect/<resource_id>/<md5>`，**33/33 本机全在**，
     包内是**明文** `*.frag`/`*.vert`/`*.xshader` + `lua` 脚本 + `Quad.mesh`。
     「向上闪入」包里就是 `Exposure`（曝光，白闪的来源）+ `GaussianBlur` 两个 effect，
     各带一份 shader 与一份 lua 时间轴脚本 ⇒ 入场动画的实现路线是**执行包内 shader**，
     与 MixMode 那批同源（`.frag` 明文当 oracle），不是靠名字猜曲线。
- **已改**：`playback_model.py` 增加 `segments[].animations[]`（kind/name/duration_us/resource_id/
  category_name/panel/material_type/path/package_exists）与 `stats.animation_segments`，
  `features.animation` 改由真实条目得出；模型重建后 `features: {{animation: 65, effects: 25, transition: 1}}`、
  errors 0 / warnings 0。**渲染器尚未消费该字段**（下一件事）。
- **Path**：`temp/playback-test/model-check.json`（重建）、`temp/playback-test/gate-after-anim.txt`（回归门）。
  复现：`python scripts/playback_model.py "temp/playback-test/plain/<草稿A>__draft_content.json.dec.json"
  --draft-root "<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>"
  --timeline 017E2FEC-11D0-47d6-87C1-9709D2A2F18D --out temp/playback-test/model-check.json`
- **证据等级**：已验证（草稿字段直读 + 修正前后的模型计数 + 包内文件清点）。

## F-079 混合模式已实现并双向验死：出厂 GLSL 与包内原文 maxΔ=0，numpy 通道 maxΔ=1 且 0 格越界（2026-10-23）

- **做法（关键是「不誊写」）**：`scripts/mixmode_shaders.py` 从包内 `.frag` 原文**切片**——保留
  「文件头 + 到该模式 `vec4 XBlendPreMul(...)` 结束的右括号」逐字节不动，只接我们自己的 `main()`
  （我们的纹理是预乘的，所以固定走预乘支、不读引擎那三个 alpha 状态 uniform，见 U-90）。
  产物 `temp/playback-test/mixmode/frags-shipped/*.frag`、浏览器出厂模块 `mixmode-blend.mjs`、
  表 `tables/mixmode_shipped.csv`（`vendor_sha16 ↔ shipped_sha16 ↔ 保留字节数`，
  保留 753–1,727 B/模式）。通道 2 用 `scripts/mixmode_blend.py`（numpy，**手抄**，所以必须外部验）。
- **三方对照（`scripts/mixmode_equivalence.py` 扩展后，oracle 仍是包内原文在 GPU 上的输出）**：
  每模式预乘支 12 个 pass × 17×17 × 4 通道 = **13,872 次通道比较**，10 模式共 **138,720** 次。

  | 对照 | 最大差（8 bit） | 越 1/255 容差的格子 |
  |---|---|---|
  | 出厂 GLSL vs 包内 GLSL（同 GPU） | **0**（10/10 模式） | 0 |
  | numpy 通道 2 vs 包内 GLSL | **1**（10/10 模式） | **0/13,872 每模式** |
  | W3C 标准式 vs 包内 GLSL（复测） | 5 模式 ≤1、柔光 11、叠加/强光/减淡/加深 255 | — |

  ⇒ **要求 1 的等价对象现在是「我们出厂的那份」而不只是「标准式能不能用」**。
  第三行同时复现 F-077：`柔光/叠加/强光/减淡/加深` 五个模式**不能**用 CSS/Pixi 的标准式，
  差到满量程；`maxΔ=1` 是 RGBA8 的量化下界，不是缺陷。
- **接线也被证了**（`scripts/mixmode_wiring_check.py`，构造样本，草稿不动）：本草稿 0 个 `mix_mode`
  引用，所以门的 L1~L6 永远不会碰这条新路径，「写了」不等于「生效」。把 `model-check.json` 的
  23 个 flag=2 叠加段注入模式后同刻渲染：普通 **98.83** → 正片叠底 **55.36** → 滤色 **180.13**
  （三张互不相同），未知包 md5 **计入降级并按普通合成画**（该时刻在动的 1 段 → 降级 1，与期望等）。
  6/6 PASS。**顺带抓到自己的口径错**：第一版把「降级数」按全时间线注入的 23 段来期望，
  把正确的实现报成 FAIL——降级只能按「该时刻真在画的段」数。
- **L1 也补上了载体**：`segments[].mix_mode = {{name, package_md5, ref}}`（直连键是
  `effects[].path` 尾段的包 md5，F-049），并加 `stats.mix_mode_segments` 自检。
  本时间线该值为 0，所以这条通道的回归验证从此靠构造样本，不靠草稿。
- **一条方法学记录（本轮唯一一次「绿色数字是错的」）**：扩展比对台时我把
  `gl2.useProgram(prog)` 随一次字符串替换删掉了，于是每一遍画的都是**上一个 pass 残留的 program**，
  十个模式全部报 255（连 F-077 里本来就等价的五个也一起坏）。发现方式不是重读代码，而是
  `ship`/`numpy` 两列与「已知等价」互相矛盾——**多列冗余读数能揭示单列读数的失效形态**，
  这与 P-21 把判据从「会喊」扩成「有图层没出图也要喊」是同一条纪律。
- **Path**：`scripts/mixmode_shaders.py`、`scripts/mixmode_blend.py`、`scripts/mixmode_wiring_check.py`、
  `docs/evidence/tables/mixmode_shipped.csv`、`temp/playback-test/mixwiring/`。
- **证据等级**：已验证（oracle=包内原文 GPU 执行；实现两侧分别是同源切片与外部逐格核对的手抄；
  接线用方向判据而非「像素不同」）。

## F-080 判字幕动画要用「该层自己的列范围」；整帧相关与全画面质心都没有区分力（2026-10-23，P-33 三把尺对照）

- **背景**：F-072 已经量出整帧相关的区分力边界——**删掉全部字幕轨，整帧只掉 0.005~0.024**。
  本轮实现了字幕入场动画之后，正好拿到一次正向验证机会：同一个改动、三把尺同时量。
- **对照（同一批时刻、同机、只切 `APPLY_ANIMATIONS`）**：

  | 判据 | 读数 | 有没有区分力 |
  |---|---|---|
  | 整帧 luma 相关（`animation_gap.py`，64 px，固定帧号） | inside 中位 0.9627 → 0.9627，**逐段 Δ=0.000** | **无**：与 F-072 一致，不是代码没生效 |
  | 全画面单色质心（借门里 L2 的 `layer_metrics`） | 更近 5 / 更远 3 / 不变 20，逐行 ON=OFF | **无**：淡出时字幕掉出色彩掩膜，质心被同色的另一条字幕接管 |
  | **该层列范围内 RGB MAD vs 成片同帧**（`animation_region_check.py`） | **更近 22 / 更远 0 / 不变 10**，MAD 中位 19.79→19.68 | **有**：方向从未错（0 次变远），量级改善小是因为列范围里大部分是背景 |

- **Finding**：判**文字层**改动必须把度量限制在该层自己的占位范围内——先把它孤立渲染（画到黑底）
  取横向边界，再在成片尺度上比 RGB MAD。整帧相关和全画面色彩掩膜质心都会把「字幕变了」
  读成「没变」，而**读数不变会被误当成「改动无效」**：本轮如果只有整帧判据，就会得出
  动画实现没起作用的黑结论，而接线检查（期内 Δmax 最高 255、期外逐字节相同）证明它是活的。
- **口径**：MAD 是 0..255 的 RGB 平均绝对差，比较发生在**同刻**（成片帧号 `round(t*30)+3` 固定，
  不搜偏移，P-29）；两侧统一到 `--oracle-width` 尺度并用 BOX 降采样（与 `export_compare.luma` 同口径）。
  覆盖度只有 3 个预设 / 8 段（全时间线 14 预设 / 33 段，其余 9 预设未覆盖，见 U-91），
  所以这张表判的是「已实现的部分被看得见」，不是「动画都做完了」。
- **Path**：`temp/playback-test/anim-ab-{off,on}.json`、`anim-layer.json`（作废判据的留档）、
  `anim-region.json`、`animwiring/wiring.json`。复现三条分别见 P-33 的 Path 段。
- **证据等级**：已验证（三把尺同一批数据对照，且各自失败模式都被独立解释）。

## F-081 U-86 的观察性判定：14 个候选字段按「爆/不爆」分组**全部重叠**，这条不能靠日志判（2026-11-23 记，实验在 P-35）

- **问题**：同一草稿、同一参数，混音有时出满刻度窗有时不出（`peak_fs` 从 0.887 一路散布到 1.676）。
  F-076 修掉 `segments[].volume` 缺失之后热尾已消失，但离散还在（U-86 收窄后的形态）。
- **做法**：把历史 `/report` 里所有吃 `model-proxy-a.json` 且带 `play.audio.peak_fs` 的跑数取出来，
  按「有 >=1 个满刻度窗 / 没有」分成两组，逐个候选字段比中位与区间，并显式检查是否**可分**
  （`min(爆) > max(不爆)` 或反之）。
- **读数（口径：跑数，n=54）**：有满刻度窗 **30** 跑 / 没有 **24** 跑。
  `peak_fs` 全体排序后是两个群：16 跑紧贴在 **0.887~0.892**，其余连续散布 **0.903~1.676**。
  候选字段：`audio.chunks`（爆中位 3195.5 [1853..4517] vs 不爆 2765 [1787..4176]）、
  `audio.nodes`（162.5 vs 140）、`loudness_applied`（6 vs 3）、`fades_applied`（3 vs 3）、
  `pool`（6 vs 7）、`requests`（4179 vs 3734）、`pump.dropped`（227.5 vs 234.5）、
  `pump.live`（2 vs 2）、`decoded`（524 vs 536）、`composited_fps`（29.62 vs 29.29）、
  `realtime_factor`（1.00 vs 1.00）、`first_frame_ms`（140.65 vs 147.10）、
  `seek.n`（12 vs 12）、`seek.median_ms`（36.8 vs 30.3），
  以及最像「覆盖差异」的 `play.source_seconds_advanced`（**9.98 vs 9.99**，区间 5.97..10.00 vs 9.96..10.00）。
  **14 个字段全部重叠，无一可分。**
- **Finding**：**这条判不了，且「判不了」本身就是结论**（本项目已有先例：U-01/U-24 按此改标注）。
  两个具体含义：
  1. 不能再用观察性配对给 U-86 找成因——上一轮我正是这么在 `loudness_applied` 上得出**错**解释的
     （7 条响度目标里 6 条是衰减，方向本来就讲不通；修后 4 次配对也把可分性打碎）。
     这次连「电池只覆盖 10 s ⇒ seek 覆盖不同」这条最合理的假设，都被 `source_seconds_advanced`
     两组都 9.98 s 顶回来。
  2. 判 U-86 只能靠**设计实验**：同一模型整条时间线确定性播放（`seeks=0`、`playms > 时长`）重复 N 次。
     分支预先写死，避免事后编故事：极差 ≤0.02 ⇒ 离散来自 seek 覆盖，混音判据必须按全时间线测；
     仍然飘 ⇒ 是混音侧竞态，转 P-18/P-22 的 `streamFor` 归属那条线。
     实现 `scripts/mix_stability.py`，结果见 P-35。
- **顺带一条读数陷阱**：历史跑数里 `play.audio.rms_windows` 大多是空数组（中位 0 个元素）——
  它是 F-076 之后才加的字段，**旧跑数没有**，所以任何按它做的百分位/极值统计都只能用在加字段之后的
  那批跑数上；我这次差点把它当「静音窗」解释，实际是没记。
- **证据等级**：已验证（n=54 跑数的分组与可分性检查；结论是「不可分」而非「无关系」，
  两者的区别就是这条为什么必须做实验）。

## F-082 U-86 的设计实验否证了「seek 覆盖」解释：整条时间线、零 seek，`peak_fs` 照样飘（2026-10-23）

- **分支预先写死**（写在 `scripts/mix_stability.py` 文件头，避免事后编故事）：
  同一模型 `playms > 时长` 且 `seeks=0` 重复 N 次，极差 ≤0.02 ⇒ 判据口径问题（离散来自 seek 覆盖）；
  仍飘 ⇒ 混音侧竞态，转 P-18/P-22 的 `streamFor` 归属那条线。
- **读数（n=3，口径：跑数；整条 36.83 s 时间线全覆盖，`source_seconds_advanced` 38.31/38.32/38.33 s）**：
  `peak_fs = 0.9143 / 0.9922 / 1.0179`，**极差 0.1036 > 0.02**。
  伴随量：`audio.chunks` 4935/4986/5150、`nodes` 265/269/275、合成 29.49/29.49/29.74 fps、
  `rt` 0.999 全部一致；**第二跑 `errors` 有 12 条**（`Input has been disposed` 那一族，见 P-31），
  而它的 `peak_fs` 落在中间。
- **Finding**：
  1. **「电池只覆盖 10 s ⇒ seek 覆盖不同所以峰值不同」这条假设被否证**。这条假设当时看起来很合理
     （F-081 里连 `source_seconds_advanced` 都看不出差别），但把窗口换成整条时间线后离散照旧。
     这正是本项目为什么要做设计实验而不是继续找相关。
  2. **离散在混音侧**，且与音频量无关：`chunks/nodes` 几乎相同、帧率与实时因子一致，
     所以不是「少喂了几块」。剩下的候选是**同一批块以不同顺序/时刻进入 `BufferSource` 队列**
     （多轨混音的到达顺序依赖解码进度），这正好和 P-31 的偶发 `disposed` 同一族——
     **两条开放项可能同因**：U-86 与 L6 的偶发错误。下一步按这条去查（记录在 U-86）。
  3. 顺带定一个口径：**混音的峰值判据必须按整条时间线测**。10 s 电池给出的 `peak_fs`
     连「有没有满刻度窗」都不稳定（n=3 里 1 跑有 2 个窗、2 跑没有），
     拿它当判据等于判噪声。
- **未做完**：n=3 太小，正在加到 n=5（`temp/playback-test/mixstab5.txt`）；
  以及「到达顺序」这条要有直接证据（同一跑内记录每轨首块到达时刻与混音窗口峰值的关系）才能结案。
- **Path**：`scripts/mix_stability.py`、`temp/playback-test/mix-stability.json`。复现：
  `python scripts/mix_stability.py --repeats 5`（约 4 分钟，机器需空载，别与门并跑）。
- **证据等级**：已验证（单变量=测量窗口；结论是**否证**，且给出了下一条候选机制）。

## F-083 浏览器通道在视频带比通道 2 亮约 2 个码值——但「字幕带两边一致」这半条已被 F-084 否证（2026-10-23，L10 首轮；2026-10-24 就地更正）

- **仪器**：门新增 L10 —— 页面用 `app.renderer.extract.pixels(app.stage)` 取自己画的那一帧，
  降到 540 宽 POST 给网关 `/shot`，脚本把同一时刻的通道 2 帧与成片帧拉齐到同一尺度比。
  首跑读数（`temp/playback-test/browser-shots-samemedia.json`，4 个时刻，通道 2 用**同一个代理模型**）：

  | t | 浏览器 vs 通道 2（固定同刻） | 浏览器 vs 成片（±3 搜对齐，报偏移） |
  |---|---|---|
  | 1.0 | **0.948** | 0.970（−1 帧） |
  | 6.633 | 0.992 | **0.898**（+3 帧，`向上闪入` 的白闪帧） |
  | 20.230 | 0.989 | 0.953（−1 帧） |
  | 28.130 | 0.991 | 0.951（−1 帧） |

- **t=1.0 那 0.05 的跨通道差「不是采样问题」这半条成立，「差在素材画面」那半条已被 F-084 否证**：
  截图与目标时刻差 **0.0 s**（页面把 `__lastPaintUs` 随图回传，判据端核验，不再假设「拍到的就是那一帧」）。
  ~~分带 MAD：y 0.02–0.62 每带 11.5–15.3，而 y 0.75–1.00（白字幕带）只有 2.9–3.0 ⇒ 分歧在素材画面，
  不在我们画的文字层。~~
  **更正（F-084）**：那个「字幕带」的 y 范围是**按字幕大概位置猜的**——真行窗由模型几何定在
  **y 0.671–0.771**（v_center = 0.5 − clip.y/2 = 0.7214），我那条网格量的是字幕**下面**的素材。
  按真行窗重测，t=1.0 带内 >200 的墨：浏览器 3544、通道 2 **43**、成片 3476 ⇒
  跨通道崩口的主因是**通道 2 没把字幕画出来**（缺字体后回退成 10 px 点阵豆腐块），不是色彩路径。
- **哪一侧偏离成片**：视频带（y 0.02–0.42、x<0.5）均值成片 = 140.79，
  **浏览器 141.41（+0.62）**、**通道 2 139.98（−0.81）**；整帧 MAD 对成片浏览器 **11.06**、通道 2 **8.20**。
  ⇒ 浏览器比通道 2 亮约 **1.8 个码值**，且整帧上通道 2 更贴近成片。
  ~~字幕带两边一致（MAD ~3）说明差异来自视频解码/GPU 上屏这一段，不是布局律。~~
  **这条读数本身有效（口径：该视频带的均值），但它不是 t=1.0 跨通道崩口的主因**（见上一条更正）；
  而且它的**符号都不稳**：t=1.0 是通道 2 更贴近成片，t=7.0 反过来是浏览器更贴近
  （对成片整帧 MAD 浏览器 11.0 / 通道 2 13.34）⇒ 「浏览器系统性偏亮」目前不是一条律，见 U-93。
- **候选机制（按可能性排，均未取证）**：
  ① Pixi 8 的纹理色彩空间处理（`colorSpace: 'srgb'` 与渲染器 sRGB 输出之间多做了一次转换）；
  ② `createImageBitmap(videoFrame, {resizeWidth, resizeHeight})` 的色彩空间默认值；
  ③ WebCodecs 对代理片（`yuv420p`，标注 bt709 vs bt601 / limited vs full）的转换与
  ffmpeg 那条路不一致。
  判据已经备好：同一条代理片，分别用 WebCodecs 与 ffmpeg 解出同一帧，比均值与逐像素 MAD；
  若均值差 ≈ 这 1.8 码值，就落到 ③/②，若只在 Pixi 上屏后出现就落到 ①。
- **为什么这不是「小 numerics」**：交互预览就是产品本体（M1-D 定案保留 web 方案），
  成片比对走的是通道 2。两条通道对同一素材差 1.8 码值时，
  **「预览里看着对」和「校验说对」不是同一个画面**——L10 之前这层从未被测过。
- **证据等级**：读数**已验证**（浏览器自取帧 vs 同模型通道 2 vs 成片同刻，采样时刻经回传值核验）；
  但本条的**结论「分歧在素材画面、字幕带两边一致」已被 F-084 否证**——那条分带定位用的 y 范围是猜的，
  且视频带 1.8 码值这条**随时刻变号**，不是一条律。引用本条时以 F-084/U-93 的口径为准。


## F-084 跨通道崩口的真因是**草稿字体被剪映中途清掉**后通道 2 静默回退成 10 px 豆腐块（浏览器同样受影响，只是回得更好）（2026-10-24，U-93 反转；条件口径见 P-41）

- **触发**：F-083 把 t=1.0 的跨通道崩口（0.948）按固定分带网格判成「差在素材画面，字幕带两边一致」。
  那个网格的 y 范围是我**按字幕大概位置猜的**。这次换一台把比较区交给证据的仪器：
  `scripts/caption_ink_check.py` —— 三条腿（浏览器回传帧 / 通道 2 / 原生导出同刻帧）一律降到
  540×960（BOX），**行窗由模型的字幕几何定**（v_center = 0.5 − clip.y/2，上下各 max(0.05, 0.8·em)），
  横向范围由**成片腿自己 >200 的亮墨包围盒**定，然后逐腿报墨量（绝对码值阈）、墨盒、对成片 corr/MAD。
- **读数（t=1.0，成片帧 33，白字幕「大家好我们逛了<素材语料>」size=10、clip.y=−0.4427、无动画）。
  口径警告：这张表是**跨条件**的——浏览器那一行取的是门 03:18 重截**之前**的截图（那时真字体还在），
  通道 2 那一行取的是重截**之后**的渲染（字体已被清）。同条件的数在本条最后的「修后读数」里，
  单独引用下表任何一行都会得出错的结论（详见 P-41）**：

  | 腿 | 带内 >200 墨 | >220 墨 | 对成片 corr | 对成片 MAD |
  |---|---|---|---|---|
  | 浏览器（旧截图，真字体在） | **3544** | 3257 | **0.789** | 20.0 |
  | 通道 2（修前，字体已没） | **43** | 5 | 0.427 | 32.4 |
  | 成片（剪映自己渲染时） | 3476 | 3208 | 1.0 | 0.0 |

  ⇒ **F-083 的方向是反的**：崩口的主因在**字幕这一层**而不是素材画面——通道 2 当时根本没把字幕
  画出来，只画了 43 个亮点。（但「浏览器本来就对」这句要等同条件复测才算数：重截之后浏览器
  自己也只剩 2221，见本条末尾。）
- **真因（一步定位，非猜测）**：`render_frame.load_font` 在请求字体不可用时落到
  `ImageFont.load_default()`——约 10 px 的点阵字，中文全是豆腐块。本例 42 条字幕样式**全部**指向
  `…/User Data/Cache/effect/7080096967543493150/e5338c6e…/HelloFont_ID_JianSong_95.ttf`，
  而该目录在这台机器上已经不存在（`Resources/Font`、`Resources/Font/SystemFont` 里也没有这款）。
  于是通道 2 把这条时间线的**每一条**字幕都按 1/4 字号画成豆腐块；浏览器侧 `loadFonts()` 按
  `f.exists` 跳过缺失字体、交给系统 sans-serif，**反而**画对了尺寸（同一条 em 律 px=62）。
- **为什么这条**不是**「四层都没看见」——本条初稿写错了，就地改**：给 L2 加墨量判据之前先做
  **负样本**（清空 `FALLBACK_FONTS` 重演豆腐块，再跑 `layer_metrics`）：豆腐块的白 mask
  `y1 = 0.540` vs 成片/修后 0.732/0.733 ⇒ **Δ0.192 ≫ 0.02，L2 本来就抓得住**（字幕是画面里最低的
  白东西，1–99 百分位盒的下边就是它定的）。它没红，是因为**字体是本次会话中途才从机器上消失的**
  （见下下条），不是判据瞎。而我准备加的「整帧墨量比」是**空判据**：豆腐块读 ink_ratio **0.865**
  （整帧白 mask 被素材亮区主导，字幕只占百分之几），任何合理带宽都拦不住 ⇒ 已回退成只报不判。
  墨量只在**字幕带内**才有判别力（43 vs 3476 那个才是信号）。
  教训同族但方向不同：**给判据加「牙齿」之前先造负样本，否则加进去的是安慰剂。**
- **回退字体是标定出来的，不是挑的**（`--sweep-fallbacks`，同一条 t=1.0 带、判据=对成片墨量与 corr）：
  雅黑粗体 墨 3961 / corr 0.777 / MAD 20.5 ← 采用；黑体 1962 / 0.765 / 20.3；
  雅黑常规 2295 / 0.715 / 22.6；思源 VF 721 / 0.605 / 27.0。
  缺的那款是 **JianSong 95（重宋）**，所以默认先落到重字面；常规字面把笔画量差到 1/5。
- **上面那张三腿表是跨条件比较，必须按这个口径读**：门在 03:18 重截浏览器帧**之前**那份截图里
  浏览器字幕墨 3544 ≈ 成片 3476（说明它是在**真字体还在**的时候画的），而通道 2 在 03:11 已经
  画成豆腐块；重截之后浏览器也只剩 **2221**（= 成片的 64%）。⇒ 同条件下的真差是
  **浏览 2221 / 通道 2 3961 / 成片 3476**：**两侧都偏离成片、方向相反**，差的都是「拿别的字面
  替代重宋」。已把浏览器侧接到**同一条标定**（`Microsoft YaHei` + `fontWeight:700`；原来写死
  `sans-serif`，Chromium 落常规体）。
- **环境事实（这一族读数的公共前提，别读成代码回归）**：草稿字幕依赖**机器上的 effect 缓存字体**，
  剪映随时可以清掉它；而模型里 `fonts[].exists` 是**建模型那一刻的快照**
  （`model-proxy*.json` 至今写 `exists: true`，文件已不在）。于是浏览器去取一个取不到的字体，
  报 `A network error occurred`，被 L6 记成错误——**这次门 L6 红就是它**，不是混音也不是黑帧。
- **修后读数（同条件：03:18 重截之后的浏览器帧）**：带内字幕墨 浏览 **2221** / 通道 2 **3961** /
  成片 **3476**；整帧对成片 corr 通道 2 **0.9679** > 浏览器 0.9109。L10 跨通道 t=1.0 从 0.948
  掉到 **0.898**——**这不是回归**，而是那条比较里两个通道各自换了字面（浏览器从真面掉到系统回退面，
  通道 2 从豆腐块换到标定面），两边都不再是原来的东西。字幕解释完之后**剩下的素材残差**
  （F-083 的 1.8 码值同族）**符号都不稳**：t=1.0 通道 2 更贴近成片，t=7.0 浏览器更贴近
  （对成片整帧 MAD 11.0 vs 13.34）⇒「浏览器系统性偏亮」不是一条律，U-93 已按此收窄。
- **顺带结案 U-94**：t=12.0 那个跨通道 **−0.370** 是**旧截图的几何**造成的——那份
  `browser-shot-12.png` 是 540×**953**（其余 540×960），拉平到同一尺度时整幅被错位；
  门 03:18 重截成 540×960 后同一时刻读到 **0.980**。⇒ 不是「两条通道画了不同内容」，
  是判据端拿了一张不该拿的图。已在 `browser_shot_check` 加**截图几何核验**（比例与模型画幅不符就跳过并报），
  因为「一张过期截图」这种失败模式**不会报错，只会给出一个看起来很严重的负相关**。
- **这条律早就在我们自己的规格里，是代码没实现它**：`spec/text.yaml` 的 `fonts.resolution_chain`
  第五、四级就是「系统字体 → 兜底默认字体」，旁边还写着
  「`font_path` 为绝对路径且可能失效；解析必须多级回退」——当时标的是 `# single`（一条推测）。
  两条渲染通道**都没实现这条回退**：通道 2 直接掉到 PIL 点阵，浏览器掉到 CSS `sans-serif`。
  所以 F-084 不是「发现了一条新律」，而是**一次推测级条目被事故升级为 verified**（同
  「先查自己规格再宣称发现」那条教训的反向情形：规格对了、代码错了，错的是代码）。
  已就地把它写成可执行口径：`fallback_law`（必须能画中文 / 保持请求字号 / **字重是量出来的** /
  **两条通道必须落同一条标定**）+ `known_ceiling`（缺面时笔画级保真不可达，实测两侧都比成片多墨
  14–19%），并把 `shipped_fonts` 的路径改对（实测在 `%LOCALAPPDATA%/JianyingPro/User Data/Resources/Font`，
  安装目录下那条**不存在**）。
- **Path**：`scripts/caption_ink_check.py`（新）、`scripts/render_frame.py`（`FALLBACK_FONTS` +
  `FONT_FALLBACKS` 计数 + stderr 上报）、`temp/playback-test/caption-ink*.json`。复现：
  `python scripts/caption_ink_check.py --timestamps 1.0 --sweep-fallbacks`。
- **证据等级**：已验证（三腿同尺度、行窗来自模型几何、墨量用绝对码值阈、回退字体经标定选定）。

## F-085 动画欠口的真实形状：没有「再补一条曲线」的便宜可占了——T1 档实测 0 个预设（2026-10-24，U-91 定档）

- **仪器**：`scripts/animation_tiers.py`（新，表 `evidence/tables/animation_tiers.csv`）。
  口径按**带真条目的段数**加权（不是预设个数、不是引用数），层级规则**写死在代码里**：
  T0 曲线可求值；T1 = 1 lua 且无 `.frag`（只差读取器）；T2 = 1 lua + ≥1 `.frag`（要执行包内 shader）；
  T3 = ≥3 lua 或 ≥2 `.frag` 或有 `.rt` 链或 AE/LightSpeed 导出件（要脚本运行时/多 pass）。
- **读数（本时间线 12 个预设 / 33 个带动画的段；下表是**加了 frag 语义细分之后**的终版，
  第一版只按实物计数把 T2 记成 3 预设/17 段=51%，那个数**偏悲观**，原因见下）**：
  - **T0：3 个预设 / 8 段 = 24%**（向下滑动 6、渐显 1、缩小 1；解出的属性只有 alpha/position/scale）
  - **T1：0 个预设 / 0 段 = 0%**
  - **T2a：2 个预设 / 15 段 = 45%**（打字光标 14、向上露出 1）——frag **只采样一次、无循环、无邻域**，
    属于 **mask/blit 类**（向上露出实测就是
    `texture2D(_MainTex,uv0) * step(uv.y, 1-(1-height_cut)*0.4)`：一个均匀量驱动的行遮罩）
  - **T2b：1 个预设 / 2 段 = 6%**（弹入：采样 3 次 + 2 个循环）
  - **T3：6 个预设 / 8 段 = 24%**（生长 II 3、侧滑、向上闪入、向右模糊 II、放大震动、模糊消失各 1；
    最重的 向右模糊 II 是 **21 个 `.frag` + 8 个 `.rt`**，侧滑 frag 内 **25 次采样**，
    模糊消失带 `.lsanim/.lsproj/.jsdat` = AE/LightSpeed 导出工程）
- **为什么细分这一层（这是本条真正的结论）**：只看包内**计数**会把「有个 `.frag`」当成「必须跑 GLSL」。
  实测第一个 T2 预设就否掉了这条推断——它的 frag 是一句行遮罩，**两条通道都不需要执行 GLSL**
  （PIL 乘 alpha、Pixi 裁 alpha 即可）。所以判据要问的是 frag 的**语义**（采样次数/循环/邻域/RT 链），
  不是文件个数。⇒ 仪器改用 `tex_fetch / loops / neighbor / rt` 四项，表里逐条给出。
- **Finding（这条改变施工顺序）**：**九个未覆盖预设的 lua 里一个 `fromTo` 都没有**——全部是
  `onUpdate` / `seek()` / `checkDirty()` 那套**状态机 + 显式数学**（签名计数逐条列在表里）。
  已经覆盖的那三个恰好是**本时间线里仅有的 fromTo 族**。所以：
  1. 「再放宽一点读取器就能多拿几段」这条路**实测为空**（T1=0），别再往这个方向排产；
  2. **但「剩下 45% 要执行包内 shader」这句也不成立**（第一版本条就是这么写的，被自己下一个预设的
     frag 实测否掉）：T2a 那 15 段的 frag 是**单采样 mask**，两通道都能不跑 GLSL 实现。
     T2a 真正阻塞的是 **lua 的语义**——打字光标 的 lua 里是 `onUpdate` + `checkDirty`×2 + `seek`
     的**逐字状态机**（还带一张光标 png），向上露出 的 lua 只有 `seek` 一个入口但配一条
     闭式贝塞尔（`controls {0,0,.5,1}`，可移植）。⇒ **施工顺序应是：先做 T2a 的两个 lua 语义移植
     （mask 在两侧各自实现），再评估 T2b/T3 是否值得为 8 段接 offscreen GL**；
  3. T3 那 8 段（24%）不是曲线也不是单 shader，是**多 pass 渲染目标链**（`.rt` 最多 8 个）或 AE 导出工程，
     成本量级完全不同，应该**明确排在 T2 之后**并单独估工。
- **代价与风险（先说在前面）**：走 shader 执行路线意味着预览要真的跑包内 GLSL。
  通道 2（PIL/ffmpeg）**跑不了 GLSL**，所以 T2 的效果要么在浏览器侧执行（预览对、离线通道仍近似），
  要么给通道 2 接一条 offscreen GL 路径。**两条通道会因此再次分叉**——这正是 L10 刚花三轮才对齐的那类问题。
  排产前需要先定这条（否则「覆盖了多少段」会掩盖「两条通道画的不是同一个东西」）。
- **Path**：`scripts/animation_tiers.py`、`docs/evidence/tables/animation_tiers.csv`。复现：
  `python scripts/animation_tiers.py`。
- **证据等级**：已验证（实物清单来自包目录实测，段数与 L1 `stats.animation_segments=33` 同口径；
  「lua 无 fromTo」是对每个包内 lua 全文扫描的结论，不是抽样）。

## F-086 「向上露出」的律被逐文件钉死：贴图滚动 + 固定裁剪，**不需要执行 GLSL**；顺带暴露分层仪器只看 frag 会看错地方（2026-10-24）

- **对象**：预设 向上露出（包 `Cache/effect/7163514358935327268/3786ff3f…`，1 段，kind=in，500 ms）。
  这是 F-085 分层里第一个被打开的 T2a 预设。
- **包内实物**：`TextAnim.lua` 4293 B、`rt.vert`、`rt.frag`、`rt.material`、`rt.xshader`、
  `anim.prefab`、两个 json。**没有** `.rt` 渲染目标文件、没有额外贴图。
- **每帧写什么（`TextAnim:seek(time)` 实测全文）**：
  - `height_cut = rectH / texH1` —— 文字 rect 高 ÷ 扩展后 rect 高，**静态几何量**（不是动画量）；
  - `eraseUV = Amaz.Vector2f(0, 1) * (1. - funcEaseBezier(time / self.duration, 0, 1, 1))`
    —— 唯一的动画量，**从 (0,1) 走到 (0,0)**；
  - `funcEaseBezier` 是**闭式三次贝塞尔**：`controls {0,0,0.5,1}`，用 `getBezierTfromX`
    二分反解（`until te-ts < 0.0001`）把 x 映到 t，再取 `value[2]` 插值。**这套数学可以照搬，不需要 lua 运行时。**
- **效果在哪一阶段（这条是本发现的关键）**：
  - `rt.vert`：`uv0.y = (1.0 - uv0.y) + eraseUV.y;  uv0.x = uv0.x + eraseUV.x`
    ⇒ **动画发生在顶点阶段**：贴图坐标整体下移（含一次 y 翻转）；
  - `rt.frag`：`texture2D(_MainTex, uv0) * step(uv0.y, 1.) * step(uv.y, 1. - (1.-height_cut)*0.5*0.8)`
    ⇒ 裁剪用的是**没被滚动过的 `uv`**，所以窗口固定、内容在里面滑出去。
  - 合起来就是**「文字在一个不动的窗口里向上滑出」** = 遮罩 + 平移。
- **对两通道的结论**：**不需要执行包内 GLSL**。通道 2 等价实现 = 把文字画进扩展框、按
  `eraseUV.y·texH` 做 y 偏移采样、再用 `height_cut` 定出的行阈裁掉；浏览器等价实现 =
  `Container` + 固定 `mask`（Graphics 矩形）+ 文字 y 偏移。`renderToRT` 那个开关只是引擎为了
  「先画进 RT 再滚 UV」的实现细节，**效果层面不需要 RT**。
- **仪器教训（已回写 `animation_tiers.py`）**：F-085 的分层用 frag 的采样次数/循环判「要不要跑 GLSL」，
  对本例**结论碰巧对、理由是错的**——它的 frag 是固定裁剪，**动画量在 `.vert` 里**。
  已加 `vert_scroll` 判据（uniform 是否出现在顶点着色器的 uv 赋值里）并写进 CSV。
  实测：向上露出 / 侧滑 / 向上闪入 = 1，其余 = 0；同时 向右模糊 II 的 frag 内 **57 次采样**
  坐实它是最重的一档（F-085 记的是 21 个 frag + 8 个 `.rt`，这里补上单 pass 的卷积宽度）。
- **Path**：包内 `TextAnim.lua` / `rt.vert` / `rt.frag`（只读）；`scripts/animation_tiers.py`、
  `docs/evidence/tables/animation_tiers.csv`。复现：
  `python scripts/animation_tiers.py`，或直接读那三个文件。
- **证据等级**：律本身**已验证**（三个文件的原文逐行读到，无推测）；
  「两通道等价实现」目前**只是设计**，实现后必须按 L8/L9/L10 复测（尤其「覆盖段数」与「跨通道一致」要一起报）。

## F-087 「打字光标」的律被读完并双通道实现；但**它的保真度还没有判据能测**（2026-10-24）

- **律（读包内 lua 原文得到，非推测）**：`Cache/effect/7237411357514011192/12196518b89652860631d196d19b6f45/TextAnim.lua`
  - 两张**写死的**节奏表（不是随机数，也**没有种子**）：
    `random_tween_time  = {.86,1.35,.62,5.2,.25,.96,.35,4.55,.03,.82,.2,1.26,.36,.1}`
    `random_tween_time1 = {同上，只有第 4、8 项改成 2.2 / 2.55}`
  - `refreshrandomTime`：第 i 字取 `table[(i-1) % 14]`，整条按 Σ=1 归一化；
    选表条件 `duration/oriCount >= 0.15` ⇒ 用 `_time1`；
  - `checkDirty(time)` 把每个字 alpha 设成 `getCharPt(i, 1.2·time/duration)`，
    而 `getCharPt` 返回 `tt > 0.9 ? 1.0 : 0.0` ⇒ **第 i 字可见 ⇔ `1.2·t/dur ≥ Σ_{j<i} w_j + 0.9·w_i`**；
  - 该式对 i **单调** ⇒ 可见集合永远是一个**前缀** ⇒ 「只画前 k 个字」与逐字设 alpha 等价；
  - **`onUpdate` 和 `getcuralpha` 在包里都是空函数**，`curalpha` 是**光标 sprite**（`kiss.png`
    + 自带 `gles2_yvsong.frag`/`gles2_bvcwvg.vert`）的透明度，不是文字的 ⇒
    F-085 把这块欠口说成「shader/状态机阻塞」是**说过头了**：文字部分不需要跑 GLSL，
    光标叠加层才需要（本次未实现，见下）。
- **实现（两通道同时落地，避免重演 L10 分叉）**：
  `animation_curve.load_typewriter()` + `typewriter_prefix()`（读表 + 前缀数）；
  通道 2 `render_frame.typewriter_truncate()` 挂在 `APPLY_ANIMATIONS` 上；
  浏览器 `player.html` 的 `typewriterCount/applyTypewriter` 在 `applyAnim` **开头**调用
  （必须开头：这条预设没有 fromTo，`animValue` 返回 null 会提前 return）；
  表由 L1 随模型带（`animations[].tw`，14 段全带上），载体经 `merge_model_carrier.py` 刷新
  （计数断言 33/33，`.bak` 已留）——页面不再自己抄一份表。
- **保真度判据这件事本身是个发现**：现有两台仪器**都测不了 reveal 类动画**。
  ① `animation_region_check` 的横向基线是**稳态（关动画、全文）**渲染定出来的列范围，
  于是「合法地还没画出来的字」被记成「缺墨」⇒ 把它扩到 88 条比较后得到
  **更近 42 / 更远 35 / 无差 11**（原来 32 条是 21/0/11），那 35 条「更远」几乎都来自打字段，
  **这是几何基线的错，不是律的错**；
  ② 直接量成片字幕行的墨迹列范围也不干净：这条段 t0=6.60 与 `向上闪入` 的**白闪帧**重叠
  （成片 6.645 整行 (0,215) 是闪白不是字），而 `APPLY_ANIMATIONS` 是**全局开关**，
  开/关两臂同时动了别的段 ⇒ 差值不只属于打字。
  ⇒ 要判这条律，需要**逐段开关** + **以成片自己该时刻的墨迹范围**为基线（不是稳态全文）。已记 U-95。
- **未做**：光标叠加层（`kiss.png` + 它自己的 frag、−250°/s 旋转）与 `FirstCharOfRow` 行边界启发式；
  所以即使律对了，画面右侧那根光标仍然缺。门在本次改动后重跑（`--shot-times 6.85,7.2,1.0`）
  看有没有回归，读数记在 P-48。
- **证据等级**：律**已验证**（原文逐行）；实现**已验证机制**（前缀单调、14 段都带表、通道 2 逐帧
  0→2→3→4 字实测）；**保真度未定**（两台仪器都不适用，已立 U-95）。

## F-088 打字光标的**时间轴取错了**：律要的是动画自己的 0.20 s，我一开始用了片段时长（0.47–0.93 s）（2026-10-24，F-087 的更正 + 新仪器）

- **怎么暴露的**：F-087 里我把 `animation_region_check` 扩到打字段后得到「更近 42 / 更远 35」，
  当时我判成「仪器基线的错」。用 `animation_region_check` 的**同刻开/关**对照把时长轴修好后，
  同一台仪器变成 **44 近 / 19 远**（打字段 56 条：23 近 / 19 远，中位 MAD 开 24.23 vs 关 24.69）
  ⇒ **仪器没错，是我把轴取错了**。这条按「先查自己代码再怪仪器」的顺序记（同 U-93 那轮的反面教材）。
- **错在哪**：`lua` 里 `seek(time)` 的 `time` 与 `self.duration` 都是**动画自己的**量
  （模型里 `animations[].duration_us = 200000`，14 段**全是 0.20 s**），
  而我拿 `segments[].target.duration_us`（0.47–0.93 s）去除 ⇒ 揭示被拉慢 **2–5 倍**；
  连带 `dur/n >= 0.15` 的**选表**也错（按动画时长 0.20/2..4 字 = 0.05–0.1，**恒选 `random_tween_time`**，
  而我按片段时长时部分段选了 `_time1`）。两通道已同时改为
  `t_local = pos − target.start − animation.start`、`dur = animation.duration_us`。
- **新仪器 `scripts/typing_extent_check.py`**：把判定换成律自己的单位——**成片这一刻露出了几个字**。
  标定不用猜：用我们自己的**纯文字层**（空白底、不解任何视频帧）画 k=0..n 个前缀，
  得到每个 k 的墨迹右边缘列 `R_k`（例：4 字段 `R_k=[-1,116,125,134,144]`，@216 宽）；
  再量成片同刻同列的右边缘 E，取 `argmin_k |R_k − E|` 作 `k_export`，与 `k_ours` 对表。
- **两个当场踩到的坑（都写进了代码注释）**：
  ① 纯白判据 `min(R,G,B) > 190` 在 216 宽参考帧上**全军覆没**——5× 降采样把细笔画和背景平均掉，
     14 段一律「文字层无白墨」。改成**两腿同尺度 + 同一个 luma>128**；
  ② 脏样本判据我写成「E 必须落在全文右边缘附近」，等于**用结论当筛子**；
     改成「E 落在我们自己前缀边缘张成的区间外」后仍然 59/70 判脏，
     真因是 E 在**整行**上取右边缘 ⇒ 字幕右侧任何亮素材（展会展牌）都把样本废掉。
     **这条还没修**（下一步：把 E 的搜索限制在该段自己的列窗内，脏判据改用「背景-only 渲染同窗比对」）。
- **目前能说的**：在**行窗干净**的 11 个样本上 **6 对 / 5 错**，错的时候
  `k_ours − k_export` 中位 **−1**（范围 −2..−1）⇒ **我们比成片慢约一个字**。
  方向与时长轴修复一致（还差一点，可能是引擎给 `seek` 的 time 含起始偏移或首字即时可见）。
  样本太少，**这不构成结论**，只构成下一条实验的假设；已记 U-95。
- **证据等级**：时长轴 bug **已验证并修复**（同一仪器 35 远 → 19 远）；
  「慢一个字」**已观察未验证**（n=11，仪器脏判据待修）。

## F-089 「打字光标慢一个字」是**仪器假信号**：位置判据把别的层当成了字幕（f<0 对照当场否证，2026-10-24）

- **仪器**：`scripts/typing_extent_check.py` 修到可用（两处缺陷见 F-088：纯白阈在 216 宽下全空、
  右边缘在整行找被素材淹）。现在的口径是**背景相减**：同刻把该段文字清空的渲染当背景，
  `成片 − 背景 > 60 luma` 才算「这里有字」，右边缘只在**该段自己前缀边缘张成的列窗**里找，
  `k_export = argmin_k |R_k − E|`。
- **读数（14 段 × 5 时刻 = 70 样本，全部有效）**：**一致 27 / 不一致 43**，
  `k_ours − k_export` 中位 **−1**，范围 **−3..+1** ⇒ **我们系统性比成片慢约一个字**。
- **两个竞争解释，一个已被否证**：
  ① 「同一行有别的字幕段，窗内的墨是它的」——**否证**：逐样本查模型里该时刻活着的其它文本段，
     **70 个样本里 0 个**有同行竞争（本时间线 3 条字幕轨虽然同 `clip.y = −0.4427`，但这些窗口互不重叠）。
  ② 「成片根本不打字」——**也否证**：确实存在部分露出的样本
     （t0=6.60 f=0.50 成片 3/4 字、14.03 f=0.10 成片 1 字、16.50 f=0.30 成片 1 字、21.97 f=0.10~0.50 成片 1 字）
     ⇒ 成片**是**逐字出的，只是**比 0.20 s 快得多**：多数段在 `f=0.10`（动画开始后 0.02 s ≈ 第 0.6 帧）
     就已经画满。
- **所以问题定位到时钟，不是曲线形状**：我们的 `τ = 1.2·(pos − target.start − anim.start)/anim.duration`
  把揭示铺满整个 0.20 s；成片却像在**片段开始之前**就把它跑完了。
  **判别实验（下一步，很便宜）**：在 `f < 0`（即片段开始前的 0.05–0.2 s）取样，
  量同一列窗的 `k_export`。
    - 若成片在 f<0 就显示部分字 ⇒ 打字动画的时钟**不以 target.start 为零点**
      （候选：以素材/材质的创建时刻、或以 `source.start` 为零点），改轴即可；
    - 若 f<0 时成片也没有该段 ⇒ 动画确实从 0 开始，那就是**时长轴**还要再缩
      （候选：引擎把 `duration` 当毫秒级 `200` 而非微秒，或 `seek` 收到的 time 已被 ×1.2 归一）。
  两种结果都只改一条参数，且改完必须同时落到两条通道（F-087 的教训）。
- **别把这条读成「打字光标做错了」**：跨通道一致性（P-49：打字窗口内 0.994）说明两条通道现在
  算的是同一条律；差的这一字是**与原生时钟的对齐**，属于保真度残差，不是渲染分叉。
- **证据等级**：仪器与 70 样本读数**已验证**；解释②的两种候选**未判**（判别实验已设计，未跑）。

### 但本条的结论**已被自己下一步的对照实验否证**（同轮 21:35 补记，别按上面那句读）

- 跑「f<0 对照」时先撞到一个**决定性反例**：t0=6.60 那段（会场上好，全文右边缘 `R_k[n]=144`），
  在 **f=−1.0（t=6.40，这段还不存在）**、f=−0.5、f=−0.25 上，成片减背景的「超出墨」右边缘是
  **E=168 / 168 / 169**，f=0.0 与 0.1 更是 **215**（= 画幅最右）；t0=16.50 那段（迅镭，`R_k[n]=125`）
  在 f=−1.0/−0.5 上是 **E=196 / 205**。⇒ **这些「超出背景的亮墨根本不是这段字幕**（该时刻这段还没上场），
  而是我们的背景渲染没能复现的那一层（别的字幕轨、`向上闪入` 那族叠加层、或素材解码差异）。
  于是 `k_export = argmin_k|R_k − E|` 在**这些段上恒等于 n**，把「一致 27 / 不一致 43」和
  「我们慢一个字」全部变成了**仪器的假信号**。
- **所以本条上面那两节（① 否证同行竞争、② 时钟错）都不成立**：①的「70 样本 0 竞争」只查了
  *别的文本段是否活着*，没查*别的层是否在该窗里留亮墨*——而 f<0 对照恰好证明后者普遍存在。
- **仪器要怎么改（已定，未做）**：
  ① 判据从「右边缘落在哪个前缀上」换成**图案匹配**：把该段前 k 个字的**纯文字层**当模板，
     取 `argmin_k MAD(成片超出墨, 文字层_k)` —— 位置判据对污染没有选择性，图案判据有；
  ② **f<0 对照升为常驻有效性检查**：每个段先测一次「该段不在场时窗内还有没有超出墨」，
     有 ⇒ 该段的 `k_export` 全部作废并计入 `unusable`，不再进总账（这次就是它救了我一条错结论）；
  ③ 若 ①② 之后可用样本太少（本时间线字幕与各种叠加层同 y 是常态），那就承认
     **这条律在成片侧没有可用的逐字判据**，退回 F-088 那条**同刻开/关 MAD** 对照
     （它不识别字，但两臂只差这一条动画，仍是目前最不失真的证据：23 近 / 19 远）。
- **教训（与本条标题同级重要）**：我这次是**用「argmin 距离」把位置判据包装成了识别**。
  一个只在「目标在场时才有信号」的判据，必须先有一个「目标不在场时应当无信号」的对照；
  没有这个对照，再干净的读数也可能是 168 那个数字。**已把这条写进 U-95。**
- **证据等级**：本条**上半部分作废**（读数有效但结论无效）；f<0 反例**已验证**；改法**未做**。

## F-090 素材层残差**在 solo 模型上复现了**：浏览器比两条离线腿亮 +1.09 码值，几何最多解释 28%（2026-10-24，U-93①）

- **仪器修好才谈得上读数**（`scripts/colour_range_probe.py` 三处）：
  ① 中心框原来写死 **256 像素** ⇒ 256/1080=24% 而 256/540=47%，浏览器腿与 ffmpeg 腿
     **量的不是同一块画面**（上一轮那个假"+21 码值"就是这么来的）；改成**按比例 23.7% 取框**。
  ② 过期截图防护：页面写的名字是它自己格式化的（`t=7.0 → browser-shot-7.png`），
     按字符串拼出来 unlink 的 `browser-shot-7-0.png` **删不掉真正会被读的文件** ⇒
     上一轮门留下的旧图会被当成本次 solo 结果。改成只认 **mtime 晚于本次启动**且时刻对得上的那张。
  ③ GBK `reconfigure` 补上（这台机器已有 4 个工具在算完之后 print 崩掉）。
  另外报告里现在带 `sizes` / `aspect_ratios` / `geometry_mismatch`——**不核验几何就报色彩差，
  是本项目重复犯过两次的错**（F-083 的猜带、P-39 的居中盒）。
- **读数（track1 素材、`t=7.0`、solo 模型，中心框 23.7%）**：
  - ffmpeg 解该源时刻 **92.14**；±1 帧 **91.96 / 92.58** ⇒ 素材本身的帧间起伏约 ±0.4 码值；
  - 通道 2 **92.14** ⇒ `d_channel2_minus_ffmpeg = 0.00`（同源同解码器，这是**一致性自检**，不是新信息）；
  - 浏览器 **93.23** ⇒ **`d_browser_minus_ffmpeg = +1.09`**，`d_browser_minus_channel2 = +1.09`。
- **几何能解释多少**：把同一个框在 ±3% 大小上扫，均值变化 −0.66/+0.19；
  本次实际失配是浏览器帧 540×953（内容包围盒）对 1080×1920，**0.7% 的宽高比差 ⇒ ≤0.3 码值**。
  ⇒ **几何最多解释 +1.09 的 28%**，剩下约 **0.8–1.1 码值**是**解码之后**引入的。
- **判到哪一层**：两条离线腿（ffmpeg 与通道 2）逐码值相同、浏览器独自偏亮 ⇒ 差**不在**剪映/素材侧，
  在浏览器管线里。还剩两个候选没分开：
  **① WebCodecs 自己的 YUV→RGB**（它和 ffmpeg 是两个不同的转换器，limited/full range、601/709 矩阵
  任一条不一致都会给出一个近似常量的偏置）；**② Pixi 上屏的色彩空间**（`colorSpace:'srgb'` 与
  渲染器输出之间多一次转换）。
  **分离实验（未跑，下一步）**：在同一个页面里画一张**已知 RGB 值**的纯色纹理，
  用 `extract.pixels` 读回来——不经过任何解码器，所以读到的值若偏，就是②；不偏，①成立。
- **与 F-083/U-93 的关系**：F-083 说"浏览器系统性偏亮 1.8 码值"，P-41 又指出那条是跨条件比较、
  且"符号随时刻变号"。本条是**修好仪器后的第一次干净复现**：在这条素材、这个时刻，
  偏亮 **成立且可测（+1.09，几何上界 0.3）**。所以 U-93① 从"未判"推进到
  **"已复现，范围收窄到浏览器管线内，两候选待分离"**。
- **证据等级**：复现与几何上界**已验证**；①/②归属**未判**（分离实验已设计好，一条命令的量级）。

## F-091 Pixi 上屏通道**逐码值中性**（12 级已知灰回读 Δ 全 0）⇒ 浏览器 +1.09 归解码/纹理入口，不归渲染（2026-10-24，U-93① 收窄）

- **实验**：`temp/playback-test/pixi-colour-readback.html` 造 12 个**已知 RGBA 的 1×1 纹理**
  （0/16/32/64/96/128/160/192/224/235/250/255）铺满画面，用与 `player.html` **同一套**
  pixi 构建、同一个 `app.init({width,height,background:'#000',antialias:false})`、
  同一个回读 API（`renderer.extract.pixels(stage)`），POST 回网关。
  **不经过任何解码器** —— 这正是它能把两个候选分开的原因。
- **读数**（`report-colourreadback.jsonl`，renderer=webgl/type 1，回读 540×960 RGBA）：
  **12 个级别 `delta` 全为 0**（输入 16 → 读回 16，输入 255 → 读回 255，`delta_min=delta_max=0`）。
- **结论**：**候选②（Pixi 色彩空间/上屏转换）被否证**。F-090 那 +1.09 码值不是 Pixi 画出来或读回来时
  改变的。⇒ 偏置只能在**「解码后的视频帧变成纹理」这一步之前或之中**引入：
  `createImageBitmap(videoFrame, {resizeWidth, resizeHeight})` 对 VideoFrame 色彩空间元数据的解释、
  或 WebCodecs 自己的 YUV→RGB（limited/full range、601/709 矩阵任一条与 ffmpeg 不同，
  都会给出一个**近似常量**的偏置 —— 与实测「跨时刻 +1.1~+1.8、符号稳定为正」一致）。
- **这条实验的边界（别说过头）**：它证明的是「**纹理来源的像素**在 Pixi 里不被改变」，
  没有证明「VideoFrame 转成纹理时不被改变」——后者恰好是剩下的嫌疑，属于**解码侧**而非渲染侧。
  再往下要分，就得拿**同一条代理片**分别用 WebCodecs 与 ffmpeg 解出**同一帧的原始 RGB** 直接比
  （不需要 Pixi），那是下一条实验。
- **对本草稿的实际影响**：+1.09 码值（几何上界 0.3）在 L10 的判据下不构成红
  （对成片 0.947–0.975 全过），属于**已定位、未修**的小残差；修的话方向是
  在 `createImageBitmap`/VideoFrame 侧显式给色彩空间，而不是去动 Pixi 的 `colorSpace`。
- **Path**：`temp/playback-test/pixi-colour-readback.html`、`temp/playback-test/report-colourreadback.jsonl`。
  复现：起网关后
  `python scripts/browser_soak.py --url "http://127.0.0.1:<port>/playback-test/pixi-colour-readback.html?tag=colourreadback" --seconds 25 --tag colourrb`。
- **证据等级**：已验证（12 级已知输入、Δ 全 0、与渲染器同源同参）。

## F-092 残差定案在**解码侧**：同一条代理帧不经 Pixi 回读就比 ffmpeg 亮 +0.86 码值（U-93① 结案为"已定位、不修"，2026-10-24）

- **实验**：`temp/playback-test/webcodecs-rgb-readback.html` 用与 `player.html` **完全相同**的取帧链
  （`Input`+`CustomSource`(Range) → `getPrimaryVideoTrack()` → `VideoSampleSink.getSample(t)` →
  `toVideoFrame()` → `createImageBitmap(vf,{resizeWidth:codedWidth,...})`），但**不画进 WebGL**：
  `drawImage` 到 2D canvas 后 `getImageData`，中心框比例与探针一致（23.7%）。
- **读数**（`report-wcrgb.jsonl`，代理 `C7573.420a.mp4`，源时刻 43.8667 s）：
  - 帧自带元数据：`format=NV12`、`colorSpace = {primaries bt709, matrix bt709, transfer bt709,
    **fullRange: false**}`、`coded 1088×1920` vs `display 1080×1920`（8 px 编码边距）；
  - **带 resize 回读 luma 93.00**，**不带 resize 93.01**（差 0.01 ⇒ `resizeWidth/Height` 不引入偏置）；
  - 同一源时刻 ffmpeg 中心框 **92.14** ⇒ **Δ = +0.86 码值**。
- **三段拼起来的因果链**（这才是本条的价值）：
  F-091：已知 RGBA 纹理过 Pixi 上屏回读 **Δ=0**（渲染中性）；
  F-092：真实视频帧**在进 Pixi 之前**就已经 **+0.86**；
  F-090：整条浏览器管线相对两条离线腿 **+1.09**（几何上界 ≤0.3）。
  ⇒ **+1.09 基本全部来自解码→RGB 那一步**，剩下的 0.2 与取帧偏差同量级
  （浏览器给到的帧时间戳 43.860483 s，比 ffmpeg 的 `-ss 43.8667` 早 6 ms，
  而素材本身的帧间起伏是 ±0.4 码值）。**Pixi/上屏被排除。**
- **为什么不修**：+0.86 码值 = 满量程的 **0.34%**，在 L10 判据下不构成红
  （对成片 0.945–0.976 全过），也不是任何一层律写错——它是**浏览器 NV12→RGB 与 ffmpeg
  在 limited-range/取整上的实现差**。要"修"只能在 VideoFrame→bitmap 处自己实现转换
  （代价：每帧一次全幅 CPU/GPU 转换 + 与 ffmpeg 谁对谁错的新一轮判据），
  换来的收益是 0.3% 的码值。**建议按"已定位、量级已知、不修"结案**，
  并把它写进 `spec/` 的已知上限（与 U-93② 的缺面上限同族：都是环境实现差，不是我们的律错）。
- **顺带修掉的仪器缺陷（值得记，因为这次差点又白测）**：页面第一版在 POST **之前**抛错
  （`getPrimaryVideoTracks()[0]` 不是 mediabunny 的真实 API，正确是 `await getPrimaryVideoTrack()`），
  网关侧只留下 3 秒 RSS 样本——读数看起来像"没数据"而不是"实验失败"。现在整段包在
  `try/catch` 里并把 `error` POST 回去。**失败必须留痕**，与 P-44（时长静默回退）同族。
- **Path**：`temp/playback-test/webcodecs-rgb-readback.html`、`report-wcrgb.jsonl`、
  `colour-probe-7.json`（ffmpeg 基线）、`report-colourreadback.jsonl`（F-091）。
- **证据等级**：已验证（同一帧、同一框比例、两条独立解码路径直接对数；
  且 F-091/F-092 两台仪器互不共享代码路径）。

## F-093 Pixi 8 的 WebGL 通道**按 GLSL ES 1.00 编译滤镜**，出厂件可逐字接入；但自定义 sampler 名一律不绑、`uniforms` 选项不存在、`useBackBuffer` 默认关（U-92 仪器四条事实，2026-10-25）

- **背景**：F-079 已证「出厂件(GLSL1) ≡ 包内原文」，`player.html` 侧要接混合模式，就得知道
  Pixi 8 这条管线会不会在搬运过程中改变数学。U-92 上一轮给出 maxΔ=255，我判它**仪器坏**
  （跳过了自定的几何自检），本轮把仪器修到能回答问题为止 —— 结果数学等价性仍未判，
  但撞出四条关于 Pixi 8 的**可复用事实**，每条都有源码行号和实测读数。
- **事实①（并撤回我先前的一句断言）**：`_GlProgram` 用 `fragment.indexOf("#version 300 es")`
  判是否 ES300（pixi.mjs:17728），我们的出厂件没有 `#version` ⇒ 走 `addProgramDefines`（17597）
  在 `#ifdef GL_ES` 下补 `#define in varying / texture texture2D / finalColor gl_FragColor`
  ⇒ **Pixi 8 的 WebGL 渲染器把滤镜按 GLSL ES 1.00 编译**。
  实测：GLSL1 写法（`varying`/`texture2D`/`gl_FragColor`）的直通滤镜 17×17 网格回读
  **maxΔ=0**（`g0`，四朝向表 `id:0/0, x:272/255, y:272/255, xy:288/255` ⇒ 朝向是 identity）。
  若 Pixi 真插了 `#version 300 es`，`varying` 就非法、编译必失败 ⇒ 不会是这个读数。
  ⇒ **「接进 Pixi 要把 GLSL3 机械改写、改写就失去不誊写性质」这个前提是错的**；
  实际代价只有两个 sampler **改名**（`_MainTex`→`uTexture`、`baseTex`→`uBackTexture`），
  混合函数体逐字不动（`rename.math_identical = true`，4 行不同，函数体 209/260 字符）。
- **事实②**：`compileShader()`（52239）**不检查 `COMPILE_STATUS`** ⇒ 编译失败不抛错，
  只是那个 program 画不出东西。这就是上一版 maxΔ=255 的真因：我按 Pixi 7 的惯例把输出
  写成 `pc_fragColor`，Pixi 8 全文**没有这个标识符**（`grep pc_fragColor` = 0 处），
  GLSL1 里它是未声明名 ⇒ 静默全黑。**踩坑教训**：这条路径的错误不会自己浮上来，
  必须靠"读回画成字符"这类正向自检（见 P-58/P-59 的 map 仪器）。
- **事实③**：离屏写法 `app.render({container, target: 自建 RenderTexture})` 读回**全 0**
  （连 alpha 都是 0 ⇒ 根本没画），而 `extract.pixels(app.stage)` 与
  `generateTexture({target: stage})` 两条路都是 maxΔ=0。四分叉单变量诊断
  `temp/playback-test/px-readback-which.html`：V1 stage=0，V2 stage+filter=0，
  V3 自建 RT 作 target=**坏**，V4 generateTexture=0。⇒ 读回走 stage。
- **事实④（U-92 的真拦路石）**：**自定义名字的 sampler 根本不会被绑**。
  `generateShaderSyncCode`（52181）按 `shader._uniformBindMap[i][j]` 去
  `programData.uniformData[uniformName]` 取位置，取不到就整段跳过 ⇒ sampler 停在默认 unit
  = 滤镜输入。实测：让 `uSrc` 直通输出，读回的是**前景网格**而不是背景硬边网格
  （`g1`/`g3` 的 map 一致，`id:285/191`）。而 Shader 构造里只有**有 WGSL 程序**时才从程序
  反射 group/binding（18639），纯 GL 路径把 `resources` 全塞进 group 99；FilterSystem 却把
  真背景放进渲染器级 `_globalFilterBindGroup` 的 binding 3（19934）⇒ 两边槽位对不上。
  支持的名字只有 `uTexture`（`addResource(...,0,1)`）和 `uBackTexture`
  （`blendRequired:true` 才注册，18994）。
- **另外两条小的**：① Pixi 8 **没有 `uniforms` 选项**（`options.uniforms` 在 dist 里 0 处引用），
  标量得走 `resources`；写成 `{_alpha: 1.0}` 抛 `Cannot create property 'name' on number '1'`，
  写成 `{_alpha: {value: 1.0}}` 抛 `Cannot read properties of undefined (reading 'match')`
  ⇒ 缺 `type`，正解待下一轮坐实。② `_GlBackBufferSystem.defaultOptions.useBackBuffer = false`
  （50655），`blendRequired` 缺它时只 `console.warn`（19991）就继续跑；本轮把它开成 true 后
  `warns=[]` 且读数不变 ⇒ **开关不是拦路石，事实④才是**。仪器不吃控制台，所以这两条
  都是靠把读数画出来才发现的，不是靠警告提醒的。
- **读数文件**：`temp/playback-test/report-mixpixi2..10.jsonl`（同一仪器的 9 轮迭代），
  诊断页 `px-readback-which.html` / `report-pxreadback.jsonl`。
- **证据等级**：事实①②③**已验证**（源码 + 单变量读数）；事实④的**现象已验证**
  （自定义名不绑、`uTexture` 绑、直通逐字正确），其"group 99 vs `_globalFilterBindGroup`"
  的**机理解释是源码推断**，尚未由修好后的读数反证；`groupMap: {0:{3:'uBackTexture'}}`
  这条路**还没测通**（本轮它先被 uniform 描述符的抛错挡住）。混合数学等价性**仍未判**。

## F-094 U-92 判完：包内混合数学经 **Pixi 自己的 BlendModeFilter 注入点**进浏览器，逐字节等价（maxΔ=0，17×17 全格过，2026-10-25）

- **结论**：不写自定义 `Filter`，而是把出厂件的混合函数**原样注进 Pixi 8 的模板槽**：
  `new BlendModeFilter({ gl: { functions: <出厂件去掉声明行的函数体>, main: 'finalColor = XBlendPreMul(front, back);' } })`
  （`compileBlendModeShader` 32260 行就是 `{FUNCTIONS}`/`{MAIN}` 两个 replace）。
  背景、`blendRequired`、`uTexture`/`uBackTexture` 的绑定**全部由厂商机器自己完成**，
  我不再碰 uniform 管道 —— 于是 F-093④ 那个拦路石被绕开，而不是被我修好。
- **读数**（`report-mixinject.jsonl`，pixi **VERSION 8.22.0**，`g0/g2v` 几何腿均 maxΔ=0 先行通过）：

  | 模式 | 注入字符数 | vs 腿 A（出厂件 GLSL） |
  |---|---|---|
  | multiply_blend_mode | 622 | **orient id，max 0，cells 0** /289 格 |
  | soft_light | 1497 | **orient id，max 0，cells 0** /289 格 |
  | 通道对照腿 C（恒用 multiply 函数体） | — | **exact true**（两次跑都 0/0） |

  参照=腿 A 的裸 WebGL2 出厂件输出，而 F-079 已证该输出 ≡ 包内原文 ⇒ **三方闭合**：
  包内 GLSL == 裸 GL 出厂件 == Pixi 注入件。柔光这一行同时再次印证 F-082：
  注入的是**包内**柔光，不是 CSS 柔光（CSS 那条在下面矩阵里 max=255）。
- **顺带量出来的能力矩阵**（`report-mixmatrix.jsonl`，10 个模式 × Pixi 内建 blend mode，
  判据同样是"与各自模式的腿 A 逐字节比"）：**只有 multiply 一个模式能被内建精确覆盖**
  （`built-in: multiply exact=True 0/0`；G5 腿单跑也是 0/0），其余全不等价：
  bright_en(lighten 255/screen 64)、dark_en(darken 255)、darken_color(darken 255/multiply 255)、
  color_dodge(255)、over_lay(255，与 F-082"包内叠加是 CSS 同名反的"一致)、
  soft_light(255)、glare_pc(plus-lighter 127/screen 255)、linear_deepening(multiply 63)、
  color_filter(无内建候选)。⇒ **走内建 blend mode 只能白拿 1/10**，剩下 9 个必须走注入通道；
  这也说明接入形状必须是"注入函数"，不是"给每个模式挑一个 CSS 名字"。
- **排除法记录**（F-093④ 之后我又排掉四个嫌疑，每个都是单变量）：
  ① 适配顶点着色器 —— `g2v`（经 `uTexture` 走 `uv0.xy/uv0.z`）maxΔ=0，**同时把上一轮那句
  撤回的"uv0 路径已证"补回为已证**（这次用的是唯一保证绑得住的名字）；
  ② 资源给 `Texture` 还是 `TextureSource` —— 两者读数**一字不变**（`g3` 都是 191/285）；
  ③ 显式 `groupMap:{0:{1:'uTexture',3:'uBackTexture'}}` —— 读数不变；
  ④ 采样 uv 用我的 `uv1` 还是 Pixi 的 `vTextureCoord` —— `g3`(适配顶点+uv1) 与
  `g4`(默认顶点+vTextureCoord) **读数完全相同** ⇒ 不是顶点着色器的事，是第二个 sampler
  在纯 GL 自定义滤镜里根本没被注册。F-094 的路线之所以成立，是因为 BlendModeFilter 同时带
  `gpuProgram`+显式 `glProgram`，group/binding 由 WGSL 反射得到（18639 行那个分支）——
  **这一条仍是源码推断**，没做正证（要正证就得给自定义滤镜也配一份 WGSL，成本不划算，
  而且既然官方注入点够用，就没必要赢这个理）。
- **还没判的**（别把 F-094 读成"接入完成"）：① ~~`player.html` 未动，门未复跑~~
  **已落地并复跑（P-61）**：注入件进 `player.html` + 新门层 `L7 mixmode browser wiring`
  （带反 fixture），全门 21/22，唯一红与混合模式无关（L10 的 6.633 是 `向上闪入` 白闪窗，
  通道 2 离线同低）；
  ② ~~`_alpha`~~ **已判（P-62）**：浏览器 `node.alpha=0.5` 与通道 2 `blend(..., fg_alpha=0.5)`
  逐格比 **maxΔ=1、0 格超差**（对立假设「alpha 没进滤镜输入」是 128/287 格不符）
  ⇒ Pixi 把 alpha 预乘进滤镜输入，注入件缺的 `_alpha` 就是厂商那条 `fg *= min(_alpha,1)`；
  ③ U-90（`blendAlphaState` 到底走 PreMul 还是 Straight 支）仍未定，这里注入的是 **PreMul** 支，与 F-079 的包装决定一致；
  ④ 本草稿 `mix_mode` 段数 0 ⇒ 接上之后仍要靠构造 fixture 进门（L7 已有这个形状）。
- **读数文件**：`report-mixinject.jsonl`（等价性 + 通道对照）、`report-mixmatrix.jsonl`（矩阵）、
  `report-mixpixi11..13.jsonl`（排除法各轮）。仪器：`temp/playback-test/mixmode-pixi.html`。
- **证据等级**：等价性**已验证**（两模式 + 通道对照 + 几何腿先行，三方闭合到包内原文）；
  矩阵数字**已验证**（10 模式，同判据）；1/10 与 maxΔ=0 都是**网格级**结论，不是真实画面级。

## F-095 「向上闪入」的时间律是**明文可读的**，而 #14 的两条前提被成片否掉（2026-10-25）

起因：检查 #14 的下一步计划时先读包，而不是直接动手。包
`Cache/effect/7273389803532456504/ecaffca7c7e1d7744fa296a29f65b366`（`package_md5` 即此，
1 段，`duration=300000 µs`）。

1. **律在 lua 里，不在引擎里**。`AmazingFeature/lua/SeekModeScript.lua` 带一张
   `ae_attribute = {["ADBE_..."] = { {bezier4, {f0,f1}, {{v0,},{v1,}}}, ... }, ...}` 的**明文关键帧表**，
   `seek()` 只做三件事：`t = mod(time, duration+1e-4)/(duration+1e-4)`、
   `AEprogress = t*21/49`、`GetVal(name, AEprogress)`（`all_frame` = 表内最大 `f1` = 49）。
   ⇒ 「T3 = 要脚本运行时、读不到」对**这一族**是错的：U-91 那句「9/12 预设不可求值」里，
   只要包里有这张表，曲线就能像 `fromTo` 一样被解出来。
   新仪器 `scripts/ae_keyframe.py`：机械解析表（不誊写：`21/49`、`mod` 的 `1e-4`、`noiseIns` 增益
   都是正则从源码取出并断言存在），并按 lua 原文逐条对齐 `_remap01`/`_cubicBezier`/
   `_getBezier01X`（二分阈值 1e-4 照抄）/`_mix`/`GetVal`。**覆盖率自证**：属性 6/6，
   每条关键帧 3~4 段，帧区间**首尾相接 = True**（表内 `all_frame=49`，但 `AEprogress` 只走到
   `t*21` ⇒ **AE 帧 21..49 永不到达**，那几段是这段动画用不到的尾巴）。
   机器上**没有 lua 解释器**（`lua`/`lua5.x`/`luajit` 无，`lupa` 未装）⇒ 移植未经执行验证，
   所以下面第 3 条的外部校验是**必需**的，不是加分项。
2. **同族不止这一个包，但"已打通"要说清分母**（`scripts/ae_table_harvest.py`，读数
   `temp/playback-test/ae-tables.json`，每条失败都带原因）：
   `Cache/effect` 下 `SeekModeScript.lua` 共 **69** 个（任意深度），落在规范布局
   `*/*/AmazingFeature/lua/` 的 **34** 个；这 34 个里含 `ae_attribute` 的 **7** 个（无表的 27 个），
   而本工具**已能完整解出 2 个**（本包的 `ecaffca7c7e1…`，6 属性 / `all_frame=49` / `t映射=21/49`，
   以及 `b8b953ad94b1…`，6 属性 / `all_frame=12` / `t映射=12/12`），
   **5 个解析失败**：3 个的 `AEprogress` 不是 `t * A / B` 形态、2 个的 `ae_attribute`
   声明形态不是 `local ae_attribute = {…}`。⇒ 这条族**打开了一半**，
   说"7 个都能解"是错的；两个包的 `t映射` 分母也不同（49 vs 12），
   所以 `AEprogress` 的映射**必须逐包取**，不能当常量。
   修解析器时踩到一条通用坑：注释里的 `--` 会被当数字
   （`could not convert string to float: '--'`），加 `strip_lua_comments()` 后才把
   "表存在但读不出"与"真读不出"分开；**改完做了回归**：本包 t=0/0.033/0.1 的 E 仍是
   1.8300/1.7395/1.4142，与 F-095 的表逐位相同。
   `animation_tiers.py` 的 `AE_MARKS = (".lsanim", ".lsproj", ".jsdat")` 只认**文件扩展名**形态，
   所以本包 `ae_export=0`——那是**标记集的覆盖缺口**，不是"没有 AE 导出"。
3. **成片逐帧亮度把两条前提否掉了**（`temp/scratch_export_luma.py`，270×480 灰度，
   基线取 f≥222 的均值 **105.48**；段起点 6.600 = 固定 lead +3 后的**帧 201**）：

   | 帧 | 成片均值 | 预测 `base·2^(E/2.2)` | 残差 | 垂直梯度 |
   |---|---|---|---|---|
   | 200 | 113.24 | — | — | 8.98 |
   | 201 | **242.11** | 187.8 (E=1.830) | **−54.3** | **0.40** |
   | 202 | 183.34 | 182.6 (1.739) | +0.7 | 1.19 |
   | 203 | 164.63 | 174.6 (1.599) | −10.0 | 2.04 |
   | 204 | 151.11 | 164.6 (1.414) | −13.5 | 2.64 |
   | 205 | 139.05 | 153.1 (1.180) | −14.1 | 3.79 |
   | 206 | 128.74 | 139.8 (0.893) | −11.1 | 6.01 |
   | 207 | 119.25 | 126.9 (0.590) | −7.6 | 7.62 |
   | 208 | 112.07 | 116.0 (0.301) | −3.9 | 7.71 |
   | 209 | 106.68 | 108.2 (0.080) | −1.5 | 7.57 |
   | 210 | 104.35 | 105.5 (0.000) | −1.1 | 7.48 |
   | 211–227 | 104.2~104.7 | 105.5 | ≈0 | 7.2~7.3 |

   - **否掉「duration 用包内 `animation_duration: 0.7`」**：E 在 0.3 s 处归零、210 帧后成片就平在
     104，与 `duration=0.3`（= 草稿 ref 的 300000 µs）一致；取 0.7 时 t=0.33 处 E 仍是 1.10，
     不可能已经平。
   - **否掉「按 lua 字面 `mod` 循环」**：`mod` 让 t=0.333 折回 0.033 ⇒ 帧 211 应再闪一次
     （预测 E=1.74），实测 211..227 **全平**（104.5/104.3/…）。⇒ 引擎给 `seek` 的 time 在
     入场动画结束后**不再驱动**（或夹紧），我们的实现要**夹**、不能循环。
   - **否掉「只做亮度项、模糊可后置」**：帧 201 的垂直梯度 **0.40 vs 常帧 7.2~8.9**，
     即那一帧被抹成近乎均匀——`ADBE_Gaussian_Blur_2_0001_2_3` 在 AE 帧 0..15 内 300→0
     （= 窗口前 71%），亮度只解释「有多亮」，不解释「没有结构」。
     同窗还有 `ADBE_Position_2_4` y 1050→540（AE 帧 0..8，即前 0.114 s 的**向上滑入**）、
     `Displacement_Map` 75→0、`Scale` 103→100。
4. **但形状是被证实的**：单看曝光一项、`duration=0.3`、**不循环**，137 码值的摆幅里
   202..210 的残差最大 **14 码值**（≈摆幅的 10%），衰减常数对得上。
   ⇒ 「曝光律已被成片验证」，而峰值帧 201 少 54 码值 —— 与第 3 条「峰值还要加模糊/位移」自洽
   （预测是纯乘性 gamma 近似，不含加性项）。
   证据等级：曲线解析**已验证**（6/6 属性 + 首尾相接 + 常数取自源码）；
   曝光形状**已验证**（对成片，逐帧 10 点）；`GetVal` 移植**未经执行验证**（无 lua 解释器），
   目前由形状吻合间接撑着；模糊/位移/噪声三项**未实现、未标定**（`u_Strength` 与像素半径的
   换算关系还没读 `GaussianBlur.frag`）。
5. **对排产的影响**：#14 的成本不是「一个亮度项」，是「一个段的 5 条律 + 3 次 RT pass」。
   而这条族（本机 7 个包）的**曲线**部分今天已经打通——所以「先解表、再逐条判定哪条律承重」
   应当排在「为 1 段实现整条 RT 链」之前。L10 的 6.633 仍按 U-91 记为未实现，不动阈值。

## F-096 「向上闪入」的**承重律已由成片判出**：曝光管亮度、垂直模糊管结构，`mod` 循环被 3 个数量级否掉（2026-10-25，`scripts/flash_attribution.py`）

F-095 只能给"梯度在 201 塌到 0.40"这种单点印象。本条把它变成**带对照的判定**，每件都带一个否证腿。

- **切点帧号**：`round(6.600*30) + lead 3 = 201`。第一版把 `--lead` 解析了却**没用**，
  于是拿 198 当切点、把 198..200 三帧常亮帧当作"闪的开头"，亮度 r 被冲成 **+0.0122**
  （置换比例 0.960 ⇒ 等于没有相关）。修完才是下面这些数。**教训**：仪器的每个参数都要有
  "它改变了读数"的证据，否则它可能是死参数（[[feedback-pass-through-control-per-channel]]）。
- **基线不能取"末 6 帧"**：`--post 14` 时末 6 帧落在 207..212，还在衰减尾巴里
  （基线 108.53 vs 干净 104.54），残差被系统性抬高。现在基线只允许取
  `t >= duration + base_after(0.2 s)` 之外的帧（本窗 16 帧）。

**读数**（`temp/playback-test/flash-attr.json`；帧 201..210 拟合，211..219 专打时间模型）：

| 判据 | 夹紧 (clamp) | 循环（lua 字面 `mod`） |
|---|---|---|
| 亮度 `r(E, log2 mean/base)` | **+0.9329**（置换 0/200） | 同（窗口内两假设不矛盾） |
| 亮度模型 `base·2^(E/2.2)` 残差 | max **55.3**、rms 19.1 码值 | 同 |
| 结构 `r(Vblur, gradV/base)` | **−0.7901**（置换 0/200） | 同 |
| **窗口外** mse（码值²） | **0.3**（max 0.7） | **2040**（max 77） |

⇒ **时间模型定案：夹紧**。`mod` 在 t=0.3 折回 E=1.83 会再闪一次，成片 211..219 平在基线，
差 **3 个数量级**。F-095 里那句散文现在有了分母（9 帧、mse、max）。
⇒ **曝光承重（亮度）**：r=0.933、置换 0/200；模型只在**峰值帧**少 55 码值
（201 预测 186.8 / 实测 242.1），其余 ≤14 —— 与"峰值还要结构/加性项"一致。
⇒ **垂直模糊承重（结构）**：各向异性拟合 `gradV/base ≈ 1/(1+k·X)`，
X=**垂直**强度 `k=0.0552 rms=0.0404 max=0.0694`；X=水平强度 `k=0.4998 rms=0.0917 max=0.1500`
⇒ 单参数下**垂直比水平好 2.3× rms**，与表里 V=300→0 / H=8→0 的形状预言相符。
静态图本身各向同性（基线 gradV 7.44 vs gradH 7.34，窗内均值比 1.18），
所以各向异性**只出现在时间过程里**——这正是"用形态量而非整帧相关"才看得到的东西。

**顺带产出缺失的那条标定**：`u_Strength` 与像素尺度的关系原本要读 `GaussianBlur.frag`；
现在有经验式 `gradV_ratio = 1/(1+0.0552·V)`，可反过来定 sigma——渲染自己的层、量自己的
gradV、选让比值吻合的 sigma，不必先看懂 frag（frag **仍未读**，别当成已证）。

**证据等级**：时间模型**已判**（夹紧胜，3 个数量级）；曝光与垂直模糊**承重已验证**
（r + 200 次置换对照，均 0/200）；峰值帧 55 码值缺口**已观测、未归因**（加性项还是合成顺序）；
位置/位移/噪声三项**未判**（要该层的独立质心，本窗做不到）；`1/(1+kV)` 是**单参数经验拟合**，
不是包内数学。门 L10 的 6.633 仍红，不动阈值、不删时刻。

## F-097 「向上闪入」的**曝光项已进通道 2**：窗内 9/9 帧 MAD 下降、0 帧变坏，
        预切点 3 帧逐字节不动；结构（垂直模糊）如预测**仍然不对**（2026-10-25）

- **改了什么**：`scripts/render_frame.py` 加 `_ae_pkg`/`ae_exposure_at`/`apply_exposure` 与
  `collect()` 末尾的一次全画布后处理（`depth==0` 才做，复合子画布不受父段曝光污染）。
  律来自包内明文表（F-095）：`E(t)` 夹紧、`duration` 取段的 `duration_us`，
  数学逐字照 `Exposure.frag`：`pow(x,2.2) → ×2^E → +u_Offset(0) → pow(1/gsc=1) → pow(0.454545454545)`。
- **两支路之争由成片判掉**（不是由 material 默认值判掉）：`flash_attribution --gamma 1.0`
  （= gamma 空间直乘，`exposure_script` 的 `no_use_linear_light:true` 会走的那支）
  残差 **rms 100.6 / max 166.9** 码值，而线性光 **rms 19.1 / max 55.3** ⇒ 取线性光。
  `Exposure.material` 的默认 `use_linear_light: 0` 与实测一致，
  但那只是旁证——真正定案的是残差差 **5 倍**。
- **A/B 读数**（`scripts/flash_channel2_ab.py`，16 帧，`temp/playback-test/flash-ab.json`；
  每帧渲染两遍 `AE_FLASH.off=True/False`，与成片同帧号比）：

  | 帧 | t(s) | MAD 关 | MAD 开 | 成片 mean | 我们关 | 我们开 | 判定 |
  |---|---|---|---|---|---|---|---|
  | 198–200 | <6.6 | 4.94/5.01/5.00 | **逐位相同** | 113 | 112.7 | 112.7 | 阴性对照通过 |
  | 201 | 6.600 | 138.71 | **107.04** | 242.1 | 97.5 | 134.6 | 改好 |
  | 202 | 6.633 | 87.27 | 62.51 | 183.3 | 97.6 | 133.1 | 改好 |
  | 204 | 6.700 | 54.93 | 28.36 | 151.1 | 97.7 | 127.8 | 改好 |
  | 207 | 6.800 | 26.30 | 14.77 | 119.2 | 97.1 | 111.1 | 改好 |
  | 209 | 6.867 | 16.02 | 14.64 | 106.7 | 97.1 | 98.8 | 改好 |
  | 210–213 | >6.9 | 13.2–14.7 | **逐位相同** | 104 | 97.2 | 97.2 | 窗外惰性 |

  **窗内 9 帧全改好、0 帧变坏、7 帧逐位不变**；平均 MAD **34.98 → 24.35**；
  降级计数 **0/16**（分母=渲染帧数，即路径真执行了）；
  预切点 3 帧 mean 最大位移 **0.000 码值**（曝光没有提前点亮）。
- **结构仍不对，而且是**预期**的不对**：帧 201 我们开了曝光后 gradV 从 5.44 → **6.64**，
  成片是 **0.40**。也就是"变亮了但没被抹平"——这正是 F-096 判出的第二条承重律
  （垂直模糊 V=300→0）缺席的签名。**这条不能顺手"调好"**：见下。
- **垂直模糊为什么不能就地接**（下一个会话别重新推导）：经验式
  `gradV/base = 1/(1+0.0552·V)` 里的 `base` 是**成片基线帧**（窗外稳态）的梯度，
  而渲染器一次只出一帧、**不知道自己窗口的基线**；要把 V 变成 sigma，需要
  ①先按我们自己的稳态帧标定 `sigma → gradV` 曲线（量自己的画面，不猜 frag 量纲，
  因为 `GaussianBlur.frag` **仍未读**），②再逐帧解出使比值吻合的 sigma。
  两个都是渲染器之外的标定步。**中途试加过 `AE_BLUR_K`/`AE_VBLUR_ATTR` 两个常量，
  因为没有可用的标定步而**已撤回**——不留无消费者的脚手架。
- **残留量化**：窗外我们比成片暗约 **7 码值**（97.2 vs 104.4，恒定偏移，与本条律无关，
  是代理片解码/色彩那条老账 U-93）；窗内峰值仍差 **107 码值**（134.6 vs 242.1），
  其中结构项（模糊+可能的加性白）占大头。
- **证据等级**：曝光项**已实现且已用同刻开/关 A/B 判过**（9/0/7 + 阴性对照 + 分母），
  支路归属**已由残差判**（19.1 vs 100.6）；结构项**未实现**，其缺失方向**已由 gradV 读数证实**。
  浏览器通道尚未接（同一律要在 Pixi 里做，属 U-92 之后的新欠口，先记在 #14）。




