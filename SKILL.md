---
name: jianying-preview
description: 只读预览与校验剪映(JianYingPro)草稿：解析/解密 draft_content.json，在浏览器按时间线复现画面与声音（多轨叠序、文本样式/描边/阴影/渐变、动画、转场、混音、复合子画布），并提供无浏览器的离线合成通道与 21 层回归门。当用户要求"预览剪映草稿""看看改完的效果""不开剪映能不能看到时间线""草稿截图""校验/验证剪映改动"，或在自动化剪辑改完草稿后需要确认结果时使用。绝不修改草稿内容。
---

# 剪映草稿只读预览与校验（M2）

三条硬规矩，先读：

1. **草稿只读。** 本 Skill 不写 `draft_content.json`、不写 `.jypreview/`、不动封面与素材索引。
   任何"看起来要写回"的需求都转交 `jianying-editor` 那条线。
2. **改完播放器必须先过门。** `python scripts/playback_check.py …` 是唯一裁判；
   手工看一张截图不算验证（历史上五个缺陷里有五个先骗过了人眼和一层临时检查）。
3. **临时产物只进 `temp/`，证据只进 `docs/`（独立 git 仓）。** 草稿副本、代理片、导出成片一律不提交。

## 通道结构

| 件 | 位置 | 职责 |
|---|---|---|
| L1 模型 | `scripts/playback_model.py` | 解密/解析草稿 → `model.json`（段、几何、字体、动画引用、音量、断言） |
| 安装定位 | `scripts/jy_paths.py` | 自动检测剪映安装（`ffmpeg.exe` / `videoeditor.dll` / `canvas_agent` 的 js 目录都从这里取），结果记在 `config.local.json`；不再往脚本里写死盘符 |
| 网关 | `scripts/preview_gateway.py` | 只绑 127.0.0.1、GET/HEAD、Range + keep-alive；媒体与字体按不透明 id 供；`/report` `/shot` `/wave` 回收入口 |
| 浏览器通道 | `player/player.html` | Pixi 8 合成 + mediabunny 解码 + WebAudio 混音；运行副本在 `temp/playback-test/player.html`（门会逐字节校验） |
| 离线通道 | `scripts/render_frame.py` | PIL/ffmpeg 同律渲染，用于像素级对照与成片比对 |
| 门 | `scripts/playback_check.py` | 21 层判据，非零退出即失败；自己起停网关 |

播放器依赖的 `pixi.js` / `mediabunny` 从 `temp/px-probe/node_modules` 取本地固定版本——**不走 CDN**，
因为换版本就是换像素，历史对照会失真。

## 最小可用流程

```bash
# 0) 安装位置自检（只读，结果记在 config.local.json），再解密草稿（plain 产物进 temp/）
python scripts/jy_paths.py
python scripts/media_probe.py "<draft_content.json>"          # 结构清点（GOP/moov/elst）
python scripts/playback_model.py "<plain.json>" --draft-root "<草稿根>" \
       --timeline <uuid> --out temp/playback-test/model.json

# 1) 无浏览器校验：模型断言 + 离线成帧 + PNG
python scripts/render_frame.py temp/playback-test/model.json --t 1.0 --out temp/playback-test/check-1.00s.png

# 2) 浏览器预览（人在环里看）
python scripts/preview_gateway.py --port 8790 --serve-dir temp --model temp/playback-test/model.json
# 浏览器打开 http://127.0.0.1:8790/playback-test/player.html?model=model.json

# 3) 回归门（跳掉慢层先跑通）
python scripts/playback_check.py --plain "<plain.json>" --draft-root "<草稿根>" --timeline <uuid> \
       --model temp/playback-test/model-check.json --media-model temp/playback-test/model-proxy-a.json \
       --oracle-mp4 "<你的成片 mp4>" --pixel-t 1.0 --pixel-colour 255,255,255 \
       --repeat 1 --skip-flash --skip-mixmode --skip-browser-shots
```

代理片（大素材的时间轴测试要用）由 `temp/playback-test/make_all_proxies.py` + `add_proxy_audio.py`
生成，配方是 `h264_nvenc yuv420p` + 1 s 关键帧 + `+faststart`，**保帧率**（源是 59.94/50 就还是 59.94/50）。

## 环境变量

| 变量 | 用途 |
|---|---|
| `JY_ORACLE_MP4` | 原生导出成片路径（L3 像素判据与若干 A/B 的对照物）。未设时相关脚本走"文件不存在"分支并报错，不会静默用空路径比对 |
| `LOCALAPPDATA` | 剪映机器资产（效果包、字体）根，即 `%LOCALAPPDATA%\JianyingPro\User Data\...`（脚本用 `Path.home()`，不写死用户名） |
| `JY_INSTALL_DIR` | 钉死剪映安装版本目录（如 `D:\Program Files\JianyingPro\11.6.0.14552`）。不设时由 `scripts/jy_paths.py` 查 C:/D: 的 `Program Files`、`Program Files (x86)` 与 user 的 `%LOCALAPPDATA%\JianyingPro\Apps`，取「完整安装」（有 `Resources/` 且带 `ffmpeg.exe`/`videoeditor.dll`）里版本号最大的那个，并写回 `config.local.json` |
| `config.local.json` | 本机安装记录（skill 根目录，已 gitignore）。记录里的目录还在就沿用，不再走盘；被升级/删除后自动重扫。`python scripts/jy_paths.py --rescan` 强制重扫 |

## 门能判什么（编号即层名）

L0 在册播放器与运行副本逐字节相同 · L1 模型断言 / 几何通道 / 载体新鲜度 / 轨类型覆盖(INFO) ·
L2 帧 vs 成片的色层包围盒 · L3 视频带与成片同刻相关 · L4 连续播放、seek、首帧、Range 流、
**整条时间轴的帧耗时尾部分布**、直播节奏 + A/V 残差 · L5 混音器 · L6 静帧守卫（正反两个方向都有牙齿）·
L7 混模式浏览器接线 · L8 动画/打字机接线 · L9 跨通道曲线一致 · L10 浏览器自截图 vs 离线通道 vs 成片 ·
L11 闪光律 in/out 单变量。

判据是**分布不是单值**：`--repeat ≥3` 才有资格说"通过"；`peak_fs`、首帧这类必须报中位与尾部。

## 已知边界（不要在这里浪费回合）

- **调色/滤镜不实现**（按规范刻意排除），所以带调色的时间线整帧相关会低一截。
- **字幕字形有天花板**：草稿引用的建馆字体可能已被剪映自己清掉，两通道都只能落到校准过的兜底字体，
  比成片多 14–19% 墨量；这条已写进 `spec/text.yaml`，不是待修项。
- **真实 rAF 节奏测不了**：headless 与应用内浏览器都不发帧，门的每帧耗时来自定时器路径的代理。
  "卡不卡"最终要人眼看一次。
- **叠序未标定**（U-15）：`render_index` 与轨道位置两种读法在本语料上给出同一结果，无法分辨。

细节与逐条证据在 `docs/`（独立仓，不进代码历史）：`evidence/findings.md`（F-xx）、
`evidence/unresolved.md`（U-xx）、`evidence/playback-log.md`（P-xx 现场记录）。
