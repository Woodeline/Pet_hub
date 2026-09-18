# 「视觉疲劳改善」实施计划 复审报告

> 版本：v1.0 · 日期：2026-09-18
> 复审对象：`docs/design-ui-fatigue-plan.md`（v1.0，2026-09-18）
> 复审方法：逐条对照真实代码（`config.py` / `motion.py` / `pet_model.py` / `pet_renderer.py` / `tray.py` / `pet_window.py` / `bubble.py`）与真实测试（`test_static_constraints.py` / `test_config.py`），并实测当前测试收集数。
> 复审人：小豆豆（UI/UX 专家会话）

---

## 0. 总体结论

**方向正确、结构合理，但存在 5 处阻断级问题，不修正就开工必然翻车。**

方案的三根支柱（新增 `THEMES` 表冻结 `COLORS`、随机走 `rng` 注入、阶段独立提交）经核实均成立；但若干「已核实」的表述与代码事实存在偏差——最严重的是 `pose.theme` 与 `PetPose.lerp_to` 的类型系统冲突（开工即崩溃）和测试基线数字失真（785 → 实测 839）。

| 等级 | 数量 | 含义 |
|---|---|---|
| 🔴 阻断级 | 5 | 实施时必然产生崩溃 / 断言失败 / 误导 |
| 🟡 设计缺口 | 5 | 会造成返工或明确的体验缺陷 |
| 🟢 细节打磨 | 6 | 建议明确化，不阻塞开工 |

---

## 1. 阻断级问题（必须先改计划）

### 🔴 R1. `pose.theme` 会击穿 `PetPose.lerp_to` 的全浮点契约

- **位置**：计划 A3「`pet_renderer.py` 的 `_body_gradient`/`_sample_gradient` 改为按 `pose.theme`（或传入主题名）从 `THEMES` 取渐变」。
- **原因**：`PetPose` 是**纯 float dataclass**（33 个通道全为 float），`lerp_to` 对**所有字段**无差别执行 `motion.lerp(getattr(self, f), getattr(other, f), t)`，即 `a + (b - a) * t`。字符串不支持减法，加入 `theme: str` 字段后**第一次 `update()` 就抛 `TypeError`**。这不是风格问题，是类型系统层面的硬冲突。
- **影响**：主循环每帧崩溃，应用无法启动（宠物窗口首帧即挂）。
- **修正**：删除 `pose.theme` 提法，**统一走「传入主题名」路线**——主题是**渲染器/控制器级状态**，不是姿态通道：
  - `PetRenderer` 增加实例状态（如 `set_theme(name)`），或 `paint()` 增加参数；
  - `_body_gradient` / `_sample_gradient` / `_draw_glow` 改为读实例主题；
  - 主题切换由 Controller 调 `renderer.set_theme()`，与 `PetPose` 完全解耦。
  - 这样 `lerp_to`、`pose_for_expression` 的字段过滤、`EXPRESSION_POSES` 常量表**一行不用动**。

### 🔴 R2. 呼吸周期随机化不能按计划的无状态写法实现（会产生相位跳变）

- **位置**：计划 A4「`breath_offset` 增加『每次循环后周期重抽 ±10%』的抖动参数」。
- **原因**：`breath_offset` 是**无状态**函数——`phase = (now / period) % 1`。周期中途换 `period`，同一 `now` 算出的相位会**瞬间跳变**（例如 period 从 3.0 变 3.3，相位从 0.99 跳回 0.90），正弦位移突跳 → 每 3 秒一次可见「打嗝」。**这比机械匀速更伤观感**，与「去机械化」的目标正好相反。
- **影响**：A4 做完后呼吸反而变丑；且 `test_motion_rhythm` 若只断言「周期在 ±10% 区间」根本测不出跳变（每次调用都是合法值），变异验证也发现不了。
- **修正**：改为**有状态累计相位**（与眨眼同款模式，`PetModel` 已有先例）：
  - `PetModel` 持有 `_breath_phase` 与 `_breath_period`；
  - 每帧 `_breath_phase += dt / _breath_period`；`_breath_phase >= 1.0` 时回绕并重抽 `_breath_period = random_interval(0.9P, 1.1P, rng)`；
  - `breath_offset` 保留原签名不动（其他调用方不受影响），新增 `breath_offset_phased(phase, amplitude)` 纯函数供模型调用；
  - 帧率无关性保持（`dt` 累计），可 mock `rng` 单测「回绕时重抽、区间正确、相位连续（回绕前后差 < 一帧增量）」。
  - 注意 `BREATH_PERIOD_S == 3.0` 是 PRD 锁定常量（`test_constants_match_prd`），**基础值不动**，抖动是 ±10% 的乘子。

