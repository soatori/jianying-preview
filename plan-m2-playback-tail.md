# M2 播放尾巴的下一步计划（2026-10-28，接 P-95）

**题已经答完**：那笔 ~350 ms 不是 Python 的执行效率（网关 376,323 次请求服务端最大 18.59 ms、
0 次超 100 ms；每请求 Python 成本 ≈0.55 ms），也不是那个源时刻的内容成本（ffmpeg 首帧在
5/20/34/43 s 都是 120–130 ms）。它由两半组成：**预热泵 park 被记成了到货延迟**（点名那几条腿
随 `warm_lead` 0.3→0.005 从 322–387 ms 塌到 37–63 ms），以及**一批与提前量无关的 >100 ms 到货**
（每轮仍有 4–16 段），后者至今没归因。

**赢的判据用哪一个数**（先把口径钉死，别再换尺子）：
`play.frame_cost_ms` 的 **p95 ≤ 33.4 / max ≤ 150**（门里 `L4 frame budget`，整条时间轴、`seeks=0`）。
这是"画面冻住多久"的直接读数。`arrivals.max_ms` **不作为判据**——P-95 证明它对背压和饥饿不分。
`stale_holds` 与 `fresh_track_frames_per_second` 只当分母看。

## 原则性约束（本轮学到的，写死在计划里）

1. 别再按 `arrivals` 调取帧策略：缩提前量会让难看的数变好看、`frame_cost.max` 从 ~120 ms 变 203–249 ms。
2. 归因没到机制之前不动策略（P-92 那句"cost≈泵等待"只到定位）。
3. 任何新渲染路径/新开关都要配一个负样本，并让开关**被证明到达页面**（`URLSearchParams.get` 取第一个匹配，
   同名参数会被前面的默认值遮蔽——P-83/P-87 的 dead-switch 家族）。
4. 计时轮次期间机器必须空闲：我自己的 ffprobe/ffmpeg 并发就把参考臂打坏过一次（P-94）。

## 步骤

### S1 仪表：把一次 push 拆成三段（浏览器侧）
`makePump` 改成手动迭代器，分别记 `await_ms`（阻塞在 `sink.samples()` 内＝Chrome 取字节+解封装+解码）、
`convert_ms`（`toVideoFrame`+`createImageBitmap`）、`park_ms`（队列满等待）；
到货记录同时给 `gap_with_park`（旧口径，保持可比）与 `gap_nopark`（新口径）。
开关 `&split=0/1`，默认开；同时把 `gen`（泵换代）与该帧年龄（`pos - segment.target.start`）记进账里，
用来判"饥饿发生在剪切点还是在段中间"。
**验收**：同一轮里 `gap_with_park` 仍能复现 ~350 ms（证明拆分没把现象抹掉，只是把它归类），
且 `gap_nopark` 的名单不再固定在"剪切点后第 4 帧"。

### S2 仪表：网关按毫秒记时，把"Python 无辜"从聚合改成逐窗
现在 `_note()` 只写 `HH:MM:SS`，所以 P-95 的结论是"这一批请求里没有一次接近 350 ms"，
而不是"那 350 ms 窗口里没有请求"——这是覆盖率的缺口，不是结论的缺口。
补两件事：日志时间戳改 epoch 毫秒；页面在 `/report` 里回送 `epoch_base = Date.now() - performance.now()`，
于是 S1 的每个 `await` 窗口能与"窗口内是否有请求、该请求服务端 ms 多少"直接相交。
顺带加 `--log-max-mb`（默认 64）滚动，别让单文件长到 630 MB。
**验收**：对每一条 `gap_nopark > 100 ms` 的腿，输出「窗口内有/无请求」二选一，且分母写明。

### S3 归因：那批与提前量无关的 >100 ms 到货到底是什么
一轮 4 臂交叉（每臂 n=2，整条时间轴 `seeks=0`、`&probe=` 点名判活）：
默认 / `warm_lead=0.005` / `warm=0` / `qmax=1`。读 `gap_nopark` 的 p95/max 与 `frame_cost` 同步对照，
按 S2 的窗口相交把它分到三堆里：**取字节窗**（有请求且服务端慢）、**解封装/解码窗**（有请求但服务端快，
或无请求）、**转换/上传窗**（`convert_ms` 占大头）。
**验收**：三堆的占比有数字，`frame_cost.max` 最大的那几帧能指到其中一堆；指不到就写"未归因"，不许猜。

