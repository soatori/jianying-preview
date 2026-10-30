# 原生只读静态收割日志（PE 结构面）

前置授权见 [scope.md §1.1](scope.md)（2026-10-21 用户扩面：**只读静态、仅限结构与格式取证**；算法还原、
改造 DLL、动态调试、分发仍在禁止面）。工具与目标哈希见 [toolchain.md](toolchain.md)。
本文件记「二进制自己携带了什么结构」，不记算法。**全程未加载、未执行、未修改目标文件**。

通道脚本：`scripts/pe_harvest.py`（标准库，mmap 只读）。产物落 `temp/rea-native/`（不入库）。
命名说明：本文件用自身编号，**不占用 `findings.md` 的 F 号段**——本轮写作时 `findings.md` 与
`unresolved.md` 正被另一会话改（已 F-053），合并时再统一分号，避免历史上 U-21/22/23 那种撞号。

## 目标身份

| 项 | 值 |
|---|---|
| 文件 | `<JY_INSTALL>\11.6.0.14552\videoeditor.dll` |
| 大小 | 72,547,608 B |
| sha256 | `8cfcbb612ccd946df974428977b1902736c1de0ae561e20c26cbd4ea86099cb1` |
| 核验方式 | `certutil -hashfile` 实测，与 `toolchain.md` 既有记录逐字节一致 |

## N-01 段布局（可行性判据）

- **Evidence**：`pe_harvest.py` 读 PE 头。`image_base=0x180000000`，`SizeOfImage=72,601,600`。

  | 段 | VA | 体积 | 属性 |
  |---|---|---|---|
  | `.text` | `0x1000` | 50,742,283 | 可执行、非可写 |
  | `.rdata` | `0x3066000` | 16,575,162 | 只读初始化数据 |
  | `.data` | `0x4035000` | 3,681,428 | 可写初始化数据 |
  | `.pdata` | `0x43b8000` | 1,189,308 | 异常/展开表 |
  | `.rsrc` | `0x44db000` | 480 | 资源（几乎为空） |
  | `.reloc` | `0x44dc000` | 395,748 | 重定位 |

- **Finding**：代码段 **50.7 MB**，且 `.rsrc` 只有 480 B。⇒ ①「靠资源段拿协议文档/内嵌 schema」这条路不存在，
  结构信息只在代码与数据里；②Ghidra 的默认 auto-analysis 要覆盖 50.7 MB x64 代码，
  这不是「等一等」的量级，必须先设预算再单次判定（见 N-06 的前置条件）。
- **Path**：`temp/rea-native/harvest-report.json -> sections`。

## N-02 语料键 × 程序字面量交叉比对

- **Evidence**：`.rdata` + `.data` 中形如 `^[a-z][a-z0-9_]{1,31}$`（词边界）的去重字面量 **20,470** 个，
  与 `temp/corpus-scan/stats.json` 的四组键表比对：

  | 键组 | 语料键数 | 作为字面量出现在二进制 | 缺席 |
  |---|---|---|---|
  | `top_level_keys` | 40 | 39 | `business_info` |
  | `track_field_keys` | 8 | 8 | — |
  | `segment_keys` | 8 | 8 | — |
  | `bucket_keys` | 42 | 42 | — |

- **Finding**：**草稿 JSON 的字段名是这块 DLL 自己的字面量**，所以按 scope §6.1 的分工，
  「字段叫什么名、哪些值合法」这一类问题，11.6 桌面二进制是权威源（此前该权威只有 `Resources/canvas_agent` 的
  agent 面和语料）。唯一缺席的 `business_info` 按 §6.1 第 3 条记为**结论而非语料错误**：
  「11.6 桌面 videoeditor 不以字面量形式写这个键」，它由别的写入者产生（待查，见 N-07）。
- **Path**：`temp/rea-native/literals.json`、`temp/rea-native/cross-check.json`、`scripts/pe_harvest.py::cross_check`。
- **证据等级**：**单源待验证**。**弱见证声明**：`id`/`name`/`type`/`text`/`video` 这类 ≤5 字符短键
  作为独立字面量命中，证据力低（到处都会出现）；强见证是长键
  （`uneven_animation_template_info`、`auto_sort_affected_tracks`、`render_index_track_mode_on`）。
  98 个键里长键占多数，但**不要把 97/98 当成逐键等权**。

## N-03 框架分层（MSVC mangled 类型名清点）

- **Evidence**：`.data` 中 `.?A` 前缀的 mangled 类型名去重 **34,703** 个，按最外层命名空间计数（取前 12）：

  `std` 18,653 / 无命名空间 `global` 9,530 / **`lyra` 3,930** / **`lvve` 1,957** / `CryptoPP` 213 /
  `clipflow` 129 / `vesdk` 129 / `anonymous` 79 / `Concurrency` 23 / `lyra_cli` 19 / **`draft_store` 18** / `nlohmann` 11

- **Finding**：模块分层清楚了——`lyra` 是编辑器主域，`lvve` 是草稿/加密层（**我们黑盒调的
  `EncryptUtils@lvve` 就在这一层**），`draft_store` 是草稿持久化，序列化用 `nlohmann::json`，
  密码学库链接了 Crypto++（**仅记录该库存在，未做任何算法还原，§3 第 1 条边界**）。
  含 draft/material/segment/track/json 关键词的类型 4,910 个。
- **Path**：`temp/rea-native/rtti.json -> names`（全量清单）、`harvest-report.json -> rti.outermost_namespaces`。

## N-04 操作词汇表：`reqMakerImpl<Req,Resp>`

- **Evidence**：`lyra::reqMakerImpl<UAddTextToVideoMaterialReqStruct, UAddTextToVideoMaterialRespStruct>`
  这一族模板实例成批出现，同批可见 `AudioUpdateMaterial`、`AutoRemoveMaterials`、`ClipTextToVideoMaterial`、
  `CombineSegment`、`CommonMoveSegment`、`CommonRemoveSegment`、`CommonSplitSegment`、
  `CloudDraftCompatibilityDetect` 等 `…ReqStruct/…RespStruct` 对。
- **Finding**：桌面端把每个草稿操作都按「请求结构 + 响应结构」成对命名，
  这是一份**操作词汇表**。对本项目的 M3（写草稿）面，它比语料推断强：操作是否合法、名字叫什么，二进制自己说了。
- **Path**：`temp/rea-native/rtti.json`（grep `reqMakerImpl`）。

## N-05 `const char*` 字段名表（反射表）

