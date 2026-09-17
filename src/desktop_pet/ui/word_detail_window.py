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

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.core.word_detail import WordDetail
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
            self._render_detail(detail, source or C.WORD_DETAIL_SOURCE_CACHE)
            self._status_label.setText("")
            self._status_label.setVisible(False)
            self._retry_btn.setVisible(False)
            return

        # 本地词库 / 用户缓存均未命中
        self._clear_detail()
        if net is None or not str(getattr(net, "api_key", "") or "").strip():
            self.set_detail_error(self._item_id, C.WORD_DETAIL_OFFLINE_HINT)
            return

        self.set_loading()
        self._start_worker()

    def set_loading(self) -> None:
        """进入「联网查询中」态（隐藏重试）。"""

        self._status_label.setText(C.WORD_DETAIL_LOADING)
        self._status_label.setVisible(True)
        self._retry_btn.setVisible(False)
        self._retry_btn.setEnabled(True)

    def set_detail_result(self, item_id: str, detail: WordDetail) -> None:
        """回填联网成功结果（来源 = 联网获取）。

        ``item_id`` 守卫：只有属于**当前**词条的结果才允许回填，隔离陈旧回调。
        """

        if str(item_id) != str(self._item_id):
            return
        if detail is None or detail.is_empty():
            self.set_detail_error(item_id, C.WORD_DETAIL_NOT_FOUND)
            return
        self._render_detail(detail, C.WORD_DETAIL_SOURCE_NET)
        self._status_label.setText("")
        self._status_label.setVisible(False)
        self._retry_btn.setVisible(False)
        self._retry_btn.setEnabled(True)

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

    # ------------------------------------------------------------------ #
    # Qt 事件
    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """关闭：清空线程池 + 断开信号 + 置 ``_closed`` 守卫，杜绝回调已销毁对象。"""

        self._closed = True
        self._pool.clear()
        self._disconnect_active()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """构建界面元素与布局。"""

        root = QVBoxLayout(self)

        # 头部：大号单词 + 等级 chip
        header = QHBoxLayout()
        self._word_label = QLabel("", self)
        self._word_label.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {C.COLORS['vocab_text']};"
        )
        header.addWidget(self._word_label)
        self._level_chip = QLabel("", self)
        self._level_chip.setStyleSheet(
            f"background: {C.COLORS['jp_level_chip_bg']};"
            f"color: {C.COLORS['jp_level_chip_text']};"
            "border-radius: 6px; padding: 2px 8px; font-weight: bold;"
        )
        header.addWidget(self._level_chip)
        header.addStretch(1)
        root.addLayout(header)

        # 基础信息：假名 + 来源标注
        self._kana_label = self._add_field(root, C.WORD_DETAIL_LABEL_KANA)
        self._source_label = QLabel("", self)
        self._source_label.setStyleSheet(f"color: {C.COLORS['bubble_sub_text']}; margin-top: 2px;")
        root.addWidget(self._source_label)

        # 五要素分组
        self._meaning_label = self._add_group(root, C.WORD_DETAIL_LABEL_MEANING_ZH)
        self._pos_label = self._add_group(root, C.WORD_DETAIL_LABEL_POS_ZH)
        self._collocations_label = self._add_group(root, C.WORD_DETAIL_LABEL_COLLOCATIONS)
        self._examples_label = self._add_group(root, C.WORD_DETAIL_LABEL_EXAMPLES)
        self._examples_label.setTextFormat(Qt.TextFormat.RichText)
        self._usage_label = self._add_group(root, C.WORD_DETAIL_LABEL_USAGE)

        # 状态 / 重试
        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        root.addWidget(self._status_label)

        bottom = QHBoxLayout()
        self._retry_btn = QPushButton(C.WORD_DETAIL_RETRY, self)
        self._retry_btn.clicked.connect(self._on_retry)
        self._retry_btn.setVisible(False)
        bottom.addWidget(self._retry_btn)
        bottom.addStretch(1)
        self._close_btn = QPushButton(C.WORD_DETAIL_CLOSE, self)
        self._close_btn.clicked.connect(self.close)
        bottom.addWidget(self._close_btn)
        root.addLayout(bottom)

        root.addStretch(1)

    def _add_field(self, root: QVBoxLayout, caption: str) -> QLabel:
        """添加「caption + value」字段行，返回 value label。"""

        row = QHBoxLayout()
        caption_label = QLabel(caption, self)
        caption_label.setStyleSheet(f"color: {C.COLORS['bubble_sub_text']};")
        caption_label.setFixedWidth(72)
        row.addWidget(caption_label)
        value_label = QLabel("", self)
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(value_label, 1)
        root.addLayout(row)
        return value_label

    def _add_group(self, root: QVBoxLayout, caption: str) -> QLabel:
        """添加一个五要素分组（分组标题 + 可选值），返回 value label。"""

        caption_label = QLabel(caption, self)
        caption_label.setStyleSheet(
            f"color: {C.COLORS['bubble_sub_text']}; font-weight: bold; margin-top: 6px;"
        )
        root.addWidget(caption_label)
        value_label = QLabel("", self)
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(value_label)
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
