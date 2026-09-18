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

commit：`1c17072 feat(theme): 托盘「主题」子菜单（含「自动」）`

---

## A5 · 动效节奏去机械化（呼吸微随机 + SurpriseKind 小动作 + 不对称眨眼）

| 项 | 内容 |
|---|---|
| 文件 | `core/constants.py`（`BLINK_EYE_DELAY_S`/`BREATH_JITTER`/`SURPRISE_MIN_S`/`SURPRISE_MAX_S`/`SURPRISE_DURATION_S`/`SURPRISE_POSES` + `__all__`）、`core/motion.py`（`breath_offset_phased`/`surprise_envelope`；`breath_offset` 原签名与行为不动 + `__all__`）、`core/pet_model.py`（`SurpriseKind` 独立枚举、`_breath_epoch`/`_breath_period` epoch 锚定相位、`_breath_phase_for`、`_surprise_allowed`/`_pick_surprise`/`_advance_surprise`、`set_reduce_motion`、右眼延迟眨眼）、`app/controller.py`（`self._model.set_reduce_motion(cfg.reduce_motion)` 注入）、`tests/test_motion_rhythm.py`（新，29 条） |
| 结果 | 全量 **975 passed / rc=0**（+29 `test_motion_rhythm`；`test_static_constraints.py`+`test_design_tokens.py` 共 81 passed） |
| 结论 | 呼吸相位改成 `now` 的纯函数；`Expression` 仍 == 8；`SURPRISE_POSES` 只用既有通道；`COLORS`/`SEMANTIC_COLORS`/`SPACING`/`FONT_SIZE`/`RADIUS` 键值未动。 |

### ⚠️ 与方案原文的偏离（唯一一处，已上报）

方案 §3 A5-1 原文要求 `_apply_life_signs` **按 `phase += dt / period` 累加**。实测该取向会让呼吸变成「dt 驱动」：
`now` 冻结时相位仍在推进 → 「目标恒定」前提失效 → 破坏 **FR-34 守卫** `test_model_frame_rate_independent_frozen_clock`
（实测 `body_y` 差 0.037 > 1e-6，全量 rc=1）。

**改法（经 team-lead 指定）**：把相位从「dt 累加」改为 **epoch 锚定**，即

```
phase = ((now - epoch) / period) mod 1
```

* 相位是 `(now, 状态)` 的**纯函数** → `now` 冻结 ⇒ 相位恒定 ⇒ FR-34 恢复绿；
* 周期**只在 `delta >= period` 的回绕点**（相位 ≈ 0/1、`sin` ≈ 0）重抽 → 相位值与导数连续，
  **R2 的原始缺陷（周期中途变更 → 相位瞬跳「打嗝」）依然被根治**，且比原方案更强；
* `breath_offset_phased(phase, amplitude)` 保持纯函数形态；`breath_offset` 一字未动。

**二次细化（本工程师主动，比 team-lead 原稿更稳）**：首帧锚点取
`epoch = now - cycle_phase(now, period) * period`（即「不大于 `now` 的最近整周期边界」），
而非直接 `epoch = now`。原因见变异 **I**——直接以 `now` 锚定会让两个「时钟不同但各自冻结」的
实例相位都归零，**连带打挂既有测试** `test_pet_model.py::test_life_signs_change_over_time`；
取整周期边界可让首帧相位等于旧 `cycle_phase(now, period)`（保持既有语义），
同时 `delta` 恒落在 `[0, period)`，避免 `time.monotonic()` 绝对数值较大时每帧误触发回绕。

**变异验证（A5）** —— 每条新断言均先破坏源码确认 FAIL 再还原：

| # | 怎么破坏 | 观察到 | 还原 |
|---|---|---|---|
| A | `_breath_phase_for` 相位改按「调用次数」推进（模拟 dt 累加） | `test_frozen_clock_frame_rate_independence_regression`、`test_motion.py::test_model_frame_rate_independent_frozen_clock` 双 **FAIL**（差 5.14） | 已还原 |
| B | 回绕时**不**推进 `epoch`（制造相位瞬跳） | `test_breath_phase_continuous_across_period_wrap` **FAIL**（回绕帧增量 6.96px ≫ 单帧上限 0.271px） | 已还原 |
| C | 重抽抖动改 ±50%（越过 ±10% 带） | `test_breath_resampled_period_within_jitter_band` **FAIL** | 已还原 |
| D | 重抽改用全局 `random` 而非 `self._rng` | `test_breath_randomization_reproducible_with_fixed_seed` **FAIL**（index 90 分叉） | 已还原 |
| E | `_surprise_allowed` 整体恒 `return True` | 四条抑制测试（SLEEPING/拖拽/临时表情/reduce_motion）全 **FAIL** | 已还原 |
| F | `surprise_envelope` 端点守卫误 `return 1.0` | `test_surprise_envelope_endpoint_literals` **FAIL** | 已还原 |
| G | 右眼去掉 `BLINK_EYE_DELAY_S` 延迟 | `test_blink_delay_affects_only_right_eye`、`..._makes_right_eye_lag_behind_left` 双 **FAIL** | 已还原 |
| H | `SURPRISE_POSES["STRETCH"]` 加不存在的 `magic_channel` | `test_surprise_poses_only_use_existing_channels` **FAIL** | 已还原 |
| I | 首帧锚点改成直接 `epoch = now`（team-lead 原稿字面量） | `test_first_frame_phase_matches_legacy_cycle_phase[1.5/10.0/123.75]` + 既有 `test_life_signs_change_over_time` 共 **4 FAIL** → 证明本工程师取整周期边界细化**必要** | 已还原 |

> 要点：变异 **A** 证明 FR-34 守卫非恒绿；**B/C/E/F/G/H** 证明新增断言均能捕获对应缺陷；
> **I** 证明对 team-lead 原稿的二次细化是由既有测试**强制**的，而非随意偏离。

**遗留 / 诚实说明**

1. `_draw_glow` 仍为阶段 A 简版（按皮肤端点取色），阶段 B 的 `glow_for_theme` 会再精修（A3 已记）。
2. `time.monotonic()` 为绝对数值：首帧取整周期边界后 `delta ∈ [0, period)`，正常；
   仅当进程长时间卡顿（单帧跨度 > 1 个呼吸周期）时相位会取模跳一次（单 `if`、无 `while` 兜底，按 team-lead 指定）。
3. 小动作门控复用 `REST_THRESHOLD_S`（=120s）；即「安静在场 ≥120s 后」才进入 40–80s 的触发倒计时，
   真实观感下触发较稀疏，属设计取舍（阶段 C 游走会共用该门控）。
4. `PetModel` 未暴露呼吸相位/周期的公共只读接口；`test_motion_rhythm.py` 按本仓库既有惯例
   （如 `test_pet_model.py` 读 `_blinking`/`_temp_expression`）白盒读取 `_breath_phase`/`_breath_period`。

commit：`feat(motion): 呼吸相位随机化 + SurpriseKind 小动作 + 不对称眨眼`

