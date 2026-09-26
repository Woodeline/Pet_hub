# 变更记录：情绪气泡触发机制调整（降低频率 + 键盘文案与触发方式对齐）

> 日期：2026-09-26
> 性质：行为变更（不新增配置项、不改持久化 schema、不改 UI 结构）
> 影响文件：`src/desktop_pet/core/constants.py`、`src/desktop_pet/app/controller.py`、`tests/`（新增 1 个测试文件 + 1 处常量表补登记）
>
> **后续变更**：同日又落地了「自定义台词拆两组 + 键盘关键字门控」（需求 C），
> 本文 §3 表格中「键盘专属文案的触发来源」一行已进一步增强；§7 的第一条边界已被消除。
> **同日下午重做**：20~60s 由「事件节流阀」升级为「递归排期 + 独立敲击窗」——
> 安静待机也会周期性说话、稳态打字也能看到敲击组（详见
> [`change-bubble-text-groups.md`](./change-bubble-text-groups.md) §10）。

---

## 1. 用户需求

1. 气泡显示改为 **20 秒 ~ 1 分钟**之间的随机间隔触发，降低整体显示频率；
2. 排查当前是否通过**监控键盘敲击**来触发显示，若是则与降低后的随机间隔**合理整合**，避免频繁弹出；
3. 与键盘敲击监控相关的气泡文案，需**包含键盘关键字**，使文案与触发方式匹配，且**仅在敲击键盘时**才被触发；
4. **保留**鼠标移动到宠物上立即显示一条文案的行为。

## 2. 排查结论（改前机制）

**确认：改前确实通过监控键盘敲击触发气泡。** 完整触发链路共 3 条：

| 来源 | 链路 | 使用的文案键 |
| --- | --- | --- |
| **键盘敲击** | `KeyboardListener` → `KeystrokeBridge.keystroke` → `_on_keystroke` → `KeystrokeAggregator` → `MoodStateMachine.on_keystroke` → 瞬时表情 → `_show_bubble_for` | `FOCUS` / `EXCITED` / `SURPRISED` / `SULKY` |
| 帧循环（自动） | `_on_frame_tick` → `MoodStateMachine.update` 状态迁移 / 休息态随机呵欠 | `Mood.IDLE` / `REST` / `SLEEP` / `Expression.YAWN` |
| 鼠标 | `_on_gesture`（CLICK 点击 / HOVER 悬停 1 秒） | `Expression.HAPPY` |

**频率过高的根因**：节流只有 `BUBBLE_MIN_GAP_S = 3.0` 秒一个硬下限，而状态机在**每次**高频敲击时都会返回 `Expression.FOCUS`（持续高频 5 秒后升级 `EXCITED`），因此**打字期间几乎每 3 秒就弹一条**。

**一个有利的既有事实**：`controller._BUBBLE_EXPRESSIONS`（恰好等于上表四个键盘键）已经把「键盘专属文案」与「鼠标 / 自动路径」天然隔离 —— 鼠标只传 `HAPPY`，帧循环只传 `Mood.*`。本次据此把该集合提升为常量中的唯一来源并加守护。

## 3. 目标行为（验收基线）

| 场景 | 改前 | 改后 |
| --- | --- | --- |
| 打字（高频敲击）过程中的气泡 | 约每 3 秒一条 | 每 **20~60 秒**最多一条（随机窗口） |
| 键盘专属文案（`FOCUS`/`EXCITED`/`SURPRISED`/`SULKY`） | 「一起加油！💪」「哇！好快好快！」等，**不含**键盘语义 | 全部含键盘关键字（如「键盘敲得真快！」「这手速太快了！」「键盘一响我就醒了~」） |
| 键盘专属文案的触发来源 | 仅敲击路径（但无守护） | 仅敲击路径，且有**源码级 + 键集级**守护 |
| 鼠标悬停（停留 1s） | 立即显示 `HAPPY` | **不变**（`immediate=True` 绕过 20~60s 窗口） |
| 鼠标点击 | 立即显示 `HAPPY` | `immediate=True`，同上 |
| 帧循环状态迁移 / 呵欠 | 受 3s 硬下限 | 受 20~60s 随机窗口 |
| 单词泡泡（日语「立即显示」/自动排期） | 与情绪气泡共享 `_last_bubble_ts` 互斥 | **不变**（仍只受 3s 硬下限，不纳入 20~60s 窗口） |

## 4. 设计要点

`_show_bubble_for(key, now, *, immediate=False)` 的三层守卫，按顺序判定：

1. **开关 / 互斥**：气泡总开关关闭、或单词泡泡正在展示 → 直接返回（既有逻辑不变）。
2. **硬下限**（**所有来源**）：`now - _last_bubble_ts < BUBBLE_MIN_GAP_S(3s)` → 返回。防止敲击与状态迁移同帧叠加、或鼠标反复进出造成连弹。
3. **自动节奏窗口**（**非 immediate 来源**）：`now < _next_bubble_ts` → 返回。窗口长度每次展示后重排为 `random_interval(20, 60)`。

**`immediate=True` 的语义**：表示「用户主动的鼠标交互」，跳过第 3 层以保留「鼠标移上去立即显示一条」；但**不跳过**第 2 层（3 秒硬下限），因此鼠标疯狂进出也不会连弹。`immediate` 展示后同样重排 `_next_bubble_ts`，避免「刚摸一下就被自动气泡紧跟糊一条」。

**键盘文案与触发方式的强绑定**：`KEYBOARD_BUBBLE_EXPRESSIONS` 是唯一来源（controller 不再各存一份），敲击路径只可能产出这 4 个键，鼠标路径只产出 `HAPPY`，帧循环只产出 `Mood.*`。

