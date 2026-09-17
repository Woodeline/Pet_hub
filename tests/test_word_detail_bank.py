"""``core.word_detail_bank`` 单测（打包详情库加载容错 / 查询）。

全部为 ``core`` 纯逻辑测试，**不需要 Qt**。
"""

from __future__ import annotations

import json
from pathlib import Path

from desktop_pet.core import constants as C
from desktop_pet.core.word_detail import Collocation, Example, WordDetail
from desktop_pet.core.word_detail_bank import WordDetailBank


def _detail_dict(meaning: str = "我") -> dict:
    return {
        C.WORD_DETAIL_FIELD_MEANING: [meaning],
        C.WORD_DETAIL_FIELD_POS: ["代词"],
        C.WORD_DETAIL_FIELD_COLLOCATIONS: [{"phrase": "私は…", "note": "自我介绍"}],
        C.WORD_DETAIL_FIELD_EXAMPLES: [{"jp": "私は学生です。", "zh": "我是学生。"}],
        C.WORD_DETAIL_FIELD_USAGE: "正式、通用。",
    }


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. 加载容错（缺失 / 空 / 结构损坏 → 空库）
# --------------------------------------------------------------------------- #
def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    bank = WordDetailBank.load(tmp_path / "nope.json")
    assert bank.is_empty() and bank.size() == 0
    assert bank.get("n5-0001") is None


def test_load_empty_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text("", encoding="utf-8")
    assert WordDetailBank.load(path).is_empty()


def test_load_invalid_json_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text("{ not json ]", encoding="utf-8")
    assert WordDetailBank.load(path).is_empty()


def test_load_non_object_root_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    _write(path, [1, 2, 3])
    assert WordDetailBank.load(path).is_empty()


def test_load_details_not_object_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    _write(path, {"version": 1, "details": [1, 2]})
    assert WordDetailBank.load(path).is_empty()


# --------------------------------------------------------------------------- #
# 2. 逐条容错
# --------------------------------------------------------------------------- #
def test_load_skips_invalid_keeps_valid(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    _write(
        path,
        {
            "version": C.WORD_DETAILS_FILE_VERSION,
            "details": {
                "n5-0001": _detail_dict("我"),
                "": _detail_dict("空键"),          # 非法键 → 跳过
                "n5-0002": "not-a-dict",            # 非法值 → 跳过
                "n5-0003": _detail_dict("三"),
            },
        },
    )
    bank = WordDetailBank.load(path)
    assert bank.size() == 2
    assert bank.get("n5-0001") is not None
    assert bank.get("n5-0003") is not None
    assert bank.get("n5-0002") is None


# --------------------------------------------------------------------------- #
# 3. 查询
# --------------------------------------------------------------------------- #
def test_get_returns_none_for_unknown(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    _write(path, {"version": 1, "details": {"n5-0001": _detail_dict()}})
    bank = WordDetailBank.load(path)
    assert bank.get("n5-9999") is None
    assert bank.get("") is None


def test_get_returns_none_for_empty_content(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    _write(path, {"version": 1, "details": {"n5-0001": {}}})
    bank = WordDetailBank.load(path)
    assert bank.get("n5-0001") is None
    assert bank.size() == 1  # 条目在，但内容为空 → 查询视为未命中


def test_get_returns_detail(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    _write(path, {"version": 1, "details": {"n5-0001": _detail_dict("我")}})
    detail = WordDetailBank.load(path).get("n5-0001")
    assert detail == WordDetail(
        meaning_zh=("我",),
        pos_zh=("代词",),
        collocations=(Collocation("私は…", "自我介绍"),),
        examples=(Example("私は学生です。", "我是学生。"),),
        usage_note_zh="正式、通用。",
    )


def test_empty_bank() -> None:
    bank = WordDetailBank.empty()
    assert bank.is_empty() is True
    assert bank.size() == 0
