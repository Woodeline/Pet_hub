# 变更记录：气泡台词按触发源分两组 + 键盘关键字门控（需求 C）

> 日期：2026-09-26
> 性质：行为变更 + 配置 schema 增量（新增 1 个字段；`CONFIG_VERSION` 保持 1，向后兼容）
> 影响文件：`src/desktop_pet/core/constants.py`、`src/desktop_pet/core/config.py`、
> `src/desktop_pet/app/controller.py`、`src/desktop_pet/ui/bubble_text_dialog.py`、
> `tests/`（新增 2 个测试文件 + 4 个既有文件更新）、`docs/prd.md`、`docs/architecture.md`
> 前置变更：[`change-bubble-trigger-rhythm.md`](./change-bubble-trigger-rhythm.md)（需求 B，同日）
> —— 本文消除其 §7 第一条「已知边界」。

---

## 1. 用户需求

1. **关键字触发**：当自定义文案内容包含「键盘」关键字时，该条文案不得被自动触发，
   仅在检测到键盘敲击事件时才允许触发；
2. **频率控制**：自动触发的气泡显示间隔改为在 20 秒 ~ 1 分钟之间随机取值；
3. **保留行为**：鼠标移动到宠物上时，仍应立即显示一条文案，且该条文案不包含「键盘」关键字；
4. **文案分组**：在气泡文案自定义中将其分为两组，一组用于自动触发，另一组用于敲击键盘时触发，
   并明确两组的触发来源与显示规则。

> 其中需求 2 已由需求 B 落地（`BUBBLE_MIN_INTERVAL_S/MAX_INTERVAL_S = 20/60`），本次只做交叉校验与复述。

## 2. 现状与根因（改前）

`controller._bubble_texts_for(key)` 是唯一的台词选池入口，改前逻辑只有两级：

```
cfg.bubble_texts_custom 非空 → 原样返回（对所有 key、所有触发来源统一生效）
否则 → 预设台词包 → 内置文案表
```

由此产生两个问题：

| 问题 | 表现 |
| --- | --- |
| **无法区分触发源** | 用户在自定义池填了「键盘敲得真快！」，鼠标移到宠物上也会弹出这句 —— 文案与触发方式不匹配 |
| **约束不可达** | 需求 B 只把「含键盘关键字」这一约束做在了内置表与预设台词包上（且有守护），自定义池优先级最高、绕过一切，等于用户一填就失效 |

需求 B 的变更文档已把这条明确列为已知边界：

> **自定义台词池**（托盘「气泡文案…」）优先级最高且对所有情绪键统一生效。用户填入自定义台词后，
> 「键盘文案含键盘关键字」这一约束不再由系统保证。

需求 C 正是要消除该边界，并把「哪条文案归哪种触发」变成一个**用户可运营的显式结构**。

## 3. 目标行为（验收基线）

**触发来源 × 台词来源的完整矩阵**：

| 触发来源 | 具体事件 | 使用的自定义池 | 预设台词包 / 内置表 |
| --- | --- | --- | --- |
| **键盘敲击** | 打字、按任意键（`_on_keystroke`） | **敲击键盘组** `bubble_texts_custom_keyboard`（不过滤） | 不过滤（键盘专属键文案本就含键盘词） |
| 状态机迁移 | 情绪自然变化（`_on_frame_tick`） | **自动触发组** `bubble_texts_custom`（**过滤键盘词**） | **过滤键盘词** |
| 休息态呵欠 | 15~30s 随机呵欠（`_on_frame_tick`） | 同上 | 同上 |
| **鼠标悬停 / 点击** | 停留 1s / 单击（`_on_gesture`，`immediate=True`） | 同上 | 同上 |

四条关键不变量：

1. **含键盘关键字的文案永远不会被自动来源触发** —— 不论它写在自动组、预设包还是内置表里；
2. **鼠标路径的文案必不含键盘关键字**（鼠标 = 自动来源，走同一套过滤）；
3. 自动来源**仍按 20~60 秒随机窗口节流**，鼠标 `immediate` 仍绕过窗口立即显示（需求 B 行为不变）；
4. 自动组若**整体被过滤空**，视为「该组未配置」→ 回落预设台词包（**不会**静默不弹）；
   最终仍为空则放弃本次展示（`_bubble_texts_for` 返回 `None`）。

**配置字段语义变化**：

