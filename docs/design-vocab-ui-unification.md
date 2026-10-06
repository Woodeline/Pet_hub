# 生词本及学习记录相关界面 · 视觉与交互统一方案

> 目标：以**右键菜单（ShadowMenu + `build_menu_qss`）**与**气泡按钮条（BubbleButtonBar）**为参考基准，
> 把「生词本 / 学习记录 / 单词详情 / 台词设置对话框」这组学习功能入口，在
> **配色 / 圆角 / 阴影 / 悬停** 四个维度收敛到同一套语义 token 与状态规则上。
>
> 状态：**批次 1 + 批次 2 已落地（未提交）**；批次 3 / 批次 4 未启动。
> 落地实录与偏差说明见 **§9**；已拍板决策见 §8（D1 部分待真机复核、D2 取 ①、D3/D4 延后）。
>
> 相关既有文档：`docs/design-ui-upgrade-plan.md`（P0 token / P1 组件 / P2 动效三阶段）、
> `docs/implementation-log-ui-theme.md`；本文是其**增量收敛方案**，不重复其内容。
> 窗口外壳（标题栏 / 阴影 / 外框圆角，E6）维度的统一另见 **`docs/design-window-chrome-unification.md`**（批次 5，方案已出待拍板 D5–D8）。

---

## 1. 基准定义（参考系）

### 1.1 基准 A —— 右键菜单

| 维度 | 现状取值 | 实现位置 |
| --- | --- | --- |
| 面板底 | `SEMANTIC_COLORS["surface"]` `#FFFFFF` | `menu_shadow.py::ShadowMenu.paintEvent` |
| 面板描边 | `SEMANTIC_COLORS["border"]` `#E3E6EA`，1px | 同上 |
| 面板圆角 | `RADIUS["md"]` = **8px** | 同上 |
| 条目圆角 | `RADIUS["sm"]` = **6px** | `theme.build_menu_qss()` |
| 条目内边距 | `8px 24px 8px 12px`（`SPACING.sm/xl/sm/md`） | 同上 |
| 条目悬停 | `surface_alt` `#F5F6F8`（**中性底，不用点缀色**） | `QMenu::item:selected` |
| 禁用条目 | 文字 `text_faint` `#98A2AD` | `QMenu::item:disabled` |
| 分隔线 | 1px `border`，左右缩进 12px、上下 4px | `QMenu::separator` |
| 阴影 | **自绘**：留白 14px / 高斯模糊 16 / alpha 50 / 垂直偏移 0，并显式关闭 DWM 原生阴影 | `MENU_SHADOW_*` + `menu_shadow.py` |

覆盖范围：托盘主菜单、全部子菜单（日语学习／难度／时长／每日数量／大小／主题／皮肤）、宠物窗口右键（复用同一 `tray.menu`）。

### 1.2 基准 B —— 气泡按钮条

| 维度 | 现状取值 | 实现位置 |
| --- | --- | --- |
| 主按钮「记住了」底 | 纵向三分停渐变 `jp_button_primary_hover→bg→pressed`（`#53C463→#3FB950→#349A44`），文字 `#FFFFFF` | `bubble_button_bar.py::_build_qss` |
| 次按钮「新单词」 | 透明底 + 1px `jp_button_secondary_border` `#C9CDD3`，文字 `#1F2328` | 同上 |
| 圆角 | `JP_BUTTON_RADIUS` = **16px**（胶囊） | 同上 |
| 内边距 / 字号 | `14px / 8px`，字号 12 | `JP_BUTTON_PAD_X/PAD_Y/FONT_SIZE` |
| 悬停 | 主：双停渐变（hover→bg）；次：填充 `jp_button_secondary_hover` `#EEF0F3` | 同上 |
| 按下 | 主：双停渐变（bg→pressed）；次：填充 = 描边色 `#C9CDD3` | 同上 |
| 浮层容器 | 底 `#FFFFFF` + 1px `#C9CDD3` 描边 + 16px 圆角（`QPainter.drawRoundedRect`） | `BubbleButtonBar.paintEvent` |
| 阴影 | `QGraphicsDropShadowEffect`：blur 10 / offset (0, 2) / alpha 70，**仅挂在主按钮上** | `BubbleButtonBar.__init__` |

