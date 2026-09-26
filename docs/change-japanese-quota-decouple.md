# 变更记录：日语学习「每日数量」与「立即显示一个新单词」解耦

> 日期：2026-09-26
> 性质：增量行为变更（不新增配置项、不改持久化 schema、不改 UI 结构）
> 影响文件：`src/desktop_pet/app/controller.py`、`src/desktop_pet/core/constants.py`、`tests/`（新增 2 个测试文件 + 修正 3 处既有断言）

---

## 1. 变更动因

改前存在两处语义缠绕：

1. **配额被手动操作穿透**：`_dispose_word` 对三态终态**无条件**写 `DailyLogStore`，而 `count_for(day)` 就是当日记录条数、`shown_ids_for(day)` 就是当日去重池。因此手动「立即显示」的单词既会**吃掉每日配额**，也会**挤占当日抽词池**。
2. **手动路径仍被上限拦截**：`_on_jp_show_now` 入口处先判 `_jp_stop_for_today()`，达到上限即 `return` 并提示「今日学习完成」，用户无法再手动看词。
3. **自动节奏过密**：`JP_WORD_MIN_INTERVAL_S=25.0` / `JP_WORD_MAX_INTERVAL_S=50.0`，最密 25 秒一次，对轻量陪伴场景偏打扰。

## 2. 目标行为（验收基线）

| 编号 | 需求 | 现状 |
| --- | --- | --- |
| R1 | 点击「立即显示一个新单词」，新展示的单词**不计入**「每日数量」的统计与配额 | 已达成 |
| R2 | 每日数量计数**仅由正常（自动）学习流程触发**，且**只受其影响** | 已达成 |
| R3 | 每日单词自动显示间隔改为**随机 30 秒 ~ 10 分钟** | 已达成 |
| — | 每日配额不再受手动显示单词的操作影响 | 已达成 |

## 3. 行为对照表

| 场景 | 改前 | 改后 |
| --- | --- | --- |
| 手动展示的词 → 超时 / 未处理 | 写当日日志（`shown_today +1`，占配额） | **不写日志**，配额不变 |
| 手动展示的词 → 点「记住了」 | `mastered +1` **且** 写当日日志 | `mastered +1`，**不写当日日志** |
| 手动展示的词 → 点「新单词」 | `vocab +1` **且** 写当日日志 | `vocab +1`，**不写当日日志** |
| 今日配额已达上限时点击「立即显示」 | 被拦截 + 提示「今日学习完成」 | **照常弹出新词**，配额不变，不置「今日完成」标志 |
| 手动展示的词是否参与「当天不重复」去重 | 参与（经当日日志的 `shown_ids`） | **参与**（经内存级 `_manual_shown_ids_today`，不落盘、不计入 count） |
| 自动路径到达上限 | 停止展示 | 停止展示（**不变**，严格遵守上限） |
| 自动展示间隔 | 25 ~ 50 秒 | **30 ~ 600 秒**（30 秒 ~ 10 分钟） |
| 学习未开启时点击「立即显示」 | 静默返回，无任何反馈 | 通知「请先开启「日语学习」哦～」 |
| 该等级词池耗尽时点击「立即显示」 | 走自动路径的「已全部掌握」一次性通知 | 通知「{level} 的词都学完了，换个难度试试～」 |
| 手动路径发生异常 | 仅写日志 | 额外通知「显示单词时出错了，请稍后重试」 |

## 4. 设计决策（已与用户对齐）

- **D1 —— 长期数据保留**：手动展示的词点「记住了」/「新单词」时**仍写入** `mastered.json` / `vocabulary.json`。解耦只针对「每日配额统计」，不针对学习成果。
- **D2 —— 当日去重保留**：手动展示的词**参与**「当天不重复展示同一单词」去重，但通过**内存级**集合 `_manual_shown_ids_today` 实现：**不落盘、不计入 count、跨日清空**。这样既避免同一天重复抽到同一个词，又不让手动操作触碰任何持久化的当日统计。
- **取舍说明**：原 `_show_word_bubble` 的 `ignore_daily_limit: bool` 参数被重构为语义更准确的 `manual: bool`；词库为空时手动点击**每次**都给反馈（原为 `_bank_warned` 一次性去重），以落实 `constants.py` 中既有的设计意图「每次手动点击都必须给出可见反馈，严禁静默返回」。

## 5. 实现落点

