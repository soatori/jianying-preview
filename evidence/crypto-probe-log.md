# crypto 黑盒调用探测日志

前置授权见 [scope.md](scope.md)；工具与目标哈希见 [toolchain.md](toolchain.md)。
本文件只记录**哪种调用形态通过了门禁**，不记录任何算法细节。全程无逆向产物。

## 目标

| 项 | 值 |
|---|---|
| DLL | `<JY_INSTALL>\11.6.0.14552\videoeditor.dll` |
| 大小 / sha256 | 72,547,608 B / `8cfcbb612ccd946df974428977b1902736c1de0ae561e20c26cbd4ea86099cb1` |
| 导出符号总数 | 32,996 |
| `EncryptUtils@lvve` 家族 | 14 个（见下） |

自研 `scripts/jy_crypto/pe.py` 解析 PE 导出目录（标准库，无第三方依赖），按 `EncryptUtils@lvve` + 方法名子串匹配解析符号，**不硬编码 mangled 名**，因此跨 DLL 版本的符号漂移也能跟上。

家族导出（`scripts/jy_crypto/dll.py --dll ...` 实测输出）：

```
?decrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@...@std@@AEBV34@0@Z          # 3 参内存版
?decrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@...@std@@AEBV34@0AEA_N@Z     # 4 参内存版（带 ok 标志）
?encrypt@EncryptUtils@lvve@@QEAA?AV?$basic_string@...@std@@AEBV34@@Z
?enable@EncryptUtils@lvve@@QEAAX_N@Z
?isEnable@EncryptUtils@lvve@@QEAA_NXZ
?decryptFile@EncryptUtils@lvve@@SAHPEBD00@Z                                    # static int(const char*,const char*,const char*)
?encryptFile@EncryptUtils@lvve@@SAHPEBD00@Z
?decryptFileBytes@EncryptUtils@lvve@@SAHPEBD0AEAV?$vector@E...@Z
?decryptFileStream@EncryptUtils@lvve@@SA?AV?$shared_ptr@VLVVEDecryptStream@lvve@@...@Z
?isFileEncrypted@EncryptUtils@lvve@@SA_NPEBD@Z
?maybeEncrypted@EncryptUtils@lvve@@QEAA_NAEBV?$basic_string_view@...@Z
?calcEntropyDynamicString@EncryptUtils@lvve@@SA?AU?$pair@...@Z
??4EncryptUtils@lvve@@QEAAAEAV01@$$QEAV01@@Z / @AEBV01@@Z                       # 赋值运算符
```

## 探测 1：路径级静态 API —— 全部失败（记为负结果）

假设：静态 `const char*` API 的调用约定最简单，若可用则完全绕开 MSVC `std::string` 的 ABI 风险。

方法：对同一份密文副本（`temp/crypto-probe/<key>.cipher`）遍历 8 个变体 = `enable(false)/enable(true)` × 第三参 `""`/`"{}"` × 参数顺序 `(src,dst)`/`(dst,src)`。

| 探测 | enable | is_enabled | 结果 |
|---|---|---|---|
| `isFileEncrypted(copy)` | false | false | `false` |
| `isFileEncrypted(copy)` | true | true | `false` |
| `decryptFile` × 4 变体 | false | false | `status=1`，输出 0 字节 |
| `decryptFile` × 4 变体 | true | true | `status=1`，输出 0 字节 |

**Finding**：路径级 API 对草稿 JSON 副本无效；`isFileEncrypted` 对已确认可解密的密文恒返回 `false`。`is_enabled` 正确跟随我们的 `enable()` 调用（false→true），说明 `this=NULL` 的成员函数调用约定本身是对的，失败不是调用约定问题。

**推论（未验证）**：这些静态 API 可能面向另一种容器（如加密素材文件），或要求文件位于草稿原始路径/带特定命名。按 scope 的有界探测原则**停止试探**，不做逆向求证。

**Path**：`temp/crypto-probe/variants/variant-*.out`（全 0 字节）、`scripts/jy_crypto/dll.py::DllCrypto.probe_path_api`。

## 探测 2：内存串 API —— 通过

调用形态：`decrypt(this=NULL, out*, in*, params*, ok*)`，`params` 传 `"{}"`；`encrypt` 前先 `enable(true)`。字符串按 MSVC x64 `std::string` 布局传递（16 字节内联缓冲 + size + capacity，SSO 阈值 16）。

结果：密文 → 合法 JSON，含 `tracks` 与 `materials`（`is_minimal_draft` 空草稿除外，见下）。

