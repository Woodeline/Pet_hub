# 小喵酱「视觉疲劳改善」实施计划

> 版本：v1.0 · 日期：2026-09-18
> 前置结论：视觉疲劳的本质是「形象永远一样」。本计划在不推翻「圆球团子猫 + 全息渐变 + 粗黑描边」既有气质的前提下，用「变化」对抗「单调」。
> 约束基线：现有 **785 项 pytest 全绿**为硬前提，任何改动不得破坏；架构红线（`core/` 零 Qt、`core` 不 import `ui/app`、无 `print`、零图片素材、画布 160×180 不可改）全程生效。

---

## 1. 目标与范围

### 1.1 目标
1. 引入**主题皮肤系统**（季节/节日），让配色随周期自动变化，直接打断视觉疲劳。
2. 让**动效节奏「去机械化」**——呼吸微随机、偶发小动作、不对称眨眼，宠物从「循环 GIF」变成「有惊喜的活物」。
3. 通过**色彩微调、微交互反馈、布局节奏**提升长时间驻留的耐看度与品质感。

### 1.2 范围
- **在范围内**：主题渐变表 + 皮肤切换；`motion`/`pet_model` 的节奏与小动作；光晕随皮肤取色；悬停回应与气泡「打字感」；空闲散步。
- **不在范围内**：宠物形象重绘、新增绘制几何、缩放档位增减、日语学习/详情页业务逻辑改动（保持现状）。

### 1.3 技术栈与落点（已核实）
| 模块 | 文件 | 现状 | 改造点 |
|---|---|---|---|
| 配色单一源 | `core/constants.py` | `BODY_GRADIENT_STOPS` + `COLORS` | 新增 `THEMES` 表 + 光晕取色规则 |
| 配置 | `core/config.py` | `AppConfig` dataclass，有 `reduce_motion` 先例 | 新增 `theme` 字段 |
| 托盘菜单 | `ui/tray.py` | `scale_menu` 单选先例 | 新增「主题」子菜单 |
| 动效节奏 | `core/motion.py` | `breath_offset`/`ear_twitch`/`random_interval` | 加随机周期 + 偶发小动作 |
| 姿态通道 | `core/pet_model.py` | `PetPose` 各通道 | 复用 `body_y`/`head_tilt` 等做小动作 |

---

## 2. 实施步骤（按优先级 P0 → P1 → P2）

### 阶段 A（P0）：主题皮肤系统 + 动效节奏去机械化

**任务 A1 — 主题渐变表（`constants.py`）**
- 新增 `THEMES: dict[str, tuple[tuple[float, str], ...]]`，定义 `default / spring / summer / autumn / winter / spring_festival / christmas` 七套渐变停靠点（每套 5 停靠点、位置 0/0.25/0.5/0.75/1.0）。
- 新增 `THEME_NAMES`（显示名映射）、`THEME_SEASON_MAP`（月份 → 默认皮肤）、`DEFAULT_THEME = "default"`。
- 同步更新 `__all__`（项目红线）。
- **验收**：新增 `tests/test_themes.py` 断言每套渐变 ≥4 停靠点、单调递增、覆盖 0→1、色值合法 `#RRGGBB`。

**任务 A2 — 配置字段（`config.py`）**
- `AppConfig` 新增 `theme: str = C.DEFAULT_THEME`，`to_dict`/`from_dict` 对称，用 `_coerce_str` 容错回落（非法值回落 default）。
- **验收**：`tests/test_config.py` 补断言：缺失/非法 `theme` 回落默认、合法值保留。

**任务 A3 — 托盘菜单 + 渲染取色（`tray.py` + `pet_renderer.py`）**
- `tray.py` 新增「主题」子菜单（`QActionGroup` 单选，含「自动」档），发出 `theme_selected: Signal(str)`。
- `pet_renderer.py` 的 `_body_gradient`/`_sample_gradient` 改为按 `pose.theme`（或传入主题名）从 `THEMES` 取渐变；`_draw_glow` 光晕色随当前皮肤主色取色。
- **验收**：新增 `test_theme_render.py` 断言不同主题渲染出不同渐变、不崩溃（offscreen）；托盘菜单单选行为正确。

