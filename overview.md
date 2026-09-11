# desktop-pet 交付总览

> 一只常驻 Windows 桌面、会「陪你敲键盘」的治愈系程序化矢量猫咪
> 交付日期：2026-09-10 · 流程：标准 SOP（产品经理 → 架构师 → 工程师 → QA）

---

## TL;DR

敲键盘时猫会同步做双爪敲击动作；空闲/专注/休息/睡觉四态自动切换并给出 8 种表情反馈；无边框透明、始终置顶、可拖动、可收纳到系统托盘。**零外部图片素材**（猫咪全部由 QPainter 矢量绘制），源码 3865 行，**248 个自动化测试全部通过**。

---

## 交付概览

| 项 | 内容 |
|---|---|
| 交付状态 | ✅ 完成并通过独立验证 |
| 技术栈 | Python 3.13 + PySide6（Qt for Python）+ pynput |
| 源码规模 | 17 个文件 / 3865 行 |
| 测试规模 | 12 个文件 / 2502 行 / **248 用例全绿** |
| 内存实测 | **59 MB**（目标 < 120MB，余量充足） |
| 已知缺陷 | 0 个 |
| 待人工验收 | 9 类（见「需要你人工验收的部分」） |

---

## 需求覆盖（PRD 39 条 → 实现）

| 模块 | 覆盖需求 | 实现要点 |
|---|---|---|
| 键盘联动 | FR-01~04 | 全局钩子独立线程；跨线程 Qt 信号桥；300ms/3 次判高频 |
| 情绪状态机 | FR-05~10 | 四态 Idle/Focus/Rest/Sleep；20s/120s/300s 阈值；5s 最小驻留防抖；敲击反馈优先级最高 |
| 表情与动作 | FR-11~14 | 8 种表情；睫毛/耳朵/尾巴/腮红独立可驱动；随机眨眼、呼吸起伏 |
| 窗口能力 | FR-15~21 | `FramelessWindowHint｜WindowStaysOnTopHint｜Tool` + `WA_TranslucentBackground`；5px 阈值区分点击与拖拽 |
| 系统托盘 | FR-22~26 | 最小化/恢复/暂停监听/缩放三档/开机自启/退出 |
| 交互反馈 | FR-27~30 | 点击弹跳、悬停抚摸（1s）、拖拽被拎起姿态、气泡对话 |
| 性能约束 | FR-31~35 | 30/15/8 FPS 动态降频；脏区局部刷新；内存 59MB |
| 配置持久化 | FR-36~39 | JSON + 逐字段容错 + 原子保存 |

---

## 关键决策与理由

1. **`core/` 层零 Qt 依赖**（硬性架构约束）
   状态机、敲击聚合、运动插值、姿态模型、配置读写全部做成纯 Python 模块，时间由调用方注入。
   → 收益：248 个测试中 231 个无需 GUI 即可运行，状态机与动画数学可被彻底验证。

2. **跨线程只留一个点**
   `KeystrokeBridge.keystroke = Signal(float)`；pynput 线程只 `emit` 时间戳，绝不触碰 UI。
   → 已验证槽函数确实在主线程执行（QueuedConnection 生效），监听线程 stop 后零残留。

3. **程序化矢量绘制而非图片素材**
   → 零素材依赖、体积最小、8 种表情靠参数驱动可无限扩展，且不存在素材与代码版本不一致的问题。

4. **姿态插值帧率无关**：采用 `t = 1 - exp(-k·dt)` 而非 `t = k`。
   → 已量化验证：冻结时钟下 30fps 与 60fps 的最终姿态差 < 1e-6。

5. **脏区局部刷新（FR-35）**
   由 `PetRenderer.body_bounds()` 计算猫咪真实包围盒，8 种表情中 6 种重绘区域收窄（如 160×180 → 127×164）；
   睡觉/兴奋态因光晕横向铺满整窗，**回退整窗**以避免裁掉光晕。

---

## 过程中发现并修正的 4 个真实问题

