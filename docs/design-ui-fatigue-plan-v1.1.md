# 大圣喵酱「视觉疲劳改善」实施计划 v1.1

> 版本：v1.1 · 日期：2026-09-18 · **取代** v1.0（`design-ui-fatigue-plan.md`）
> 修订依据：`docs/design-ui-fatigue-plan-review.md`（复审报告）
> 基线事实（实测 2026-09-18 23:58，非引用历史数字）：`pytest tests/` → **839 passed, rc=0, 14.64s**
> venv：`C:\Users\王佐成\.workbuddy\binaries\python\envs\default`，运行须带 `QT_QPA_PLATFORM=offscreen`、`PYTHONPATH=src`

---

## 0. 本次修订总览（v1.0 → v1.1）

复审共提出 16 项意见（5 阻断级 / 5 设计缺口 / 6 细节），**全部采纳**；其中 1 项复审建议经复核**被证伪并修正**（见 §2 的 G1）。

| 复审项 | v1.0 原述 | 处置 | v1.1 落点 |
|---|---|---|---|
| 🔴 R1 | 渲染按 `pose.theme` 取色 | **修正** | 主题改为 `PetRenderer.set_theme()` 实例状态，`PetPose` 零改动（§3 A3） |
| 🔴 R2 | `breath_offset` 加周期抖动参数 | **修正** | 有状态累计相位 + 回绕重抽（§3 A5-1） |
| 🔴 R3 | 用 `_coerce_str` 容错 | **修正** | 新增 `_coerce_theme` 白名单校验（§3 A2） |
| 🔴 R4 | 小动作复用姿态通道 | **补充** | 独立 `SurpriseKind`，**禁用** `Expression` 扩展（§3 A5-2） |
| 🔴 R5 | 基线 785 | **修正** | 基线改为开工当日实测数（当前 **839**）（§0 抬头 / §5） |
| 🟡 G1 | 新色值进 `SEMANTIC_COLORS` | **复审本身有误，见 §2** | 新增**独立模块级常量** `PROP_OUTLINE`（§3 B1-3） |
| 🟡 G2 | 散步 ±20px 随机游走 | **补充** | 锚点 + 瞬态偏移模型，不污染持久化（§3 C1） |
| 🟡 G3 | 「长空闲时随机触发」 | **补充** | IDLE/REST 门控 + 睡觉/拖拽/临时表情抑制（§3 A5-2） |
| 🟡 G4 | `THEME_SEASON_MAP` 月份映射 | **决策** | 四季自动；节日手动（方案 a）（§3 A1-3） |
| 🟡 G5 | 未定义月份来源 | **补充** | `resolve_theme(month, user)` 纯函数 + app 层注入（§3 A3-1） |
| 🟢 P1 | — | 采纳 | 托盘图标跟随主题（§3 A3-4） |
| 🟢 P2 | — | 采纳 | 打字感「全文测量 / 子串绘制」（§3 B2-3） |
| 🟢 P3 | `blink_curve` 加相位参数 | **修正** | 改 `PetModel` 右眼 `elapsed - δ`（§3 A5-3） |
| 🟢 P4 | — | 采纳 | `test_theme_render` 以数据级断言为主（§5） |
| 🟢 P5 | — | 采纳 | 悬停凝视优先级：悬停 > 表情 > 空闲（§3 B2-1） |
| 🟢 P6 | — | 采纳 | `test_config` roundtrip 键集同步加 `theme`（§3 A2） |

**工时变化**：v1.0 的 5.75 人天 → v1.1 的 **7.25 人天**（新增 A0 基线固化、`resolve_theme`、托盘图标参数化、以及 5 个新增测试文件的编写与变异验证）。

---

## 1. 目标与范围

### 1.1 目标
1. **主题皮肤系统**：四季自动换肤，直接打断「永远一样」的视觉疲劳。
2. **动效去机械化**：呼吸节奏微随机、偶发小动作、不对称眨眼，从「循环 GIF」变为「有惊喜的活物」。
3. **色彩与微交互打磨**：光晕随主题、配色更耐看、道具与主体分层、悬停/点击/气泡有即时反馈。
4. **布局节奏**：长空闲时小范围游走与换姿态，消除「钉死在一点」的呆滞感。

