# UI 视觉升级改造计划（三阶段）

> 目标：在不破坏现有 785 项测试基线的前提下，把「小喵酱」桌面宠物的 UI 从「能用」升级到「专业 + 品质感」。
>
> 依据：`docs/` 下既有 PRD/design 文档 + `constants.py` 单一事实源约定 + 测试守护约束。
>
> 版本：v1.0（2026-09-17）

---

## 0. 核心约束（改造的「红线」）

这些约束来自现有测试的**硬断言**，任何一阶段都不能违反：

| 约束来源 | 具体限制 | 对改造的约束 |
|---|---|---|
| `test_color_palette_matches_prd` | `C.COLORS` 字典**全等断言** | **现有色键值不可改**；语义色只能**新增** `SEMANTIC_COLORS` 表 |
| `test_static_constraints.py` | `core/` 零 Qt 依赖；`core` 不 import `ui/app`；无 `print`；零图片素材 | 所有 token 放 `core/constants.py`（纯 Python）；QSS 生成器放 `ui/`；图标必须 QPainter 矢量绘制 |
| `test_base_size_unchanged` | `BASE_W==160, BASE_H==180` | 画布尺寸不动 |
| `test_jp_bubble_visual.py` | 按钮条**无穿透标志**、有投影、气泡固定宽度 | UI 组件改样式时保留行为契约 |
| `test_jp_ui.py` | 窗口标题 / 尺寸 / 信号 / 状态三态全等 | 布局重构不改变公共 API 与文案常量 |

**总原则**：改造只做「**加法**」（新增 token、新增语义层、新增主题/图标模块）与「**翻译**」（组件从硬编码色改为引用 token），不做会改变现有断言结果的「**替换**」。

---

## 1. 三阶段总览

| 阶段 | 主题 | 关键产物 | 风险 | 测试增量 |
|---|---|---|---|---|
| **P0** | 设计 token 地基 | `SEMANTIC_COLORS` / `SPACING` / `FONT_SIZE` / `RADIUS` 常量 | 极低（纯加法） | +语义色/刻度测试 |
| **P1** | 组件统一接入 | `ui/theme.py`（QSS 生成器）+ `ui/icon_factory.py`；三窗接入 | 中（需保持 API 不变） | +QSS 快照/图标测试 |
| **P2** | 动效与图标落地 | 淡入动效 / spinner / 状态标签动画 | 中低（纯 UI 增强） | +动效守卫测试 |

每个阶段**独立可提交、独立可验证**，后一阶段依赖前一阶段的 token 但不依赖其 UI 改动。

---

## 2. P0 —— 设计 token 地基（改色不改结构）

### 改造范围
仅 `src/desktop_pet/core/constants.py` 一个文件（加常量），加配套测试 `tests/test_design_tokens.py`。

### 关键改动点

1. **新增 `SEMANTIC_COLORS` 语义色表**（不触碰 `COLORS` 字典）：

```python
SEMANTIC_COLORS: Final[dict[str, str]] = {
    "primary": "#7A5A42",        # 品牌主色（暖棕，= 气泡正文色）
    "primary_hover": "#8B6B4F",  # 悬停 +8%
    "primary_pressed": "#6B4E3A",# 按下 -8%
    "success": "#7A9E7E",        # 正向操作（「记住了」）
    "success_hover": "#8FB090",
    "success_pressed": "#6B8E6F",
    "info": "#5B8DB8",           # 信息/已掌握状态
    "warning": "#C99A5B",        # 生词状态（从「蓝」改为琥珀，与 info 解耦）
    "muted": "#B7A99A",          # 未处理/辅助
    "destructive": "#C05B5B",    # 危险操作（清空）
    "destructive_hover": "#CE6B6B",
    "surface": "#FFFDF8",        # 卡片/窗口底
    "surface_alt": "#F7EEDF",    # 斑马纹/次级底
    "border": "#EFE3D4",         # 边框
    "text_primary": "#5A4636",   # 正文
    "text_secondary": "#9C8570", # 次级
    "text_faint": "#B7A99A",     # 最淡
}
```

2. **新增间距 / 字号 / 圆角刻度表**（8px 基线）：

```python
SPACING: Final[dict[str, int]] = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}
FONT_SIZE: Final[dict[str, int]] = {
    "display": 24, "title": 16, "body": 12, "caption": 11, "small": 9,
}
RADIUS: Final[dict[str, int]] = {"sm": 6, "md": 8, "lg": 12, "pill": 16}
```

