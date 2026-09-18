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

---

## A1 + A2 · 主题渐变表 + AppConfig.theme + `_coerce_theme`

| 项 | 内容 |
|---|---|
| 文件 | `core/constants.py`（`THEMES`/`DEFAULT_THEME`/`AUTO_THEME`/`THEME_NAMES`/`THEME_SEASON_MAP`/`THEME_ALLOWED`/`TRAY_MENU_THEME`/`THEME_RECHECK_MS` + `__all__`）、`core/config.py`（`_coerce_theme` + `theme` 字段 + `to_dict`/`from_dict`）、`tests/test_themes.py`（新）、`tests/test_config.py`（扩） |
| 结果 | 全量 **898 passed / rc=0**（+49 `test_themes`，+10 `test_config`） |
| 结论 | `default` 以 `is` 引用 `BODY_GRADIENT_STOPS`；`THEME_ALLOWED` 8 成员；`_coerce_theme` 白名单。`COLORS`/`SEMANTIC_COLORS`/`SPACING`/`FONT_SIZE`/`RADIUS` 键值未动。 |

**变异验证（A1/A2）**

| # | 怎么破坏 | 观察到 | 还原 |
|---|---|---|---|
| 1 | `_coerce_theme` 去掉白名单（`if True: return candidate`） | `test_theme_coercion[banana-default]`、`[-default]` **FAIL** | 已还原 |
| 2 | `THEMES["default"]` 改为复制 `tuple(...)` | `test_default_theme_is_body_gradient_stops_object` **FAIL** | 已还原 |
| 3 | `THEME_ALLOWED` 去掉 `| {AUTO_THEME}` | `test_theme_allowed_has_eight_members` **FAIL** | 已还原 |
| 4 | `spring` 位置 `0.25→0.20` 且色值改小写 | 位置/大小写两条 **FAIL** | 已还原 |

commit：`f3c5dc7 feat(theme): 主题渐变表 + AppConfig.theme + _coerce_theme`

---

## A3 · `resolve_theme` 纯函数 + 渲染取色 + 托盘图标跟随

| 项 | 内容 |
|---|---|
| 文件 | `core/theme.py`（新，纯逻辑零 Qt/零 time）、`ui/pet_renderer.py`（`set_theme`/`theme_stops` 实例状态；`_body_gradient`/`_sample_gradient`/`_draw_glow` 读 `self._stops`；`build_tray_icon(stops)`/`_paint_tray_face(painter, stops)` 参数化）、`ui/tray.py`（`set_icon`）、`app/controller.py`（启动 + 每日 `QTimer(self)` + 跨日检测 → `resolve_theme`；托盘图标跟随）、`tests/test_theme_render.py`（新）、`tests/test_static_constraints.py`（把 `core.theme` 加入无 Qt 导入清单） |
| 结果 | 全量 **934 passed / rc=0**（+36 `test_theme_render`） |
| 结论 | `PetPose` 零改动（R1）；`paint()` 签名不变；托盘图标随皮肤重建。app 层是唯一 `time` 使用点。 |

**变异验证（A3）**

| # | 怎么破坏 | 观察到 | 还原 |
|---|---|---|---|
| 1 | `_sample_gradient` 改回读 `C.BODY_GRADIENT_STOPS` | `test_sample_gradient_differs_across_themes[0/0.25/0.5/0.75/1.0]` **FAIL** | 已还原 |
| 2 | `resolve_theme` 非法分支返回 `AUTO_THEME`（忽略用户选择） | `test_resolve_theme_manual_overrides_auto` **FAIL** | 已还原 |
| 3 | `PetPose` 插入 `theme: str` 字段（模拟 R1 复发） | `test_petpose_fields_are_all_float` **FAIL** | 已还原 |

> 说明：`_draw_glow` 阶段 A 简版按「清醒取深端 / 睡觉取亮端」从 `self._stops` 派生；
> 阶段 B 的 `glow_for_theme` 会再精修。跨月换肤 = 每日 `QTimer` **叠加** `_on_frame_tick`
> 既有跨日检测（保证零点精度，而非最多滞后一天）。

commit：`94561fe feat(theme): resolve_theme 纯函数 + 渲染取色 + 托盘图标跟随`

---

## A4 · 托盘「主题」子菜单（含「自动」）

| 项 | 内容 |
|---|---|
| 文件 | `ui/tray.py`（`theme_selected = Signal(str)` + `_theme_menu`/`_theme_group`/`_theme_actions` + `set_theme_checked`）、`app/controller.py`（接线 `_on_theme_selected`；`_apply_theme` 同步勾选）、`tests/test_tray.py`（新） |
| 结果 | 全量 **946 passed / rc=0**（+12 `test_tray`） |
| 结论 | 子菜单含「自动」+ 7 套皮肤（单选 `QActionGroup`）；沿用 `scale_menu` 先例用 `triggered` 连接（避免单选组取消勾选时误发信号）；`set_theme_checked` 走 `blockSignals` 静默同步。 |

**变异验证（A4）**

| # | 怎么破坏 | 观察到 | 还原 |
|---|---|---|---|
| 1 | `set_theme_checked` 改用 `action.trigger()`（会发信号） | `test_set_theme_checked_is_silent` **FAIL** | 已还原 |
| 2 | `_on_theme_selected` 去掉 `_apply_theme()` | `test_on_theme_selected_applies_and_persists`、`test_tray_theme_click_reaches_controller` **FAIL** | 已还原 |
| 3 | 主题项初值改为恒 `default`（忽略 `cfg.theme`） | `test_theme_default_checked_follows_config` **FAIL** | 已还原 |
