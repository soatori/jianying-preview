# 仓库规制

- 临时文件一律放在 `temp/`，不要写到仓库根目录或其他位置。
- 文档放在 `docs/`。`docs/` 是**独立的 git 仓库**（有自己的 `.git`），提交用 `git -C docs ...`，不要从根仓库提交它。
- 根仓库通过 `.gitignore` 忽略 `/temp/` 与 `/docs/`，两者都不进代码历史。
- 剪映（JianYingPro）安装路径：`D:\Program Files\JianyingPro`
- 剪映草稿副本、测试 fixture、导出成片一律不提交；提交前先征得同意。