## 5. 实现落点

### `src/desktop_pet/core/constants.py`
- 新增 `BUBBLE_MIN_INTERVAL_S = 20.0` / `BUBBLE_MAX_INTERVAL_S = 60.0`（置于气泡时序区）。
- 新增 `KEYBOARD_BUBBLE_EXPRESSIONS`（键盘专属文案键集，唯一来源）与 `BUBBLE_KEYBOARD_KEYWORDS`（守护用关键字表：键盘 / 敲 / 打字 / 码字 / 手速 / 按键）。
- 改写 `BUBBLE_TEXTS` 中 `FOCUS` / `EXCITED` / `SURPRISED` / `SULKY` 的文案，使其全部命中键盘关键字；同步改写 `BUBBLE_TEXT_PACKS` 中 `energy`（FOCUS/EXCITED）与 `gentle`（FOCUS/SULKY）的对应文案。
- `HAPPY` 文案（鼠标专属）保持无键盘关键字；`Mood.*` 文案不变。
- `__all__` 同步登记 4 个新符号。

### `src/desktop_pet/app/controller.py`
- 新增运行时状态 `self._next_bubble_ts: float`（下一次自动展示允许时刻，初始 `-inf` 使启动后首次立即可用）。
- `_show_bubble_for` 增加 `immediate` 关键字参数与上述三层守卫；展示后统一重排窗口。
- `_on_keystroke`：改用 `C.KEYBOARD_BUBBLE_EXPRESSIONS`（引用唯一来源）。
- `_on_gesture`：CLICK / HOVER 改为 `immediate=True`。
- 删除模块私有 `_BUBBLE_EXPRESSIONS`（消除重复定义）。

### 测试
- 新增 `tests/test_bubble_trigger_rhythm.py`（13 用例）：常量字面量与 `__all__`；20~60s 窗口大样本采样（含上界可达 1 分钟、下界接近 20 秒）；自动来源窗口内被节流 / 窗口过后恢复；`immediate` 绕过窗口；`immediate` 仍受硬下限；**模拟 60 秒连续高频打字，气泡条数 ≤ 4**；键盘文案关键字守护（默认包 + 全部预设包）；`HAPPY` 文案不含键盘关键字；键盘键集与鼠标 / Mood 键隔离；源码级断言（手势路径只用 HAPPY + `immediate`、敲击路径引用共享键集）。
- `tests/test_static_constraints.py`：常量表补登记 `BUBBLE_MIN_INTERVAL_S` / `BUBBLE_MAX_INTERVAL_S` 字面量。

## 6. 验证结论

| 项目 | 结果 |
| --- | --- |
| 全量回归 | `tests/` 共 1229 用例，EXIT=0，0 失败 / 0 错误 |
| 变异验证 | **4/4 全部被测试捕获**：① 去掉 20~60s 窗口节流 ② `BUBBLE_MIN_INTERVAL_S` 回退 3.0 ③ 键盘文案去掉键盘关键字 ④ 手势路径去掉 `immediate=True` —— 均 FAIL，且还原后 md5 与备份逐字节一致 |
| 还原方式 | `cp` 备份 + `try/finally` 兜底（未执行任何 git 写操作，未删除任何文件） |

## 7. 已知边界

- ~~**自定义台词池**（托盘「气泡文案…」）优先级最高且对所有情绪键统一生效。用户填入自定义台词后，「键盘文案含键盘关键字」这一约束不再由系统保证（守护测试只覆盖内置默认包与预设包）。~~
  **⚠️ 本边界已于同日被后续变更消除**：自定义池已拆为「自动触发组」与「敲击键盘组」两组，且自动侧对**任何**来源（自定义自动组 / 预设台词包 / 内置文案表）都统一剔除含键盘关键字的条目。详见 [`change-bubble-text-groups.md`](./change-bubble-text-groups.md)。
- 鼠标悬停的触发条件是**停留 1 秒**（`HOVER_TRIGGER_S`，既有行为），不是鼠标进入的瞬间；本次未改动该阈值。
- 单词泡泡（日语模块）不纳入 20~60s 窗口，仍只与情绪气泡共享 `BUBBLE_MIN_GAP_S` 互斥，避免影响日语自动排期节奏。

## 8. 被本变更覆盖的既有文档描述

| 文档 | 位置 | 说明 |
| --- | --- | --- |
| `docs/prd.md` | FR-30 | 已就地补充 20~60s 随机窗口与鼠标 `immediate` 语义 |
| `docs/architecture.md` | FR-30 行、时间阈值表 | 已就地补充节奏常量 `BUBBLE_MIN_INTERVAL_S/MAX_INTERVAL_S=20/60` |
| `docs/prd-japanese-learning.md` | 「不改动现有情绪气泡的文案与触发逻辑」 | 该条仅约束日语模块自身改动范围；已加注说明情绪气泡其后已单独调整 |
| `docs/prd-japanese-memory.md` | 「不改动既有情绪气泡文案与触发逻辑」 | 同上 |

## 9. 复现与回归入口

```bash
# 全量回归
cd desktop-pet
PYTHONPATH=src QT_QPA_PLATFORM=offscreen <venv-python> -m pytest tests/ -q

# 只跑本次节奏与文案守护
... -m pytest tests/test_bubble_trigger_rhythm.py -q

# 变异验证（一次一个变异，脚本自带 try/finally 兜底还原）
python ../_tmp_bubble_mutation/run_one.py <1|2|3|4>
```