## 门禁结果（20 份样本：10 legacy + 10 hybrid）

| 门禁 | 通过 | 说明 |
|---|---|---|
| 等长（重加密后长度与原密文一致） | **20 / 20** | 例：348,948 B → 348,948 B |
| 字节相同（重加密后与原密文逐字节一致） | 0 / 20 | **预期不成立**，见下 |
| 语义回环（明文→密文→明文，两次明文全等） | **20 / 20** | 硬门禁 |
| 外部 oracle（我们的明文 sha256 == `jianying-editor-skill` CLI 输出） | **20 / 20** | 硬门禁；测试期对照，非运行时依赖 |
| 源文件未被改动（扫描前后全文件 sha256） | **20 / 20** | 只读保证 |

原始记录：`temp/crypto-probe/probe-log.json`、`temp/crypto-probe/gate20.json`。

### Finding：加密含随机熵，字节级回环不可能成立

重加密产物**长度完全相同但 sha256 不同**（例：原密文 `d6d5b5e2…` 348,948 B → 重加密 `f533a8e7…` 348,948 B）。导出表中的 `calcEntropyDynamicString`（返回 `pair<string, array<char,208>>`）与此一致：密钥/IV 含动态熵。

**因此门禁定义已修正**：字节相同降级为**信息项**，硬门禁 = 等长 + 语义回环 + 外部 oracle + 源文件未变。原计划里的「字节回环」判据据此作废（`docs/spec/crypto.md` 记录修正后的判据）。

### Finding：存在 `is_minimal_draft` 空草稿

20 份里有 2 份（一份 hybrid 时间线副本、一份 legacy 根内容）解密后只有 922 B，顶层键为
`canvas_config, config, function_assistant_info, id, is_minimal_draft, keyframes, last_modified_platform, materials, new_version, path, platform, render_index_track_mode_on`，**没有 `tracks` 键**。

**含义**：解析器与渲染器必须容忍 `tracks` 缺失；不能用「有没有 tracks」判断草稿是否有效。已记入 `docs/spec/layout.yaml` 待办。

### Finding：顶层键里已有合成顺序线索

解密样本的顶层键包含 `render_index_track_mode_on`、`free_render_index_mode_on`（见另一份样本）、`group_container`。这与「合成顺序」空白直接相关，由全语料扫描统计其出现率与取值分布（`temp/corpus-scan/csv/interesting_keys.csv`）。

## 探测 3：11.7 冷进程内存解密静默返空（2026-11-02）

**现场**：会话中途剪映自动升级 `11.6.0.14552 → 11.7.0.14652`（14:54 仍在 11.6，16:50 已是 11.7）。
升级后 `gate.py` 报 `FAIL: no plaintext produced`，且 `jianying-editor-skill` 那条外部 oracle CLI
同样写出 0 字节 —— 两条独立通路同时空产出，说明问题在 DLL 侧而非我们的绑定侧。

**有界变体矩阵**（`temp/playback-test/probe_matrix.py`，16 格全跑）：
`decrypt` 2 个重载 × `params` `"{}"`/`""` × `enable` True/False × 输入{自建密文, 草稿快照密文}。
**16 格全部 `len=0`**。`isEnable` 正确跟随 `enable()`（调用约定仍然对），
`maybeEncrypted` 对两种密文都返回 **True**（容器被识别）。

**关键判别（同进程自回环）**：用 11.7 自己的 `encrypt` 产密文再喂回自己的 `decrypt`，
`ok=true / out=0`。这条不牵扯密钥库、草稿路径与参数格式 —— 契约在 11.7 上就是断了。
对照：11.6 的同一测试 `equals=True`（探测 2 的「语义回环 20/20」硬门禁即此条）。

**导出表未漂移**：11.7 的 `EncryptUtils@lvve` 家族 14 个符号，mangled 名与 11.6 **逐字符相同**；
全表 33,128 个导出中含 `ncrypt` 的 25 个里，新增可见的只是
`EncryptedFeatureManager@lvve`（`instance()`/`needEncrpyt`/`initEncrpytedFeatureList`）与
`draft_store` 的 `isDraftEncryptionEnable` 一族。**没有继续试探**：这些是应用侧初始化状态，
猜它的入参就是逆向，超出本层授权（scope 的有界探测原则）。

### 恢复路径：更新器留了已知良好副本

升级把旧文件**改名**而非删除：`11.6.0.14552/videoeditor.dll_d_17b9036`，
72,547,608 B，sha256 `8cfcbb612ccd946df974428977b1902736c1de0ae561e20c26cbd4ea86099cb1`
—— 与本文件「目标」表记录的 11.6 基线**完全一致**。