### 1.3 两个基准之间的既有分歧（统一时必须先裁决）

| 维度 | 右键菜单 | 气泡按钮条 | 说明 |
| --- | --- | --- | --- |
| 圆角语义 | 面板 8 / 条目 6 | 容器与按钮 16 | 「面板档」vs「胶囊档」 |
| 阴影层次 | 整面板一层（blur16/α50/Δy0） | **只主按钮一层**（blur10/α70/Δy2） | 同一浮层内两个按钮厚薄不一 |
| 悬停观感 | 中性底 `surface_alt` | 渐变位移 / 描边填充 | 一个是「弱色块」，一个是「材质变化」 |
| 主操作色 | 无（菜单条目不用彩色） | 绿色 `success` 族 | 菜单里没有「主操作」概念 |

**结论（本文采用）**：把「圆角档位 / 阴影档位 / 悬停底色」三件事**按控件类别**统一（浮层 vs 窗口内控件 vs 胶囊），
而不是强行让气泡按钮长得像菜单条目 —— 那会破坏「绿色正向操作」这一已被 `test_design_tokens` 钉死的语义。

---

## 2. 现状勘察：需调整的入口与范围

优先级：**P0** = 与基准明显冲突（一眼可见的不一致）；**P1** = 同族控件内部不一致；**P2** = 增量增强（新增入口）。

| # | 入口（文件） | 现状问题 | 优先级 |
| --- | --- | --- | --- |
| E1 | 生词本窗口 `ui/vocab_window.py` | ① 卡片圆角 `RADIUS["lg"]=12`，与菜单面板 8 不同档；② Tab 圆角 0（设计如此）与按钮 8 并排；③ 清空确认走 `QMessageBox.question`，**完全未接主题**（系统方角 + 系统色 + DWM 方阴影）；④ 无右键菜单 | P0（③）、P1（①②） |
| E2 | 学习记录窗口 `ui/log_window.py` | ① 卡片圆角 12（同 E1）；② 底部**没有「关闭」按钮**，与生词本底栏结构不一致；③ 状态标签用 `muted` `#98A2AD`（= `text_faint`）作「未处理」文字色，在 `surface` 上对比度偏低；④ 无右键菜单 | P0（②）、P1（①③） |
| E3 | 单词详情窗口 `ui/word_detail_window.py` | ① 卡片圆角 12；② 「记住了」= `success` 变体（纯色 8px 圆角、无阴影），与气泡同文案按钮（渐变 16px + 阴影）**形态不同**；③ 等级 chip 圆角 6 与卡片 12 混排 | P1 |
| E4 | 台词设置对话框 `ui/bubble_text_dialog.py` | ① 3 个 `QGroupBox` **零 QSS** → 系统默认方形边框 + 标题压线；② 2 个 `QPlainTextEdit` **零 QSS** → 直角系统边框，与 `QComboBox/QLineEdit`（圆角 8 + token 色）不同族；③ 「应用 / 取消」未设 `variant` → 落到基础 `QPushButton` 兜底，主操作无强调 | P0 |
| E5 | 浮层一致性 | 气泡按钮条的阴影只挂主按钮 → 同一浮层内左右厚薄不均；菜单是整面板阴影 | P1 |
| E6 | 窗口 chrome | 三个业务窗口都是系统标题栏窗口，**无面板阴影**；菜单/气泡浮层有自绘阴影 → 「有阴影的浮层」与「无阴影的窗口」并置 | P2（决策点 D3）→ **已立项批次 5**，方案见 `docs/design-window-chrome-unification.md` |
| E7 | 右键菜单覆盖 | 生词本 / 学习记录窗口内**没有右键菜单**（列表项只能左键双击开详情） | P2 |

