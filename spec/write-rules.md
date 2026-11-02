# 写回不变式（M3 自研事务层照此实现）

本项目自己实现写回，**不复制** `jianying-editor-skill` 的代码，也不在运行时 import 它。
本节是规格：实现必须满足这些不变式；`../evidence/findings.md` 的实测证据支撑其中标 verified 的条目。
M1 全程只读，本文件不落地代码。

## 0. 前置：只读期结束的条件

M1 结束前不得写任何草稿字节。写回开发开始前必须已成立：
- crypto 三门禁通过（等长 + 语义回环 + 外部对照，见 `crypto.md` 第 5 节）；
- 目标草稿的读写前 sha256 快照机制可用；
- 回滚路径实测可用（故意制造失败，验证能恢复到逐字节原状）。

## 1. 选址：先发现副本，再决定写谁

1. 由 `layout.yaml` 判别布局（legacy / hybrid / draft_info_only / no_content）。
2. 活动时间线由 `Timelines/project.json` 的 `main_timeline_id` 决定，过滤 `is_marked_delete`。
3. **副本集合必须解码后按 content-id 推导**：逐个候选文件解密，比较其顶层 `id` 是否等于目标 timeline id。候选名只是入口，不是身份。**判据要分清两个方向**：重加密是等长的（F-003：`等长但摘要不同`），所以「长度不同」确实说明内容不同（实测 348,948 vs 349,060），但「等长而摘要不同」**不能**当作分叉证据 —— 那可能只是熵填充差异，必须解密后比 content-id 与解码内容（F-025）。候选名还应包含 `draft_content.json.bak` 与 `template*.tmp`（语料实测 `.bak` 2,803 个、`template-2.tmp` 2,888 个、`template.tmp` 1,800 个，扫描器一律不解析它们，所以「内容文件数」是下界）。
4. 根镜像（r3：**349 个**镜像文件，其中 **191 份**内容只存在于根镜像；旧稿的 698 是 r1 翻倍口径）是否与时间线副本一起写，需按目标一致性显式决定并记录。

## 2. 事务（任一环节失败 → 全量回滚）

```
1) 预检   : probe 目标；记录每个待写文件的 sha256 + 解码后的 content-id + duration + 轨道/片段计数（指纹）
2) 门禁   : 加密目标必须先通过 crypto.md 第 5 节三条门禁
3) 快照   : 把**全部**待写文件复制到 temp/ 内带时间戳的快照目录，写 sha256 清单（快照不进草稿目录）
4) 变更   : 只在内存中的归一化模型上做；序列化不得新增读时才补的默认键（如 timerange.start）
5) 结构校验: 引用完整性（material_id / extra_material_refs 全部可解析）、id 唯一、轨道无重叠、duration 一致
6) 原子写 : 同目录 mkstemp → 写 → flush+fsync → os.replace；每个目标独立原子
7) 回读   : 每个副本重新解码，做**语义**比对（不是字节比对）；明文目标做结构等价比较
8) 复验   : 再跑一次第 5 步校验；失败即回滚
9) 回滚   : 从快照逐文件原子恢复；快照缺失的新生成文件删除；回滚后再次 sha256 确认
```

- 多副本写入之间存在进程被硬杀的时间窗（可能留下混合状态）。缓解：先写非活动副本、最后写活动副本，并把「已写清单」落盘，重启后可据此判定并修复。
- `os.replace` 是同目录原子操作；**禁止**跨目录移动或先删后写。
- **快照范围（2026-10-18 实测，F-028）**：一次「打开→改→保存」在副本草稿里改写了 **15 个文件**、新增 **24 个**（其余 287 个逐字节不变）。改写的 = `draft_content.json` 与 `.bak`、`template.tmp`/`template-2.tmp`（根 + 时间线双份）、`draft.extra`（根 + 时间线）、`draft_meta_info.json`、`draft_settings`、`draft_biz_config.json`、`agent_adoption_ledger.db`、`deepagent/deepagent.db`、`.backup/timeline_backup_manifest.json`。所以「只快照 `draft_content.json`」不足以整目录还原；事务快照必须覆盖**整个草稿目录**，或至少是上面这张清单。

## 3. 内容不变式