**任务 A4 — 动效节奏（`motion.py` + `pet_model.py`）**
- 呼吸：`breath_offset` 增加「每次循环后周期重抽 ±10%」的抖动参数。
- 偶发小动作：新增 `idle_surprise(now, rng)` 决策函数，按 `IDLE_SURPRISE_MIN_S/MAX_S` 随机间隔触发「伸懒腰/甩尾/抖耳/看角落」四选一（复用现有姿态通道）。
- 不对称眨眼：`blink_curve` 支持左右眼相位偏移参数。
- **验收**：新增 `test_motion_rhythm.py` 用固定 `rng` 种子断言输出可复现、周期抖动范围正确、偶发动作触发概率符合预期。

**阶段 A 验收（里程碑 M1）**：七套皮肤可切换、auto 档按月份生效；动效节奏有随机性且 `reduce_motion` 下关闭；**785 项全绿 + 新增测试全绿**。

---

### 阶段 B（P1）：色彩微调 + 微交互反馈

**任务 B1 — 色彩微调（`constants.py`）**
- 光晕 `glow_yellow`/`glow_blue` 改为「随皮肤主色派生」的辅助函数或皮肤内嵌色。
- 彩虹渐变饱和度整体下调 5–10%（改 `BODY_GRADIENT_STOPS` 具体色值——已核实 `test_body_gradient_and_outline_defined` 只查数量/单调/范围/合法性，**改色值不破坏断言**）。
- 键盘/鼠标描边改为略浅灰，与主体 `ink` 拉开层级。
- **验收**：`test_static_constraints.py` 全绿；新增 `test_palette_level.py` 断言道具描边 ≠ 主体描边。

**任务 B2 — 微交互（`pet_window.py` + `bubble.py`）**
- 悬停回应：悬停超阈值后猫看向光标 + 眨眼 + 尾巴轻摆。
- 点击弹跳加「压扁→弹起→过冲回落」（复用 `body_squash` + `ease_out_bounce`）。
- 气泡「打字感」：学习泡泡单词逐字浮现（`reduce_motion` 下直接整块）。
- **验收**：新增 `test_micro_interaction.py`；`test_jp_bubble_visual.py` 仍绿（气泡宽度/按钮 bar 契约不变）。

**阶段 B 验收（里程碑 M2）**：配色更耐看、层级分明；交互有即时反馈；**全量测试绿**。

---

### 阶段 C（P2）：布局节奏优化

**任务 C1 — 空闲散步（`pet_window.py`）**
- 长空闲时窗口在右下角 ±20px 随机游走（缓慢平移，几秒挪一点）。
- 偶发换姿态（正坐 ↔ 侧卧/趴着，复用姿态通道）。
- **注意**：涉及窗口定位与脏区，需复跑 `test_dirty_rect_no_clip`、`test_ui_smoke.py`，确保不引入漂移/裁切。
- **验收**：新增 `test_idle_wander.py` 断言位移有界、不越屏；`test_memory_budget.py` 仍绿（新 QTimer 挂 parent + close 时 stop）。

**阶段 C 验收（里程碑 M3）**：宠物不再「钉死」，画面有呼吸感；**全量测试绿**。

---

## 3. 负责人与预计耗时

> 单人项目（木头绳），以下「负责人」按模块分工标注，实际由主工程 + AI 协作完成。

| 任务 | 负责人 | 预计耗时 | 说明 |
|---|---|---|---|
| A1 主题渐变表 | 主工程 | 0.5 天 | 纯常量，7 套渐变选色 |
| A2 配置字段 | 主工程 | 0.25 天 | 照 `reduce_motion` 复制 |
| A3 托盘+取色 | 主工程 | 1 天 | 托盘菜单 + 渲染取色联调 |
| A4 动效节奏 | 主工程 | 1 天 | 随机性 + 偶发动作，需 mock 测试 |
| B1 色彩微调 | 主工程 | 0.5 天 | 降饱和 + 描边分层 |
| B2 微交互 | 主工程 | 1.5 天 | 悬停/弹跳/打字感 |
| C1 空闲散步 | 主工程 | 1 天 | 窗口定位风险最高，谨慎 |
| **合计** | — | **约 5.75 人天** | 分 3 阶段独立提交 |