> 证据：截图见 `_ui-review-phase-d/unify-01-vocab.png` … `unify-06-dialog.png`（现状基线）；
> 复现脚本 `_ui-review-phase-d/_capture_unify_baseline.py`。
> 注：离屏环境无中文字体，截图中文字显示为方框，**仅作结构与几何/配色证据**使用。

### 2.1 ⚠️ 前置发现（必须先复核，影响 P0 的「圆角」实现方式）

离屏实测（offscreen QPA，Qt 6.9.3）下，**`QPushButton` 的 QSS `border-radius` 未裁剪背景填充**：

- 生词本「清空」按钮（`destructive`，`border-radius: 8px`，启用态）角像素 `(1,1)` = `#D64545`（填充色），
  而非窗口底色 → 圆角未生效；
- 气泡按钮条主按钮（`border-radius: 16px`，`border: none`）四角同样为渐变填充色 → 圆角未生效；
- 同一环境下由 `QPainter.drawRoundedRect` **自绘**的菜单面板圆角正常（`unify-05-menu.png` 可见）。

两种解释：**(a)** offscreen 平台未实现 QSS 圆角裁剪（真机正常，仅截图假象）；
**(b)** 本机/本版本下 QSS 圆角对按钮确实不生效（真机同样是直角）。

复核方式（一条命令，肉眼可判）：`_ui-review-phase-d/_probe_window_qss2.py`（取启用态按钮四角像素）。
**在真机确认之前，不把「圆角」写成纯 QSS 改动**，见 §6 的 T1 双路线与 §8 决策点 D1。

---

## 3. 统一后的样式标准（四维）

单一事实源：`core/constants.py` 的 `SEMANTIC_COLORS / SPACING / FONT_SIZE / RADIUS`。
**红线**（`tests/test_design_tokens.py` 会红）：四张表的**键集合**均被全等断言，
`COLORS` 键集被 `test_color_palette_matches_prd` 全等断言 → **不得新增键**；
新增色值/尺寸一律走**独立标量常量**（照 `PROP_OUTLINE` 先例）并同步 `__all__`。

### 3.1 配色

| 语义 | token | 取值 | 用在哪 |
| --- | --- | --- | --- |
| 面板底 | `surface` | `#FFFFFF` | 菜单面板、卡片、对话框、输入框 |
| 悬停底（统一基准） | `surface_alt` | `#F5F6F8` | **菜单条目 hover、卡片 hover、次按钮 hover、ghost hover** |
| 按下底 | `border` | `#E3E6EA` | 次按钮 / ghost 按下 |
| 描边 | `border` | `#E3E6EA` | 面板、卡片、输入框（1px） |
| 正文 / 次级 / 弱化 | `text_primary` / `text_secondary` / `text_faint` | `#1F2328` / `#5A626C` / `#98A2AD` | 文字三级 |
| 正向主操作 | `success` (+`_hover`/`_pressed`) | `#3FB950` / `#53C463` / `#349A44` | 「记住了」（气泡与详情**同族同色**） |
| 危险操作 | `destructive` (+`_hover`) | `#D64545` / `#E05656` | 清空生词本 |
| 状态标签 | `info` / `warning` / `text_secondary` | `#4C8DDA` / `#C28A2B` / `#5A626C` | 记录窗口三态（已掌握 / 生词 / 未处理） |
| 点缀色 | 主题 `accent` | 运行时 | Tab 选中文字与下划线、卡片选中描边 |

**改动点（已落地）**：E2 的「未处理」文字色由 `muted`（`#98A2AD`，与 `text_faint` 同值，偏淡）
**提升为 `text_secondary`**（`#5A626C`，在 `surface` 上对比度 6.18 vs 原 2.59，达 WCAG AA）。

> ⚠️ **落地后才发现的二次缺陷（已被 QA 证伪并修复）**：只改 `_STATUS_COLOR_KEYS` 的映射是**死改动** ——
> `log_window.py::_LogCard.__init__` 原第 88 行有 `if entry.status != C.DAILY_LOG_STATUS_UNPROCESSED:` 门控，
> 未处理态**根本不创建状态标签**，映射永不参与渲染。
> 最终裁决：**走「三态齐平」**（删除门控，三种状态一律渲染标签），而非删掉映射降低口径。
> 守护用例 `tests/test_ui_style_unification.py::test_unprocessed_card_renders_contrast_status_label`。