### 1.2 范围内
主题渐变表与切换链路、配置字段、动效节奏、光晕派生、道具描边分层、悬停凝视/弹跳过冲/气泡打字感、空闲游走。

### 1.3 明确不在范围内（防范围蔓延）
- ❌ **不新增 `Expression` 枚举成员**（`test_expression_count_matches_prd` 锁定 ==8，属 PRD 级断言）。
- ❌ **不改 `COLORS` 的键集合与值**（`test_color_palette_matches_prd` 全等 + `test_colors_key_set_unchanged_by_p0` 键集双守护）。
- ❌ 不改画布 160×180、不改绘制几何、不改缩放档位。
- ❌ 不动日语学习/详情窗业务逻辑与竞态守卫。
- ❌ 不引入 `time` 到 `core/`，不引入任何外部图片素材或新依赖。

---

## 2. 复审意见逐项处置（含复审报告的自我修正）

### 2.1 阻断级（5 项，全部按修正方案落地）

**R1 — `pose.theme` 与 `PetPose.lerp_to` 类型冲突**
`PetPose` 全 float，`lerp_to` 对每字段执行 `a + (b - a) * t`；字符串进 lerp 首帧即 `TypeError`。
→ **v1.1 做法**：主题是**渲染器实例状态**，不是姿态通道。`PetPose`、`pose_for_expression` 的字段过滤、`EXPRESSION_POSES` 全部零改动。

**R2 — 无状态呼吸抖动会相位跳变**
`cycle_phase = (now / period) % 1`，周期中途变更 → 相位瞬跳 → 每周期一次可见「打嗝」。
→ **v1.1 做法**：`PetModel` 持有 `_breath_phase` / `_breath_period`，逐帧 `phase += dt / period`，回绕时用 `random_interval` 重抽；原 `breath_offset` 签名保留不动。

**R3 — `_coerce_str` 不校验取值**
`"banana"` 直通 → 渲染器 `THEMES["banana"]` → `KeyError`，违背 config 的 FR-39 契约。
→ **v1.1 做法**：照 `_coerce_level` 先例新增 `_coerce_theme`，白名单 = `set(THEMES) | {"auto"}`。

**R4 — 小动作若走 `Expression` 撞数量锁**
→ **v1.1 做法**：独立 `SurpriseKind` 枚举 + 姿态增量表，与 `Expression` 完全解耦。

**R5 — 基线数字失真**
实测 839（v1.0 写 785；历史链 785 → 880 → 839 随瘦身漂移）。**任何硬编码的历史数字都不可信**。
→ **v1.1 做法**：计划只陈述「开工当日实测数」，并把实测命令写进 §5。

### 2.2 设计缺口（5 项）

**G1 — 新色值落点（⚠️ 复审建议有误，此处修正）**
复审报告建议「道具描边色值放 `SEMANTIC_COLORS`，零测试摩擦」。**该结论经复核不成立**：`test_design_tokens.py::test_semantic_colors_keys_match_plan` 对 `SEMANTIC_COLORS` 做的是**全等键集断言**（`set(...) == expected`），新增键同样会挂测试。
→ **v1.1 正确做法**：新增**独立模块级常量**（照 `OUTLINE_W` 先例），两个全等断言都不在射程内，只需同步 `__all__`：
```python
# 道具（键盘 / 鼠标）描边：比主体 ink 略浅，形成「主体 vs 道具」层级差
PROP_OUTLINE: Final[str] = "#4A4A4A"
```
→ **附带教训（写入实施纪律）**：本仓库对**字典类常量**普遍使用全等断言，**「新增键」与「改值」等价危险**；新色值一律优先考虑独立标量常量。

**G2 — 散步污染持久化锚点**
`mouseMoveEvent` → `position_changed` → Controller 持久化 `window_x/y`（FR-36 重启恢复）。散步若走同路径，随机位置会被存成新锚点，跨会话漂移。
→ **v1.1 做法**：锚点 + 瞬态偏移模型；散步不 emit 该信号；拖拽即重锚；退出存锚点。

**G3 — 小动作缺状态门控**
→ **v1.1 做法**：仅 IDLE / REST 两态触发；`SLEEPING` 表情、`is_dragging()`、`_temp_expression` 活动期间、`reduce_motion` 开启时一律抑制。空闲判定与 C1 散步**共用同一阈值**（`REST_THRESHOLD_S`），避免两套空闲定义漂移。

