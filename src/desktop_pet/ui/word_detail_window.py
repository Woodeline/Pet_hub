"""ui.word_detail_window —— 纯中文五要素单词详情窗口（本地即时渲染 + 联网三态回填）。

设计要点（架构 §5.2 T04 / §4 时序）：
- ``show_entry(entry, detail, source, net)`` 先渲染基础信息（词 / 等级 / 假名）。
- ``detail`` 命中（本地词库 / 用户缓存）→ **同步即时渲染（无加载态闪烁）** + 来源标注。
- ``detail`` 未命中且（``net`` 为空 或 ``api_key`` 为空）→ 离线中文降级提示 + 重试（无英文残留）。
- 否则 → ``set_loading()`` + 后台 ``WordDetailWorker``（跨线程 ``QueuedConnection`` 回主线程）。
- 关闭窗口用 ``pool.clear()`` + ``disconnect`` + ``_closed`` 守卫，避免回调已销毁对象。
- 五要素：中文释义（分条）/ 词性（标签）/ 常见搭配 / 典型例句（日文加粗 + 中文次行）/ 语境语气。
"""

from __future__ import annotations

import logging
from html import escape

from PySide6.QtCore import QSize, QThreadPool, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.core.word_detail import WordDetail
from desktop_pet.ui import icon_factory, motion_ui, theme
from desktop_pet.ui.spinner import Spinner
from desktop_pet.ui.word_detail_worker import (
    WordDetailNetConfig,
    WordDetailSignals,
    WordDetailWorker,
)

logger = logging.getLogger(__name__)


