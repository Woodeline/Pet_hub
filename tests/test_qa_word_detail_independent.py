"""独立 QA 验证：桌面宠物「日语单词详情」中文五要素改造。

本文件由 QA 独立编写（不复用工程师既有断言的角度），聚焦：
1. 五要素真实渲染 + 按上限截断（释义≤3 / 例句≤3 / 搭配≤5，词性与语气不裁剪）。
2. 两入口（生词本 / 学习记录）→ 同一窗口单例 + 同一渲染路径。
3. 查找链优先级：打包库 > 用户缓存 > 未命中。
4. 本地命中「零加载态闪烁」（同步即时渲染，绝不进入 loading）。
5. 离线降级：无 Key + 未命中 → 中文提示 + 重试，无英文残留。
6. 缓存落盘往返 + 损坏备份 ``.corrupt-*``（不静默清空）。
7. LLM 客户端请求形状 / JSON 提取容错 / 异常分类 / Worker 不裸抛。
8. 真实详情库端到端完整性（**含 phrase / jp 全字段**英文残留扫描）。
9. 边界容错（详情库损坏降级 / from_dict 非法分支）。
10. 死代码：详情链路无 jisho 残留。

运行：``pytest tests/test_qa_word_detail_independent.py -q``
"""

from __future__ import annotations

import json
import random
import re
import urllib.error
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core import llm_client, paths
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogStore
from desktop_pet.core.llm_client import (
    DeepSeekClient,
    LLMAuthError,
    LLMConfigError,
    LLMNetworkError,
    LLMParseError,
)
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.word_detail import Collocation, Example, WordDetail
from desktop_pet.core.word_detail_bank import WordDetailBank
from desktop_pet.core.word_details_cache_store import WordDetailsCacheStore
from desktop_pet.ui.word_detail_window import WordDetailWindow
from desktop_pet.ui.word_detail_worker import WordDetailNetConfig, WordDetailWorker

_DETAILS_PATH = paths.word_details_path()
_BANK_PATH = paths.word_bank_path()
#: 值字段中出现 ≥3 个连续 ASCII 字母即视为英文残留（"JLPT" 白名单放行）
_ENGLISH = re.compile(r"[A-Za-z]{3,}")
_ALLOWED = {"jlpt"}


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _entry(i: int = 1, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}", level=level, word=f"語{i}", kana=f"かな{i}",
        translation="译", meaning="义",
    )


def _detail(meaning: str = "我") -> WordDetail:
    return WordDetail(
        meaning_zh=(meaning,),
        pos_zh=("代词",),
        collocations=(Collocation("私は…", "自我介绍"),),
        examples=(Example("私は学生です。", "我是学生。"),),
        usage_note_zh="正式、通用。",
    )


def _net(api_key: str = "sk-test") -> WordDetailNetConfig:
    return WordDetailNetConfig(
        api_key=api_key, base_url=C.LLM_ENDPOINT, model=C.LLM_MODEL,
        timeout_s=C.LLM_TIMEOUT_S, retries=0,
    )


class _FakePool:
    """记录 start/clear，不真正执行 runnable（杜绝真实联网）。"""

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