| 规则 | 依据 |
|---|---|
| 时间为微秒整数；`target = source / speed` | verified |
| 缺失的 `timerange.start` 读时当 0，**写回时不得新增该键** | verified |
| 顶层 `duration` 必须等于最大片段结束时间；超限报错、不等告警 | single |
| 同轨片段不得重叠（除非显式允许） | single |
| ID 用 `str(uuid.uuid4()).upper()`；常规保存不改动既有 ID | verified |
| 克隆时间线只生成一个新 ID，并做整值精确匹配递归替换；**禁止全局文本替换** | single |
| 文本 `content` 是 JSON 字符串；改动文本长度后必须重新同步 `styles[].range` | single |
| 不得把 `content.text` 与过期 `recognize_text` 拼接 | single |
| 音频 material 的 `type` 取值是 **`sound` / `video_original_sound` / `music` / `text_to_audio` / `extract_music`**（实测条目 7,069 / 3,062 / 1,302 / 1,143 / 166）⇒ 新增音效写 `sound`、新增配乐才写 `music`、配音写 `text_to_audio`；**`audio` 是轨道类型名，从来不是 material type 值** | verified（F-048 全量实测 `tables/material_type_enums.csv`；旧行「必须是 music 而非 audio」是单样本外推，已作废） |
| **不按 `track.type` 分派字段表或语义类型**：片段的语义由 `material_id` 指向的 bucket 及其 `type` 决定，而 `texts.subtitle` 有 564 次是被 **mixed 轨**引用的（字幕不必在 text 轨上）⇒ 写字幕、写贴纸、写特效时先定位 bucket，再决定写哪条轨 | verified（F-048 `tables/track_material_map.csv`） |
| **不得按「本类型通常有」补键**：同一种轨道里 8~15 键最小形与 45 键完整形并存（全语料只有一种 45 键形、6,004 段），缺键是合法状态不是损坏；新增片段应复制**同类型的最小形**，不要复制完整形（完整形带 8 个音频/歌词族与占位键，剪映自己也是按版本写的） | verified（F-048 `tables/segment_shapes.csv`） |
| **主轨 = `tracks[0]`，但插入会联动副轨**：内置协议明确「往主轨开头插入 video/image，底层 apply 会把副轨片段整体后移」。我们写回时不存在「应用帮忙后移」，**必须自己显式重算副轨所有片段的 `target_timerange`**，否则与剪映语义不一致 | verified 现象（F-047/F-048）/ open 影响面（与 U-45 同批差分） |
| **复合片段写入要同时动两处**：`materials.drafts[]`（区分 `type` = `combination` 4,657 / `composition` 439）与 `<draft>/draft_virtual_store.json` 的父子索引（`child_id`/`parent_id`）；后者此前不在规格里，属**目录快照必须覆盖**的文件 | verified 存在性与形状（F-047）/ open 写入侧（M3 实验） |
| **`platform` 与版本 stamp 默认不动**：桌面剪映写 `version=360000` + `platform{os:windows, app_id:3704, app_source:lv}`，内置 agent 写 `400000` + `{os:web, app_id:348188, app_version:"15.4.0"}` 且不动 `new_version`；跟哪一边、应用读回会不会重写都未判（U-60）⇒ **只搬运原值，不改写、不规范化** | verified 两套值实测 / open 该用哪套（U-60） |
| `local_material_id` 为空需回填，否则 5.9+ 报素材丢失 | single |
| 新建 segment 必须补齐辅助 material stub（见 `materials.yaml` 的 `stub_requirements`）——注意这条说的是**bucket 里的配套条目**，不是 segment 自身的键；segment 的键按下条「不得按类型补键」处理 | single |
| 不写 `deepagent/`、`subdraft/`、`Resources/`、`matting/`、`adjust_mask/`、`common_attachment/`、`.backup/`、`*.db`、`crypto_key_store.dat*` | verified（目录存在性实测） |
| `is_minimal_draft` 草稿没有 `tracks` 键；新增内容时才创建该结构 | verified |
| **派生缓存三式**：`speeds[].speed == segment.speed`；`uniform_scale.value == clip.scale.x / clip.scale.y`（仅等比开着时维护，关掉后 `value` 停在 1.0）；`shadow_point` 的模 == 0.18×distance、方向 == (cos,sin)(angle)。写回时**要么同步、要么整键删除**，渲染只读源字段 | verified（F-023 + 2026-10-18 差分 F-027） |
| **字号以 `styles[].size` 为权威**（1:1 无换算）；`texts.font_size` 只是镜像：该键**可以合法缺席**（语料 4.8%，新建 11.6 字幕即此类），多段样式时它只能等于其中一段（97.2% 是 `styles[0]`）→ **不得为了「补齐」而给没有该键的字幕新增 font_size，也不得反过来用 font_size 覆盖分段字号** | verified（F-027 换算 + F-034 载体） |
| **`styles[].range` 按 UTF-16 code unit 计数**：改文本长度时按 UTF-16 重算，emoji 占 2 | verified（F-027，结案 U-01） |
| **单帧关键帧骨架**：片段可带「每属性一条、`keyframe_list` 长度 1」的骨架轨道，其帧值与标量字段同步变化；改 `clip.scale` 一类标量时必须一并改对应 `KFTypeScaleX/Y…` 的帧值，否则与剪映不一致。轨道的创建/删除时机未定（等比关闭会**新建** `KFTypeScaleY`、开回来会**删除**它） | verified 现象 / open 语义（F-027、U-45） |
| **画面描边/文字发光走资源包**：参数在 `color` + `adjust_params[]`（`effects_adjust_size`/`effects_adjust_alpha` = UI÷100，每项带 `default_value`），类型选择 = 不同 `resource_id`，**没有枚举字段可写**；只改开关不选类型时参数键**整键缺席** | verified（F-027，结案 U-39） |
| **字幕版面位置只由 `texts.alignment` 承载**（单字段互斥枚举，不可拆 x/y 两轴），`clip.transform` 不随之改变；「居中」有**两种落盘编码**——老写入器（≤8.0）写 `1`、新写入器（≥8.7）删键。读时两者都按居中处理，**写回时不得把 `1` 规范化成删键**（那会改变老版本读到的值），也不得给居中态补写 `1` | verified（F-027/F-031） |
| **位置写入按当前 `canvas_config` 的对应边长归一**：`x = 面板px/width`、`y = -面板px/height`（**面板 px 与画布 px 差 2 倍，且 y 轴向上**，F-035；渲染一律用 `值 × 边长 / 2`），读回显示值必须 `round(value × 边长)`（`.5` 实测进位：`-637.5` 显示 `-638`）；**改画幅不会重写已存浮点**（1080x1440 草稿里 46.35% 的 y 仍只在 ×1920 时整数），所以跨画幅草稿不能假设整数性仍成立，也不要把面板显示的整数当存回值（**已观测**：把 16:9 面板上的 178 原样键回，剪映自己还原成 ≈177.7778/1920，不是 178/1920 → 未经用户真改的 `transform` 必须**原样搬运**，不得做 px 往返）。**`canvas_config` 按时间线各写各的**（同一草稿可混画幅，根镜像只代表 `main_timeline_id`），写回前必须取目标时间线的画幅，不能取草稿级 | verified（F-032/F-033） |
| **不得展开或改写 `##_draftpath_placeholder_<uuid>_##/`**：展开结果 = 草稿自身目录，uuid 身份未知（U-41），跨机复制草稿时必须整串原样搬运 | verified 现象 / open 身份 |
| **官方 draft 模型层的默认值不等于桌面写入缺省，禁止按 `tables/js_model_keys.csv` 回填**：文本 material 的 `check_flag` 模型默认 **63**，而 r3 语料众数是 **39**（11,180 次）、63 只 87 次；`alignment` 模型默认 **1**，而 11.6 桌面写入是**整键缺席**（U-30）。这层属于 canvas_agent（web 面，`version=400000 / os="web"` 那一套身份，F-047），正确用法只是**字段合法性与命名的白名单** single（F-049；两处反例是语料实测）|
| **协议层的 `no-support` 不等于格式层的不存在**：`references/no-support.md:9-20` 把 `keyframe`/`keyframes`/`motiongraph_effect`/MotionGraph 四件、人声分离、人声美化列为 agent 不支持写入，而 r3 语料里带 `common_keyframes` 键的 segment 有 **17,411** 个（非空 836）。所以这些条目只能当**「我们的写回面不要生成它们」**的约束，不能当成「草稿里不该有这些键」，更不得据此删除语料里已有的关键帧数据 verified（F-049，协议声明 + 语料对账）|
| **混合模式必须按资源索引直连，且不许 join `nameId`**：草稿 `effects[type=="mix_mode"]` 的 `resource_id`/`effect_id`/`path` 尾段 md5 三个键都能对上 `Resources/MixMode/MixMode.json`（r3 全量 166/166 命中、0 未匹配）；而该索引的 `nameId` 会把滤色包标成 `color_filter`（C-013）。另外协议枚举 12 个模式、本机只有 10 个包 ⇒ 遇到 **差值 / 颜色滤镜** 必须显式提示降级，不许静默按 normal 渲 verified（F-049）|
| **`tracks[].flag` 按官方枚举写，且 0 与缺席等价**（U-61 结案，F-050）：`FlagNone=0 / FlagTextSubtitle=1 / FlagSubVideo=2 / FlagTextLyric=3 / FlagVideoSubtitle=4 / FlagAudioSubtitle=5 / FlagAiScriptSubtitle=6`。新建一条 **非首条** video 轨必须写 `flag=2`（r3 里非首条 video 轨 1,662/1,662 都是 2）；**不得**给首条 video 轨写 2（首条 1,533 条里 0 条是 2，只有 0 或整键缺席）。新建字幕轨写 `flag=1`（971/1,004 装 subtitle 素材）。**禁止**为了「补齐」把缺席的轨写成 `flag:0`，也**禁止**主动生成 4/5/6（桌面语料零出现，属 agent/云侧识别产物） | verified（枚举出自前端 chunk，语义出自全量交叉表，两路一致）|
| **`mixed` 不是一类，按 `flag` 再分一次**（F-050，U-62）：`flag` 缺席的 mixed 实质是另一种视频轨（298/315 纯装 `videos.video`、零文字），`flag==2` 的才是真混装容器。写回时不要把它们当同一类处理，也不要把 `flag` 缺席的那批「规范化」成 video 轨——`track.type` 本身是权威落盘值 | verified（内容构成 × flag 交叉表）|
| **改 `render_index` 必须同步 clip 的层级两处**：贴纸/文字模板落地时同一个值还会写进 `clip.filter.filterLayer` 与 `clip.layer`（均为 `BigInt(renderIndex)`），只改片段索引就是静默不一致（F-052）| verified（JS 原文）|
| **不要开启 `free_render_index_mode_on`**：桌面语料 2,050 份里**从不为真**（缺席 1,402 / false 648 / true 0），打开它会把分配基座换成 video 2000 / adjust 7000 / videoEffect 11000 / text&sticker 14000+count+2，造出桌面不会产生的值；读侧要认得这套基座但不写（F-052）。另注意它与 `render_index_track_mode_on` 是两个不同的根键 | verified |
| **不要把 `mixed` 改名成 `composition`**：`mixed` 不在厂商 `TrackType` 的 13 个 wire 值里、只存在于 11.1.0~11.4.2 的草稿中，11.6 侧最可能是 `composition` 但同一性未被任何一侧证明（F-052）| open 同一性 |
| **容忍应用自己的归一化写入**（不是我们的改动，别当回归）：`type:""` → `"none"`；`Cache/effect/<rid>/<md5>` → `Cache/artistEffect/<rid>/<md5>`（同一资源换缓存根，rid/md5 不变）；浮点末位 ULP 漂移（`-12.328813552856445` → `…444`）；`extra_material_refs` 字符串数组**顺序轮换**；UI 整数值不保证落成整浮点（200% → `1.9999999999999998`） | verified（F-027，同一份内容只改一处时的剩余差异） |