### S4 只动一个杠杆，并配对开/关
按 S3 的归属选（不要预先决定）：
- 落在**解码窗** → 代理的关键帧栅格。**实测事实（2026-10-29 更正后）**：配方在
  `temp/playback-test/make_all_proxies.py:38-39` =
  `h264_nvenc -pix_fmt yuv420p -preset p4 -cq 23 -force_key_frames "expr:gte(t,n_forced*1)" -b_strategy 0 -sc_threshold 0`
  ⇒ **每秒强制一个关键帧**（60 fps ⇒ GOP≈60，30 fps ⇒ GOP≈30），不是全 I 帧
  （P-96 那句"全 I 帧 GOP=1"是我把 ffprobe `-of csv` 的列位读错，已在原处更正）。
  所以这一支的具体做法是**去掉 `-force_key_frames`、改 `-g N`**（工具：`make_proxy_gop.py --dry-run` 已验证只差这一个变量；
  A/B：`s4_gop_ab.py --rounds 2`，注意两条最慢腿在 **composite 子画布**内、必须整串替换 13 处而不是只改顶层）；
  改前先量关键帧间隔，**且探测要先自证列位**（`-show_entries packet=flags -of json`，断言源 5 s 窗 K 数 ≈5）；
- 落在**取字节窗** → 预解码深度/提前量（`QMAX`、剪切点后 park）；注意 P-87：`qmax=1` 把 p95 16→3 ms
  但 `Σover-budget` 497→743 ms，尾巴与躯体是交换关系，五个数都要读；
- 落在**转换/上传窗** → 队列里存 `VideoFrame` 还是 `ImageBitmap`（现在是每帧建位图，见 :709-711）。
**验收**：`L4 frame budget` 在整条时间轴上连续绿（当前是**边缘绿**：16+ 读数 88–156 ms，
曾有一轮读 153 转红），且 `warm used/started` 与 `wasted` 的分母随读数一起出。150 ms 这条线**不许为了过关而上移**。

### S5 收尾：门的完整回归 + 记录本 build 的包络
`playback_check.py --oracle-mp4 $JY_ORACLE_MP4 --repeat 2` 全量（含 `--mixmode-gpu`）；
把 `frame_cost` 的分布、`peak_fs`、RSS 一并写进 `docs/evidence/playback-log.md`（新 P 号），
并声明哪些数是 `--repeat 1` 的单点、哪些是分布。

## 不在本计划里（等你的两条，别混进来）
- **音频电平口径**：`peak_fs` 修复后 1.167–1.475、5/5 超满刻度，而成片 float 解码峰 +2.98 dBFS——
  ≤2 GB 那条判据口径（U-79/Q-8）与头余量口径都是**你定**，我不替你选尺子。
  **【已定 2026-10-28】削顶照抄成片，不设 ≤0 dBFS 线**：成片自己 float 解码 +2.98 dBFS、7629 个
  ≥0.9995 的样本 ⇒ 我方超刻度不算失败，判据写成「与成片同向 + 最响窗差若干 dB」，**不加限幅、
  不写"电平已对齐"**。**【已定 2026-10-28】内存 `≤2 GB` 按 peak**（不是 median、不是 p95）：
  当前 600 s 单跑 peak 1767 MB，余量约 14%。两条都并进 S5 的读数口径。
- **M3 写回那一半**：副本在剪映里重开是否报修复，需要人在环里开一次；
  回滚路径（九步事务第 9 步）从未被触发过，本计划不动它。

## 复跑命令
```
python temp/playback-test/py_leg_probe.py --tail-mb 48 --bench-append 300 --big-mb 512   # Python 侧成本
python temp/playback-test/decode_cost.py                                                  # 源时刻贵不贵
python temp/playback-test/lead_ab.py 2                                                     # warm_lead 因果（4 臂×2）

# 全量门。S5 之前这条写的是 `--oracle-mp4 "$JY_ORACLE_MP4" --repeat 2`，**跑不起来**：
# `--plain / --draft-root / --timeline` 是必填（playback_check.py:189-191），而且本机
# `JY_ORACLE_MP4` 在 User 与 Machine 环境里都没设（2026-10-28 实测两个作用域都是空），
# 所以成片 oracle 必须写绝对路径。下面这条的 7 个输入已逐个核到在盘上。
python scripts/playback_check.py \
  --plain "temp/playback-test/plain/<草稿A>__draft_content.json.dec.json" \
  --draft-root "<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>" \
  --timeline 017E2FEC-11D0-47d6-87C1-9709D2A2F18D \
  --model temp/playback-test/model-check.json \
  --media-model temp/playback-test/model-proxy-a.json \
  --oracle-mp4 "<EXPORT_DIR>\<EXPORT_NAME>.mp4" --pixel-t 1.0 --pixel-colour 255,255,255 \
  --cover "<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>\draft_cover.jpg" \
  --cover-frame "<DRIVE_D>/JianyingPro\<DRAFT_ROOT>\<草稿A>\Resources\cover\BA76BCB5-DF8C-40e0-B7DC-42A8BEA03BFB.jpg" \
  --video-scan 0.05:0.55:0.05 --mixmode-gpu --repeat 2
```

