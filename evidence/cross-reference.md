# 与 jianying-editor-skill 的覆盖对比（可复现）

复现命令：

```bash
python scripts/corpus_presets.py           # 采集预设身份（resource_id/effect_id/md5/时长/是否本机存在）
python scripts/crossref_editor_skill.py    # 双向对比：字段覆盖 + 目录匹配 + 包定位探针
python scripts/crossref_editor_skill.py --json
```

对比对象：`jianying-editor-skill`（MIT，上游 luoluoluo22，本机 fork `1.7.0+crypto-ops.1`）
其文本 **136 个文件 / 1.87 MB**，其中 **1.20 MB** 是 vendored `pyJianYingDraft/metadata/`（Apache-2.0，17 个文件、解析出 **2650** 条目录项）。
**只读解析其源码文本作为数据，不 import、不复制其代码或表数据入库。**

## 1. 字段清点覆盖（我们 vs 他们提及）

| 类别 | 我们清点 | 他们提及 | 覆盖率 |
|---|---|---|---|
| `styles[]` 键 | 15 | 14 | 93% |
| material bucket | 39 | 34 | 87% |
| 顶层键 | 40 | 33 | 82% |
| segment 字段 | 52 | 32 | 62% |
| 关键帧 `property_type` | 51 | 20 | 39% |
| bucket 内键名 | 417 | 121 | 29% |

他们**全库零命中**的概念（12 个）：`mix_mode`、`common_mask`、`responsive_layout`、`is_minimal_draft`、
`animation_duration`、`TextAnim`、`useLetterColor`、`thickness_projection_angle`、`contour_path`、
`crypto_key_store`、`ShaderData`、`BlendPreMul`。
→ M1 最有价值的两条结论（混合模式是 `effects.type=mix_mode` + 预乘 GLSL；动画曲线是预设包内明文 Lua）**在其体系内不存在**，无法交叉验证，只能靠剪映自带资源包与成片。

## 2. 资源目录覆盖（他们 vs 我们语料实测）

| 我们的 bucket | 他们目录条目 | 我们观测 distinct resource_id | id 命中 | 名称命中 |
|---|---|---|---|---|
| `material_animations` | 737 | 369 | **74%** | 82% |
| `transitions` | 433 | 192 | **74%** | 75% |
| `effects` | 672 | 694 | 4% | 9% |
| `stickers` | **0（无目录）** | 372 | 0% | 0% |
| `text_templates` | **0（无目录）** | 327 | 0% | 0% |
| `common_mask` | 6（`mask_meta.py`） | 13 | 31% | 62% |
| `masks` | 6 | 4 | 100% | 100% |

目录分布：`font_meta` 796、`filter_meta` 483、`transition_meta` 433、`video_intro` 155、`text_intro` 145、
`video_outro` 124、`video_group_animation` 123、`video_scene_effect` 112 …

解读：

- **动画与转场是他们的强项**：目录条目带 `name / resource_id / effect_id / md5 / 默认时长 / is_overlap`，
  正好补我们缺的「全集 + 默认时长 + 是否重叠」。语料里真实出现的动画与转场，四分之三能在其目录中定位。
- `effects` 只有 4% —— 因为我们的 `effects` bucket 是异构的（r3 实测 **33 种** `type`（r1 记 22，未闭合）：`figure` 36,621、
  `mix_mode` 166、`text_effect` 3,016、`lut` 98…，均为 2050 份去重内容口径。**注意**：33 种里 6 种（`bloom/color_dehaze/backlight_correction/restore_detail/color_levels/color_soften`）各只出现 1 次，且全部由 10月16日 那份「尽量打开所有样式」草稿单独带入 —— 排除它只剩 27 种，见 U-40 与 F-020），而他们的目录只覆盖场景/人物/滤镜/音色族。混合模式那 10 个
  根本不在其目录里（`滤色/正片叠底/变亮/变暗` 全库 0 次）。
