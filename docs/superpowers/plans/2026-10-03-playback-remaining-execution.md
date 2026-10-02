# 播放预览剩余任务执行计划

> 用户于 2026-10-03 明确批准执行。执行方式：superpowers:subagent-driven-development；每项修复独立提交和审查，同一工作区只有一个代码写入者。

**Goal:** 从 ff578da 关闭 seek 竞态及图片图结构节律问题，完成真实 A/V 验收、导出对照、合并清理。
**Architecture:** 复用现有 MLT audio consumer 和浏览器帧身份协议；修复客户端提交屏障与原生 seek 复位，并仅合并兼容的顺序 still lane。采集按既有 fallback 分阶段证明精度，证据达标后执行旧模块删除。
**Tech Stack:** Python 3.14 / MLT 7.40 / SDL DirectSound / JavaScript / aiohttp / Pillow。
**Spec:** 2026-10-01-timeline-playback-preview-engine.md、2026-10-01-timeline-playback-preview-engine-design.md、2026-10-02-timestamped-browser-av-channel-design.md。

## Global Constraints

- 保留原验收算术、DirectSound 默认驱动和当前输出设备；临时产物仅写根 temp/。
- 用户已有修改按文件和修改块保全；文档从 docs/ 提交，仅含本次改动。实测 docs/ 当前属于主仓，不误报独立文档仓。
- 采集失败停止依赖阶段及 Task 7 删除，记录缺失证据；播放代码、运行时或输出设备改变须重新采集。
- 主会话负责协调；代码由 worker 修改，一次一个实现 worker，独立 reviewer；每任务通过后合并 release。

## Review Focus

迟到 snapshot 与连续 seek；native 旧位置造成回退或误 ended；still lane 合并改变 z/空隙/源帧；设备和浏览器计时误差被中位数掩盖；缺真实捕获或导出被误标通过。

### Task 1: seek 提交屏障与原生复位

Files: scripts/jypreview/web/backend.js、scripts/jypreview/mlt_backend.py；回归在既有 test_playback_kernel.mjs/test_mlt_controller.py，必要的 live harness 放 temp/。
Interfaces: API、帧身份头和返回形状不变；服务端项目帧/时钟仍来自 native audio consumer。

- [ ] renderAt 发出 request ID 时建立 pending；只有匹配 /render 图片或 ended 提交 accepted/tUs/frameIndex。期间 JSON 可更新传输状态；发起于提交前的 snapshot 即使晚到也不能恢复旧时钟。
- [ ] 匹配 render 提交后重启 stream；409、失败、覆盖、close/reopen 按 request ID 与 epoch 清理，旧 finally 不能清新请求。
- [ ] 原生顺序为 stop并join → purge → seek → 捕获目标 → start，沿用 GIL 释放方式。先验证此最小方案。
- [ ] 若旧 consumer.position 仍污染新代，改用仅由真实 audio consumer frame-show 写入的当前代位置；手动 capture 不写。无新输出保持目标/buffering，start 返回后 1.5 秒无新输出进入 error。并发实测发现目标槽被覆盖时，/render 使用独立冻结目标帧。
- [ ] RED/GREEN 覆盖 ack旧8.133→buffering0→playing8.2→render0、旧snapshot晚到、连续seek、409、失败、ended、close/reopen；controller 覆盖播放中回退和接近EOS回退。
- [ ] live 同时验证服务端 snapshot、client clock、显示落到量化目标，返回后两秒继续推进。保存原始 trace，结束自有 server/browser。
- [ ] 测试、提交、独立审查、合并。

### Task 2: 顺序 still lane 合并与 B1 显示节律

Files: scripts/jypreview/mlt_backend.py、test_mlt_compiler.py；只有 B1 在 PNG 下仍不足时修改 server/handlers_backend.py 的 stream 编码与相应 MIME 回归。
Interfaces: 保留原排序、音频解码器/位置映射、keep 所有权、关闭和帧身份语义。

