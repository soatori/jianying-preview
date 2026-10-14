# 导出对照夹具与播放匹配现状（2026-10-13）

目标：复制 `10月12日` 草稿与它的真实导出作为测试夹具，让项目"正确识别 + 播放时匹配导出结果（忽略首帧）"。
本轮做完夹具与识别，并交付可重复的逐帧匹配工具；**播放匹配尚未达成**，根因已定位到具体一层。

## 1. 夹具（不进仓库）

| 项 | 值 |
| --- | --- |
| 草稿副本 | `D:\JianyingPro\JianyingPro Drafts\1012-1626-fixture`（563 MB，`draft_content.json` 与原件逐字节一致） |
| 副本 did / 活动时间线 | `1e9cd2a6f0b06c04` / `44BA0A70-E900-4774-828A-FA74D709DD0F`（名称"时间线01"） |
| 真实导出副本 | `C:\Users\11\.jypreview\fixtures\1012-1626-fixture\1012-1626.mp4`（+ 封面 jpg） |
| 导出 sha256 | `313320a359caa82801b5364d43812a415206ab41535ea61d29f450781c35462c` |
| 原件 | `D:\JianyingPro\JianyingPro Drafts\10月12日`、`E:\输出\机床蒋堂\1012-1626\1012-1626.mp4`（只读，未改动） |
| 清单 | `C:\Users\11\.jypreview\fixtures\1012-1626-fixture\fixture.json`（含 did/tid、两个 sha256、画布、时长、来源路径） |

副本排除 `.backup/` 与 `.jypreview/`，所以识别走的是全新解析路径而不是复用缓存。
`.gitignore` 新增 `fixtures/`、`*1012-1626-fixture/`，草稿与导出永不入库。

## 2. 新工具 `python -m jypreview.tools.export_match`

`scripts/jypreview/tools/export_match.py`，默认读上面那份 `fixture.json`，跑在默认解释器上
（只做 HTTP + Pillow + ffmpeg，不需要 mlt7），但要求 serve 由隔离 MLT 解释器启动：
`powershell -File temp\mlt-build\server.ps1 -Action start`。

它做三件事，全部按 `2026-10-03-playback-remaining-execution.md` Task 4 的"导出对照"要求：

1. 识别：草稿 sha256 完整性、`did/tid/layout/encoding`、模型帧 IR 能否解析、画布、帧率、时长。
   帧率取模型自己的口径（`/api/frame` 的 `fps`），因为 `TimelineContent.fps` 对这个草稿是 0，
   真实值来自 `draft_adapter` 的 `fps_defaulted`（默认 30）——这一点写进代码注释，避免以后又去猜。
2. 对齐：导出帧用一次 ffmpeg `select='eq(n,K)…'` 单遍解码按**精确帧号**取，不用 `-ss`
   （`-ss` 会吸附到关键帧，正好会把要测的对齐悄悄改掉）；解码时 `out_range=full` 对齐 MLT 的
   full-range RGBA；ffmpeg 9 已删 `-vsync`，先试 `-fps_mode passthrough` 再退回。
3. 匹配：项目帧号 ↔ 导出帧号，**首帧按目标要求排除**（`first_frame_ignored` 记录该口径），
   每帧比对渲染 PNG 与导出静帧，并核对 `X-Project-Frame` 响应头与请求帧号一致；
   `--offset-scan --offset-window N` 给出 ±N 帧的相似度曲线，用来区分"内容不对"与"整体错位"。
   默认不设阈值（沿用"benchmark 只记观测值，不发明阈值"的既有约束），`--min-similarity` 可选。

## 3. 实测结果

识别与对齐全部 PASS：

```text
PASS: draft fixture intact / draft recognized (did=1e9cd2a6f0b06c04 layout=hybrid encoding=jianying-dll)
PASS: model IR resolves the fixture  layers=4 media_missing=0
PASS: canvas matches export          model 1080x1920 vs export 1080x1920
PASS: fps matches export             model 30.0 (30/1) vs export 30/1
PASS: head aligns, tail tolerated    export 51177007 us - model 51066666 us = 110341 us tail (3.31 帧)
PASS: export frames decoded          30 PNG stills, one ffmpeg decode pass
PASS: playback backend open          phase=ready duration_us=51066666
```

匹配 FAIL：`--frames 6` 时 median 0.6345 / min 0.5618；加 `out_range=full` 与 ±8 偏移扫描后
median 0.5992、最佳偏移 −5，仍远低于可用水平。也就是说差异不是色彩范围、不是整体错位、
也不是帧号身份（`rendered_frame_header_mismatches = 0`），而是画面内容本身。

肉眼比对同一帧（项目帧 200，两份 PNG 存在 `temp/inspect/`）：导出是满屏竖构图 + 三行标题；
我们的渲染几乎整屏是 `#e040a0`，顶部一条真实画面，只有一行字。`#e040a0` 正是
`mlt_backend.py` 里 `media_placeholder` 的占位色。

> 本节是当天第一次测量的原始状态，只作留痕。当前数值见 4h（曲线实现后）与 4j（调色落地后：
> 全帧 median 0.8043、干净帧 median 0.8135），下一步路线见 4k。

## 4. 根因定位（初判，结论见 4b 与 4e）

`temp/diag_compile.py` 把模型逐层摊开后：

- 顶层 `video` 片段（`C7463.MP4`，NAS 上存在）：`path_served=True exists=True` ✓
- 顶层 `compound` 片段 `FE4B6D93`（0.8–49.5 s，铺满整条时间线，正是背景）：`ph=0`，
  但它 nested 里的**每一个** video 片段都是
  `MediaRef(path='', exists=False, available_range=TimeRange(0, 45700000), duration_us=45700000)`