| 步骤 | 结果 |
|---|---|
| 把 66 个 `*_d_*` 复制回 `temp/dll-11.6/` 并去掉后缀 | 65 文件；DLL 按目录解析同级依赖，改名后才能 `LoadLibrary` |
| `JIANYING_VIDEOEDITOR_DLL` 钉住该副本 | 相对路径会让 `os.add_dll_directory` 抛 `[WinError 87]`，**必须绝对路径** |
| 解密 11.7 重存过的草稿快照 | 1,052,176 → **789,079 B 合法 JSON**（`{"id":"017E2FEC-…"`） |
| 同进程自回环 | `plain=234 → cipher=384 → back=234 equals=True` |

**推论**：密文容器与密钥轴未变（11.6 能解 11.7 写的），变的是 11.7 的 `decrypt` 需要应用侧
初始化状态才肯干活。因此这是**版本漂移**，不是格式换代。

### Finding：`ok=true` 不等于有明文

`decrypt_bytes` 原先把「没抛异常」当成功，于是 11.7 的 `ok=true / 0 字节` 既**掩盖了失败**，
又**短路**了后备重载（后备其实也返 0，但这条当时看不出来）。已改为：只有非空输出算成功，
空输出一条条记进错误并继续试，全失败则抛错并带上 DLL 版本 —— 0 字节 `plain.json` 从此不可能
被当成解密成功。

## 探测 4：门禁在钉住的 11.6 上重跑，并用「另一个实现」定位故障归属（2026-11-02）

`JIANYING_VIDEOEDITOR_DLL` 指向 `temp/dll-11.6/videoeditor.dll` 后三道门全过：

```
python scripts/jy_crypto/gate.py --samples 6 --oracle
  ok=True  samples=3  g1_length_preserved_pass=3  g1_byte_identical_count=0
  g2_semantic_roundtrip_pass=3  g3_oracle_pass=3  sources_untouched=True  layouts=["hybrid"]
  hybrid PASS 中智矩阵 10月28日 (10) / 恒锋 11月2日 齿条丝锥二2 / 李金昌 10月15日 (4)
```

`--samples 6` 实到 3：语料里只有这三份是「有密文且非最小草稿」的 hybrid 样本，不是截断。

### 但 G3 通过证明的东西比看起来少

`gate.py` 的外oracle 是 `~/.agents/skills/jianying-editor-skill/scripts/jy_draft_crypto.py`，
它**也**认 `JIANYING_VIDEOEDITOR_DLL`（`find_jianying_dll()` 第一优先级）。所以这一轮两边加载的是
**同一个 DLL**：G3 校验的是「我的 ctypes 绑定 == 他们的调用序列，在同一 DLL 上逐字节同明文」，
**不能**被引用为「这个 DLL 能解密」的证据 —— 后者只由 789,079 B 明文本身和自回环支撑。

### 决定性的一测：故障在 DLL，不在绑定

把环境变量拿掉，让他们的 CLI 自己去找，它加载现装的 11.7 并写出：

```
{"ok": true, "output": "temp\\playback-test\\g3-117.json", "dll": "D:\\Program Files\\JianyingPro\\11.7.0.14652\\videoeditor.dll"}
-rw-r--r-- 1 ... 0 Nov  2 17:29 g3-117.json          ← 0 字节，仍然 ok=true
```

两个**互不相干**的实现（不同的调用序列、不同的进程、共享的只有那个 DLL）在 11.7 上给出同一个
`ok=true / 0 字节`。这排除了「我的签名模型/ABI 猜错」这条解释路径，把故障钉在 DLL 侧 ——
与探测 3 的「11.7 对它自己 encrypt 的产物也返空」一致。

### 移交给 jianying-editor 那条线的隐患（本项目不改它）

他们的 CLI 在 11.7 上会**静默产出 0 字节文件并返回 `ok:true`**，退出码 0。对只读预览无害，
但对「解密→改→再加密写回」的编辑流程是数据丢失路径：一次 `--decrypt` 拿到空文件，若被当成
「这个草稿本来就是空的」继续往下走，回写就会把草稿清成 0 字节。建议他们把 `ok` 判定改成
「输出非空」，与本项目 `decrypt_bytes` 的守卫（探测 3 Finding）同一口径。**不在本 Skill 里动手**：
草稿只读，且那是另一个 Skill 的代码。

### 恢复动作已脚本来化

