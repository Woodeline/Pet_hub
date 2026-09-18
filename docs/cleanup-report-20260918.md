# 代码瘦身报告 — desktop-pet

- **日期**：2026-09-18
- **分支**：`feature-ui-upgrade`（未提交）
- **基线**：`ed447ff`（P0 + P1/P2 + 托盘"减少动效"，880 tests 全绿）
- **结果**：**36 个文件变更，+56 / −1149 行；839 tests 全绿（rc=0）**
- **原则**：只删「明确废弃、生产零引用」的内容；不动业务行为、不动对外 API、不动画布 160×180 与配色契约

---

## 一、删除的文件（5 个，共 868 行）

| 文件 | 行数 | 删除理由 |
|---|---|---|
| `src/desktop_pet/core/jisho.py` | 215 | Jisho 第三方词典 API 客户端。日语详情页查找链已改为「打包词库 `jlpt_word_details.json` → 本地缓存 → DeepSeek 联网」三级，**生产代码对 Jisho 零引用**（全仓 `grep -ri jisho` 仅剩测试与文档叙述）。离线可用是硬需求，保留一个必然超时/被墙的联网客户端只会误导后续维护者 |
| `src/desktop_pet/core/jisho_cache_store.py` | 236 | 仅服务于上述 API 的磁盘缓存层，引用方只有 `jisho.py` / `jisho_worker.py` 两个同样被删的模块；现有 `word_details_cache_store.py` 已承担等价职责 |
| `src/desktop_pet/ui/jisho_worker.py` | 63 | 上述 API 的 QThread 包装，无任何窗口/控制器引用；详情页请求走 `word_detail_worker.py` |
| `tests/test_jisho.py` | 181 | 被测模块已删，测试随之失效 |
| `tests/test_jisho_cache_store.py` | 173 | 同上 |

> 文件未做物理删除，已移入工作区外隔离区 `C:/Users/王佐成/WorkBuddy/_cleanup_quarantine_20260918/files/`，`git status` 中显示为 `D`（已跟踪文件被删）。

---

## 二、删除的死代码

### `core/constants.py`（+2 / −34）
| 删除内容 | 理由 |
|---|---|
| `JISHO_*` 6 个常量 + 对应 `__all__` 条目 | 随 `jisho.py` 一起失效，无任何读取点 |
| `KeystrokeOutcome` IntEnum（4 个成员） | 键盘事件聚合重构后改用普通 bool 短路，该枚举从定义起就未被任何生产代码引用；`docs/architecture.md` 的对应条目同步删除 |
| `SLEEPY_REST_S` | 睡眠态时长常量，仅被已移除的旧状态机读取 |
| `EAR_TWITCH_MAX_S` | 耳朵抖动上限，实现只用 `EAR_TWITCH_MIN_S` + `EAR_TWITCH_AMPLITUDE_DEG` 两个常量，上限值恒未被读 |
| `PET_ANCHOR_X` | 窗口锚点 X 已由 `pet_window` 内的即时计算取代 |
| `BUBBLE_MAX_WIDTH_PX` | 与 `BUBBLE_MAX_WIDTH` 语义重复的废弃别名，实际读取点统一用后者 |