**G4 — 月份粒度表达不了节日（决策）**
春节为农历（公历 1/22–2/19 漂移），圣诞为 12/24–26 窗口，月粒度映射无法表达。
→ **v1.1 决策（方案 a）**：`THEME_SEASON_MAP` **只做四季**；春节/圣诞皮肤**仅由用户手动选择**，首版不做节日自动触发。理由：诚实、零近似误差、零年度维护。若日后要做自动节日，再引入 `THEME_DATE_OVERRIDES`（公历日期窗 + 文档注明不追农历），属独立增量。

**G5 — auto 档月份来源未定义**
→ **v1.1 做法**：`core/theme.py::resolve_theme(month, user_choice)` 纯函数（core 零 `time`）；月份由 **app 层**注入（启动时 + 每日重估定时器）。

### 2.3 细节（6 项）
P1 托盘图标跟随主题、P2 打字感全文测量/子串绘制、P3 不对称眨眼改 `PetModel`、P4 主题渲染数据级断言、P5 悬停凝视优先级、P6 roundtrip 键集加 `theme` —— 均按原建议落地，落点见 §3。

---

## 3. 分阶段实施步骤

```
A0 ─┬─► A1 ─► A2 ─► A3 ─► A4
    └─► A5 ─┬─► B2（微交互）
            └─► C1（布局）
A1 ─────────────────► B1（光晕随主题）
```
（A5 与 A1–A4 相互独立，可并行；B1 仅依赖 A1；B2 / C1 依赖 A5 的动效通道。）

---

### 阶段 A（P0）：主题皮肤系统 + 动效去机械化

**目标**：实现四季自动换肤的完整链路；把呼吸/眨眼/小动作从「机械循环」变为「有随机性的生命感」。全部为**加法或等价替换**，不触碰任何被断言锁定的既有语义。

**预计工时**：4.25 人天

---

#### A0 · 基线固化（前置，0.25 天）

- **范围**：无代码改动。
- **任务**：开工前跑全量测试，记录真实数字作为本阶段基线；确认 `git status --porcelain` 干净、分支为 `feature-*`（禁斜杠）。
- **产出**：基线记录（当前实测 **839 passed / rc=0 / 14.64s**），写入实施日志。

---

#### A1 · 主题渐变表（0.5 天）

- **范围**：`core/constants.py`（纯常量段 + `__all__`）。
- **任务**：
  1. 新增 `THEMES: Final[dict[str, tuple[tuple[float, str], ...]]]`，7 套 × 5 停靠点（位置 0/0.25/0.5/0.75/1.0）：
     `default`（**直接引用 `BODY_GRADIENT_STOPS`**，保证 B1 降饱和时默认皮肤自动跟随）、`spring`、`summer`、`autumn`、`winter`、`spring_festival`、`christmas`。
  2. 新增 `DEFAULT_THEME = "default"`、`AUTO_THEME = "auto"`、`THEME_NAMES`（显示名）、`THEME_SEASON_MAP: dict[int, str]`（**仅 3–5 春 / 6–8 夏 / 9–11 秋 / 12,1,2 冬**，按 G4 决策不含节日）、`THEME_ALLOWED: frozenset[str] = frozenset(THEMES) | {AUTO_THEME}`。
  3. `__all__` 同步新增全部名称（项目红线）。
- **产出**：`constants.py` 常量段；新增 `tests/test_themes.py`。
- **注意**：停靠点位置必须严格单调、首 0.0 末 1.0；色值一律 `#RRGGBB` 字面量。测试期望值**写字面量**，不得用 `C.THEMES[...]` 拼期望（自引用假绿，项目红线）。

---

#### A2 · 配置字段与容错（0.25 天）

- **范围**：`core/config.py` + `tests/test_config.py`。
- **任务**：
  1. 新增 `_coerce_theme(value, default)`：白名单 `C.THEME_ALLOWED`，非字符串/空串/非法值一律回落 `default`（照 `_coerce_level` 写法，**不用 `_coerce_str`**）。
  2. `AppConfig` 新增 `theme: str = C.DEFAULT_THEME`；`to_dict` / `from_dict` 对称。
  3. `tests/test_config.py`：
     - 参数化容错用例：`None / 123 / "" / "banana" / ["autumn"]` → 回落 `"default"`；`"autumn" / "auto"` → 保留。
     - `test_load_after_save_is_json_readable` 的 `set(data)` 期望集合**同步加入 `"theme"`**（可加性契约扩展）。
     - 默认值断言：`AppConfig().theme == C.DEFAULT_THEME`。