## 4. 并发与「剪映开着」

- 写前重新计算指纹并与第 1 步记录比较；不一致说明应用或其他工具中途改过 → **停止并上报**，绝不覆盖。
- 检测到 `JianyingPro.exe` 运行只告警、不阻断（用户可在工作时要求写入），但必须：先做完整快照、写后立即回读校验、给出明确的「若剪映随后保存会覆盖本次改动」提示。
- **草稿级信号 `.locked`**：实测该文件在草稿于剪映里**打开期间**存在于草稿根目录，**关闭时间线时被删除**（同时 `.backup/` 写 3 份 `.close.bak`，内容零变化，F-028/U-46）。它是比进程存在性更精确的门禁：`.locked` 在 → 该草稿正被编辑，写入几乎必然被应用随后的自动保存覆盖 → 默认拒绝、要求用户显式批准；`.locked` 不在 → 仍要跑指纹复验（不能反推「一定没人开着」）。「`.locked` 在时我们写盘会怎样」仍是 open，必须在副本草稿上做受控实验（U-46 写入侧）。
- `.backup/` 不是备份目录而是**事件流水**：`<YYYYMMDDHHMMSS>_<hash>.<load|save|close>.bak`，每个事件同时写 3 个镜像位置（`./.backup/`、`./.backup/<timeline_id>/`、`./.backup/projectBackUp/`）。它会单调增长，**不得**当作回滚来源，也不得由我们写入。
- 剪映可能在任意时刻回写草稿（尤其自动保存），因此快照是唯一可靠的事后恢复手段；快照目录不清理、不进 git。

## 5. 校验命令（自研，供 M3 与 M2 复用）

`scripts/validate_draft.py <draft> [--timeline active|<id>] [--json]` 至少检查：

1. 布局判别与活动时间线定位；
2. 每个副本可解码且 content-id 匹配；
3. 引用完整性（material_id / extra_material_refs 全部命中）；
4. 轨道重叠与 duration 一致性；
5. 文本 `content` 可解析、`styles[].range` 与文本长度自洽；
6. 输出 `ok / errors / warnings / replicas_checked / fingerprint`。

外部对照（非依赖）：`jianying-editor-skill` 的 `validate` 子命令可作第二意见；两者结论冲突时以本机草稿实测与剪映能否正常打开为准。

最终验收：写入后的草稿必须能被剪映正常打开、时间线可见、**不出现修复/重建提示**。