- **Evidence**：在 `.rdata`/`.data` 扫「连续 ≥5 个 8 字节槽、每槽是指向标识符形字符串的 in-image 指针」，
  命中 **24** 张表。最宽的几张：

  | RVA | 字段数 | 内容摘要 |
  |---|---|---|
  | `0x333dba8` | 23 | `tracks, segments, options, type, attributes, anchor, ref_track_id, ref_track_index, position, above, track_ref, track_id, source_from_id, target_time_range, source_time_range, start, duration, name, attribute, flag, auto_sort_affected_tracks, remove_empty_tracks, return_affected_segments` |
  | `0x4056d90` | 24 | `root, position, rotation, scale, association_params, current_word_info, start_time, end_time, text, words, word_id_range, action_type, keyword_ranges, children, type, …` |
  | `0x32e89a0` | 26 | 美颜/脸型调节面（`face_id, skin_tone_coldwarm, skin_tone_intensity, figures, resources, operator, …`） |
  | `0x4056f90` | 13 | 动画面（`anims, anim_type, anim_resource_id, anim_resource_path, duration, loop_duration, op_code, fparam1..4, sparam, text`） |
  | `0x332ef78` | 16 | 封面面（`draft_cover, action, source, path, url, frame_time_us, segment_id, width, height, fallback_width/height, …`） |

- **Finding**：这些是 **11.6 agent/协议写入面的 schema 反射表**（`auto_sort_affected_tracks`、
  `remove_empty_tracks`、`return_affected_segments` 是请求参数而非草稿 JSON 键），**不是**桌面草稿序列化表。
  指针表顺序=声明顺序，所以表内字段的次序可用。顺带捞到两份纯枚举：受支持容器清单
  `jpg png mp4 mov m4v avi webm` / `m2v vob wma m4a mp3 flac`，以及 HSL 六元组
  `hue_sat hue_hue hue_lum lum_sat sat_sat sat_lum`（`hsl` bucket 的取值矩阵）。
- **Path**：`temp/rea-native/name-tables.json`、`scripts/pe_harvest.py::harvest_name_tables`。

## N-06 一次误判与撤回（纪律记录）

- **Evidence**：第一版按「x64 TypeDescriptor 前置两个零字」判据跑，**34,703 条全不命中**；
  改按 CFG 的 `EncodedTypeDescriptor` 假设后表面上「34,703 全命中」，但解引用那个 qword
  （如 `0x183439710`）落到 `api-ms-win-c…` 的 **UTF-16 字符串池**，不是 CompleteObjectLocator。
- **Finding**：**继承图（COL→CHD→BaseClass）没有建立**，此前脚本里那句 `col_pointer` 判据与
  `names_with_bases` 字段已从 `pe_harvest.py` 删除，`leading_qword_observation` 只作为中性观察值保留。
  「mangled 名字串存在」是可证的；「这些名字背后是可解引用的 RTTI 结构」在本轮**未证**，属于 Ghidra 的活。
- **Path**：撤回记录在本文件；代码侧见 `scripts/pe_harvest.py::harvest_rtti` 的 docstring。
- **另一条落空的假设**：「桌面草稿字段名会物理相邻排列」。实测 `.rdata` 里连续 ≥5 个相邻标识符串只有 12 处，
  **与语料键交集为 0**（命中的全是格式表和快捷键码表）。指针表形（N-05）才是这个二进制的反射形状。

## N-07 待办（不在本文件分号，合并时进 `unresolved.md`）

1. `business_info` 由谁写入——11.6 桌面 videoeditor 无该字面量（候选：agent 面 / 旧版本 / 云端回灌）。
2. 桌面草稿序列化器到底在哪：`nlohmann` 只有 11 个类型名，`JsonMaterialProcessor` 只有 2 个，
   规模不像主序列化路径 ⇒ 可能在别的模块或走别 reflection 机制。**需要 Ghidra 定点取证**。
3. 类型继承图与字段偏移（容器格式的真正形状）——同上，需 Ghidra。
4. Ghidra provider 可行性：见 N-08…N-10（2026-10-21 已就位并量过斜率）。

## N-08 provider 就位（工具链溯源，**待合并进 `toolchain.md` §1/§2**）

本轮写作时 `toolchain.md` 正被另一会话修改（mediabunny/F-054 批次），故溯源先记在这里。