`scripts/rebuild_dll_sandbox.py`（已入库，替掉原先住在 `temp/` 的一次性脚本 —— `temp/` 已经被清过一次，
配方只活在文档里等于没有配方）：

- 安装目录**只读**，落点由 `cache.assert_scratch_target` 兜死在 `temp/`（实测拒绝 `--out` 进安装目录）；
- 按还原后的名字归组，**同名多份就拒绝猜测**（下一次 11.7→11.8 升级会在同一目录叠出两套残留，
  靠 `_d_<tag>` 后缀区分不了：实测后缀每个文件都不同 `17b8355/17b8365/17b8384/…`，只有**目录**能区分版本）；
- `--sha256` 与基线不符则非零退出，且**验副本**（沙箱里的 `videoeditor.dll` 与源文件 sha256 不同也退出）；
- 幂等：重复重建时按 size 跳过已拷文件，实测第二次跑「写入 0 个文件」。

## 探测 5：组合子画布的渲染件——**视频腿密文、alpha 腿明文**（2026-11-03，只读文件头）

起因不是加密问题，是找**配对成片**（门 S5 的 `--oracle-mp4`）。有界只读扫描（`temp/find_oracle.py`：C:/D:/E:/X:/Y: 浅层 + 目标草稿目录内 3 层），
按名字含「李金昌」或时间轴 uuid 筛 mp4/mov。全盘**没有**整条时间轴的导出件；唯一像"剪映自己渲染出来的东西"的是
`<草稿>/Resources/combination/` 里的三对：`<uuid>_video.mp4`（20 / 8 / 6 MB）与它们的 `<uuid>_video.mp4.alpha.mp4`（≈0 MB）。
只读前 64 字节 + `ffprobe` 头部（**没有任何解密尝试、没有算法侧动作**）：

| 文件 | 头 24 字节可读部分 | ffprobe |
| --- | --- | --- |
| `..._video.mp4` ×3 | 乱码（无 `ftyp`） | `moov atom not found` ⇒ **密文** |
| `..._video.mp4.alpha.mp4` ×3 | ` ftypisomisomiso2avc1mp4` | 正常解析 ⇒ **明文** |
| `..._audio.a*` ×2 | 乱码 | `Error decoding AAC frame header` / `channel element 2.4 is not allocated` ⇒ **密文** |

- 结论口径：**同一目录、同一 UUID 的派生下，主视频腿与音轨腿被加密、alpha 腿是明文**。
  这只是"哪些文件在密文域里"的一条新事实，**不能**外推成"alpha 不参与加密是因为它不重要"，也不能当破解线索。
  与已有的写围栏口径一致：`combination/` 属草稿自己的目录，本 skill 一律只读、不写、不碰。
- **对 S5 的判读：这些件不是 oracle**。它们是按 UUID 的**子画布合成分量**（段级），不是 36.83 s 整条时间轴的输出；
  `--pixel-t` 比的是时间轴某一秒的整帧，拿段级合成分量冒充 oracle 会得到一个"看起来过了"的假判据。
  ⇒ #19/#20 仍**卡在缺配对成片**，需要用户给出绝对路径（`JY_ORACLE_MP4` 实测两个作用域都为空）或**授权导出一条成片**
  （导出会在草稿目录写文件，属需批准的动作，不自行触发）。

## 探测 6：门禁的 PASS 读的是上一轮留下的陈货（2026-11-03，等窗口期间做的非时间读数）

**现场**：12:59 `python scripts/jy_crypto/gate.py --samples 6 --dll temp/dll-11.6/videoeditor.dll`
⇒ RC=1，三条样本 **1 PASS / 2 FAIL**（`no plaintext produced`），summary 里
`sources_untouched=false`。看起来像"通道又坏了"。

**直读探针**（`temp/playback-test/crypto_channel_probe.py`：显式把 dll 传给
`client.decrypt_bytes`，源前后各算一次哈希，明文只进围栏内的 `temp/crypto-probe/`）：
四份草稿（target `李金昌 10月15日 (4)` + 门禁那三条）**全部解开**，target 明文 789,079 B /
sha `4b76d2ae…` 与在册 `temp/playback-test/plain.json` **逐位一致**，四条源哈希前后未变；
把同一份密文喂给 `11.7.0.14652/videoeditor.dll` ⇒ 0 字节（与探测 3 一致）。
⇒ **通道没坏，坏的是门禁**。两处缺陷：