### 3.2 圆角（按控件类别定档，不新增 `RADIUS` 键）

| 档位 | 取值 | 适用 |
| --- | --- | --- |
| 面板档 | `RADIUS["md"]` = **8px** | 菜单面板、**卡片（由 12 收敛到 8）**、对话框面板、输入框、按钮 |
| 小元素档 | `RADIUS["sm"]` = **6px** | 菜单条目、chip、滚动条手柄 |
| 胶囊档 | `JP_BUTTON_RADIUS` = **16px** | **仅气泡按钮条**（浮层胶囊语义，唯一例外） |
| 笔直档 | `0` | 文字 Tab（下划线选中态，刻意不圆） |

即：**窗口内一切面板/控件 = 8px，小元素 = 6px，气泡浮层 = 16px，Tab = 0**。四档语义写进 `theme.py` 模块 docstring，
并加静态测试（§7）防止再次漂移。

### 3.3 阴影（两档，新增独立标量）

| 档位 | 参数 | 适用 | 落地方式 |
| --- | --- | --- | --- |
| **L1 浮层** | blur 16 / alpha 50 / Δy 0 / 留白 14 | 右键菜单、气泡按钮条 | 复用现有 `MENU_SHADOW_*`；气泡按钮条改为**整条一层**（抽出 `menu_shadow` 的位图生成函数供二者共用） |
| **L2 面板**（新增） | blur 24 / alpha 40 / Δy 4 | 台词设置对话框等模态面板 | 新增 `SHADOW_PANEL_BLUR_PX/ALPHA/OFFSET_Y`（独立标量 + `__all__`） |

**统一原则**：一个浮层**只允许一层阴影**，且挂在**最外层容器**上 —— 修掉 E5（现在主按钮独占阴影，次按钮没有）。

### 3.4 悬停

- 统一规则：**面板类元素 hover 一律用 `surface_alt`**（菜单条目、卡片、次/ghost 按钮一致）；
- 主操作色按钮（success / primary / destructive）hover 用自身 `_hover` 色，**不叠加** `surface_alt`；
- 文字 Tab hover 只改文字色（`text_primary`），不改底；
- 卡片 hover = `surface_alt`；卡片**选中** = 1px `primary`（或 accent）描边（沿用 `theme.set_card_selected`）；
- 不做 QSS 过渡动画（Qt QSS 无 transition）；如需淡入，走 `motion_ui` + `设置 reduce_motion` 开关，默认关闭。

---

## 4. 交互状态表现（状态矩阵）

| 控件 | 常态 | 悬停 | 按下 | 选中 / 激活 | 禁用 | 焦点 |
| --- | --- | --- | --- | --- | --- | --- |
| 菜单条目 | 透明 | `surface_alt` | `surface_alt` | — | 文字 `text_faint` | — |
| 菜单面板 | `surface` + 1px `border` | — | — | — | — | — |
| 主操作按钮（记住了） | 渐变 `hover→bg→pressed`（气泡）/ `success` 纯色（窗口内） | 渐变位移 / `success_hover` | 渐变位移 / `success_pressed` | — | `surface_alt` 底 + `text_faint` 字 | 2px `primary` 环 |
| 次按钮（删除选中 / 应用） | `surface` + 1px `border` | `surface_alt` | `border` | — | 同上 | 同上 |
| ghost（关闭 / 取消） | 透明 | `surface_alt` | `border` | — | 同上 | 同上 |
| destructive（清空） | `destructive` | `destructive_hover` | `destructive` | — | 同上 | 同上 |
| 文字 Tab | 次级字 | 文字 `text_primary` | 同悬停 | accent 字 + 2px accent 下划线 | — | 刻意 NoFocus |
| 生词卡片 | `surface` + 1px `border` | `surface_alt` | — | 1px `primary` 描边 + 单击选中→启用「删除选中」 | — | — |
| 记录卡片 | 同上 | 同上 | — | — | — | — |
| 气泡主/次按钮 | 见 §1.2 | 见 §1.2 | 见 §1.2 | — | — | NoFocus（当前） |
| 输入类（下拉 / 输入框 / 多行） | `surface` + 1px `border` | 描边 `text_secondary` | — | — | 底 `surface_alt` | 2px `primary` 环 |