### 其他源码（−173 行）
| 文件 | 删除内容 | 理由 |
|---|---|---|
| `core/vocabulary.py` | `WordSampler` 类（含 `__all__` 条目、`import random`、类 docstring） | 已被 `weighted_picker.py` + `vocab_store.py` 取代的旧抽样器，生产零调用；`docs/` 相关文档加注「已移除」说明 |
| `ui/pet_renderer.py` | `_tapered_path()`（37 行）、`_brush_blush` | 尾巴改为粗弧绘制后 `_tapered_path` 失去唯一调用点；`_brush_blush` 自鼾泡重绘改造后未被引用 |
| `core/pet_model.py` | `_temp_action_until` 字段、未使用的 `Final` 导入 | 临时动作计时迁移到 `motion.py` 的插值器后，该字段只写不读 |
| `ui/pet_window.py` | `_press_ts`（2 处赋值/读取） | 点击判定已统一走 5px 位移阈值，按下时间戳不再参与 |
| `core/event_aggregator.py` | `_window_ms` 属性 | 冗余状态：写入后无任何生产读取点，仅有一处「空循环 + 断言」的测试在消费它 —— 该断言不产生任何行为约束，故连测试一并删除 |
| `ui/icon_factory.py` | `ICON_NAMES` 6 → 4（保留 `close`/`retry`/`remove`/`trash`）、`_path_refresh`、`_path_chevron_down` | 「零外部图片素材」硬约束下未接入 UI 绘制路径，`make_icon("refresh")` / `("chevron_down")` 全仓无调用点；`tests/test_icon_factory.py` 同步收敛期望集合 |
| `ui/log_window.py` | 未使用的 `Qt` 导入 | pyflakes F401 |
| `core/word_details_cache_store.py` | 未使用的导入 | pyflakes F401 |

### 测试侧冗余（−238 行）
| 文件 | 删除内容 | 理由 |
|---|---|---|
| `tests/test_vocabulary.py` | `WordSampler` 相关 6 组用例（含参数化展开） | 被测类已删 |
| `tests/test_static_constraints.py` | `("SLEEPY_REST_S", 30.0)` 断言、`KeystrokeOutcome` 校验 | 被测常量/枚举已删 |
| `tests/test_config.py` | 未使用的 `import os` | pyflakes F401 |
| `tests/test_event_aggregator.py` | `_window_ms` 断言 | 该断言恒真、无行为约束（见上） |
| `tests/test_hand_visibility.py` | 未使用的 `_GEO_PAW_W` 导入 | pyflakes F401 |
| `tests/test_icon_factory.py` | 6 名 → 4 名期望集合 | 跟随 `ICON_NAMES` 收敛 |

---

## 三、新增与改动（功能性，非删除）

| 文件 | 变化 | 说明 |
|---|---|---|
| `tests/test_ui_icon_integration.py` | **新增，69 行 / 2 用例** | 图标此前虽已实现但**从未接到任何按钮上**（`setIcon` 全仓零调用），属「有实现无使用」的隐性死代码。本用例断言详情窗/生词本窗口的 retry/close/remove/clear 按钮**确实持有非空 icon**、`availableSizes()` 非空、尺寸恰为字面量 16px。已做变异验证（改回不设图标 → FAIL） |
| `ui/word_detail_window.py`（+10 / −2）<br>`ui/vocab_window.py`（+14 / −2） | 按钮接入 `make_icon` + `setIconSize(QSize(16, 16))`，颜色取自 `SEMANTIC_COLORS` | 兑现图标工厂的实际价值，同时消除裸色值；**文案、标题、窗口尺寸、信号连接、按钮对象名一律未变** |
| `requirements-dev.txt` / `pyproject.toml` | 补 `pytest-qt>=4.4` | **依赖缺口**：16 个测试文件使用 `qtbot`，但此前从未声明 `pytest-qt`。本机恰好装着 4.5.0 所以测试一直能过，**换机器 / 重建 venv 会直接 collect error**。`pytest-cov` 保留（已声明、当前未用，属常规工具链） |

---

## 四、文档同步

| 文件 | 变化 |
|---|---|
| `docs/architecture.md` | 删除 `KeystrokeOutcome`、`_temp_action_until`、`_press_ts` 三行已失效条目 |
| 10 个日语相关文档/mermaid<br>（`prd-*` / `design-*` / `class-diagram*` / `sequence-diagram*`） | 仅**首行加归档注记**（Jisho 客户端与 `WordSampler` 于 2026-09-18 移除），**正文一字未改** —— 保留设计演进的历史可读性 |
| `tests/manual_checklist.md` | 移除 Jisho 相关手工验证项 |

---

## 五、验证证据

