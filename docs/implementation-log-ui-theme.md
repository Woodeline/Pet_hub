# 实施日志 · 主题皮肤系统 + 动效去机械化（阶段 A）

> 依据：`docs/design-ui-fatigue-plan-v1.1.md`（唯一权威方案）
> 分支：`feature-ui-upgrade`（禁 checkout/switch/merge/push）
> 记录格式：时间 / 命令 / 结果 / 结论（追加式，只增不改）

环境固定前缀（本机 Git Bash，`grep`/`tail` 依赖 PATH）：

```
export PATH="/usr/bin:/bin:/mingw64/bin:/c/Windows/System32:$PATH"
cd "C:/Users/王佐成/WorkBuddy/软件开发/desktop-pet"
VENV="C:/Users/王佐成/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
```

全量测试命令（**注意**：`pyproject.toml` 的 `addopts = "-q"`，若再叠 `-q` 会变成 `-qq`，
**汇总行会被吞掉**；因此显式 `-o addopts=""` 以便读到 `N passed`）：

```
PYTHONPATH=src QT_QPA_PLATFORM=offscreen "$VENV" -m pytest tests/ -p no:cacheprovider -o addopts="" 2>&1 | tail -3
```

---

## A0 · 基线固化（无代码改动）

| 项 | 内容 |
|---|---|
| 时间 | 2026-09-19 |
| 命令 | `git branch --show-current` / `git rev-parse --short HEAD` / `git status --porcelain` |
| 结果 | 分支 `feature-ui-upgrade`；HEAD `fc674b9`；`git status --porcelain` **空**（干净） |
| 结论 | 工作区干净，可开工。改动只落在 `feature-ui-upgrade`。 |

| 项 | 内容 |
|---|---|
| 命令 | 全量 pytest（见上） |
| 结果 | **839 passed / rc=0 / 14.46s** |
| 结论 | 本阶段基线 = **839**。完成后必须 ≥839 且全绿。 |

> 环境备注：本机 `pytest -q`（叠加 `addopts=-q`）不打印汇总行；改用 `-o addopts=""`
> 可稳定读到 `N passed`。据此得到基线 839（与方案 §0 抬头一致）。
