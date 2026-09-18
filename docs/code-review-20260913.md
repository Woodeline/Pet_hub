# desktop-pet 代码质量审查报告

> 审查日期：2026-09-13 · 分支：`develop@24fa130`（含未提交 JP-17/18/19 改动）
> 范围：`src/desktop_pet` 全部 20 个源文件（约 6800 行，含 tests 6771 行总计）+ 打包/配置
> 方法：全量人工精读 + AST 死代码扫描 + pytest 全量回归 + 符号引用交叉检索

---

## 一、总体结论

| 维度 | 评价 |
|------|------|
| 整体完成度 | **高**。FR-01~FR-39 主链路（键盘监听→状态机→动画→气泡→托盘→持久化→自启）+ 日语学习（词库/加权抽取/生词本/每日配额/进度持久化）全部落地 |
| 测试基线 | **388 项全部通过**（本次实测 rc=0），core 层零 Qt/零 time 依赖有静态测试守护 |
| 架构纪律 | **优秀**。三层依赖单向、常量唯一来源、原子写盘、边界容错（永不冒泡崩溃）执行得很到位 |
| 本次发现 | **无 P1 级缺陷**；P2 级 6 项（重复逻辑、封装泄漏、死代码），P3 级 8 项 |

代码库整体质量明显高于同规模业余项目：容错路径覆盖完整（每个 JSON 存储都有 corrupt-backup + 原子替换）、注释解释"为什么"而非"做了什么"、时间统一注入保证可测性。以下问题多为卫生类，不影响当前运行。

---

## 二、P1 —— 高危（无）

未发现会导致崩溃、数据丢失或功能明显错误的缺陷。特别核实过的高风险点均正确：

- ✅ 跨线程键盘回调只发信号不碰 widget（`keyboard_listener.py`），线程模型正确；
- ✅ 三个 JSON 存储（config/vocab/jp_state）全部走 `mkstemp + fsync + os.replace` 原子写，损坏先备份再降级；
- ✅ `WordSampler` 排除已记住 → 加权 → 去连续重复的约束链完整，池空正确返回 None 并停止排期；
- ✅ 每日配额按去重 `shown_ids` 计数，跨天 rollover 保留 learned；
- ✅ 敲击瞬时通道绕过全局平滑的绝对赋值（`pet_model._apply_keystroke`）无重复叠加路径。

---

## 三、P2 —— 中等（建议修复）

### P2-1 「记住了」与「记住当前单词」两段近乎复制粘贴的逻辑
- 位置：`app/controller.py:620-638`（`_on_word_new`）vs `app/controller.py:640-659`（`_on_jp_remember`）
- 问题：除"jp_enabled 前置检查"与"current_word 为空时的提示"外，核心 12 行（add → 通知 → 刷新窗口 → 同步加权集）完全相同。将来改通知文案/刷新逻辑必须改两处，漏一处即行为分叉。
- 建议：提取 `_add_to_vocab(self, entry: VocabEntry) -> bool` 私有方法，两个槽各自处理前置判断后调用。
- 同类问题：`_notify_jp_startup_state`（`controller.py:467-478`）与 `_on_jp_toggled` 的开启分支（`controller.py:546-552`）重复了「气泡未开 / 词库为空 / 今日已停」三段判断，可一并提取。

### P2-2 `VocabStore.items()` 返回内部可变列表引用
- 位置：`core/vocab_store.py:201-204`
- 问题：`return self._items` 未复制，外部可直接增删改内部状态绕过 `add/remove/clear` 的去重与落盘逻辑。当前调用方只读+复制，无实害，但这是封装缺口，测试或后续功能很容易踩中。
- 建议：`return list(self._items)`（与 `JpStateStore.shown_ids()` 的做法保持一致——同类里它就做对了）。

### P2-3 `WORD_BANK_VERSION` 定义了但词库加载从不校验
- 位置：`core/constants.py:366`；`core/vocabulary.py:109-161`（`WordBank.load`）
- 问题：词库 JSON 若未来改结构，旧文件会被静默按新逻辑解析，`from_dict` 逐条跳过可能导致"整个词库静默清空只剩一条 warning"。定义版本常量却不用，等于没有版本契约。
- 建议：`WordBank.load` 读取根节点 `version` 字段，与 `WORD_BANK_VERSION` 不一致时记 warning（暂不拒载），为未来迁移留挂钩。

### P2-4 死代码：`KeystrokeOutcome` 枚举、`BUBBLE_MAX_WIDTH_PX` 别名、`PetModel._target`
- `core/constants.py:52-58` `KeystrokeOutcome`：全仓库（src+tests）零引用。高频判定实际走 `KeystrokeResult.high_frequency` 布尔。删除（连同 `__all__` 导出）。
- `core/constants.py:339` `BUBBLE_MAX_WIDTH_PX = BUBBLE_MAX_WIDTH`：零引用的纯别名，删除。
- `core/pet_model.py:82,189` `self._target`：每帧赋值、从不读取。删除后还省去每帧一次死写入。
- 建议：三条均可直接删；项目约定"改常量要过 `test_static_constraints`"，删除前确认无静态断言引用即可。