- **产出**：配置字段 + 容错器 + 测试；`CONFIG_VERSION` **保持 1**（纯加法，向后兼容）。

---

#### A3 · 主题解析与应用链路（1.25 天）

- **范围**：新建 `core/theme.py`；`ui/pet_renderer.py`；`app/controller.py`；`tests/test_theme_render.py`。
- **任务**：
  1. **`core/theme.py`（新，纯逻辑，零 Qt / 零 time）**：
     ```python
     def resolve_theme(month: int, user_choice: str) -> str:
         """user_choice == AUTO_THEME 时按月份查 THEME_SEASON_MAP，否则原样返回。"""
     def theme_stops(name: str) -> tuple[tuple[float, str], ...]:
         """取主题停靠点；未知名称回落 default（防御性，不抛异常）。"""
     ```
     （常量表留在 `constants.py`，本模块只承载**逻辑**，符合「constants 只放阈值/配色/尺寸/文案」的约定。）
  2. **`PetRenderer` 改为实例状态持有主题**：新增 `set_theme(name)`，内部缓存 `self._stops = C.THEMES[...]`；`_body_gradient` / `_sample_gradient` / `_draw_glow` 改为读 `self._stops`；`paint()` 签名**不变**。
  3. **app 层注入月份**：Controller 在启动时与**每日重估定时器**（`QTimer`，挂 parent）中调用 `resolve_theme(time.localtime().tm_mon, cfg.theme)` → `renderer.set_theme(...)`。跨月零点自动换肤。
  4. **托盘图标跟随主题（P1）**：`build_tray_icon(stops)` 参数化（`_paint_tray_face` 同步），切换主题时重建并 `setIcon`。
- **产出**：`core/theme.py` + 渲染取色链路 + 新测试 `tests/test_theme_render.py`（**数据级断言为主**，P4）：
  - `resolve_theme` 逐月字面量期望（1→winter、4→spring、7→summer、10→autumn）；
  - `resolve_theme(6, "christmas") == "christmas"`（手动覆盖 auto）；
  - 各主题停靠点**互不相同**、`_sample_gradient` 同一 frac 在不同主题下返回不同色值；
  - `paint()` 遍历 7 主题 offscreen 跑通不抛异常（smoke）。

---

#### A4 · 托盘主题菜单（0.5 天）

- **范围**：`ui/tray.py` + `app/controller.py` + `tests/test_tray.py`（若无则并入 `test_ui_smoke`）。
- **任务**：
  1. 新增信号 `theme_selected = Signal(str)`；照 `scale_menu` 先例新增「主题」子菜单：`QActionGroup`（`setExclusive(True)`），含「自动」+ 7 套皮肤，每项 `checkable`。
  2. 新增 `set_theme_checked(value: str)`（`blockSignals` 同步勾选，不触发信号）。
  3. Controller 接线：写 `cfg.theme` → 保存配置 → `renderer.set_theme(resolve_theme(month, cfg.theme))` → 重建托盘图标 → `tray.set_theme_checked(...)`。
- **产出**：托盘菜单 + 接线 + 测试（信号发射正确、单选互斥、勾选同步不重入）。

---

#### A5 · 动效节奏去机械化（1.5 天）

