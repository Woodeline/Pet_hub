"""中文单词详情窗口冒烟（五要素渲染 / 来源 / 三态 / 离线降级 / 关闭取消）。

使用 fake pool 避免真实网络请求；``QT_QPA_PLATFORM=offscreen`` 离屏渲染。
"""

from __future__ import annotations

from pathlib import Path

from desktop_pet.core import constants as C
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.core.word_detail import Collocation, Example, WordDetail
from desktop_pet.ui.word_detail_window import WordDetailWindow
from desktop_pet.ui.word_detail_worker import WordDetailNetConfig


def _entry() -> VocabEntry:
    return VocabEntry(
        id="n5-0001", level="N5", word="私", kana="わたし",
        translation="我", meaning="第一人称代词", romaji="watashi",
    )


def _detail() -> WordDetail:
    return WordDetail(
        meaning_zh=("我", "吾"),
        pos_zh=("代词",),
        collocations=(Collocation("私は…", "自我介绍"), Collocation("私の")),
        examples=(Example("私は学生です。", "我是学生。"),),
        usage_note_zh="正式、通用。",
    )


def _net(api_key: str = "sk-test") -> WordDetailNetConfig:
    return WordDetailNetConfig(
        api_key=api_key, base_url=C.LLM_ENDPOINT, model=C.LLM_MODEL,
        timeout_s=C.LLM_TIMEOUT_S, retries=C.LLM_RETRIES,
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


def _all_text(window: WordDetailWindow) -> str:
    labels = [
        window._word_label, window._level_chip, window._kana_label, window._source_label,
        window._meaning_label, window._pos_label, window._collocations_label,
        window._examples_label, window._usage_label, window._status_label,
    ]
    return "\n".join(label.text() for label in labels)


# --------------------------------------------------------------------------- #
# 1. 本地 / 缓存命中 → 同步即时渲染（无加载态）
# --------------------------------------------------------------------------- #
def test_detail_hit_renders_five_elements_no_loading(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=_detail(), source=C.WORD_DETAIL_SOURCE_LOCAL)

    # 基础信息
    assert window._word_label.text() == "私"
    assert window._level_chip.text() == "N5"
    assert window._kana_label.text() == "わたし"
    # 五要素
    assert window._meaning_label.text() == "我；吾"
    assert window._pos_label.text() == "代词"
    assert "私は…" in window._collocations_label.text()
    assert "自我介绍" in window._collocations_label.text()
    assert "私は学生です。" in window._examples_label.text()
    assert "我是学生。" in window._examples_label.text()
    assert window._usage_label.text() == "正式、通用。"
    # 来源
    assert window._source_label.text() == C.WORD_DETAIL_SOURCE_LOCAL
    # 无加载态闪烁、未启动后台查询
    assert window._status_label.text() == ""
    assert window._retry_btn.isHidden() is True
    assert pool.started == []


def test_detail_hit_default_source_is_cache(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=_detail())
    assert window._source_label.text() == C.WORD_DETAIL_SOURCE_CACHE


def test_empty_groups_show_placeholder(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    detail = WordDetail(meaning_zh=("我",))
    window.show_entry(_entry(), detail=detail, source=C.WORD_DETAIL_SOURCE_LOCAL)
    assert window._pos_label.text() == C.WORD_DETAIL_EMPTY_GROUP
    assert window._collocations_label.text() == C.WORD_DETAIL_EMPTY_GROUP
    assert window._examples_label.text() == C.WORD_DETAIL_EMPTY_GROUP
    assert window._usage_label.text() == C.WORD_DETAIL_EMPTY_GROUP


def test_truncation_applied_in_render(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    detail = WordDetail(
        meaning_zh=tuple(f"义{i}" for i in range(5)),
        examples=tuple(Example(f"jp{i}", f"zh{i}") for i in range(5)),
        collocations=tuple(Collocation(f"p{i}") for i in range(8)),
    )
    window.show_entry(_entry(), detail=detail, source=C.WORD_DETAIL_SOURCE_LOCAL)
    assert window._meaning_label.text() == "义0；义1；义2"          # ≤3
    assert window._collocations_label.text().count("\n") == 4       # ≤5
    assert window._examples_label.text().count("<b>") == 3          # ≤3


# --------------------------------------------------------------------------- #
# 2. 未命中 + 有 Key → 加载态 + 启动 worker
# --------------------------------------------------------------------------- #
def test_no_detail_with_key_starts_worker_and_loading(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=None, net=_net("sk-abc"))

    assert len(pool.started) == 1
    assert window._status_label.text() == C.WORD_DETAIL_LOADING
    assert window._retry_btn.isHidden() is True
    # 基础信息先出，网络后填
    assert window._kana_label.text() == "わたし"


def test_empty_detail_treated_as_miss(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=WordDetail(), net=_net("sk-abc"))
    assert len(pool.started) == 1  # 空详情 = 未命中 → 走联网


# --------------------------------------------------------------------------- #
# 3. 未命中 + 无 Key / 无 net → 离线中文降级（无英文残留）
# --------------------------------------------------------------------------- #
def test_no_key_shows_offline_hint_with_retry(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=None, net=_net(""))

    assert pool.started == []
    assert window._status_label.text() == C.WORD_DETAIL_OFFLINE_HINT
    assert window._retry_btn.isHidden() is False
    assert "Jisho" not in _all_text(window)
    assert "来源：本地词库" not in window._source_label.text()


def test_none_net_shows_offline_hint(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=None, net=None)

    assert pool.started == []
    assert window._status_label.text() == C.WORD_DETAIL_OFFLINE_HINT
    assert window._retry_btn.isHidden() is False


# --------------------------------------------------------------------------- #
# 4. 三态（加载中 / 成功 / 失败）
# --------------------------------------------------------------------------- #
def test_three_states(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    # 先绑定当前词条（_item_id="n5-0001"），使后续 set_detail_* 通过 item_id 守卫
    window.show_entry(_entry(), detail=None, net=_net("sk-x"))

    window.set_loading()
    assert window._status_label.text() == C.WORD_DETAIL_LOADING
    assert window._retry_btn.isHidden() is True

    window.set_detail_result("n5-0001", _detail())
    assert window._source_label.text() == C.WORD_DETAIL_SOURCE_NET
    assert window._retry_btn.isHidden() is True
    assert window._status_label.text() == ""

    window.set_detail_error("n5-0001", "boom")
    assert window._status_label.text() == C.WORD_DETAIL_ERROR_TEMPLATE.format(msg="boom")
    assert window._retry_btn.isHidden() is False


def test_not_found_error_shows_fallback_text(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    # 绑定当前词条后，set_detail_error 才属于当前词条（item_id 守卫）
    window.show_entry(_entry(), detail=None, net=_net("sk-x"))
    window.set_detail_error("n5-0001", C.WORD_DETAIL_NOT_FOUND)
    assert window._status_label.text() == C.WORD_DETAIL_NOT_FOUND


def test_set_detail_result_none_shows_not_found(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    # 绑定当前词条后，空结果回落「未找到」（item_id 守卫）
    window.show_entry(_entry(), detail=None, net=_net("sk-x"))
    window.set_detail_result("n5-0001", None)  # type: ignore[arg-type]
    assert window._status_label.text() == C.WORD_DETAIL_NOT_FOUND


# --------------------------------------------------------------------------- #
# 5. 关闭取消 + 回调守卫 + 重试
# --------------------------------------------------------------------------- #
def test_close_clears_pool_and_guards() -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    window.show_entry(_entry(), detail=None, net=_net("sk-abc"))
    assert window._closed is False

    window.close()

    assert pool.cleared is True
    assert window._closed is True

    # 已关闭后 worker 回调被守卫拦截，不再上报 controller
    emitted: list[str] = []
    window.detail_succeeded.connect(lambda item_id, _detail: emitted.append(item_id))
    window._on_worker_succeeded("n5-0001", _detail())
    assert emitted == []


def test_worker_failed_callback_emits_and_renders(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=None, net=_net("sk-abc"))
    failed: list[tuple[str, str]] = []
    window.detail_failed.connect(lambda item_id, msg: failed.append((item_id, msg)))

    window._on_worker_failed("n5-0001", "鉴权失败（HTTP 401）")

    assert failed == [("n5-0001", "鉴权失败（HTTP 401）")]
    assert window._retry_btn.isHidden() is False


def test_worker_succeeded_callback_emits(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=None, net=_net("sk-abc"))
    got: list[str] = []
    window.detail_succeeded.connect(lambda item_id, _detail: got.append(item_id))

    window._on_worker_succeeded("n5-0001", _detail())

    assert got == ["n5-0001"]
    assert window._source_label.text() == C.WORD_DETAIL_SOURCE_NET


def test_retry_restarts_worker(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=None, net=_net("sk-abc"))
    assert len(pool.started) == 1

    window._on_retry()

    assert len(pool.started) == 2
    assert window._status_label.text() == C.WORD_DETAIL_LOADING


def test_retry_without_key_keeps_offline_hint(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_entry(), detail=None, net=_net(""))
    window._on_retry()
    assert pool.started == []
    assert window._status_label.text() == C.WORD_DETAIL_OFFLINE_HINT


# --------------------------------------------------------------------------- #
# 6. 静态约束：controller 不再引用 Jisho 详情符号
# --------------------------------------------------------------------------- #
def test_controller_no_longer_references_jisho(project_root: Path) -> None:
    source = (project_root / "src" / "desktop_pet" / "app" / "controller.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    assert "jisho" not in lowered, "controller 仍引用 Jisho 详情符号（应已解绑）"
