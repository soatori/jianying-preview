---
name: jianying-preview
description: 只读预览与校验剪映(JianYingPro)草稿——解析/解密 draft_content.json，在浏览器按时间线复现画面（多时间线切换、播放、文本样式/描边/阴影/渐变、动画、转场与特效标注），并给 agent 提供无浏览器的 JSON/PNG 校验通道。当用户要求"预览剪映草稿"、"看看改完的效果"、"不开剪映能不能看到时间线"、"草稿截图"、"校验/验证剪映改动"，或在 jianying-editor 改完草稿后需要确认结果时使用。绝不修改草稿内容。
---

# 剪映草稿预览器 (JianYing Draft Previewer)

## Overview

用已装剪映的 `videoeditor.dll` 解密草稿，在 Python 侧算出确定性的 **FrameDescriptor IR**，
浏览器只负责把 IR 画出来。因此同一 `(草稿, 时间线, t)` 永远得到同一份结果，
agent 既能读 JSON，也能拿 PNG 截图，不必启动剪映。

本 skill **只读**：不写 `draft_content.json`，不调用加密/apply-plan；
唯一的写操作是在草稿目录下新增 `.jypreview/` 缓存（可用 `--cache user` 关闭）。

依赖 `jianying-editor-skill`（同目录的 `jianying-editor-skill/scripts/`）提供解密与布局解析；
本 skill 只 import，不修改它。

## Quick start

```bash
python <SKILL_ROOT>/scripts/preview.py serve         # 打开 http://127.0.0.1:8765/
python <SKILL_ROOT>/scripts/preview.py launch "草稿名"  # 启动一次性会话并打开浏览器
python <SKILL_ROOT>/scripts/preview.py serve --no-browser --persistent  # Agent 长连接模式
python <SKILL_ROOT>/scripts/preview.py close --session <session_id>     # 关闭一次性会话
```
「打开草稿」→ 弹**系统资源管理器目录选择框**（`GET /api/pick-folder`，服务端 tkinter），选完即打开；
不在网页里自建文件列表。头部只有：打开草稿 / 时间线下拉 / 刷新 / 走带时钟。未打开草稿时这句话
显示在时间线区域里。
布局固定：左侧画面（固定画框、自动 letterbox）+ 走带 + 轨道泳道（**画面轨按 render_index
自上而下=前景到背景、音频轨在下**，与剪映面板一致），右侧是两块各自独立、可点标题栏折叠的面板：
**① 属性栏**（选中图层的定位/几何/文本/样式/素材/效果标签）、**② 信息栏**（时间线、覆盖情况、
可选时间线、缓存，**警告列在信息栏内**）；折叠状态记在 localStorage，折叠一块另一块自动占满。泳道片段块上只显示素材名，不放属性字段；属性栏只渲染
有内容的分组。走带一行只有：播放图标 / 进度条 / 声音图标 / **画幅下拉**（原始 · 16:9 · 16:10 · 4:3 ·
3:4 · 1:1 · 9:16 · 2:1 · 21:9）/ **缩放图标**（悬停浮出拉杆 + 百分比 + 适应，不占行高；点击可固定，
Esc 收起；非"适应"时图标描边变蓝）。轨道泳道顶部是一条**时间刻度尺**（自动选步长，0s/10s…1:00，
与片段条同基准，点它可以跳转）。
`warm` 只在需要全库列表时才用得到。

选择器（`"…"` / `?draft=` / CLI 位置参数同一套）接受绝对路径、文件夹名、did，会去掉首尾空格与
结尾斜杠。**歧义的部分名不猜**：`draft_b` 同时命中 23日/24日时返回 `draft_not_found` +
`candidates`，UI 渲染成可点芯片；命中唯一时才自动选中。名字找不到会先自动重扫一次索引（剪映
新建的草稿因此无需手动刷新），agent 侧也可 `POST /api/drafts/rescan` 强制重扫。

