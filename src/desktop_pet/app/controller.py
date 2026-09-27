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
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QFileDialog

from desktop_pet.app.keyboard_listener import KeystrokeBridge, KeyboardListener
from desktop_pet.core import constants as C
from desktop_pet.core import motion, paths
from desktop_pet.core.config import AppConfig, ConfigStore
from desktop_pet.core.constants import Expression, Gesture, Mood
from desktop_pet.core.theme import resolve_theme, theme_stops, ui_accent_for_theme
from desktop_pet.core.event_aggregator import KeystrokeAggregator
from desktop_pet.core.mood_state_machine import (
    MoodStateMachine,
    MoodTransition,
    expression_for_mood,
)
from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.pet_model import PetModel
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import (
    VocabEntry,
    WordBank,
    WordBankParseError,
    parse_bank_file,
)
from desktop_pet.core.weighted_picker import WeightedWordPicker
from desktop_pet.core.word_detail import WordDetail
from desktop_pet.core.word_detail_bank import WordDetailBank
from desktop_pet.core.word_details_cache_store import WordDetailsCacheStore
from desktop_pet.ui.bubble import BubbleWindow
from desktop_pet.ui.bubble_button_bar import BubbleButtonBar
from desktop_pet.ui.bubble_text_dialog import BubbleTextDialog
from desktop_pet.ui.log_window import LogWindow
from desktop_pet.ui.motion_ui import show_window_animated
from desktop_pet.ui.pet_renderer import PetRenderer
from desktop_pet.ui.pet_window import PetWindow
from desktop_pet.ui.skin_renderer import build_skin_renderer
from desktop_pet.ui.tray import TrayController
from desktop_pet.ui.vocab_window import VocabWindow
from desktop_pet.ui.word_detail_window import WordDetailWindow
from desktop_pet.ui.word_detail_worker import WordDetailNetConfig

logger = logging.getLogger(__name__)

