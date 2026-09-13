"""app.controller —— 装配全部组件、接线信号、驱动帧循环与生命周期管理。

职责（架构 §7 T04）：
- 装配 :class:`PetModel` / :class:`PetRenderer` / :class:`PetWindow` /
  :class:`BubbleWindow` / :class:`TrayController` / :class:`KeyboardListener` /
  :class:`KeystrokeAggregator` / :class:`MoodStateMachine`。
- 信号接线：``bridge.keystroke → 主线程槽 → aggregator → 状态机 → 模型 → 重绘``。
- 帧循环 ``_on_frame_tick``：推进状态机与模型、切换帧率、脏区重绘。
- 窗口位置 / 缩放变更持久化（FR-36/37/38）；开机自启（``winreg``，FR-26）。
- 优雅退出 ``shutdown()``：确保监听线程停止、无残留（FR-24）。
"""

from __future__ import annotations

import logging
import os
import random
import sys
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from desktop_pet.app.keyboard_listener import KeystrokeBridge, KeyboardListener
from desktop_pet.core import constants as C
from desktop_pet.core import motion, paths
from desktop_pet.core.config import AppConfig, ConfigStore
from desktop_pet.core.constants import Expression, Gesture, Mood
from desktop_pet.core.event_aggregator import KeystrokeAggregator
from desktop_pet.core.mood_state_machine import (
    MoodStateMachine,
    MoodTransition,
    expression_for_mood,
)
from desktop_pet.core.pet_model import PetModel
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank, WordSampler
from desktop_pet.ui.bubble import BubbleWindow
from desktop_pet.ui.pet_renderer import PetRenderer
from desktop_pet.ui.pet_window import PetWindow
from desktop_pet.ui.tray import TrayController
from desktop_pet.ui.vocab_window import VocabWindow

logger = logging.getLogger(__name__)

#: 单帧最大时间步长（秒），防止卡顿后姿态"跳变"或状态机误判
_MAX_FRAME_DT_S: float = 0.25
#: 敲击后维持活跃帧率的时长（秒）
_ACTIVE_HOLD_S: float = 1.0
#: 触发气泡的"瞬时反馈"表情集合
_BUBBLE_EXPRESSIONS = frozenset(
    {Expression.EXCITED, Expression.SURPRISED, Expression.SULKY, Expression.FOCUS}
)