### 🔴 R3. `theme` 字段用 `_coerce_str` 容错 = 留下崩溃入口

- **位置**：计划 A2「用 `_coerce_str` 容错回落（非法值回落 default）」。
- **原因**：`_coerce_str` 只校验「是不是字符串」，不校验取值。配置文件里 `"theme": "banana"` 会原样通过，随后渲染器 `THEMES["banana"]` → `KeyError`。这违背 `config.py` 自己的模块契约——「字段类型错误/**越界值** → 逐字段回落默认值，绝不抛异常崩溃」（FR-39 / 架构 §9.6）。
- **影响**：手改配置 / 上游版本残留一个非法主题名，应用启动即崩。而且这个路径**现有测试覆盖不到**（没人会想到测一个「合法类型非法取值」的字符串）。
- **修正**：照 **`_coerce_level`**（校验 `JP_LEVELS` 白名单）的先例，新增 `_coerce_theme`：
  ```python
  def _coerce_theme(value: Any, default: str) -> str:
      if isinstance(value, str):
          candidate = value.strip()
          if candidate in C.THEME_ALLOWED:   # set(THEMES) | {"auto"}
              return candidate
      return default
  ```
  计划 A2 的验收测试也要相应加用例：`"banana" / "" / None / 123` → 回落 default，`"autumn"` → 保留。

### 🔴 R4. 「偶发小动作」若走新增 `Expression` 路线，会撞死在数量锁上

- **位置**：计划 A4「偶发小动作：伸懒腰/甩尾/抖耳/看角落」。
- **原因**：`test_expression_count_matches_prd` 断言 `len(list(Expression)) == 8`——这是 **PRD 锁定断言**，不是可加性契约。把「伸懒腰」做成第 9 个 `Expression` 枚举成员必然挂测试；而放宽该断言意味着改 PRD，超出本计划权限。
- **影响**：实施者最自然的实现路径（加表情枚举）恰好是死路；发现晚的话要返工整个触发机制。
- **修正**：明确写入计划——小动作走**独立的姿态叠加通道**，不碰 `Expression`：
  - `PetModel` 增加 `_surprise_action: Optional[SurpriseKind]` + `_surprise_timer`（`SurpriseKind` 是新的独立枚举，非 Expression）；
  - 每种动作定义为一个**姿态增量 dict**（复用 `body_y`/`head_tilt`/`tail_angle`/`ear_*_tilt` 等现有通道，与 `_apply_life_signs` 同层叠加）；
  - 动作包络复用 `_keystroke_envelope` 的「缓出-保持-回弹」思路，新建 `surprise_envelope(elapsed)` 纯函数进 `motion.py`。

### 🔴 R5. 测试基线数字失真：计划写 785，实测 839

- **位置**：计划 §5「改前快照 `pytest -q`（785 passed）」及约束基线表述。
- **原因**：实测（2026-09-18，`--collect-only`，退出码 0 无收集错误）当前用例总数为 **839**，与计划及此前会话记忆中的 785 不符——785 是更早时点的快照，其间测试有增长。
- **影响**：以 785 为「改前快照」基准，任何人复核时都会对不上数，进而怀疑「是不是有测试被删了」——在高纪律测试文化的项目里这是**信任级事故**。
- **修正**：开工前先跑一次全量记录真实数字（839 或当时的值）写进计划；且建议计划行文改为「以**开工当日实测数**为基线」，不硬编码历史数字。

---

## 2. 设计缺口（不阻断，但会造成返工 / 体验缺陷）

### 🟡 G1. B1「道具描边分层」的色值落点没找对——加键同样会挂全等断言

- **原因**：`test_color_palette_matches_prd` 是**全字典相等**（`C.COLORS == expected`）。计划风险表只写了「改现有键值触发断言」，漏了**新增键也会触发**（dict 相等要求键集也一致）。「键盘/鼠标描边略浅灰」必然需要一个新色值。
- **影响**：实施者把 `prop_outline` 加进 `COLORS` → 测试挂 → 以为撞了红线，实际是漏改测试。
- **修正**：新色值放 **`SEMANTIC_COLORS`**（已存在，`constants.py` L181，且不在任何全等断言的射程内），`COLORS` 保持键集与值双重冻结。这是零测试摩擦的落点。若一定要进 `COLORS`，则按「可加性契约扩展」先例同步扩 `test_color_palette_matches_prd` 的 expected——但没必要。

### 🟡 G2. C1「空闲散步」会污染持久化锚点，跨会话漂移

- **原因**：`PetWindow` 的位置持久化链是：拖拽 `mouseMoveEvent` → `position_changed` 信号 → Controller 保存 `window_x/y`（FR-36 重启恢复）。散步若直接 `move()` 并走同一条信号（或退出时读 `pos()` 保存），**散步结束时的随机位置**会被存成新锚点。每开一次机锚点漂一点，几次之后宠物「离家出走」。
- **影响**：用户明确感知的回归 bug；且极难从单测发现（offscreen 测不出窗口几何语义）。
- **修正**：写入计划的 C1 约束：
  - 散步 = **锚点 + 瞬态偏移**，`window_x/y` 只存锚点；
  - 散步的 `move()` **不得** emit `position_changed`；
  - 用户开始拖拽 = 重新锚定，散步偏移即刻清零；
  - 退出保存时保存锚点而非 `pos()`。

### 🟡 G3. `idle_surprise` 缺 mood / 状态门控

- **原因**：计划只说「长空闲时随机触发」。但项目有四态情绪机（`Mood = IDLE/FOCUS/REST/SLEEP`，阈值 `IDLE_START_S=20 / REST_THRESHOLD_S=120 / SLEEP_THRESHOLD_S=300`）。睡觉时触发「伸懒腰」会与 `zzz_alpha`/`glow_alpha`/睡眠呼吸幅度（×0.25）打架；FOCUS 态（用户正在打字）触发会与敲击反馈抢通道。
- **影响**：姿态叠加冲突 → 画面抽搐或动作互相吞掉；睡觉中突然做小动作也违背「静音休息」的产品直觉。
- **修正**：门控条件写入 A4：仅在 `IDLE / REST` 两态触发；`SLEEPING` 表情、`is_dragging()`、`_temp_expression` 活动期间一律抑制；触发阈值建议挂在 `REST_THRESHOLD_S`（120s）之后，与「散步」（C1）共享同一空闲判定，避免两套空闲定义漂移。

### 🟡 G4. `THEME_SEASON_MAP` 的月份粒度表达不了节日窗口

- **原因**：前一轮方案明确「春节前后」「圣诞 12/24–26」，但计划 A1 的落点 `THEME_SEASON_MAP`（月份 → 皮肤）只有**月粒度**。春节是农历节日，公历日期每年在 1/22–2/19 间漂移；圣诞若按整月 12 月都是圣诞皮肤，则与「冬雪」皮肤几乎全月冲突。
- **影响**：要么节日皮肤霸占整月（季节皮肤形同虚设），要么实现时擅自改语义（计划与实现漂移）。
- **修正**（二选一，需明确决策）：
  - **方案 a（推荐，简单诚实）**：月粒度映射只做**四季**；节日皮肤**只由用户手动选择**，不做自动触发。首版砍掉「春节/圣诞自动」承诺。
  - **方案 b**：增加 `THEME_DATE_OVERRIDES: list[(month, day_range, theme)]` 公历日期窗表（如圣诞 12/24–26）；春节按近三年公历区间近似（如 1/20–2/10），文档注明「公历近似，不追农历」。每年无需改代码，精度取舍写明即可。

### 🟡 G5. 「auto 档」的月份来源与注入点未定义

- **原因**：core 层禁止 import `time`（计划风险表自己也写了），但 auto 档要「按月份」决策——**月份从哪来**计划没说。若在 `constants.py` 或 `config.py` 里偷懒 `import time`，直接撞 `test_core_imports_without_loading_qt` 同级的架构红线（core 零 time 是项目约定）。
- **影响**：实施时要么违规（架构测试风险），要么卡住。
- **修正**：core 提供**纯函数** `resolve_theme(month: int, user_choice: str) -> str`（`user_choice="auto"` 时查 `THEME_SEASON_MAP[month]`，否则原样返回）；月份由 **app 层**（Controller）在启动时与每日定时器里注入 `time.localtime().tm_mon`。测试用字面量月份，零 mock 负担。同时写明重估时机（建议：启动时 + 每天一次，跨月零点自动换肤）。

---

## 3. 细节打磨（建议明确，不阻塞）

### 🟢 P1. 托盘图标不随主题切换

`build_tray_icon()` / `_paint_tray_face()` 直接读 `C.BODY_GRADIENT_STOPS`（模块级常量），用户切到「秋日暖阳」后托盘仍是彩虹脸。建议决策：跟随主题（`build_tray_icon(theme_stops)` 化，切换时重建图标）或保持品牌一致（托盘恒为默认彩虹）。推荐前者——托盘是「换装」感知的重要触点，成本也低（改静态方法签名）。

### 🟢 P2. 「打字感」气泡必须按**全文**测量、按**子串**绘制

`test_jp_bubble_visual` 锁定气泡固定宽度；`bubble.py` 现有 `_measure`/`_word_layout` 均按完整词条测量。打字感若逐字重新测量/resize，气泡会在打字过程中伸缩，撞测试且观感廉价。正确机制：**几何按全文一次算定，reveal 只裁剪绘制子串**（`drawText` 传前缀）。同时 reveal 的 QTimer 必须挂 parent、在 `hide_bubble()` 与气泡提前关闭路径里 `stop()`（计划的风险表有通用要求，但应把这两条写死在 B2 验收里）。

### 🟢 P3. 「不对称眨眼」的改动点在 PetModel，不在 `blink_curve`

计划写「`blink_curve` 支持左右眼相位偏移参数」——层不对。现状是**单个** `_blink_timer/_blinking/_blink_elapsed` 状态同时驱动双眼（`_apply_life_signs` 里两眼乘同一 openness）。改法：PetModel 内右眼用 `max(0, elapsed - δ)` 计算（δ≈40–80ms），`blink_curve` 签名可以完全不动。落点写错会导致实施者在纯函数上白做一层没人调用的参数。

### 🟢 P4. `test_theme_render` 的断言策略：数据级为主，像素级为辅

offscreen 下逐像素对比渐变既慢又脆（抗锯齿/浮点）。建议：主断言在数据级——`THEMES` 各主题停靠点互不相同、`_sample_gradient` 同一 frac 在不同主题下返回不同色值、`paint()` 各主题跑通不抛异常（smoke）。像素级对比只留一组固定种子的黄金样本（可选）。

### 🟢 P5. 悬停「看向光标」与现有两套 look 逻辑的优先级未定义

`look_x` 已有两个写入方：空闲张望 `look_around_offset`（`_apply_life_signs`）与表情模板。悬停又触发 HAPPY（眯眼弧线眼）——**眼睛都闭上了，「看向光标」根本不可见**。建议：悬停回应 = 减弱眯眼（如 openness 0.55 而非弧线眼）+ 悬停凝视**覆盖**空闲张望（优先级：悬停 > 表情 > 空闲），并把该优先级写进 B2 设计说明。

### 🟢 P6. `test_config` 往返契约需同步加 `theme` 键

`test_load_after_save_is_json_readable` 断言 `set(data) == {...}` 全等键集。A2 落地时必须把 `"theme"` 加进该集合（可加性契约扩展，与 `reduce_motion` 先例一致）。计划 A2 验收里没列这条，漏了会挂一次测试才知道。

---

## 4. 修正后的关键设计要点（替换计划对应条目）

| 计划条目 | 原表述 | 修正后 |
|---|---|---|
| A2 | `_coerce_str` 容错 | `_coerce_theme` 白名单校验（`THEME_ALLOWED = set(THEMES) \| {"auto"}`）；roundtrip 测试键集加 `theme` |
| A3 | 按 `pose.theme` 取渐变 | `PetRenderer.set_theme(name)` 实例状态；`paint` 链路不改签名；托盘图标同步决策（P1） |
| A4 | `breath_offset` 加抖动参数 | PetModel 有状态 `_breath_phase` 累计 + 回绕重抽；`breath_offset_phased` 新纯函数 |
| A4 | `blink_curve` 相位偏移 | PetModel 右眼 `elapsed - δ`；`blink_curve` 不动 |
| A4 | `idle_surprise(now, rng)` | 调度状态在 PetModel（同眨眼先例）；`surprise_envelope` 纯函数进 motion；独立 `SurpriseKind`，**不碰 Expression**；IDLE/REST 门控 + 拖拽/睡觉抑制 |
| A1 | `THEME_SEASON_MAP` 月份映射 | 四季走月映射；节日走 G4 方案 a（手动）或 b（公历日期窗），二选一明确写死 |
| 新增 | — | `resolve_theme(month, user_choice)` 纯函数 + app 层注入月份 + 每日重估 |
| B1 | 道具描边浅灰 | 色值进 `SEMANTIC_COLORS`，`COLORS` 键集值全冻结 |
| C1 | ±20px 随机游走 | 锚点+瞬态偏移模型；散步不 emit `position_changed`；拖拽即重锚；退出存锚点 |
| §5 | 785 基线 | 开工当日实测数（当前 839） |

---

## 5. 复审中核实为正确的关键判断（无需改动）

1. ✅ `test_color_palette_matches_prd` 确为全字典相等——「`COLORS` 冻结、主题走新 `THEMES` 表」的路线判断正确。
2. ✅ `test_body_gradient_and_outline_defined` 确实只查结构（数量/单调/覆盖/合法性）——降饱和改 `BODY_GRADIENT_STOPS` 具体色值不破坏断言。
3. ✅ `random_interval(rng=...)` 注入接口、`clamp_to_screens`、托盘 `scale_menu` 单选先例、`_coerce_*` 家族——计划引用的先例全部真实存在。
4. ✅ 阶段划分（P0 主题+节奏 / P1 色彩+微交互 / P2 布局）与依赖关系表述正确；后项只依赖前项常量/接口的论断成立。
5. ✅ 风险表中「QTimer 挂 parent + close 时 stop」「随机走 rng 注入 + 固定种子」「core 不 import time」与项目红线一一对应。

---

## 6. 结论

计划的整体骨架（目标拆解、阶段划分、测试保障机制、提交节奏）**合格且可执行**；但 R1–R5 五个阻断级问题说明此前「已核实」的核实深度不足——尤其是 R1（类型系统冲突）和 R5（基线数字），一个是「照着做必崩」，一个是「数字对不上引发信任危机」。

**建议**：先按第 4 节修正计划文档（约半天的文档工作量，零代码），再按修正后的 A1 开工。修正后本计划可以进入实施。