- **范围**：`core/motion.py`、`core/pet_model.py`、`core/constants.py`（新阈值）、`tests/test_motion_rhythm.py`。
- **任务**：

  **A5-1 呼吸微随机（R2 修正方案）**
  - `motion.py` 新增纯函数 `breath_offset_phased(phase: float, amplitude: float) -> float`；`breath_offset` **保留原签名与行为**（其他调用方不动）。
  - `PetModel` 新增 `_breath_phase` / `_breath_period`；`_apply_life_signs` 改用相位版：
    `phase += dt / period`；`phase >= 1.0` 时 `-= 1.0` 并用 `motion.random_interval(BREATH_PERIOD_S * (1 - J), BREATH_PERIOD_S * (1 + J), self._rng)` 重抽。
  - 常量：`BREATH_JITTER: Final[float] = 0.10`（`BREATH_PERIOD_S == 3.0` 为 PRD 锁定值，**不动**）。
  - 测试断言：相位连续（回绕前后相邻帧位移差 < 单帧最大增量）、重抽周期落在 ±10% 区间、固定种子输出可复现。

  **A5-2 偶发小动作（R4 + G3 修正方案）**
  - 新增 `SurpriseKind` 枚举（在 `core/pet_model.py`，**不得进 `Expression`**）：如 `STRETCH`（伸懒腰）/`TAIL_FLICK`（甩尾）/`EAR_FLICK`（抖耳）/`GLANCE_CORNER`（看角落）。
  - 每种动作定义为**姿态增量表**（`constants.SURPRISE_POSES: dict[SurpriseKind, dict[str, float]]`），仅使用现有通道（`body_y`/`body_squash`/`head_tilt`/`ear_*_tilt`/`tail_angle`/`look_x`/`look_y`）。
  - `motion.py` 新增 `surprise_envelope(elapsed, duration) -> float`（缓出-保持-回弹，复用 `ease_out_cubic` / `ease_in_out`）。
  - `PetModel` 调度状态 `_surprise_timer` / `_surprise_kind` / `_surprise_elapsed`，间隔用 `random_interval(SURPRISE_MIN_S, SURPRISE_MAX_S, rng)`。
  - **门控（必做）**：仅当 `_base_expression` 属 IDLE/REST 对应态、非 `_dragging`、非 `SLEEPING`、`_temp_expression is None` 时才推进与触发；触发阈值挂 `REST_THRESHOLD_S`。
  - **`reduce_motion` 开启时**：不调度、不叠加（由 UI 层把开关写入模型，或模型持有该标志）。
  - 常量：`SURPRISE_MIN_S: Final[float] = 40.0`、`SURPRISE_MAX_S: Final[float] = 80.0`。

  **A5-3 不对称眨眼（P3 修正方案）**
  - `blink_curve` **签名与实现不动**；`PetModel._apply_life_signs` 中右眼改用 `motion.blink_curve(max(0.0, self._blink_elapsed - C.BLINK_EYE_DELAY_S), C.BLINK_DURATION_S)`，左眼保持原值。
  - 常量：`BLINK_EYE_DELAY_S: Final[float] = 0.05`。
  - 注意 `_draw_eye` 的 `openness < 0.18` 会切弧线眼——延迟量需小于 `BLINK_DURATION_S` 的一半，避免两眼视觉上「不同种类」。

- **产出**：`test_motion_rhythm.py`——呼吸相位连续性、重抽区间、固定种子可复现、小动作门控（SLEEPING/拖拽/临时表情/reduce_motion 下**不触发**）、`surprise_envelope` 端点值字面量断言、眨眼延迟只影响右眼。

**阶段 A 交付物**：7 套皮肤全链路可切换 + auto 按月生效 + 动效去机械化；新增 4 个测试文件。

---

### 阶段 B（P1）：色彩微调 + 微交互反馈

**目标**：让长时间驻留的配色更耐看、层次分明；每次交互都有即时且克制的回应。

**预计工时**：2.0 人天 · **依赖 A1（`THEMES`）与 A5（动效通道）**

---

#### B1 · 色彩微调（0.5 天）

- **范围**：`core/constants.py`、`ui/pet_renderer.py`、`tests/test_palette_level.py`。
- **任务**：
  1. **光晕随主题派生**：新增纯函数（`core/theme.py`）`glow_for_theme(name, sleeping) -> str`——清醒时取该主题**暖端主色**派生，睡觉时取**冷端派生**（保持「睡觉淡蓝」的语义，不机械取色）。
  2. **降饱和**：只改 `BODY_GRADIENT_STOPS` 的**色值**（结构/数量/位置不变）。已核实 `test_body_gradient_and_outline_defined` 只查结构（数量/单调/0→1/合法 hex），**改值不破坏断言**。分两次提交（每档 5%），每次附截图对比，一次只动一档。
  3. **道具描边分层（G1 修正方案）**：新增**独立标量常量** `PROP_OUTLINE`（+ `__all__` 同步），渲染器新增 `_outline_prop` 笔，`_draw_keyboard` / `_draw_mouse` 改用它；主体、面部、前爪继续用 `_outline`（ink）。