素材时长/可用区间都读到了，说明子草稿的 material 表被解析；**空的是 path**——
嵌套素材的文件路径没有解析出来，于是 `clip.placeholder=True`，MLT 侧整屏变占位色，
子草稿里的另外两行标题也一起没了（它们同样挂在 nested 上）。
`model.warnings` 里那 10 条 `media_missing:<id>` 与 nested 里的
`media_missing:FE4B6D93…/<子片段 id>` 就是这个。

这与 `SKILL.md` 故障表里"复合片段只有字幕没有画面"是同一症状，按该表口径应先确认内层
`media.path_served`——这里是空值，所以属于解析/注册层，而不是渲染序层。

下一步该做的（不在本轮范围）：让 `DraftAdapter` 在构建 nested 内容时用**子草稿自己的** material
表与路径基准解析 `MediaRef.path`（顶层能解析、nested 不能，说明查找只走了外层 registry）。
修好后 `export_match` 无需改动即可复测，阈值也应在真实残差出来以后按观测定，而不是先拍。

## 4b. 已修的一处解析缺陷与量化效果（同日追加）

诊断推翻了"适配器没替换 token"的初判：`media.py` 一直用 `PLACEHOLDER_RE` 处理
`##_draftpath_placeholder_<guid>_##/...`。真正的 bug 在 `model/draft_adapter.py` 的复合片段分支：
`draft_file_path` 本身就是这个 token 形式，代码直接 `Path(draft_file).parent` 当子草稿根目录，
于是 root 变成 `.../1012-1626-fixture/##_draftpath_place…` 这样不存在的目录，
嵌套素材的全部兜底候选（含 `<root>/media/<name>`）都落空。

修法：先经 `media.resolve(draft_file, root)` 定位真实文件再取 parent，定位不到才退回原逻辑。

| 指标 | 修前 | 修后 |
| --- | --- | --- |
| 模型里 `exists=False` 的素材 clip（全树 112 个） | 60 | 5 |
| `export_match` median 相似度（8 帧） | 0.5992 | 0.7495 |
| min 相似度 | 0.5618 | 0.6368 |
| 帧号身份不符（`X-Project-Frame` vs 请求帧） | 0 | 0 |

同时把被挪动的素材回捞进夹具：`X:/工博会2026/IMG_7318…7322.MOV` 等 13 个文件现在在
`<fixture>/media/`（`media.resolve` 原生把 `<draft>/media/<basename>` 当兜底候选，因此不需要改产品代码）。
另有 11 条索引里的"缺失"是我索引脚本 token 正则漏了 GUID 连字符造成的误报，文件本就在草稿 `Resources/` 内；
剩下 36 条是剪映特效/资源缓存（`User Data/Cache/effect/…`、`artistEffect/…`），不是画面素材。

回归：`test_timeline_model`、`test_mlt_compiler`、`test_mlt_controller` 均退出 0；
`test_mlt_acceptance` 仍是 9 个 section PASS + capture 证据门槛 FAIL（与本轮改动无关，维持原状）。

## 4c. 仍未达成匹配的原因（下一步）

1. 修后第 200 帧已能看到多层真实画面，但仍有一块占位矩形（该时刻还剩 5 个 clip 未解析：audio/sticker/video）。
2. 模型自己声明不预览的项在导出里是生效的：`effect_unsupported` 数十条、`text_shadow_unsupported` 数十条、
   `hsl` 36 条、`color_curves` 2 条、`animation_unsupported` 若干——这些是像素级差异的稳定来源。
3. 草稿在导出之后又被编辑过：导出 16:26，`draft_content.json` 16:39。所以部分时段的内容与导出本就不一致，
   逐帧匹配只能在"未改动时段"上逼近。
4. 原始 `D:\JianyingPro\JianyingPro Drafts\10月12日` 在本轮工作期间已从语料中消失（`10月12日 (1)` 也不在）。
   现在唯一的两份留存是 `1012-1626-fixture` 草稿副本与 `E:\fixtures\1012-1626-fixture` 打包件（含 sha256 清单）。
   这既是夹具的价值，也说明匹配基准只能以这两份为准。

阈值仍不设（沿用"不发明阈值"的约束）；等 1–3 收敛后按实测残差定 `--min-similarity`。

## 4d. 内存与本轮修正后的真实状态

夹具跑起来很吃内存：这份 112 素材 clip 的草稿，serve 进程工作集峰值 **8,638 MB**（本机物理 15.8 GB）。
因此约定：每轮测量后立刻 `server.ps1 -Action stop`，不要让它常驻；`export_match` 的像素比对也改成
按字节分块累计 RMSE，不再把栅格展开成 Python float 列表（原来每张图几十 MB，逐帧×偏移会叠好几份）。

本轮另外三处修正与实测：

| 项 | 修前 | 修后 |
| --- | --- | --- |
| 模型 `clip_invalid`（异常被宽泛 except 吞掉后丢整条片段） | 68 | 0 |
| 编译 `media_placeholder` | 70 | 3 |
| 模型未解析素材 clip | 60 | 4（1 贴纸缓存 + 3 个 material_id 两处表都查不到） |
| `export_match` median（8 帧） | 0.7495 | 0.7495（未变） |

`clip_invalid` 那 68 个是**我自己引入的回归**：给 `MediaRef` 加 `rotation` 字段时用 `_integer` 校验，
而容器旋转是 `-90`，`ValueError` 被 `_build` 的 `except (TypeError, ValueError, ...)` 吞成 `clip_invalid`
并整条丢弃片段。这暴露了一个流程性问题：`clip_invalid` 不带异常类型，任何构造期 bug 都会伪装成
"素材/片段无效"。值得单独改成把异常类名与 clip id 一起记进 warnings。

旋转不是那块品红的原因：实验证明 MLT 的 avformat 产者在 `get_image(rgba, 1080, 1920)` 下
已经按显示方向出了 upright 帧（`meta.attr.rotate` 全为 None，但出图是正的）。所以 `probe.rotation`
只作为元数据保留（含 `display_width/height`），**没有**接进编译器。

