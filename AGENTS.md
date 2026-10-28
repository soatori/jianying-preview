# 仓库规制

- 临时文件一律放在 `temp/`，不要写到仓库根目录或其他位置。
- 文档放在 `docs/`。`docs/` 是**独立的 git 仓库**（有自己的 `.git`），提交用 `git -C docs ...`，不要从根仓库提交它。
- 根仓库通过 `.gitignore` 忽略 `/temp/`、`/docs/` 与 `/config.local.json`，三者都不进代码历史。
- 剪映（JianYingPro）安装路径**不写死**：`python scripts/jy_paths.py` 自动检测（默认查 C:/D: 的
  `Program Files`、`Program Files (x86)` 与 user 的 `%LOCALAPPDATA%\JianyingPro\Apps`，取「完整安装」里
  版本号最大的版本目录），结果记在根目录 `config.local.json`。装在不同盘就设 `JY_INSTALL_DIR` 指向版本目录，
  或直接改 `config.local.json` 的 `install_dir`。
- 剪映草稿副本、测试 fixture、导出成片一律不提交；提交前先征得同意。