class PetAppController(QObject):
    """桌面宠物应用总控制器。"""

    def __init__(self, app: QApplication, store: ConfigStore) -> None:
        """构造控制器并完成组件装配（不显示窗口）。

        Args:
            app: QApplication 实例。
            store: 配置存储。
        """

        super().__init__()
        self._app: QApplication = app
        self._store: ConfigStore = store
        self._cfg: AppConfig = store.load()

        # 核心逻辑组件
        self._model: PetModel = PetModel()
        self._renderer: PetRenderer = PetRenderer()
        self._window: PetWindow = PetWindow(self._model, self._renderer, self._cfg.scale)
        self._bubble: BubbleWindow = BubbleWindow()
        self._icon = PetRenderer.build_tray_icon()
        self._tray: TrayController = TrayController(self._icon, self._cfg)

        self._bridge: KeystrokeBridge = KeystrokeBridge()
        self._keyboard: KeyboardListener = KeyboardListener(self._bridge)
        self._aggregator: KeystrokeAggregator = KeystrokeAggregator()
        # 用当前时刻初始化，保证启动时为"空闲"起始态而非因 idle 计时从 0 起算而瞬间入睡
        self._sm: MoodStateMachine = MoodStateMachine(now=time.monotonic())

        # 运行时状态
        self._running: bool = False
        self._shutting_down: bool = False
        self._last_frame_ts: float = time.monotonic()
        self._last_bubble_ts: float = float("-inf")
        self._active_until: float = 0.0
        self._next_yawn_ts: float = float("inf")
        self._rng: random.Random = random.Random()

        # —— 日语学习运行时状态（词库 / 抽取器 / 生词本 / 单词定时 / 生词本窗口单例）——
        self._bank: WordBank = WordBank.empty()
        self._sampler: WordSampler = WordSampler(self._bank, self._rng)
        self._vocab: VocabStore = VocabStore(VocabStore.default_path())
        self._current_word: VocabEntry | None = None
        self._vocab_window: VocabWindow | None = None
        self._next_word_ts: float = float("inf")
        self._bank_warned: bool = False

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """启动：接线、定位、显示窗口、启动监听与帧循环。"""

        logger.info("桌面宠物启动中……")
        self._connect_signals()

        self._apply_scale(self._cfg.scale, persist=False)

        x, y = self._initial_position()
        self._window.restore_position(x, y)
        self._cfg.window_x, self._cfg.window_y = x, y

        self._window.set_context_menu(self._tray.menu)

        self._tray.set_listen_checked(self._cfg.listen_enabled)
        self._tray.set_scale_checked(self._cfg.scale)
        self._tray.set_autostart_checked(self._cfg.autostart)
        self._tray.set_bubble_checked(self._cfg.bubble_enabled)
        self._load_japanese()
        self._tray.set_jp_checked(self._cfg.jp_enabled)
        self._tray.set_jp_level_checked(self._cfg.jp_level)
        self._tray.set_jp_enabled(self._cfg.jp_enabled)
        self._tray.set_jp_current_word(None)
        self._tray.show()
        self._notify_jp_startup_state()

        self._window.show()
        self._window.raise_()

        self._model.set_base_expression(expression_for_mood(self._sm.mood))
        self._window.set_fps(C.FPS_IDLE)
        self._window.start_animation()

        if self._cfg.listen_enabled:
            self._keyboard.start()
        else:
            logger.info("配置为不启用键盘监听")

        now = time.monotonic()
        self._last_frame_ts = now
        self._next_yawn_ts = now + motion.random_interval(C.YAWN_MIN_S, C.YAWN_MAX_S)
        self._schedule_next_word(now)
        self._running = True

        self._app.aboutToQuit.connect(self._on_about_to_quit)
        self._tray.notify(C.APP_DISPLAY_NAME, "我来陪你敲键盘啦~")
        logger.info("桌面宠物已启动：位置=(%d,%d) 缩放=%.1f 监听=%s",
                    x, y, self._cfg.scale, self._cfg.listen_enabled)

    def shutdown(self) -> None:
        """优雅退出：停止监听与帧循环、持久化配置、退出应用（FR-24）。"""

        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("开始退出流程……")
        try:
            self._keyboard.stop()
        except Exception:  # noqa: BLE001
            logger.exception("停止键盘监听失败")
        try:
            self._window.stop_animation()
        except Exception:  # noqa: BLE001
            logger.exception("停止帧循环失败")
        self._persist()
        try:
            self._bubble.hide_bubble()
            self._window.hide()
        except Exception:  # noqa: BLE001
            logger.exception("隐藏窗口失败")
        self._running = False
        logger.info("退出流程完成")
        self._app.quit()

    # ------------------------------------------------------------------ #
    # 信号接线
    # ------------------------------------------------------------------ #
    def _connect_signals(self) -> None:
        """连接全部信号与槽。"""

        # 帧循环与鼠标手势
        self._window.frame_tick.connect(self._on_frame_tick)
        self._window.gesture_triggered.connect(self._on_gesture)
        self._window.drag_finished.connect(self._on_drag_finished)
        self._window.position_changed.connect(self._on_position_changed)

        # 跨线程键盘信号（AutoConnection → 自动排队到主线程）
        self._bridge.keystroke.connect(self._on_keystroke)

        # 托盘
        self._tray.listen_toggled.connect(self._on_listen_toggled)
        self._tray.bubble_toggled.connect(self._on_bubble_toggled)
        self._tray.scale_selected.connect(self._apply_scale)
        self._tray.minimize_requested.connect(self._on_minimize)
        self._tray.restore_requested.connect(self._on_restore)
        self._tray.autostart_toggled.connect(self._set_autostart)
        self._tray.quit_requested.connect(self.shutdown)

        # 日语学习
        self._tray.jp_enabled_toggled.connect(self._on_jp_toggled)
        self._tray.jp_level_selected.connect(self._on_jp_level_selected)
        self._tray.jp_remember_requested.connect(self._on_jp_remember)
        self._tray.jp_vocab_requested.connect(self._on_jp_vocab)

    # ------------------------------------------------------------------ #
    # 槽：键盘
    # ------------------------------------------------------------------ #
    def _on_keystroke(self, timestamp: float) -> None:
        """主线程处理一次按键：聚合 → 状态机 → 模型 → 重绘（FR-02/03/10）。"""

        try:
            now = float(timestamp)
            result = self._aggregator.record(now)
            transition = self._sm.on_keystroke(now, result.high_frequency)
            # 拖拽（被拎起）期间不触发敲击：避免「双手下垂外摆 + 落指」同帧叠加。
            if not self._model.is_dragging():
                self._model.press_arm()
            self._active_until = now + _ACTIVE_HOLD_S
            self._sync_fps_and_visuals(transition)

            if transition.expression in _BUBBLE_EXPRESSIONS:
                self._show_bubble_for(transition.expression, now)
            elif transition.changed:
                self._show_bubble_for(transition.to_mood, now)

            self._window.set_fps(C.FPS_ACTIVE)
        except Exception:  # noqa: BLE001 —— 键事件异常绝不崩溃
            logger.exception("处理按键事件异常（已忽略）")

    # ------------------------------------------------------------------ #
    # 槽：帧循环
    # ------------------------------------------------------------------ #
    def _on_frame_tick(self, now: float | None = None) -> None:
        """帧循环：推进状态机与模型，切换帧率并脏区重绘。

        Args:
            now: 当前时刻（秒）。若为 ``None`` 则自行读取 ``time.monotonic()``。
        """

        try:
            now = float(now) if now is not None else time.monotonic()
            dt = now - self._last_frame_ts
            if dt <= 0.0 or dt > 1.0:
                dt = C.interval_for_fps(C.FPS_ACTIVE) / 1000.0
            self._last_frame_ts = now

            transition = self._sm.update(now)
            if transition.changed:
                self._sync_fps_and_visuals(transition)
                self._show_bubble_for(transition.to_mood, now)
            else:
                # 保证基础表情与当前情绪态一致（临时表情过期后自动回落）
                self._model.set_base_expression(expression_for_mood(self._sm.mood))

            # 休息态随机呵欠（PRD §3.3.1：间隔 15~30s）
            if self._sm.mood == Mood.REST and now >= self._next_yawn_ts:
                self._model.set_expression(Expression.YAWN, C.TEMP_EXPRESSION_S)
                self._show_bubble_for(Expression.YAWN, now)
                self._next_yawn_ts = now + motion.random_interval(C.YAWN_MIN_S, C.YAWN_MAX_S)
            elif self._sm.mood != Mood.REST:
                self._next_yawn_ts = now + motion.random_interval(C.YAWN_MIN_S, C.YAWN_MAX_S)

            # 学习模式：独立随机节奏（25~50s）展示日语单词（挂在既有帧循环，不新开 QTimer）
            if self._cfg.jp_enabled and now >= self._next_word_ts:
                self._show_word_bubble(now)
                self._schedule_next_word(now)

            # 帧率联动（活跃 30 / 空闲 15 / 睡眠 8）
            fps = C.FPS_ACTIVE if now < self._active_until else self._fps_for_mood(self._sm.mood)
            self._window.set_fps(fps)

            self._model.update(max(0.0, min(dt, _MAX_FRAME_DT_S)), now)
            self._window.refresh()
        except Exception:  # noqa: BLE001
            logger.exception("帧循环异常（已忽略本帧）")

    # ------------------------------------------------------------------ #
    # 槽：鼠标手势
    # ------------------------------------------------------------------ #
    def _on_gesture(self, gesture_value: int) -> None:
        """处理鼠标手势（点击 / 悬停 / 拖拽 / 唤醒）。"""

        try:
            gesture = Gesture(int(gesture_value))
            now = time.monotonic()
            if gesture == Gesture.CLICK:
                self._model.trigger_click()
                self._active_until = now + C.CLICK_ANIM_S
                self._show_bubble_for(Expression.HAPPY, now)
            elif gesture == Gesture.HOVER:
                self._active_until = now + _ACTIVE_HOLD_S
                self._show_bubble_for(Expression.HAPPY, now)

            transition = self._sm.on_gesture(gesture, now)
            self._sync_fps_and_visuals(transition)
        except Exception:  # noqa: BLE001
            logger.exception("处理鼠标手势异常（已忽略）")

    def _on_position_changed(self, x: int, y: int) -> None:
        """窗口拖动中：仅更新内存位置（松手后再落盘，避免频繁写盘）。"""

        self._cfg.window_x = int(x)
        self._cfg.window_y = int(y)

    def _on_drag_finished(self, x: int, y: int) -> None:
        """拖拽结束：越界钳制（FR-36）并持久化。"""

        try:
            cx, cy = motion.clamp_to_screens(
                x, y, self._window.width(), self._window.height(),
                self._screen_geometries(), self._primary_geometry(),
            )
            if (cx, cy) != (int(x), int(y)):
                self._window.move(cx, cy)
            self._cfg.window_x, self._cfg.window_y = cx, cy
            self._persist()
        except Exception:  # noqa: BLE001
            logger.exception("处理拖拽结束异常（已忽略）")

    # ------------------------------------------------------------------ #
    # 槽：托盘
    # ------------------------------------------------------------------ #
    def _on_listen_toggled(self, checked: bool) -> None:
        """切换键盘监听开关（FR-01/FR-38）。"""

        self._cfg.listen_enabled = bool(checked)
        if checked:
            self._keyboard.start()
            self._tray.notify(C.APP_DISPLAY_NAME, "键盘监听已恢复")
        else:
            self._keyboard.stop()
            self._tray.notify(C.APP_DISPLAY_NAME, "键盘监听已暂停")
        self._persist()

    def _on_bubble_toggled(self, checked: bool) -> None:
        """切换气泡提示开关（FR-38 / PRD Q-01）。"""

        self._cfg.bubble_enabled = bool(checked)
        if not checked:
            self._bubble.hide_bubble()
        self._persist()

    def _on_minimize(self) -> None:
        """最小化到托盘（FR-22）。"""

        self._bubble.hide_bubble()
        self._window.hide()
        self._tray.notify(C.APP_DISPLAY_NAME, "我躲进托盘啦，双击图标叫我出来~")

    def _on_restore(self) -> None:
        """从托盘恢复窗口（FR-23）。"""

        try:
            x = self._window.x()
            y = self._window.y()
            cx, cy = motion.clamp_to_screens(
                x, y, self._window.width(), self._window.height(),
                self._screen_geometries(), self._primary_geometry(),
            )
            self._window.restore_position(cx, cy)
            self._window.show()
            self._window.raise_()
            now = time.monotonic()
            transition = self._sm.on_wake(now)
            self._sync_fps_and_visuals(transition)
        except Exception:  # noqa: BLE001
            logger.exception("恢复窗口异常（已忽略）")

    # ------------------------------------------------------------------ #
    # 内部：日语学习（词库 / 单词定时 / 生词本 / 4 槽）
    # ------------------------------------------------------------------ #
    def _load_japanese(self) -> None:
        """启动时加载内置词库与生词本（任何损坏都优雅降级，绝不崩溃）。"""

        try:
            self._bank = WordBank.load(paths.word_bank_path())
        except Exception:  # noqa: BLE001
            logger.exception("加载词库失败（已忽略，使用空词库）")
            self._bank = WordBank.empty()
        self._sampler = WordSampler(self._bank, self._rng)
        self._sampler.set_level(self._cfg.jp_level)

        try:
            self._vocab = VocabStore(VocabStore.default_path())
            self._vocab.load()
        except Exception:  # noqa: BLE001
            logger.exception("加载生词本失败（已忽略，使用空生词本）")
            self._vocab = VocabStore(VocabStore.default_path())

    def _notify_jp_startup_state(self) -> None:
        """启动时若已开启学习：给一次状态提示（气泡总开关未开 / 词库不可用）。"""

        if not self._cfg.jp_enabled:
            return
        if not self._cfg.bubble_enabled:
            self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_NEED_BUBBLE)
        elif self._bank.is_empty():
            self._bank_warned = True
            self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_BANK_UNAVAILABLE)

    def _schedule_next_word(self, now: float) -> None:
        """按 25~50s 随机间隔排期下一次单词展示（学习关闭时置 ``inf`` 不触发）。"""

        if self._cfg.jp_enabled and not self._bank.is_empty():
            self._next_word_ts = now + motion.random_interval(
                C.JP_WORD_MIN_INTERVAL_S, C.JP_WORD_MAX_INTERVAL_S, self._rng
            )
        else:
            self._next_word_ts = float("inf")

    def _show_word_bubble(self, now: float) -> None:
        """抽取并展示一条日语单词（受气泡总开关 / 睡觉态 / 最小间隔约束）。"""

        if not self._cfg.bubble_enabled:
            return
        if self._sm.mood == Mood.SLEEP:
            return
        if (now - self._last_bubble_ts) < C.BUBBLE_MIN_GAP_S:
            return
        entry = self._sampler.next()
        if entry is None:
            if not self._bank_warned:
                self._bank_warned = True
                logger.warning("日语词库为空或该等级无词（level=%s）", self._cfg.jp_level)
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_BANK_UNAVAILABLE)
            return
        self._current_word = entry
        self._tray.set_jp_current_word(entry.word)
        self._bubble.set_anchor(self._bubble_anchor())
        duration = motion.random_interval(
            C.BUBBLE_MIN_DURATION_S, C.BUBBLE_MAX_DURATION_S, self._rng
        )
        self._bubble.show_word(entry, duration)
        self._last_bubble_ts = now

    def _on_jp_toggled(self, checked: bool) -> None:
        """切换「日语学习」开关（JP-02）。"""

        checked = bool(checked)
        self._cfg.jp_enabled = checked
        self._tray.set_jp_enabled(checked)
        now = time.monotonic()
        if checked:
            self._sampler.set_level(self._cfg.jp_level)
            self._schedule_next_word(now)
            if not self._cfg.bubble_enabled:
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_NEED_BUBBLE)
            elif self._bank.is_empty():
                self._bank_warned = True
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_BANK_UNAVAILABLE)
        else:
            self._next_word_ts = float("inf")
        self._persist()

    def _on_jp_level_selected(self, level: str) -> None:
        """切换难度等级（JP-06，单选，持久化）。"""

        level = str(level)
        if level not in C.JP_LEVELS:
            return
        self._cfg.jp_level = level
        self._tray.set_jp_level_checked(level)
        self._sampler.set_level(level)
        self._persist()

    def _on_jp_remember(self) -> None:
        """把「最近一次展示」的单词加入生词本（JP-08，按 id 去重）。"""

        if not self._cfg.jp_enabled:
            return
        entry = self._current_word
        if entry is None:
            self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_NO_WORD)
            return
        added_at = self._now_iso()
        if self._vocab.add(entry, added_at):
            self._tray.notify(
                C.APP_DISPLAY_NAME,
                C.JP_NOTIFY_REMEMBER_ADDED.format(word=entry.word, kana=entry.kana),
            )
            if self._vocab_window is not None:
                self._vocab_window.refresh(self._vocab.items())
        else:
            self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_REMEMBER_DUPLICATE)

    def _on_jp_vocab(self) -> None:
        """打开生词本窗口（单例，重开则前置）。"""

        try:
            if self._vocab_window is None:
                self._vocab_window = VocabWindow()
                self._vocab_window.remove_requested.connect(self._on_vocab_remove)
                self._vocab_window.clear_requested.connect(self._on_vocab_clear)
            self._vocab_window.refresh(self._vocab.items())
            self._vocab_window.show()
            self._vocab_window.raise_()
            self._vocab_window.activateWindow()
        except Exception:  # noqa: BLE001
            logger.exception("打开生词本窗口异常（已忽略）")

    def _on_vocab_remove(self, item_id: str) -> None:
        """删除单条生词并刷新窗口。"""

        try:
            if self._vocab.remove(str(item_id)) and self._vocab_window is not None:
                self._vocab_window.refresh(self._vocab.items())
        except Exception:  # noqa: BLE001
            logger.exception("删除生词异常（已忽略）")

    def _on_vocab_clear(self) -> None:
        """清空生词本并刷新窗口。"""

        try:
            self._vocab.clear()
            if self._vocab_window is not None:
                self._vocab_window.refresh(self._vocab.items())
        except Exception:  # noqa: BLE001
            logger.exception("清空生词本异常（已忽略）")

    def _now_iso(self) -> str:
        """返回当前 UTC 墙钟时间的 ISO8601 字符串（仅 app 层生成，注入 core）。"""

        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------ #
    # 内部：应用迁移 / 帧率 / 气泡 / 缩放 / 持久化
    # ------------------------------------------------------------------ #
    def _sync_fps_and_visuals(self, transition: MoodTransition) -> None:
        """把状态机迁移结果同步到模型表情（并在必要时设置临时表情）。

        Args:
            transition: 状态机产生的迁移描述。
        """

        base_expr = expression_for_mood(transition.to_mood)
        self._model.set_base_expression(base_expr)

        transient = transition.expression
        if transient != base_expr:
            duration = C.TEMP_EXPRESSION_S
            if transient == Expression.SULKY:
                duration = C.WAKE_SULKY_S
            elif transient == Expression.SURPRISED:
                duration = C.SURPRISED_ANIM_S
            self._model.set_expression(transient, duration)

    def _fps_for_mood(self, mood: Mood) -> int:
        """情绪态 → 目标帧率（FR-34）。"""

        if mood == Mood.SLEEP:
            return C.FPS_SLEEP
        if mood == Mood.FOCUS:
            return C.FPS_ACTIVE
        return C.FPS_IDLE

    def _show_bubble_for(self, key: Expression | Mood, now: float | None = None) -> None:
        """按表情/情绪态随机展示气泡（受开关与最小间隔约束，FR-30）。

        Args:
            key: ``Expression`` 或 ``Mood``（作为文案表索引）。
            now: 当前时刻（秒）。若为 ``None`` 则自行读取。
        """

        if not self._cfg.bubble_enabled:
            return
        now = float(now) if now is not None else time.monotonic()
        if (now - self._last_bubble_ts) < C.BUBBLE_MIN_GAP_S:
            return
        texts = C.BUBBLE_TEXTS.get(key)
        if not texts:
            return
        text = self._rng.choice(texts)
        self._bubble.set_anchor(self._bubble_anchor())
        duration = motion.random_interval(
            C.BUBBLE_MIN_DURATION_S, C.BUBBLE_MAX_DURATION_S, self._rng
        )
        self._bubble.show_message(text, duration)
        self._last_bubble_ts = now

    def _bubble_anchor(self) -> QPoint:
        """计算气泡锚点（宠物头顶的全局坐标）。"""

        width = self._window.width()
        height = self._window.height()
        return self._window.mapToGlobal(QPoint(int(width * 0.5), int(height * 0.06)))

    def _apply_scale(self, scale: float, persist: bool = True) -> None:
        """应用缩放档（FR-20/37）。"""

        try:
            value = float(scale)
            for allowed in C.SCALES:
                if abs(value - allowed) < 1e-6:
                    value = float(allowed)
                    break
            self._cfg.scale = value
            self._window.set_scale(value)
            self._tray.set_scale_checked(value)
            if persist:
                self._persist()
        except Exception:  # noqa: BLE001
            logger.exception("应用缩放失败（已忽略）")

    def _persist(self) -> None:
        """把当前运行时状态写回配置（原子保存）。"""

        try:
            self._cfg.window_x = self._window.x()
            self._cfg.window_y = self._window.y()
        except Exception:  # noqa: BLE001 —— 窗口可能尚未创建
            logger.debug("持久化时窗口坐标不可用，使用配置中的旧值")
        self._store.save(self._cfg)

    # ------------------------------------------------------------------ #
    # 内部：开机自启（FR-26，winreg，免管理员，非 Windows 跳过）
    # ------------------------------------------------------------------ #
    def _set_autostart(self, enabled: bool) -> None:
        """设置开机自启开关。"""

        enabled = bool(enabled)
        self._cfg.autostart = enabled
        self._write_autostart(enabled)
        self._tray.set_autostart_checked(enabled)
        self._persist()

    def _write_autostart(self, enabled: bool) -> None:
        """写入 / 移除 ``HKCU\\...\\Run`` 启动项（仅 Windows）。"""

        if sys.platform != "win32":
            logger.info("非 Windows 平台，跳过开机自启设置")
            return
        try:
            import winreg  # 仅 Windows 可用

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                C.AUTOSTART_REG_PATH,
                0,
                winreg.KEY_SET_VALUE,
            )
            try:
                if enabled:
                    winreg.SetValueEx(
                        key, C.AUTOSTART_REG_KEY, 0, winreg.REG_SZ,
                        self._autostart_command(),
                    )
                else:
                    try:
                        winreg.DeleteValue(key, C.AUTOSTART_REG_KEY)
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
            logger.info("开机自启已%s", "启用" if enabled else "禁用")
        except Exception:  # noqa: BLE001 —— 注册表操作失败不崩溃
            logger.exception("设置开机自启失败（已忽略）")

    def _autostart_command(self) -> str:
        """构建开机自启命令行。"""

        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        exe = sys.executable
        if exe.lower().endswith("python.exe"):
            pythonw = exe[: -len("python.exe")] + "pythonw.exe"
            if os.path.exists(pythonw):
                exe = pythonw
        return f'"{exe}" -m desktop_pet'

    # ------------------------------------------------------------------ #
    # 内部：屏幕几何 / 初始位置
    # ------------------------------------------------------------------ #
    def _screen_geometries(self) -> list[tuple[int, int, int, int]]:
        """返回全部屏幕的几何列表。"""

        result: list[tuple[int, int, int, int]] = []
        try:
            for screen in QGuiApplication.screens():
                rect = screen.geometry()
                result.append((rect.x(), rect.y(), rect.width(), rect.height()))
        except Exception:  # noqa: BLE001
            logger.exception("获取屏幕列表失败")
        return result

    def _primary_geometry(self) -> tuple[int, int, int, int]:
        """返回主屏几何（不可用时回落 1920×1080 虚拟主屏）。"""

        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                rect = screen.geometry()
                return (rect.x(), rect.y(), rect.width(), rect.height())
        except Exception:  # noqa: BLE001
            logger.exception("获取主屏几何失败")
        return (0, 0, 1920, 1080)

    def _initial_position(self) -> tuple[int, int]:
        """计算初始窗口位置（配置优先，越界回落主屏右下角，FR-36）。"""

        w = self._window.width()
        h = self._window.height()
        if self._cfg.window_x >= 0 and self._cfg.window_y >= 0:
            x = int(self._cfg.window_x)
            y = int(self._cfg.window_y)
        else:
            px, py, pw, ph = self._primary_geometry()
            x = px + pw - w - C.DEFAULT_MARGIN_PX
            y = py + ph - h - C.DEFAULT_MARGIN_PX
        return motion.clamp_to_screens(
            x, y, w, h, self._screen_geometries(), self._primary_geometry()
        )

    def _on_about_to_quit(self) -> None:
        """Qt 即将退出：兜底确保监听线程已停止（无残留线程）。"""

        try:
            self._keyboard.stop()
        except Exception:  # noqa: BLE001
            logger.exception("退出时停止监听失败")


__all__ = ["PetAppController"]