**语义约定（写进实现注释）**：所有「破坏性」动作都必须用 `destructive`，不允许出现
「同一个窗口里两个删除动作色阶不同」（当前 E1 的「删除选中」是次级灰、而「清空」是红：**保留**，
因为前者可撤销、后者不可逆 —— 本方案将这一点显式写进规范，避免后续被当成不一致改掉）。

---

## 5. 落地清单（文件级，按批次）

### 批次 1 —— 基础层（`theme.py` / `menu_shadow.py`），先立规矩 · ✅ T1 已落地，T2/T3 主动不做

| ID | 文件 | 改动 | 验收 |
| --- | --- | --- | --- |
| T1 | `ui/theme.py` | ① 补 `QGroupBox`（圆角 8 + `surface` 底 + `border` 描边 + 标题 `text_secondary` 小字）、`QPlainTextEdit/QTextEdit`（对齐 `QLineEdit` 四态）、`QMessageBox/QDialog`（`surface` 底 + 圆角 8 + `text_primary`）三块 QSS；② 卡片 role 圆角 `lg`→`md`；③ 模块 docstring 写明 §3.2 四档圆角语义 | `build_qss()` 含新块；新增静态断言（§7） |
| T2 | `ui/menu_shadow.py` | 抽出 `blurred_shadow_pixmap()` 为公共函数 + `apply_overlay_shadow(widget)` 供浮层共用；菜单行为不变 | **本批次不做** —— 唯一消费方 T7（气泡按钮条整层阴影）未启动，抽出即「有实现无使用」死代码 |
| T3 | `core/constants.py` | 新增独立标量 `SHADOW_PANEL_BLUR_PX/ALPHA/OFFSET_Y` 与 `SHADOW_LAYER_BAND_PX`，同步 `__all__`（**不加 `COLORS`/`SEMANTIC_COLORS` 键**） | **本批次不做** —— L2 面板阴影没有落地消费方（T6③ 一并取消），等批次 3 一起做 |

### 批次 2 —— 学习功能入口对齐（E1 / E2 / E4）· ✅ 已落地

| ID | 文件 | 改动 |
| --- | --- | --- |
| T4 ✅ | `ui/vocab_window.py` + **新增 `ui/confirm_dialog.py`** | ② 清空确认由 `QMessageBox.question` 换为**主题化确认对话框**：新增 `ConfirmDialog(QDialog)`，`theme.apply_theme` 接管配色/QSS，底栏 `[取消(ghost) → reject][清空(destructive) → accept]`，`@staticmethod ask(parent, title, text, confirm_text) -> bool`；`vocab_window` 移除 `QMessageBox` import。**偏差**：未接 L2 面板阴影（`QDialog` 走系统 chrome，见 D3 延后），故 T3 也无消费方 |
| T5 ✅ | `ui/log_window.py` | ① 卡片圆角随 T1 收敛；② 底栏右侧补 `ghost`「关闭」按钮（`C.JP_LOG_BTN_CLOSE` + `make_icon("close", text_primary)`）；③ 「未处理」标签文字色 `muted`→`text_secondary`，并删除原第 88 行状态门控实现**三态齐平**（见 §3.1 二次缺陷说明） |
| T6 ✅ | `ui/bubble_text_dialog.py` | ① GroupBox/PlainTextEdit 由 T1 的 QSS 接管（本文件不写局部样式）；② 「应用」→ `theme.set_variant(btn, "primary")`、「取消」→ `"ghost"`；③ **不做**（同 T4 偏差理由） |

### 批次 3 —— 浮层与详情对齐（E3 / E5）