| 字段 | 改前语义 | 改后语义 |
| --- | --- | --- |
| `bubble_texts_custom` | 自定义池（对所有来源生效） | **自动触发组**（对自动来源生效，含键盘词的条目被过滤） |
| `bubble_texts_custom_keyboard` | —（新增） | **敲击键盘组**（仅真实敲击键盘时生效，不过滤） |

## 4. 设计要点

**① 门控发生在「展示时」，不发生在「入库时」。**
`core.config._coerce_bubble_texts_custom` 只做 strip / 去空 / 去重 / 限长，
**不做**关键字过滤。含键盘词的行原样写进 `config.json` —— 这样用户才能把一条文案在
「自动组 ↔ 敲击组」之间搬移而不丢内容。过滤只在 `controller._bubble_texts_for` 每次选池时执行。

**② 过滤逐级下沉，不只覆盖优先级最高的那一级。**
自动侧的过滤顺序是：自动组自定义 → 预设台词包 → 内置文案表，**每一级都过
`constants.filter_keyboard_texts`**。这样即便未来有人给内置表新增一个自动侧键、
或改写预设包文案混进键盘词，不变量仍然成立。

**③ 「过滤后为空」等价于「未配置」而非「放弃展示」。**
若自动组只有 1 条且含键盘词，过滤得空 → 继续回落预设包；只有连预设包/内置表也被过滤空
才返回 `None`。避免用户一次误配置就让自动气泡彻底消失。

**④ 触发源由调用方显式声明，不靠键名推断。**
`_show_bubble_for(key, now, *, immediate, keyboard)`：`keyboard` 是与 `immediate` 正交的
独立维度（`immediate` 管节奏窗口，`keyboard` 管选池与过滤）。
`_on_keystroke` 的两处调用显式传 `keyboard=True`；帧循环与鼠标手势路径不传（默认 `False`）。
严禁通过「key 是否属于 `KEYBOARD_BUBBLE_EXPRESSIONS`」来反推触发源 —— 那会让鼠标路径
在将来复用到某个键盘键时静默失效。

**⑤ 单一事实源。**
键盘关键字词表只有一个：`constants.BUBBLE_KEYBOARD_KEYWORDS`；
判定与过滤也只有一个：`constants.has_keyboard_keyword()` / `filter_keyboard_texts()`。
config / controller / ui 三处都引用它，不得各自实现。

## 5. 实现落点

### `src/desktop_pet/core/constants.py`
- 新增 `has_keyboard_keyword(text) -> bool` 与 `filter_keyboard_texts(texts) -> list[str]`（纯函数，零 Qt）。
- `__all__` 登记 2 个新符号。
- 更新两处注释：键盘专属键集说明、自定义池分组语义说明。

### `src/desktop_pet/core/config.py`
- `AppConfig` 新增 `bubble_texts_custom_keyboard: list[str]`（默认空）。
- `_coerce_bubble_texts_custom` 文档补注「两组共用、不做关键字过滤」。
- `to_dict` / `from_dict` 同步；`CONFIG_VERSION` 保持 1（新增字段缺失时回落默认，天然向后兼容）。

### `src/desktop_pet/app/controller.py`
- `_show_bubble_for` 新增 `keyboard: bool = False` 参数，传递给 `_bubble_texts_for`。
- `_bubble_texts_for(key, *, keyboard=False)` 重写为按触发源选池 + 逐级过滤（见 §4）。
- `_on_keystroke` 两处调用加 `keyboard=True`。
- `_on_bubble_text_settings` / `_on_bubble_text_applied` 扩展为三参；两组**一次事务写入**。

### `src/desktop_pet/ui/bubble_text_dialog.py`
- 由单一编辑区拆为两个：`_auto_edit`（自动触发组）/ `_hit_edit`（敲击键盘组），各带独立计数标签。
- 自动组计数标签实时提示「其中 N 条含键盘关键字，不会被自动触发（如需生效请移到敲击键盘组）」。
- `applied` 信号签名 `Signal(str, list, list)`；`load_state(pack, auto, hit)`。
- 两个 `QGroupBox` 标题明确标注触发来源；`parse_custom_texts` 静态方法两组共用。

### 测试
- **新增** `tests/test_bubble_text_groups.py`（工程师侧，16 用例）：关键字门控、两组独立、
  鼠标路径、常量工具、源码级触发源隔离、以及**回落路径也过滤**的契约用例。
- **新增** `tests/test_bubble_text_groups_qa.py`（QA 独立验证，27 用例）：黑盒「配置 → 运行 → 实际展示文案」
  链路、关键字位置参数化、穷举矩阵（3 预设包 × 11 键 × 2 路径）、配置文件端到端、升级兼容、清洗边界、Qt 集成。
