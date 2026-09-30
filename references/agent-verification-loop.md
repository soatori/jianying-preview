# Agent 校验回路 SOP

目的：把"改完剪映草稿 → 重开剪映肉眼看"换成"改完 → 读 JSON + 一张 PNG"。
剪映只在最终导出时打开一次。

## 0. 一次性准备

```bash
python <S>/preview.py warm                      # 建语料索引（~1s，不解密）
python <S>/preview.py serve --no-browser &      # 常驻服务，持有唯一的 headless 浏览器
curl -s http://127.0.0.1:8765/api/state         # 确认 dll / catalog / cache 都在
```

`serve` 没起时 `shot` 会自己拉一个私有浏览器（`--no-server`），但那样每次都要冷启动。

## 1. 改前留档

```bash
python <S>/preview.py frame "<草稿>" --timeline <tid> \
       --times 0.5,3,7,12,20 --out before.json
```

`--times` 一次最多 60 个时间点，覆盖你打算动的每个区间。
留档必须在**写回之前**：`ir-diff` 只能比较两份 IR，不能凭空恢复改前状态。

## 2. 用 jianying-editor 写回

```bash
python <EDITOR>/scripts/jianying_project.py apply-plan "<草稿>" --timeline <tid> --plan plan.json          # 先看 dry-run
python <EDITOR>/scripts/jianying_project.py apply-plan "<草稿>" --timeline <tid> --plan plan.json --apply  # 再落盘
```

## 3. 让预览器重新解密 + 比对

```bash
curl -s "http://127.0.0.1:8765/api/reload?draft=<did>"
python <S>/preview.py frame "<草稿>" --timeline <tid> --times 0.5,3,7,12,20 --out after.json
python <S>/preview.py ir-diff "<草稿>" --a-file before.json --b-file after.json
```

判据：

```jsonc
{"summary":{"added":0,"removed":1,"changed":2,
            "duration_us":[57766666,57766666]}}   // 时长变了 = 动到了没打算动的地方
```

- `duration_us` 前后必须相等，除非你确实增删了片段长度。
- `changed[].fields` 里只应出现你计划改的字段（`text`、`start_us`、`duration_us`、`fill`、`cy_px`…）。
- 出现计划外的 `added/removed`，或 `z_order`/`track` 变了 → **停手**，别继续写回，先查 plan。

## 4. 视觉复核

```bash
python <S>/preview.py shot "<草稿>" --t 7 --out after.png      # 只出画面（1080x1920）
python <S>/preview.py shot "<草稿>" --t 7 --view ui --w 1500 --h 1000 --out after_ui.png   # 带图层列表/角标
python <S>/preview.py what-at "<草稿>" --t 7
```

`--view ui` 的截图里能直接看到：图层列表、`精确/近似/占位` 标签计数、缺失素材数量、警告。
这些是"预览器自己知道哪里没画准"的自证，读图时先看这里。

## 5. 无浏览器时的最小断言

只读 JSON 也能回答大部分问题：

```bash
python <S>/preview.py what-at "<草稿>" --t 12.4
# -> {"who":[{"kind":"text","text":"售后响应慢","at_px":[540.0,1385.0],"em_px":86.4,
#             "badges":["media_ok","strokes×1","shadow×1"]}]}
```

## 端点速查