| ID | 文件 | 改动 |
| --- | --- | --- |
| T7 | `ui/bubble_button_bar.py` | 阴影由「只挂主按钮」改为**整条容器一层**（与菜单同族），并按 §8-D1 的路线修圆角 |
| T8 | `ui/word_detail_window.py` | ① 卡片圆角随 T1 收敛；② 「记住了」按钮：**保持 `success` 语义色**，按 §8-D2 决定是否升级为气泡同款胶囊+渐变；③ 等级 chip 与卡片圆角档位说明注释 |

### 批次 4 —— 增量增强（E7，可选）

| ID | 文件 | 改动 |
| --- | --- | --- |
| T9 | `ui/vocab_window.py` / `ui/log_window.py` | 卡片右键菜单（`ShadowMenu`）：打开详情 / 移出生词本（生词本）/ 标记已掌握 / 复制单词。菜单项复用 `build_menu_qss`，无新样式 |

---

## 6. 验收与回归

1. **自动化**：全量 `pytest`（改造前 1374 项 → 改造后 **1397 项**）必须全绿；新增 `tests/test_ui_style_unification.py`（23 项）：
   - `build_qss()` 含 `QGroupBox / QPlainTextEdit / QDialog` 块且各含四态；
   - 卡片 role 的 `border-radius` 等于 `RADIUS["md"]`（防回退到 `lg`）；
   - 四档圆角语义常量存在且互不相等（`md=8 / sm=6 / JP_BUTTON_RADIUS=16 / tab=0`）；
   - `SHADOW_PANEL_*` 三个独立标量存在且为正（**本批次不适用**，随 T3 延后到批次 3）；
   - **一个浮层只有一层阴影**：`BubbleButtonBar` 中不再对子按钮调用 `setGraphicsEffect`（源码级断言完整调用行，不用 `count`）——**本批次不适用**，随 T7 延后。
   - **本轮实际新增的 23 项断言**：8 个新选择器齐备、`QPlainTextEdit/QTextEdit` 四态按块断言、卡片圆角 = `RADIUS["md"]` 且 ≠ `RADIUS["lg"]`、新增块无裸 hex、四档圆角互不相等、
     `ConfirmDialog` 两条分支真实按钮接线、`VocabWindow` 源码级 `"QMessageBox" not in 源文件` + 行为断言、`LogWindow` 关闭按钮点击隐藏、`BubbleTextDialog` variant 断言、
     以及缺陷探针 `test_unprocessed_card_renders_contrast_status_label`。
2. **视觉**：用 `_ui-review-phase-d/_capture_unify_baseline.py` 同款脚本产出**改造后**对照图（`unify-after-*.png`），
   `before/after` 成对评审；像素抽检（按钮中心色 = token 值）沿用已固化的取色测试。
3. **交互**：手工清单 —— 菜单条目 hover/禁用、按钮四态、Tab 切换、卡片选中与双击、清空确认弹窗（取消不删）、台词对话框应用/取消。
4. **真机复核（P0 前置）**：圆角裁剪（§2.1）必须在真机确认，必要时改走自绘路线。

---

## 7. 风险与红线

| 风险 | 说明与规避 |
| --- | --- |
| token 全等断言 | `SEMANTIC_COLORS / SPACING / FONT_SIZE / RADIUS` 键集、`COLORS` 键集均被全等断言 → **只加独立标量，不加键** |
| 卡片圆角 12→8 | 可能被既有 UI 测试断言 → 同步更新；`design-ui-upgrade-plan.md` 里 12 的表述需一并改口径 |
| `ui/**.py` 禁裸 hex | 所有新样式必须走 `C.COLORS/C.SEMANTIC_COLORS` 键（AST 扫描守护，`test_static_constraints`） |
| 自绘阴影成本 | L2 面板阴影若用 `QGraphicsDropShadowEffect`，会与子控件透明度/半透明耦合（参考气泡按钮条的圆角疑云）→ 优先复用 `menu_shadow` 的**离屏位图 + 自绘**路线 |
| 主题化确认弹窗 | 新增对话框文件是**新入口**，需补 `reduce_motion` 注入与关闭动效，保持与其它窗口一致 |