第 200 帧仍有 50.8% 是 `#e040a0`，来自 3 个 `material_id` 在父表与子表都查不到的内层视频
（内层时间 0–4.87 s，映射到外层 2.33–7.20 s，正好覆盖该帧）。这是匹配度停在 0.75 的当前主因，
也是下一步该查的：那三个 id 究竟存在哪一层。

## 4e. 收尾：悬空引用与最终数值

那 3 个仍未解析的内层视频不是项目缺陷：它们的 `material_id` 在活动时间线、两条兄弟时间线、
14 个子草稿明文文件、以及所有字符串编码 payload 里都**没有定义**——是草稿自身的悬空引用
（导出后编辑过，素材被删而片段还在）。为它们试加过的"父内容回退"和"兄弟时间线回退"
在实测中没有带来任何改善（未解析数 4→4），已撤回，只保留有数据支撑的两处修复
（子草稿 `draft_file_path` 的 token 解析、`_media` 的父草稿 root 回退）。

最终测量（`--frames 12`，忽略首帧，serve 用完即停）：

```text
median 0.7706 / min 0.6011 / max 0.8160，12/12 帧低于 0.90
rendered_frame_header_mismatches = 0        # 帧号身份逐帧正确
clip_invalid 0 · media_placeholder 3 · 未解析素材 4/112
test_timeline_model / test_mlt_compiler / test_mlt_controller = exit 0
```

匹配仍未达成，剩余误差按证据分三类：192 条 `effect_unsupported`、38 条 `text_shadow_unsupported`、
28 条 `animation_unsupported`、`hsl` 36 / `color_curves` 2 —— 模型自己声明不预览而剪映导出生效；
3 个悬空引用片段（第 200 帧那 50.8% 品红的主因）；以及导出后 13 分钟的编辑漂移。
前两类需要实现剪映的特效/阴影语义才能收敛，属于新功能而不是夹具能绕开的范围，因此不设阈值。

内存侧记一条硬事实：这份 112 素材 clip 的草稿，serve 工作集 8.6–9.2 GB（本机 15.8 GB）。
`temp/mlt-build/server.ps1` 现在启动前会清掉占用端口的旧进程，测量结束必须立刻 `-Action stop`。

## 4f. 残差归因（`export_match --attribute` + 离线像素分析）

`--attribute` 会给每帧加两项：`placeholder_share`（渲染里 `#e040a0` 占位像素占比）与
`similarity_grade_normalized`（按通道均值/方差对齐后的相似度）。12 帧实测：

| 项 | 值 |
| --- | --- |
| raw median / min / max | 0.7706 / 0.6011 / 0.8160 |
| 对齐一阶统计后 median | 0.8330 |
| 占位占比 | 均值 9.21%，仅第 192、702 帧为 50.5% / 60.0%，其余 10 帧为 0 |
| 帧号身份不符 | 0 |

对 8 个"零占位"干净帧又做了离线归因（图对存在 `temp/inspect/attr/`，分析脚本 `temp/color_attr.py`）：

- 全局传递函数不是原因：把渲染按 tv→full 展开反而从 0.8034 降到 0.7974；full→tv 0.8055；
  gamma 0.92 也只有 0.8155；而按通道均值/方差对齐能到 0.833。
- 误差在画面上均匀分布：上/中/下三段平均绝对误差 35.77 / 37.40 / 38.33，不集中在字幕带，
  也不是缺层（占位为 0）。
- 渲染在每帧每通道都系统性偏暗、方差偏低（例：121.4/98.0/103.5 对 170.8/130.5/143.2）。

结论：干净帧那 ~0.15 的残差是**逐片段调色**，不是色彩管线、不是几何、不是缺层。
模型侧对应的是自己声明不预览的 `hsl` 36 条、`color_curves` 2 条、`material_colors` 22 条
（`model/content.py` 把这些列在未预览桶里）。因此下一步的唯一高价值项是在 MLT 路径实现
剪映的 HSL/曲线/素材颜色语义；`text_shadow_unsupported` 38 条与 `animation_unsupported` 28 条
是次级项（误差没有集中在文字带，说明它们不是主因）。

第 192、702 帧的 50–60% 占位是另一件事：那 3 个悬空 `material_id` 在整份草稿里确实没有定义，
属于素材缺失，任何渲染器都只能画占位，不计入匹配残差的修复范围。

## 4g. 曲线落地：解析与 producer 级应用均保留（含一条自我更正）

把剪映曲线接进 MLT 的尝试得到三条硬事实：

1. 解析可行且已保留：`color_curves` 的贝塞尔节点（`anchor` + `left_control`/`right_control`）
   在适配器里采样成 `Clip.color_curve`（本夹具 2 个片段各 17 点/通道，master 曲线确认抬亮：
   x=0.17→y=0.205）。这部分有回归保护（`test_timeline_model` 通过）。
2. 这个 MLT 7.40 ucrt64 构建里 **`avfilter.*` 全部空转**：`avfilter.curves`（含 `preset=lighter`）
   与 `avfilter.eq brightness=1` 对固定灰度源都不改变一个像素；`lift_gamma_gain` 六种属性拼写同样无效。
   实际有效的只有原生 `gamma`、`brightness`、`frei0r.gamma`、`frei0r.levels`。
3. 用原生 `gamma` 拟合曲线后，帧 64 从 0.7925 升到 0.8044（该曲线片段只在 2.33–7.20 s 可见，
   所以影响范围窄），实现保留在 `mlt_backend` 的 producer 级挂载。

### 撤回一条错误归因

