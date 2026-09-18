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

---

## B1 · 色彩微调（光晕随主题派生 + 降饱和两档 + PROP_OUTLINE 道具描边分层）

| 项 | 内容 |
|---|---|
| 文件 | `core/theme.py`（`glow_for_theme(name, sleeping)` 纯函数 + 色相工具 `_warmth`/`_pick_warmest`/`_pick_coldest`/`_soften` + `__all__`）、`core/constants.py`（`PROP_OUTLINE` 独立标量 + `BODY_GRADIENT_STOPS` 降饱和 + `__all__`）、`ui/pet_renderer.py`（`_theme_name` 实例状态 / `_outline_prop` 道具笔 / `_draw_glow` 改走 `glow_for_theme`；`_draw_keyboard`/`_draw_mouse` 用道具笔）、`tests/test_palette_level.py`（新，26 条）、`tools/render_theme_preview.py`（新，离屏预览工具） |
| 结果 | 全量 **1001 passed / rc=0**（B1-1+B1-3 落地后）；B1-2 两档各再全量绿 |
| 结论 | 光晕色**只在 core 派生**（`ui/` 零裸 hex，`test_static_constraints` AST 扫描绿）；道具描边用**独立标量常量**（照 `OUTLINE_W` 先例），`COLORS` / `SEMANTIC_COLORS` 键值未动。 |

**降饱和公式（B1-2）**：`L = 0.299R + 0.587G + 0.114B`；`new = round(c + (L − c) · ratio)`。
分两档、每档 5%，第 2 档在第 1 档结果上**再乘一次 5%**（累计 `1 − (1 − 0.05)² ≈ 0.0975`，**非**一次算 10%）。

| 档 | `BODY_GRADIENT_STOPS` 色值（0 / .25 / .5 / .75 / 1.0） | commit |
|---|---|---|
| 原始 | `#AEE6A8 · #FFF9B0 · #FFCB9E · #FFAECD · #AEDAF1` | — |
| 第 1 档（5%） | `#AAE5A3 · #FEF7AC · #FDC8A3 · #FCAAD4 · #AAD7EE` | `94cfc0a` |
| 第 2 档（累计 10%） | `#ACE4A5 · #FDF7AF · #FBC9A5 · #F9ABD3 · #ACD6EC` | `2359e32` |

> 结构 / 数量 / 位置一律未动，仅改色值；`THEMES["default"]` 以 `is` 引用 `BODY_GRADIENT_STOPS` 对象本身 → 默认皮肤自动跟随。

**视觉证据（阶段 B1，PNG 在仓库外）**：`_ui-review-phase-b/` 下
`b1-before-{7 套}.png`（降饱和前）· `b1-desat5-{7 套}.png`（第 1 档）· `b1-desat10-{7 套}.png`（第 2 档），
命令：`QT_QPA_PLATFORM=offscreen python tools/render_theme_preview.py --stage b1-desat5 --outdir <绝对路径>`。

**变异验证（B1）** —— 每条均先破坏源码确认 FAIL 再还原：

| # | 怎么破坏 | 观察到 | 还原 |
|---|---|---|---|
| M1 | `PROP_OUTLINE` 改成 `#141414`（与 ink 同色，层级差消失） | `test_prop_outline_constant_is_literal_value`、`test_prop_outline_differs_from_ink` 双 **FAIL** | 已还原 |
| M2 | 渲染器 `_outline_prop` 改回 `QPen(ink)` | `test_renderer_prop_pen_uses_prop_outline` **FAIL** | 已还原 |
| M3 | `glow_for_theme` 睡觉分支误用暖端/清醒参数 | `test_glow_for_theme_awake_differs_from_sleeping[7 套]` + `..._default_literal_values` 共 **8 FAIL** | 已还原 |
| M4 | `BODY_GRADIENT_STOPS` 暖端主色（0.50）退回第 1 档值 | `test_glow_for_theme_default_literal_values` **FAIL** | 已还原 |

> ⚠️ M4 首轮误打在 0.00（薄荷绿）停靠点上 → **rc=0 未 FAIL**：该停靠点既非暖端主色也非冷端主色，
> `glow_for_theme` 不取它，故无锚点覆盖。据此把变异改打到真正驱动默认光晕的暖端主色（0.50）→ 命中。
> **诚实披露**：`BODY_GRADIENT_STOPS` 中 0.00 / 0.25 / 0.75 三个停靠点的**色值**目前无字面量断言锁定
> （只有结构/合法 hex 断言），仅由 PNG 目视证据覆盖——若未来要做「色值漂移」守卫，需补字面量锚点。