---

## 8. 待决策点（动工前拍板）

- **D1｜圆角实现路线**：① 先真机复核；若 QSS 圆角可用 → 仅对齐档位（成本最低）；
  ② 若真机同样是直角 → 统一改**自绘圆角底**（`paintEvent` + `QPainterPath`，照 `ShadowMenu` 先例），成本较高但一次到位。**推荐 ①→②**。
  → **裁决：①（先按 QSS 档位对齐落地，真机复核后再定是否走 ②）。** 未复核前不得宣称圆角已真正生效。
- **D2｜详情「记住了」形态**：① 保持 `success` 纯色 8px（窗口内控件族，与「重试/关闭」齐平）；
  ② 升级为气泡同款「渐变 + 16px 胶囊 + 阴影」（与气泡按钮**完全一致**，但在窗口内容易显得突兀）。**推荐 ①**，理由：气泡按钮是**浮层**语义，窗口内按钮属**面板**族。
  → **裁决：①（用户已拍板：保持 8px 纯色）。** 批次 3 的 T8② 相应取消形态升级，仅保留「同色同文案」保证。
  **【2026-10-01 更新】** 用户改拍板：颜色维度升级为**气泡同款三态渐变**（`success` 变体 QSS 改 `qlineargradient`，
  端点 token 与气泡 `jp_button_primary_*` 同值；圆角仍保持面板档 8px，形态不升级）。已落地，见 §9.3。
- **D3｜窗口 chrome**：是否给三个业务窗口加自绘面板阴影（L2）以与浮层呼应？**推荐暂不做**（系统窗口已有 DWM 阴影，叠加易过重）。
  → **裁决：暂不做**（本轮实际也未做，`ConfirmDialog` 因此不设 `FramelessWindowHint`）。
  **【2026-10-01 更新】** 用户复盘后要求探索三窗口与菜单的观感统一，已立项批次 5（`ShadowPanel` 自绘外壳），
  方案与待拍板决策点 D5–D8 见 `docs/design-window-chrome-unification.md`；`ConfirmDialog` 是否同批换壳 → D6。
- **D4｜增量右键菜单（T9）**：是否本批次一并做？**推荐延后**，先完成四维统一。
  → **裁决：延后**（批次 4 未启动，待用户确认）。

---

## 9. 落地实录（批次 1 + 批次 2，2026-09-30）

### 9.1 实际改动文件

| 文件 | 性质 | 内容 |
| --- | --- | --- |
| `src/desktop_pet/ui/theme.py` | 改 | `BUTTON_VARIANTS` 增 `"success"`（色值取 `SEMANTIC_COLORS["success"]` 族，与气泡按钮绿同源）；卡片 role 圆角 `lg(12)`→`md(8)`；`build_qss()` 新增 `QGroupBox`+`::title`、`QPlainTextEdit/QTextEdit`（常态/hover/focus 2px primary 环/disabled）、`QDialog`、`QMessageBox` 保底四块；docstring 补 §3.2 四档圆角语义 |
| `src/desktop_pet/ui/confirm_dialog.py` | **新增** | 见 T4 |
| `src/desktop_pet/ui/vocab_window.py` | 改 | 清空确认接 `ConfirmDialog.ask(...)`，移除 `QMessageBox` import |
| `src/desktop_pet/ui/log_window.py` | 改 | 底栏补 ghost「关闭」；未处理态色改 `text_secondary`；删除状态门控实现三态齐平 |
| `src/desktop_pet/ui/bubble_text_dialog.py` | 改 | 「应用」`primary`、「取消」`ghost` |
| `src/desktop_pet/core/constants.py` | 改 | 独立标量 `JP_LOG_BTN_CLOSE`（同步 `__all__`，未动四张 token 表键集） |
| `tests/test_ui_style_unification.py` | **新增** | 23 项 |

### 9.2 QA 独立验证发现并修复的缺陷（D 项）