我先前写"挂 `gamma` 会毁掉混合链（compiler 预言变 `(110,144,129)`/`(7,18,60)`）"——**这是错的**。
把 `mlt_backend.py` 完全回退到 HEAD（零曲线代码）后，同一条预言仍然随机失败：
经 `run_gate.ps1` 的 16 次干净运行里失败 5 次（≈31%），失败值包括
`(254,11,103)`、`(151,36,117)`、`(121,108,165)`、`(110,144,129)`、`(178,203,203)`，
全是红底与 `#e040a0` 占位色的不同混合比例；同一进程内连跑 3 次则全通过。

即 **`test_mlt_compiler` 的嵌套缺素材叠加预言本身就是非确定性的**（约 20–30% 失败率），
与曲线改动无关。不是 Python 哈希 seed 造成的：固定 `PYTHONHASHSEED=0` 连跑 4 次全过，
但固定 `PYTHONHASHSEED=1` 仍失败 1/4，随机 seed 下 5/16 失败 —— 三组样本都不足以区分，
方向应看 MLT 侧（`cairoaffineblend` 混合、loader 线程池）而非 Python 迭代顺序；
`mlt_backend` 里与顺序相关的只有 `sorted(...)` 两处和 `model.transitions` 的顺序遍历，本身是确定的。

重要对照：**夹具的匹配测量是可复现的**。三次独立 12 帧运行给出完全相同的
median 0.7706 / min 0.6011 / max 0.8160 与 `rendered_frame_header_mismatches = 0`，
所以这条非确定性不影响 `export_match` 的基线，只影响那条合成小图的断言。

### 本构建的调色原语限制（仍然成立）

`avfilter.*` 选项在这个 MLT 7.40 ucrt64 构建里完全空转（`avfilter.curves` 含 `preset=lighter`、
`avfilter.eq brightness=1` 对固定灰度源都不改变像素），`lift_gamma_gain` 六种属性拼写同样无效；
实测有效的只有原生 `gamma`、`brightness`、`frei0r.gamma`、`frei0r.levels`。
因此剪映 `hsl`（本夹具 36 条，指向特效包 `User Data/Cache/effect/7416258989467374091`）
无法忠实落地，这仍是全局偏暗的主因。



也就是说：忠实的曲线/HSL 落地需要先解决两件事——这个构建里可用的调色原语（avfilter 不可用），
以及滤镜挂载位置（producer 级而非 lane 级，并重新验证混合链）。这属于新功能工作量，
不是夹具能绕开的配置问题。当前匹配数值仍是 median 0.7706 / min 0.6011（12 帧，忽略首帧）。

顺带记录一次测试非确定性：在同一份已回退代码上，`test_mlt_compiler` 曾给出 `(178,203,203)`，
随后 3 次连跑全部通过。可疑触发条件是同一命令里并发两个 MLT 进程（本机内存压力 9 GB 级别）。
后续跑门槛应当串行执行，不要把 compiler 与 controller 放在同一条并发命令里。

## 4h. 夹具基线（供后续改动对照）

`export_match --frames 12 --attribute` 在曲线实现生效后的基线（`temp/export-match-baseline.json`）：

| 指标 | 值 |
| --- | --- |
| 全部 12 帧 median / min / max | 0.7706 / 0.6011 / 0.8160 |
| 干净帧（无占位）9 帧 median / min | **0.7950** / 0.7282 |
| 干净帧对齐一阶统计后 median | 0.8330 |
| 含占位帧 | 3（帧 192 占位 50.5%、帧 702 占位 60.0%、帧 1339 占位 0.01%） |
| 帧号身份不符 | 0 |

对照记录：曲线实现前，同一 12 帧的干净帧 median 是 0.7866；实现后 0.7950。
后续任何渲染改动应当先看 `median_similarity_clean_frames` 这个数，
含占位帧不参与评价——那 3 个 `material_id` 在整份草稿里没有定义，
`placeholder_infos` 也只有 `meta_type: none`、不含任何路径线索，属源数据缺失，无法恢复。

三次独立 12 帧运行的 `median/min/max` 完全一致，说明**夹具测量本身是可复现的**；
不确定的只有 `test_mlt_compiler` 那条合成小图的断言（见 4g）。


## 4i. 调色天花板（关掉一条路）与回归门槛

对 7 个干净帧做"作弊式"逐帧最优全局亮度×饱和拟合（网格 1.0–1.4 / 1.0–1.3）：

| 帧 | raw | 最佳全局拟合 | 最佳倍率 |
| --- | --- | --- | --- |
| 64 | 0.8044 | 0.8640 | 亮度×1.35 饱和×1.3 |
| 447 | 0.8145 | 0.8177 | ×1.05 / ×1.0 |
| 574 | 0.8142 | 0.8198 | ×1.1 / ×1.0 |
| 829 | 0.7903 | 0.8264 | ×1.4 / ×1.2 |
| 1084 | 0.7652 | 0.7993 | ×1.4 / ×1.0 |
| 1339 | 0.7676 | 0.8125 | ×1.35 / ×1.0 |
| 1467 | 0.8247 | 0.8684 | ×1.3 / ×1.0 |

median 0.8044 → **0.8198**，且最佳倍率每帧从 1.05 跳到 1.4。结论：全局调色最多解释约 0.015，
剩余约 0.17 是逐区域内容差（192 条 `effect_unsupported`、38 条 `text_shadow_unsupported`、
28 条 `animation_unsupported`、贴纸，以及导出后编辑漂移）。所以"实现剪映调色"不是这台机器上
能吃到残差的杠杆，这条路可以关掉；`hsl` 里带数值的那些条目符号还与我们需要的方向相反
（`lightness: -42/-20` 是压暗，而我们本来就比导出暗），进一步印证它们不是主因。

据此把夹具做成可判定的回归门槛，而不是保真声明：`--min-clean-similarity` 只评价无占位帧，
双向验证过 —— 地板 0.79 时 exit 0，地板 0.95 时 exit 1（`temp/export-match-gate-pass.json` /
`temp/export-match-gate-fail.json`）。当前地板值取实测 0.79，含义是"别退步"，不是"已匹配"。
调色落地后（见 4j）实测升到 0.8135，地板同步抬到 **0.81** 并复验 exit 0
（`temp/export-match-floor-081.json`）。

