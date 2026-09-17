"""ui.motion_ui / ui.spinner 回归测试（UI 视觉升级 P2）。

守护动效的不变式：

- 时长 / 位移常量与计划一致（200 / 150 / 4 / 200）。
- ``motion_enabled`` 统一判定（``reduce_motion=True`` → 关闭）。
- 淡入创建**两个**动画（透明度 + 位置），位置满足「上移 MOTION_RISE_PX 落位」。
- ``reduce_motion=True`` 时**直接终态且不创建任何动画对象**。
- ``fade_out`` 时长与 ``on_finished`` 回调契约。
- spinner 旋转状态机 + 真能画出不透明像素。
- 详情窗：加载态 spinner 转、文字保留；非加载态 spinner 停。
- 详情窗 reduce_motion 守卫：``reduce_motion=True`` 的联网 loading 分支**不创建**标签动画
  （直接终态 opacity=1.0），且 ``controller._open_word_detail`` **先注入再显示**（防接线顺序写反）。

均使用 ``QT_QPA_PLATFORM=offscreen``，不依赖真实窗口显示。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QPropertyAnimation, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig, ConfigStore
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.ui import motion_ui
from desktop_pet.ui.spinner import Spinner
from desktop_pet.ui.word_detail_window import WordDetailWindow
from desktop_pet.ui.word_detail_worker import WordDetailNetConfig


def _entry() -> VocabEntry:
    return VocabEntry(
        id="n5-0001", level="N5", word="私", kana="わたし",
        translation="我", meaning="第一人称代词", romaji="watashi",
    )


def _fresh_entry() -> VocabEntry:
    """词库/缓存里必然不存在的词条（用于强制走联网 loading 分支）。"""

    return VocabEntry(
        id="zzz-motion-unit-0001", level="N5", word="試験", kana="しけん",
        translation="考试", meaning="", romaji="",
    )


def _net_with_api_key() -> WordDetailNetConfig:
    """带非空 api_key 的联网配置 → 使 ``show_entry`` 进入 loading 分支。"""

    return WordDetailNetConfig(
        api_key="sk-motion-unit-test",
        base_url="https://example.invalid",
        model="deepseek-chat",
        timeout_s=1.0,
        retries=0,
    )


class _FakePool:
    """记录 start/clear，不真正执行 runnable（避免真实联网）。"""

    def __init__(self) -> None:
        self.started: list[object] = []
        self.cleared: bool = False

    def start(self, runnable: object) -> None:
        self.started.append(runnable)

    def clear(self) -> None:
        self.cleared = True


def _render_spinner(spinner: Spinner) -> QImage:
    """把 spinner 渲染到透明底 QImage（用于统计像素）。"""

    image = QImage(spinner.width(), spinner.height(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    spinner.render(image, QPoint(0, 0))
    return image


def _opaque_pixel_count(image: QImage) -> int:
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                count += 1
    return count


# --------------------------------------------------------------------------- #
# 1. 时长 / 位移常量
# --------------------------------------------------------------------------- #
def test_motion_constants_match_plan() -> None:
    assert motion_ui.MOTION_FADE_IN_MS == 200
    assert motion_ui.MOTION_FADE_OUT_MS == 150
    assert motion_ui.MOTION_RISE_PX == 4
    assert motion_ui.MOTION_LABEL_FADE_MS == 200


# --------------------------------------------------------------------------- #
# 2. motion_enabled 判定
# --------------------------------------------------------------------------- #
def test_motion_enabled_semantics() -> None:
    assert motion_ui.motion_enabled(None) is True
    assert motion_ui.motion_enabled(False) is True
    assert motion_ui.motion_enabled(True) is False


# --------------------------------------------------------------------------- #
# 3. 淡入：两个动画 + 上移 4px
# --------------------------------------------------------------------------- #
def test_show_window_animated_creates_fade_in(qtbot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)

    motion = motion_ui.show_window_animated(widget, reduce_motion=False)

    assert isinstance(motion, motion_ui.WindowMotion)
    assert motion.window is widget
    assert motion.reduce_motion is False

    assert motion.opacity_animation is not None
    assert motion.opacity_animation.duration() == 200
    assert motion.pos_animation is not None
    assert motion.pos_animation.duration() == 200

    start = motion.pos_animation.startValue()
    end = motion.pos_animation.endValue()
    assert start.y() == end.y() + 4, "淡入未体现「上移 4px」"


# --------------------------------------------------------------------------- #
# 4. reduce_motion=True：直接终态，不创建动画
# --------------------------------------------------------------------------- #
def test_show_window_animated_reduce_motion_skips_animation(qtbot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)

    motion = motion_ui.show_window_animated(widget, reduce_motion=True)

    assert widget.windowOpacity() == 1.0
    assert motion.reduce_motion is True
    assert motion.opacity_animation is None
    assert motion.pos_animation is None


# --------------------------------------------------------------------------- #
# 5. 淡出：时长 150ms + on_finished 回调
# --------------------------------------------------------------------------- #
def test_fade_out_duration_and_callback(qtbot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    motion = motion_ui.create_window_motion(widget, reduce_motion=False)
    called: list[bool] = []
    motion.fade_out(on_finished=lambda: called.append(True))

    assert motion.opacity_animation is not None
    assert motion.opacity_animation.duration() == 150
    assert called == []  # 动画未结束前不应回调

    motion.opacity_animation.stop()
    motion.opacity_animation.finished.emit()
    assert called == [True]


def test_fade_out_reduce_motion_calls_synchronously(qtbot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)

    motion = motion_ui.create_window_motion(widget, reduce_motion=True)
    called: list[bool] = []
    motion.fade_out(on_finished=lambda: called.append(True))

    assert called == [True]
    assert motion.opacity_animation is None


# --------------------------------------------------------------------------- #
# 6. Spinner 旋转状态机 + 真绘制
# --------------------------------------------------------------------------- #
def test_spinner_state_machine(qtbot) -> None:
    spinner = Spinner()
    qtbot.addWidget(spinner)

    assert spinner.is_spinning() is False
    spinner.start()
    assert spinner.is_spinning() is True
    assert spinner._timer.parent() is spinner  # 计时器挂 parent，防泄漏
    spinner.stop()
    assert spinner.is_spinning() is False


def test_spinner_reduce_motion_stays_static(qtbot) -> None:
    spinner = Spinner(reduce_motion=True)
    qtbot.addWidget(spinner)

    spinner.start()
    assert spinner.is_spinning() is False


def test_spinner_paints_opaque_pixels(qtbot) -> None:
    spinner = Spinner(size=16)
    qtbot.addWidget(spinner)

    image = _render_spinner(spinner)
    assert _opaque_pixel_count(image) > 0, "spinner 未画出任何不透明像素（空白图）"


# --------------------------------------------------------------------------- #
# 7. 详情窗集成：加载态 spinner 转 / 文字保留；非加载态停
# --------------------------------------------------------------------------- #
def test_detail_window_spinner_lifecycle(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)

    # 离线态（net=None）：不转
    window.show_entry(_entry(), detail=None, net=None)
    assert window._status_label.text() == C.WORD_DETAIL_OFFLINE_HINT
    assert window._spinner.is_spinning() is False

    # 加载态：文字保留「联网查询中…」且 spinner 转
    window.set_loading()
    assert window._status_label.text() == C.WORD_DETAIL_LOADING
    assert window._spinner.is_spinning() is True

    # 失败态：spinner 停
    window.set_detail_error(window._item_id, "boom")
    assert window._spinner.is_spinning() is False


# --------------------------------------------------------------------------- #
# 8. 详情窗 reduce_motion 守卫（计划 §4 验收：reduce_motion=True 跳过动画，直接终态）
#    —— 联网 loading 分支的标签淡入是「首开详情窗」唯一会创建动画的地方，
#       故此处是「接线顺序写反」缺陷的直接守卫。
# --------------------------------------------------------------------------- #
def test_detail_window_reduce_motion_skips_label_animation(qtbot) -> None:
    """``reduce_motion=True`` + loading 分支：**不创建任何**标签动画，effect 直接终态 1.0。"""

    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)

    window.set_reduce_motion(True)
    window.show_entry(_entry(), None, None, _net_with_api_key())

    assert window._status_label.text() == C.WORD_DETAIL_LOADING  # 确认走了 loading 分支
    animations = window._status_label.findChildren(QPropertyAnimation)
    assert animations == [], f"reduce_motion=True 仍创建了标签动画：{animations}"
    effect = window._status_label.graphicsEffect()
    assert effect is not None and effect.opacity() == 1.0


def test_detail_window_motion_on_creates_label_animation(qtbot) -> None:
    """对照组：``reduce_motion=False`` + loading 分支 → 恰好创建 1 个标签动画（证明上条有区分度）。"""

    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)

    window.set_reduce_motion(False)
    window.show_entry(_entry(), None, None, _net_with_api_key())

    animations = window._status_label.findChildren(QPropertyAnimation)
    assert len(animations) == 1, f"开启动效时应恰好 1 个标签动画，实际 {len(animations)}"
    effect = window._status_label.graphicsEffect()
    assert effect is not None and effect.opacity() < 1.0


def test_open_word_detail_injects_reduce_motion_before_show(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """controller 级守卫：``_open_word_detail`` 必须**先注入** reduce_motion 再 ``show_entry``。

    ``reduce_motion=True`` 配置下首开详情窗（联网 loading 分支）不得创建标签动画 ——
    这正是「set_reduce_motion / show_entry 顺序写反」缺陷的回归守卫。
    """

    from desktop_pet.app.controller import PetAppController
    from desktop_pet.ui import word_detail_worker

    # 避免真实联网：把 worker.run 置空（loading 态动画在 set_loading 内**同步**创建，与本补丁无关）。
    monkeypatch.setattr(word_detail_worker.WordDetailWorker, "run", lambda self: None)

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    store.save(
        AppConfig(
            listen_enabled=False,
            reduce_motion=True,
            deepseek_api_key="sk-motion-unit-test",
        )
    )

    app = QApplication.instance()
    assert isinstance(app, QApplication)

    controller = PetAppController(app, store)
    try:
        controller.start()
        controller._open_word_detail(_fresh_entry())

        window = controller._detail_window
        assert window is not None, "详情窗未被创建"
        label = window._status_label
        assert label.text() == C.WORD_DETAIL_LOADING, "未走联网 loading 分支（用例前提不成立）"
        animations = label.findChildren(QPropertyAnimation)
        assert animations == [], (
            f"reduce_motion=True 仍创建了标签动画（_open_word_detail 接线顺序写反？）：{animations}"
        )
        effect = label.graphicsEffect()
        assert effect is not None and effect.opacity() == 1.0
        assert window.windowOpacity() == 1.0
    finally:
        controller.shutdown()
        app.processEvents()