- **产出**：`tests/test_palette_level.py`——`PROP_OUTLINE != C.COLORS["ink"]`（字面量期望）、色值合法 `#RRGGBB`、`PROP_OUTLINE in C.__all__`、`COLORS` 键集与值均未变（回归）。

---

#### B2 · 微交互（1.5 天）

- **范围**：`ui/pet_window.py`、`ui/bubble.py`、`core/pet_model.py`、`tests/test_micro_interaction.py`。
- **任务**：
  1. **悬停凝视（含 P5 优先级）**：悬停超 `HOVER_TRIGGER_S` 后，宠物**看向光标**（由 `look_x/look_y` 驱动瞳孔）+ 尾巴轻摆。优先级明确为 **悬停 > 表情模板 > 空闲张望**；`_apply_life_signs` 中空闲 `look_around_offset` 在悬停期间不写入。悬停表情降为「半眯」（openness≈0.55）而非全闭弧线眼，否则凝视不可见。
  2. **点击弹跳过冲**：`_apply_actions` 的弹跳改用 `motion.ease_out_back`（已存在）替代/叠加现有 `ease_out_bounce`，得到「压扁 → 弹起 → 轻微过冲回落」的物理感；幅度不超过现值的 1.1 倍（避免越出脏区）。
  3. **气泡打字感（P2 修正方案）**：`bubble.py` 的 `_measure` / `_word_layout` **仍按完整词条一次算定**，仅 `_paint_word` 按 reveal 进度绘制**前缀子串**——气泡尺寸在打字过程中**恒定**（`test_jp_bubble_visual` 的固定宽度契约不破）。reveal `QTimer` 挂 parent，并在 `hide_bubble()` 与提前关闭路径中 `stop()`；`reduce_motion` 开启时跳过逐字、直接全显。
- **产出**：`tests/test_micro_interaction.py`（悬停优先级、弹跳幅度上界、打字感在 reduce_motion 下直达终态、QTimer 停止）+ 复跑 `test_jp_bubble_visual.py` 保绿。

**阶段 B 交付物**：配色层级分明 + 三类微交互；新增 2 个测试文件。

---

### 阶段 C（P2）：布局节奏优化

**目标**：消除「钉死在一个像素点」的呆滞感，画面有呼吸感。

**预计工时**：1.0 人天 · **依赖 A5（空闲判定与姿态通道）**

---

#### C1 · 空闲游走与偶发换姿态（1.0 天）

- **范围**：`ui/pet_window.py`、`app/controller.py`、`tests/test_idle_wander.py`。
- **任务**：
  1. **锚点 + 瞬态偏移模型（G2 修正方案）**：
     - Controller 维护 `anchor_x/anchor_y`（= 持久化的 `window_x/y`）；
     - 游走 = `anchor + offset`，`offset` 严格有界（±20px）；
     - **游走的 `move()` 不得 emit `position_changed`**（该信号只服务于用户拖拽 → 持久化）；
     - 用户开始拖拽 → 立刻清零 `offset` 并**重锚**（把新位置作为锚点写入配置）；
     - 退出保存**锚点**，不读 `pos()`。
  2. **偶发换姿态**：复用 A5 的 `SurpriseKind` 机制新增姿态（正坐 ↔ 侧卧 / 趴着），同样受 IDLE/REST 门控与 `reduce_motion` 抑制。
  3. **越屏保护**：每次移动后仍走 `motion.clamp_to_screens`（多显示器安全）。
  4. **定时器**：游走节奏用 `QTimer` 挂 parent，`closeEvent` / `stop_animation` 时 `stop()`。
- **产出**：`tests/test_idle_wander.py`——位移严格有界（含边界钳制）、锚点不被游走改写、拖拽重锚、多屏 `clamp_to_screens` 回落；复跑 `test_dirty_rect_no_clip`、`test_ui_smoke`、`test_memory_budget`。

**阶段 C 交付物**：空闲游走 + 换姿态；新增 1 个测试文件。

---

## 4. 依赖关系与里程碑

### 4.1 依赖矩阵