3. **同步更新 `__all__`**（项目红线：删/加常量必须同步 `__all__`）。

### 验收标准
- `SEMANTIC_COLORS` / `SPACING` / `FONT_SIZE` / `RADIUS` 全部可导入、键名与设计文档一致。
- **新增测试** `test_design_tokens.py`：校验语义色与 `COLORS` 的映射关系（如 `success == COLORS["jp_button_primary_bg"]`）、刻度满足 8px 基线、字号单调递减。
- **既有 785 项全绿**（本阶段是纯加法，理论上零破坏；关键验证 `test_color_palette_matches_prd` 仍通过——因为没改 `COLORS`）。

### 如何确保不破坏测试
- 不修改 `COLORS` 任何现有键值；`SEMANTIC_COLORS` 是**新字典**，不影响 `test_color_palette_matches_prd` 的 `==` 断言。
- 新常量只出现在 `core/constants.py`（纯 Python，无 Qt import），不触发 `test_core_has_no_qt_imports`。
- 运行命令复核：
  ```bash
  cd /d C:\Users\王佐成\WorkBuddy\软件开发\desktop-pet && set PYTHONPATH=src && pytest tests/ -q
  ```

---

## 3. P1 —— 组件统一接入（token → QSS）

### 改造范围
新增 `src/desktop_pet/ui/theme.py`、`src/desktop_pet/ui/icon_factory.py`；改造三个窗口接入（`vocab_window.py`、`word_detail_window.py`、`log_window.py`，如存在）。**不改** `pet_renderer.py`、`bubble.py`、`bubble_button_bar.py` 的绘制几何。

### 关键改动点

1. **`ui/theme.py` —— QSS 生成器**（唯一负责把 token 翻译成 QSS 字符串的地方）：

```python
def build_qss() -> str:
    """由 SEMANTIC_COLORS / FONT_SIZE / RADIUS 拼出全局 QSS。"""
    # 按钮四态、表格斑马纹、chip、输入框、滚动条等全部从 token 取值
```

- 按钮变体：`primary / secondary / ghost / destructive`；四态 `:hover/:pressed/:disabled/:focus`。
- 统一圆角 `RADIUS["md"]`、焦点环 `border: 2px solid primary`。

2. **`ui/icon_factory.py` —— 矢量图标工厂**（延续「零外部素材、程序化绘制」）：
- `QPainterPath` 绘制 24×24（20×20 安全区）线性图标：`icon_close` / `icon_retry` / `icon_refresh` / `icon_remove` / `icon_trash` / `icon_chevron_down`。
- 返回 `QIcon`，颜色取 `SEMANTIC_COLORS["text_secondary"]`。

3. **窗口接入**（保持公共 API 与文案不变）：
- 详情窗：`_build_ui` 里的硬编码 `setStyleSheet` 改为引用 token（`f"color: {C.SEMANTIC_COLORS['text_secondary']}"` 或直接 `theme.build_qss()` 全局应用）。
- 生词本 / 学习记录：表格接入斑马纹 + 行 hover；状态标签三态改引语义色（`info/warning/muted`）。
- 等级 chip 从「绿」改为中性描边 chip（引用 `border` + `text_secondary`），消除与「记住了」按钮的绿色撞车。

### 验收标准
- `theme.build_qss()` 返回的 QSS 含按钮四态、表格斑马纹、chip 样式，且所有色值来自 token（无裸十六进制）。
- `icon_factory` 各图标可生成 `QIcon` 且非空、可渲染。
- **新增测试** `test_theme.py` / `test_icon_factory.py`：断言 QSS 字符串含关键选择器、图标 pixmap 非空、绘制不崩溃（offscreen）。
- **既有 785 项全绿**：重点复跑 `test_jp_ui.py`（窗口标题/尺寸/信号不变）、`test_word_detail_window.py`（详情窗三态/守卫不变）。