commit：`1f18197 feat(palette): 光晕随主题派生 + PROP_OUTLINE 道具描边分层` ·
`94cfc0a feat(palette): BODY_GRADIENT_STOPS 降饱和（第 1 档 5%）` ·
`2359e32 feat(palette): BODY_GRADIENT_STOPS 降饱和（第 2 档累计 10%）`

---

## B2 · 微交互（悬停凝视 + 点击弹跳过冲 + 气泡打字感）

| 项 | 内容 |
|---|---|
| 文件 | `core/constants.py`（`HOVER_GAZE_*` / `CLICK_BOUNCE_PX` / `BUBBLE_TYPE_*` + `__all__`）、`core/motion.py`（`gaze_vector` 纯函数 + `__all__`）、`core/pet_model.py`（`_gaze`/`set_gaze`/`clear_gaze`；`_apply_life_signs` 悬停凝视 + 空闲张望抑制；`_apply_actions` 半眯眼 + `ease_out_back` 弹跳过冲；`_surprise_allowed` 纳入悬停抑制）、`ui/pet_renderer.py`（`face_center` 静态方法）、`ui/pet_window.py`（`_update_gaze` + `_on_frame` 调用）、`ui/bubble.py`（打字感 `_reveal`/`_reveal_timer`/`_revealed_text`/`_advance_reveal` + `set_reduce_motion`；`_paint_word` 前缀子串）、`app/controller.py`（启动 + 开关切换注入 `bubble.set_reduce_motion`）、`tests/test_micro_interaction.py`（新，21 条）、`tools/render_theme_preview.py`（`--stage b2` 三帧） |
| 结果 | 全量 **1022 passed / rc=0**（+21 `test_micro_interaction`） |
| 结论 | 悬停优先级 **悬停 > 表情模板 > 空闲张望** 生效且可测；弹跳峰值 ≤ 旧值 1.1 倍；气泡打字期间**宽度恒定**；`reduce_motion` 直达终态；逐字 QTimer 挂 parent 且 `hide_bubble` 停止。 |

### 实现要点（含一处「主动修正」）

**B2-1 悬停凝视**：`PetWindow._update_gaze` 每帧把 `QCursor.pos()` → `mapFromGlobal` →
`/scale` 得逻辑画布坐标，再经 `motion.gaze_vector(px,py, cx,cy, HOVER_GAZE_MAX_DIST_PX)`
归一化（`cx,cy` = `PetRenderer.face_center(pose)`），写入 `model.set_gaze(nx,ny)`。
模型在 `_apply_life_signs` 里 `look_x = nx·HOVER_GAZE_RANGE_PX`（**绝对赋值**，覆盖模板）。

> ⚠️ **主动修正（比 plan 原文更稳）**：plan §B2-1 只要求「空闲 `look_around_offset` 在悬停期间不写入」。
> 首次实现把「凝视块」放在「空闲张望块」**之后**——结果空闲张望即便写入也会被随后的绝对赋值抹掉，
> 该守卫**形同虚设且无法被变异测试捕获**（变异 M2 首轮 rc=0 未 FAIL）。遂把**凝视块前置**、空闲张望块后置，
> 守卫即可观测：去掉 `and not self._hovering` → 悬停时 `look_x = gaze + 3.0` → 断言必挂。
> 这既满足 plan 语义，也让守卫成为**真正承重**的代码（而非装饰）。

**B2-2 点击弹跳过冲**：`_apply_actions` 用 `motion.ease_out_back(u)`（`u: 0→1→0`）替代旧
`ease_out_bounce`；峰值 `ease_out_back` ≈ **1.1** → 最大位移 `CLICK_BOUNCE_PX(7.0) × 1.1 = 7.7px`，
**恰好等于**旧版峰值（`BREATH_AMPLITUDE_PX 3.5 × 2.2 = 7.7px`）→ 满足「≤ 现值的 1.1 倍」且脏区包围盒不扩大。