class WordDetailWindow(QWidget):
    """非模态中文详情窗口（由 controller 管理单例）。"""

    #: 上报 controller 持久化用户缓存（成功 / 失败）
    detail_succeeded = Signal(str, object)  # (item_id, WordDetail)
    detail_failed = Signal(str, str)        # (item_id, error_message)

    def __init__(
        self,
        pool: QThreadPool | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """构造详情窗口。

        Args:
            pool: 外部 ``QThreadPool``；``None`` 时自建（挂到本窗口生命周期）。
            parent: 父窗口。
        """

        super().__init__(parent)
        self.setWindowTitle(C.WORD_DETAIL_WINDOW_TITLE)
        self.resize(C.WORD_DETAIL_WINDOW_W, C.WORD_DETAIL_WINDOW_H)

        self._pool: QThreadPool = pool if pool is not None else QThreadPool()
        self._entry: VocabEntry | None = None
        self._item_id: str = ""
        self._net: WordDetailNetConfig | None = None
        self._active_signals: WordDetailSignals | None = None
        self._closed: bool = False
        #: 「减少动效」开关（由 controller 在 show 之前经 :meth:`set_reduce_motion` 注入）。
        self._reduce_motion: bool = False

        self._build_ui()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def show_entry(
        self,
        entry: VocabEntry,
        detail: WordDetail | None = None,
        source: str | None = None,
        net: WordDetailNetConfig | None = None,
    ) -> None:
        """展示一个词条：命中本地/缓存则即时渲染，否则按配置决定联网或离线降级。

        竞态防护（关键）：入口侧在**所有分支**开头无条件 ``_disconnect_active()``，
        确保「切到新词」后，上一个在途 worker 的信号不再连到本窗口，既不能回填、
        也不能上报 controller；回调侧还有 ``item_id`` 守卫做二道防线。
        """

        if entry is None:
            return
        # 重开前置：先断连上一次查询（丢弃在途信号），再复位关闭守卫。
        self._disconnect_active()
        self._closed = False
        self._entry = entry
        self._item_id = entry.id
        self._net = net
        self._render_header(entry)

        if detail is not None and not detail.is_empty():
            # 本地/缓存命中：丢弃在途任务，杜绝旧 worker 迟到回填当前词条。
            self._pool.clear()
            self._status_label.setText("")
            self._status_label.setVisible(False)
            self._retry_btn.setVisible(False)
            self._hide_spinner()
            self._render_detail(detail, source or C.WORD_DETAIL_SOURCE_CACHE)
            return

        # 本地词库 / 用户缓存均未命中
        self._clear_detail()
        if net is None or not str(getattr(net, "api_key", "") or "").strip():
            self.set_detail_error(self._item_id, C.WORD_DETAIL_OFFLINE_HINT)
            return

        self.set_loading()
        self._start_worker()

    def set_loading(self) -> None:
        """进入「联网查询中」态（隐藏重试；spinner 旋转 + 状态标签淡入）。"""

        self._status_label.setText(C.WORD_DETAIL_LOADING)
        self._status_label.setVisible(True)
        self._retry_btn.setVisible(False)
        self._retry_btn.setEnabled(True)
        self._spinner.setVisible(True)
        self._spinner.start()
        motion_ui.fade_label_in(self._status_label, self._reduce_motion)

    def set_detail_result(self, item_id: str, detail: WordDetail) -> None:
        """回填联网成功结果（来源 = 联网获取）。

        ``item_id`` 守卫：只有属于**当前**词条的结果才允许回填，隔离陈旧回调。
        """

        if str(item_id) != str(self._item_id):
            return
        if detail is None or detail.is_empty():
            self.set_detail_error(item_id, C.WORD_DETAIL_NOT_FOUND)
            return
        self._status_label.setText("")
        self._status_label.setVisible(False)
        self._retry_btn.setVisible(False)
        self._retry_btn.setEnabled(True)
        self._hide_spinner()
        self._render_detail(detail, C.WORD_DETAIL_SOURCE_NET)

    def set_detail_error(self, item_id: str, msg: str) -> None:
        """进入失败态：显示中文提示并给出重试（离线降级文案原样展示）。

        ``item_id`` 守卫：只有属于**当前**词条的失败才允许置错误态，隔离陈旧回调。
        """

        if str(item_id) != str(self._item_id):
            return
        if msg in (C.WORD_DETAIL_NOT_FOUND, C.WORD_DETAIL_OFFLINE_HINT):
            text = msg
        else:
            text = C.WORD_DETAIL_ERROR_TEMPLATE.format(msg=msg)
        self._status_label.setText(text)
        self._status_label.setVisible(True)
        self._retry_btn.setVisible(True)
        self._retry_btn.setEnabled(True)
        self._hide_spinner()
        self._fit_height_to_content()

    def set_reduce_motion(self, flag: bool) -> None:
        """注入「减少动效」开关（由 controller 在窗口显示前调用）。"""

        self._reduce_motion = bool(flag)
        self._spinner.set_reduce_motion(self._reduce_motion)

    def set_accent(self, accent: str | None) -> None:
        """应用主题点缀色：重刷全局 QSS + 词性下划线（controller 在换肤时调用）。

        Args:
            accent: 点缀色（``#RRGGBB``）；``None`` 回落中性主色。
        """

        theme.apply_theme(self, accent)
        color = accent if accent else C.SEMANTIC_COLORS["primary"]
        self._pos_label.setStyleSheet(
            f"color: {color}; font-weight: bold;"
            f" font-size: {C.FONT_SIZE['body']}px;"
            f" border-bottom: 2px solid {C.SEMANTIC_COLORS['muted']};"
            " background: transparent;"
        )

    def _fit_height_to_content(self) -> None:
        """窗口高度随内容自适应（钳制屏幕可用高度 85%），消除底部固定留白。

        测量走布局的 ``heightForWidth``（含换行文本的真实高度）；布局不支持 hfw
        时退回 ``sizeHint``（防御分支，正常路径不会走到）。
        """

        layout = self.layout()
        if layout is None:
            return
        if layout.hasHeightForWidth():
            needed = layout.heightForWidth(self.width())
        else:
            needed = self.sizeHint().height()
        screen = self.screen() or QGuiApplication.primaryScreen()
        max_h = int(screen.availableGeometry().height() * 0.85)
        height = max(180, min(int(needed), max_h))
        if height != self.height():
            self.resize(self.width(), height)

    # ------------------------------------------------------------------ #
    # Qt 事件
    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """关闭：清空线程池 + 断开信号 + 置 ``_closed`` 守卫，杜绝回调已销毁对象。

        动效（P2）：先**同步**完成既有收尾（置守卫 / 清池 / 断连 / 停 spinner）；
        仅当开启动效且窗口**当前可见**时才改为「淡出后再隐藏」（``event.ignore()`` ),
        未显示过的窗口（如单测直接 ``close()``）一律走原始路径。
        """

        self._closed = True
        self._pool.clear()
        self._disconnect_active()
        self._spinner.stop()

        if motion_ui.motion_enabled(self._reduce_motion) and self.isVisible():
            event.ignore()
            motion = motion_ui.create_window_motion(self, self._reduce_motion)
            motion.fade_out(on_finished=self.hide)
            return

        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """构建界面元素与布局（卡片化改版：五要素分组改为圆角卡片）。"""

        # 统一接入语义 token（QSS 由 theme 生成，组件内只引用 token 色值）。
        theme.apply_theme(self)

        root = QVBoxLayout(self)

        # 头部：大号单词 + 等级胶囊 chip（右上）
        header = QHBoxLayout()
        self._word_label = QLabel("", self)
        self._word_label.setStyleSheet(
            f"font-size: {C.FONT_SIZE['display']}px; font-weight: bold;"
            f" color: {C.SEMANTIC_COLORS['text_primary']};"
        )
        header.addWidget(self._word_label)
        header.addStretch(1)
        # 等级 chip：描边胶囊样式（与「记住了」按钮的绿色不撞车）。
        self._level_chip = QLabel("", self)
        self._level_chip.setStyleSheet(
            "background: transparent;"
            f" color: {C.SEMANTIC_COLORS['text_secondary']};"
            f" border: 1px solid {C.SEMANTIC_COLORS['border']};"
            f" border-radius: {C.RADIUS['pill']}px; padding: 2px 10px; font-weight: bold;"
        )
        theme.set_role(self._level_chip, "chip")
        header.addWidget(self._level_chip)
        root.addLayout(header)

        # 假名行：假名 + 喇叭占位（置灰，发音功能预留，点击无响应）
        kana_row = QHBoxLayout()
        self._kana_label = self._add_field(root, kana_row, C.WORD_DETAIL_LABEL_KANA)
        kana_row.addStretch(1)
        speaker = QLabel(self)
        speaker.setPixmap(
            icon_factory.make_icon(
                "speaker", color=C.SEMANTIC_COLORS["text_faint"]
            ).pixmap(QSize(C.SPACING["xl"], C.SPACING["xl"]))
        )
        speaker.setToolTip(C.JP_SPEAKER_TIP)
        kana_row.addWidget(speaker)
        root.addLayout(kana_row)

        self._source_label = QLabel("", self)
        self._source_label.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['text_secondary']}; margin-top: 2px;"
        )
        root.addWidget(self._source_label)

        # 词性：强调行（参考词典应用：词性带下划线突出，下划线仅贴文字宽度）
        pos_row = QHBoxLayout()
        self._pos_label = QLabel("", self)
        self._pos_label.setWordWrap(True)
        self._pos_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._pos_label.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['primary']}; font-weight: bold;"
            f" font-size: {C.FONT_SIZE['body']}px;"
            f" border-bottom: 2px solid {C.SEMANTIC_COLORS['muted']};"
            " background: transparent;"
        )
        pos_row.addWidget(self._pos_label)
        pos_row.addStretch(1)
        root.addLayout(pos_row)

        # 五要素分组（词性已上提，其余四组用圆角卡片承载）
        self._meaning_label = self._add_group(root, C.WORD_DETAIL_LABEL_MEANING_ZH)
        self._examples_label = self._add_group(root, C.WORD_DETAIL_LABEL_EXAMPLES)
        self._examples_label.setTextFormat(Qt.TextFormat.RichText)
        self._collocations_label = self._add_group(root, C.WORD_DETAIL_LABEL_COLLOCATIONS)
        self._usage_label = self._add_group(root, C.WORD_DETAIL_LABEL_USAGE)

        # 状态 / 重试（spinner 与状态标签同行；状态标签文本/可见性逻辑保持不变）
        status_row = QHBoxLayout()
        self._spinner = Spinner(self, reduce_motion=self._reduce_motion)
        self._spinner.setVisible(False)
        status_row.addWidget(self._spinner)
        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        status_row.addWidget(self._status_label, 1)
        root.addLayout(status_row)

        bottom = QHBoxLayout()
        self._retry_btn = QPushButton(C.WORD_DETAIL_RETRY, self)
        theme.set_variant(self._retry_btn, "primary")
        self._retry_btn.setIcon(
            icon_factory.make_icon("retry", color=C.SEMANTIC_COLORS["surface"])
        )
        self._retry_btn.setIconSize(QSize(C.SPACING["lg"], C.SPACING["lg"]))
        self._retry_btn.clicked.connect(self._on_retry)
        self._retry_btn.setVisible(False)
        bottom.addWidget(self._retry_btn)
        bottom.addStretch(1)
        self._close_btn = QPushButton(C.WORD_DETAIL_CLOSE, self)
        theme.set_variant(self._close_btn, "ghost")
        self._close_btn.setIcon(
            icon_factory.make_icon("close", color=C.SEMANTIC_COLORS["text_primary"])
        )
        self._close_btn.setIconSize(QSize(C.SPACING["lg"], C.SPACING["lg"]))
        self._close_btn.clicked.connect(self.close)
        bottom.addWidget(self._close_btn)
        root.addLayout(bottom)

        root.addStretch(1)

    def _add_field(self, root: QVBoxLayout, row: QHBoxLayout, caption: str) -> QLabel:
        """添加「caption + value」字段行（行布局由调用方持有），返回 value label。"""

        caption_label = QLabel(caption, self)
        caption_label.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['text_secondary']};"
            f" font-size: {C.FONT_SIZE['caption']}px;"
        )
        caption_label.setFixedWidth(72)
        row.addWidget(caption_label)
        value_label = QLabel("", self)
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(value_label, 1)
        return value_label

    def _add_group(self, root: QVBoxLayout, caption: str) -> QLabel:
        """添加一个圆角卡片分组（卡内：分组标题 + 值），返回 value label。"""

        card = QFrame(self)
        theme.set_role(card, "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            C.SPACING["md"], C.SPACING["sm"], C.SPACING["md"], C.SPACING["sm"]
        )
        card_layout.setSpacing(C.SPACING["xs"])
        caption_label = QLabel(caption, self)
        caption_label.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['text_secondary']};"
            f" font-size: {C.FONT_SIZE['caption']}px; font-weight: bold;"
            " background: transparent;"
        )
        card_layout.addWidget(caption_label)
        value_label = QLabel("", self)
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value_label.setStyleSheet("background: transparent;")
        card_layout.addWidget(value_label)
        root.addWidget(card)
        return value_label

    # ------------------------------------------------------------------ #
    # 内部：渲染
    # ------------------------------------------------------------------ #
    def _render_header(self, entry: VocabEntry) -> None:
        """渲染基础信息（词 / 等级 / 假名）。"""

        self._word_label.setText(entry.word)
        self._level_chip.setText(entry.level)
        self._kana_label.setText(entry.kana or C.WORD_DETAIL_NO_VALUE)

    def _clear_detail(self) -> None:
        """清空五要素与来源标注（进入加载 / 失败态前）。"""

        self._source_label.setText("")
        for label in (
            self._meaning_label,
            self._pos_label,
            self._collocations_label,
            self._examples_label,
            self._usage_label,
        ):
            label.setText("")

    def _hide_spinner(self) -> None:
        """停止并隐藏联网 spinner（进入非加载态时调用）。"""

        self._spinner.stop()
        self._spinner.setVisible(False)

    def _render_detail(self, detail: WordDetail, source: str) -> None:
        """按展示上限渲染五要素与来源标注（空分组显示「暂无」）。"""

        cut = detail.truncated()
        self._source_label.setText(source or C.WORD_DETAIL_SOURCE_CACHE)
        self._meaning_label.setText(
            "；".join(cut.meaning_zh) if cut.meaning_zh else C.WORD_DETAIL_EMPTY_GROUP
        )
        self._pos_label.setText(
            "、".join(cut.pos_zh) if cut.pos_zh else C.WORD_DETAIL_EMPTY_GROUP
        )
        self._collocations_label.setText(self._format_collocations(cut))
        self._examples_label.setText(self._format_examples(cut))
        self._usage_label.setText(cut.usage_note_zh or C.WORD_DETAIL_EMPTY_GROUP)
        self._fit_height_to_content()

    @staticmethod
    def _format_collocations(detail: WordDetail) -> str:
        """把搭配渲染为「短语　说明」多行文本；空则返回「暂无」。"""

        if not detail.collocations:
            return C.WORD_DETAIL_EMPTY_GROUP
        lines: list[str] = []
        for collocation in detail.collocations:
            if collocation.note:
                lines.append(f"{collocation.phrase}　{collocation.note}")
            else:
                lines.append(collocation.phrase)
        return "\n".join(lines)

    @staticmethod
    def _format_examples(detail: WordDetail) -> str:
        """把例句渲染为「日文加粗 + 中文次行」富文本；空则返回「暂无」。"""

        if not detail.examples:
            return C.WORD_DETAIL_EMPTY_GROUP
        parts: list[str] = []
        for example in detail.examples:
            segment = f"<b>{escape(example.jp)}</b>"
            if example.zh:
                segment += f"<br/>{escape(example.zh)}"
            parts.append(segment)
        return "<br/>".join(parts)

    # ------------------------------------------------------------------ #
    # 内部：后台查询
    # ------------------------------------------------------------------ #
    def _start_worker(self) -> None:
        """创建并启动一次后台联网查询。"""

        if self._closed or self._entry is None or self._net is None:
            return
        self._disconnect_active()
        entry = self._entry
        worker = WordDetailWorker(
            entry.id, entry.word, entry.kana, entry.level, entry.translation, self._net
        )
        worker.signals.succeeded.connect(
            self._on_worker_succeeded, Qt.ConnectionType.QueuedConnection
        )
        worker.signals.failed.connect(
            self._on_worker_failed, Qt.ConnectionType.QueuedConnection
        )
        self._active_signals = worker.signals
        self._pool.start(worker)

    def _disconnect_active(self) -> None:
        """断开上一次查询的信号连接（避免多次连接 / 回调已关闭窗口）。"""

        if self._active_signals is None:
            return
        try:
            self._active_signals.succeeded.disconnect()
            self._active_signals.failed.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._active_signals = None

    def _on_retry(self) -> None:
        """点击重试 → 以当前词条与联网配置重新发起查询。"""

        if self._closed or self._entry is None:
            return
        self.show_entry(self._entry, None, None, self._net)

    def _on_worker_succeeded(self, item_id: str, detail: WordDetail) -> None:
        """后台成功回调（主线程）→ 回填并上报 controller。

        守卫：``_closed``（窗口已关）+ ``item_id``（结果非当前词条）双闸，隔离陈旧回调。
        """

        if self._closed:
            return
        if str(item_id) != str(self._item_id):
            return
        self.set_detail_result(item_id, detail)
        self.detail_succeeded.emit(item_id, detail)

    def _on_worker_failed(self, item_id: str, msg: str) -> None:
        """后台失败回调（主线程）→ 降级显示并上报 controller。

        守卫：``_closed``（窗口已关）+ ``item_id``（失败非当前词条）双闸，隔离陈旧回调。
        """

        if self._closed:
            return
        if str(item_id) != str(self._item_id):
            return
        self.set_detail_error(item_id, msg)
        self.detail_failed.emit(item_id, msg)


__all__ = ["WordDetailWindow"]