### P2-5 跨天 rollover 时 `record_shown/record_learned` 双重落盘
- 位置：`core/jp_state.py:154-163,165-173`
- 问题：`record_shown` 先调 `rollover(today)`（内部已 `save()` 一次），随后自己又 `save()` 一次。跨天首次记录单词时同一份数据写盘两遍。无害但浪费且语义含混。
- 建议：给 `rollover` 加 `save: bool = True` 参数，`record_*` 内部传 `save=False`，最后统一 save 一次。

### P2-6 `_load_japanese` 重复构造 `VocabStore`
- 位置：`app/controller.py:101`（`__init__`）vs `app/controller.py:408-413`
- 问题：`__init__` 已创建一次，`_load_japanese` 再 new 一个覆盖。首实例白建；且异常分支里 `VocabStore(VocabStore.default_path())` 出现两次的嵌套构造，可读性差。
- 建议：`__init__` 只留空声明（或全部移到 `_load_japanese`），保留一处构造。

---

## 四、P3 —— 轻微（择机清理）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P3-1 | `core/jp_state.py:25` | `from typing import Any` 未使用 | 删除 |
| P3-2 | `core/pet_model.py:17` | `Final` 未使用 | 删除 |
| P3-3 | `core/event_aggregator.py:30,35,99,104` | `rate_per_sec` 字段、`is_high_frequency()`、`burst_count(now)` 生产代码零消费（仅测试用） | 保留可（测试价值），但在 docstring 标注"仅供诊断" |
| P3-4 | `app/keyboard_listener.py:100` | `stop()` 在从未启动时也打日志"全局键盘监听已停止"，日志有误导 | 移入 `if listener is not None` 分支 |
| P3-5 | `core/config.py:255` | docstring 语病"永不为抛异常设计"（应为"永不以抛异常为设计目标"） | 顺手改 |
| P3-6 | `core/config.py:129` | `AppConfig.version` 字段预留但无任何迁移逻辑 | 可接受；未来 schema v2 时补 `_migrate` |
| P3-7 | `core/vocabulary.py:235,240` | `set_learned_ids(ids)` / `set_boost_ids(ids)` 缺参数类型注解，违反项目"函数一律带类型注解"规范 | 补 `ids: Iterable[str]` |
| P3-8 | `ui/pet_window.py:151-155` | 从光晕态（SLEEPING/EXCITED）退出瞬间 `glow_alpha` 跌破 0.01，脏区收窄后窗外圈可能残留极淡光晕像素（alpha≈0.005，肉眼不可见） | 如在意，可在 `pet_rect` 收窄前做一次全窗 `update()` 的状态切换钩子 |

另：`core/motion.py` 的 `ease_out_back`（:88）与 `interpolate_pose`（:117）仅被测试消费，属"工具箱函数"，可保留（缓存动效库属性），不算死代码。

---

## 五、优化建议（非缺陷）

1. **每帧 `pose_for_expression` 重建 dict + PetPose**（`core/pet_model.py:180`）：8 种表情的模板可按枚举预构建缓存（表情只有 8 种，命中率高），每帧省 2 次 dict 复制 + 1 次构造。收益小但实现简单。
2. **`_apply_filter` 全量重建表格**（`ui/vocab_window.py:151-159`）：生词本规模小（<500 条），当前做法可接受；若未来支持导入大词表，改 `setSortingEnabled` + 增量更新。
3. **建议引入 ruff 并入 dev 依赖**：本次靠手写 AST 扫描抓出 2 个未用 import、3 处死代码；`pyproject.toml` 的 dev 组加 `ruff` 一行即可让 CI/本地一条命令守住这类问题。
4. **JP-17/18/19 改动尚未提交**：当前 10 个修改文件 + 3 个新文件（`jp_state.py`、`test_jp_state.py`、`docs/params-japanese-learning.md`）全部悬在工作区。388 测试全绿正是提交的好时机，建议尽快 commit 到 `develop`（注意本机 git 红线：提交后 `git log -3` 复核）。

---

## 六、完成度清单

| 功能域 | 状态 |
|--------|------|
| 四态情绪状态机 + 防抖 + 唤醒委屈 | ✅ 完整，测试覆盖 |
| 敲击聚合（300ms/3次高频）+ 兴奋/惊讶/呵欠 | ✅ 完整 |
| 敲键盘动画（落指/抬腕/屈指/键帽下沉/拖拽抑制） | ✅ 完整，幅度有自证测试 |
| 矢量渲染（彩虹渐变团子猫/透视键盘/鼠标/尾巴/ZZZ） | ✅ 完整，零外部素材 |
| 脏区刷新 + 光晕整窗回退 | ✅ 完整 |
| 气泡（文本模式/学习模式/淡入淡出/翻转/穿透切换） | ✅ 完整（穿透切换含 Windows 平台实测补丁链） |
| 托盘（菜单/通知/缩放/自启注册表/生词本入口） | ✅ 完整 |
| 日语学习（词库/加权/生词本/每日配额/进度跨天） | ✅ 完整（JP-17/18/19 未提交） |
| 配置持久化 + 日志轮转 + PyInstaller 打包 | ✅ 完整 |

**结论**：项目处于"功能完备、测试全绿、只剩卫生清理"状态。建议按 P2-1~P2-6 做一轮小重构 + 提交未入库改动，即可作为 1.0.0 收口。
