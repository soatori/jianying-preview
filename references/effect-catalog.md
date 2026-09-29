# 对照表（effect catalog）

`assets/generated/effect_catalog.json` = 27,246 条，构建耗时 ~13s：
`python <S>/preview.py catalog`（`--no-rp-db` 只用 vendor，~1s）

## 三层来源

1. **vendor**：`jianying-editor-skill/scripts/vendor/pyJianYingDraft/metadata/*.py` 的 14 个枚举
   （转场 453、画面特效 1097、人物特效 240、滤镜 1052、字体 798、入场 155、出场 124、组合 123、
   文字入场 145 / 出场 97 / 循环 93、音效 85、美颜音色 57、蒙版 6）。
   每条带 `name / effect_id / resource_id / md5 / is_vip / duration_us / is_overlap / params[]`。
   注意枚举成员名被 Python 化（`_3D空间`），**真实中文名在 `.value.name` / `.value.title`**。
2. **rp.db**：`<JianYing 数据根>/User Data/Cache/ressdk_db/<账号>/rp.db` 的 `http_cache.response_body`
   → `data.effect_item_list[].common_attr`（`title`、`effect_type`、`md5`、`cover_url`、
   `sdk_extra.transition.{defaultDura,isOverlap}`、`extra.is_vip`、`category_ids`）。
   - **必须** `sqlite3.connect("file:…?mode=ro", uri=True)`；`immutable=1` 会读到 0 行。
   - `rp_master.db` 没有 `http_cache` 表，跳过。
   - 分片可能被剪映锁（`-wal/-shm`）：`busy_timeout=200ms` + 逐片 try/except，失败只在 meta 记 `skipped:busy`。
   - `effect_type` → 语义：`1 花字, 3 音效, 6 文字模板, 7 画面特效, 8 人脸道具, 12 滤镜,
     19 转场, 20/21/121/148 美颜, 48 字幕模板, 50 综合, 58 数字人, 97 蒙版`。
   - 入场/出场/循环动画面板**不在** rp.db 里 → 只能靠 vendor。
3. **文件层**：对每条探测 `Cache/effect/<effect_id>`、`Cache/effect/<resource_id>`、
   `Cache/artistEffect/<resource_id>`，记录 `has_frag / has_effectstyle / has_cover / font_file`。
   这一层决定"能不能真画"，前两层只决定"叫什么名字"。

## render_class 判定

| 级别 | 条件 | 行为 |
|---|---|---|
| `exact` | 花字本地有 `effectStyle.json`；字体本地有 `.ttf/.otf`；或 `approx_overrides.json` 标了 `impl:"exact"` | 真画 |
| `approx` | 命中 overrides，或按中文名关键词规则命中（淡入/淡出、放大/缩小、推近/拉远、左移/右移、旋转、抖动、模糊、叠化、闪黑、闪白…） | 用文档化的近似运动/溶解代替 |
| `placeholder` | 其余 | 只出带中文名的角标，**绝不静默留白** |

规则表在 `jypreview/model/labels.py`（`APPROX_BY_KEYWORD`、`TRANSITION_APPROX`）；
手改覆盖放 `assets/generated/approx_overrides.json`，键为 `"<kind>:<中文名>"` 或 id。

## 查表顺序

`material.path` 解析出的 `(id, md5)` → `by_md5` → `effect_id` → （动画的短码在 `id` 字段）→
`resource_id` → `"<kind>:<name>"` → `"any:<name>"` → 草稿自己的 `key_value.json` → `unknown`。

## 本机实测覆盖率

对 60 份明文草稿（`python -m jypreview.tools.catalog_coverage --drafts-root <root> --catalog <json>`）：

| 桶 | 唯一 id | 解析率 |
|---|---|---|
| transitions | 10 | **100%** |
| video_effects | 12 | **100%** |
| material_animations | 54 | **100%** |
| fonts | 14 | 93% |
| effects（含花字/滤镜/美颜） | 43 | 65% |
| 花字 effectStyle | 12 | 58% |
| text_templates | 7 | 57% |
| stickers | 29 | 7% |

`selfcheck --milestone M2` 的闸门是 转场/画面特效 ≥95%、动画 ≥90%、字体 ≥85%。

**已知设计缺口（不是 bug）**：美颜/`figure`（本语料 2,531 条）在本机无任何名字来源
（`effect_id` 为空、只有算法产物路径），只出一个聚合角标"美颜/AI 算法 ×N（剪映专有算法，不预览）"。

## 版本钉扎

`effect_catalog.meta.json` 记 `jianying_version`、`videoeditor.dll` 路径、
`vendor_metadata_sha256`、分片清单、`render_class` 计数。
版本与当前安装不一致时 `EffectCatalog.load()` 直接拒绝，避免拿旧 id 表解释新草稿；
确认可接受时加 `--allow-catalog-skew`。剪映升级后重跑 `preview.py catalog` 即可。