### 如何确保不破坏测试
- **不改**任何窗口的 `windowTitle`、`resize` 尺寸、信号名、`_table`/`_btn_*` 等被测试引用的属性名。
- **不引入**穿透标志（`test_button_bar_keeps_no_input_transparency` 守护）。
- QSS 只影响视觉，不影响 `test_jp_ui.py` 里 `item().text()`、`rowCount()` 等数据断言。
- 详情窗竞态守卫（`item_id` 双闸）**一行不动**——`test_qa_word_detail_independent.py` 有 60 例专测这个。
- 图标用 QPainter 绘制，**不落盘任何 `.png/.svg`**，不触发 `test_no_image_assets`。

---

## 4. P2 —— 动效与图标落地

### 改造范围
窗口淡入/淡出、详情窗联网 spinner、状态标签切换动画；「减少动效」开关（对应 `prefers-reduced-motion`）。

### 关键改动点

1. **窗口淡入 + 上移 4px**：`QPropertyAnimation` 作用于 `windowOpacity` + `pos`，200ms；关闭淡出 150ms。仅 `transform/opacity`（遵守克制原则）。
2. **联网 spinner**：`ui/spinner.py` 用 `QPainter` 画旋转弧，`QTimer` 驱动，替代静态「联网查询中…」文字（文字保留）。
3. **状态标签切换淡入淡出**：200ms 透明度过渡。
4. **「减少动效」开关**：加入 `AppConfig`（`reduce_motion: bool`，默认 `False`），动效统一走一个 `motion_enabled()` 判断；关闭时直接跳到终态（不播放动画）。

### 验收标准
- 动效在 `offscreen` 平台下**可实例化、可 start、可正常 stop**，不依赖真实窗口显示。
- `reduce_motion=True` 时跳过动画（直接终态）。
- **新增测试** `test_motion_ui.py`：断言动画对象存在、时长符合 200ms、`reduce_motion` 开关生效、spinner 绘制不崩溃。
- **既有 785 项全绿**：重点复跑 `test_ui_smoke.py`（UI 冒烟）、`test_memory_budget.py`（新增动画不引入内存泄漏/QTimer 泄漏）。

### 如何确保不破坏测试
- 动效**默认关闭或仅在有窗口显示时启动**，offscreen 测试环境不依赖实际渲染帧。
- 新增 `QTimer` 必须挂 `parent`（`QTimer(self)`）并在窗口关闭时 `stop()`，避免 `test_memory_budget` 检测到泄漏。
- `AppConfig` 新增字段走「默认值 + 容错读取」，不改变既有 `config.json` 反序列化契约（`test_config.py` 守护）。
- 若 spinner 每帧重绘，需复用 `PetRenderer` 的脏区思路，避免 `test_dirty_rect_no_clip` 类回归。

---

## 5. 全程保障：如何确保各阶段测试全绿

统一「改造 → 验证」闭环，每阶段重复执行：

1. **改前快照**：记录 `pytest -q` 基线（应 785 passed）。
2. **小步提交**：每个改动点（新增常量 / 新增模块 / 接入一个窗口）单独跑一次全量测试，**不攒批**。
3. **静态守护优先**：改完 `constants.py` 先跑 `test_static_constraints.py`（最快暴露架构违规）。
4. **变异验证（项目红线）**：新增测试断言，必须**故意破坏被测行为证明其能 FAIL**，再改回，防止「恒绿的假测试」。
5. **验收七项**（项目既定流程）：`status --porcelain` 空 / HEAD 对齐 / `diff --quiet` / `clean -ndx` 空 / 分支干净 / pytest 全绿 / 无新增图片素材。

### 风险清单与规避

| 风险 | 规避 |
|---|---|
| 改 `COLORS` 触发全等断言 | 语义色走 `SEMANTIC_COLORS` 新表，`COLORS` 冻结 |
| QSS 影响 offscreen 测试 | QSS 只改样式不改结构；测试断言数据/行为而非像素 |
| 新增 QTimer 泄漏 | 全部挂 parent + close 时 stop |
| 图标落盘触发零素材断言 | 全部 QPainter 内存绘制 |
| 动效依赖真实窗口 | 动效可开关，offscreen 下走「直达终态」路径 |

---

## 6. 建议的提交节奏

```
P0:  commit "feat(ui): 新增语义色/间距/字号/圆角 design token"
P1:  commit "feat(ui): 引入 QSS 生成器与矢量图标工厂，三窗接入语义色"
P2:  commit "feat(ui): 窗口淡入动效 + spinner + 减少动效开关"
```

每个 commit 后单独跑全量测试，保持 `develop` 分支始终可回滚。