不开浏览器就能用的 agent 通道（`<S>` = `<SKILL_ROOT>/scripts`）：

```bash
python <S>/preview.py timelines "<草稿>"                 # 时间线列表 + active 判定依据
python <S>/preview.py frame "<草稿>" --t 1.7 --compact   # 每层一行（省 context）
python <S>/preview.py what-at "<草稿>" --t 12.4          # 此刻屏上是谁、在哪、什么字体
python <S>/preview.py shot "<草稿>" --t 12.4 --out s.png # 1080x1920 PNG，可复现
python <S>/preview.py shot "<草稿>" --t 12.4 --ratio 16:9 --out w.png  # 换画幅看跨比例效果
```

所有命令输出单个 JSON 文档 `{ok, code, reason, data}`，stdout 已切 UTF-8。

## 何时用哪条通道

| 需求 | 命令 / 端点 |
|---|---|
| 看整体节奏、找时间点 | `GET /api/trackmap` 或 UI 轨道泳道 |
| 断言"某时刻屏上有什么" | `what-at` / `GET /api/what-at` |
| 逐字段核对图层 | `frame --out a.json` + `ir-diff --a-file/--b-file` |
| 视觉确认 | `shot`（`--view stage` 只出画面；`--view ui` 出整页含标注） |
| 查特效/动画/转场中文名 | `catalog --q 叠化` 或 `GET /api/catalog` |
| 改了草稿后验收 | 见下面"改后校验回路" |

## 改后校验回路（与 jianying-editor 配合）

```bash
# 1. 改前留档
python <S>/preview.py frame "草稿名" --timeline <tid> --times 0.5,3,7,12 --out before.json
# 2. 用 jianying-editor 的 apply-plan 真正写回（--apply）
# 3. 让预览器重新解密
python <S>/preview.py clean --help >/dev/null 2>&1; curl "http://127.0.0.1:8765/api/reload?draft=<did>"
python <S>/preview.py frame "草稿名" --timeline <tid> --times 0.5,3,7,12 --out after.json
# 4. 逐层比对：只应出现预期的改动
python <S>/preview.py ir-diff "草稿名" --a-file before.json --b-file after.json
# 5. 截图复核被改的时刻
python <S>/preview.py shot "草稿名" --t 7 --out after.png
```

`ir-diff` 的 `summary.added/removed/changed` 就是改动的"爆炸半径"；`changed[].fields`
给出每个字段的前后值。若出现计划外的图层变化，先停手检查，不要继续写回。

## 只读保证（机器强制）

- 服务器进程永不加载 `videoeditor.dll`：解密在短命子进程 `jypreview.decrypt.worker` 里完成，
  结果写文件后 `TerminateProcess`（DLL 会漏堆、刷 banner，不能常驻）。
- 缓存只落在 `<draft>/.jypreview/` 或 `~/.jypreview/`，**绝不**写进 `Timelines/`；
  只新增自己 `manifest.txt` 记录过的文件，命中他人文件即回退到用户级缓存。
- `selfcheck` 证明两件事：我们拥有的每个缓存文件都在 `.jypreview/` 下（manifest 逐条核对），
  且本次运行没有新建任何草稿内容文件；运行期间草稿被外部改动（剪映自己开着）会作为提示列出，不算失败。
  并 grep 包内禁止出现 `encrypt(`/`apply_plan`/`clone_timeline`/`rename_timeline`/`JyProject(`。
- 清理：`preview.py clean <draft>`（默认 dry-run，加 `--apply` 才删）。

## 覆盖与降级（本机实测，别当成 bug）

