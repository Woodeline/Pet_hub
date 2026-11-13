"""ui.macos_window —— macOS 原生 NSPanel 行为修正（仅 darwin 生效，其他平台 no-op）。

背景（置顶/焦点缺陷根因）：本项目三个顶层窗口（宠物窗 / 气泡 / 按钮条）都用
``Qt.Tool | WindowStaysOnTopHint``。macOS 上 ``Qt.Tool`` 窗口映射为 **NSPanel**，
而 NSPanel 的 ``hidesOnDeactivate`` **默认为 YES** —— 用户切到其他应用、本应用
失活的瞬间，系统会自动把面板从屏幕移除（表现为「宠物先消失」）；随后宠物窗的
置顶重申定时器（``_reassert_topmost``）调用 Qt 层 ``setFlag``/``raise_``，
在 macOS 上前者可能触发原生窗口重建（销毁再创建 NSWindow → 窗口闪现），
后者可能激活失活应用（表现为「几秒后重现并抢走焦点」）。

修正方式（全部走 pyobjc 原生 API，绕开 Qt 的窗口重建路径）：

* ``setHidesOnDeactivate:NO`` —— 应用失活时面板保持可见（修「先隐藏」）。
* ``setBecomesKeyOnlyIfNeeded:YES`` —— 面板仅在确需输入时才成为 key window，
  点击/显示面板不会把 key 焦点从当前应用抢走。
* ``setCollectionBehavior: CanJoinAllSpaces | FullScreenAuxiliary | IgnoresCycle`` ——
  宠物跟随所有 Space / 全屏空间置顶显示，且不进入 Cmd+` 窗口轮换。
* ``orderFrontRegardless`` —— 把窗口带到最前但**不激活应用**（Qt ``raise_()``
  在失活应用上有激活风险），供置顶重申定时器使用。
* ``setLevel:NSFloatingWindowLevel`` —— 保底重设置顶层（不经 ``setFlag``，
  不会重建原生窗口）。

所有函数：非 macOS 平台、句柄无效、pyobjc 不可用时安静返回（debug 日志），
绝不抛出异常影响 Qt 主流程。
"""

from __future__ import annotations

import logging
import sys

# 注意用 sys.platform（小写 "darwin"）；platform.system() 返回 "Darwin"（大写 D）
IS_MACOS = sys.platform == "darwin"

logger = logging.getLogger(__name__)

#: NSWindowLevel —— 与 Qt WindowStaysOnTopHint 在 macOS 使用的浮动层一致
_NS_FLOATING_WINDOW_LEVEL = 3

#: NSWindowCollectionBehavior 位标志
_CB_CAN_JOIN_ALL_SPACES = 1 << 0        # 跟随所有 Space（含切换空间时保持可见）
_CB_IGNORES_CYCLE = 1 << 4              # 不参与 Cmd+` 窗口轮换
_CB_FULL_SCREEN_AUXILIARY = 1 << 8      # 可悬浮在原生全屏窗口之上


def _nswindow_from_ptr(nsview_ptr: int):
    """从 Qt ``winId()``（macOS 上是 NSView 指针）取宿主 NSWindow。失败返回 None。

    **平台守卫**：仅当 Qt 平台插件确为 ``cocoa`` 时才把 ``winId()`` 当作
    NSView 指针使用。offscreen（测试）/ minimal 等非原生插件的 ``winId()``
    是假句柄（小整数），对它做 ObjC 消息派发会**段错误**（崩溃无法被
    Python try/except 拦截，必须提前拦截）。
    """

    import objc
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "cocoa":
        return None

    view = objc.objc_object(c_void_p=int(nsview_ptr))
    window = view.window()
    if window is None:
        return None
    return window


def make_nonactivating_panel(nsview_ptr: int) -> None:
    """把 Qt Tool 窗口宿主的 NSPanel 配置为「失活不隐藏、永不抢 key」。

    **调用时机**：必须在 show 管线**结束后**调用（如 showEvent 里
    ``QTimer.singleShot(0, ...)`` 延迟一拍）。实测 Qt 在 showEvent 返回后会
    重置 NSPanel 属性（重新 ``setHidesOnDeactivate:YES``），同步调用会被覆盖。
    本函数幂等，可周期性重挂自愈。原生窗口重建后也需重挂。
    """

    if not IS_MACOS:
        return
    try:
        window = _nswindow_from_ptr(nsview_ptr)
        if window is None:
            logger.debug("macOS 面板修正：未取到 NSWindow（ptr=%r）", nsview_ptr)
            return
        # 修「切换应用后宠物先隐藏」：应用失活时面板不随系统默认行为被移除。
        window.setHidesOnDeactivate_(False)
        # 修「抢焦点」：面板只在确需键入时才成为 key window；默认展示/点击不夺焦。
        try:
            window.setBecomesKeyOnlyIfNeeded_(True)
        except Exception:  # noqa: BLE001 —— 非 NSPanel 宿主时可能不支持，忽略
            logger.debug("setBecomesKeyOnlyIfNeeded 不支持（已忽略）", exc_info=True)
        # 全 Space / 全屏跟随 + 不进窗口轮换，保证「始终在所有窗口之上」。
        window.setCollectionBehavior_(
            _CB_CAN_JOIN_ALL_SPACES | _CB_IGNORES_CYCLE | _CB_FULL_SCREEN_AUXILIARY
        )
    except Exception:  # noqa: BLE001 —— 原生层任何异常都不能拖垮 Qt 主流程
        logger.debug("macOS 面板行为修正失败（已忽略）", exc_info=True)


def ensure_floating_level(nsview_ptr: int) -> None:
    """保底置顶层：仅当当前 level **低于** NSFloatingWindowLevel 时才抬升。

    **只升不降**：Qt 对 WindowStaysOnTopHint 实际使用 level 8（高于浮动层 3），
    若无条件 ``setLevel:3`` 反而会把宠物降到置顶层之下。本函数只兜底
    「层被异常拿掉」的场景，正常情况不动 Qt 已设的层；走原生 API 不重建窗口。
    """

    if not IS_MACOS:
        return
    try:
        window = _nswindow_from_ptr(nsview_ptr)
        if window is None:
            return
        if int(window.level()) < _NS_FLOATING_WINDOW_LEVEL:
            window.setLevel_(_NS_FLOATING_WINDOW_LEVEL)
    except Exception:  # noqa: BLE001
        logger.debug("macOS 置顶层重设失败（已忽略）", exc_info=True)


def order_front_no_activate(nsview_ptr: int) -> None:
    """把窗口带到最前但**绝不激活应用**（``orderFrontRegardless``）。

    替代 Qt ``raise_()``：后者在 macOS 上映射为 ``orderFront:``，对**失活的
    应用**存在触发应用激活（抢走当前应用焦点）的风险；``orderFrontRegardless``
    文档明确「仅调序、不激活」。
    """

    if not IS_MACOS:
        return
    try:
        window = _nswindow_from_ptr(nsview_ptr)
        if window is None:
            return
        window.orderFrontRegardless()
    except Exception:  # noqa: BLE001
        logger.debug("macOS orderFrontRegardless 失败（已忽略）", exc_info=True)