## 4j. 调色落地：本轮最大残差的闭环（推翻 4f 的结论）

4f 说"干净帧残差是逐片段调色"，但方向搞错了一半：真正被丢掉的不是 `color_curves`/`hsl`，
而是 `materials.effects` 里的**调节标量**。逐条 dump 后确认：

- 每个视频片段都挂着 `smart_color_adjust = 0.8`（智能调色），另有 `light_sensation`（光感）
  0.17–0.36、`brightness` 0.04–0.25、`contrast` 0.04–0.19、`clear` 0.44–0.77、`sharpen`、
  `temperature` ±0.23、`highlight`/`shadow` 负值；`hsl` 36 条绝大多数是默认零值（只有 3 条
  有 hue/saturation/lightness），`material_colors` 22 条**只有 `id` 一个字段**（空壳）。
  所以偏暗不是"HSL 包打不开"，而是这些标量在适配器里被整桶丢弃了。
- 反解校准（`temp/grade_fit.py`，把每帧每通道均值还原成 gamma）：无截距最小二乘给出
  `ln(gamma) = 0.149·smart_color_adjust + 0.452·light_sensation + 0.152·brightness − 0.234·contrast`，
  离线模拟把 8 帧 median 从 0.7834 抬到 0.8144（逐帧作弊式拟合的上界是 0.819，见 4i，
  说明这条公式已经吃到绝大部分可得收益）。
- 实现：`Clip.grade`（适配器按 kind 聚合，本夹具 19/98 片段带值）+ `mlt_backend` 的
  `_grade_gamma`/`_merge_grade`，最终落在 producer 级单一级 `gamma` 滤镜上，与曲线 gamma 相乘合并。
- **复合片段的调色必须下沉到叶子 producer**：挂在子 tractor 上的滤镜在这个构建里只部分生效，
  A/B（`temp/grade_ab.py`）实测帧 64 在"tractor 挂载"下只到 0.8054，改成祖先链继承后到 0.8293。

夹具实测（12 帧、忽略首帧，`temp/export-match-graded2.json` 对比 `temp/export-match-baseline.json`）：

| 指标 | 调色前 | 调色后 |
| --- | --- | --- |
| 全 12 帧 median | 0.7706 | **0.8043** |
| 干净帧（9→10 帧）median | 0.7950 | **0.8135** |
| 干净帧 min | 0.7282 | 0.7343 |
| 一阶统计对齐后 median | 0.8330 | 0.8442 |
| 帧号身份不符 | 0 | 0 |

回归地板随之从 0.79 抬到 **0.81**。门槛复跑：`test_timeline_model` 0、`test_mlt_controller` 0、
`test_mlt_compiler` 0（本轮一次通过，抖动见 4g）、`test_mlt_acceptance` 9 节 PASS + 3 条
capture-evidence FAIL（缺真机采集证据，与本改动无关）。

仍未落地的（按残差贡献排序）：`saturation`/`temperature`/`highlight`/`shadow`/`clear`/`sharpen`
已进模型但本构建没有可用的逐通道/分区原语（`avfilter.*` 空转，见 4g）；美颜 `figure` 64 条是
逐区域几何形变；文字阴影 38 条。帧 192 的 95.8% 占位与调色无关（A/B 两版一致），仍是那 3 个
悬空 `material_id`。

## 4k. 原语可用性实测：推翻 4g 的"能力缺口"判断，并排掉一条猜测

`temp/primitive_probe2.py`（日志 `temp/gate-logs/primitive-probe7.log`，灰色源 `#806040`，
逐通道均值对比）在本构建上实测：

| 结论 | 服务 |
| --- | --- |
| **可用**（像素确实变化） | `lumaliftgaingamma`（`lift`/`gamma`/`gain` 以及 `gain_r` 等逐通道）、`frei0r.saturat0r`、`frei0r.coloradj_RGB`、`frei0r.curves`、`frei0r.levels`、`brightness`、`gamma` |
| **不可用**（全 0 变化） | `avfilter.*`（`eq`/`hue`/`colorbalance`/`lut3d` 全试）、原生 `saturation`、`lift_gamma_gain`、`frei0r.saturation` |

所以 4g 写的"忠实的曲线/HSL 落地需要先换一个能用的构建"是**错的**：逐通道与分区（lift/gamma/gain）
原语就在眼前，`lumaliftgaingamma` 甚至同时给到阴影/中间调/高光三段和逐通道增益。剩下的只是
"剪映标量 → 这些参数"的标定工作量，不是能力缺口。另外记录一次踩坑：手写 tractor + null consumer
的探测进程会在原生层崩（`-1073741819`），必须像 `filter_probe.py` 那样先
`mlt7.Factory().init(None)` + `profile.set_explicit(1)` + `producer.get_frame(0)`。

同时排掉一条对残差的猜测：**整份草稿没有任何关键帧变换**。主时间线 22 条视频片段与 14 个子草稿
的 `common_keyframes` 计数都是 0，所以 4j 之后"画面平移几个像素会更像"不是动画没落地。
`temp/geom_fit.py` 对 5 帧做尺度×位移网格搜索：最优 scale 全在 0.99–1.00，位移收益只有零星
±4px（帧 1339 0.7908→0.8388、1212 0.7195→0.7451、64 无收益），属重采样与内容漂移级别，
不是系统性几何错误——几何这条可以划掉了。

下一步按可期望收益排序：① 用 `lumaliftgaingamma` 把 `temperature`/`highlight`/`shadow` 和
逐通道曲线真正落地（方法与 4j 相同，改成逐通道标定）；② 文字阴影 38 条；③ 美颜 `figure` 64 条
（逐区域形变，收益最大但成本最高）。