- **贴纸与文字模板他们完全没有目录**（0 条），而我们观测到 372 / 327 个 resource_id —— 这块只能自己采。
- `mask_meta.py` 只有 6 条（`圆形/爱心/镜面/钢笔…` 一类），但他们的文档完全没有 `common_mask` 字段知识，
  所以「有目录、无格式」。

## 3. 预设包定位探针（新能力，来自这次对比）

用他们的 `(resource_id, md5)` 去本机 `Cache/effect/<resource_id>/<md5>` 与 `Cache/artistEffect/...` 找实体包：

| 目录文件 | 抽样 | 本机存在 |
|---|---|---|
| `text_intro` | 25 | **12** |
| `video_intro` | 25 | 2 |
| `transition_meta` | 25 | 1 |
| 其余 11 个文件 | 25 各 | 0 |

结论：**`md5` 就是预设包目录名**（实测例：`左移弹动` 的 `7313890082040058406/c21d4019453137cd76e0d847d5d8af96`
与其目录记录逐字一致）。因此即使草稿里的 `path` 指向旧安装位置或已失效，也能用
`resource_id + md5` 重新定位本机缓存 —— 这补上了 `spec/animations.yaml` 的解析回退链。

但**缓存才是瓶颈**，不是定位法：全语料 126,225 条可定位预设中，本机实际存在的包只有 **46,233 个（36.6%）**（口径：`scripts/corpus_presets.py` 的一次性清点，含嵌套草稿，未随 r2/r3 重跑，只作数量级参考）。
→ 渲染器必须把「按名近似」当常规路径而非异常路径来设计（约 2/3 的预设引用拿不到原始 Lua/GLSL）。

## 4. 采纳与不采纳

| 动作 | 决定 |
|---|---|
| 把他们的动画/转场目录作为 **ID↔名称↔默认时长↔md5** 的交叉校验源 | 采纳（分析期使用，Apache-2.0 需署名，数据不复制入库） |
| 用它校验我们 369 个动画 id + 192 个转场 id | 采纳（当前 74% 命中；未命中项如 `撕裂分割/宫格归位/模糊入场2/羽化/变速推近/电光/数字矩阵` 是其目录滞后于剪映新版本所致） |
| 把它当写回时的合法值域白名单 | 暂不采纳（目录滞后 26%，会误杀新预设） |
| 用它替代 `effects` / `stickers` / `text_templates` 的目录 | 不可行（他们分别为 4% / 0 / 0 覆盖） |
| 从他们的文档找混合模式或 `common_mask` 字段语义 | 不可行（零命中），继续走剪映资源包 + 成片 |

## 5. 已回补给 jianying-editor-skill 的内容

本仓库净新增、而对方全库零命中的字段知识，已写成一份可直接合并的独立文档：

- 位置：`<HOME>\.agents\skills\jianying-editor-skill\references\draft-field-observations.md`（181 行，未跟踪）
- 内容：12 项零命中概念的实测形状——`mix_mode` 及其预乘 GLSL、`common_mask`/`masks` 两 bucket 与 6 种具名形状、
  关键帧记录与控制点形状及真实 `curveType` 集合、`responsive_layout` 死默认、`extra_material_refs` 组成表与
  **10 个悬挂引用**（据此建议把引用完整性从错误降为 warning）、`is_minimal_draft` 无 `tracks`、
  转场 `duration`/`is_overlap` 实状、`video_shadows`、路径级 DLL API 对草稿无效、重加密等长不等值、
  vendored 目录表 74%/0% 覆盖率实测，外加「我们也不知道的」清单与逐文件修订建议表。
- 状态：**未提交**。原因：该仓库此刻有 12 个文件正被另一会话修改，其 `CONTRIBUTING.md` 要求 feature branch
  且 `main` 保持可发布；`references/README.md` 实为 vendored 上游 pyJianYingDraft 的 README，不能往里塞索引行。
  待对方工作树干净时在 feature 分支上提交，并可选地在 `SKILL.md` 的 references 段落加一条引用。