- **更新** `tests/test_config.py`（新增敲击组 coerce / roundtrip / 旧配置兼容用例 + 键集断言）、
  `tests/test_bubble_text_dialog.py`（重写为两组，13 用例）、
  `tests/test_bubble_text_settings.py`（来源优先级改为自动侧口径 + 三参落地，10 用例）。

## 6. 验证结论

| 项目 | 结果 |
| --- | --- |
| 全量回归 | `tests/` 共 **1291** 用例，EXIT=0，0 失败 / 0 错误（改前 1229） |
| QA 独立验证 | `tests/test_bubble_text_groups_qa.py` 27 用例全绿（独立进程、黑盒路径） |
| 变异验证 | **6/6 全部被测试捕获**（详见下表），还原后源码 md5 与 baseline 逐字节一致 |

变异验证明细：

| 变异 | 内容 | 结果 |
| --- | --- | --- |
| M1 | 自动组自定义池不做键盘词过滤 | FAILED（预期） |
| M2 | 回落预设包/内置表时不做键盘词过滤 | **首轮 SURVIVED → 补测试后 FAILED** |
| M3 | 敲击路径不标记 `keyboard=True`（改用自动池） | FAILED（预期） |
| M4 | 鼠标路径误标记 `keyboard=True`（改用敲击池） | FAILED（预期） |
| M5 | `has_keyboard_keyword` 恒返回 `False` | FAILED（预期） |
| M6 | `BUBBLE_MIN_INTERVAL_S` 由 20.0 改为 3.0 | FAILED（预期） |

> **M2 的价值**：首轮变异存活，暴露出既有用例全部使用「自动组非空」的场景 —— 自动分支提前
> `return`，永远走不到回落路径，因此「过滤只做在自定义池上」也能全绿。据此补了
> `test_auto_fallback_path_also_filters_keyboard_text` / `test_auto_fallback_path_filters_pack_texts`
> （工程师侧）与 `test_auto_fallback_never_leaks_keyboard_text` / `test_auto_fallback_pack_level_filter`
> （QA 侧）四个契约用例，复验即被杀死。

**还原方式**：`cp` 备份 + `try/finally` 兜底还原 + 每个变异前后 md5 复核，
未执行任何 git 写操作，未删除任何文件。

## 7. 已知边界

- **关键字判定是朴素子串匹配**（`any(kw in text)`），不做分词。词表中的单字「敲」可能误伤
  非键盘语义的文案（例如「敲开心！」会被判为键盘文案而无法自动触发）。用户可通过改写文案规避；
  若将来需要，可在 `BUBBLE_KEYBOARD_KEYWORDS` 上做词边界处理，无需改动调用方。
- **门控只作用于情绪气泡**。单词泡泡（`BubbleWindow.show_word`）与日语学习模块零关联，不受两组池影响。
- **两组共用同一条数与长度上限**（`BUBBLE_TEXT_CUSTOM_MAX_COUNT` / `MAX_LEN`），不是各组独立配额。
- **自动组的全部内容都被过滤时不会报错也不会提示失败**，只静默回落预设台词包；UI 的实时计数提示是唯一的提示面。
- 对话框内提示文案沿用 `ui/` 层硬编码中文（与 `bubble_text_dialog.py` 既有风格一致），未集中进 `constants`。

## 8. 被本变更覆盖的既有文档描述

| 文档 | 位置 | 处理 |
| --- | --- | --- |
| `docs/change-bubble-trigger-rhythm.md` | §7 第 1 条「自定义台词池……约束不再由系统保证」 | 就地划除并指向本文（边界已消除） |
| `docs/change-bubble-trigger-rhythm.md` | 顶部「性质 / 影响文件」 | 加注「同日后续变更」 |
| `docs/prd.md` | FR-30 | 就地补充两组池、关键字门控与鼠标路径不含键盘词的约定 |
| `docs/architecture.md` | FR-30 行 | 就地补充分组与过滤，模块列补 `ui/bubble_text_dialog.py`、`core/config.py` |

## 9. 复现与回归入口

```bash
# 全量回归
cd desktop-pet
PYTHONPATH=src QT_QPA_PLATFORM=offscreen <venv-python> -m pytest tests/ -q

# 只跑本次分组与门控守护
... -m pytest tests/test_bubble_text_groups.py tests/test_bubble_text_groups_qa.py -q

# 变异验证（一次一个变异，脚本自带 try/finally 兜底还原 + md5 复核）
<venv-python> ../_tmp_bubble_groups/run_mutation.py
```