### `src/desktop_pet/core/constants.py`
- `JP_WORD_MIN_INTERVAL_S = 30.0` / `JP_WORD_MAX_INTERVAL_S = 600.0`（R3）。
- `JP_NOTIFY_SHOW_NOW_OVER_LIMIT` 文案去掉不再准确的「已超出今日目标」，改为「…今日已完成 {count}/{limit}，手动显示不计入每日数量」。
- 四条此前**零引用**的手动路径文案 `JP_NOTIFY_JP_OFF` / `JP_NOTIFY_POOL_EXHAUSTED` / `JP_NOTIFY_SHOW_NOW_FAILED` / `JP_NOTIFY_SHOW_NOW_OVER_LIMIT` 全部落地使用（消除死常量）。

### `src/desktop_pet/app/controller.py`
- 新增状态 `self._word_manual: bool`（当前展示词是否来自手动路径）、`self._manual_shown_ids_today: set[str]`（D2 内存去重集合）。
- 帧循环跨日分支追加 `self._manual_shown_ids_today.clear()`。
- `_show_word_bubble(now, *, bypass_gap=False, manual=False)`：`manual=True` 跳过 `_jp_stop_for_today()`；抽取排除集合并入 `_manual_shown_ids_today`；`_word_manual` **在所有守卫之后**才赋值（守卫 return 不污染状态）。
- `_on_jp_show_now`：**移除**入口的 `_jp_stop_for_today()` 拦截；按是否已达上限选择成功文案；补全未开启 / 池耗尽 / 异常三类可见反馈。
- `_dispose_word`：开头读取并**即刻复位** `_word_manual`；三态 `_daily_log.add_entry` 全部加 `if not manual:` 守卫；`mastered` / `vocab` 的 `add` 保持无条件（D1）；`manual` 为真时把 `entry.id` 并入 `_manual_shown_ids_today`（D2）。

> 依赖方向与分层约束未变：`core/` 仍零 Qt、零 `time`/`datetime`、零 `print`；三态与内存集合均由 app 层驱动。

## 6. 验证结论

| 层级 | 内容 | 结果 |
| --- | --- | --- |
| 工程师自测 | `tests/test_jp_quota_decouple.py`（15 用例） | 通过 |
| 独立验证 | `tests/test_jp_quota_decouple_qa.py`（18 用例，外部进程独立编写） | 通过 |
| 变异验证 | 4 组定向变异（去 `if not manual` 守卫 / 去 `not manual and` / 去排除集合手动项 / `JP_WORD_MAX_INTERVAL_S` 回退 50） | 4/4 均被测试捕获为 FAIL，还原后恢复绿 |
| 全量回归 | `tests/` 共 1216 用例 | 全绿（0 失败 / 0 错误 / 0 跳过） |

独立验证覆盖的关键风险点：
- 手动词**落盘隔离**（读 `daily_log.json` + 全新 store 重载，而非仅断言内存计数）；
- 守卫命中时 `_word_manual` **不被污染**（否则下一个自动词会被误判为手动、从而泄漏配额）；
- 自动 / 手动交错序列的**精确计数**（证明「计数只受自动流程推进」而非「完全不计」）；
- 手动词的真实帧循环超时路径（`_on_frame_tick`）不写日志；
- 间隔上下界确实拓宽（500 次采样 `max > 500`，证明不是仅改下界）。

## 7. 被本变更覆盖的既有文档描述

以下历史文档中的相关描述已被本文件取代，阅读时以本文件为准：

| 文档 | 位置 | 原描述 |
| --- | --- | --- |
| `docs/params-japanese-learning.md` | §3 出现节奏参数 | `25.0` / `50.0`，区间 `[25, 50]` —— **已就地更新为 `30.0` / `600.0`** |
| `docs/prd-japanese-learning.md` | JP-13 | 「建议 25~50s」—— **已就地标注现行 30~600s** |
| `docs/design-japanese-learning.md` | §8.4 互斥 | 「按 25~50s 重新排期」—— **已就地更新为 30~600s** |
| `docs/prd-japanese-config.md` | 「立即显示」触发说明 / AC 序列图 / T02 验收点 | 「绕过随机 25~50s 排期」「保留上限/全掌握守卫」「shown_today +1」—— **已就地上游标注，配额相关语义以本文件为准** |
| `docs/design-japanese-config.md` | §A4.2 时序图、T02 说明与验收点 | 守卫列表含「上限/全掌握」、「shown_today+1」—— **配额相关语义以本文件为准** |