- **现象**：`log_window.py` 原第 88 行的 `if entry.status != C.DAILY_LOG_STATUS_UNPROCESSED:` 门控，
  使第 49 行的 `text_secondary` 映射**永不参与渲染** → 只改颜色是**死改动**，§3.1 目标未达成。
- **发现方式**：QA 用**有意失败的探针** `test_unprocessed_card_renders_contrast_status_label` + WCAG 量化（`muted` 2.59 → `text_secondary` 6.18）钉住，而非「跑一遍全绿就签收」。
- **裁决**：走「三态齐平」（删门控、三态都渲染标签），不删映射降口径。
- **修复**：删除门控（去一层 if + 分支体去缩进，最小 diff），补中文注释说明动机；未改任何测试。

### 9.3 遗留项

1. **圆角裁剪需真机复核**（D1）：离屏（offscreen QPA / Qt 6.9.3）实测 `QPushButton` 的 QSS `border-radius` **不裁剪背景**（四角像素 = 填充色），同环境 `QPainter.drawRoundedRect` 自绘正常。真机确认前，圆角改动只能视为「档位已对齐」，不等价于「视觉已生效」。
2. `theme.py` 的 `QMessageBox` 保底 QSS 属**防御性兜底**（当前仓库已无 `QMessageBox` 调用方），保留以防新增调用方落到系统默认样式。
3. `vocab_window.py` 的 `Final` 未导入（F821）为分支既有问题，不影响运行，待后续清理。

### 9.3 增补（2026-10-01）：详情「记住了」按钮渐变对齐气泡（D2 更新裁决）

| 文件 | 内容 |
| --- | --- |
| `src/desktop_pet/ui/theme.py` | `success` 变体三态底色改为与 `BubbleButtonBar` 完全同款的 `qlineargradient`（常态 hover→success→pressed 三停；悬停 hover→success；按下 success→pressed），端点取 `SEMANTIC_COLORS` success 族（与 `jp_button_primary_*` 同值，映射由 `test_design_tokens` 钉死）；描边置 transparent；圆角仍 `RADIUS["md"]`=8px（胶囊档仍为气泡浮层专属） |
| `tests/test_jp_detail_mastered.py` | 像素取色断言改 ±2/通道容差（渐变下中心像素落在 0.5 停靠点哪侧由按钮尺寸奇偶决定，±1/通道波动；未上色/错色仍差几十以上可分辨） |

「记住了」点击处置逻辑（落 mastered + 移出生词本 + 即时 `refresh` 生词本窗口 + 托盘反馈追加「已移出生词本」后缀）此前已在批次 2 落地（`controller._on_detail_mastered` / `_remove_word_from_vocab`），本批仅动视觉，全量测试通过。

### 9.4 增补（2026-10-01）：焦点环改细改淡（用户拍板 C 方案）

- **现状问题**：``:focus`` 为 ``2px solid primary``（#1F2328 近黑），粗黑框压过按钮本身。
- **拍板**：四候选效果图（现状 / 1px 中灰 / 1px 浅灰 / 1px 淡蓝，见
  `_ui-review-phase-d/focus-ring-variants.png`）中先选淡蓝、**后改拍浅灰**（用户复核真机观感：
  「淡蓝色不好看」）→ 终版 **1px 浅灰 `text_faint`（#98A2AD）**，复用既有语义 token。
- **落地**：`theme.py` 新增独立标量 `FOCUS_RING_WIDTH_PX = 1`（四类 focus 规则统一改
  `1px solid text_faint`：QPushButton 基础/变体、QComboBox/QLineEdit、QPlainTextEdit/QTextEdit）；
  `FOCUS_RING_PX = 2` 保留但**仅**用于 Tab 选中下划线线宽（名字属历史沿用，注释已说明）。
- **测试**：`test_theme.py` 焦点环契约改为字面量 `1px solid #98A2AD` + 旧 `2px solid #1F2328`、淡蓝 `#4C8DDA` 双反向断言
  反向断言（防残留）+ Tab 下划线线宽守护；全量 pytest 通过。