| 检查项 | 结果 |
|---|---|
| `pytest tests/ -q`（offscreen） | **rc=0，839 passed**（37 个测试文件收集到 839 用例，0 FAILED / 0 ERROR） |
| 基线对比 | 880 → 839；减少 43 例 = 删除 45 例（Jisho 14+15、`WordSampler` 6+6、常量/枚举 2 等）＋ 新增 2 例图标集成 |
| 模块可导入性 | `import desktop_pet.core.jisho` → `ModuleNotFoundError`（确认断链干净、无残留引用） |
| 静态约束（`test_static_constraints.py`） | 全绿 —— `core/` 仍零 Qt、`ui/` 仍零裸十六进制色值、画布仍 160×180 |
| 配色契约（`test_color_palette_matches_prd`） | 全绿 —— `COLORS` 32 键精确匹配未动 |
| 变异验证 | `setIcon` 回退 → 期望用例 FAIL；恢复后 sha1 与原文一致（证明用例非恒绿） |
| `__all__` 一致性 | `constants.py` / `vocabulary.py` / `icon_factory.py` 的 `__all__` 与实体集合逐一核对，无幽灵条目 |
| 窗口 API | `word_detail_window` / `vocab_window` 的公开方法签名、信号列表 diff 为空 |

---

## 六、清理后项目结构

```
desktop-pet/
├── src/desktop_pet/                      36 个 .py / 10479 行
│   ├── main.py                           (116)
│   ├── app/
│   │   ├── controller.py                 (1138)
│   │   └── keyboard_listener.py          (123)
│   ├── core/                             零 Qt · 零 print · 零 time
│   │   ├── config.py                     (355)
│   │   ├── constants.py                  (770)
│   │   ├── daily_log_store.py            (340)
│   │   ├── event_aggregator.py           (130)
│   │   ├── llm_client.py                 (294)
│   │   ├── mastered_store.py             (309)
│   │   ├── mood_state_machine.py         (382)
│   │   ├── motion.py                     (463)
│   │   ├── paths.py                      (61)
│   │   ├── pet_model.py                  (487)
│   │   ├── vocab_store.py                (310)
│   │   ├── vocabulary.py                 (211)  ← WordSampler 已删
│   │   ├── weighted_picker.py            (51)
│   │   ├── word_detail.py                (251)
│   │   ├── word_detail_bank.py           (123)
│   │   └── word_details_cache_store.py   (243)
│   └── ui/
│       ├── bubble.py                     (472)
│       ├── bubble_button_bar.py          (253)
│       ├── icon_factory.py               (148)  ← ICON_NAMES 4 名
│       ├── log_window.py                 (245)
│       ├── motion_ui.py                  (188)
│       ├── pet_renderer.py               (1136) ← _tapered_path 已删
│       ├── pet_window.py                 (298)
│       ├── spinner.py                    (147)
│       ├── theme.py                      (264)
│       ├── tray.py                       (343)
│       ├── vocab_window.py               (245)
│       ├── word_detail_window.py         (453)
│       └── word_detail_worker.py         (100)
├── tests/                                39 个文件（含 conftest），839 用例
├── docs/                                 新增本报告，10 份日语文档加归档注记
└── requirements-dev.txt / pyproject.toml 补 pytest-qt
```

**已消失的模块**：`core/jisho.py`、`core/jisho_cache_store.py`、`ui/jisho_worker.py`（+ 对应测试）。

---

## 七、未做的清理（有意保留）

| 对象 | 保留理由 |
|---|---|
| `pet_model.tail_evade()` | 名为 "evade" 易误判为废弃，实为**活跃观测 API** —— `pet_window` 每帧调用 `set_tail_evade()` 驱动尾巴闪避动画。删除会直接改变渲染行为 |
| `pytest-cov` | 已声明、当前无覆盖率门槛，但属常规工具链，保留成本为零 |
| 历史 PRD/设计文档正文 | 只加归档注记、不改正文，保留设计演进脉络 |
| `docs/` 中的 Jisho 叙述 | 同上，删正文会丢失决策上下文 |