| 任务 | 依赖 | 可否并行 |
|---|---|---|
| A0 基线固化 | — | 前置，必须最先 |
| A1 主题表 | A0 | 与 A5 并行 |
| A2 配置字段 | A1（`DEFAULT_THEME` / `THEME_ALLOWED`） | 串行 |
| A3 解析与应用 | A1 + A2 | 串行 |
| A4 托盘菜单 | A2 + A3 | 串行 |
| A5 动效节奏 | A0（+ A1 的常量段合并提交） | **与 A1–A4 并行** |
| B1 色彩微调 | A1（THEMES 取色） | 可在 A 完成后独立做 |
| B2 微交互 | A5（动效通道） | 与 B1 并行 |
| C1 布局节奏 | A5（空闲门控/姿态通道） | 与 B 并行（但改动窗口定位，建议最后做） |

### 4.2 里程碑

| 里程碑 | 对应 | 判定 |
|---|---|---|
| **M1** | 阶段 A 完成 | 7 套皮肤可切换 + auto 按月生效 + 动效去机械化；基线（实测 839）+ 新增测试**全绿** |
| **M2** | 阶段 B 完成 | 配色层级分明（`PROP_OUTLINE` 生效）+ 三类微交互；**全绿** |
| **M3** | 阶段 C 完成 | 游走有界且不污染锚点；**全绿** |

### 4.3 提交节奏（每 commit 后跑全量，`develop` 始终可回滚）

```
A1+A2: feat(theme): 主题渐变表 + AppConfig.theme + _coerce_theme
A3:    feat(theme): resolve_theme 纯函数 + 渲染取色 + 托盘图标跟随
A4:    feat(theme): 托盘「主题」子菜单（含「自动」）
A5:    feat(motion): 呼吸相位随机化 + SurpriseKind 小动作 + 不对称眨眼
B1:    feat(palette): 光晕随主题 + 降饱和（两档）+ PROP_OUTLINE 道具描边
B2:    feat(interact): 悬停凝视 + 弹跳过冲 + 气泡打字感
C1:    feat(idle): 锚点式空闲游走 + 偶发换姿态
```

---

## 5. 验收标准

### 5.1 每阶段通用（项目既定七项）

1. `git status --porcelain` 空；2. HEAD 与远端基线一致；3. `git diff --quiet` 通过；4. `git clean -ndx` 仅剩构建缓存（`build/` `dist/` `__pycache__`，判据 = **无游离源码**）；5. 分支干净；6. **pytest 全绿**；7. 无新增图片素材。

### 5.2 基线命令（数字以**开工当日实测**为准，不硬编码历史值）

```bash
export PATH="/usr/bin:/bin:/mingw64/bin:/c/Windows/System32:$PATH"
cd "<repo>" && PYTHONPATH=src QT_QPA_PLATFORM=offscreen \
  "<venv>/Scripts/python.exe" -m pytest tests/ -p no:cacheprovider
# 2026-09-18 实测：839 passed in 14.64s（rc=0）
```

### 5.3 各阶段专项验收

| 阶段 | 必须满足 |
|---|---|
| A | ① 7 套皮肤逐一切换，渲染不崩、渐变互不相同；② `auto` 按月份生效且可被手动覆盖；③ 非法 theme 配置回落默认（含 `"banana"`）；④ 呼吸相位连续无跳变；⑤ 小动作在 SLEEPING / 拖拽 / 临时表情 / `reduce_motion` 下**不触发**；⑥ `Expression` 成员数仍 == 8；⑦ `COLORS` 键值未变 |
| B | ① `PROP_OUTLINE != ink` 且 `COLORS` 键值未变、`SEMANTIC_COLORS` 键集未变；② 气泡宽度在打字过程中恒定（`test_jp_bubble_visual` 绿）；③ 悬停优先级生效（悬停期间空闲张望不写入）；④ `reduce_motion` 下打字感直达终态 |
| C | ① 位移严格 ≤ ±20px 且有界；② **锚点不被游走改写**（重启后位置 = 锚点）；③ 拖拽即重锚；④ 多屏 `clamp_to_screens` 生效；⑤ `test_dirty_rect_no_clip` / `test_memory_budget` 绿 |

### 5.4 测试纪律（红线）

- **变异验证**：每个新增断言必须先「故意破坏源码」证明能 FAIL，防恒绿假测试。
- **期望值写字面量**：不得用被测常量拼期望（自引用假绿）。
- **新增测试文件即时全量**：每个改动点单独跑全量，不攒批。
- 改完 `constants.py` 先跑 `test_static_constraints.py`（最快暴露架构违规）+ `test_design_tokens.py`。

---

## 6. 风险说明

