# jianying-preview

剪映（JianYingPro）草稿的**只读预览与校验**工具集：解析/解密 `draft_content.json`，在浏览器里按时间线复现画面，并提供无浏览器的 JSON/PNG 校验通道，用来在**不打开剪映**的情况下确认改动效果。

> ⚠️ **本项目正在开发中。** 脚本、规格和结论都在持续迭代，接口与数据模型尚未稳定，不保证向后兼容，暂不建议直接用于生产流程。

## 目录结构

- `scripts/` — 解码、模型提取、渲染、播放、各类校验与实验脚本（Python）
- `spec/` — 草稿格式与行为规格（加密、时间基、文本、动画、混合模式等）
- `evidence/` — 实测证据与数据表（`evidence/tables/` 是数据表）
- `base-selection.md` — 渲染基座选型结论
- `requirements.txt` — Python 依赖清单（含各包在 Python 3.15 上的 wheel 覆盖情况）
- `temp/` — 临时文件（不入库）

> 这三样原先住在独立的 `docs/` 仓，`origin/docs` 在 `1fed3d8` 并进 main 后就在根目录；
> 旧文本里的 `docs/spec/…`、`docs/evidence/…` 指的是同一批文件。

## 依赖与环境

两条通道各有各的依赖，缺哪条就瘫哪一段。装法（Python 3.15.2 / win-amd64 实测）：

```bash
python -m venv --system-site-packages temp/venv
temp/venv/Scripts/python.exe -m pip install -r requirements.txt
```

venv 落在 `temp/` 下（已被 `.gitignore` 忽略），不进代码历史也不碰全局解释器。
之后**所有脚本都要用 `temp/venv/Scripts/python.exe` 跑**：PATH 上那个 `python` 没有 pillow，
门连 `--help` 之外的任何判据都执行不到。

| 依赖 | 用处 | 缺了会怎样 |
|---|---|---|
| `pillow` | 离线通道 `render_frame.py` 的画布/字体/叠序；门里每张 PNG 进 numpy 前的解码 | `render_frame.py`、`playback_check.py` 直接 ImportError |
| `numpy` | 20 个脚本的像素运算与相关性计算 | 所有像素判据不可用 |
| `psutil` | 仅 `browser_soak.py`：按 Chrome 进程树采 RSS 峰值并归因到 `--type=` 角色 | 只损失 L4 的内存那一格 |
| `av` (PyAV) | 仅 `media_probe.py`：GOP/moov/elst 结构清点 | 素材结构探针不可用（3.15 无 wheel，见 requirements 注释） |
| `pyyaml` | 仅 `check_spec_yaml.py`：校验 `spec/*.yaml` | 文档门失效，与 28 条播放判据无关 |
| `pixi.js` **8.22.0** | 浏览器通道合成器：叠轨 `Container/Sprite`、字幕 `Text`、`ColorMatrixFilter`（曝光）、`BlurFilter`、`BlendModeFilter`（混合律） | L7 混模式 / L8 动画 / L11 闪光律 无从测起 |
| `mediabunny` **1.65.0** | 浏览器通道解码取样：`Input`+`ALL_FORMATS` 解封装、`CustomSource` 包 Range 分段、`VideoSampleSink` 出帧、`AudioBufferSink` 出 PCM | L4 连续/seek/首帧/A/V 残差、L5 混音器 全废 |
| Chrome | 门经 CDP（`--remote-debugging-port`）驱动，**不需要 playwright** | 浏览器整条通道起不来 |
| `ffmpeg.exe` | 系统侧可用，但脚本优先取剪映自带的 `<install_dir>\ffmpeg.exe`（由 `scripts/jy_paths.py` 探测） | 帧提取与代理片生成失效 |
| `videoeditor.dll` | 唯一的解密通道（黑盒调用剪映自己的 `EncryptUtils`）。**版本是判据可复现性的一部分**：已知良好基线 sha256 `8cfcbb61…`（11.6.0.14552） | 整条通路起不来——11.7.0.14652 冷进程解密对任何输入都返 0 字节，见 `evidence/crypto-probe-log.md` 探测 3 |