## 执行状态与交接（2026-10-29 上午，写给"暂停后接手的人"）

### 已完成，且有盘上证据 + 已落档
- **S1+S2 仪表**（P-96）：`player/player.html` 1999→2136 行（三段拆分 `await/convert/park`、`&split=0/1`
  且 `split=0` 是**改前原样**的自身负样本、`slow_legs={gaps,over,dropped,rows,cap}`、`switches` 含 `search` 原文、
  `epoch_base/epoch_sent`）；`scripts/preview_gateway.py` 384→455 行（`epoch=<毫秒>` + `run=<id>`、
  `--log/--log-max-mb(64)/--run-id`、超限**改名归档**不删）。读数：`s1-split-summary-main.json`、`s2-intersect-main.json`。
- **归因（S3 本体）**：8 轮里 `np>100 ms` 的腿**全部**落在解封装/解码窗，取字节窗 0、转换窗 0
  ⇒ 本计划的"只动一个杠杆"收敛到**材料侧解码成本**。判废的 `r2qmax1/r2nowarm` 与其证据一起记在
  P-96 的「S3 臂间读数」子节（不许用它证明"关预热会崩"）。
- **门的牙齿**：`--skip-jank` 现在会留 `SKIP` 行、`L6` 不再把没跑过的整条/直播跑计进分母
  （`scripts/playback_check.py:478 / :527 / :536`）。**注意末尾"N of N passed"把 SKIP 也算作未失败**，
  所以报绿必须连 SKIP 条数一起报。
- **口径**：复跑命令已补全必填参数；两把尺子定案（削顶照抄成片不设 ≤0 线、内存按 peak）写在
  `docs/evidence/unresolved.md` 的「口径已定案（2026-10-28）」。

### 在飞 / 已排队
- **已完成（2026-10-29）**：**S5 全量门** → P-97：`25 of 28`（22 判绿 + 3 INFO + 3 红，rc=1），
  `L4 frame budget` **连续绿**（4 点 max 101–110 / p95 恒 16 / warm 22/22 白热 0 废 0）；
  三红 = `L10 t=1.0`（字体天花板 F-084，线不动）+ `L4 live pacing` + `L6`（同一跑直播节奏 `846DA305`，
  独立复测 5 次不可复现 ⇒ 未归因）。**#7 取字节窗判据**已改为 await 窗逐请求量，真实回归 **15/15 落解码窗**
  （`s7-regress-real.json`，gaps 合计 21058），并留下约束：**只能作排除法依据**（排除"网关单请求慢"），
  分不清连接池排队与解码堆，`ms=` 撑大污染未除。
- **在飞**：**#6 门的阶段间 settle**（`--settle-seconds` 默认 12，钩子挂在 `battery()` 首行 :434 ⇒
  含整条帧预算在内的所有电池调用都覆盖；另挂直播节奏 / L10 / L7 浏览器腿 / L7 GPU 三方）。
  它要拆开的正是 `L4 live pacing`、`L6` 与 **RSS peak** 三处纠缠的读数。
- **排队（阻塞在 #6 之后）**：**S4** 材料侧杠杆——**方向已按实测更正**：代理不是全 I 帧，配方是
  `-force_key_frames "expr:gte(t,n_forced*1)"` = **每秒强制一个关键帧**（`make_all_proxies.py:38-39`），
  所以做法是**去掉它、改 `-g N`**（工具 `make_proxy_gop.py`，`--dry-run` 已验证只差这一个变量 + 流集自证 + 列位自证）。
  A/B 用 `s4_gop_ab.py`：注意两条最慢腿在 **composite 子画布**内，必须整串替换 13 处而不是只改顶层段。
  **五个数一起读**（p95 / max / Σover-budget / fresh 帧每秒 / warm used+started+wasted）。
  全量重编代价（已核实）：`make_all_proxies.py` 约 **10 分钟 GPU** + `add_proxy_audio.py` 约 **30 秒**，25 支；
  属材料管线大动作，要先报代价、由用户决定，不许自行开工。
- **排队（小）**：把 P-96 里那节代理栅格测量**重跑并存盘** `temp/playback-test/s4-proxy-grid.json`
  （现在那些数字只在控制台读过，按 `scripts/check_doc_counts.py` 的规矩属不可回溯引用），并跑一次它做文档数字体检。