## 4l. 导出头部重复帧：对齐之后匹配度是 0.86，不是 0.81

4j 之后再看误差分布（`temp/error_locate.py`）：帧 1212 有 **84.9% 的误差能量落在高细节区**
（高细节 mean|err| 81.5 对低细节 30.6），这是"边缘对不上"的特征，而不是"颜色不对"。于是把
项目帧 N 与导出帧 N−8..N+8 全比一遍（`temp/offset_scan.py`，日志
`temp/gate-logs/offset-scan2.log`），结果很直接：

- **导出的开头把项目首帧重复了三次**：导出帧 0/1/2 互相相似度 0.9996、平均亮度都是 142.4，
  帧 3 才变化（0.615、138.0）。这只给出一个**下界**（项目帧 N 至少对应导出帧 N+2）；按内容对齐
  的最优值是 **N+3**，见下面的工具规则与剪辑边界验证。此前每个 median 都白扣了一个固定错位——
  这也正好对上"开头首帧忽略"这句话的物理含义。
- 8 帧网格的 median 随偏移单调上升后回落：`+0 0.7508 → +1 0.7721 → +2 0.8199 → +3 0.8610 →
  +4 0.8262 → +8 0.7815`，单帧最高到 0.9143（帧 1052）。

工具改动（`scripts/jypreview/tools/export_match.py`）：偏移取"结构下界 + 在 ≥ 下界的候选里选扫描
最优"。头部重复只证明导出**至少**多持有了那么多帧，所以把结构值当**下界**而不是答案；本夹具最终
落在 **+3**。summary 新增 `alignment_offset_frames` / `export_head_padding_frames` /
`alignment_medians_by_offset` / `median_similarity_unaligned`，逐帧记录实际比对的 `export_frame`。
顺带修掉一个潜在故障：一次把上百个 `eq(n,X)` 相加会被 ffmpeg 表达式解析器直接拒绝，现在按 16 帧
一批解码（原来 `--offset-scan` 配大 `--frames` 就会踩）。

复测（12 帧、忽略首帧、对齐 +3，`temp/export-match-aligned3.json`；同会话两次逐帧一致）：

| 指标 | 对齐前（4j） | 对齐后 |
| --- | --- | --- |
| 全 12 帧 median | 0.8043 | **0.8479** |
| 干净帧（10 帧）median | 0.8135 | **0.8634** |
| 干净帧 min | 0.7343 | 0.8199 |
| 一阶统计对齐 median | 0.8442 | **0.9024** |
| 单帧最高 | 0.8406 | 0.9084 |
| 帧号身份不符 | 0 | 0 |

回归地板抬到 **0.86**，双向验证：地板 0.86 时 exit 0（`temp/export-match-floor-086.json`）、
地板 0.95 时 exit 1 且打印
`FAIL: playback at/above the clean-frame regression floor — … export head offset +3, median 0.84785`
（`temp/export-match-floor-095c.json`）。两次运行的 median 与偏移完全一致，说明对齐后的测量本身
也是可复现的。

**+3 不是渲染器早一帧或晚一帧**。在内层片段切点做逐帧变化量对照（`temp/cut_align.py`，日志
`temp/gate-logs/cut-align.log`）：项目帧 320 处我们跳 98.1、导出跳 116.2；帧 404 处 78.2 对 100.7
——**两侧在同一项目帧切开**，时间线结构是帧精确的，多出来的三帧属于导出头部的持有策略。
同一份日志还给出一个副产品：我们有些相邻帧完全相同（317/319/322 变化 0.0），导出同段却有 12–16
的逐帧变化，那是 H.264 编码噪声底。也就是说内容完全一致时对齐 RMSE 仍有 ~15 的地板
（≈0.94 similarity），残差里有一块永远来自编码而非渲染。

留档：偏移不是全程恒定的——低运动段（帧 813）的曲线在 −6..+6 上是平的，帧 256 在 0 处最像，
所以全局常数偏移是最优近似；要做净得按片段分别对齐，那是代价更高的事后拟合。另外帧 192 的占位
比例跨会话出现过 50.5% 与 95.8% 两个值（同一会话内两次运行完全一致），与 4g 记录的
`test_mlt_compiler` 非确定性同源；含占位帧本来就不进评价，不影响地板。

## 4m. 字幕这条线查清了：字号/位置没错，错在逐字配色与画面内运动

误差按高度十分位看（`temp/text_look.py`，全分辨率 1080x1920，对齐 +3）：帧 64 是
`[33.1, 28.6, 30.3, 29.2, 28.9, 26.2, 26.5, 55.0, 34.9, 57.3]`、帧 1339 在第 8 位 55.5，
而帧 1212 全程只有 13–24。底部两个十分位翻倍，第一反应是"字幕画错了"。逐条量下来不是：

- **字号与位置是对的**。用黄色像素反解字幕包围盒（`temp/text_bbox.py`）：帧 1212 我们
  `y 866-1594 x 410-1079`（670x729，质心 1230,744），导出 `y 866-1606 x 420-1079`
  （660x741，质心 1236,750）——差 1% 量级。所以"标题偏小/偏位"这条可以排除。
- **帧 1339 那行字幕是真的不一致，但原因在配色而不是几何**：模型里这条是 13 字、整条
  `#ffde00`（`runs.0.fill.css`），我们画满 873 px；导出同一行只有 236 px 是黄的。该
  `runs.0.use_letter_color = True`，也就是剪映开了**逐字配色**（配合 56 条
  `material_animations` 里的字幕动画做逐字显现/高亮），而我们把整条按单一颜色画。这条是
  内容级缺口，不是解析错误——`animation_unsupported` 那 28 条警告里就包含它。