node 侧两个库装在 `temp/px-probe/node_modules`，是 `player/player.html` 里硬编码的两个 dist 路径，
不走 CDN。**当前这两个版本号是 2026-11-02 重建的结果**：原先的固定版本只存在于被 gitignore 的
`temp/` 里，仓库从未记录过，清一次 temp 就丢了。重装等于换像素，所以**只有真的走浏览器的那条像素判据**
`L10 browser pixels` 在重新标定之前不可信（L7/L8 那两条浏览器接线层同理，要重跑一遍才算数）。
其余三条"对成片/封面帧敏感"的像素层**都不吃 node 库**，2026-11-03 已用配对成片与封面帧在门外复跑、
逐位复现历史读数，细节见 `evidence/playback-log.md` P-116 ⑪⑫：
`L11 flash`（`flash_channel2_ab.py` 只 import `numpy`/`PIL`/`render_frame`）、
`L2 pixel layer`（比的是离线通道 `render_frame.py` 对 ffmpeg 抽的成片帧，整条不开浏览器——
它原来也被误挂在这里，同一族的误挂）、`L3 video band`（对 `--cover-frame` 封面帧）。
判据名口径与旗标详见 `SKILL.md`。

## 开发阶段

当前处于 M2（播放通道）阶段：解码与模型层已可用，浏览器渲染与逐帧比对基准仍在建设中。
**seek 已达标**（代理片配置 + 1/6 s 关键帧定档后门内 `L4 seek` **38.2 ms**，线 150 ms；旧 1 s 配率是 118–129 ms；
`base-selection.md` 里那句"只剩 seek 一条不达标"是当时**直连源/NAS** 的读数，见该文件顶部的现状行）。
`L4 first frame` 也随定档从 FAIL 转 PASS（431 → **128.4 ms**，线 300；P-119 那跑门内读 **112.1 ms**、`L4 seek` 41.8 ms）。
**帧尾 max 现已逐点过线**：P-118（`--repeat 3`）三点 **138/107/120**、P-119（`--repeat 2` 带 oracle）**150/133**，
`p95` 恒 12（线 33.4/150，**150 那一点是压线不是余量**，分布按 107–150 报）。

当前已知问题按性质列三条，别混在一起（都带盘上出处）：
1. **`L10` 的 `t=1.0`** ＝原字库 `HelloFont_ID_JianSong_95.ttf` 被剪映自己删过、两通道统一回落雅黑 Bold，
   比成片重 14–19%（`F-084` 字体天花板，三次独立跑读 0.945 / 0.948 / 0.948）——**判据线不下调**，这条是内容天花板不是播放器 bug。
2. **剪切点边界那一帧的归属**：P-124 三张 ±4 表显示对上就是 0.968–0.987 且曝光/梯度比≈1.00（＝同一帧像素差一个索引），
   而成片正落在切点的那一帧与两条通路都塌到 0.003–0.085 ⇒ **一帧（33 ms）的闪白起始差**，
   每个切点一次；**已定位、未修**（改的是"时刻→帧号"的取整/含边，要配对开关＋负样本＋过门）。
3. **音频没有判据层**：门里 `L5 mixer` 判的是页面自报的混音器健康（`audio_errors=0`），`mix headroom` 是 INFO；
   把预览**录下来**对成片的读数在 P-122 ⑥（连续跑占空比 95.4 %、洞 1.0 s、最响窗 −10.85 vs 成片 −7.94、
   float 峰 −0.05 dBFS vs 成片 +3.26 dBFS，且**页面自报 `peak_fs 1.038–1.0602` 比录音乐观**）。
   口径仍按 2026-10-28 定案（削顶照抄成片、不设 ≤0 dBFS 线、不加限幅、不写"电平已对齐"）——
   **但"匹配成片"这句话目前只有读数支撑，没有绿/红可引**。