**B2-3 气泡打字感**：`_measure` / `_word_layout` 仍按**完整词条**一次算定（`_measure_word` 与 `_reveal` 无关）；
仅 `_paint_word` 对 `layout[0]`（恒为单词行）绘制 `_revealed_text()` 前缀子串 → 打字期间气泡尺寸恒定
（`test_jp_bubble_visual` 固定宽度契约不破）。`_reveal_timer` 挂 parent，`hide_bubble()` 与 `show_message()`
路径均 `stop()`；`reduce_motion` 时 `_reveal` 直达 `1.0`、不启动定时器。

**视觉证据（阶段 B2，PNG 在仓库外）**：`_ui-review-phase-b/` 下
`b2-hover-gaze.png` · `b2-click-overshoot.png` · `b2-bubble-typing.png`，
命令：`QT_QPA_PLATFORM=offscreen python tools/render_theme_preview.py --stage b2 --outdir <绝对路径>`。

**变异验证（B2）** —— 每条均先破坏源码确认 FAIL 再还原：

| # | 怎么破坏 | 观察到 | 还原 |
|---|---|---|---|
| M1 | 去掉 `_apply_life_signs` 的凝视赋值块 | `test_hover_gaze_writes_look_offsets`、`test_hover_gaze_overrides_expression_template` 双 **FAIL** | 已还原 |
| M2 | 空闲张望去掉 `and not self._hovering` | `test_hover_gaze_suppresses_idle_look_around`、`test_hover_gaze_writes_look_offsets` 双 **FAIL** | 已还原 |
| M3 | 去掉悬停「半眯」眼（openness/curve 覆盖） | `test_hover_uses_half_squint_not_full_arc_eye` **FAIL** | 已还原 |
| M4 | `_surprise_allowed` 去掉 `or self._hovering` | `test_hover_suppresses_surprise_action` **FAIL** | 已还原 |
| M5 | `CLICK_BOUNCE_PX` 调到 8.0（峰值 8.8 > 8.47 上界） | `test_click_bounce_peak_within_1_1x_legacy` **FAIL** | 已还原 |
| M6 | `_revealed_text` 恒返回全文（不截前缀） | `test_revealed_text_is_prefix_substring` **FAIL** | 已还原 |
| M7 | `_measure_word` 改为按子串测量（宽度随打字变化） | `test_word_bubble_width_constant_during_typing` **FAIL** | 已还原 |
| M8 | `show_word` 无视 `reduce_motion`（恒从 0 逐字） | `test_reduce_motion_skips_typing_reaches_terminal_state` **FAIL** | 已还原 |
| M9 | `hide_bubble` 不停止逐字定时器 | `test_hide_bubble_stops_reveal_timer` **FAIL** | 已还原 |
| M10 | `gaze_vector` 去掉分量钳制 | `test_gaze_vector_clamps_components_to_unit` **FAIL** | 已还原 |

> 要点：**M2** 首轮 rc=0 未 FAIL（守卫被后置绝对赋值掩盖）→ 触发上文的**主动修正**；修正后 M2 命中。
> **M5** 证明弹跳上界断言非恒绿；**M7** 证明「宽度恒定」是**按完整词条测量**才成立（按子串测量会挂）。

**遗留 / 诚实说明**

1. `HOVER_GAZE_RANGE_PX = 4.0` 为**主观取值**（略大于空闲张望幅度 3.0）——凝视可见性已由 PNG 目视确认，
   但数值本身无客观基准，后续如觉偏弱可只调该常量。
2. 悬停凝视的 `look_x` 经 `face_center` 基准：`_GEO_BODY_CX/``_GEO_BODY_CY` 是渲染层几何常量，
   `face_center` 已把二者封装为**单一来源**，渲染层若调整脸心，凝视基准会同步跟随（无需改 UI）。
3. 打字感目前只作用于**单词行**（`layout[0]`）；假名 / 翻译 / 释义仍全显（plan §B2-3 明示「前缀子串」单数）。
   若后续要「整块逐行打字」，属独立增量。
4. `CLICK_BOUNCE_PX` 使峰值与旧值**持平**（非「略有过冲」）：为严守「≤1.1 倍 + 不越脏区」两条硬约束，
   选择了物理上最保守的取值；`ease_out_back` 的过冲形状（压扁→弹起→回落）已体现「回弹」观感。