### 接手必读的三条坑（都踩过）
1. **计时轮次期间机器必须空载**：并发 ffprobe/转码/第二个 agent 会让读数整体作废（P-94、P-96、`r2` 那两臂）。
2. **判活只认 `&probe=<id>` 且 `pushes>0`**；A/B 换素材必须同时改 `segments[].media.path` 与 `media[]` 并走
   网关 `--extra` 直供，否则静默 404 的"停顿消失"会被当成效果（P-94 原案）。
3. **判断中文坏没坏看字节**（`decode('utf-8')` + 数 `U+FFFD`），本机控制台是 GBK，回显会自己造乱码假案。
4. **一次只跑一个计时 agent**，且由协调者排队——不要写进子 agent 任务书让它"自己等安静"：
   臂与臂之间本来就有 12–15 s 空档，第二个 agent 会在空档里判定"安静"并动手（`r2` 两臂因此作废）。

### #6 的 settle A/B 中间判定（2026-10-29 16:55，我独立算的，接手时先看这条）
`t6-settle-ab.json` n=5 对 5：两臂 `frames` 全 1062、`gap p95` 42、`gap max` 72 / 74、`>100 ms` 的 gap **两臂都 0**、
`black_streaks` 0，且 **`pre_alive_procs_at_B_start` 10 个样本全为 0**。
⇒ **这是一次空检验**：nosettle 臂从未造出"上一阶段 Chrome 还在收尾"的条件，所以既不能写"settle 无效"也不能写"settle 已验证"；
能写的只有一条——**门内那次 662 帧 / paint p50 1516 ms 的污染态，用这个两阶段小跑具复现不出来**，
"Chrome 收尾残留"不是可复现的成因路径。真成因候选改为：门阶段之间自己跑的离线重活
（L2/L3 像素比对、channel 2 的 `render_frame.py` PIL+ffmpeg），或全程存在的外部 uvicorn（P-97 已声明"空载只对我这边成立"）。
⇒ `--settle-seconds` 现在是**没被证明的保险**：要么按 `t6_deep_ab.py`（16:55 新建）把 nosettle 臂改成"紧接一次 channel-2
离线成帧之后起跑"、让 `pre_alive_procs` 真的非零再测；要么承认本轮只是**排除一个假设**，别宣称验证过（死开关先例：P-83、P-87）。
验收硬标准不变：门内直播跑 `warm 白热` 16 → 0、帧数 662 → 1040–1062，**且负样本臂能稳定造出污染态**。

### 停放状态（2026-10-29 16:58，回合耗尽时自动暂停的现场）
- **#6 仍在跑深一轮**：臂名 `t6dnosettle1ck0/ck1/jn`（16:57–16:58 还在写 `t6d-gw.log`）——
  它按判定把"阶段前插入离线成帧"造进条件了，方向对。
- **`scripts/playback_check.py` 是脏的且属于 #6**：接手第一件事先 `git status`，
  **别提交、别回滚**它；确认 #6 交报（或它的进程/产物已停）之后再决定提还是改。
- **别重复派单**：#3 的工具与判读口径都在任务 #3 描述里；只有当 #6 结束、机器空载（`report-*.jsonl`
  与 `*-gw-*.log` 180 秒无写入、无他人 python/ffmpeg）才起 `make_proxy_gop.py` → `s4_gop_ab.py --rounds 2`。
- 已落库：根仓库 `7d9cbad`+`330f353`；docs `af77838`/`e3f0e6c`/`4506d64`/`7e1a41f`。**均未 push**（push 需单独授权）。

### 若回合不够，按这个顺序取舍（2026-10-29）**#3 S4**（唯一还没测的计划步）＞ **#6 验收** ＞ **#8 内存**（600 s peak 复跑 + LRU `break`→`continue`
与 `Input has been disposed` 同批改造，阻塞在 #6 之后）＞ **#5**（栅格存盘 + `check_doc_counts.py` 体检）。
提交：根仓库 `SKILL.md`（已改未提）+ #6 在改的 `playback_check.py`；docs 仓库 P-96/P-97/计划/口径。
**push 需要单独授权。**

### 预览本体的目视确认（2026-10-29）
`temp/playback-test/browser-shot-1.png`（P-97 那跑，13:38）：1080×1920 竖幅<素材语料>实拍 + 下方三分之一处
白字描边字幕「大家好我们逛了<素材语料>」位置与样式正确 ⇒ 视频腿与文本腿确实合成出来了，不是"计数器绿而画布黑"。
t=1.0 那条 L10 红是人眼可辨的**过墨**（原字库 `HelloFont_ID_JianSong_95.ttf` 被剪映自己删过，
两通道统一回落雅黑 Bold，比成片重 14–19%，F-084）——**判据线不下调**。
另两张（6.633 / 20.23）与通道 2 对照 `c2-*.png` 在盘上但**未逐张目视**，不声称看过。