- **帧 64 右下角的"黄色块"根本不是元素**：裁出来看是一只失焦的手挡在镜头前
  （`temp/inspect/text/corner-export-64.png`），属于源素材里的运动内容，我们取的那一帧手在别的
  位置。加上 4l 记的编码噪声底，这类"同一时刻画面里动的东西不一样"是残差的一部分。

结论：字幕渲染的几何与样式映射在这个夹具上是对的，剩下的字幕差异来自**逐字配色/字幕动画没有落地**
（需要按 `use_letter_color` + `material_animations` 的时间轴逐字上色），以及源素材内的运动与
导出后的编辑漂移（导出 16:26、`draft_content.json` 16:39）——后两者不是渲染器能追平的。

把这条线走到底再收：数了一下这份草稿的字幕动画（`material_animations` 按轨道与名字聚合）——
**26 条 text 入场动画，全部 0.5 s**，其中 `打字光标` 13 条（category `ruchang`），其余是
`缩小`×2、`亮字渐隐`×2、`向右模糊 II`、`向上露出`、`向下露出`、`渐显`、`放大`、`生长`、
`激光雕刻`、`星光闪闪` 各 1 条。26 × 0.5 s ≈ 13 s，占 51 s 时间线的四分之一，采样帧落进动画里的
概率不低。但两条硬约束记在这里，免得下一次再走一遍：

1. **`打字光标` 这类逐字显现没法落在现有 MLT 图上**：编译出来的是静态 producer，文本写死在 pango
   producer 上，逐字显现要么按帧改文本、要么把每个字拆成独立 clip 按帧入轨——是一层新功能，不是配
   参数。能表达的是整条效果（`渐显`/`放大`/`缩小`/`向上露出`/`向下露出`，共 7 条），它们可以用带
   关键帧的 opacity / affine geometry 滤镜落地。
2. **就算做了逐字显现也不保证对上**：帧 1339 那条 13 字字幕从 44.467 s 开始，我们比对的是 44.73 s
   （进度 0.53，线性预测约 6.8 字），导出实际只有约 3.5 字宽（236 px ÷ 每字约 67 px）。说明剪映的
   揭示曲线不是线性的，或时长不止 `material_animations` 里写的 0.5 s——要做准需要那个特效包
   （`User Data/Cache/effect/4011192/12196518b89652860631d196d19b6f45`）的语义，而它在模型里被
   明确标为不可预览。

下一步若还要动像素指标，优先级是：整条入场动画（7 条，关键帧滤镜可做）> `figure` 美颜形变 >
`clear`/`sharpen` 局部细节；逐字类动画与色调都已见底（4i/4j/4k/4m）。

## 4n. 连续播放这条：到的帧很准，但每 7 帧只到 1 帧

前面所有数字都来自 `/api/backend/seek` + `/api/backend/render`，那是"停帧"。目标说的是**播放**，
所以补了一次真流：`/api/backend/play` 之后读 `/api/backend/stream`（multipart，每帧一段带身份头），
从项目帧 440 起跑 40 段（`temp/playback_match.py`）：

- **到达的帧内容是对的**：442/449/456/463/470/477 对导出（+3 对齐）的相似度
  `0.9000 / 0.9056 / 0.9076 / 0.9075 / 0.9121 / 0.9200`，median **0.9076**，比定格采样的
  干净帧 median 0.8634 还高一档——这一段（14.7–15.9 s）画面与导出基本重合。
- **但播放丢帧**：交付的帧号是 439 → 442 → 449 → 456 → 463 → 470 → 477 → 484 → 491 …
  步进 7，40 段里 39 处 gap，也就是**每 7 个项目帧只有 1 帧送到客户端**（约 4.3 fps 的画面流）。
  流本身按挂钟推进，所以渲染跟不上时是"跳帧保持同步"，不是错序：帧号单调、身份头一致，
  没有回退也没有重复。
- 原因量出来了：1080x1920 一帧 PNG 在默认 `compress_level=6` 下要 **313 ms**，降到 level 1 是
  **182 ms**（无损，像素完全一致，只有体积 +5%）。已经把 `_encode_png` 改成 level 1
  （`scripts/jypreview/server/handlers_backend.py`），同一次播放里 440/441/442 三帧开始连续到达，
  gap 数 39 → 36，交付帧的 median 0.9076 → 0.9087。剩下的步进 7 属于 MLT 图本身
  （本机 ~0.35x 实时，见 `2026-10-12-mlt-runtime-rebuild-device2.md`）。
- **"给预览流一个比画布小的尺寸"这条路已实测否掉并回退**。临时给 stream 加了
  `?width=540&height=960`（PIL 降采样后再编码，功能可用）跑同一段：交付帧号序列与 gap 数
  **完全一样**（36 处，439/440/441/442/449/456…），median 0.9086 对 0.9087，降采样只亏 0.0001。
  说明每帧约 230 ms 的预算里编码与传输都不在关键路径上，卡的是 MLT 出帧速度。该参数因此没有留下，
  要抬交付率只能动图（线程数、滤镜链、按视口少合成几层），不是动 PNG。
- 门槛复跑（`temp/gate-logs/enc2-*.log`）：`test_backend_lifecycle` 0、`test_mlt_controller` 0、
  `test_mlt_acceptance` 9 节 PASS + 3 条 capture-evidence FAIL（缺真机采集证据，与本次改动无关）。
  夹具的像素 median 不需要重测：`compress_level` 是无损参数，PNG 解出来的字节完全一致。
  两条操作坑记在这里：① `run_gate.ps1 -UseFixtures` 会给 acceptance 塞 `--video/--audio`，而它不接
  这两个参数，argparse 直接 exit 2——那是**用法错误**不是门槛失败，跑 `test_mlt_acceptance`
  不要带 `-UseFixtures`；② 同一个服务会话里连跑两次播放流客户端，第二次会在建连后被重置
  （WinError 10054），一次一个进程就正常。
  踩坑记一笔：`run_gate.ps1 -UseFixtures` 会给 acceptance 塞 `--video/--audio`，而它不接这两个参数，
  于是 argparse 直接 exit 2——那是**用法错误**不是门槛失败，跑 acceptance 不要带 `-UseFixtures`。

