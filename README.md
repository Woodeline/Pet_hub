# desktop-pet · 大圣喵风格桌面宠物

一只常驻 Windows 桌面、会"陪你敲键盘"的治愈系程序化猫咪。
监听全局键盘敲击并同步做出"敲键盘"动画，在**空闲 / 专注 / 休息 / 睡觉**四态间
自动切换并给出不同情绪反馈。**程序化矢量绘制，零外部图片素材。**

---

## 🚀 我要马上运行（30 秒）

**不需要装 Python**，直接双击：

```text
desktop-pet\dist\desktop-pet\desktop-pet.exe
```

或者双击项目根目录的 **`run.bat`**（自动挑选可用运行时）。

启动后猫咪会出现在屏幕右下角。**退出方式**：右键猫咪 → 退出。
内存占用约 **50 MB**。

---

## 功能亮点

| 能力 | 说明 | 对应需求 |
| --- | --- | --- |
| 键盘同步 | 全局键盘敲击检测，双爪交替按压 + 身体微颤（端到端 < 100ms） | FR-01/02 |
| 高频判定 | 连续 300ms 内 ≥3 次按键判定高频，进入专注/兴奋 | FR-03/04 |
| 情绪状态机 | 空闲 / 专注 / 休息 / 睡觉 四态自动切换，最小驻留 5s 防抖 | FR-05~10 |
| 8 种表情 | 开心 / 专注 / 犯困 / 惊讶 / 委屈 / 打呵欠 / 睡觉 / 兴奋 | FR-11/12 |
| 生命体征 | 随机眨眼（3~6s）、呼吸起伏（约 3s）、尾巴摆动、耳朵抖动 | FR-13/14 |
| 窗口能力 | 无边框透明、始终置顶、不占任务栏、可拖动、多屏适配 | FR-15~21 |
| 系统托盘 | 最小化到托盘 / 恢复 / 暂停监听 / 缩放 / 开机自启 / 退出 | FR-22~26 |
| 交互反馈 | 点击弹跳、悬停抚摸、拖拽被拎起姿态、气泡对话 | FR-27~30 |
| 轻量省电 | 活跃 30 / 空闲 15 / 睡眠 8 FPS，脏区局部刷新 | FR-31~35 |
| 配置持久化 | JSON 配置，损坏自动回落默认 | FR-36~39 |

---

## 环境要求

**方式 A（推荐，开箱即用）**：无需安装任何东西 —— 直接用已打包好的独立程序：

```text
desktop-pet\dist\desktop-pet\desktop-pet.exe
```

双击即可运行。也可双击项目根目录的 `run.bat`，它会自动优先启动这个 exe。

**方式 B（源码运行）**：需要 **Python 3.13**（Windows x64）+ Windows 10 / 11。

> ⚠️ 常见坑：如果敲 `pip` 提示 **"'pip' 不是内部或外部命令"**，说明本机没有安装 Python
> （Windows 自带的 `python.exe` 只是个跳转到微软商店的占位符，不是真解释器）。
> 这时请走「方式 A」，或先到 <https://www.python.org/downloads/> 安装 Python 3.13，
> **安装时务必勾选 "Add python.exe to PATH"**，装完重开一个命令行窗口再敲 `pip -V` 验证。

## 安装（仅方式 B 需要）

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> 如果下载很慢或超时，可换国内镜像：
> `pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/`

开发（含测试依赖）：

```bat
pip install -r requirements-dev.txt
```

## 运行

**方式 A：独立程序（无需 Python）**

```bat
dist\desktop-pet\desktop-pet.exe
```

或双击项目根目录的 `run.bat`（会按 `dist` exe → 项目 `.venv` → 其他可用运行时 的顺序自动选择）。

**方式 B-1：源码运行（src-layout，需把 `src` 加入 `PYTHONPATH`）**

```bat
cd /d <本项目目录>
set PYTHONPATH=src
python -m desktop_pet.main
```

**方式 B-2：以可编辑模式安装后使用入口命令（开机自启依赖此方式）**

```bat
pip install -e .
desktop-pet
```

> 提示：命令要**一行一条**执行。若粘贴成 `pip install -r requirements.txtset PYTHONPATH=src`
> 这种连在一起的形式，必然报错。

## 退出程序