#: 单帧最大时间步长（秒），防止卡顿后姿态"跳变"或状态机误判
_MAX_FRAME_DT_S: float = 0.25
#: 敲击后维持活跃帧率的时长（秒）
_ACTIVE_HOLD_S: float = 1.0
#: 触发气泡的"瞬时反馈"表情集合 —— 即**键盘敲击专属文案键**，唯一来源为
#: ``constants.KEYBOARD_BUBBLE_EXPRESSIONS``（这些键的文案都含键盘关键字，
#: 且只会由 :meth:`PetAppController._on_keystroke` 驱动，保证文案与触发方式相匹配）。


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
        # 皮肤包帧图渲染通道（Phase 2）：按 ``cfg.skin_name`` 加载（``vector`` 显式
        # 关闭、``""`` 自动取首个可用包）；无 skins/ 或包损坏时回落矢量渲染。
        self._skin_renderer = build_skin_renderer(self._cfg.skin_name)
        self._window: PetWindow = PetWindow(
            self._model, self._renderer, self._cfg.scale, self._skin_renderer
        )
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
        # 下一次**自动**情绪气泡的排期时刻：每成功展示一条就重排为 now+20~60s 随机，
        # 帧循环到点会**主动**展示一条（自动触发是递归定时器，不是仅事件节流；
        # 鼠标 immediate 不受此限）。首个排期在 start() 里种下（启动 20~60s 后）。
        self._next_bubble_ts: float = float("-inf")
        # 下一次**敲击键盘**气泡允许展示的时刻：与自动窗**相互独立**（敲键盘不挤占
        # 自动闲聊额度，反之亦然）。初始 -inf：启动后第一次敲键即可响应。
        self._next_kb_bubble_ts: float = float("-inf")
        self._active_until: float = 0.0
        self._next_yawn_ts: float = float("inf")
        self._rng: random.Random = random.Random()

        # —— 游走锚点（阶段 C1-1 / G2）：持久化的基准位置，**不含**瞬态游走偏移 ——
        #   = 配置里的 window_x / window_y；退出与拖拽结束时保存它，绝不保存 pos()。
        self._anchor_x: int = 0
        self._anchor_y: int = 0

        # —— 日语学习运行时状态（词库 / 加权抽取器 / 生词本 / 单词定时 / 生词本窗口单例）——
        self._bank: WordBank = WordBank.empty()
        self._picker: WeightedWordPicker = WeightedWordPicker(self._bank, self._rng)
        self._vocab: VocabStore = VocabStore(VocabStore.default_path())
        self._current_word: VocabEntry | None = None
        self._vocab_window: VocabWindow | None = None
        self._next_word_ts: float = float("inf")
        self._bank_warned: bool = False

        # —— 日语记忆闭环运行时状态（已掌握集合 / 每日记录 / 按钮条 / 记录窗口单例）——
        self._mastered: MasteredStore = MasteredStore(MasteredStore.default_path())
        self._daily_log: DailyLogStore = DailyLogStore(DailyLogStore.default_path())
        self._button_bar: BubbleButtonBar = BubbleButtonBar()
        self._log_window: LogWindow | None = None
        # 气泡文案设置对话框（单例，重开则前置）
        self._bubble_text_dialog: BubbleTextDialog | None = None
        self._word_deadline: float = float("inf")
        self._word_disposed: bool = True
        # 当前展示词是否来自手动「立即显示」路径（决定处置时是否计入每日配额）
        self._word_manual: bool = False
        # D2：内存级「当日手动展示过」去重集合（不落盘、不计入 count，跨日清空）
        self._manual_shown_ids_today: set[str] = set()
        self._today_str: str = ""
        self._today_done_notified: bool = False
        self._level_done_notified: bool = False
        # 当前等级候选池已耗尽（已掌握 ∪ 当日已展示 覆盖全部词条）：
        # 置 True 后排期置 inf 停止空转；等级切换 / 导入词库 / 跨日 时复位。
        self._pool_exhausted: bool = False

        # —— 单词详情（中文五要素）：打包详情库（只读）+ 用户缓存 + 详情窗口单例 ——
        self._detail_bank: WordDetailBank = WordDetailBank.empty()
        self._detail_cache: WordDetailsCacheStore = WordDetailsCacheStore(
            WordDetailsCacheStore.default_path()
        )
        self._detail_window: WordDetailWindow | None = None

        # —— 主题皮肤：当前生效皮肤名 + 每日重估定时器（挂 parent，随控制器销毁）——
        self._current_theme: str = C.DEFAULT_THEME
        self._theme_timer: QTimer = QTimer(self)
        self._theme_timer.setInterval(C.THEME_RECHECK_MS)
        self._theme_timer.timeout.connect(self._recheck_theme)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """启动：接线、定位、显示窗口、启动监听与帧循环。"""

        logger.info("桌面宠物启动中……")
        self._connect_signals()

        # 主题：启动即按「用户选择 + 当前月份」解析并应用（渲染器取色 + 托盘图标）
        self._apply_theme()
        self._theme_timer.start()

        self._apply_scale(self._cfg.scale, persist=False)

        x, y = self._initial_position()
        # 锚点式游走：起始位置即锚点（offset 归零）；持久化保存的是锚点而非 pos()。
        self._window.set_anchor(x, y)
        self._anchor_x, self._anchor_y = x, y
        self._cfg.window_x, self._cfg.window_y = x, y

        self._window.set_context_menu(self._tray.menu)

        self._tray.set_listen_checked(self._cfg.listen_enabled)
        self._tray.set_scale_checked(self._cfg.scale)
        self._tray.set_autostart_checked(self._cfg.autostart)
        self._tray.set_bubble_checked(self._cfg.bubble_enabled)
        self._tray.set_reduce_motion_checked(self._cfg.reduce_motion)
        self._load_japanese()
        self._load_word_details()
        self._tray.set_jp_checked(self._cfg.jp_enabled)
        self._tray.set_jp_level_checked(self._cfg.jp_level)
        self._tray.set_jp_duration_checked(self._cfg.jp_bubble_duration_s)
        self._tray.set_jp_daily_limit_checked(self._cfg.jp_daily_limit)
        self._tray.set_jp_enabled(self._cfg.jp_enabled)
        self._tray.show()
        self._notify_jp_startup_state()

        self._window.show()
        self._window.raise_()

        self._model.set_base_expression(expression_for_mood(self._sm.mood))
        self._model.set_reduce_motion(self._cfg.reduce_motion)
        # 气泡打字感（阶段 B2-3）：reduce_motion 开启时跳过逐字、直接全显
        self._bubble.set_reduce_motion(self._cfg.reduce_motion)
        self._window.set_fps(C.FPS_IDLE)
        self._window.start_animation()

        if self._cfg.listen_enabled:
            self._keyboard.start()
        else:
            logger.info("配置为不启用键盘监听")

        now = time.monotonic()
        self._last_frame_ts = now
        self._next_yawn_ts = now + motion.random_interval(C.YAWN_MIN_S, C.YAWN_MAX_S)
        # 首条自动闲聊排在启动 20~60s 后（启动瞬间不说话，两条闲聊之间同为此随机间隔）
        self._next_bubble_ts = now + motion.random_interval(
            C.BUBBLE_MIN_INTERVAL_S, C.BUBBLE_MAX_INTERVAL_S, self._rng
        )
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
            self._theme_timer.stop()
        except Exception:  # noqa: BLE001
            logger.exception("停止主题重估定时器失败")
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
            self._button_bar.hide_bar()
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
        self._tray.bubble_text_requested.connect(self._on_bubble_text_settings)
        self._tray.scale_selected.connect(self._apply_scale)
        self._tray.minimize_requested.connect(self._on_minimize)
        self._tray.restore_requested.connect(self._on_restore)
        self._tray.autostart_toggled.connect(self._set_autostart)
        self._tray.reduce_motion_toggled.connect(self._on_reduce_motion_toggled)
        self._tray.theme_selected.connect(self._on_theme_selected)
        self._tray.skin_selected.connect(self._on_skin_selected)
        self._tray.quit_requested.connect(self.shutdown)

        # 日语学习
        self._tray.jp_enabled_toggled.connect(self._on_jp_toggled)
        self._tray.jp_level_selected.connect(self._on_jp_level_selected)
        self._tray.jp_duration_selected.connect(self._on_jp_duration_selected)
        self._tray.jp_daily_limit_selected.connect(self._on_jp_daily_limit_selected)
        self._tray.jp_show_now_requested.connect(self._on_jp_show_now)
        self._tray.jp_vocab_requested.connect(self._on_jp_vocab)
        self._tray.jp_log_requested.connect(self._on_jp_log)
        self._tray.jp_import_bank_requested.connect(self._on_jp_import_bank)

        # 日语记忆：气泡按钮条（记住了 / 新单词）
        self._button_bar.mastered_clicked.connect(self._on_word_mastered)
        self._button_bar.vocab_clicked.connect(self._on_word_vocab)

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

            # 敲击路径一律走「敲击键盘组」自定义池（keyboard=True，不做关键字过滤），
            # 受**独立的** 20~60s 敲击窗节流（避免「敲一次就弹一次」）：
            # - 键盘专属表情（进专注/兴奋/久违回座/睡觉被吵醒）→ 用该表情键；
            # - 仅情绪态迁移 → 用目标情绪键；
            # - 稳态敲击（无迁移）→ 回落 FOCUS 键：只要真在敲键盘，敲击组文案就会
            #   按节奏出现（需求 C-1「仅在敲击时才允许触发」的正向面——敲了就能看到）。
            if transition.expression in C.KEYBOARD_BUBBLE_EXPRESSIONS:
                key = transition.expression
            elif transition.changed:
                key = transition.to_mood
            else:
                key = Expression.FOCUS
            self._show_bubble_for(key, now, keyboard=True)

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

            # ① 跨日检测：本地自然日变化 → 重置当日状态并立即恢复排期（core 无时钟，日期由 app 判定）
            today = self._local_date_str()
            if today != self._today_str:
                self._today_str = today
                self._today_done_notified = False
                # 跨日：清空内存级「当日手动展示」去重集合（D2，不落盘）
                self._manual_shown_ids_today.clear()
                # 跨日：当日已展示排除集随新日期 key 自然清空，池耗尽可能解除
                self._pool_exhausted = False
                self._next_word_ts = now
                # 跨日 → 顺带重估主题（保证跨月零点自动换肤，而非最多等一天）
                self._recheck_theme()

            # ② 超时检测：当前词到点未处置 → 记「未处理」（与按钮点击单飞互斥）
            if (
                self._current_word is not None
                and not self._word_disposed
                and now >= self._word_deadline
            ):
                self._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, now)

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

            # 自动触发节奏（需求 C-2：20~60s 随机的**递归排期**）——窗口到点就主动
            # 展示一条自动组文案，安静待机时宠物也会说话（迁移/呵欠只是在窗口开放
            # 时抢先供词，展示成功即重排窗口）。睡觉态不闲聊但跳过本周期（防醒来
            # 瞬间连弹）；被单词泡泡 / 气泡开关抑制时不推进窗口，解除后下一帧补上。
            if now >= self._next_bubble_ts:
                if self._sm.mood == Mood.SLEEP:
                    self._next_bubble_ts = now + motion.random_interval(
                        C.BUBBLE_MIN_INTERVAL_S, C.BUBBLE_MAX_INTERVAL_S, self._rng
                    )
                else:
                    self._show_bubble_for(self._sm.mood, now)

            # 学习模式：独立随机节奏（30~600s）展示日语单词（挂在既有帧循环，不新开 QTimer）
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
            # 鼠标来源一律 immediate：保留「鼠标移到宠物上立即显示一条文案」的行为，
            # 不受 20~60s 自动节奏窗口约束（仅受 BUBBLE_MIN_GAP_S 硬下限保护，防连弹）。
            if gesture == Gesture.CLICK:
                self._model.trigger_click()
                self._active_until = now + C.CLICK_ANIM_S
                self._show_bubble_for(Expression.HAPPY, now, immediate=True)
            elif gesture == Gesture.HOVER:
                self._active_until = now + _ACTIVE_HOLD_S
                self._show_bubble_for(Expression.HAPPY, now, immediate=True)

            transition = self._sm.on_gesture(gesture, now)
            self._sync_fps_and_visuals(transition)
        except Exception:  # noqa: BLE001
            logger.exception("处理鼠标手势异常（已忽略）")

    def _on_position_changed(self, x: int, y: int) -> None:
        """窗口拖动中：仅更新内存位置（松手后再落盘，避免频繁写盘）。"""

        self._cfg.window_x = int(x)
        self._cfg.window_y = int(y)

    def _on_drag_finished(self, x: int, y: int) -> None:
        """拖拽结束：越界钳制（FR-36）后**重锚**并持久化（G2）。"""

        try:
            cx, cy = motion.clamp_to_screens(
                x, y, self._window.width(), self._window.height(),
                self._screen_geometries(), self._primary_geometry(),
            )
            # 重锚：拖拽后的落点成为新锚点、瞬态游走偏移归零（set_anchor 同时移动窗口）。
            self._window.set_anchor(cx, cy)
            self._anchor_x, self._anchor_y = cx, cy
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

    def _on_bubble_text_settings(self) -> None:
        """打开「气泡文案」设置对话框（单例，重开则前置）。"""

        try:
            if self._bubble_text_dialog is None:
                self._bubble_text_dialog = BubbleTextDialog()
                self._bubble_text_dialog.applied.connect(self._on_bubble_text_applied)
            dialog = self._bubble_text_dialog
            dialog.load_state(
                self._cfg.bubble_text_pack,
                self._cfg.bubble_texts_custom,
                self._cfg.bubble_texts_custom_keyboard,
            )
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception:  # noqa: BLE001
            logger.exception("打开气泡文案设置异常（已忽略）")

    def _on_bubble_text_applied(
        self, pack: str, custom_texts: list, custom_keyboard_texts: list
    ) -> None:
        """台词设置确认：写配置 → 落地 → 通知（即改即生效，无需重启）。

        两组自定义池**一次事务写入**（自动触发组 + 敲击键盘组），避免只更新一组
        造成两组语义错位。

        清洗复用 config 的 coerce 规则（经 ``from_dict``，单一事实源）——
        对话框虽已清洗，此处兜底防其它调用方传入脏数据。
        """

        try:
            if pack in C.BUBBLE_TEXT_PACK_ALLOWED:
                self._cfg.bubble_text_pack = str(pack)
            cleaned = AppConfig.from_dict(
                {
                    "bubble_texts_custom": list(custom_texts or []),
                    "bubble_texts_custom_keyboard": list(custom_keyboard_texts or []),
                }
            )
            self._cfg.bubble_texts_custom = cleaned.bubble_texts_custom
            self._cfg.bubble_texts_custom_keyboard = cleaned.bubble_texts_custom_keyboard
            self._persist()
            self._tray.notify(C.APP_DISPLAY_NAME, C.TRAY_NOTIFY_BUBBLE_TEXT_SAVED)
        except Exception:  # noqa: BLE001
            logger.exception("应用气泡文案设置异常（已忽略）")

    def _on_reduce_motion_toggled(self, checked: bool) -> None:
        """切换「减少动效」开关（对应 prefers-reduced-motion）。

        配置为**唯一真相源**：三个业务窗口在每次 ``show`` 前都会读取
        ``self._cfg.reduce_motion``，此处只需更新配置、落地并同步**已存在**的窗口，
        保证开关即时生效而不必重开窗口。
        """

        enabled = bool(checked)
        self._cfg.reduce_motion = enabled
        self._tray.set_reduce_motion_checked(enabled)
        self._apply_reduce_motion_to_windows(enabled)
        self._model.set_reduce_motion(enabled)
        self._bubble.set_reduce_motion(enabled)
        self._persist()
        self._tray.notify(
            C.APP_DISPLAY_NAME,
            C.TRAY_NOTIFY_REDUCE_MOTION_ON if enabled else C.TRAY_NOTIFY_REDUCE_MOTION_OFF,
        )

    def _apply_reduce_motion_to_windows(self, enabled: bool) -> None:
        """把「减少动效」同步到已创建的业务窗口（未创建则跳过，show 时会再读配置）。"""

        for window in (self._vocab_window, self._log_window, self._detail_window):
            if window is None:
                continue
            try:
                window.set_reduce_motion(bool(enabled))
            except Exception:  # noqa: BLE001 —— 单个窗口同步失败不应中断开关切换
                logger.exception("同步「减少动效」到窗口失败：%r", window)

    def _on_theme_selected(self, value: str) -> None:
        """切换主题皮肤（托盘「主题」子菜单，单选）。

        写 ``cfg.theme`` → 应用（渲染器取色 + 托盘图标 + 托盘勾选）→ 落地配置。
        整窗 ``update()`` 已在 :meth:`_apply_theme` 内完成（防脏区残留，v1.1 风险 11）。
        """

        value = str(value)
        if value not in C.THEME_ALLOWED:
            return
        self._cfg.theme = value
        self._apply_theme()
        self._persist()

    def _on_skin_selected(self, value: str) -> None:
        """切换皮肤包（托盘「皮肤」子菜单，单选）。

        写 ``cfg.skin_name`` → 重建渲染器并热替换到窗口 → 同步菜单勾选 → 落地配置。
        指定包不存在时 ``build_skin_renderer`` 回落到自动选择（不报错，仅记日志），
        勾选态也随 :meth:`TrayController.set_skin_checked` 同步为「自动」。
        """

        value = str(value)
        self._cfg.skin_name = value
        new_renderer = build_skin_renderer(value)
        self._skin_renderer = new_renderer
        self._window.set_skin_renderer(new_renderer)
        self._tray.set_skin_checked(value)
        self._persist()
        if new_renderer is not None:
            self._tray.notify(
                C.APP_DISPLAY_NAME,
                C.TRAY_NOTIFY_SKIN_APPLIED.format(name=new_renderer.pack_name),
            )
        elif value not in (C.SKIN_NAME_AUTO, C.SKIN_NAME_VECTOR):
            self._tray.notify(
                C.APP_DISPLAY_NAME, C.TRAY_NOTIFY_SKIN_FALLBACK.format(name=value)
            )
        logger.info("皮肤包切换：%s → %s", value, getattr(new_renderer, "pack_name", "矢量"))

    def reveal(self) -> None:
        """让宠物显形并前置（供单实例守卫在二次启动时调用，也用于外部唤起）。

        与 :meth:`_on_restore` 的区别：额外 ``activateWindow()`` —— 用户此时
        刚双击了 exe，期望窗口立刻到前台，而不只是「已在显示」。
        """

        self._on_restore()
        try:
            self._window.activateWindow()
        except Exception:  # noqa: BLE001
            logger.debug("前置宠物窗口失败（已忽略）", exc_info=True)

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
            self._window.set_anchor(cx, cy)
            self._anchor_x, self._anchor_y = cx, cy
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
        """启动时加载内置词库、生词本、已掌握集合与每日记录（损坏均优雅降级，绝不崩溃）。"""

        try:
            self._bank = WordBank.load(paths.word_bank_path())
        except Exception:  # noqa: BLE001
            logger.exception("加载词库失败（已忽略，使用空词库）")
            self._bank = WordBank.empty()

        # 外置词库（用户导入，%APPDATA%\desktop-pet\jlpt_words_extra.json）：
        # 存在则按 id 合并覆盖进内置词库；损坏 / 结构不符仅告警，不影响启动。
        try:
            extra_path = paths.extra_word_bank_path()
            if extra_path.exists():
                extra_entries, extra_skipped = parse_bank_file(extra_path)
                self._bank.merge(extra_entries)
                logger.info(
                    "外置词库已合并：%s（有效 %d 条，跳过 %d 条）",
                    extra_path, len(extra_entries), extra_skipped,
                )
        except WordBankParseError as exc:
            logger.warning("外置词库不可用（%s）：%s", exc, paths.extra_word_bank_path())
        except Exception:  # noqa: BLE001
            logger.exception("合并外置词库失败（已忽略内置词库继续可用）")

        self._picker = WeightedWordPicker(self._bank, self._rng)

        try:
            self._vocab = VocabStore(VocabStore.default_path())
            self._vocab.load()
        except Exception:  # noqa: BLE001
            logger.exception("加载生词本失败（已忽略，使用空生词本）")
            self._vocab = VocabStore(VocabStore.default_path())

        try:
            self._mastered = MasteredStore(MasteredStore.default_path())
            self._mastered.load()
        except Exception:  # noqa: BLE001
            logger.exception("加载已掌握集合失败（已忽略，使用空集合）")
            self._mastered = MasteredStore(MasteredStore.default_path())

        try:
            self._daily_log = DailyLogStore(DailyLogStore.default_path())
            self._daily_log.load()
        except Exception:  # noqa: BLE001
            logger.exception("加载每日记录失败（已忽略，使用空表）")
            self._daily_log = DailyLogStore(DailyLogStore.default_path())

    def _load_word_details(self) -> None:
        """启动时加载打包详情库（只读）与用户缓存；损坏均优雅降级，绝不崩溃。"""

        try:
            self._detail_bank = WordDetailBank.load(paths.word_details_path())
        except Exception:  # noqa: BLE001
            logger.exception("加载中文详情库失败（已忽略，使用空详情库）")
            self._detail_bank = WordDetailBank.empty()

        try:
            self._detail_cache = WordDetailsCacheStore(WordDetailsCacheStore.default_path())
            self._detail_cache.load()
        except Exception:  # noqa: BLE001
            logger.exception("加载中文详情缓存失败（已忽略，使用空缓存）")
            self._detail_cache = WordDetailsCacheStore(WordDetailsCacheStore.default_path())

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
        """按 30~600s 随机间隔排期下一次单词展示（学习关闭时置 ``inf`` 不触发）。

        候选池耗尽（:data:`_pool_exhausted`）时同样置 ``inf``：耗尽后每次到点
        抽取必然落空，继续排期只是空转；恢复由等级切换 / 导入词库 / 跨日驱动。
        """

        if self._cfg.jp_enabled and not self._bank.is_empty() and not self._pool_exhausted:
            self._next_word_ts = now + motion.random_interval(
                C.JP_WORD_MIN_INTERVAL_S, C.JP_WORD_MAX_INTERVAL_S, self._rng
            )
        else:
            self._next_word_ts = float("inf")

    def _show_word_bubble(
        self, now: float, *, bypass_gap: bool = False, manual: bool = False
    ) -> None:
        """记忆闭环：停止判定 → 加权抽取 → 展示学习泡泡 + 按钮条（受多重守卫约束）。

        Args:
            now: 当前时刻（秒）。
            bypass_gap: ``True`` 时跳过 ``BUBBLE_MIN_GAP_S`` 最小间隔（「立即显示」用），
                仍保留睡觉 / 气泡关 / 词库空守卫。
            manual: ``True`` 表示本次展示来自手动「立即显示」路径（用户决策：手动点击为
                显式意图，不受每日配额约束，且其处置不计入每日数量统计）。
                **仅手动路径可传 True**；自动排期路径必须保持 ``False``，严格遵守上限。
        """

        # 守卫：已有词在展示时不重复抽取；气泡关闭 / 睡觉 / 最小间隔不展示
        if self._current_word is not None:
            return
        if not self._cfg.bubble_enabled:
            return
        if self._sm.mood == Mood.SLEEP:
            return
        if not bypass_gap and (now - self._last_bubble_ts) < C.BUBBLE_MIN_GAP_S:
            return

        if not self._today_str:
            self._today_str = self._local_date_str()

        # 停止判定：达到每日上限 → 一次性通知后今日不再弹
        # 仅自动路径受限；手动「立即显示」传 manual=True 可突破（用户决策）
        if not manual and self._jp_stop_for_today():
            if not self._today_done_notified:
                self._today_done_notified = True
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_TODAY_DONE)
            return

        today = self._today_str
        # 排除集合：已掌握 + 当日已展示（落库）+ 当日手动展示过（D2，内存级去重）
        excluded = (
            self._mastered.ids()
            | self._daily_log.shown_ids_for(today)
            | self._manual_shown_ids_today
        )
        vocab_ids = {item.id for item in self._vocab.items()}
        entry = self._picker.pick(self._cfg.jp_level, excluded, vocab_ids)
        if entry is None:
            # 池耗尽：置排期停转标志（手动/自动路径状态一致，恢复由等级切换 /
            # 导入词库 / 跨日驱动）；手动路径给专用反馈，自动路径保持既有
            # 「等级掌握」一次性通知。
            self._pool_exhausted = True
            if manual:
                self._tray.notify(
                    C.APP_DISPLAY_NAME,
                    C.JP_NOTIFY_POOL_EXHAUSTED.format(level=self._cfg.jp_level),
                )
            elif not self._bank.is_empty() and not self._level_done_notified:
                self._level_done_notified = True
                logger.warning("该等级单词已全部掌握（level=%s）", self._cfg.jp_level)
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_LEVEL_DONE)
            return
        self._pool_exhausted = False

        # 单飞状态机：置当前词 / deadline / 未处置标志 + 手动标记（供 _dispose_word 判定）
        self._current_word = entry
        self._word_deadline = now + self._cfg.jp_bubble_duration_s
        self._word_disposed = False
        self._word_manual = manual

        anchor = self._bubble_anchor()
        self._bubble.set_anchor(anchor)
        self._bubble.show_word(entry, self._cfg.jp_bubble_duration_s)
        self._button_bar.show_bar(
            anchor,
            self._bubble.geometry(),
            self._bubble.pointing_down(),
            self._cfg.jp_bubble_duration_s,
        )
        self._last_bubble_ts = now

    def _on_jp_toggled(self, checked: bool) -> None:
        """切换「日语学习」开关（JP-02）。"""

        checked = bool(checked)
        self._cfg.jp_enabled = checked
        self._tray.set_jp_enabled(checked)
        now = time.monotonic()
        if checked:
            self._level_done_notified = False
            self._pool_exhausted = False
            self._schedule_next_word(now)
            if not self._cfg.bubble_enabled:
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_NEED_BUBBLE)
            elif self._bank.is_empty():
                self._bank_warned = True
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_BANK_UNAVAILABLE)
        else:
            self._next_word_ts = float("inf")
            # 关闭学习时若仍有展示词：清理气泡/按钮条（不落库，用户主动关闭）
            if self._current_word is not None:
                self._bubble.hide_bubble()
                self._button_bar.hide_bar()
                self._current_word = None
                self._word_deadline = float("inf")
                self._word_disposed = True
                self._word_manual = False
        self._persist()

    def _on_jp_level_selected(self, level: str) -> None:
        """切换难度等级（JP-06，单选，持久化）。"""

        level = str(level)
        if level not in C.JP_LEVELS:
            return
        self._cfg.jp_level = level
        self._tray.set_jp_level_checked(level)
        self._level_done_notified = False
        # 换难度即换候选池：旧等级耗尽导致的停转在恢复排期后解除（仅耗尽态才
        # 抢跑，避免改变正常态的既有节奏）。
        if self._pool_exhausted:
            self._pool_exhausted = False
            if self._cfg.jp_enabled:
                self._next_word_ts = time.monotonic()
        self._persist()

    def _on_jp_duration_selected(self, value: int) -> None:
        """切换「显示时长」档位（单选，持久化，只信任档位值）。"""

        value = int(value)
        if value not in C.JP_BUBBLE_DURATION_OPTIONS:
            return
        self._cfg.jp_bubble_duration_s = value
        self._tray.set_jp_duration_checked(value)
        self._persist()

    def _on_jp_daily_limit_selected(self, value: int) -> None:
        """切换「每日数量」档位（单选，持久化，只信任档位值）。"""

        value = int(value)
        if value not in C.JP_DAILY_LIMIT_OPTIONS:
            return
        self._cfg.jp_daily_limit = value
        self._tray.set_jp_daily_limit_checked(value)
        self._persist()

    def _on_jp_show_now(self) -> None:
        """托盘「立即显示一个新单词」→ 先等价超时未处理当前词，再立即弹新词（方案 A）。

        用户决策：手动展示不受每日配额约束 —— 已移除「今日已达上限 → 拦截」的判定；
        且手动展示的词在处置时不计入每日数量统计（详见 :meth:`_dispose_word`）。
        每次点击都必须给出可见反馈，严禁静默返回（历史缺陷：与自动路径共用一次性标志位）。
        """

        try:
            now = time.monotonic()
            if not self._cfg.jp_enabled:
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_JP_OFF)
                return
            if not self._cfg.bubble_enabled:
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_NEED_BUBBLE)
                return
            if self._sm.mood == Mood.SLEEP:
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_SHOW_NOW_BLOCKED)
                return
            if self._bank.is_empty():
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_BANK_UNAVAILABLE)
                return

            # 当前词在展示 → 先等价超时落「未处理」；是否计数由 _dispose_word 内的
            # _word_manual 标记天然决定（旧词为自动词则正常计数，为手动词则不计数）。
            if self._current_word is not None and not self._word_disposed:
                self._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, now)

            # manual=True：跳过每日上限停止判定，且处置时不计入每日数量统计
            self._show_word_bubble(now, bypass_gap=True, manual=True)
            if self._current_word is not None:
                today = self._today_str or self._local_date_str()
                count = self._daily_log.count_for(today)
                limit = self._cfg.jp_daily_limit
                # 已达/超出目标时用专用文案（明确「手动显示不计入每日数量」）
                template = (
                    C.JP_NOTIFY_SHOW_NOW_OVER_LIMIT
                    if count >= limit
                    else C.JP_NOTIFY_SHOW_NOW
                )
                self._tray.notify(
                    C.APP_DISPLAY_NAME,
                    template.format(
                        word=self._current_word.word,
                        kana=self._current_word.kana,
                        count=count,
                        limit=limit,
                    ),
                )
        except Exception:  # noqa: BLE001
            logger.exception("立即显示单词异常（已忽略）")
            self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_SHOW_NOW_FAILED)

    def _on_jp_log(self) -> None:
        """打开学习记录窗口（单例，喂入全部日期与当日记录，重开则前置）。"""

        try:
            if self._log_window is None:
                self._log_window = LogWindow()
                self._log_window.set_accent(ui_accent_for_theme(self._current_theme))
                self._log_window.word_double_clicked.connect(self._on_log_word_double_clicked)
            days = self._daily_log.days()
            self._log_window.set_dates(days)
            limit = self._cfg.jp_daily_limit
            today = self._local_date_str()
            for day in days:
                self._log_window.refresh(day, self._daily_log.entries_for(day), limit)
            # 保证「今天」始终可选中（即使今日暂无记录）
            self._log_window.refresh(today, self._daily_log.entries_for(today), limit)
            self._log_window.set_reduce_motion(self._cfg.reduce_motion)
            show_window_animated(self._log_window, self._cfg.reduce_motion)
            self._log_window.raise_()
            self._log_window.activateWindow()
        except Exception:  # noqa: BLE001
            logger.exception("打开学习记录窗口异常（已忽略）")

    def _on_jp_import_bank(self) -> None:
        """托盘「导入词库…」：校验 → 拷贝到 %APPDATA% → 合并进当前词库 → 通知。

        导入词库同时是「等级学完」的官方解法：合并产生新增/更新后复位池耗尽与
        一次性通知标志并恢复排期。每次点击都必须给出可见反馈，严禁静默返回。
        """

        try:
            src_name, _filter = QFileDialog.getOpenFileName(
                None,
                C.JP_IMPORT_DIALOG_TITLE,
                "",
                C.JP_IMPORT_DIALOG_FILTER,
            )
            if not src_name:
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_BANK_IMPORT_CANCELLED)
                return

            entries, skipped = parse_bank_file(Path(src_name))

            # 先落盘为外置词库（下次启动自动合并），再合并进运行中的词库。
            dest = paths.extra_word_bank_path()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_name, dest)
            added, updated = self._bank.merge(entries)
            self._picker = WeightedWordPicker(self._bank, self._rng)

            if added or updated:
                self._pool_exhausted = False
                self._level_done_notified = False
                if self._cfg.jp_enabled:
                    self._next_word_ts = time.monotonic()

            logger.info(
                "导入词库：%s（新增 %d，更新 %d，跳过 %d）→ %s",
                src_name, added, updated, skipped, dest,
            )
            self._tray.notify(
                C.APP_DISPLAY_NAME,
                C.JP_NOTIFY_BANK_IMPORTED.format(
                    added=added, updated=updated, skipped=skipped
                ),
            )
        except WordBankParseError as exc:
            logger.warning("导入词库被拒绝：%s", exc)
            self._tray.notify(
                C.APP_DISPLAY_NAME,
                C.JP_NOTIFY_BANK_IMPORT_FAILED.format(reason=exc),
            )
        except Exception:  # noqa: BLE001
            logger.exception("导入词库异常")
            self._tray.notify(
                C.APP_DISPLAY_NAME,
                C.JP_NOTIFY_BANK_IMPORT_FAILED.format(reason="未知错误，请稍后重试"),
            )

    def _on_jp_vocab(self) -> None:
        """打开生词本窗口（单例，重开则前置）。"""

        try:
            if self._vocab_window is None:
                self._vocab_window = VocabWindow()
                self._vocab_window.set_accent(ui_accent_for_theme(self._current_theme))
                self._vocab_window.remove_requested.connect(self._on_vocab_remove)
                self._vocab_window.clear_requested.connect(self._on_vocab_clear)
                self._vocab_window.word_double_clicked.connect(self._on_vocab_word_double_clicked)
            self._vocab_window.refresh(self._vocab.items())
            self._vocab_window.set_reduce_motion(self._cfg.reduce_motion)
            show_window_animated(self._vocab_window, self._cfg.reduce_motion)
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

    def _local_date_str(self) -> str:
        """返回本地自然日字符串 ``YYYY-MM-DD``（仅 app 层使用 ``datetime``）。"""

        return datetime.now().strftime("%Y-%m-%d")

    def _jp_stop_for_today(self) -> bool:
        """当日停止判定：仅达到每日上限时停止。

        不再用 ``all_mastered``（「当日已展示词全部点了掌握」）作为早停条件——
        那会让用户对第一个展示词点一次「记住了」就误判为「全部掌握」、当天后续
        单词全部停摆（跨天才恢复）。「当前等级词库已全部掌握」这一语义已由
        :meth:`_show_word_bubble` 中 :meth:`WeightedWordPicker.pick` 返回 ``None``
        的分支正确兜底，无需在此重复判定。
        """

        today = self._today_str or self._local_date_str()
        return self._daily_log.count_for(today) >= self._cfg.jp_daily_limit

    def _dispose_word(self, status: str, now: float) -> None:
        """单飞处置当前展示词（三态互斥：一次展示恰好落一种终态）。

        帧循环超时与按钮点击都在 Qt 主线程内串行执行，``_word_disposed`` 保证「先到先得、
        后到即 no-op」。处置后落库、清状态并排期下一词。
        """

        # 1) 单飞守卫：同词二次处置直接丢弃
        if self._word_disposed:
            return
        entry = self._current_word
        if entry is None:
            return

        # 2) 置已处置标志，杜绝竞态；读取并即刻复位「手动展示」标记
        #    （末尾会排期下一词 / 或被守卫提前 return，标记不残留污染下次自动展示）
        self._word_disposed = True
        manual = self._word_manual
        self._word_manual = False

        # 3) 立即隐藏气泡与按钮条
        self._bubble.hide_bubble()
        self._button_bar.hide_bar()

        # 4) 落库（today 为本地自然日 key，由 app 注入 core）
        #    解耦规则：手动展示的词仍写长期数据（mastered / vocab，用户决策 D1），
        #    但**不计入每日数量统计**（每日配额只由正常自动流程触发，用户决策 R1/R2）。
        today = self._today_str or self._local_date_str()
        iso = self._now_iso()
        if status == C.DAILY_LOG_STATUS_MASTERED:
            added = self._mastered.add(entry, iso)
            if not manual:
                self._daily_log.add_entry(
                    today, DailyLogEntry.from_entry(entry, iso, status)
                )
            if added:
                self._tray.notify(
                    C.APP_DISPLAY_NAME,
                    C.JP_NOTIFY_MASTERED_ADDED.format(word=entry.word, kana=entry.kana),
                )
            else:
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_MASTERED_DUPLICATE)
        elif status == C.DAILY_LOG_STATUS_VOCAB:
            added = self._vocab.add(entry, iso)
            if not manual:
                self._daily_log.add_entry(
                    today, DailyLogEntry.from_entry(entry, iso, status)
                )
            if added:
                self._tray.notify(
                    C.APP_DISPLAY_NAME,
                    C.JP_NOTIFY_REMEMBER_ADDED.format(word=entry.word, kana=entry.kana),
                )
            else:
                self._tray.notify(C.APP_DISPLAY_NAME, C.JP_NOTIFY_REMEMBER_DUPLICATE)
            if self._vocab_window is not None:
                self._vocab_window.refresh(self._vocab.items())
        elif status == C.DAILY_LOG_STATUS_UNPROCESSED:
            if not manual:
                self._daily_log.add_entry(
                    today, DailyLogEntry.from_entry(entry, iso, status)
                )

        # 5) D2：手动词并入「当日不重复展示」去重集合（内存级、不落盘、不计入 count）
        if manual:
            self._manual_shown_ids_today.add(entry.id)

        # 6) 清状态
        self._current_word = None
        self._word_deadline = float("inf")

        # 7) 排期下一词
        self._schedule_next_word(now)

    def _on_word_mastered(self) -> None:
        """气泡「记住了」按钮 → 处置为已掌握。"""

        self._dispose_word(C.DAILY_LOG_STATUS_MASTERED, time.monotonic())

    def _on_word_vocab(self) -> None:
        """气泡「新单词」按钮 → 处置为生词。"""

        self._dispose_word(C.DAILY_LOG_STATUS_VOCAB, time.monotonic())

    def _now_iso(self) -> str:
        """返回当前 UTC 墙钟时间的 ISO8601 字符串（仅 app 层生成，注入 core）。"""

        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------ #
    # 内部：单词详情（中文五要素）—— 打包库 / 用户缓存 / DeepSeek 联网 + 窗口单例
    # ------------------------------------------------------------------ #
    def _on_log_word_double_clicked(self, item_id: str) -> None:
        """学习记录双击 → 按 id 还原词条并打开详情窗口。"""

        entry = self._bank.entry_by_id(str(item_id))
        if entry is not None:
            self._open_word_detail(entry)

    def _on_vocab_word_double_clicked(self, item_id: str) -> None:
        """生词本双击 → 优先词库还原，找不到用 VocabItem 字段兜底（romaji=""）。"""

        item_id = str(item_id)
        entry = self._bank.entry_by_id(item_id)
        if entry is None:
            for item in self._vocab.items():
                if item.id == item_id:
                    entry = VocabEntry(
                        id=item.id,
                        level=item.level,
                        word=item.word,
                        kana=item.kana,
                        translation=item.translation,
                        meaning=item.meaning,
                        romaji="",
                    )
                    break
        if entry is not None:
            self._open_word_detail(entry)

    def _open_word_detail(self, entry: VocabEntry) -> None:
        """打开中文详情窗口（单例）：打包库优先 → 缓存补充 → 联网兜底。"""

        try:
            if entry is None:
                return
            if self._detail_window is None:
                self._detail_window = WordDetailWindow()
                self._detail_window.set_accent(ui_accent_for_theme(self._current_theme))
                self._detail_window.detail_succeeded.connect(self._on_detail_succeeded)
                self._detail_window.detail_failed.connect(self._on_detail_failed)
            detail, source = self._lookup_word_detail(entry.id)
            net = self._detail_net_config()
            # 动效开关须在 show_entry **之前**注入：show_entry 的加载分支（联网态）会读取
            # _reduce_motion 决定 set_loading 是否创建标签淡入动画。顺序与 _on_jp_log /
            # _on_jp_vocab 保持一致；否则 reduce_motion=True 时首开详情窗仍会创建一个动画。
            self._detail_window.set_reduce_motion(self._cfg.reduce_motion)
            self._detail_window.show_entry(entry, detail, source, net)
            show_window_animated(self._detail_window, self._cfg.reduce_motion)
            self._detail_window.raise_()
            self._detail_window.activateWindow()
        except Exception:  # noqa: BLE001
            logger.exception("打开单词详情窗口异常（已忽略）")

    def _lookup_word_detail(self, item_id: str) -> tuple[WordDetail | None, str | None]:
        """返回详情与来源：打包库优先（权威只读）→ 用户缓存补充。

        打包库是经审核的权威版本，发布新版本即应生效，不被用户旧联网结果遮挡；
        缓存只补充「打包库未收录」的冷门词。均未命中返回 ``(None, None)``。
        """

        item_id = str(item_id)
        if not item_id:
            return None, None
        detail = self._detail_bank.get(item_id)
        if detail is not None:
            return detail, C.WORD_DETAIL_SOURCE_LOCAL
        item = self._detail_cache.get(item_id)
        if item is not None and not item.detail.is_empty():
            return item.detail, C.WORD_DETAIL_SOURCE_CACHE
        return None, None

    def _detail_net_config(self) -> WordDetailNetConfig:
        """从当前配置**现取现构**联网参数（保证运行时改配置即时生效）。"""

        return WordDetailNetConfig(
            api_key=self._cfg.deepseek_api_key,
            base_url=self._cfg.deepseek_base_url,
            model=self._cfg.deepseek_model,
            timeout_s=self._cfg.word_detail_llm_timeout_s,
            retries=self._cfg.word_detail_llm_retries,
        )

    def _on_detail_succeeded(self, item_id: str, detail: WordDetail) -> None:
        """联网成功回调：写用户缓存（``fetched_at`` 由 app 层注入）并落盘。"""

        try:
            if detail is None or detail.is_empty():
                return
            self._detail_cache.put(str(item_id), detail, self._now_iso())
        except Exception:  # noqa: BLE001
            logger.exception("写入中文详情缓存异常（已忽略）")

    def _on_detail_failed(self, item_id: str, msg: str) -> None:
        """联网失败回调：仅记日志（窗口已做中文降级展示）。"""

        logger.info("详情联网失败（%s）：%s", item_id, msg)

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

    def _show_bubble_for(
        self,
        key: Expression | Mood,
        now: float | None = None,
        *,
        immediate: bool = False,
        keyboard: bool = False,
    ) -> bool:
        """按表情/情绪态随机展示气泡（受开关、硬下限与节奏窗口约束，FR-30）。

        触发节奏（2026-09-26 需求 C 重做：20~60s 随机是「排期」而不只是「节流」）：

        - **自动来源**（帧循环排期器 / 状态机迁移 / 休息态呵欠）：共享**自动窗**
          ``_next_bubble_ts``。帧循环到点必主动展示一条；迁移/呵欠只是恰好在窗口
          开放时抢先供词。任一次成功展示都把窗口重排为 ``now + 20~60s`` 随机，
          因此安静待机时宠物也会每 20~60 秒说一句话。
        - **键盘敲击**（``keyboard=True``，仅全局键盘监听）：走**独立的敲击窗**
          ``_next_kb_bubble_ts``（同样 20~60s 随机）。稳态敲击（无情绪迁移）也
          会触发——真在敲键盘时敲击组文案按节奏可靠出现，又不刷屏。
        - **鼠标来源**（悬停抚摸 / 点击）：``immediate=True``，跳过两个窗口立即
          显示（保留「鼠标移到宠物上立即显示一条」）；仍受 ``BUBBLE_MIN_GAP_S``
          硬下限保护，且展示后推迟自动窗（避免「刚摸一下就被自动闲聊紧跟一条」）。

        文案来源（2026-09-26 需求 C，按**触发源**选池 + 关键字门控）：

        - ``keyboard=True``（仅全局键盘监听）→ 敲击键盘组自定义池，不做关键字过滤；
        - ``keyboard=False``（其余全部来源，含鼠标 immediate）→ 自动触发组自定义池，
          **过滤掉含键盘关键字的条目**；过滤后为空则回落预设包（同样过滤）。
          因此「鼠标移到宠物上」看到的文案一定不含「键盘」等键盘关键字。

        Args:
            key: ``Expression`` 或 ``Mood``（作为文案表索引）。
            now: 当前时刻（秒）。若为 ``None`` 则自行读取。
            immediate: ``True`` = 用户主动的鼠标交互，跳过两个节奏窗口。
            keyboard: ``True`` = 本次展示由真实键盘敲击驱动（决定用哪个窗口与自定义池）。

        Returns:
            ``True`` = 本次成功展示（相应窗口已重排）；``False`` = 被守卫拦下
            （调用方据此决定是否保持排期重试，见帧循环排期器）。
        """

        if not self._cfg.bubble_enabled:
            return False
        # 学习词展示期间抑制情绪气泡（避免覆盖「展示 → 标记」闭环，设计 §1.5）
        if self._current_word is not None:
            return False
        now = float(now) if now is not None else time.monotonic()
        # ① 硬下限：任何来源都必须满足，防止敲击/迁移同帧叠加或鼠标反复进出连弹
        if (now - self._last_bubble_ts) < C.BUBBLE_MIN_GAP_S:
            return False
        # ② 节奏窗口（20 秒 ~ 1 分钟随机）：鼠标 immediate 不受限；键盘敲击走
        #    独立敲击窗，与自动窗互不挤占
        if not immediate:
            window = self._next_kb_bubble_ts if keyboard else self._next_bubble_ts
            if now < window:
                return False
        texts = self._bubble_texts_for(key, keyboard=keyboard)
        if not texts:
            return False
        text = self._rng.choice(texts)
        self._bubble.set_anchor(self._bubble_anchor())
        duration = motion.random_interval(
            C.BUBBLE_MIN_DURATION_S, C.BUBBLE_MAX_DURATION_S, self._rng
        )
        self._bubble.show_message(text, duration)
        self._last_bubble_ts = now
        # ③ 展示成功后重排对应窗口（20~60s 随机）。鼠标 immediate 用的是自动组
        #    文案，故推迟自动窗；敲击窗不受鼠标交互影响（两组各自独立节奏）。
        interval = motion.random_interval(
            C.BUBBLE_MIN_INTERVAL_S, C.BUBBLE_MAX_INTERVAL_S, self._rng
        )
        if keyboard:
            self._next_kb_bubble_ts = now + interval
        else:
            self._next_bubble_ts = now + interval
        return True

    def _bubble_texts_for(
        self, key: Expression | Mood, *, keyboard: bool = False
    ) -> list[str] | None:
        """情绪气泡的台词来源（按**触发源**选池，需求 C-1 / C-3 / C-4）。

        两类触发源各自独立选池：

        - ``keyboard=True``（仅全局键盘监听路径）：敲击键盘组自定义池 > 预设台词包
          > 内置表；**不做**键盘关键字过滤 —— 敲击时看到键盘文案才自然。
        - ``keyboard=False``（状态机迁移 / 休息态呵欠 / 鼠标悬停与点击）：自动触发组
          自定义池 > 预设台词包 > 内置表；**每一级都剔除含键盘关键字的条目**
          （:func:`constants.filter_keyboard_texts`）。自动组被过滤空时视为「未配置」，
          继续回落预设包 —— 否则用户误把键盘文案放进自动组就会完全看不到自动气泡。

        Args:
            key: 文案索引（``Expression`` 或 ``Mood``）。
            keyboard: 是否由真实键盘敲击驱动。

        Returns:
            可选台词列表；``None`` / 空列表表示本键无可用台词（调用方放弃展示）。
            现读 ``self._cfg``：台词设置对话框确认后**即改即生效**，无需重启。
            只影响情绪气泡；单词泡泡（``show_word``）与日语学习模块零关联。
        """

        cfg = self._cfg
        if keyboard:
            if cfg.bubble_texts_custom_keyboard:
                return list(cfg.bubble_texts_custom_keyboard)
        else:
            auto_texts = C.filter_keyboard_texts(cfg.bubble_texts_custom)
            if auto_texts:
                return auto_texts

        texts = C.BUBBLE_TEXT_PACKS.get(cfg.bubble_text_pack, {}).get(key) or C.BUBBLE_TEXTS.get(
            key
        )
        if not texts:
            return None
        if not keyboard:
            texts = C.filter_keyboard_texts(texts)
        return texts or None

    def _bubble_anchor(self) -> QPoint:
        """计算气泡锚点（宠物头顶的全局坐标）。"""

        width = self._window.width()
        height = self._window.height()
        return self._window.mapToGlobal(QPoint(int(width * 0.5), int(height * 0.06)))

    def _apply_theme(self) -> None:
        """按「用户选择 + 当前月份」解析并应用主题（渲染器取色 + 托盘图标）。

        这是 **app 层唯一的月份来源**（``time.localtime().tm_mon``）——core 层零 ``time``，
        月份在此注入 :func:`resolve_theme`。切换后整窗 ``update()`` 一次（非脏区），
        防止主题变更瞬间脏区残留（v1.1 风险 11）。
        """

        try:
            name = resolve_theme(time.localtime().tm_mon, self._cfg.theme)
            self._current_theme = name
            self._renderer.set_theme(name)
            self._refresh_tray_icon(name)
            self._tray.set_theme_checked(self._cfg.theme)
            self._tray.set_skin_checked(self._cfg.skin_name)
            self._apply_ui_accent()
            self._window.update()
        except Exception:  # noqa: BLE001
            logger.exception("应用主题失败（已忽略）")

    def _recheck_theme(self) -> None:
        """周期重估主题（每日定时器 + 跨日检测调用）；仅当生效皮肤变化时才更新。

        这样 ``auto`` 档在跨月后会自动换肤（月份由 app 层读取并注入）。
        """

        try:
            name = resolve_theme(time.localtime().tm_mon, self._cfg.theme)
            if name == self._current_theme:
                return
            self._current_theme = name
            self._renderer.set_theme(name)
            self._refresh_tray_icon(name)
            self._apply_ui_accent()
            self._window.update()
        except Exception:  # noqa: BLE001
            logger.exception("重估主题失败（已忽略）")

    def _apply_ui_accent(self) -> None:
        """把当前主题的点缀色应用到已创建的业务窗口（换肤即点即生效）。

        点缀只落在 Tab 选中 / 卡片选中描边 / 词性下划线等小面积元素；窗口尚未
        创建时跳过——懒加载创建点（_on_jp_vocab / _on_jp_log / _open_word_detail）
        会补一次 :meth:`set_accent`。
        """

        try:
            accent = ui_accent_for_theme(self._current_theme)
            for window in (self._vocab_window, self._log_window, self._detail_window):
                if window is not None:
                    window.set_accent(accent)
        except Exception:  # noqa: BLE001
            logger.exception("应用界面点缀色失败（已忽略）")

    def _refresh_tray_icon(self, name: str) -> None:
        """按主题停靠点重建托盘图标并应用到托盘（P1：托盘跟随换肤）。"""

        icon = PetRenderer.build_tray_icon(theme_stops(name))
        self._icon = icon
        self._tray.set_icon(icon)

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
        """把当前运行时状态写回配置（原子保存）。

        位置一律保存**游走锚点**而非窗口 ``pos()``：游走施加的瞬态偏移绝不落盘，
        否则随机位置会被存成新锚点、跨会话持续漂移（v1.1 §2.3 G2 / 风险 6）。
        """

        try:
            ax, ay = self._window.anchor()
            self._anchor_x, self._anchor_y = int(ax), int(ay)
        except Exception:  # noqa: BLE001 —— 窗口可能尚未创建
            logger.debug("持久化时游走锚点不可用，沿用内存中的锚点")
        self._cfg.window_x, self._cfg.window_y = self._anchor_x, self._anchor_y
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