所以"播放时匹配"要分两半记：**内容保真**已经到 0.90 量级（这一段），**时间保真**在这台机器上
还做不到 30 fps 全帧交付。之前所有 median 都是定格口径，不要把两者混为一谈。

## 5. 自包含打包件（防丢失）

`E:\fixtures\1012-1626-fixture\`：`draft/`（564 MB 副本）、`media/`（38 个引用素材 2.4 GB）、
`export/`（真实导出 + 封面）、`MANIFEST.json`（每个文件的原始位置、字节数、sha256）。
素材清单来自 `temp/fixture_media_index.py`（直接遍历解密后的内容，覆盖子草稿内联素材），
回捞逻辑在 `temp/recover_fast.py`，结果在 `temp/media-recovery.json`。

## 6. 收口状态（本轮停在这里）

已验证的事实，按目标三句话分：

1. **复制成测试夹具**：草稿副本 `D:\JianyingPro\JianyingPro Drafts\1012-1626-fixture`
   （did `1e9cd2a6f0b06c04`，时间线 `44BA0A70…`），自包含包 `E:\fixtures\1012-1626-fixture\`
   （draft/ + media/ 38 个素材 + export/ + sha256 MANIFEST）。两份都在盘上；原始
   `10月12日` 已从语料消失，所以这两份是唯一副本，按只读处理。两者都不进 git。
2. **正确识别**：全绿且可复跑 —— `draft fixture intact`（sha256 对表）、`draft recognized`
   （did/name/layout=hybrid/encoding=jianying-dll）、`model IR resolves the fixture`
   （media_missing=0）、`canvas matches export`（1080x1920）、`fps matches export`（30/1）、
   `head aligns, tail tolerated`（导出多 3.31 帧）、`rendered_frame_header_mismatches = 0`。
3. **播放时匹配（忽略首帧）**：分两半，都还达不到"像素一致"。
   - 定格口径（`export_match` 12 帧、+3 头部偏移对齐）：全帧 median 0.8479，干净帧 median
     **0.8634**、min 0.8199，一阶统计对齐 0.9024，单帧最高 0.9084；地板
     `--min-clean-similarity 0.86` 双向验证（0.86→exit 0，0.95→exit 1）。
   - 播放口径（`/api/backend/stream` 连续取帧）：到达帧 median **0.9087**，但每 7 个项目帧
     只到 1 帧；已实测这既不是 PNG 编码也不是帧尺寸的问题（level 1 已改，尺寸方案已回退），
     是 MLT 出帧速度。
     → 2026-10-14 后续：串行 sink + PNG level 1 之后 gap 已经是 0，改为 `open?longest=960`
     按预览尺寸编译整张图后交付 4.08 → 4.94 fps，到达帧 median 0.9079；帧率与内存的账见
     `2026-10-14-playback-items.md` §4（同一轮把视频原声修回来了，open 内存 11.2 → 13.59 GB）。

门槛：`test_timeline_model` / `test_mlt_controller` / `test_mlt_compiler` / `test_mlt_runtime` /
`test_backend_lifecycle` 全 0；`test_mlt_acceptance` 9 节 PASS + 3 条 capture-evidence FAIL
（缺真机采集证据，与本轮改动无关）。

收口前又跑了一次完整定格测量（`temp/export-match-final-check.json`，含 `--min-clean-similarity 0.86`
→ exit 0），逐项与 PNG 编码改动之前的 `temp/export-match-aligned3.json` 对比：偏移、全帧 median、
干净帧 median/min、干净帧数、一阶对齐、单帧最高、帧号身份不符**八项全部逐字相同**——
"`compress_level` 无损"这句从断言变成了实测。

没有做完的、按期望收益排序的下一步：

1. **整条入场动画**（26 条 text 入场里的 7 条：`渐显`/`放大`/`缩小`/`向上露出`/`向下露出`）——
   用带关键帧的 opacity / affine geometry 落地，是唯一还能靠"补功能"拿分且语义确定的项；
   `打字光标` 那 13 条需要特效包语义，模型里标为不可预览，别从它开始。
2. **抬播放交付率**：只能动图（线程数、按视口少合成几层、或播放期降分辨率渲染），
   预期把 1/7 提到 1/3 以上；先量 `pull_frame` 的单帧耗时再改。
3. **`figure` 美颜形变**（64 条）与 `clear`/`sharpen` 局部细节：收益真实但工作量大。
4. 帧 192/702 的占位不可恢复：3 个 `material_id` 在整份草稿里没有定义（导出后编辑漂移造成），
   `placeholder_infos` 不含路径线索；含占位帧本就不进评价。

工作区状态：6 个文件修改 + 3 个新文件，**全部未提交**（按用户"先不要提交"）。

## 7. 复跑

回归门槛（含地板判定与占位归因）：

```powershell
PYTHONPATH=scripts py -3.14 -m jypreview.tools.export_match `
  --frames 12 --attribute --min-clean-similarity 0.86 --json temp/export-match-aligned3.json
```


```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\server.ps1 -Action start
PYTHONPATH=scripts py -3.14 -m jypreview.tools.export_match --frames 24 --offset-scan --offset-window 4
PYTHONPATH=scripts py -3.14 temp\diag_compile.py      # 逐层 placeholder 与 MediaRef 现状
powershell -NoProfile -ExecutionPolicy Bypass -File temp\mlt-build\server.ps1 -Action stop
```

证据：`temp/export-match.json`（逐帧相似度与偏移曲线）、`temp/inspect/render-200.png` vs
`temp/inspect/export-200.png`、`temp/diag_compile.py` 输出。