4. **调色只实现了一支**：`effects.type == brightness` 已按装机包内明文 GLSL
   （`AmazingFeature_adjustColor/xshader/colorAdjust.frag`）**两条通路都落地并默认打开**——
   通道 2 `render_frame.apply_color_adjust`（P-130：整轴 `<0.90` 的点 13/37 → 7/37、
   `|1−亮度比|` 中位 0.024 → 0.013）＋ 页内普通 `Filter`+`GlProgram`（P-133：8 个抽查点的亮度比
   0.658–1.119 全部收进 0.987–1.038，其中两条**对成片 FAIL 翻绿**；同一张 8 级灰阶 ramp 上
   shader 154.22 vs numpy 153.25，两半是同一支律）。
   ⚠ P-131 曾判"浏览器这条的形状不适用"，真因是声明被行尾注释吞掉，而 `BlendModeFilter` 的
   `{gl}` 注入槽在本包**根本不执行**（F-094 已就地更正，混合模式那条腿另见 U-107）。
   其余 `contrast/clear/shadow/black/light_sensation` **仍 skip**——它们的滑杆→uniform 映射
   （pivot/xFactor、slope/bias、17³ LUT）**没有被成片验过**，剩余 7 个点就全在这些段上。
   ⚠ 相关度类判据（`L10`/`L3`/`L11`）**看不见乘性偏差**：暗 36 % 的帧 corr 仍读 0.94（P-129），
   所以 `browser_shot_check.py` 现在每个时刻同时报**亮度比**（只报数，容差等用户定）。

另外记一条同族坑（P-122）：**`L10` 依赖 `temp/playback-test/ae-curves.json`**（页内闪白曲线的唯一输入，
`player.html:88-90` fetch 失败**不报错、只是全程不闪**）。它和 `mixmode-eq.html`、mixmode 抽取件一样是
**temp 里的派生物、不进 git**，一清就悄悄改变像素判据的含义——门现在缺了当场补建，并把
`pkgs/段/截图命中` 写进判定行、表 0 段可用时直接判红。

## 说明

- 本工具集对草稿**只读**，不会修改任何剪映项目文件。
- 剪映安装路径不写死：`python scripts/jy_paths.py` 自动检测（默认查 C:/D: 的 `Program Files`、
  `Program Files (x86)` 与 user 的 `%LOCALAPPDATA%\JianyingPro\Apps`），结果记在 `config.local.json`
  （已 gitignore）。装在不同盘时设 `JY_INSTALL_DIR` 指向版本目录。
- 剪映**升级会悄悄换掉解密通道**（11.6→11.7 实测：导出表逐字节相同，内存 `decrypt` 却对任何输入
  返 `ok=true / 0 字节`）。升级后先跑门禁，它同时在真草稿上做长度保持与语义回环：

  ```bash
  python scripts/jy_crypto/gate.py --samples 6 --oracle    # G1/G2/G3 全绿才算通
  ```

  不通就用 `JIANYING_VIDEOEDITOR_DLL` 钉住旧版 DLL。旧版没被删，只是被更新器改名成
  `<旧版本目录>/*_d_*`（实测 65/66 个文件都改了名），整批还原交给脚本：

  ```bash
  python scripts/rebuild_dll_sandbox.py --version-dir "<旧版本目录>" --out temp/dll-11.6 \
         --sha256 8cfcbb612ccd946df974428977b1902736c1de0ae561e20c26cbd4ea86099cb1
  ```

  它只读安装目录、落点被写围栏兜在 `temp/`、sha256 对不上就非零退出，最后打印要 export 的那行
  （**必须绝对路径**：`os.add_dll_directory` 收相对路径抛 WinError 87）。
- 跑加密层自检 `scripts/jy_crypto/gate.py` 时，**读数要带口径**：这一跑真的钉住了 DLL 才算数
  ——要么 export `JIANYING_VIDEOEDITOR_DLL`，要么带 `--dll`。2026-11-03 之前 `--dll` 只喂给
  identity 的 `report`、样本三次 `call` 走自动发现（报告写 11.6、干活的是 11.7），而且 scratch
  产物按源 sha 命名、跑前不清空，于是上一轮的旧明文能把"全失败"读成一条 PASS。
  两处都已修，改后对照 = 带 `--dll` 3/3 过 / 不带 0/3；详见 `evidence/crypto-probe-log.md` 探测 6。
- 想参与或跟进，先读 `spec/00-overview.md`。