| 项目 | 状态 |
|---|---|
| 布局/时间线/多时间线切换 | 完整；`legacy-single` / `multi-timeline` / `hybrid` 三种布局 |
| 混合布局陈旧镜像 | 只读 `Timelines/<tid>/draft_content.json`，根文件按镜像处理并报 `mirror_drift` |
| 文本样式（字体/字号/描边/阴影/渐变/背景/竖排/自动换行） | 渲染，字号已按真实导出标定；字体走 7 级本地阶梯，缺失时出"字体回退"角标 |
| 花字 `effectStyle` | 本地有 `artistEffect/<rid>/<md5>/effectStyle.json` 时精确，否则出中文名占位（约 58% 可解析） |
| 转场 | 标注名称/时长/`is_overlap`，并按名称近似（叠化→交叉溶解、闪黑/闪白…）；**不改变时间线长度** |
| 入场/出场/循环动画 | 按对照表近似（淡入淡出/缩放/位移/旋转/抖动/模糊），其余占位标注 |
| 画面特效/滤镜/美颜 | 占位标注（美颜 `figure` 本机无任何名字来源，只出一个聚合角标） |
| 素材像素 | 新草稿基本齐全；老草稿大量路径失效 → 出带名称/编码/原路径的占位瓦片，UI 明示"N 个素材缺失" |
| 复合片段 | 递归渲染内层内容（媒体按 `draft_file_path` 所在目录解析）；内层不可解析时退回剪映自己的 `draft_cover_path` 封面 |
| 音频 | 播放时挂 `<audio>` 按 IR 的 `source_time_us`/`volume` 对齐（不做多轨混音/淡变曲线）；轨道静音与无路径的仍只列标签 |
| 播放 | **窗口驱动 + 状态机**：`PlaybackController` 只在有效窗口覆盖当前 `t_us` 时推进时钟；窗口请求使用 generation 丢弃旧结果，`FrameStore` 区分 point/window IR，`SceneGraph` 决定可见层，`MediaScheduler` 管理解码预算/预取/释放，`EffectRenderer` 按 `t_us` 应用文字和媒体动画。视频 `currentTime` 不再反向修改时间线 |
| 播放开关的隐式写操作 | `t` 深链在被打开草稿后只做一次：`start()` 读的是模块加载时快照的 `deepLink`，因为 `openDraft`/`selectTimeline` 会把选中的 timeline 写回 `params` —— 若直接读 `params`，同一时间线会被选第二次，把刚建好的图层池 `clear()` 掉，表现为"按下播放有 1 帧空白" |
| 蒙版 / LUT / curve_speed / 复合片段>2 层 | 不渲染，见 references |

对照表覆盖率（对 60 份明文草稿实测）：转场 100%、画面特效 100%、动画 100%、字体 93%、
花字 58%、贴纸 7%。重跑：`python -m jypreview.tools.catalog_coverage --drafts-root <root> --catalog <json>`。

## 关键不变量

- 时间单位一律 **微秒(µs)**；`fps` 缺失时默认 30 并写进 `warnings`。
- **画幅（`--ratio` / `?ratio=`）是重算而不是拉伸**：`apply_ratio` 保持长边不变换比例（9:16 的
  1080×1920 → 16:9 得 1920×1080，与剪映一致），随后所有几何与 `px_per_size = width × 0.00625`
  按新画布重算；片段保持自己的像素尺寸与相对位置，所以竖屏内容切横屏会露黑边——这是剪映的真实
  行为，不是渲染缺陷。IR 里 `canvas.ratio` 是视图比例，`canvas.ratio_draft` 是草稿原比例。
- `clip.transform` 是**半画布**单位且 y 轴向上：`cy = H/2 − y·H/2`（`y=-0.8` → 1920 高的画布上 cy=1728，标准字幕位）。
- 文本 `em_px = font_size × 画布宽 × 0.00625`（即 `width/160`）。**已用真实导出视频标定**：
  `<export>.mp4` 里 8 字/9 字两行字幕逐字推进均为 67.5px，字号 10 → 6.75px/单位。
  旧值 `width/100`（10.8）会把字幕画大 1.6 倍。重测：`python -m jypreview.tools.measure_export`。
