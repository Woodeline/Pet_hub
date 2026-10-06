"""工程师自测：已掌握词库窗口（MasteredWindow）—— 卡片渲染 / 排序 / 信号 / 状态行。

覆盖：
1. 到期描述：毕业 / 已到期（含跨天）/ 24 小时内 / 未来 N 天 / 未排期 五种形态
   的文案与语义色（``_due_description`` 纯函数）。
2. 卡片渲染：单词 / 假名 / 翻译 / 等级 chip / 记忆状态行齐备，喇叭键同口径。
3. 展示排序：复习中的词按 ``due_at`` 升序（最早到期最上、未排期置顶）、
   已毕业垫底（新毕业在前）；等级 Tab 过滤纯本地执行。
4. 状态栏：``共 N 个词 · 待复习 M 个``（到期数按 ``due_at <= now`` 计）。
5. 信号：单击选中启用「立即复习 / 退回生词本」、双击发详情信号、清空走二次确认。

遵循项目测试隔离约定：offscreen 渲染，不触碰真实用户数据。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.mastered_store import MasteredItem
from desktop_pet.ui.mastered_window import MasteredWindow, _due_description, _parse_iso

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _now_iso(offset_s: int = 0) -> str:
    """当前 UTC ± offset 的 ISO 定长字符串（``_due_description`` 同基准）。"""

    dt = datetime.now(timezone.utc) + timedelta(seconds=offset_s)
    return dt.strftime(_ISO_FMT)


def _item(
    i: int,
    *,
    stage: int = 0,
    due_at: str = "",
    level: str = "N5",
    review_count: int = 0,
    mastered_at: str = "2025-01-01T00:00:00Z",
) -> MasteredItem:
    """构造一条已掌握测试记录。"""

    return MasteredItem(
        id=f"{level.lower()}-{i:04d}",
        level=level,
        word=f"語{i}",
        kana="かな",
        translation="译",
        mastered_at=mastered_at,
        stage=stage,
        due_at=due_at,
        last_review_at=mastered_at,
        review_count=review_count,
    )


# --------------------------------------------------------------------------- #
# 1. 到期描述（纯函数）
# --------------------------------------------------------------------------- #
def test_due_description_graduated() -> None:
    """毕业态：stage 走完阶梯 → 「已毕业 · 长期记忆」+ info 色。"""

    total = len(C.REVIEW_INTERVALS_DAYS)
    text, color = _due_description(_item(1, stage=total))
    assert text == C.JP_MASTERED_GRADUATED
    assert color == "info"


def test_due_description_overdue() -> None:
    """已到期：当日 → 「待复习」；跨 N 天 → 「待复习（已过 N 天）」；均为 warning。"""

    text, color = _due_description(_item(1, due_at=_now_iso(-3600)))
    assert C.JP_MASTERED_DUE_NOW in text  # 状态行 = 阶段段 + 到期段
    assert color == "warning"

    text, color = _due_description(_item(2, due_at=_now_iso(-3 * 86400 - 60)))
    assert C.JP_MASTERED_DUE_OVERDUE_TEMPLATE.format(days=3) in text
    assert color == "warning"


def test_due_description_future() -> None:
    """未到期：24 小时内 → 「24 小时内复习」；更远 → 「N 天后复习」（进一法取整）。"""

    text, _ = _due_description(_item(1, due_at=_now_iso(2 * 3600)))
    assert C.JP_MASTERED_DUE_SOON in text

    text, _ = _due_description(_item(2, due_at=_now_iso(3 * 86400 + 3600)))
    assert C.JP_MASTERED_DUE_IN_TEMPLATE.format(days=4) in text  # 3天+1小时 → 进一位 4 天


def test_due_description_unscheduled_and_counts() -> None:
    """未排期（due_at 空）→ 「待复习」+ warning；复习次数追加在末段。"""

    text, color = _due_description(_item(1, due_at="", review_count=2))
    assert C.JP_MASTERED_DUE_NOW in text
    assert C.JP_MASTERED_REVIEWED_TEMPLATE.format(count=2) in text
    assert color == "warning"


def test_parse_iso_rejects_garbage() -> None:
    """非法 ISO → ``None``（展示层容错不抛）。"""

    assert _parse_iso("not-a-date") is None
    assert _parse_iso("") is None
    assert _parse_iso(None) is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 2/3/4. 窗口渲染 / 排序 / 状态栏
# --------------------------------------------------------------------------- #
@pytest.fixture()
def window(qtbot) -> MasteredWindow:
    """空窗口 + 加入 qtbot 生命周期管理。"""

    win = MasteredWindow()
    qtbot.addWidget(win)
    return win


def test_cards_render_all_rows(window: MasteredWindow) -> None:
    """卡片四要素：单词、假名、翻译、记忆状态行（阶段 + 到期描述）。"""

    due = _now_iso(2 * 86400)
    window.refresh([_item(1, stage=1, due_at=due)])
    card = window._card_by_id["n5-0001"]
    assert card._word_label.text() == "語1"
    assert card._kana_label.text() == "｜かな"
    # 状态行含阶段与到期描述
    status_text = card.layout().itemAt(2).widget().text()
    assert C.JP_MASTERED_STAGE_TEMPLATE.format(stage=2, total=7) in status_text
    assert C.JP_MASTERED_DUE_IN_TEMPLATE.format(days=2) in status_text


def test_refresh_sorts_due_first_graduated_last(window: MasteredWindow) -> None:
    """排序：未排期置顶 → 按到期升序 → 已毕业垫底（新毕业在前）。"""

    items = [
        _item(1, stage=1, due_at=_now_iso(5 * 86400)),
        _item(2, stage=0, due_at=_now_iso(1 * 86400)),
        _item(3, stage=7, due_at=""),                                    # 毕业（旧）
        _item(4, stage=7, due_at="", mastered_at="2025-02-01T00:00:00Z"),  # 毕业（新）
        _item(5, stage=0, due_at=""),                                    # 未排期瞬态
    ]
    window.refresh(items)

    assert list(window._card_by_id.keys()) == ["n5-0005", "n5-0002", "n5-0001", "n5-0004", "n5-0003"]


def test_level_filter_local(window: MasteredWindow) -> None:
    """等级 Tab 为纯本地过滤：N4 只剩 N4 的卡片。"""

    window.refresh([_item(1), _item(2, level="N4")])
    window._tab_buttons["N4"].click()
    assert list(window._card_by_id.keys()) == ["n4-0002"]
    window._tab_buttons[C.JP_VOCAB_FILTER_ALL].click()
    assert len(window._card_by_id) == 2


def test_status_bar_counts_due(window: MasteredWindow) -> None:
    """状态栏：总数 + 待复习数（已到期；未来 / 毕业不计）。"""

    window.refresh(
        [
            _item(1, due_at=_now_iso(-60)),      # 已到期
            _item(2, due_at=_now_iso(-86400)),   # 已到期（跨天）
            _item(3, due_at=_now_iso(86400)),    # 未来
            _item(4, stage=7, due_at=""),        # 毕业
        ]
    )
    assert window._status.text() == C.JP_MASTERED_STATUS_TEMPLATE.format(count=4, due=2)


def test_empty_state(window: MasteredWindow) -> None:
    """空集合 → 空态文案、清空按钮禁用。"""

    window.refresh([])
    assert window._empty_label.isVisible() or window._stack.currentWidget() is window._empty_label
    assert not window._btn_clear.isEnabled()


# --------------------------------------------------------------------------- #
# 5. 信号
# --------------------------------------------------------------------------- #
def test_card_click_enables_actions_and_emits_signals(
    qtbot, window: MasteredWindow
) -> None:
    """单击选中 → 启用操作按钮；点「立即复习 / 退回生词本」发出对应信号。"""

    window.refresh([_item(1), _item(2)])
    review_signals: list[str] = []
    back_signals: list[str] = []
    window.review_requested.connect(review_signals.append)
    window.back_to_vocab_requested.connect(back_signals.append)

    assert not window._btn_review.isEnabled()
    window._on_card_clicked("n5-0002")
    assert window._btn_review.isEnabled()
    assert window._btn_back.isEnabled()

    window._btn_review.click()
    window._btn_back.click()
    assert review_signals == ["n5-0002"]
    assert back_signals == ["n5-0002"]


def test_card_double_click_emits_detail_signal(window: MasteredWindow) -> None:
    """双击卡片 → 发 ``word_double_clicked``（携带 item id）。"""

    window.refresh([_item(1)])
    got: list[str] = []
    window.word_double_clicked.connect(got.append)
    window._card_by_id["n5-0001"].double_clicked.emit("n5-0001")
    assert got == ["n5-0001"]


def test_clear_requires_confirmation(window: MasteredWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    """清空：二次确认取消 → 不发信号；确认 → 发 ``clear_requested``。"""

    window.refresh([_item(1)])
    got: list[bool] = []
    window.clear_requested.connect(lambda: got.append(True))

    monkeypatch.setattr(
        "desktop_pet.ui.mastered_window.ConfirmDialog.ask", lambda *a, **k: False
    )
    window._on_clear_clicked()
    assert got == []

    monkeypatch.setattr(
        "desktop_pet.ui.mastered_window.ConfirmDialog.ask", lambda *a, **k: True
    )
    window._on_clear_clicked()
    assert got == [True]


def test_clear_disabled_when_empty(window: MasteredWindow) -> None:
    """空集合点清空：直接忽略（不发信号，不弹确认）。"""

    got: list[bool] = []
    window.clear_requested.connect(lambda: got.append(True))
    window._on_clear_clicked()
    assert got == []
