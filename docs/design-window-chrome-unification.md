# 窗口外壳统一方案 —— 三个业务窗口对齐 ShadowMenu 观感（E6 → 批次 5）

> 目标：把「生词本 / 学习记录 / 单词详情（+ 确认对话框）」的**窗口外壳**（标题栏 / 阴影 / 外框圆角）
> 换成与右键菜单（`ShadowMenu`）同源的自绘浮层技术，消除「有阴影的浮层 vs 系统标题栏窗口」并置的观感断裂。
>
> 状态：**方案已出，待拍板 D5–D8 后动工**。内容层 token 统一（批次 1+2）已完成，见
> `docs/design-vocab-ui-unification.md`；本文是其外壳维度的增量方案。
>
> 本文取代前文档 D3 的「暂不做」裁决（当时裁决的是"本轮"范围；用户复盘后要求探索统一路径）。

---

## 1. 问题定义：观感差异的三个来源

批次 1+2 已把窗口**内容层**收敛到同一套语义 token（卡片圆角 8 / 描边 `#E3E6EA` / 悬停中性底）。
剩余差异全部来自 QSS 够不着的**窗口外壳**三件事：

| # | 差异 | 菜单（基准 A） | 业务窗口现状 | QSS 可解？ |
| --- | --- | --- | --- | --- |
| 1 | 标题栏 | 无（自绘浮层） | Win10 系统标题栏：方角、系统灰、系统字 | **不可** |
| 2 | 阴影 | 自绘高斯软晕（blur 16 / alpha 50 / Δy 0） | DWM 硬阴影 | **不可**（QSS 无 box-shadow） |
| 3 | 外框圆角 | 自绘 8px 整体圆角 | 直角（Win10 无 `DWMWA_WINDOW_CORNER_PREFERENCE`） | **不可**（QSS 只画窗口内部） |

结论：在「系统窗口 + 内容 QSS」路线内无解，必须换外壳技术。唯一已被项目验证过的路线就是
`ShadowMenu` 的自绘浮层（`FramelessWindowHint` + `WA_TranslucentBackground` + 自绘阴影/面板），
把菜单的整套手法泛化成可复用的窗口基类。

**已验证的技术前提**（均来自现有代码探针结论，非推测）：

- `menu_shadow.py::_blurred_shadow_pixmap(size, radius, blur_px, alpha)` 已存在且被 `ShadowMenu` 使用；
  位图带模糊外溢余量，四角不会「边角打架」。
- 窗口标志**顺序敏感**：先 `FramelessWindowHint` → 再 `WA_TranslucentBackground` → 再
  `NoDropShadowWindowHint`，否则 Windows 上半透明渲染成不透明黑边（`ShadowMenu` / `bubble.py` 双先例注释）。
- 分层窗口自绘 paintEvent 必须先 `CompositionMode_Source` 清屏（`ShadowMenu.paintEvent` 先例）。
- 宠物主窗口已有自绘拖拽（`pet_window.py::mouseMoveEvent`）先例。
- PySide6 ≥6.8：`QWindow.startSystemMove()` / `startSystemResize()` 可用（Qt 6.4+ 引入），
  **无需手写边缘 hit-test / 手动 move**——这是本方案工作量可控的关键前提。

## 2. 技术方案：`ui.shadow_panel.ShadowPanel` 基类

### 2.1 类设计

```
QWidget (顶层)
 ├─ 窗口标志：FramelessWindowHint + WA_TranslucentBackground + NoDropShadowWindowHint
 │            （顺序照探针写法；普通 Qt.Window，**非** Qt.Tool → 保留任务栏图标）
 ├─ 窗口四周预留 band = MENU_SHADOW_BAND_PX (14px) 留白（内容 margin 撑出）
 ├─ paintEvent：清屏 → 画缓存阴影位图 → 画 8px 圆角白面板 + 1px 描边
 │             （与 ShadowMenu 完全同参数：RADIUS.md / MENU_SHADOW_* 四常量）
 ├─ content layout：宿主调用 set_content(widget) 塞入业务内容，margin = band
 ├─ 自绘迷你标题栏 _PanelTitleBar（高 ~36px，见 2.2）
 └─ 边缘缩放命中：mouseMoveEvent/mousePressEvent 判定 band 外圈 → startSystemResize(edge)
```

- 阴影位图按面板尺寸缓存（同 ShadowMenu 策略）；生词本/学习记录可缩放 → resize 时缓存失效
  重建一次，位图生成实测开销可接受（菜单首次弹出同路径），必要时降采样预模糊。
- `show_window_animated()`（motion_ui）对透明度动画的兼容性列入验收（风险 R2），不兼容则该窗口降级直显。

### 2.2 自绘迷你标题栏 `_PanelTitleBar`

- 高 36px：左起窗口标题（`text_secondary` + caption 字号，克制）、右端「最小化 / 关闭」两枚 ghost 族图标按钮（复用 `icon_factory`）。
- 拖拽：`windowHandle().startSystemMove()`——保住系统拖拽语义（多显示器、贴边提示），不手写 move 循环。
- 双击最大化：**不做**（决策 D7，三窗均为固定/自适应尺寸语义，最大化无场景）。
- Esc 关闭 / Alt+F4：Qt 默认行为，不拦截。

### 2.3 前置重构 T2（设计文档既定项，先行落地）

`menu_shadow.py`：`_blurred_shadow_pixmap` → 改名公开 `blurred_shadow_pixmap()`（同步 `__all__`），
`ShadowMenu` 改为复用自身模块函数——**行为零变化**，`test_menu_shadow.py` 全绿即验收。
另将 2.1 的三条窗口标志/清屏「探针结论」注释沉淀为 `shadow_panel.py` 模块 docstring。

## 3. 迁移范围与各窗差异