| # | 问题 | 发现者 | 处理 |
|---|---|---|---|
| 1 | 状态机以 `now=0` 初始化，导致启动首帧无输入时长被算成巨大值、**立刻跳进睡眠态** | 工程师自测 | 改为以 `time.monotonic()` 初始化 |
| 2 | **FR-35 脏区刷新未真正落地**（`pet_rect()` 返回整窗，等于每次全窗重绘） | QA 复核 | 新增 `body_bounds()` 真实计算包围盒；并**新增 9 个永久回归用例**防止将来裁剪 |
| 3 | 时钟倒退时过期按键样本不被剔除，`burst_count` 虚高（实测 3 次却报 4） | QA 复核 | 检测时间戳倒退 → 清空窗口重启；**同一毫秒内的连续敲击不误判** |
| 4 | 被误判为「死代码」的分支实为活路径 | 工程师**抗命并证伪** | 分支保留。反例：「休息态下点击/悬停猫咪会重置空闲计时器但状态仍为休息」，此后单次敲键即命中该分支（2 万步模糊测试命中 4895 次） |

> 第 4 项的说明：主理人曾判定 `mood_state_machine.py:236-239` 不可达并要求删除，工程师未照做而是先写脚本证明——结论是该分支真实可达。若按原判断删除，「点一下休息中的猫再敲键」会从「回到空闲」变成「卡在休息态」。

---

## 文件清单

### 源码 `src/desktop_pet/`（17 文件 / 3865 行）

| 文件 | 行数 | 职责 |
|---|---|---|
| `main.py` | 116 | 入口，QApplication 装配，日志轮转 |
| `core/constants.py` | 314 | 枚举 / 阈值 / 配色 / 文案**唯一来源** |
| `core/config.py` | 255 | 配置读写，逐字段容错 + 原子保存 |
| `core/mood_state_machine.py` | 382 | 四态情绪状态机 |
| `core/motion.py` | 284 | 缓动 / 帧率无关插值 / 屏幕钳制 |
| `core/pet_model.py` | 318 | 26 通道姿态模型 |
| `core/event_aggregator.py` | 114 | 敲击聚合与高频判定 |
| `ui/pet_renderer.py` | 546+ | QPainter 矢量猫咪 + 包围盒 + 托盘图标 |
| `ui/pet_window.py` | 248+ | 无边框透明置顶窗口 / 拖拽 / 帧循环 |
| `ui/bubble.py` | 240 | 气泡浮层（淡入淡出 + 顶部翻转） |
| `ui/tray.py` | 184 | 系统托盘 |
| `app/keyboard_listener.py` | 123 | pynput 守护线程 + 跨线程信号桥 |
| `app/controller.py` | 541 | 装配 / 接线 / 生命周期 |

### 文档
`docs/prd.md`（249 行，39 条需求）· `docs/architecture.md`（754 行）· `docs/class-diagram.mermaid` · `docs/sequence-diagram.mermaid` · `README.md`

### 测试 `tests/`（12 文件 / 2502 行 / 248 用例）
`test_mood_state_machine.py` · `test_motion.py` · `test_config.py` · `test_pet_model.py` · `test_event_aggregator.py` · `test_ui_smoke.py` · `test_cross_thread_bridge.py` · `test_static_constraints.py` · `test_memory_budget.py` · `test_dirty_rect_no_clip.py` · `conftest.py` · `manual_checklist.md`

---

## 如何运行

### 最简方式 —— 无需安装 Python（推荐）

双击 `dist\desktop-pet\desktop-pet.exe`，或双击项目根目录的 `run.bat`（自动挑选可用运行时）。
实测：进程正常存活，**内存 50.5 MB**。退出方式：右键猫咪 → 退出。

### 源码方式（需要 Python 3.13）

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd /d <本项目目录>
set PYTHONPATH=src
python -m desktop_pet.main
```

以可编辑模式安装后可直接用入口命令（开机自启依赖此方式）：

```bat
pip install -e .
desktop-pet
```

跑测试：`pytest -q`

### 打包（已产出，如需重做）

```bat
pip install pyinstaller
pyinstaller --noconfirm --windowed --name desktop-pet --paths src ^
    --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 ^
    src\desktop_pet\main.py
