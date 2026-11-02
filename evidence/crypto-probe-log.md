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

## 结论

- **唯一已验证的调用面 = 内存串 API**（`decrypt` 4 参重载优先，3 参重载后备）。
- 路径级 API 在本场景不可用，记为**未解决**（`docs/evidence/unresolved.md`），不阻塞后续工作。
- 所有 DLL 调用都在子进程内完成，结果写文件而非 stdout，进程以 `TerminateProcess` 结束以跳过 DLL 的 detach banner；主进程从不加载 DLL。
- 写围栏（`scripts/jy_crypto/cache.py`）拒绝任何落在草稿语料或剪映安装目录内的写入，产物只进 `temp/`。