1. **`--dll` 只进了 identity 的 `report`**（`gate.py:202`），样本里三次 `call`
   （decrypt / encrypt / re-decrypt）一律 `dll=None` ⇒ 走 `discover_dll()` ⇒ 今天解析到 11.7。
   于是同一次运行里有两个互相矛盾的"DLL 是谁"：summary 打 `dll: …temp\dll-11.6…`
   （来自 report op），错误串钉 `in 11.7.0.14652`（来自真正干活的 worker）。**读哪一个都会错。**
2. **产物按源 sha 前 16 位命名、跑前不清空** ⇒ 上一轮（11-02）留下的 `<key>.memapi.json`
   被这一轮当成"刚解出来的明文"：`中智矩阵 10月28日 (10)` 那条 G1/G2 全 True，而这一轮
   的解密一条都没成（`worker_errors` 就摆在同一条记录里）。G2 更绕——`<key>.replain`
   也是同名陈货，于是"重解密等于原明文"是**两份旧文件互相印证**。
   顺带：`sources_untouched = all(r.get("source_untouched"))` 把"没检查"(早退样本里是 `None`)
   与 `False` 混成一个数 ⇒ "草稿全程未被动过"这条安全声明在那两条样本上其实没测过。

**改法**（`scripts/jy_crypto/gate.py`）：每条样本开工前 `unlink` 四个产物并把清掉的文件名记进
`cleared_stale`；`dll=` 打进那三次 `call`；早退路径也补 `src_sha256_after`。

**两条对照**（现场读数，同一条命令、只差 `--dll`）：

| 跑 | 结果 |
| --- | --- |
| 13:12 `--samples 6 --dll …/temp/dll-11.6/videoeditor.dll` | **3/3 PASS**，`sources_untouched=true`，RC=0 |
| 13:13 `--samples 6`（不带 `--dll`） | **0/3**，全 `no plaintext produced`，RC=1，失败样本现在也报 `untouched=True` |

改前那次是"1 过 2 败"，其中那个"过"来自陈货；改后带钉全过、不带钉全败——**这才是要的形状**。

**修正探测 4 的口径**：11-02 那次三道门全过**结论不变**（当时 shell 里 export 了
`JIANYING_VIDEOEDITOR_DLL`，`discover_dll` 与报告都指 11.6，不是靠 `--dll`），但那次的 PASS
拿不到"这一轮亲测"的分量。凡引用本文件探测 4 的门禁读数，加一条口径：
**要么 export `JIANYING_VIDEOEDITOR_DLL`、要么带 `--dll`（改后才真正生效），二者其一，否则样本跑在自动发现的那个 DLL 上。**

**规矩一条**：按内容哈希命名的 scratch 产物，跑前不清空 = 上一轮的输出会被读成这一轮的。
这与 `evidence/playback-log.md` P-116 ① 的 `tasklist /NH` 被改写、⑮ ⓐ 的正则截断同族：
**取数的那条自己坏了，读数就全废**——而且这一族坏法不报错，只会多给一个绿色。

## 结论

- **唯一已验证的调用面 = 内存串 API**（`decrypt` 4 参重载优先，3 参重载后备）。
- 路径级 API 在本场景不可用，记为**未解决**（`docs/evidence/unresolved.md`），不阻塞后续工作。
- 所有 DLL 调用都在子进程内完成，结果写文件而非 stdout，进程以 `TerminateProcess` 结束以跳过 DLL 的 detach banner；主进程从不加载 DLL。
- 写围栏（`scripts/jy_crypto/cache.py`）拒绝任何落在草稿语料或剪映安装目录内的写入，产物只进 `temp/`。
- **`videoeditor.dll` 的 sha256 是可复现性基线的一部分**，与 `pixi.js`/`mediabunny` 的固定版本同级：
  已知良好 = `8cfcbb61…`（11.6.0.14552）。剪映升级后先跑自回环，再决定用哪个 DLL；
  需要旧版时用 `JIANYING_VIDEOEDITOR_DLL` 钉住绝对路径（恢复动作见 `scripts/rebuild_dll_sandbox.py`）。
- **判断「是 DLL 变了还是我绑定错了」要有第二只眼睛**：拿另一个独立实现（这里是 jianying-editor 的
  `jy_draft_crypto.py`）在同一 DLL 上对照。两边同时 `ok=true / 0 字节` 才算把故障钉在 DLL 侧；
  只看自己那条路径的失败，永远分不清绑定问题与产品问题。
- **G3 通过 ≠ DLL 可信**。两边共用同一个 `JIANYING_VIDEOEDITOR_DLL`，所以 G3 是同一 DLL 上的
  实现一致性检查，不是版本合格证明。