```

> 两个 `--hidden-import` 必须加：`pynput` 的后端模块是运行时动态导入的，PyInstaller 静态分析扫不到，
> 漏掉会导致打包后启动即静默崩溃。产物 `dist/desktop-pet/`，约 93 MB（含 Qt 运行时）。

---

## 环境相关的两个坑（已处理）

1. **本机未安装 Python**：PATH 里的 `python.exe` 只是跳转微软商店的占位符（`AppInstallerPythonRedirector.exe`），
   所以 `pip` 必然报"不是内部或外部命令"。→ 用上面的独立 exe 即可绕开；或装 Python 3.13 并勾选 "Add python.exe to PATH"。
2. **`APPDATA` 不可用时程序会回落用户主目录**：配置/日志将写到 `~/desktop-pet/`。这是 `config.py` 的内置容错
   （`base = Path(appdata) if appdata else Path.home()`），正常桌面环境下 `%APPDATA%` 存在，会正确写到
   `%APPDATA%\desktop-pet\`。

---

## 需要你人工验收的部分（自动化覆盖不到）

自动化测试在 `offscreen` 平台完成，以下必须真机确认，清单见 `tests/manual_checklist.md`：

1. **FR-02 敲键盘延迟** —— 真机敲键，观察猫是否同步动作、体感延迟是否 < 100ms
2. **外观目视核对** —— 猫咪形象与 8 种表情是否符合 PRD §4.1/§4.5 设计（像素统计只能证明「画出来了、8 种彼此不同」，不能证明「好看、像猫」）
3. **窗口透明** —— 确认真机无黑底方块、无边框、切窗口后仍在最上层
4. **托盘行为** —— 最小化/恢复/退出后无残留进程
5. **内存与 CPU** —— 任务管理器实测（offscreen 下测到 59MB，真实桌面合成器会更高）
6. **笔记本合盖休眠唤醒** —— 状态是否正常、不卡死
7. **多显示器拖动、高 DPI 125%/150%** 显示是否正常
8. **开机自启** —— 勾选后注册表写入、取消后移除（测试中未真实写注册表以免污染系统）

---

## 下一步建议

1. 先按上面第 1、2、3 条跑一遍——这三条决定了「能不能用、好不好看」
2. 视觉不满意时，只需改 `core/constants.py` 的 `COLORS` 与 `EXPRESSIONS_POSES`、`ui/pet_renderer.py` 的 `_GEO_*` 几何常量，不必动逻辑
3. 想调节奏（多久算休息、多久睡觉）：改 `core/constants.py` 的 `REST_THRESHOLD_S` / `SLEEP_THRESHOLD_S`
4. 想放松内存/CPU：把默认帧率 `FPS_ACTIVE` 从 30 降到 20
5. 想要免装 Python 的独立程序：按 README 的 PyInstaller 命令打包单文件 exe

---

# 本轮更新（2026-09-10 晚）：UI 重构为「双手敲迷你键盘」

## 交付状态：✅ 完成

| 项目 | 结果 |
|---|---|
| 自动化测试 | **279 / 279 通过**（退出码 0） |
| 像素级幅度自证 | 落指 **9.00px**（目标 ≥8）、抬腕 **13.18px**（目标 ≥12）、键帽下沉 **3.00px**（目标 ≥3） |
| 高频可读性 | 4 / 6 / 8 / 10 次每秒 下抬腕均 **13.5px**（目标 ≥4） |
| 独立 exe | 已重新打包并启动冒烟通过，内存约 **51 MB**，进程可干净退出 |

## 改了什么

原先只有一只圆爪做 8px 垂直位移，观感很"塑料"。现在：

- **新增迷你键盘**：72×16 浅奶油底板 + 2 行 × 8 个焦糖色键帽，键帽随按压**刚性下沉 3.2px**
- **新增双手**：前臂（粗圆角线 + 奶油高光芯）+ 掌心（20×14 圆角矩形 + 蜜桃粉掌垫）+ 3 根手指
  （按压时屈曲、抬起时伸展）
- **击键姿态是左右不对称的**：活动手落指下沉 + 屈指，**对侧手同时抬腕** —— 既贴近真实打字姿态，
  又让高频连打（≥8 次/秒）下抬腕动作不会自己打断自己
- **拖拽期间敲键不生效**（避免"悬空按键"的怪异画面）
- 新增 2 个测试文件：`test_keystroke_dynamics.py`(19 例)、`test_hand_visibility.py`(12 例)

改动文件（5 个）：
```
src/desktop_pet/core/pet_model.py      # 4 个新姿态通道 + 击键包络（绕过全局平滑）
src/desktop_pet/core/constants.py      # 击键时序常量 + NEUTRAL_POSE 补齐
src/desktop_pet/ui/pet_renderer.py     # _draw_keyboard / _draw_hands / _draw_hand
src/desktop_pet/app/controller.py      # 拖拽守卫
tests/test_keystroke_dynamics.py       # 新增
tests/test_hand_visibility.py          # 新增
```

## 关键实现要点（后续改 UI 时请遵守）

1. **击键包络必须绕过全局帧平滑**。全局 `POSE_SMOOTH_K=9` 每帧只收敛约 26%，
   会把 100~200ms 的瞬态击键吃掉。做法：`update()` 里先 `lerp_to(target, t)` 平滑，
   再由 `_apply_keystroke()` 对击键通道**直接赋值**（后写覆盖）。
2. **单相时长 ≥4~6 帧**。30fps 下 `PRESS_DOWN_S=0.14`、`PRESS_REBOUND_S=0.18`；
   再短就算幅度够大也看不见。
3. **改完务必做像素级实测**，不要只信"代码里写了 8px"。可靠手法：
   渲染 QImage → 逐像素统计目标色块位移/包围盒（脚本见下）。
4. 零外部图片素材的硬约束仍然生效，键盘与手都是纯 QPainter 矢量绘制。

## 生成预览图 / 自证幅度

```bash
cd C:\Users\王佐成\WorkBuddy\软件开发\desktop-pet
%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe _tmp_preview.py
```
输出到仓库外的 `..\desktop-pet_preview\`（3x 用于查几何、1x 用于看真实观感），
并把幅度实测值与目标逐条对比打印。

## ⚠️ 本次踩到的环境事故（务必知悉）

清理项目根目录 40+ 个 `_*` 临时文件时连续使用 `rm`，触发沙箱 **safe-delete 批量删除保护**
（阈值 50 个/轮），副作用是**整个工作区被回滚**：`.git` 被删除、5 个源文件退回重构前、
2 个新测试文件消失。

**已全部恢复**：靠事故前 1 分钟做的备份 `软件开发\_backup_before_branch`（74 文件）完整还原，
复跑测试 279 例全绿。但**原 git 历史（基线提交 `aa669e9`）已不可恢复**，故重建为单一基线提交
`bf712df`（43 文件 / 9343 行），`main` 与 `develop` 均指向它。

**今后请遵守**：

1. **不要用 `rm` / `rm -rf` / `del` 清理本项目**。需要清理时用工具自带参数
   （PyInstaller 用 `--noconfirm`，pytest 用 `--basetemp=`），或手动在资源管理器里删。批量/递归删除前**必须先备份**。
2. 根目录 `_*` 临时文件已被 `.gitignore` 的 `/_*` 规则排除，**不影响提交**，可以放着不管。
3. 旧打包产物保留在 `dist\desktop-pet_old_1754\`（未删，可手动清理）。
4. 本环境 git 写不了 `refs/heads/<带斜杠分支名>` 的嵌套 ref，开 `feature/xxx` 分支需要手动建 ref 文件
   （详见工作区记忆 `MEMORY.md`）。

---

# 第二轮更新（2026-09-11）：形象重构为「3/4 透视圆球猫」

## 交付状态：✅ 完成

| 项目 | 结果 |
|---|---|
| 自动化测试 | **286 / 286 通过**（上一轮 279 → 本轮 +7，含 QA 补的 4 个新用例） |
| 独立验证 | QA 7 项逐条复核，**IS_PASS: YES**，无源码缺陷 |
| 落指下压 | **+10.00 px**（目标 ≥8） |
| 抬腕上移 | **+13.00 px**（目标 ≥12） |
| 键帽下沉 | **+4.00 px**（目标 ≥3） |
| 高频抬腕 | 4 / 6 / 8 / 10 次每秒均 **13.5 px** |
| 脏矩形 | 8 表情 × 多姿态 × 3 缩放档，裁剪失败 **0**，最紧余量 2px（0.8 档） |
| 内容边界 | 1x 内容包围盒 (3,14,135,175)，画布 160×180 → 右余 24px / 下余 4px，**无裁切** |
| 1x 可读性 | 头部区近黑（描边）占比 14.6%~20.3%，彩色像素 5.0k~6.7k → 轮廓清晰，非一坨黑 |
| 8 表情 | 1x 渲染 md5 两两不同，非透明像素 12.8k~26.7k |

## 用户需求与选择

原话：「改成这种侧面 45 角度的视角，喵喵改的更可爱一些」，附参考图。
用户明确选择：**照搬参考图（彩虹渐变 + 粗黑描边）** + **头身一体的圆球体型** + **键盘 + 鼠标都要**。

## 改了什么

原型是「正面平视 + 头身分离 + 奶油焦糖纯色 + 细暖棕描边 + 双手敲键盘」。现在：

- **圆球团子**：头身用 `QPainterPath.united` 融成一个整体，无接缝；顶部两只小三角耳
- **柔和全息彩虹渐变**：左上薄荷绿 → 奶油黄 → 暖橙 → 粉 → 右下天空蓝，对角线性渐变
- **粗纯黑描边**：`OUTLINE_W = 3.2`，全部轮廓统一
- **极简脸**：实心近黑椭圆眼 + ω 形小弯嘴 + 粉腮红（保留全部 8 种表情驱动）
- **斜放的键盘**：整体旋转约 -10° 的四边形（上下边**同向**倾斜）+ 键帽按同一角度 shear + 前缘深色厚度边
- **左下角鼠标**：斜置椭圆仓 + 滚轮 + 分割线，与键盘留隙
- **粗弧尾巴**：描边宽度与主体一致，根部塞进团子轮廓内再向外延伸

改动文件：
```
src/desktop_pet/core/constants.py              # COLORS 换新 + BODY_GRADIENT_STOPS + OUTLINE_W
src/desktop_pet/ui/pet_renderer.py             # 整体重写
tests/test_hand_visibility.py                  # 等价强度改写
tests/test_keystroke_dynamics.py               # 像素折算改为读渲染常量
tests/test_static_constraints.py               # 调色板断言更新 + 新增渐变/描边断言
tests/test_new_elements_visibility.py          # 新增（QA 补，验证鼠标/尾巴/键盘确实存在且不越界）
_tmp_preview.py                                # 自证脚本判色法改版
```

## 复现验证

```bat
cd /d C:\Users\王佐成\WorkBuddy\软件开发\desktop-pet
set PYTHONPATH=src
%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe -m pytest
%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe _tmp_preview.py
```
注意：`pyproject.toml` 的 `addopts` 已含 `-q`，**命令行不要再加 `-q`**，否则变 `-qq` 会把统计行压掉。

## 本轮的三条可复用经验

1. **「断言等价改写」和「放水」必须用变异体来判别。**
   这轮重构必然要改写旧断言（旧断言数的是蜜桃色手指块，新画法下不存在了）。
   QA 没有只看 diff 下结论，而是**造了一个「爪子消失」的变异体**去跑新断言 ——
   结果发现其中一条（`n >= 40`）连爪子整个消失都拦不住（前臂白芯本身就贡献 174px），
   判定为真实强度下降，并补了「爪子比前臂宽」的可证伪判据（正常 16px / 变异体 12px，阈值 14）才通过。
   **只读 diff 看不出强度，只有变异体能证明断言真的能拦住缺陷。**
2. **斜放物体的画法要点**：整体旋转的四边形（上下边**同向**倾斜，不是上窄下宽的正梯形）
   + 表面元素按同一角度 shear + 前缘画一条深色厚度边 + 外圈描边。缺任何一条都会读成「正面视图贴了个歪方块」。
3. **自证脚本本身会撒谎**：`_tmp_preview.py` 打印的落指幅度是 9.00px，而常量 `_GEO_HAND_PRESS_PX` 是 10.0。
   原因是脚本取的不是真正的峰值帧。**测量工具的偏差必须用第二套独立方法交叉验证**（QA 换口径测到 +10px 才发现）。


