# 日语学习功能参数总表

> 覆盖范围：桌面宠物「日语学习」模块（JP-01 ~ JP-19）。
> 参数唯一来源（Single Source of Truth）为 `src/desktop_pet/core/constants.py`，配置项另落 `core/config.py` 的 `AppConfig`。
> 版本对应：`develop`（2026-09-13 交互升级后）。整理日期 2026-09-13。

---

## ⚡ 交互升级（JP-17/18/19，2026-09-13）

在学习泡泡下方新增「记住了 / 新单词」按钮，显示时长与每日数量可调：

| 参数名 | 类型 | 默认值 | 取值范围 | 作用说明 | 必填 |
| --- | --- | --- | --- | --- | --- |
| `jp_bubble_duration_s`（配置） | `float` | `30.0` | `[5, 120]`（越界钳制） | 单词泡泡显示时长（秒），超时无操作自动消失。托盘「显示时长」可选 10/30/60/120 秒。 | 否 |
| `jp_daily_limit`（配置） | `int` | `15` | `[1, 500]`（越界钳制） | 每日展示单词配额（按**去重**词条计）。托盘「每日单词数」可选 5/10/15/20/50。 | 否 |
| `JP_NEW_WORD_WEIGHT` | `float` | `3.0` | `> 1` | 生词本内词条（标过「新单词」）的抽取权重倍数，其余词条权重 1.0。 | 是 |
| `JP_BUBBLE_DURATION_MIN/MAX_S` | `float` | `5.0 / 120.0` | min < max | 泡泡时长钳制边界。 | 是 |
| `JP_DAILY_LIMIT_MIN/MAX` | `int` | `1 / 500` | min < max | 每日配额钳制边界。 | 是 |
| `JP_DURATION_CHOICES_S` | `tuple` | `(10,30,60,120)` | — | 托盘时长档位。 | 是 |
| `JP_DAILY_CHOICES` | `tuple` | `(5,10,15,20,50)` | — | 托盘配额档位。 | 是 |
| `JP_BUBBLE_BTN_W/H/GAP` | `float` | `92 / 26 / 10` | `> 0` | 按钮宽/高/间距（逻辑像素）。 | 是 |
| `JP_STATE_FILE_NAME` | `str` | `"jp_state.json"` | — | 学习进度文件名（`%APPDATA%\desktop-pet\`）。 | 是 |
| `JP_STATE_VERSION` | `int` | `1` | — | 进度文件 schema 版本。 | 是 |

**新状态文件 `jp_state.json` 字段**：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `date` | `str` | 进度归属日（`YYYY-MM-DD`，本地自然日；跨天自动清零当日进度，`learned_ids` 保留） |
| `shown_ids` | `list[str]` | 当日已展示的词条 id（去重，用于配额与「全部记住」判定） |
| `learned_ids` | `list[str]` | 已标记「记住了」的词条 id，**跨天永久保留，永不复现** |

**升级后判定链**（`_show_word_bubble`）：

1. `bubble_enabled = false` → 不展示。
2. 睡觉态（`Mood.SLEEP`）→ 不展示。
3. 跨天检测：归属日 ≠ 今天 → 当日进度清零（learned 保留）。
4. 每日配额已用完（`len(shown_ids) >= jp_daily_limit`）**或**当天展示过的词已全部「记住了」→ 今日停显，托盘提示一次。
5. 距上次气泡 < `BUBBLE_MIN_GAP_S` → 本轮跳过。
6. 加权抽取：排除 `learned_ids`；生词本内词条权重 ×3；不与上一次展示重复。
7. 展示时长 = `jp_bubble_duration_s`（不再随机 2~4s）。

**按钮交互**：泡泡单词模式窗口切换为可交互；「记住了」→ `learned_ids` 永久排除 + 通知；「新单词」→ 入生词本（按 id 去重）+ 加权；超时无操作 → 无任何标记，该词仍可再次出现。

> ⚠️ 行为说明：按需求原文，「当天展示过的单词全部标记记住了」会**立即停止当日展示**（即使每日配额未用完）。若希望改为「继续引入新词直到配额用完」，把 `controller._jp_daily_stopped()` 中 `or self._jp_all_learned_today()` 删除即可。

---

## 目录

1. [模块总览](#1-模块总览)
2. [A. 配置参数（`AppConfig`，持久化到 `config.json`）](#2-a-配置参数)
3. [B. 出现节奏参数（单词展示定时）](#3-b-出现节奏参数)
4. [C. 学习泡泡排版参数](#4-c-学习泡泡排版参数)
5. [D. 词库与生词本文件参数](#5-d-词库与生词本文件参数)
6. [E. 词条 / 生词记录字段](#6-e-词条与生词记录字段)
7. [F. 生词本窗口尺寸参数](#7-f-生词本窗口尺寸参数)
8. [参数依赖关系](#8-参数依赖关系)
9. [使用注意事项](#9-使用注意事项)

---

## 1. 模块总览

日语学习功能横跨三层，参数分属 6 个功能子模块：

| 子模块 | 关键参数载体 | 所在文件 |
| --- | --- | --- |
| 配置（开关 / 难度） | `AppConfig.jp_enabled`、`jp_level` | `core/config.py` |
| 单词出现节奏 | `JP_WORD_*_INTERVAL_S` | `core/constants.py` |
| 学习泡泡排版 | `JP_BUBBLE_*`、`BUBBLE_LINE_SPACING` | `core/constants.py` |
| 词库 / 生词本文件 | `WORD_BANK_*`、`VOCAB_*` | `core/constants.py` |
| 词条 / 生词记录字段 | `VocabEntry`、`VocabItem` 必填字段 | `core/vocabulary.py`、`core/vocab_store.py` |
| 生词本窗口尺寸 | `VOCAB_WINDOW_W/H` | `core/constants.py` |

---

## 2. A. 配置参数

来源 `AppConfig`，写入 `%APPDATA%\desktop-pet\config.json`。类型为 JSON 可序列化类型。

| 参数名 | 类型 | 默认值 | 取值范围 | 作用说明 | 必填 |
| --- | --- | --- | --- | --- | --- |
| `jp_enabled` | `bool` | `false` | `true` / `false` | 日语学习总开关（JP-02）。开启后按节奏弹出单词泡泡；关闭后立即停止排期。 | 否（缺省回落 `false`） |
| `jp_level` | `string` | `"N5"` | `"N5"` `"N4"` `"N3"` `"N2"` `"N1"` | 当前展示难度等级（JP-06）。经 `_coerce_level` 收敛，非法值回落 `"N5"`。 | 否（缺省回落 `"N5"`） |

**依赖说明**：`jp_level` 只在 `jp_enabled = true` 时产生实际效果（见 §8）。

---

## 3. B. 出现节奏参数

来源 `core/constants.py`。控制单词泡泡的弹出时机。

| 参数名 | 类型 | 默认值 | 取值范围 | 作用说明 | 必填 |
| --- | --- | --- | --- | --- | --- |
| `JP_WORD_MIN_INTERVAL_S` | `float` | `25.0` | `> 0`（推荐 ≥ `BUBBLE_MIN_GAP_S`） | 相邻两次单词展示的最小随机间隔（秒）。 | 是（常量） |
| `JP_WORD_MAX_INTERVAL_S` | `float` | `50.0` | `≥ JP_WORD_MIN_INTERVAL_S` | 相邻两次单词展示的最大随机间隔（秒）。 | 是（常量） |

> 实际间隔由 `motion.random_interval(lo, hi)` 在闭区间 `[25, 50]` 秒内均匀随机。
> `hi <= lo` 时退化返回 `lo`（见 `core/motion.py`）。

---

## 4. C. 学习泡泡排版参数

来源 `core/constants.py`。控制学习泡泡四行文本的字号、宽度、字体与行距。

| 参数名 | 类型 | 默认值 | 取值范围 | 作用说明 | 必填 |
| --- | --- | --- | --- | --- | --- |
| `JP_BUBBLE_WORD_FONT_SIZE` | `int` | `16` | `> 0` | 日语单词行字号（加粗）。 | 是 |
| `JP_BUBBLE_KANA_FONT_SIZE` | `int` | `12` | `> 0` | 假名读音行字号。 | 是 |
| `JP_BUBBLE_TRANSLATION_FONT_SIZE` | `int` | `11` | `> 0` | 中文翻译行字号。 | 是 |
| `JP_BUBBLE_MEANING_FONT_SIZE` | `int` | `9` | `> 0` | 中文释义行字号（最淡）。 | 是 |
| `JP_BUBBLE_MAX_WIDTH` | `float` | `240.0` | `> 0` | 学习泡泡固定内容宽度（逻辑像素）。保证「测量换行宽 == 绘制换行宽」。 | 是 |
| `JP_BUBBLE_FONT_FAMILY` | `str` | `"Microsoft YaHei"` | 系统已安装字体名 | 学习泡泡四行统一字体。 | 是 |
| `BUBBLE_LINE_SPACING` | `float` | `3.0` | `≥ 0` | 多行泡泡行距（逻辑像素，历史命名故无 `JP_` 前缀）。 | 是 |

> 字号递减关系：单词 16 > 假名 12 > 翻译 11 > 释义 9。颜色见 `COLORS` 的 `bubble_text` / `bubble_sub_text` / `bubble_faint_text`。

---

## 5. D. 词库与生词本文件参数

来源 `core/constants.py`，由 `core/paths.py` 与 `core/vocab_store.py` 组合定位。

| 参数名 | 类型 | 默认值 | 取值范围 | 作用说明 | 必填 |
| --- | --- | --- | --- | --- | --- |
| `WORD_BANK_DIR_NAME` | `str` | `"data"` | 合法目录名 | 随包数据目录名（`.../desktop_pet/data`）。 | 是 |
| `WORD_BANK_FILE_NAME` | `str` | `"jlpt_words.json"` | 合法文件名 | 内置 JLPT 词库文件名。 | 是 |
| `WORD_BANK_VERSION` | `int` | `1` | `≥ 0` | 词库 JSON 顶层 `version` 期望值（当前仅记录，未强制校验）。 | 是 |
| `VOCAB_FILE_NAME` | `str` | `"vocabulary.json"` | 合法文件名 | 生词本文件名。 | 是 |
| `VOCAB_VERSION` | `int` | `1` | `≥ 0` | 生词本 JSON 顶层 `version` 写入值。 | 是 |

**路径解析**（`core/paths.py`）：

| 路径 | 源码运行 | PyInstaller 冻结运行 |
| --- | --- | --- |
| 词库 | `<repo>/src/desktop_pet/data/jlpt_words.json` | `sys._MEIPASS/desktop_pet/data/jlpt_words.json` |
| 生词本 | `%APPDATA%\desktop-pet\vocabulary.json`（`APPDATA` 缺失回落 `~`） | 同左（用户目录，非解包目录） |

---

## 6. E. 词条与生词记录字段

### 6.1 词库词条 `VocabEntry`（`core/vocabulary.py`）

| 字段 | 类型 | 默认值 | 取值范围 | 作用说明 | 必填 |
| --- | --- | --- | --- | --- | --- |
| `id` | `str` | 无 | 非空，格式 `n<级>-<四位序号>`，全局唯一 | 词条唯一标识，去重键。 | 是 |
| `level` | `str` | 无 | `"N5".."N1"`（必须 `∈ JP_LEVELS`） | JLPT 难度等级。 | 是 |
| `word` | `str` | 无 | 非空 | 日语单词表记（汉字 / 假名 / 片假名）。 | 是 |
| `kana` | `str` | 无 | 非空，全平假名（可含长音符 `ー`） | 假名读音。 | 是 |
| `translation` | `str` | 无 | 非空 | 简短中文对应词。 | 是 |
| `meaning` | `str` | 无 | 非空 | 中文词性 / 用法说明。 | 是 |
| `romaji` | `str` | `""` | 任意字符串 | 罗马音，P2 预留，存而不显。 | 否 |

### 6.2 生词记录 `VocabItem`（`core/vocab_store.py`）

| 字段 | 类型 | 默认值 | 取值范围 | 作用说明 | 必填 |
| --- | --- | --- | --- | --- | --- |
| `id` | `str` | 无 | 非空 | 冗余快照自 `VocabEntry.id`，去重键。 | 是 |
| `level` | `str` | 无 | `"N5".."N1"` | 冗余快照。 | 是 |
| `word` | `str` | 无 | 非空 | 冗余快照。 | 是 |
| `kana` | `str` | 无 | 非空 | 冗余快照。 | 是 |
| `translation` | `str` | 无 | 非空 | 冗余快照。 | 是 |
| `meaning` | `str` | 无 | 非空 | 冗余快照。 | 是 |
| `added_at` | `str` | 无 | ISO8601 UTC（如 `2026-09-13T03:53:59Z`） | 加入时间，由 `app` 层注入，`core` 不解析。 | 是 |

> `VocabItem` 是对 `VocabEntry` 的冗余快照，另加 `added_at` 时间戳，用于离线展示。

---

## 7. F. 生词本窗口尺寸参数

来源 `core/constants.py`。

| 参数名 | 类型 | 默认值 | 取值范围 | 作用说明 | 必填 |
| --- | --- | --- | --- | --- | --- |
| `VOCAB_WINDOW_W` | `int` | `440` | `> 0` | 生词本窗口初始宽度（逻辑像素）。 | 是 |
| `VOCAB_WINDOW_H` | `int` | `360` | `> 0` | 生词本窗口初始高度（逻辑像素）。 | 是 |

---

## 8. 参数依赖关系

```
jp_enabled ──┬─→ 决定是否调用 _schedule_next_word / _show_word_bubble
             └─→ false 时：_next_word_ts = +∞，不再弹单词；「难度」「记住当前单词」菜单置灰