| 窗口 | 现状 | 迁移要点 |
| --- | --- | --- |
| 生词本 `vocab_window.py` | 系统标题栏、可缩放、可最小化 | **试点**（最复杂：可缩放 + 最小化按钮 + 筛选 Tab 交互全保留） |
| 学习记录 `log_window.py` | 系统标题栏、底栏关闭 | 平移，同生词本（可缩放） |
| 单词详情 `word_detail_window.py` | 系统标题栏、宽度固定、高度自适应 | 平移；高度自适应逻辑（`_fit_height_to_content`）需把 band 计入钳制 |
| 确认对话框 `confirm_dialog.py` | 系统标题栏窗口族（刻意未设 Frameless，D3 旧裁决） | 同批换壳（量小；否则「系统弹窗」成为新残留）——决策 D6 |
| 台词设置 `bubble_text_dialog.py` | 系统标题栏、非模态、两个 `QPlainTextEdit` | 随 5b 换壳；**本家族唯一文本输入面** → IME 列为专项验收（§4.9），真机不达标则单窗回退系统壳（其余窗不受影响） |

## 4. 行为回归清单（真机验收必过）

1. 拖拽移动（标题栏按住），多显示器跨屏拖拽不撕裂、不丢失响应区。
2. 八向边缘缩放（生词本/学习记录）：光标形状随边缘变化；最小尺寸钳制生效。
3. 最小化按钮 → 任务栏；任务栏图标点击恢复；无系统标题栏后 Win+↓ 降级为还原属预期。
4. 关闭按钮 / Alt+F4 / Esc（对话框）三条关闭路径均触发既有 `closeEvent` 淡出逻辑。
5. `show_window_animated` 淡入/淡出在新外壳下正常（风险 R2，不兼容则降级直显并记录）。
6. 150% DPI 缩放：band 留白、圆角、阴影位图无错位发虚。
7. 窗口内右键菜单（批次 4 规划项暂无）、双击词条开详情、按钮 hover/焦点环不变。
8. 离屏 `pytest` 全绿（`test_menu_shadow.py` 有分层窗口 grab 先例，可照抄到 ShadowPanel 测试）。
9. **IME 专项（台词对话框）**：中文输入法在两个 `QPlainTextEdit` 组字，候选框跟住光标、上屏正常；150% DPI 复验。不达标 → 该对话框单窗回退系统壳（`ShadowPanel` 壳层包装，回退改动约一行），批次其余照常交付。

## 5. 待拍板决策点

- **D5｜标题栏形态**：① 36px 极简条（推荐：标题文字保留辨识度，窗口拖拽区直观）；② 无标题栏，仅右上角浮动关闭钮（更「浮层」，但拖拽区不明显）。→ **推荐 ①**
- **D6｜确认对话框同批换壳**：① 同批（推荐，量小、避免残留）；② 延后。→ **推荐 ①**
- **D7｜最大化**：不做（固定尺寸语义）。→ **推荐维持**
- **D8｜开关动画**：`show_window_animated` 兼容则保留淡入淡出，不兼容降级直显。→ 实测定

## 6. 批次拆分与试点顺序

| 子批次 | 内容 | 验收 |
| --- | --- | --- |
| **5a 试点** | T2 抽 `blurred_shadow_pixmap`（零行为变化）→ `ShadowPanel` + `_PanelTitleBar` 落地 → **生词本**换壳 → 真机过 §4 全清单 | 全量 pytest 绿 + 真机截图（生词本 vs 右键菜单同框对比） |
| **5b 平移** | 学习记录、单词详情、（D6 拍板后）确认对话框、台词设置对话框换壳（IME 专项验收，见 §4.9） | 全量 pytest 绿 + 真机 §4 |
| **5c 收尾** | `theme.py` docstring 圆角语义更新（面板档从「窗口内」扩到「窗口面板本体」）；`design-vocab-ui-unification.md` E6/D3 状态回写；静态约束测试联动（`MENU_SHADOW_*` 字面量断言扩展到 ShadowPanel） | 文档与测试同步 |

## 7. 风险表

| # | 风险 | 概率 | 缓解 |
| --- | --- | --- | --- |
| R1 | 分层窗口的任务栏**缩略图预览**空白/黑块（Windows 对 layered window 的已知怪癖） | 中 | 5a 试点首个真机验证项；若复现，接受预览异常（记录已知问题）或评估 `WS_EX_NOREDIRECTIONBITMAP` 替代路线 |
| R2 | `WindowOpacity` 渐变对 translucent 分层窗口无效 → 动画失效 | 低 | 降级直显（菜单先例本就无动画），观感无损 |
| R3 | offscreen 测试环境对 translucent 渲染与真机不一致（§2.1 前置发现同源） | 中 | 测试只断言**几何与调用**（band/margin/缓存失效/信号），像素级断言仅限 ShadowMenu 已验证模式 |
| R4 | 内容 QSS 圆角裁剪真机不生效（D1 遗留） | 低 | 外壳圆角是自绘不依赖 QSS；内容卡片若真机直角，按菜单先例改自绘，随 5c 处理 |
| R5 | 无边框后输入法候选框定位异常（台词对话框，全家族唯一文本输入面） | 低~中 | 随 5b 真机专项验证（§4.9）；组字本身走 input context 与窗口壳无关，最坏是候选框偏移；兜底 = 该对话框单窗回退系统壳，其余窗不受影响 |

## 8. 工作量预估

- 5a：中等——`shadow_panel.py` 新基类（~200 行）+ 抽函数重构 + 生词本迁移 + 边缘行为回归；
- 5b：小——机械平移（每窗改动预计 < 20 行，主要为 `__init__` 壳接入与高度钳制调整）；
- 5c：小——文档 + 测试联动。