右键桌面上的猫咪 → **退出**；或右键托盘图标 → **退出**。
（关掉命令行窗口**不会**结束宠物，因为它运行在分离进程中。）

## 重新打包为独立程序（可选）

已打包好的产物在 `dist/`。如需重新打包：

```bat
pip install pyinstaller
pyinstaller --noconfirm --windowed --name desktop-pet ^
    --paths src ^
    --hidden-import pynput.keyboard._win32 ^
    --hidden-import pynput.mouse._win32 ^
    src\desktop_pet\main.py
```

`--hidden-import` 两项是必须的：`pynput` 的后端模块是运行时动态导入的，PyInstaller 静态分析扫不到，
漏掉会导致打包后的程序启动即静默崩溃。

打包后可在托盘菜单勾选"开机自启"，注册表将写入该可执行文件的路径。

## 测试

```bat
pytest -q
```

---

## 配置项说明

配置文件位置：`%APPDATA%\desktop-pet\config.json`（人类可读 JSON）。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `version` | int | `1` | schema 版本号 |
| `window_x` | int | `-1`（自动） | 窗口左上角 x |
| `window_y` | int | `-1`（自动） | 窗口左上角 y |
| `scale` | float | `1.0` | 缩放档，取值 `0.8 / 1.0 / 1.2` |
| `listen_enabled` | bool | `true` | 全局键盘监听开关 |
| `bubble_enabled` | bool | `true` | 气泡提示开关 |
| `autostart` | bool | `false` | 开机自启 |

> 配置损坏 / 字段缺失 / 类型错误 / 数值越界时，会**逐字段回落默认值**并记录日志，
> 程序不会崩溃。删除配置文件后重新启动即可以默认值重建。

日志文件：`%APPDATA%\desktop-pet\app.log`（自动轮转，单文件上限 512KB）。

---

## 隐私说明（关于全局键盘监听）

- 本程序使用 `pynput` 监听**全局键盘敲击事件**，目的是让猫咪同步做出敲键盘动画。
- **仅统计按键发生的时刻与频率，绝不记录、绝不存储、绝不上传任何按键内容**。
  所有数据处理都在本机内存中完成，程序不包含任何网络请求代码。
- 你可以随时**暂停监听**：右键宠物或托盘图标 → 取消勾选"监听键盘"；
  该开关状态会被记住。暂停后程序将不再接收任何键盘事件。
- 监听运行在独立守护线程，异常会被捕获并记入日志，不会影响系统稳定。

---

## 目录结构

```text
desktop-pet/
├─ run.bat                     # ★ 双击启动（自动挑选可用运行时）
├─ dist/desktop-pet/
│  └─ desktop-pet.exe          # ★ 打包好的独立程序，无需 Python
├─ docs/                       # PRD / 架构 / 类图 / 时序图
├─ overview.md                 # 交付总览
├─ src/desktop_pet/
│  ├─ main.py                  # 入口
│  ├─ core/                    # 纯逻辑层（零 Qt 依赖，可无头单测）
│  │  ├─ constants.py          # 枚举 / 阈值 / 配色 / 文案 唯一来源
│  │  ├─ config.py             # 配置读写（容错 + 原子保存）
│  │  ├─ event_aggregator.py   # 敲击聚合与高频判定
│  │  ├─ mood_state_machine.py # 四态情绪状态机
│  │  ├─ motion.py             # 缓动 / 插值 / 周期动画 / 屏幕钳制
│  │  └─ pet_model.py          # 姿态模型
│  ├─ ui/                      # 渲染层（PySide6）
│  │  ├─ pet_renderer.py       # QPainter 矢量猫咪 + 托盘图标
│  │  ├─ pet_window.py         # 无边框透明置顶窗口
│  │  ├─ bubble.py             # 气泡浮层
│  │  └─ tray.py               # 系统托盘
│  └─ app/                     # 组装层
│     ├─ keyboard_listener.py  # pynput 守护线程 + 跨线程信号桥
│     └─ controller.py         # 装配 / 接线 / 生命周期
├─ tests/                      # 248 个测试 + 人工验收清单
├─ requirements.txt
├─ requirements-dev.txt
└─ pyproject.toml
```

架构依赖方向：`app → ui → core`（单向）；`core` 层**绝不含任何 Qt 依赖**。