jp_level ────┐
             ├─→ 写入 config.json（持久化）
             ├─→ WordSampler.set_level() 切换抽取池
             └─→ 依赖 jp_enabled = true 才真正驱动展示

jp_enabled ──┬─→ true 且 bubble_enabled = false → 托盘通知 JP_NOTIFY_NEED_BUBBLE
bubble_enabled─→ _show_word_bubble 前置拦截：false 直接 return

JP_WORD_MIN/MAX_INTERVAL_S ─→ random_interval() 产生活跃间隔，再经帧循环判定 now >= _next_word_ts

JP_BUBBLE_* / BUBBLE_LINE_SPACING ─→ ui.bubble 四行排版（测量与绘制共用同一 wrap 宽）

WORD_BANK_* ─→ paths.word_bank_path() 定位 → WordBank.load() 容错加载
VOCAB_FILE_NAME + CONFIG_DIR_NAME ─→ VocabStore.default_path() 定位生词本

jp_level ─→ entries_for(level) 过滤词库；level 不在 JP_LEVELS 时返回空列表
```

**核心拦截链**（决定「单词是否真弹出来」的先后顺序，`app/controller.py`）：

1. `jp_enabled = false` → 不排期。
2. 词库为空 → 不排期，`_next_word_ts = +∞`。
3. `bubble_enabled = false` → `_show_word_bubble` 直接返回。
4. 情绪为 `Mood.SLEEP` → 返回（睡觉时不打扰）。
5. `now - _last_bubble_ts < BUBBLE_MIN_GAP_S` → 返回（与情绪气泡共用最小间隔）。
6. `WordSampler.next()` 返回 `None`（该级无词）→ 返回并告警一次。

---

## 9. 使用注意事项

1. **常量唯一来源**：所有阈值 / 字号 / 尺寸 / 文件名只允许定义在 `core/constants.py`，其余模块不得硬编码（有 `test_static_constraints.py` 守护）。改参数先改这里。

2. **`core/` 层零 Qt / 零 time 依赖**：`core/vocabulary.py`、`core/vocab_store.py`、`core/paths.py` 均不得 `import PySide6`，也不得调用 `time` / `datetime`。`added_at` 时间戳由 `app/controller._now_iso()` 生成后注入；生词本损坏备份时间戳改用 `os.stat().st_mtime` 规避 time 依赖。

3. **`kana` 全平假名约束**：词库 `kana` 必须全平假名（可含长音符 `ー`），不得含汉字 / 罗马字 / 空格。`data/README.md` 与自检脚本 `_check_wordbank.py` 均有校验，扩充词库后务必跑一遍。

4. **`id` 全局唯一且格式固定**：`n<级数字>-<四位序号>`，去重靠它。生词本「记住当前单词」按 `id` 去重，重复 id 会静默返回「已在生词本中」。

5. **逐条容错、静默丢弃**：词库 / 生词本加载时，任一必填字段非法（非 `str` / 空串 / `level` 越界）该条即被跳过（记 warning）。扩充词库若条数对不上，多半是存在非法记录被丢弃。

6. **生词本损坏不静默清空**：损坏文件会先 `os.replace` 备份为 `vocabulary.json.corrupt-<mtime秒>` 再以空列表启动；同秒多次损坏会追加 `-1`、`-2` 后缀，绝不覆盖旧备份。

7. **保存原子性**：`config.json` 与 `vocabulary.json` 均走「同目录 `mkstemp` + `flush/fsync` + `os.replace`」原子替换，避免半写损坏；保存失败仅记 warning，不崩溃。

8. **单词展示挂既有帧循环**：不新开 QTimer，节奏由帧循环里的 `now >= _next_word_ts` 判定。改帧率不会破坏节奏，但帧循环必须持续运行，否则单词永不弹出。

9. **与情绪气泡共用最小间隔**：`_last_bubble_ts` 为情绪气泡与单词泡泡共享，二者互斥，间隔小于 `BUBBLE_MIN_GAP_S`（3 秒）时后触发者被丢弃。

10. **睡觉态不弹单词**：`Mood.SLEEP` 下 `_show_word_bubble` 直接返回，属于刻意的防打扰设计。

11. **配置非法值自动回落**：`jp_level` 经 `_coerce_level` 收敛，`config.json` 里若出现 `"N99"` 等非法值会自动回落 `"N5"`；`jp_enabled` 经 `_coerce_bool` 解析（字符串仅接受 `true/1/yes/on` 与 `false/0/no/off`）。

12. **WordBank 的 `version` 未强制校验**：`WORD_BANK_VERSION = 1` 目前仅作 schema 记录，`WordBank.load` 不会因版本不符而拒绝加载。未来若做迁移需在 load 中显式比对。

---

## 附：相关文件索引

| 文件 | 职责 |
| --- | --- |
| `core/constants.py` | 全部日语常量（节奏 / 排版 / 文件 / 文案 / 窗口尺寸） |
| `core/config.py` | `AppConfig`（`jp_enabled`、`jp_level`）+ 容错读写 |
| `core/vocabulary.py` | `VocabEntry` / `WordBank` / `WordSampler`（洗牌非重复抽取） |
| `core/vocab_store.py` | `VocabItem` / `VocabStore`（原子写 + 损坏备份） |
| `core/paths.py` | 词库路径解析（源码 / 冻结双环境） |
| `app/controller.py` | 装配与业务判定（排期、展示、拦截链、4 槽） |
| `ui/bubble.py` | 学习泡泡四行排版渲染 |
| `ui/tray.py` | 托盘「日语学习」菜单组（只发信号） |
| `ui/vocab_window.py` | 生词本窗口（只展示 + 发信号） |
| `data/jlpt_words.json` | 内置词库（N5~N1 各 100 词，共 500 词） |
| `data/README.md` | 词库编写规范与自检说明 |