---

## 4. 所需资源与依赖

- **无新外部依赖**：全部复用 PySide6 6.9.3 + 现有标准库（`random`/`math`），不新增包、不引入图片素材（零素材红线）。
- **依赖关系**：B1 光晕随皮肤依赖 A1 的 `THEMES` 表；B2/C1 依赖 A4 的动效通道。阶段间**后项只依赖前项的常量/接口，不依赖其 UI 表现**，可部分并行。
- **环境**：隔离 venv `C:\Users\王佐成\.workbuddy\binaries\python\envs\default`；测试 `QT_QPA_PLATFORM=offscreen`。

---

## 5. 关键里程碑与验收标准

| 里程碑 | 阶段 | 验收标准 |
|---|---|---|
| **M1** | A（P0） | 七套皮肤可切换、auto 按月份生效；动效节奏有随机性；785 + 新增测试全绿 |
| **M2** | B（P1） | 配色耐看、层级分明；交互有即时反馈；全量测试绿 |
| **M3** | C（P2） | 空闲散步/换姿态不漂移不裁切；全量测试绿 |

**每个阶段通用验收**（项目既定七项）：
1. `git status --porcelain` 空；2. HEAD 对齐；3. `diff --quiet` 通过；4. `clean -ndx` 仅剩 `__pycache__` 等构建缓存；5. 分支干净；6. pytest 全绿；7. 无新增图片素材。

**测试保障机制**（每阶段重复）：
- 改前快照 `pytest -q`（785 passed）。
- 小步提交，每个改动点单独跑全量，不攒批。
- 改完 `constants.py` 先跑 `test_static_constraints.py`（最快暴露架构违规）。
- **变异验证**（红线）：新增断言必须先「故意破坏」证明能 FAIL，防恒绿假测试。

---

## 6. 潜在风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 改 `COLORS` 触发 `test_color_palette_matches_prd` 全等断言 | 测试挂 | 主题走**新 `THEMES` 表**，`COLORS` 现有键值**冻结不动**；降饱和只改 `BODY_GRADIENT_STOPS`（该断言只查结构不查具体色值） |
| 降饱和主观判断「改得不好看」 | 效果不佳 | 饱和度下调做成**可调参数**，一次只调一档，配截图对比 |
| 偶发小动作/散步引入随机性 → 测试不稳定 | 假失败 | 所有随机走 `random.Random` 注入（`motion.random_interval` 已支持 `rng`），测试用固定种子 |
| 新增 QTimer 泄漏 | `test_memory_budget` 挂 | QTimer 一律挂 parent，窗口 close 时 `stop()` |
| 空闲散步动窗口定位 | 漂移/裁切/脏区错误 | 位移严格有界（±20px 内）、复用 `clamp_to_screens`；复跑 `test_dirty_rect_no_clip` |
| `reduce_motion` 下随机性仍运行 | 无障碍违背 | 所有随机/散步/打字感在 `reduce_motion` 下**直达终态或跳过** |
| core 层引入 `time` | 架构红线 | 时间参数继续由调用方注入，`motion` 只用注入的 `now`，不 import `time` |

---

## 7. 建议提交节奏

```
A1+A2: commit "feat(theme): 新增主题渐变表与 AppConfig.theme 字段"
A3:    commit "feat(theme): 托盘主题菜单 + 渲染按皮肤取色"
A4:    commit "feat(motion): 呼吸随机化 + 偶发小动作 + 不对称眨眼"
B1:    commit "feat(palette): 降饱和 + 道具描边分层"
B2:    commit "feat(interact): 悬停回应 + 弹跳过冲 + 气泡打字感"
C1:    commit "feat(idle): 长空闲散步与换姿态"
```

每个 commit 后单独跑全量测试，`develop` 分支始终可回滚；阶段完成打内部标签便于回溯。
