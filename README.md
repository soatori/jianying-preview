# jianying-preview

剪映（JianYingPro）草稿的**只读预览与校验**工具集：解析/解密 `draft_content.json`，在浏览器里按时间线复现画面，并提供无浏览器的 JSON/PNG 校验通道，用来在**不打开剪映**的情况下确认改动效果。

> ⚠️ **本项目正在开发中。** 脚本、规格和结论都在持续迭代，接口与数据模型尚未稳定，不保证向后兼容，暂不建议直接用于生产流程。

## 目录结构

- `scripts/` — 解码、模型提取、渲染、播放、各类校验与实验脚本（Python）
- `docs/spec/` — 草稿格式与行为规格（加密、时间基、文本、动画、混合模式等）
- `docs/evidence/` — 实测证据与数据表
- `docs/base-selection.md` — 渲染基座选型结论
- `temp/` — 临时文件（不入库）

## 开发阶段

当前处于 M2（播放通道）阶段：解码与模型层已可用，浏览器渲染与逐帧比对基准仍在建设中，存在已知问题（如 seek 延迟不达标，见 `docs/base-selection.md`）。

## 说明

- 本工具集对草稿**只读**，不会修改任何剪映项目文件。
- 剪映安装路径：`D:\Program Files\JianyingPro`
- 想参与或跟进，先读 `docs/spec/00-overview.md`。
