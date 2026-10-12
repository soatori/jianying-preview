# 工作区整理与跨设备交接报告（2026-10-12）

## 1. 本轮已落地

- `main` 已从 `83db567` 快进并推送至 `d542d0886ee7c44cc4e77fdaee4b2f9ed38d056a`。
- `release` 的 42 个历史提交，加上本轮 `.gitignore`、播放计划/规格修正和 EOF 整理，已合并到 `main`。
- `origin` 新增两个可继续执行的工作分支：
  - `codex/dll-native-preview` → `0ba421761fb38078c731a8bfe7fb9fbfe350330c`
  - `codex/stale-seek-fix-20261002` → `25ebffa91c2e44a749fe3cd197f2ce6d0db2b073`
- 未推送 `private-unsanitized-backup`；其历史明确要求只保留在本地。

## 2. 工作区状态

| 工作区 | 当前引用 | 状态 | 交接说明 |
|---|---|---|---|
| `E:\Develop\jianying-preview` | `release` | 源码/文档已提交 | 合并后需再快进到 `main` |
| `d215`（当前工作区） | `main = d542d08` | clean，已与 `origin/main` 同步 | 作为下一轮主入口 |
| `4669` | `codex/dll-native-preview = 0ba4217` | clean；构建产物已被忽略 | 继续 DLL Task 1 阻塞诊断 |
| `a191` | `13fc2b1`（detached） | clean；重复规格文件已移除 | 历史检查点，不作为主入口 |
| `59b5` | `83db567`（detached） | clean | 旧 `origin/main` 检查点 |

`4669` 中保留但已忽略的本地产物：`temp/`、`.pi/`、`scripts/jypreview/native/bin/`、`scripts/jypreview/native/obj/`、`nul`。这些不是提交内容；需要复跑原生门槛时可直接复用，若换机器则按报告中的命令重建。

## 3. 本轮已验证（新执行）

以下命令在本轮实际运行并返回 0：

```powershell
$env:PYTHONPATH = 'scripts'
py -3.14 -m jypreview.tools.test_timeline_model
node scripts/jypreview/tools/test_playback_kernel.mjs
py -3.14 -m compileall -q scripts
git diff --check origin/main..HEAD
```

DLL 分支另跑了当前工作树的 17 项 gate self-test，结果为 `Ran 17 tests ... OK`，退出码 0。

尚未声称通过的检查：

- `test_backend_lifecycle`：默认 Python 3.14 缺少 `aiohttp`，导入阶段失败。
- `test_mlt_compiler`、`test_mlt_controller`：默认解释器缺少 `mlt7`，属于运行时缺失，不是本轮代码回归结论。
- 完整 DLL native gate 本轮没有重跑；最近一次完整记录仍是 24 项、2 项失败（见下节）。

## 4. 未完成事项与优先级

### P0：恢复隔离 MLT 运行时并重跑完整回归

当前 shell 的 `JY_PREVIEW_MLT_PYTHON` 未设置；历史记录中的运行时路径为：

`C:\Users\cbsjz\.codex\worktrees\mlt-runtime-prep\jianying-preview\temp\mlt-runtime\ucrt64\bin\python.exe`

该路径在本轮检查时不存在。先按 `docs/native-backend-evaluation/2026-10-01-mlt-gate.md` 恢复运行时和 `process-env.ps1`，再执行计划中的：

```powershell
$env:PYTHONPATH = 'scripts'
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_compiler
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_controller
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_acceptance --av-evidence temp/mlt-av-evidence.json
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.benchmark_mlt --json temp/mlt-benchmark.json
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_playback_state
```

完整清单和停止条件见 `docs/superpowers/plans/2026-10-03-playback-remaining-execution.md`。

### P0：播放验收仍未完成

以 `docs/native-backend-evaluation/2026-10-03-playback-remaining-status.md` 为准：

- 严格 B1 显示节律未满足：生产页观测约 `29.999238 fps`，不能四舍五入成通过。
- 25ebffa 的一次完整 controller 运行在 5 秒 native startup-readiness 门槛失败（SDL audio timeout）；后续没有 broad retry 或新的 native/page 重测。
- T1/T2 实际呈现与设备发射仍未验证；T3/T4 精度未重新采集。
- 外部 ≥240fps 屏幕+音频标定、匹配的剪映真实导出对照仍缺失。
- Task 6 的同步 capture、正常/dropped-video 双模式证据，以及 Task 7 的旧模块删除门槛均未通过。

下一台设备不要根据“内部 graph 时间戳正常”跳过 capture/export 门槛。

### P1：`codex/dll-native-preview` 仍停在 Task 1

最新完整记录位于 `4669` 的 `temp/dll-native-preview-review-hardening/`：

- `24` 项中 `22` 通过、`2` 失败，`errors=[]`。
- `PlayerWin`：`init_rejected`，不能用伪造配置或空 `this` 绕过。
- `FrameReader`：190/190 尝试、157 成功、33 个随机访问请求 `pts_out_of_range`；连续 90 帧全部成功。
- 输入哈希前后不变：`C0308.MP4`、2868 文件草稿树均未被修改。
- 按该计划的停止规则，Task 2–7 尚未开始；不要直接把这个分支当作已验收的渲染后端。

当前 17 项 IPC/JSON/重复字段 self-test 已通过；下一步应先修复或隔离上述两个原生门槛，再考虑接入 Python PlaybackBackend。

### P1：`codex/stale-seek-fix-20261002` 尚未合并

该分支包含 still lane、JPEG 流和 readiness 相关 8 个提交，但 `release`/`main` 没有合入。其状态报告明确说明：候选 `204e731` 的质量审查未通过严格 B1，后续 `25ebffa` 只改测试且一次完整 controller run 失败。

合并前必须补齐：

1. 完整 controller 生命周期与 SDL startup-readiness 重跑；
2. 45 秒 1080p 夹具的 direct-consumer + 浏览器 B1≥30fps 实测；
3. 独立审查，并保留原始 trace/失败日志。

## 5. 下一台设备的最短启动序列

```powershell
git fetch origin
git switch main
git pull --ff-only
$env:PYTHONPATH = 'scripts'

# 先做不依赖 MLT/aiohttp 的快速检查
py -3.14 -m jypreview.tools.test_timeline_model
node scripts/jypreview/tools/test_playback_kernel.mjs
git diff --check origin/main..HEAD

# 再恢复隔离 MLT runtime，最后跑完整播放/DLL 门槛
```

如果要继续未合并工作，按需切换：

```powershell
git switch codex/dll-native-preview
git switch codex/stale-seek-fix-20261002
```

## 6. 证据索引

- 播放剩余状态：`docs/native-backend-evaluation/2026-10-03-playback-remaining-status.md`
- 播放执行清单：`docs/superpowers/plans/2026-10-03-playback-remaining-execution.md`
- MLT 运行时来源与复现：`docs/native-backend-evaluation/2026-10-01-mlt-gate.md`
- DLL 完整门槛原始证据：`C:\Users\cbsjz\.codex\worktrees\4669\jianying-preview\temp\dll-native-preview-review-hardening\`
- DLL 计划与规格：`docs/superpowers/plans/2026-10-05-jianying-dll-native-preview.md`、`docs/superpowers/specs/2026-10-05-jianying-dll-native-preview-design.md`

报告只记录已实际观察到的状态；缺失的运行时、capture、export 或门槛证据均明确标为未验证。