| 件 | 实测 |
|---|---|
| Ghidra | `ghidra_12.1.4_PUBLIC_20260921.zip`，**569,649,598 B**，sha256 `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db` |
| 摘要来源 | `api.github.com` 该 release 资产的 `digest` 字段（TLS 读取，官方口径），落盘前后**逐字节比对一致** |
| 取件 | 本机直连 GitHub 资产域不可用：单连接 25 KB/s、4 路并发 Range 各 20 s 全 0 字节、`gh release download` 6 分钟 1.3 MiB ⇒ **由用户浏览器下载**到 `<DRIVE_D>/Users\11\Downloads\`，agent 校验后解压 |
| 落点 | `temp/vendor/ghidra_12.1.4_PUBLIC`（6,695 个条目，解压 20 s，未压缩 0.84 GiB）；zip 单一根目录，名字与预配的 `GHIDRA_INSTALL_DIR` 正好一致 |
| Java 区间 | `Ghidra/application.properties`：`application.version=12.1.4`、`application.java.min=21`、**`application.java.max=`（空＝无上限）**、`application.java.compiler=21` ⇒ 21 与 27 形式上都合规，本项目按 REA 的验证组合走 **21** |
| JDK | `<DRIVE_D>/Program Files\Java\jdk-21.0.12.1`，`IMPLEMENTOR = Oracle Corporation`（**不是 Temurin**，供应方与先前建议不符，按实测记），x86_64、含 `javac.exe`/`jmods`/`include` |
| 环境变量 | 用户级 `HKCU\Environment`：`JAVA_HOME`、`GHIDRA_INSTALL_DIR` 两条；**未改 `Path`、未改 HKLM、未跑 `rea setup`、未注册 MCP** |
| Node | doctor 报 `24.19.0`，满足 `rea-agents` engines |

**`rea doctor --json` 结果**：`healthy:false`，但**九项 ghidra 检查全绿**——
`version 12.1.4`、`headless → support\analyzeHeadless.bat`、
`native_decompiler → Ghidra\Features\Decompiler\os\win_x86_64\decompile.exe reports pe x86_64, which matches win32/x64`、
`java → "21.0.12.1; 64-bit; JDK; …; accepted a 64-bit full JDK 21 or newer"`、
`native_authority → "Verified Windows native Job Object, private DACL, and reparse-safe handle controls; local NTFS only"`；
`providerInspections[ghidra] = configured:true, available:true`。
红灯只有 hopper / IDA / JADX 三个未装的引擎 + 五个客户端 MCP 注册项（`config_drift`），
**这些都是 §5 故意不做的**，不是故障。doctor 顺手列出了 `rea setup` 会改写的文件
（含 `<HOME>\.qoder-cn\settings.json`），佐证「不跑 setup」这条禁令该留。
- **Path**：`temp/rea-native/smoke-inspect.json`、`temp/rea-native/smoke-10mb.json`。

## N-09 冒烟与斜率（**更正我先前的「数小时」估计**）

| 目标 | 体积 | `inspect` 墙钟 | 备注 |
|---|---|---|---|
| `lyra_cli_executable_log_suppressor.dll` | 23 KiB | **28 s** | exit 0；`import_mode = ephemeral-source-immutable`、`executable_role = shared-library`、`managed = false` ⇒ 确证「导入不可变副本、不载入不执行」 |
| `lyra_cli_client.dll` | 10.6 MiB | **363 s** | `segment_count=8`、`procedure_count=14,289`、`string_count=14,810`（heap 512M→2G） |

- **Finding**：边际成本约 **34 s/MiB**（28 s 里绝大部分是 JVM+Ghidra 固定启动）。外推 `videoeditor.dll`
  整文件 72.5 MiB ⇒ **约 40–60 分钟**，不是先前书面估计的「数小时以上」。该修正按 §6 就地改写，不留旧数。
- **Path**：同上两条 JSON；两条命令都在 `GHIDRA_HEADLESS_MAXMEM` 受限下跑完，未触发 OOM。

## N-10 真正的成本约束：snapshot 不是数据库

- **Evidence**：`temp/vendor/rea/docs/cli.md:200-206`：
  「These are cached observations, **not a saved provider database**: only eligible exact queries can reuse a result,
  and new or live queries can still require provider startup」。
  另 `native-investigation.md:77`：「Cancelling an active request **terminates the ephemeral database and discards its annotations**」。
  `ghidra-provider.md:38`：「The socket is exposed **only after default auto-analysis completes**」。
- **Finding**：一次 auto-analysis 只买一次问答。若走 CLI 逐条问 `videoeditor.dll`，
  **每个新问题 ≈ 40–60 分钟**，且中途取消等于白跑（不能「先跑 20 分钟看看」）。
  ⇒ 全量分析必须**在一个活的 provider 会话里把问题问完**，才摊平这 45 分钟；
  这正好是 MCP `open_binary` → 多次 `tools/call` → `close_binary --snapshot` 的形态，
  而 CLI 没有跨调用的会话（命令表里 native 侧没有 session/批量原语）。
- **Path**：上述三处文档行号。策略岔口见当轮对话记录。

## N-11 `draft_store` 是桌面草稿序列化层（导出表直接给，零成本）

- **Evidence**：`scripts/jy_crypto/pe.py` 枚举 11.6 `videoeditor.dll` 的 32,996 个导出名，按子串计数：

  | 片段 | 命中 | 代表符号 |
  |---|---|---|
  | `draft_store` | **860** | `DraftStore@draft_store`、`StoreWrapper@draft_store`、`DraftIOFactoryBase@draft_store` |
  | `DraftIO` | 40 | `??0DraftIOFactoryBase@draft_store@@QEAA@XZ`（构造函数） |
  | `json`（小写原样） | 3,529 | `KeyValueJsonManager@kv_json@draft_store`、`StructCoding@json_coder` |
  | `Json`（大写） | 206 | `AttachmentArticleVideoCapflowJsonObject@lvve` |

  四个函数名直接点出草稿-素材的 JSON 桥：
  `ReadDraftMetaJsonMaterials@DraftStore@draft_store` / `FillDraftMetaJsonMaterials@DraftStore@draft_store`
  及其 `StoreWrapper@draft_store` 包装版，签名收发
  `std::map<MaterialType@draft_store, std::vector<std::shared_ptr<DraftMaterial@draft_store>>>`。
  旁证：在**另一个**小模块 `lyra_cli_client.dll` 里用 Ghidra 搜 `draft_store`，26 条命中全是
  `VIDEOEDITOR.DLL::draft_store::DraftIOFactoryBase::…` 形式的导入符号——客户端按名字消费这套门面。
- **Finding**：**N-07 第 2 问结案**：桌面草稿序列化不在 `nlohmann`（它只有 11 个类型名，规模不符），
  而在 `draft_store` 命名空间，按 `MaterialType` 枚举分桶组织 `DraftMaterial` 集合。
  这把「素材类型桶」（语料侧 `bucket_keys` 42 项）与程序侧的 `MaterialType` 枚举直接对上，
  按 §6.1 属「名字与合法性以程序为准」的那一类。
- **Path**：`temp/rea-native/harvest-report.json`、`temp/rea-native/session-lyracli/05-proc-draft_store.json`；
  清点方式 `PEExports(...).find(片段)`（只读导出表，未反汇编，属 §3 原有允许面）。
- **证据等级**：**已验证**（导出表 + 另一模块的导入符号两路一致）。
- **边界声明**：`EncryptUtils@lvve` 只作**命名清点**，不取其伪代码——§1.1 的算法线不越。

## N-12 全量分析实测 + `draft_store` 框架图（Ghidra 侧）

- **Evidence**：一次活会话跑完 27 步（`scripts/rea_session.py`，Ghidra 12.1.4 / JDK 21 / heap 4G）。
  **时间轴**：`binary_overview` **3,101.5 s（51.7 分钟）** = 全量 auto-analysis；此后**所有搜索 0.0–0.1 s 返回**
  ⇒ 摊平成立，一次分析确实买得起一批问题（这正否证了「每问 45 分钟」只在会话被拆成多次 CLI 调用时才成立）。
  规模：`procedure_count=116,637`、`string_count=124,028`、`segment_count=8`。
  段表与 N-01 手工 PE 解析**逐段吻合**（`.text 0x180001000–0x183065600`、`.rdata 0x183066000–0x184034c00`、
  `.data 0x184035000–0x1843b7c94`、`.rsrc` 仅 0x200 B），两路独立互证。
  `open_binary` 回读 sha256 与目标一致；`close_binary` 存出快照 507,197 B、`evidence_records=19`、`primitive_entries=0`。
- **Finding（框架图）**：Ghidra 解粘后 `draft_store` 有 **771 个函数**，按类分布：

  | 类 | 函数数 | 读法 |
  |---|---|---|
  | `DraftStore` | 213 | 草稿读写主体 |
  | `StoreWrapper` | 205 | 对外的包装层（与 DraftStore 近乎成对） |
  | `DraftUploadCloudStore` / `DraftRestoreCloudStore` | 69 / 49 | 云上传与恢复两条路径 |
  | `DraftStoreManager` | 44 | 生命周期/调度 |
  | `DraftMaterial` | 41 | **素材对象本体**（语料 42 个 bucket 的程序侧对应物） |
  | `MultiTimelineContext` | 21 | **多时间线上下文**（本项目主场景） |
  | `IOManager` 19 / `DraftUtil` 17 / `DraftIOFactoryBase` 13 / `DraftActionParam` 10 / `DraftIO` 10 | | |

  序列化桥梁的具体地址：`CreateDraftMetaJsonString` `0x1812ae9a0`、
  `FillDraftMetaJsonMaterials` `0x1812af7b0`、`ReadDraftMetaJsonMaterials` `0x1812b2d20`、
  另有 Cloud / Enterprise 两组变体，及 `getDraftMetaJsonFile` `0x1812be140`。
  旁支 `draft_store::kv_json::KeyValueJsonManager` 是一台**按前缀取键的磁盘 KV-JSON 机**
  （`GetKeysByPrefix` / `EraseObjectsByPrefix` / `LoadKVJsonFromDiskSync` / `GetFilePath`），
  与根镜像/时间线副本那一摊（U-17）是同一族问题。
- **Path**：`temp/rea-native/session-videoeditor/*.json`（`01-overview`、`02-segments`、`03-proc-draft_store` 等 22 份）、
  `temp/rea-native/snapshot-videoeditor.json`、日志 `temp/rea-native/videoeditor-session.log`。
- **证据等级**：**已验证**（Ghidra 全量分析 + 自有 PE 解析 + 导出表三路一致）。

## N-13 `business_info` 缺席升级为双路确认

- **Evidence**：①自有字节扫描（限 `.rdata`+`.data`）：20,470 个标识符形字面量里无 `business_info`（N-02）；
  ②Ghidra 全镜像字符串清点 124,028 条：`search_strings business_info` → **0 行**。
- **Finding**：`business_info` **不是 11.6 桌面 videoeditor 写的**，且不只是「不在数据段」——整份镜像里这个字面量都不存在。
  按 §6.1 第 3 条，这是「有第二个写入者」的强证据而非语料错误；候选仍是 agent 面（`canvas_agent`）或云端回灌。
- **Path**：`temp/rea-native/cross-check.json`、`temp/rea-native/session-videoeditor/11-str-business_info.json`。
- **证据等级**：**已验证**（两种独立清点法一致，且分母口径不同：字节级 vs 镜像级）。
- **同批附带**：字段名字面量的分布密度（全部落 `.rdata`）——`material_id` 135 处、`check_flag` 24、
  `draft_content` 21、`uniform_scale` 20、`render_index_track_mode_on` 12、`draft_meta` 10、
  `responsive_layout` 8、`mix_mode` 3。引用方（谁读这些地址）在 N-14 的 xrefs 批次里。

## N-14 函数档案批次（第二轮活会话）

- **Evidence**：87 步计划（69 个 `analyze_function` + 16 个 `xrefs` + open/close）。时间轴：
  全量 auto-analysis 在**第一个** `analyze_function` 里付掉 **2,976.1 s（49.6 分钟）**，
  之后每个档案 **0.6–3.6 s**、每个 `xrefs` **0.0 s**、`close_binary` 22.6 s。
  产物 88 份 / 146 MB（`temp/rea-native/session-deep/`，不入库）。
  3 份档案返回 `resource_constraint`（含最想看的 `ReadDraftMetaJsonMaterials`）：
  语义是「响应超过 stdio 预算，**结果未截断而是保留**」，续读要用 `inspect_analysis_view` 加分页参数。
- **方法更正（重要，别复用错的那个数）**：第一版排名用 `key in pseudocode` 的**子串**匹配，
  得到 `DraftMaterial::getSubTimeRange` 引用「16 个语料键」——那是 `id`/`path`/`name`/`source`
  这类短键在标识符与变量名里乱命中的假象，**作废**。改用工具自己给出的 `referenced_strings`
  （真实数据引用）后，同一函数为 0 键。以下结论只基于后者。
- **Finding**：
  1. 元信息写入者的字符串级字段面：`DraftStore::FillDraftMetaJsonMaterials` 与其
     `StoreWrapper::` 包装版（档案成对，规模 25,079 B / 25,574 B 伪代码）引用
     **`create_time`、`duration`、`extra_info`**；`DraftStore::DraftStoreManager` 引用
     `drafts`、`id`、`path`、`video`。
  2. `json_coder::StructCoding` 的 `Serialize`/`Deserialize`/`_serialize`/`_deserialize`/`_registerParams`
     的 `referenced_strings` **全为 0** ⇒ 它是泛型派发器，**字段名不在这层**，由调用方传入。
     这否证了「`json_coder` 里能找到键表」的猜测。
  3. 源码树泄露：`C:\32139\videoeditor\lyra\trash_src\draftstore\draft_store_manager.cpp`、
     `C:\32139\videoeditor\lyra\base\looper\ve_looper\queue\message_loop_impl.h`
     ⇒ 模块布局是 `videoeditor/lyra/<模块>/…`，且 **draftstore 挂在 `trash_src` 下**（遗留目录命名，
     与「`draft_store` 是较新的独立子系统」直觉相反，值得写回代码侧结论）。
  4. 文件名字面量：`draft_meta_info.json`、**`root_meta_info.json`**、**`root_draft_meta_info.json`**。
     **就地更正**：`draft_meta_info.json` 对本项目**不是新发现**（F-028 写入足迹、
     `spec/format-reference.md` 与 `spec/write-rules.md` 均已记录，语料扫描也明说「只解析 `draft_content.json`」）。
     本轮新增的是**第二路独立印证**——这些名字由原生代码引用，而非只出自 `canvas_agent` 常量；
     以及 `root_meta_info.json` / `root_draft_meta_info.json` 两个 `root_*` 名字不在已知的 5 成员清单里。
  5. nlohmann 报错串（`type must be string, but is `、`cannot get value`、
     `cannot compare iterators of different containers`）出现在该层 ⇒ 印证 §6.1 里
     「这层 JSON 由 nlohmann::json 承担」，与 RTTI 侧 `nlohmann` 命名空间同源。
- **Path**：`temp/rea-native/session-deep/fn-*.json`、`xref-*.json`、`temp/rea-native/deep-session.log`。
- **证据等级**：1、3、5 **单源待验证**（仅原生代码一路）；4 为**已验证**（原生字面量 + 既有 F-028 实测两路）。

## N-15 `User Data\Projects\com.lveditor.cloud.draft_*` 是一个未授权的草稿根

- **Evidence**：按文件名 glob（未读内容）：`<DRIVE_D>/JianyingPro\User Data\Projects\com.lveditor.cloud.draft_1146127169623127\root_meta_info.json`，
  同名形态共 **5** 个目录；草稿根 `<DRIVE_D>/JianyingPro\<DRAFT_ROOT>` 下 1,537 个草稿目录里
  `draft_meta_info.json` 命中 **1,514**（98.5%），`root_*` 两个名字命中 **0**。
- **Finding**：`DraftStoreManager` 的 root/save path 落在**另一个根**（`User Data\Projects`），
  与用户草稿目录并列；命名空间也对得上——包名 `com.lveditor` 正对应代码里的 `lvve`。
  **但这不在 scope §1「数据对象」列出的路径里**（那条只点名 `<DRAFT_ROOT>`、`User Data\Cache`、`<DRIVE_E>/输出`、fixture 包），
  故本轮**只确认文件名存在、未解析其内容**，按 §7「发现即停，先问用户」处理。
- **Path**：glob 结果见当轮记录；解析需先扩 §1。

## N-16 字段名引用点计数（全镜像）

- **Evidence**：对 8 个字段名/文件名字面量的地址取 `xrefs`，**556 个引用点**：

  | 字面量 | 引用点数 |
  |---|---|
  | `material_id` | 235 |
  | `check_flag` | 127 |
  | `uniform_scale` | 85 |
  | `responsive_layout` | 49 |
  | `render_index_track_mode_on` | 22 |
  | `draft_meta`（文件名族） | 21 |
  | `mix_mode` | 15 |
  | `draft_content`（文件名） | **2** |

- **Finding**：读写面的宽窄与字段层级相符——`material_id` 是跨素材的公共外键（最宽），
  `check_flag`/`uniform_scale`/`responsive_layout` 是片段样式位，`draft_content` 作为**文件名**只被 2 处引用
  ⇒ 打开该文件的路径是集中的（与 N-14 的 `getDraftMetaJsonFile` 一族相吻合），不是到处各自拼路径。
  **这些地址暂时只能算「引用点」不能算「引用者」**：`xrefs` 返回的是地址列表，
  要落成函数名需要一张 `list_procedures` 全表离线映射（见 N-17）。
- **Path**：`temp/rea-native/session-deep/xref-*.json`。
- **方法记录（第二次踩同一个坑）**：`xrefs` 的 `normalized_result` 行是**裸地址字符串**，
  前两版按 `procedure`/`name`/`value` 键提取，得到全 0 的假阴性。
  与 N-14 那条子串假阳性合起来看：**这批工具的返回形状必须实测，不能推定**；
  任何「0 结果」在没确认提取路径前都不算结论。

## N-17 下一批的前置：把函数表与字符串表离线化（**已完成，见 N-21**）

- **待办**：一次会话里取 `list_procedures`（116,637 行）与 `list_strings`（124,028 行）全表落 `temp/`。
  有了 start/end 地址区间，N-16 的 556 个引用点以及此后任何地址都能**离线**映射到函数，
  不必再为每个问题付 50 分钟。这是把「一次分析买一批问题」进一步变成「一次分析买无限问题」。
- **成本**：会话启动仍是全量 auto-analysis ≈ 50 分钟（实测 2,976 s / 3,101 s 两次）。

## N-18 草稿注册表：`root_meta_info.json`（明文，2.85 MB）

授权来自 scope §1 的 2026-10-21 扩项（`<DRIVE_D>/JianyingPro\User Data\Projects`，只读）。

- **Evidence**：`<DRIVE_D>/JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json`
  = 2,849,968 B **明文 JSON**（未加密）。顶层三键：`all_draft_store`（**2,126 条**，每条 **38 个键**）、
  `draft_ids`（114）、`root_path`。条目键含
  `draft_id`（GUID）、`draft_name`、`draft_fold_path`（**绝对路径**）、`draft_json_file`、`draft_root_path`、
  `draft_cover`、`draft_timeline_materials_size`、`draft_new_version`、`draft_type`、`draft_is_invisible`、
  `draft_is_cloud_temp_draft`、`draft_is_infinite_canvas_draft`、`draft_is_ai_shorts`、`draft_is_pippit_draft`、
  `draft_is_web_article_video`、`cloud_draft_sync`、`draft_cloud_*`（模板/教程/购买信息）、`pippit_*`、
  `streaming_edit_draft_ready`、`tm_draft_create` / `tm_draft_modified` / `tm_draft_removed` / `tm_duration`、
  `tm_draft_cloud_entry_id` / `_parent_entry_id` / `_space_id` / `_user_id`。
  同目录还有 `draft_meta_info.json`（1,708 B，**密文**）、`template.json`（251,960 B，密文）与
  `template.json.bak`（252,340 B，密文且与主文件不同）、`template.tmp`（2,099 B，明文）、
  `.recycle_bin\root_meta_info.json`（22,693 B，明文）。
  另有 6 个 `com.lveditor.cloud.draft_<id>` 目录，每个只有 0–1 份 `root_meta_info.json`（多数很小、`all_draft_store` 为空）。
- **Finding**：这是**草稿的权威索引**（谁存在、叫什么、在哪个根、多大、何时改、是否已删、云端状态），
  而且**不加密**——本项目此前只能靠遍历目录名来认草稿。`tm_draft_removed` 非空 **153 条**、
  `.recycle_bin/` 独立成册 ⇒ 「已删除但仍被登记」是可查的。
  `draft_type` 在 2,126 条里**全为空串**；但同一批里 **`draft_new_version` 不是全空**——2026-10-22 复核为
  1,798 空 + **328 有值**（`114.0.0` 82、`164.0.0` 80、`129.0.0` 40、`93.0.0` 29…，本条初稿记成"全空"是错的，见 N-23）。
  ⇒ 「注册表不承载版本判别」这句要收窄：它承载的是**一批低于桌面当前区间（179–189）的**版本串，不能与草稿内
  `platform.app_version` 混用（U-75）；版本轴仍只能回到草稿内的 `platform`（与 F-051/U-66 一致，本条从程序侧再钉一次）。
  `root_path` 字段写的是 `<HOME>/AppData/Local/...`，而文件实际躺在 `<DRIVE_D>/JianyingPro\User Data\...`
  ⇒ 该字段随安装搬迁而失真，**不可作为定位依据**；定位要用条目级 `draft_fold_path`。
  `template.json.bak` 与 `template.json` 密文不同而长度相近，是 F-003/U-20「每次重加密带随机熵」的又一见证。
- **Path**：文件本体（只读，未改动）；解析脚本为当轮一次性读取，未落库（隐私：条目含真实草稿名与云 ID，
  **文档只记 schema 与计数，不抄值**）。

## N-19 语料口径缺口：草稿根不止一个，E: 根从未被扫描

- **Evidence**：注册表 2,126 条的 `draft_root_path` 去重后是三个**拼写**、两个**实体**：

  | `draft_root_path` | 条数 | 目录存在 | 实测子项 |
  |---|---|---|---|
  | `<DRIVE_D>/JianyingPro/<DRAFT_ROOT>` | 1,493 | 是 | 1,538 |
  | **`<DRIVE_E>/JianyingPro/<DRAFT_ROOT>`** | **629** | 是 | **647** |
  | `<DRIVE_D>/JianyingPro\<DRAFT_ROOT>`（反斜杠形） | 4 | 是 | 同上 D: 根 |

  E: 根实测：647 个子目录，**416 个含 `draft_content.json`**、629 个含 `draft_meta_info.json`，另有 `.recycle_bin`。
  而扫描器只认两个根：`scripts/jy_crypto/cache.py:18-27` 的默认根 = `<DRIVE_D>/JianyingPro\<DRAFT_ROOT>`
  + `%LOCALAPPDATA%\JianyingPro\<DRAFT_ROOT>`；scope §1 的「数据对象」也只点名 D: 根。
- **Finding**：**r3 语料（2,215 内容文件 / 1,537 草稿目录）系统性漏掉了 E: 根**。
  按目录数算少 629 个草稿（约 −29%），按 `draft_content.json` 算少 **416** 个内容文件（约 +19% 的潜在分母）。
  ⇒ 一切**频次、缺省值、取值范围**类结论的分母都偏小；`stats.json -> corpus` 的自洽检查只保证「扫到的一致」，
  不保证「扫全了」，这是它的盲区。**修法要改一行代码**（本条初稿写「不需改代码」，2026-10-22 实测后就地更正）：
  `cache.py` 的 `_roots()` 把 `JY_DRAFT_ROOTS` 整串当**一个**路径（`values = [override]`），
  所以给两个根时第二个从未生效——已改为按 `os.pathsep` 切分（Windows 上即 `;`），
  实测 `JY_DRAFT_ROOTS='<DRIVE_D>/… Drafts;<DRIVE_E>/… Drafts'` 解析出两个存在的根。
  重跑 `corpus_scan.py` 即可；但必须先过 §4 的只读证明（随机分层 40 份全文件 sha256 不变）。
  同时记下**路径拼写陷阱**：同一根在注册表里有 `<DRIVE_D>/` 与 `<DRIVE_D>/` 两种写法（1,493 vs 4），
  任何按路径去重的逻辑要先归一化分隔符。
- **Path**：`scripts/jy_crypto/cache.py:18-27`（默认根）、注册表计数见 N-18、E: 根实测见本条。
- **证据注册等级**：**已验证**（注册表声明 + 磁盘实测两路一致）。
- **待办**：新开未解决项——「E: 根并入后 r3 全部频次结论需要重算」；合并时向 `unresolved.md` 分号。

## N-20 元素材记录的真实键表（`ReadDraftMetaJsonMaterials` 全量伪代码）

- **Evidence**：会话 3 用自动分页取回完整伪代码 **47,236 code units**（24 页 × 2048，`coverage.exhausted` 达成）。
  引号内字符串字面量共 **18** 个（精确匹配，非子串）：

  ```
  ai_group_type  create_time  draft_materials  duration  enter_from  extra_info
  file_Path  height  import_time  import_time_ms  item_source  material_color_tag
  metetype  roughcut_time_range  start  sub_time_range  value  width
  ```

  调用面：**120 个调用点、28 个被调函数**。按「绑定了哪个键字面量」分类：

  | 被调地址 | 调用次数 | 绑定的键 | 读法 |
  |---|---|---|---|
  | `FUN_18009b0d0` | 24 | 上述 **17** 个键（几乎全部） | **按键取值**（`get(container,"key")` 形） |
  | `FUN_1800a2170` | 17 | **9** 个：`create_time duration enter_from file_Path height import_time import_time_ms item_source width` | 按键写入 |
  | `FUN_1800fc8a0` | 11 | — | 另一族取值/判定 |
  | `FUN_18009b650` | 7 | — | 返回 char 且被 `== '\0'` 判，形如「键是否存在」 |

- **Finding**：
  1. `draft_meta_info.json` 里**素材记录**的键面在这段代码里是闭合可枚举的（18 个），
     与 N-18 注册表的 38 键是**不同层**的东西：注册表管「有哪些草稿」，这里管「一条素材元信息长什么样」。
  2. **读写面不对称**：读取覆盖 17 个键，本函数内的按键写入只覆盖 9 个
     ⇒ 剩下 8 个键由被调方或别处产生。对 M3 写入回环的含义：**不能假定「读得到就写得出」**，
     要按这 9/17 的差集去定位第二个写入点。
  3. 命名不合常规处要照抄不规范化：**`file_Path` 的 P 大写**、**`metetype` 无下划线**
     （同批别处出现过 `meta_type`，二者是否同义**未证**，见待办）。按 §6.1 第 3 条，
     不能因为「不像规范写法」就改成 `file_path`/`meta_type`。
  4. 另外两份分页取回的档案是纯访问器：`draft_store::DraftMaterial::get*`（30,210 units、**0** 字面量）
     与 `MultiTimelineContext` 的 `vector<TimelineData*>` 访问器（1,546 units、0 字面量）
     ⇒ 键名不在这两层，与 N-14 的 `json_coder::StructCoding` 零字面量结论同构。
- **Path**：`temp/rea-native/session-tables/20-fn-ReadDraftMetaJsonMaterials[.pageNNN].json`、
  `21-fn-material*`、`22-fn-multitimeline*`；日志 `temp/rea-native/tables-session.log`。
- **证据等级**：1、2、4 **单源待验证**（仅伪代码一路，需与 `draft_meta_info.json` 实文明细对照才算两路）；
  3 的「大写 P」是**已验证**（字面量原文直接可见）。
- **会话 3 的执行账**：`list_procedures` **2,758.2 s**（全量分析在这里付掉）、`list_strings` 21.5 s、
  三个档案 3.5 / 4.9 / 6.7 s、`close_binary` 18.3 s。
  **两张全表没拿到**：`list_procedures`/`list_strings` 返回的 `resource_constraint` **不带 `continuation`**
  （与 N-14 那种带分页参数的形状不同），官方口径是
  「`get_evidence_bundle`(detail: summary) 发现保留记录 → `export_evidence_bundle` 导出完整会话」；
  而 retained evidence **只在会话内有效**（N-14 实测 `evidence_integrity_mismatch`），
  快照不携带。⇒ 需要第四次会话，且必须在同一会话内完成导出。
- **第三次踩同一类坑（方法记录）**：统计被调函数时把 `FUN_[0-9a-f]{8}` 写死 8 位，
  而 Ghidra 的名字是 `FUN_1800a2170`（**9** 位十六进制），于是「访问器三件套」计数一度全为 0。
  与 N-14 子串假阳性、N-16 键名假阴性同型：**计数前必须先验匹配式对被测词形的覆盖**。
- **待办（合并进 `unresolved.md`）**：①`file_Path` 的 `P` 大写是否被大小写敏感的读取路径依赖；
  ②`metetype` 与 `meta_type` 是否同义、分别属于哪一层；
  ③写入侧缺失的 8 个键由谁产生；④E: 根并入后 r3 频次重算（N-19）。

## N-21 序列化架构：1,102 对 `to_json`/`from_json` + 292 类补丁三件套

- **Evidence**：会话 4 用 `export_evidence_bundle`（入参只要 `{path, overwrite}`，导的是整个保留会话）
  导出 `temp/rea-native/bundle-tables.json` = **78,572,639 B**，含 `list_procedures` **116,637 行**
  （内部 115,800 + `EXTERNAL:` 导入 837）与 `list_strings` **124,028 行**。
  `list_procedures` 这次**又**付了 2,632.6 s 全量分析 ⇒ 再次证伪「靠快照跳过分析」，retained/快照都不跨会话。
  按尾名数重载规模（Ghidra 解粘后**重载共享全名**，按名字聚合得到的是「族」不是「单个函数」）：

  | 尾名 | 不同全名 | 实例数 |
  |---|---|---|
  | `to_json` | 3 | **1,110**（`lvve` 1,102 + `lyra::project` + `lyra::FlowerUtils`） |
  | `from_json` | 3 | **1,159** |
  | `patch_from_json` | **292** | 292（每类一个成员） |
  | `to_patch_json` | 281 | 281 |
  | `dirty_node_to_patch_json` | 293 | 293 |

  用 `procedures.tsv`（115,800 行入口地址；**以下一个入口为排他界**的区间近似）把 N-16 的 556 个引用点落到函数：

  | 字段 | 引用点 | 不同函数 | 尾名分布（点数） |
  |---|---|---|---|
  | `material_id` | 235 | **174** | to_json 45、from_json 42、patch_from_json 18 |
  | `check_flag` | 127 | 74 | to_json 17、patch_from_json 16、to_patch_json 16 |
  | `uniform_scale` | 85 | 32 | patch_from_json 35、to_patch_json 28、dirty_node 7（**to_json/from_json 为 0**） |
  | `responsive_layout` | 49 | 21 | patch_from_json 20、to_patch_json 16、dirty_node 4 |
  | `render_index_track_mode_on` | 22 | 17 | to_json 6、from_json 5、patch_from_json 4 |
  | `draft_meta`（文件名族） | 21 | 8 | changeFoldNameAndCovertFoldName 5、getDraftMetaJsonFile 3、saveDraftMetaInfoJson 3 |
  | `mix_mode` | 15 | 6 | patch_from_json 5、to_patch_json 5、dirty_node 2 |
  | `draft_content`（文件名） | 2 | **1** | `StoreWrapperInitInfo::StoreWrapperInitInfo` |

- **Finding**：
  1. 草稿 JSON 层是 **nlohmann 的 ADL 自由函数重载集**——`lvve::to_json`/`from_json` 各约 1,100 个实例，
     **一类型一对**；其上再叠 **292 个类型**的 `patch_from_json`/`to_patch_json`/`dirty_node_to_patch_json`
     成员（增量与脏节点写路径）。⇒ 本项目要写回草稿，该对标的是这套 292 类补丁三件套，
     而不是那 1,100 对全量序列化器。
  2. **两条路径有分工**：`uniform_scale`/`responsive_layout`/`mix_mode` 在 `to_json`/`from_json` 里
     **一个引用都没有**，全走补丁三件套 ⇒ 片段级字段属**补丁面**，不属全量序列化面。
     `material_id` 横跨 174 个函数（含 to_json/from_json）⇒ 跨切外键。
     `check_flag` 两边都有（to_json 17 + 补丁族 32）⇒ 与 U-28/U-47「位不是样式的纯函数」相容，
     且提示它在全量与增量两条路径上**各写一次**，写回时两处都要同步（与 F-027 字号「两处同时写」同型）。
  3. `draft_content` 文件名只被 **1 个函数**引用（`StoreWrapperInitInfo` 构造）⇒ 路径拼装单点；
     `draft_meta` 由 `DraftStore` 的改名/取路径/落盘三兄弟集中管理。
  4. 结构旁证：837 个 `EXTERNAL:` 导入里出现
     `CCCREATOR.DLL::vesdk::ccmodel::CCTextStickerFilter::calcPreviewMd5`
     ⇒ `vesdk`/`ccmodel` 那层**不在** videoeditor 内，属另一模块；
     N-03 里 videoeditor 的 129 个 `vesdk` 类型名因此应读作**消费方**。
- **Path**：`temp/rea-native/bundle-tables.json`（78.5 MB，不入库）、`temp/rea-native/procedures.tsv`、
  `temp/rea-native/field-referrers.json`、`temp/rea-native/export-session.log`。
- **证据等级**：Finding 1、3 **已验证**（N-20 伪代码 + 本条全量函数表两路一致）；
  2 的「分工」为**单源待验证**（仅地址映射一路，要与 `draft_content.json` 的实际差分行为对照才成立）；4 为**单源**。
- **方法记录（同型错误第 5 次 + 两次真实返工）**：
  ①从文件名反取字段时用了 `xref-(...)-0x` 模式，而生成的文件名里 `0x` 早被剥掉 ⇒ 正则失配报错；
  ②按函数**名**聚合会把 1,102 个 `to_json` 重载误当成一个函数（已改为「按地址数不同函数 + 按尾名分桶」双口径）；
  ③`out[key]` 被同字段的第二个地址文件覆盖（已改为按字段合并）。
  另记：**区间近似**（以下一入口为界）会影响归属判定，函数边界本身在 Ghidra 侧也有 `function_boundary_observations` 限制。

## N-22 双根重扫：E: 根是逐字节镜像，不是覆盖缺口（N-19 的分母推断就地更正，2026-10-22）

- **Evidence**：`scripts/corpus_scan.py` 同一脚本两条腿各跑一次全量（用户批准「按 N-19 建议起 E: 根重扫」）：

  | 快照 | 日期 | 根 | 内容文件 | 去重内容 | 目录记录 | 只读证明 |
  |---|---|---|---|---|---|---|
  | r3（在册基准，已还原） | 10-16 | D | 2,215 | 2,050 | 2,450 | 40/40 不变 |
  | r4-d 控制腿 | 10-22 | D | 2,268 | 2,089 | 2,503 | 40/40 不变（40 份全在 D） |
  | r4-de 实验腿 | 10-22 | D+E | 2,754 | **2,095** | 3,134 | 40/40 不变（**31 份 D + 9 份 E**，按 `Random(0)` 复现名单） |

  E 根 486 个内容文件（legacy 369 / hybrid 70 / 根镜像 47，明文 279 / 密文 207，合计 24,922,588 B）里
  **480 个的摘要与 D 根某个文件逐字节相同**，只有 **6** 个是 D 根没有的内容；
  `content_multiplicity` 从控制腿的「1 份 1,912 / 2 份 176 / 4 份 1」变成实验腿的「1 份 1,521 / 2 份 531 / 3 份 1 / **4 份 42**」
  （r3 单根时是 1 份 1,887 / 2 份 162 / 4 份 1）⇒ 那个 4 就是「hybrid 双副本 × 双根」。
- **Finding**：
  1. **N-19 按目录/文件数推出的「r3 分母系统性偏小约 19%」不成立**（那是把文件数当内容数）。
     按内容口径 E 根只贡献 **6 / 2,095 = 0.3%**；引用 r3 频次的结论**不因 E 根失真**。
  2. **让数字动的是漂移不是覆盖**：10-16 → 10-22 的 D 单根就有 added 66 / removed 13 / **内容改写 94 个文件**
     （14 个草稿目录），数字叶子变化 **1,975 项**，文本侧若干键下移 4.5–18.1% 且**同幅联动**
     （`recognize_model` 4,976→4,077、`group_id` 16,726→15,827、`subtitle_keywords` 16,690→15,802、
     `base_content` 13,818→12,931、`texts.type==subtitle` 17,718→16,906）⇒ 是**少数字幕大户**改写/离场，不是普遍退化。
     实验腿相对控制腿 1,173 项变化，绝大多数 `+0.7–1.0%`，其中 `bucket_keys.effects.*` 齐涨 **+523** 由那 6 份里的**一份**造成。
  3. **基准不换**：换成 r4 要重生成 `docs/evidence/tables/` 全部 CSV 与 1,339 处数字引用，还会把「覆盖」与「漂移」混成一个差值。
     做法是 r3 留在 `temp/corpus-scan/` 当在册基准、两条腿各存一份、`scripts/corpus_diff.py` 做归因、引用带 `snapshot_date`
     （与 r2→r3 那轮同法）。三个快照目录已进 `check_doc_counts.py` 的可绑定证据清单。
  4. **副本普查在双根口径下必然含镜像**：`.bak` 2,854→3,342、`template-2.tmp` 2,939→3,431、`template.tmp` 1,815→2,461；
     这三个「只数不解析」的数**不得**当独立草稿数引用。
- **Path**：`temp/corpus-scan-r3/`、`temp/corpus-scan-r4d/`、`temp/corpus-scan-r4de/`（各含 `stats.json`/`manifest.json`/`csv/`），
  `temp/corpus-scan-r4de/e-root-check.txt`，`temp/diff-r3-to-r4d.txt`，脚本 `scripts/corpus_diff.py`（新）、
  `temp/e_root_check.py`；跑批日志 `temp/corpus-scan-rerun-a.log` / `-b.log`。
- **证据等级**：**已验证**（两条腿各带独立 sha256 只读证明；镜像判定用的是摘要级逐字节同一，非启发式）。
- **顺带修的一个 bug**：`cache.py::_roots()` 把 `JY_DRAFT_ROOTS` 整串当**一个**路径，双根从来只有第一个生效
  ⇒ 已按 `os.pathsep` 切分（N-19 原文「修法不需改代码」同步就地更正）。

## N-23 注册表侧的双根真相：628 组同名草稿、id 无一相同（M3 定位歧义，2026-10-22）

- **Evidence**：只读解析 `<DRIVE_D>/JianyingPro\User Data\Projects\com.lveditor.draft\root_meta_info.json`（明文，2,126 条 × 38 键），
  探针 `temp/registry_root_check.py`、`temp/registry_root_probe2.py`，输出存 `temp/corpus-scan-r4de/registry-*.txt`：

  | 观察 | 值 |
  |---|---|
  | 顶层 | `all_draft_store`（2,126 条）、`draft_ids: 114`（含义未解释）、`root_path`（写 `<HOME>/AppData/Local/…`，实际文件在 `<DRIVE_D>/JianyingPro\User Data\…` ⇒ 搬迁后失真） |
  | 按 `draft_root_path` 分根 | D **1,497** / E **629** |
  | 同名草稿目录跨根 | **628 组**（E 侧 629 个目录名里 628 个在 D 也存在） |
  | 跨根的 `draft_id` | **0 组同 id、628 组异 id** |
  | 跨根的时间戳 | 580/628 组 `tm_draft_create` 与 `tm_draft_modified` **逐位相同**；42 组 E 更新、6 组 D 更新 |
  | `tm_draft_removed` 为真 | D 126 / E 27 |
  | 全为假的标志位 | `draft_is_invisible`、`draft_is_cloud_temp_draft`、`draft_is_pippit_draft`、`draft_is_ai_shorts`、`draft_is_infinite_canvas_draft`、`draft_is_web_article_video` 均 2,126/2,126 False；`cloud_draft_sync` True 150；`draft_json_file` 2,126 条都以 `json` 结尾 |
  | `tm_draft_modified` | 单位**微秒**，跨度 2023-10-25 → 2026-10-22（当天仍在被写），0 条为空 |

- **Finding**：
  1. E 根是**整目录复制后重新注册**的一批：内容逐字节同（N-22）、时间戳逐位同（580/628）、但 `draft_id` 全新。
     ⇒ 「两台机器/两个根上的同一条草稿」在这台机器上是**两个独立注册条目**，应用侧列表里就是两行同名。
  2. **M3 的定位歧义是实打实的**：按草稿名解析路径会在 **628** 个草稿上二义。定位必须走
     「注册表条目 → 绝对 `draft_fold_path`（含根）」，且写回前要说明选了哪一根；名字/`draft_id` 都不足以唯一定位。
  3. **注册表不是版本轴**（就地更正 N-18）：`draft_type` 全空，但 `draft_new_version` 有 **328** 条非空
     （`114.0.0`/`164.0.0`/`129.0.0`/`93.0.0`/`106.0.0`/`97.0.0`/`163.0.0`/`110.0.1`/`139.0.0`/`87.0.0`/`133.0.0`…），
     整体**低于** U-60 在草稿内观测到的 179.0.0–189.0.0 区间 ⇒ 是老草稿或别产品线的串，不能与 `platform.app_version` 互换（U-75）。
  4. `business_info`（U-68）多一个候选写入者：注册表里有 **150** 条 `cloud_draft_sync=true`，
     且 `User Data\Projects` 下确有云侧存储根目录（见下面的清点），云侧回灌这条路没有被关闭。
- **顺带把存储根目录点清**（N-15 的「5 个」指的是**含 `root_meta_info.json` 的目录数**，不是目录名数，此处补精确口径）：
  `com.lveditor.*` 目录 **8 个**，其中 **5 个**含 `root_meta_info.json`（`com.lveditor.draft` + 4 个 `cloud.draft_*`），
  **3 个为空**（`cloud.draft_1539746931679022`、`cloud.draft_3428755309342810`、`textTemplate.draft`）。
  活的那本 `com.lveditor.draft/` 共 5 个文件：`root_meta_info.json` 2,849,960 B、`template.json` 251,960 B、
  `template.json.bak` 252,340 B、`template.tmp` 2,099 B、`draft_meta_info.json` 1,708 B。
- **Path**：`temp/corpus-scan-r4de/registry-root-check.txt`、`temp/corpus-scan-r4de/registry-probe2.txt`、探针脚本两个。
- **证据等级**：1、2、3 **已验证**（注册表 + 文件摘要两路一致）；4 是**候选登记**，未证。
- **隐私纪律**：本条与两份探针输出**只记计数、哈希前缀与取值**，不抄草稿名、`draft_id`、云空间 id。