| 端点 | 用途 |
|---|---|
| `GET /api/drafts?q=&layout=&limit=&offset=` | 语料列表（含 layout、编码、时间线名） |
| `GET /api/timelines?draft=` | 每条时间线的 id/name/duration/encoding/`media_hit_ratio` |
| `GET /api/draft?draft=` | `probe` 全貌 + `active_evidence` + `mirror_drift` + 副本清单 |
| `GET /api/frame?draft&timeline&t_us` | FrameDescriptor |
| `GET /api/frame?draft&timeline&t_us&window_us=<长度>` | 窗口 IR：与 `[t_us, t_us+window_us)` **相交**的全部图层（播放用；也支持 `from_us`/`to_us`，长度上限 120s） |
| `GET /api/frames?draft&timeline&times=…&compact=1` | 批量 |
| `GET /api/what-at?draft&timeline&t_us` | 精简断言面 |
| `GET /api/trackmap?draft&timeline` | 整条时间线的轨道/片段表（不开浏览器看结构） |
| `GET /api/ir-diff?draft&a_us&b_us` 或 `&a=<快照>&b=<快照>` | 层级 diff |
| `GET /api/shot?draft&timeline&t_us&view=stage|ui&w&h&out=` | PNG |
| `GET /api/fonts.css?draft&timeline` | 该时间线用到的所有 `@font-face`（含来源注释） |
| `GET /api/catalog?q=&kind=&render_class=` | 查对照表 |
| `GET /api/preview-plan?draft&timeline` | 这个时间线会画什么、什么会降级 |
| `GET /api/events` | SSE：`draft.changed`（剪映或我们重写文件时推送） |
| `GET /api/state` | 服务健康、解密统计、缓存、浏览器状态 |
| `GET /api/health` / `POST /api/lease` / `POST /api/session/close` | 启动器会话健康、心跳和关闭 |

## 6. 校验"播放"（shot 只能验瞬间，验不了走带）

`shot`/`what-at` 都是**点**查询，看不出"上层素材有没有跟着滚"、"片段切了没"。要验播放，
按播放键再用页面自己的诊断钩子读 DOM 池 —— 读的是真实在屏节点，不是 IR：

```javascript
window.__play(true)                    // 等价于点播放按钮，返回 playing
window.__snapshot()                    // 当前在屏图层（id/kind/mediaTime/paused/seeking/ready）
window.__state()                       // tUs/playing/buffering/windowRange/pool/flat/loads/primary
window.__layers()                      // 池内全部节点（含 display / data-hidden / 时间区间）
window.__stage                         // Stage 实例，运行时插桩用（谁 drop 了节点）
window.__renderErrors                  // 最近的渲染异常
window.__play(false)
```

现成工具：`python -m jypreview.tools.audit_playback "<草稿>" --seconds 24 [--start 19]` ——
headless Edge + CDP，按 0.25s 采样，把每次采样与该时刻的 `/api/frame` 点帧真值逐层比对，输出
`缺图层 / 多图层 / 该有画面却空白 / 媒体位置漂移`，并列出每个视频层的媒体位置起止
（起止差 < 0.05s = 该层画面冻结）。判据：三项不符必须全 0，且参与播放的视频层"全部在推进"。
退出码 2 = 至少一次与草稿不符。

```bash
# 服务必须先起着；本机环境会导出 http_proxy → 脚本里已 pop，连 127.0.0.1 才不被拦成 502
python <S>/preview.py serve --no-browser &
python -m jypreview.tools.audit_playback "<草稿>" --seconds 24
```

这条通道能验到的三件事，正是点查询验不了的：跨窗口预取（媒体位置会越过窗口末尾继续推进）、
上层素材滚动（出现 >1 个推进中的视频层）、剪切换轨（`图层切换` 次数 > 0）。

读输出时的两个**非**缺陷陷阱：

- `实时率` 是 `(末次 tUs − 首次 tUs) / 墙钟`。草稿短于播放秒数时，走带到底就停，比率会低到
  0.3× —— 先看 `/api/timelines` 的 `duration_us` 再下结论。
- `duration_us = 0` 的草稿（空时间线）本来就该是 `池内节点 0`，不是没画出来。

## 注意

- **别对真草稿做写测试**。要试写回流程，把草稿复制到 `~/.jypreview/fixtures/` 再指过去。
- 草稿目录名含中文/空格/括号：URL 里一律用 `did`（`warm`/`drafts` 给出），名字只出现在 JSON 里。
- `visible:false` 的片段被排除是正常的（模板残留的隐藏文本很常见），不是丢了。
- 老草稿大量素材路径失效 → 看到的是占位瓦片 + "N 个素材缺失"，这是数据问题不是渲染问题；
  用 `/api/timelines` 的 `media_hit_ratio` 先判断这个草稿值不值得做像素级核对。
- 美颜/滤镜/LUT/蒙版/音频混音不渲染，会明确写在 `warnings` 和角标里。
