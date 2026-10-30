# crypto —— 剪映草稿加解密的调用规格（自研实现照此执行）

范围：`draft_content.json` 等时间线文件的密文识别、解密、（M3）加密写回。
本项目**不实现、不推断、不发布任何算法**；加解密一律通过剪映自带的 `videoeditor.dll` 在用户本机完成。
实测证据见 `../evidence/crypto-probe-log.md`（F-003）。

## 1. 密文判定

| 观察 | 判定 | 依据 |
|---|---|---|
| 首字节为 `{` 且能解析为 JSON 对象 | 明文 | 内容判定，不看版本号 |
| 首字节为 `{` 但解析失败 | **损坏**（不是加密） | 两种失败必须区分，否则把坏文件当密文去解密 |
| 首字节非 `{` | 密文（6.0+） | 语料实测（r3，快照 2026-10-16）：1475 个草稿目录里 907 个含密文；按去重内容是 1713 份密文 / 337 份明文 |

- **不要**用 `videoeditor.dll` 的 `isFileEncrypted(const char*)` 做判定：实测对已确认可解密的密文副本恒返回 `false`（`enable` 开关前后都一样）。判定用首字节 + JSON 解析。
- 编码由**内容**决定，不由草稿版本决定：读时先按 UTF-8(-sig) JSON 试解析，失败才走解密。写回时**保留该文件原有的输出编码**（明文保持紧凑 JSON、密文保持加密容器）。

## 2. DLL 发现顺序

1. `JIANYING_VIDEOEDITOR_DLL` —— 指向确切文件时**一票优先**（用于钉死版本），文件不存在直接报错，绝不静默回落。
2. 安装根候选：`%LOCALAPPDATA%/JianyingPro`、`%ProgramFiles%/JianyingPro`、`%ProgramFiles(x86)%/JianyingPro`，以及 `C:`/`D:`/`E:` 的 `Program Files/JianyingPro`；本机制定安装根为 `<JY_INSTALL>`。
3. 注册表卸载项中 DisplayName 含 `jianying`/`剪映` 的 `InstallLocation`/`DisplayIcon`。
4. 在每个候选根下查 `videoeditor.dll` 与 `<版本目录>/videoeditor.dll`，**用路径中的版本号取最新**；再按「导出表里是否存在 `EncryptUtils@lvve`」过滤（不是所有版本都带该 DLL：本机 14 个版本目录中仅 2 个携带）。

## 3. 调用面

### 3.1 符号解析：按模式匹配，不硬编码 mangled 名

用 PE 导出表（本项目 `scripts/jy_crypto/pe.py`，标准库实现）枚举全部导出名，再以 `EncryptUtils@lvve` + `?decrypt@` / `?encrypt@` / `?enable@` / `?isEnable@` 子串匹配解析。理由：mangled 名随编译器版本与类模板参数变化，硬编码会在剪映更新后静默失效。

### 3.2 内存串 API（唯一已验证可用）

| 导出（解析后） | 用法 |
|---|---|
| `decrypt`（带 `ok` 出参的重载，mangled 尾 `AEA_N@Z`） | `(this=NULL, out*, in*, params*, ok*)`；`params` 传 `"{}"`；`ok==false` 视为失败 |
| `decrypt`（不带 ok 的重载） | 后备，签名同上少一个出参 |
| `encrypt` | `(this=NULL, out*, in*)`；**调用前必须先 `enable(true)`** |
| `enable` / `isEnable` | 成员函数，`this` 传 NULL 可用；`isEnable` 用于确认开关状态生效 |

`std::string`（MSVC x64）布局：16 字节内联缓冲 + `size` + `capacity`；`len < 16` 走内联（`capacity=15`），否则前 8 字节存堆指针（缓冲需以 `\0` 结尾并由调用方保活）。

### 3.3 路径级静态 API —— 已探测不可用，且已从代码删除

`decryptFile(const char*, const char*, const char*) → int`、`encryptFile(…)`、`decryptFileBytes(…)`、`isFileEncrypted(const char*)`：对草稿密文副本的 8 个变体（enable 开/关 × 第三参 `""`/`"{}"` × 参数顺序两种）全部 `status=1`、0 字节输出，`isFileEncrypted` 恒 `false`。原因未查证（不做逆向），记在 `../evidence/unresolved.md` U-16（已定案）。

**这些绑定在 r2 已整体删除**（`dll.py` 的 `is_file_encrypted`/`decrypt_file`/`encrypt_file`/`probe_path_api` 与 worker 的对应 op）。删除理由不只是「没用」：`probe_path_api` 的 `dst_src` 变体会把**草稿原始路径**作为第二个 `const char*` 交给一个参数方向未证实的导出，而 `cache.py` 的写围栏只能校验我们自己选定的那个目标——这是本项目唯一可能让 `videoeditor.dll` 往草稿目录里写东西的调用点。零收益、非零风险，故不提供该表面；内存串 API 是唯一入口。

## 4. 副作用与隔离（硬约束）

- `videoeditor.dll` 约 72 MB，加载时会向 stdout 冲 banner，且每次 `decrypt`/`encrypt` **泄漏一个堆块**（DLL 未导出 `~basic_string`，无法释放返回的缓冲）。
- 因此：**主进程（含 Web 服务、浏览器网关）绝不加载 DLL**。每次批处理起一个子进程 worker，结果写入**文件**（不依赖 stdout），处理完用 `kernel32.TerminateProcess` 直接结束进程以跳过 detach。
- 单批上限：40 个文件后换新 worker（r2 实测 1877 份密文文件 → 47 批；明文缓存按内容 sha256 命中，重跑时只有当天新增/变更的 9 份真正走解密，无内存问题）。
- 写围栏：任何加解密产物只允许落在本仓库 `temp/` 下；`scripts/jy_crypto/cache.py` 对目标路径做前缀检查，命中草稿语料根或剪映安装根即抛 `WriteFenceError`。

## 5. 门禁（不满足即停止，不写任何东西）

对每批实现，以下三条必须同时成立：

1. **等长**：`len(encrypt(plain)) == len(original_cipher)`。
2. **语义回环**：`decrypt(encrypt(plain)) == plain`（逐字节）。
3. **外部对照**：抽样 ≥20 份密文，我们的明文与 `jianying-editor-skill` CLI 的输出 sha256 逐字节一致（测试期对照，非运行时依赖）。

明确**不作要求**：`encrypt(decrypt(cipher)) == cipher`。实测 20/20 份重加密等长但摘要不同（容器含随机熵，导出表另有 `calcEntropyDynamicString`），因此该等式在本格式下不可能成立，把它当门禁会永远卡住。

M3 写回前额外要求：对目标文件先做 2+3，再执行快照/原子替换流程（见 `write-rules.md`）。

## 6. 版本兼容

- 已验证版本：剪映 `11.6.0.14552`（主）与 `11.1.0.14287 - 副本`（DLL 备用）。
- 若某版本调用不通：不猜测、不降级到「猜算法」，回退到已验证版本，并把该版本写入 `../evidence/unresolved.md`。
- 平台：仅 Windows（DLL 与 `ctypes.WinDLL` 决定）。macOS 草稿的加解密不在本规格范围内。