| # | 风险 | 影响 | 应对 |
|---|---|---|---|
| 1 | `PetPose` 误加非 float 字段（R1 复发） | 首帧崩溃 | 主题只走 `PetRenderer` 实例状态；新增测试断言 `PetPose` 全字段为 float |
| 2 | 呼吸相位实现不当仍跳变（R2 复发） | 观感劣化且难测 | 断言**相邻帧位移连续性**（而非仅区间），并做变异验证 |
| 3 | 配置出现非法 theme 字符串（R3 复发） | 启动崩溃 | `_coerce_theme` 白名单 + 参数化容错测试（含 `"banana"`） |
| 4 | 小动作误用 `Expression` 扩展（R4 复发） | 撞 PRD 级断言返工 | 实施前明确 `SurpriseKind` 独立；`test_expression_count_matches_prd` 保持绿 |
| 5 | 给字典类常量**新增键**（G1 类） | 全等断言挂 | 新色值一律优先**独立标量常量**；改字典键集前先跑 `test_design_tokens` / `test_color_palette_matches_prd` |
| 6 | 游走污染持久化锚点（G2） | 跨会话位置漂移，用户可感知 | 锚点模型 + 不 emit `position_changed` + 专项测试 |
| 7 | 游走/小动作在睡觉或打字时触发（G3） | 姿态冲突、观感违和 | IDLE/REST 门控 + 四种抑制条件逐一测 |
| 8 | 降饱和「改丑了」 | 主观效果不佳 | 分两档、每档 5%、一次只动一档、附截图对比；可回滚 |
| 9 | 随机性导致测试不稳定 | 假失败 | 全部随机走 `rng` 注入 + 固定种子；禁止裸 `random` |
| 10 | 新增 QTimer 泄漏 | `test_memory_budget` 挂 | 一律挂 parent，窗口 `closeEvent` / 停止动画时 `stop()` |
| 11 | 主题切换瞬间脏区残留 | 边缘色块 | 切换后整窗 `update()` 一次（非脏区），并复跑 `test_dirty_rect_no_clip` |
| 12 | 工程量上升导致范围蔓延 | 交付延期 | 严格按 §1.3「不做清单」；节日自动换肤等增量一律后置 |
| 13 | `core` 误引 `time`（auto 档） | 架构红线 | 月份由 app 层注入；`test_core_imports_without_loading_qt` 保持绿（建议把 `core.theme` 加入该测试的导入清单以加固） |

---

## 7. 附录

### 7.1 关键落点速查

| 内容 | 文件 | 备注 |
|---|---|---|
| 主题渐变表 / 季节映射 / 白名单 | `core/constants.py` | 纯常量；`__all__` 同步 |
| `resolve_theme` / `theme_stops` / `glow_for_theme` | `core/theme.py`（新） | 纯逻辑，零 Qt / 零 time |
| `theme` 字段 + `_coerce_theme` | `core/config.py` | `CONFIG_VERSION` 保持 1 |
| 呼吸相位 / 小动作 / 眨眼延迟 | `core/pet_model.py` + `core/motion.py` | 调度在模型、纯函数在 motion |
| 主题取色 / 光晕 / 道具描边 / 托盘图标 | `ui/pet_renderer.py` | `set_theme()` 实例状态 |
| 主题菜单 | `ui/tray.py` | 照 `scale_menu` 先例 |
| 月份注入 / 接线 / 锚点 | `app/controller.py` | 唯一的 `time` 使用点 |
| 悬停凝视 / 游走 | `ui/pet_window.py` | 游走不 emit `position_changed` |
| 打字感 | `ui/bubble.py` | 全文测量、子串绘制 |

### 7.2 新增测试文件清单

`test_themes.py`（A1）· `test_theme_render.py`（A3）· `test_motion_rhythm.py`（A5）· `test_palette_level.py`（B1）· `test_micro_interaction.py`（B2）· `test_idle_wander.py`（C1）；扩展：`test_config.py`（A2）、`test_tray.py` 或 `test_ui_smoke.py`（A4）。

### 7.3 v1.0 保留不变的判断

`COLORS` 冻结、主题走新 `THEMES` 表、渐变断言只查结构、`rng` 注入、托盘 `scale_menu` 先例、阶段依赖（后项只依赖前项常量/接口）、提交节奏 —— 全部继承 v1.0。