@pytest.fixture()
def qa_controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """最小 controller：所有 store 隔离到 tmp_path，注入 2 词小词库。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)
    ctrl._bank = WordBank((_entry(1), _entry(2)))
    ctrl._vocab = VocabStore(tmp_path / "vocab.json")
    ctrl._mastered = MasteredStore(tmp_path / "mastered.json")
    ctrl._daily_log = DailyLogStore(tmp_path / "daily_log.json")
    ctrl._vocab.load()
    ctrl._mastered.load()
    ctrl._daily_log.load()
    ctrl._detail_cache = WordDetailsCacheStore(tmp_path / "word_details_cache.json")
    ctrl._detail_cache.load()
    ctrl._detail_bank = WordDetailBank.empty()
    ctrl._today_str = "2025-01-01"
    return ctrl


# =========================================================================== #
# 组 1：五要素渲染 + 截断 + 空分组
# =========================================================================== #
def test_qa_five_elements_rendered_distinctly(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    detail = WordDetail(
        meaning_zh=("甲义", "乙义"),
        pos_zh=("名词", "サ变"),
        collocations=(Collocation("P1", "n1"), Collocation("P2")),
        examples=(Example("JP1。", "中1。"), Example("JP2。", "中2。")),
        usage_note_zh="语气说明。",
    )
    window.show_entry(_entry(1), detail=detail, source=C.WORD_DETAIL_SOURCE_LOCAL)

    assert "甲义" in window._meaning_label.text() and "乙义" in window._meaning_label.text()
    assert "名词" in window._pos_label.text() and "サ变" in window._pos_label.text()
    coll = window._collocations_label.text()
    assert "P1" in coll and "n1" in coll and "P2" in coll
    ex = window._examples_label.text()
    assert "JP1。" in ex and "中1。" in ex and "JP2。" in ex
    assert "<b>" in ex  # 日文加粗
    assert window._usage_label.text() == "语气说明。"
    assert window._source_label.text() == C.WORD_DETAIL_SOURCE_LOCAL


def test_qa_truncation_exact_limits(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    detail = WordDetail(
        meaning_zh=tuple(f"M{i}" for i in range(6)),
        pos_zh=tuple(f"Q{i}" for i in range(6)),        # 词性不裁剪
        collocations=tuple(Collocation(f"C{i}") for i in range(8)),
        examples=tuple(Example(f"E{i}", f"Z{i}") for i in range(6)),
        usage_note_zh="u。",
    )
    window.show_entry(_entry(1), detail=detail, source=C.WORD_DETAIL_SOURCE_LOCAL)

    assert window._meaning_label.text() == "M0；M1；M2"          # 释义 ≤3
    assert window._pos_label.text() == "Q0、Q1、Q2、Q3、Q4、Q5"   # 词性不裁剪
    coll = window._collocations_label.text()
    assert coll.count("\n") == 4                                  # 搭配 ≤5
    assert "C4" in coll and "C5" not in coll
    ex = window._examples_label.text()
    assert ex.count("<b>") == 3                                   # 例句 ≤3
    assert "E2" in ex and "E3" not in ex


def test_qa_empty_groups_show_placeholder(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    window.show_entry(_entry(1), detail=WordDetail(meaning_zh=("只有释义",)))
    assert window._meaning_label.text() == "只有释义"
    assert window._pos_label.text() == C.WORD_DETAIL_EMPTY_GROUP
    assert window._collocations_label.text() == C.WORD_DETAIL_EMPTY_GROUP
    assert window._examples_label.text() == C.WORD_DETAIL_EMPTY_GROUP
    assert window._usage_label.text() == C.WORD_DETAIL_EMPTY_GROUP


# =========================================================================== #
# 组 2：本地命中「零加载态闪烁」
# =========================================================================== #
def test_qa_local_hit_never_enters_loading(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    calls: list[str] = []
    # 洞悉：若 show_entry 进入 loading 分支，这里会被记录
    monkeypatch.setattr(window, "set_loading", lambda: calls.append("loading"))

    window.show_entry(_entry(1), detail=_detail("本地义"), source=C.WORD_DETAIL_SOURCE_LOCAL)

    assert calls == [], "本地命中不得先进入 loading"
    assert window._meaning_label.text() == "本地义"   # 已同步渲染
    assert window._status_label.text() == ""
    assert window._retry_btn.isHidden() is True
    assert pool.started == []                         # 未启动后台查询


# =========================================================================== #
# 组 3：离线降级（无 Key / 无 net）
# =========================================================================== #
@pytest.mark.parametrize("net", [_net(""), None])
def test_qa_offline_degradation_chinese_no_english(qtbot, net) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_entry(1), detail=None, net=net)

    assert pool.started == []
    assert window._status_label.text() == C.WORD_DETAIL_OFFLINE_HINT
    assert window._retry_btn.isHidden() is False
    text = _all_text(window).lower()
    assert "jisho" not in text
    for bad in ("meaning", "example", "translation", "english", "romaji", "definition"):
        assert bad not in text, f"离线界面出现英文残留：{bad}"


def test_qa_offline_hint_has_no_english_detail_content() -> None:
    """离线提示常量本身不得包含英文详情内容（Jisho 英文区应已移除）。"""
    hint = C.WORD_DETAIL_OFFLINE_HINT
    assert not _ENGLISH.search(hint.replace("Key", "")), hint
    assert "Jisho" not in hint and "jisho" not in hint


# =========================================================================== #
# 组 4：controller 查找链优先级 + 缓存落盘/损坏
# =========================================================================== #
def test_qa_lookup_bank_priority_over_cache(qa_controller: PetAppController) -> None:
    ctrl = qa_controller
    ctrl._detail_cache.put("n5-0001", _detail("缓存义"), ctrl._now_iso())
    ctrl._detail_bank = WordDetailBank({"n5-0001": _detail("库义")})

    detail, source = ctrl._lookup_word_detail("n5-0001")
    assert source == C.WORD_DETAIL_SOURCE_LOCAL
    assert detail is not None and detail.meaning_zh == ("库义",)


def test_qa_lookup_cache_when_bank_miss(qa_controller: PetAppController) -> None:
    ctrl = qa_controller
    ctrl._detail_cache.put("n5-0002", _detail("缓存义"), ctrl._now_iso())
    ctrl._detail_bank = WordDetailBank.empty()

    detail, source = ctrl._lookup_word_detail("n5-0002")
    assert source == C.WORD_DETAIL_SOURCE_CACHE
    assert detail is not None and detail.meaning_zh == ("缓存义",)


def test_qa_lookup_miss_returns_none(qa_controller: PetAppController) -> None:
    ctrl = qa_controller
    ctrl._detail_bank = WordDetailBank.empty()
    assert ctrl._lookup_word_detail("n5-9999") == (None, None)
    assert ctrl._lookup_word_detail("") == (None, None)


def test_qa_controller_on_succeeded_persists_and_reload(qa_controller: PetAppController) -> None:
    ctrl = qa_controller
    ctrl._on_detail_succeeded("n5-0007", _detail("联网义"))

    # 重新构造 store 从磁盘读回（真正的落盘证据）
    fresh = WordDetailsCacheStore(ctrl._detail_cache.path)
    fresh.load()
    item = fresh.get("n5-0007")
    assert item is not None, "联网成功后详情未落盘"
    assert item.detail.meaning_zh == ("联网义",)
    assert item.fetched_at, "fetched_at 应由 app 层注入且非空"


def test_qa_controller_on_succeeded_ignores_empty(qa_controller: PetAppController) -> None:
    ctrl = qa_controller
    ctrl._on_detail_succeeded("n5-0008", WordDetail())
    assert ctrl._detail_cache.get("n5-0008") is None


def test_qa_corrupt_cache_backed_up_not_silently_cleared(qa_controller: PetAppController) -> None:
    ctrl = qa_controller
    path = ctrl._detail_cache.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ 这不是合法 JSON", encoding="utf-8")

    store = WordDetailsCacheStore(path)
    assert store.load() == {}
    backups = list(path.parent.glob(path.name + ".corrupt-*"))
    assert len(backups) == 1, f"损坏缓存必须备份：{backups}"
    assert not path.exists(), "损坏文件应被移走（备份），而非静默清空原地重写"


# =========================================================================== #
# 组 5：两入口一致性（同一窗口单例 + 同一渲染路径）
# =========================================================================== #
def test_qa_two_entries_share_singleton_and_render(qa_controller: PetAppController) -> None:
    ctrl = qa_controller
    ctrl._detail_bank = WordDetailBank({"n5-0001": _detail("库义")})

    ctrl._on_log_word_double_clicked("n5-0001")
    window = ctrl._detail_window
    assert window is not None
    first = (window._word_label.text(), window._meaning_label.text())

    ctrl._on_vocab_word_double_clicked("n5-0001")
    assert ctrl._detail_window is window, "两入口应复用同一窗口单例"
    assert (window._word_label.text(), window._meaning_label.text()) == first


def test_qa_both_entry_signals_route_to_same_handler(
    qa_controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl = qa_controller
    ctrl._detail_bank = WordDetailBank({"n5-0001": _detail("库义")})
    opened: list[str] = []
    monkeypatch.setattr(ctrl, "_open_word_detail", lambda entry: opened.append(entry.id))

    # 生词本入口：窗口信号 → controller 槽 → _open_word_detail
    ctrl._on_jp_vocab()
    assert ctrl._vocab_window is not None
    ctrl._vocab_window.word_double_clicked.emit("n5-0001")

    # 学习记录入口：窗口信号 → controller 槽 → _open_word_detail
    ctrl._on_jp_log()
    assert ctrl._log_window is not None
    ctrl._log_window.word_double_clicked.emit("n5-0001")

    assert opened == ["n5-0001", "n5-0001"], "两入口未汇聚到同一 _open_word_detail 处理器"


def test_qa_stale_network_result_must_not_overwrite_new_local_entry(qtbot) -> None:
    """打开 A（联网挂起）后立刻打开 B（本地命中）；A 的迟到结果不得污染 B 的展示。"""
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)

    window.show_entry(_entry(1), detail=None, net=_net("sk-stale"))   # A：loading + worker
    assert pool.started, "A 应启动后台查询"
    worker_a = pool.started[-1]

    window.show_entry(_entry(2), detail=_detail("乙义"), source=C.WORD_DETAIL_SOURCE_LOCAL)
    assert window._word_label.text() == "語2"
    assert window._meaning_label.text() == "乙义"

    # 模拟 A 的 worker 完成（跨线程 QueuedConnection → 走事件循环）
    worker_a.signals.succeeded.emit("n5-0001", _detail("甲义"))  # type: ignore[attr-defined]
    QApplication.processEvents()

    # 当前窗口打开的仍是 B，绝不能显示 A 的内容
    assert window._word_label.text() == "語2"
    assert window._meaning_label.text() == "乙义", "迟到的联网结果覆盖了当前词条（缺 item_id 守卫）"


def test_qa_stale_network_failure_must_not_pollute_new_local_entry(qtbot) -> None:
    """同一根因：A 的迟到失败回调不得在 B（本地命中）上显示错误态。"""
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)

    window.show_entry(_entry(1), detail=None, net=_net("sk-stale"))
    worker_a = pool.started[-1]

    window.show_entry(_entry(2), detail=_detail("乙义"), source=C.WORD_DETAIL_SOURCE_LOCAL)
    worker_a.signals.failed.emit("n5-0001", "网络错误：boom")  # type: ignore[attr-defined]
    QApplication.processEvents()

    assert window._meaning_label.text() == "乙义"
    assert window._status_label.text() == "", "迟到的联网失败污染了当前词条的展示"


# =========================================================================== #
# 组 6：LLM 客户端（mock urlopen）
# =========================================================================== #
_RAW = {
    C.WORD_DETAIL_FIELD_MEANING: ["我"],
    C.WORD_DETAIL_FIELD_POS: ["代词"],
    C.WORD_DETAIL_FIELD_COLLOCATIONS: [{"phrase": "私は…", "note": "自我介绍"}],
    C.WORD_DETAIL_FIELD_EXAMPLES: [{"jp": "私は学生です。", "zh": "我是学生。"}],
    C.WORD_DETAIL_FIELD_USAGE: "正式、通用。",
}


class _Resp:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _envelope(content: str) -> str:
    return json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False)


def test_qa_request_shape_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    cap: dict[str, object] = {}

    def fake(request, timeout=None):
        cap["url"] = request.full_url
        cap["method"] = request.get_method()
        cap["headers"] = {k.lower(): v for k, v in request.header_items()}
        cap["body"] = json.loads(request.data.decode("utf-8"))
        cap["timeout"] = timeout
        return _Resp(_envelope(json.dumps(_RAW, ensure_ascii=False)))

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake)
    client = DeepSeekClient(
        api_key="sk-qa", base_url=C.LLM_ENDPOINT, model=C.LLM_MODEL,
        timeout_s=7.5, retries=0,
    )
    detail = client.fetch_word_detail("私", "わたし", "N5", "我")

    assert detail == WordDetail.from_dict(_RAW)
    assert cap["url"] == C.LLM_ENDPOINT
    assert cap["method"] == "POST"
    assert cap["headers"]["authorization"] == "Bearer sk-qa"
    assert cap["headers"]["content-type"] == "application/json"
    body = cap["body"]
    assert body["model"] == C.LLM_MODEL
    assert body["response_format"] == {"type": C.LLM_RESPONSE_FORMAT_TYPE}
    assert body["temperature"] == C.LLM_TEMPERATURE
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert cap["timeout"] == 7.5


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(_RAW, ensure_ascii=False),
        "```json\n" + json.dumps(_RAW, ensure_ascii=False) + "\n```",
        "前言" + json.dumps(_RAW, ensure_ascii=False) + "后语",
        _envelope(json.dumps(_RAW, ensure_ascii=False)),
    ],
)
def test_qa_extract_json_accepts_variants(text: str) -> None:
    assert DeepSeekClient._extract_json(text) == _RAW


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "完全没有 JSON", '{"meaning_zh": ["我"', "[1,2,3]", "```json\n{\"a\":1"],
)
def test_qa_extract_json_rejects_bad(bad: str) -> None:
    with pytest.raises(LLMParseError):
        DeepSeekClient._extract_json(bad)


def test_qa_empty_key_config_error_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake(request, timeout=None):
        calls["n"] += 1
        return _Resp("{}")

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake)
    with pytest.raises(LLMConfigError):
        DeepSeekClient(api_key="").fetch_word_detail("私")
    assert calls["n"] == 0


def test_qa_401_auth_error_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake(request, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(C.LLM_ENDPOINT, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake)
    with pytest.raises(LLMAuthError):
        DeepSeekClient(api_key="sk", retries=3).fetch_word_detail("私")
    assert calls["n"] == 1


def test_qa_429_is_network_error_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake(request, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(C.LLM_ENDPOINT, 429, "Too Many", {}, None)

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake)
    with pytest.raises(LLMNetworkError):
        DeepSeekClient(api_key="sk", retries=2).fetch_word_detail("私")
    assert calls["n"] == 3


def test_qa_timeout_is_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(request, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake)
    with pytest.raises(LLMNetworkError):
        DeepSeekClient(api_key="sk", retries=0).fetch_word_detail("私")


def test_qa_bad_json_is_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_client.urllib.request, "urlopen",
        lambda request, timeout=None: _Resp("这不是 JSON"),
    )
    with pytest.raises(LLMParseError):
        DeepSeekClient(api_key="sk", retries=0).fetch_word_detail("私")


def test_qa_worker_run_never_raises(qtbot) -> None:
    # net=None → failed，不裸抛
    worker = WordDetailWorker("n5-0001", "私", "", "N5", "", None)  # type: ignore[arg-type]
    failed: list[str] = []
    worker.signals.failed.connect(lambda iid, msg: failed.append(iid))
    worker.run()
    assert failed == ["n5-0001"]

    # 客户端内部抛未预期异常 → 转 failed，不裸抛
    worker2 = WordDetailWorker("n5-0002", "私", "", "N5", "", _net())
    failed2: list[str] = []
    worker2.signals.failed.connect(lambda iid, msg: failed2.append(iid))
    worker2.run()  # 无 mock：真实 urllib 会因网络失败转 LLMNetworkError → failed
    assert failed2 == ["n5-0002"]


# =========================================================================== #
# 组 7：真实详情库端到端完整性（含 phrase / jp 全字段）
# =========================================================================== #
def _load_details() -> dict:
    if not _DETAILS_PATH.exists():
        pytest.skip(f"详情库尚未生成：{_DETAILS_PATH}")
    return json.loads(_DETAILS_PATH.read_text(encoding="utf-8"))


def test_qa_english_scanner_is_effective() -> None:
    """自检：扫描器确实能命中英文（防止断言恒真）。"""
    assert _ENGLISH.findall("这是 english 残留") == ["english"]
    assert _ENGLISH.findall("纯粹中文，无英文") == []


def test_qa_details_full_field_no_english_residue() -> None:
    """**全字段**（含 collocation.phrase 与 example.jp）扫描英文残留。"""
    payload = _load_details()
    offenders: list[str] = []
    for item_id, raw in payload["details"].items():
        detail = WordDetail.from_dict(raw)
        assert detail is not None, item_id
        values = (
            list(detail.meaning_zh)
            + list(detail.pos_zh)
            + [detail.usage_note_zh]
            + [c.phrase for c in detail.collocations]
            + [c.note for c in detail.collocations]
            + [e.jp for e in detail.examples]
            + [e.zh for e in detail.examples]
        )
        for value in values:
            hits = [t for t in _ENGLISH.findall(value) if t.lower() not in _ALLOWED]
            if hits:
                offenders.append(f"{item_id}: {value!r} -> {hits}")
    assert not offenders, f"发现英文残留：{offenders[:10]}"


def test_qa_details_500_ids_one_to_one() -> None:
    payload = _load_details()
    bank = json.loads(_BANK_PATH.read_text(encoding="utf-8"))
    bank_ids = [w["id"] for w in bank["words"]]
    assert len(bank_ids) == len(set(bank_ids)) == 500, "词库 id 数量/唯一性异常"
    assert set(payload["details"]) == set(bank_ids), "详情库与词库 id 非一一对应"
    assert len(payload["details"]) == 500


def test_qa_details_bank_loads_and_random_samples_non_empty() -> None:
    bank = WordDetailBank.load(_DETAILS_PATH)
    assert bank.size() == 500
    words = json.loads(_BANK_PATH.read_text(encoding="utf-8"))["words"]
    rng = random.Random(20240916)
    for word in rng.sample(words, 10):
        detail = bank.get(word["id"])
        assert detail is not None, f"{word['id']} 详情库未命中"
        assert not detail.is_empty(), f"{word['id']} 五要素全空"


def test_qa_details_field_types_and_limits() -> None:
    payload = _load_details()
    for item_id, raw in payload["details"].items():
        assert isinstance(raw["meaning_zh"], list), item_id
        assert isinstance(raw["pos_zh"], list), item_id
        assert isinstance(raw["collocations"], list), item_id
        assert isinstance(raw["examples"], list), item_id
        assert isinstance(raw["usage_note_zh"], str), item_id
        detail = WordDetail.from_dict(raw)
        assert detail is not None
        assert len(detail.meaning_zh) <= C.WORD_DETAIL_MAX_MEANINGS, item_id
        assert len(detail.examples) <= C.WORD_DETAIL_MAX_EXAMPLES, item_id
        assert len(detail.collocations) <= C.WORD_DETAIL_MAX_COLLOCATIONS, item_id


# =========================================================================== #
# 组 8：边界容错
# =========================================================================== #
def test_qa_bank_load_boundaries(tmp_path: Path) -> None:
    # 缺失
    assert WordDetailBank.load(tmp_path / "missing.json").is_empty()
    # 空文件
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert WordDetailBank.load(empty).is_empty()
    # 根非对象
    root = tmp_path / "root.json"
    root.write_text("[1, 2, 3]", encoding="utf-8")
    assert WordDetailBank.load(root).is_empty()
    # details 非对象
    det = tmp_path / "det.json"
    det.write_text(json.dumps({"version": 1, "details": [1, 2]}), encoding="utf-8")
    assert WordDetailBank.load(det).is_empty()
    # 单条非法跳过、合法保留
    mixed = tmp_path / "mixed.json"
    mixed.write_text(
        json.dumps({"version": 1, "details": {"good": {"meaning_zh": ["义"]}, "bad": "字符串"}}),
        encoding="utf-8",
    )
    bank = WordDetailBank.load(mixed)
    assert bank.size() == 1
    assert bank.get("good") is not None
    assert bank.get("bad") is None


@pytest.mark.parametrize(
    "bad",
    [None, "字符串", [], 123, 3.14],
)
def test_qa_from_dict_non_dict_returns_none(bad) -> None:
    assert WordDetail.from_dict(bad) is None


def test_qa_from_dict_empty_dict_is_all_empty() -> None:
    """空 dict → 全空 WordDetail（不是 None）；is_empty() 为真。"""
    detail = WordDetail.from_dict({})
    assert detail is not None and detail.is_empty()


def test_qa_from_dict_meaning_str_and_invalid_fields() -> None:
    # meaning_zh 为 str → 单元素
    assert WordDetail.from_dict({"meaning_zh": "我"}).meaning_zh == ("我",)  # type: ignore[union-attr]
    # 全字段非法 → 全空
    detail = WordDetail.from_dict(
        {
            "meaning_zh": 123,
            "pos_zh": {"不是", "列表"},
            "collocations": "不是列表",
            "examples": 5,
            "usage_note_zh": None,
        }
    )
    assert detail is not None and detail.is_empty()


def test_qa_truncated_limit_branches() -> None:
    detail = WordDetail(meaning_zh=("a", "b", "c", "d"))
    assert detail.truncated({"meaning_zh": 2}).meaning_zh == ("a", "b")
    assert detail.truncated({"meaning_zh": True}).meaning_zh == ("a", "b", "c")   # bool → 默认 3
    assert detail.truncated({"meaning_zh": -1}).meaning_zh == ("a", "b", "c")     # 非法 → 默认 3
    assert detail.truncated({}).meaning_zh == ("a", "b", "c")                     # 缺键 → 默认 3


# =========================================================================== #
# 组 9：死代码检查（jisho 残留）
# =========================================================================== #
def test_qa_no_jisho_in_detail_window_source(project_root: Path) -> None:
    source = (project_root / "src" / "desktop_pet" / "ui" / "word_detail_window.py").read_text(
        encoding="utf-8"
    )
    assert "jisho" not in source.lower()


def test_qa_no_jisho_in_controller_source(project_root: Path) -> None:
    source = (project_root / "src" / "desktop_pet" / "app" / "controller.py").read_text(
        encoding="utf-8"
    )
    assert "jisho" not in source.lower()


def test_qa_window_exposes_no_jisho_signals() -> None:
    names = [name for name in dir(WordDetailWindow) if "jisho" in name.lower()]
    assert names == [], f"详情窗口仍有 jisho 相关符号：{names}"


def test_qa_detail_chain_no_jisho_imports() -> None:
    for module in (
        llm_client,
        WordDetailWindow,
        WordDetailWorker,
    ):
        src_file = getattr(module, "__file__", None)
        if not src_file:
            continue
        text = Path(src_file).read_text(encoding="utf-8").lower()
        assert "import jisho" not in text and "from desktop_pet.core.jisho" not in text


# =========================================================================== #
# 组 10：第 2 轮 —— BUG-1 修复后的竞态边界（回归 + 新增场景）
# =========================================================================== #
def _process() -> None:
    QApplication.processEvents()


def test_qa_stale_success_then_stale_failure_keeps_new_entry(qtbot) -> None:
    """A 挂起 → 打开本地命中 B → A 的成功回调到达 → A 的失败回调再到达；窗口始终只显示 B。"""
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)

    window.show_entry(_entry(1), detail=None, net=_net("sk-a"))     # A：挂起
    worker_a = pool.started[-1]
    window.show_entry(
        _entry(2), _detail("乙义"), C.WORD_DETAIL_SOURCE_LOCAL, net=_net("sk-a")
    )

    worker_a.signals.succeeded.emit("n5-0001", _detail("甲义"))      # 陈旧成功
    _process()
    worker_a.signals.failed.emit("n5-0001", "boom")                  # 陈旧失败
    _process()

    assert window._word_label.text() == "語2"
    assert window._meaning_label.text() == "乙义"
    assert window._status_label.text() == ""


def test_qa_close_window_then_stale_callbacks_are_safe(qtbot) -> None:
    """A 挂起 → 打开本地命中 B → 关闭窗口 → A 回调到达：无异常、无渲染、无上报。"""
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)

    window.show_entry(_entry(1), detail=None, net=_net("sk-a"))
    worker_a = pool.started[-1]
    window.show_entry(_entry(2), _detail("乙义"), C.WORD_DETAIL_SOURCE_LOCAL)

    emitted: list[str] = []
    window.detail_succeeded.connect(lambda iid, _d: emitted.append(iid))
    window.detail_failed.connect(lambda iid, _m: emitted.append(iid))

    window.close()                                                  # 关闭窗口
    assert pool.cleared is True
    assert window._closed is True

    worker_a.signals.succeeded.emit("n5-0001", _detail("甲义"))       # 关闭后到达
    _process()
    worker_a.signals.failed.emit("n5-0001", "boom")
    _process()

    assert emitted == [], "关闭后不应再上报 controller"
    assert window._meaning_label.text() == "乙义"                    # 未被污染


def test_qa_double_retry_only_current_result_applies(qtbot) -> None:
    """重试按钮连点两次：只有最后一次的 worker 结果被采纳。"""
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)

    window.show_entry(_entry(1), detail=None, net=_net("sk"))      # worker1
    worker1 = pool.started[-1]
    window._on_retry()                                             # worker2（worker1 断连）
    assert len(pool.started) == 2
    worker2 = pool.started[-1]

    worker1.signals.succeeded.emit("n5-0001", _detail("旧结果"))    # 陈旧
    _process()
    assert window._meaning_label.text() == ""                      # 未采纳
    assert window._status_label.text() == C.WORD_DETAIL_LOADING

    worker2.signals.succeeded.emit("n5-0001", _detail("新结果"))
    _process()
    assert window._meaning_label.text() == "新结果"


def test_qa_repeat_show_entry_same_word_ignores_old_worker(qtbot) -> None:
    """同一词重复 show_entry：旧 worker 结果被丢弃，只有最新 worker 生效。"""
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)

    window.show_entry(_entry(1), detail=None, net=_net("sk"))
    worker1 = pool.started[-1]
    window.show_entry(_entry(1), detail=None, net=_net("sk"))
    worker2 = pool.started[-1]

    worker1.signals.succeeded.emit("n5-0001", _detail("旧"))
    _process()
    assert window._meaning_label.text() == ""

    worker2.signals.succeeded.emit("n5-0001", _detail("新"))
    _process()
    assert window._meaning_label.text() == "新"


def test_qa_net_disabled_after_pending_ignores_old_callback(qtbot) -> None:
    """A 挂起后配置变为「无网」→ 离线降级；旧 worker 迟到回调不得改写界面。"""
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)

    window.show_entry(_entry(1), detail=None, net=_net("sk"))      # 有 key → 挂起
    worker1 = pool.started[-1]
    window.show_entry(_entry(1), detail=None, net=_net(""))        # 配置变无 key → 离线
    assert window._status_label.text() == C.WORD_DETAIL_OFFLINE_HINT

    worker1.signals.succeeded.emit("n5-0001", _detail("迟到"))      # item_id 与当前相同，但已断连
    _process()
    assert window._status_label.text() == C.WORD_DETAIL_OFFLINE_HINT
    assert window._meaning_label.text() == ""


def test_qa_offline_ui_has_no_english_ascii(qtbot) -> None:
    """OBS-4：离线降级界面无任何 ≥3 连续字母的英文词。"""
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    window.show_entry(_entry(1), detail=None, net=_net(""))
    text = _all_text(window)
    assert not re.search(r"[A-Za-z]{3,}", text), f"离线界面出现英文残留：{text!r}"
    assert "密钥" in window._status_label.text()


def test_qa_queued_result_emitted_before_switch_is_not_applied(qtbot) -> None:
    """A 的结果已入队（emit 但未 processEvents）后立刻切到本地命中 B：排队中的陈旧结果不得回填。"""
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)

    window.show_entry(_entry(1), detail=None, net=_net("sk-a"))
    worker_a = pool.started[-1]
    worker_a.signals.succeeded.emit("n5-0001", _detail("甲义"))   # 已投递（Queued），未处理事件
    window.show_entry(_entry(2), _detail("乙义"), C.WORD_DETAIL_SOURCE_LOCAL)
    _process()

    assert window._word_label.text() == "語2"
    assert window._meaning_label.text() == "乙义"


def test_qa_deleted_constants_absent_and_kept_present(project_root: Path) -> None:
    """OBS-3：死常量已删；KANA / MEANING_ZH 仍在且被引用。"""
    constants = (project_root / "src" / "desktop_pet" / "core" / "constants.py").read_text(
        encoding="utf-8"
    )
    for dead in (
        "WORD_DETAIL_LABEL_WORD",
        "WORD_DETAIL_LABEL_ROMAJI",
        "WORD_DETAIL_LABEL_TRANSLATION",
        "WORD_DETAIL_LABEL_LEVEL",
    ):
        assert dead not in constants, f"死常量未删除：{dead}"
    for kept in ("WORD_DETAIL_LABEL_KANA", "WORD_DETAIL_LABEL_MEANING_ZH"):
        assert kept in constants, f"在用常量被误删：{kept}"
    window_src = (
        project_root / "src" / "desktop_pet" / "ui" / "word_detail_window.py"
    ).read_text(encoding="utf-8")
    assert "WORD_DETAIL_LABEL_KANA" in window_src
    assert "WORD_DETAIL_LABEL_MEANING_ZH" in window_src