- 描边/阴影按 **em 相对**换算；阴影 `distance` 是 em 的百分之一（`distance:5` + `em:86` ≈ 4.3px）。
- z 序：`segment.render_index ?? track.render_index ?? 类型默认`，升序=后→前；`text` 默认 14000。
- `visible: false` 的片段一律排除（模板留下的隐藏文本很常见）。
- 复合片段（`subdraft`）**没有自己的盒子**：Python 侧把内层图层按 `scale_to_parent` 重算进父画布
  坐标，前端递归摊平到同一画布。子层的 `z.global` 来自内层时间线，**不能**用于跨兄弟片段排序，
  所以绘制序取遍历序号（`Stage.paint`）；嵌套文字用独立的 `.nested-text` 堆叠上下文，才能被后一个
  兄弟片段的画面盖住。把 HTML `<div>` 塞进 SVG `<g>` 会让它脱离布局（rect 0×0、画面全黑）。

## 故障排查

| 现象 | 处理 |
|---|---|
| `drafts_root_not_found` | `--drafts-root "D:\\JianyingPro\\JianyingPro Drafts"` 或设 `JY_PREVIEW_DRAFTS_ROOT` |
| `decrypt_failed` / 找不到 DLL | 设 `JIANYING_VIDEOEDITOR_DLL` 指向确切 `videoeditor.dll`；加密草稿仅支持 Windows |
| `timeline_ambiguous` | 别用 `active`，从 `timelines` 里挑一个 id |
| `draft_not_found` | 看 `data.candidates`：多半是部分名同时命中多条（不替你猜）。新建草稿会自动重扫一次索引，仍失败就 `preview.py timelines "<名字>"` 重试 |
| 点「打开草稿」没弹选择框 | 服务跑在无人登录的会话里时 tkinter 无法显示桌面窗口；直接用 `?draft=<草稿文件夹路径>` |
| 画面全黑但有图层 | 多半是素材路径失效；看 `media.placeholder_reason` 与 UI 瓦片文字 |
| 复合片段只有字幕没有画面 | 先 `frame --compact` 确认内层 `media.path_served` 有值且 `exists:true`，那就是渲染序问题，比对 `Stage.paint` 与 DOM `z-index` |
| 改了 `web/*` 界面没变 | `/web/*` 已带 `Cache-Control: no-cache` 且 import 统一打 `?v=<mtime>`；仍不生效就硬刷新一次 |
| 截图报 `page never became ready` | 确认 `serve` 在跑（`shot` 默认复用服务器持有的浏览器）；或加 `--no-server` |
| `browser exited during startup` | 规范 profile 被上一次被杀的浏览器占住；`BrowserSession` 会自动换同级新 profile 重试，日志里会带 `retry with msedge-<ts>-0` |
| 视频区不显示 | 用于截图的浏览器需带 H.264：Playwright 自带 chromium/headless_shell **不带**，默认已优先用 Edge |
| `catalog` 版本不一致 | `python preview.py catalog` 重建；或 `--allow-catalog-skew` |
| 缓存太多 | `preview.py clean --apply`，或 `--cache user` 改到用户级 |

## 验收

```bash
python <SKILL_ROOT>/scripts/preview.py selfcheck --milestone all   # M0/M1/M2 共 40 项断言
python -m jypreview.tools.audit_playback "<草稿>" --seconds 24     # 需要 serve：真机播放逐帧比对
```

## Resources

- `references/ir-schema.md` — FrameDescriptor 全字段契约（谁算什么、单位、降级规则）
- `references/draft-schema-notes.md` — 实测草稿 JSON 字段与坑（与 editor skill 文档不一致处以草稿为准）
- `references/effect-catalog.md` — 对照表三层来源、`render_class` 判定、真实覆盖率
- `references/calibration-and-oracle.md` — 文字尺寸/fit 模型的标定方法与已知残差
- `references/agent-verification-loop.md` — 改前留档 → 写回 → 重载 → ir-diff → 截图 的完整 SOP，
  含"验播放"一节：`__snapshot()` 读 DOM 池 + `python -m jypreview.tools.audit_playback` 真机逐帧比对