**真机手测建议**（offscreen 测不出 Qt 平台差异）：

1. 托盘「气泡文案…」→ 自动触发组填「键盘敲得真快！」，观察计数标签是否提示「1 条含键盘关键字，不会被自动触发」；
2. 打字 1 分钟：气泡条数应 ≤ 4，且键盘文案只可能出现在敲键盘时；
3. 鼠标移上去 / 单击：应**立即**出现一条文案，且一定不含「键盘」字样；
4. 把该条文案从自动组移到敲击组，再打字 → 此时才可能看到这句。

---

## 10. 同日重做：自动触发从「节流阀」升级为「排期制」（2026-09-26 下午）

### 10.1 重做原因（用户验收反馈：四项需求未做到位）

上版实现把需求 2 的「20 秒~1 分钟」做成了**纯事件节流阀**：`_next_bubble_ts` 只在
「事件发生时」检查——状态迁移 / 呵欠 / 敲击不来，气泡就永远不会出现。真机日志
（`%APPDATA%\desktop-pet\app.log` 13:45~13:48 段）验证了两个用户可见缺陷：

| 缺陷 | 表现 | 根因 |
| --- | --- | --- |
| 安静待机永远不说话 | 宠物晾在桌面上时，IDLE 稳态**没有任何气泡** | 排期器不存在：IDLE 稳态无迁移、无呵欠、无鼠标事件 → `_show_bubble_for` 无从被调用 |
| 稳态打字看不到敲击组 | 用户配了敲击组文案，持续打字时几乎不出现 | 敲击组文案只在**情绪迁移瞬间**（进专注/兴奋/久违回座/吵醒）才有机会弹出，稳态敲击无迁移 → 无调用 |

即「20 秒~1 分钟随机显示」这一验收点**在两个最日常的场景下根本没有发生**。

### 10.2 重做内容

`app/controller.py`（文案选池 `_bubble_texts_for` 与关键字门控**零改动**）：

1. **自动窗升级为递归排期**：帧循环每帧检查 `now >= _next_bubble_ts`，到点**主动**
   调 `_show_bubble_for(self._sm.mood, now)` 展示一条自动组文案；每次成功展示（无论
   来源）都重排 `now + 20~60s` 随机。状态迁移 / 呵欠只是恰好在窗口开放时**抢先供词**，
   与排期器共用同一窗口（不会双弹）。首个排期在 `start()` 种下（启动 20~60s 后）。
2. **敲击组独立敲击窗** `_next_kb_bubble_ts`：与自动窗同规格（20~60s 随机）但**相互
   独立**——敲击不挤占自动闲聊额度，自动闲聊也不推迟敲击反馈。
3. **稳态敲击兜底**：`_on_keystroke` 改为先选 key 再统一调用——键盘专属表情 → 该表情；
   仅情绪态迁移 → 目标情绪；**稳态敲击（无迁移）→ 回落 `Expression.FOCUS`**。只要真在
   敲键盘，敲击组文案就按 20~60s 节奏可靠出现（需求 1 的正向面）。
4. **`_show_bubble_for` 返回 `bool`**（是否真的展示）：帧循环排期器据此保持「被抑制
   （单词泡泡展示中 / 气泡关）→ 窗口不推进 → 解除后下一帧补上」的重试语义。
5. **睡觉态到点不闲聊**但窗口照常推进（防醒来瞬间被糊一条）；鼠标 `immediate` 展示
   重排自动窗、不碰敲击窗。

`ui/bubble_text_dialog.py`：两组的触发来源说明同步更新（自动组标注「每 20 秒~1 分钟
随机一条」，敲击组标注「独立 20 秒~1 分钟随机节奏，打字再快也不刷屏」）。

### 10.3 验证

- 气泡相关 5 个测试文件共 **90 用例**全绿；全量回归 `tests/` EXIT=0；
- 新增守护（工程师侧 + QA 侧各 5+6 例）：安静待机 10 分钟自动闲聊 10~30 条、
  稳态打字 3 分钟敲击组出现 3~9 次、两窗互不挤占、睡觉态跳过但推进窗口、
  被抑制时不推进窗口（解除后补上）、`_show_bubble_for` 布尔返回契约。
- 关键字门控 / 两组选池 / 鼠标路径过滤的行为与上版**完全一致**（相关用例未改动即通过）。