- [ ] 仅合并排序中连续、同原 track/同 z/相同 transform、crop、opacity、blend 的 video-mode image/photo；媒体有效、无 nested/placeholder/effects/animations/任何关联 transition；时间和量化帧区间都不重叠。
- [ ] 每组一个 Playlist，各 clip 保留独立 producer、源帧起点、ID和警告；共享 lane 只保留 track ID，组尾补 blank，共享过滤器挂一次，音频独立。45图片+audio+bg 从47lane降至3。
- [ ] RED/GREEN 覆盖边界、空隙、随机seek；重叠、不同z/属性、效果/转场、损坏媒体及nested按原路径。
- [ ] 在45秒1080p夹具复跑直接consumer与浏览器显示；B1≥30fps。PNG仍不足时 stream 使用JPEG q85和image/jpeg，点帧/render保留PNG，帧身份头不变。
- [ ] 测试、提交、独立审查、合并。

### Task 3: Phase A 精度证明

Files: harness/raw/report仅放temp/；通过后报告摘要写docs/。
Interfaces: 通过条件 T1+T2≤4750µs、T3≤500µs、T4≤500µs、T5≤2583µs、T6=0；任一未证禁止PhaseB。

- [ ] P1a至少900帧，正常及目标负载；记录decode/swap/rAF、slip与实际显示常数证据。
- [ ] T2复用正确DirectSound slot3创建/slot4游标探针，与独立loopback/mic beacon验证插值；采集重试15分钟封顶。10ms步进与500µs中位轮询均不能证明通过，脉冲附近查询间隙须≤500µs。
- [ ] T3使用同server临时持久WebSocket echo≥500样本，30秒播放前后括测；offset区间[S1−T1,S0−T0]交集加量化/漂移的绝对误差≤500µs且交集非空。保留旧原始samples，另出×1000→×1e6单位订正，median CI不代替绝对精度。
- [ ] 缺beacon/精度失败记录unverified并停止依赖阶段，禁止生成合成通过证据。

### Task 4: Phase B/C、真实导出对照与回归

- [ ] PhaseB标定：beacon及≥240fps屏幕+音频外部校验；两次29对并排，各≥27对残差≤9394µs，两次常数差≤2067µs，channel最大残差≤8333µs且零异常，外部差值≤8333µs。复核仍失败停止PhaseC。
- [ ] PhaseC normal/dropped_video各≥30秒、各恰好29对；实际drops至少一次距marker≤1项目帧。维持quarter-frame uncertainty和per-pair一帧算术。
- [ ] evidence形状遵守当前validator：frame_rate:{num,den}、runs[].dropped_frames、dropped模式drops；event仅project_frame/video_capture_us/audio_capture_us。
- [ ] 导出对照需要匹配draft/timeline、源素材、真实剪映导出、FPS/画布/项目帧号；复用现有pull及_load/_similarity，渲染真实模型相同帧，记录差异。输入缺失Step5阻塞。
- [ ] 运行kernel/model/compiler/controller/playback-state/native-preview/acceptance/benchmark；benchmark只记观测值；capture记录最终受测HEAD。
- [ ] 文档订正头名、B1、刷新率、T3/T4、运行配方及schema，报告真实门禁状态。

### Task 5: Task7、最终合并与清理

- [ ] 前置捕获门禁与真实导出对照均完成。删除原计划六个旧模块，保留点帧诊断；kernel仅去旧audio断言，保留MLT回归；native-preview重写MLT并保留ready/loading、playing、pause断言。
- [ ] 旧引用零匹配与最终回归；实际播放路径改变则重采两模式，失败恢复删除提交。
- [ ] 独立审查后合并release，台账记最终HEAD、运行时/设备和证据路径。
- [ ] 删除worktree前确认提交有branch引用、独有证据归档且SHA一致；可恢复归档或无force删除，保留runtime/current及独有修改证据树。
- [ ] 关闭自有servers/browser配置和后台进程，核实残留。
