"""``core.word_detail`` 数据模型单测（逐字段容错 / str 兼容 / is_empty / truncated）。

全部为 ``core`` 纯逻辑测试，**不需要 Qt**，也不触碰任何用户目录。
"""

from __future__ import annotations

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.word_detail import Collocation, Example, WordDetail


# --------------------------------------------------------------------------- #
# 1. from_dict 顶层容错
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [None, [], "str", 42, True])
def test_from_dict_non_dict_returns_none(bad) -> None:
    assert WordDetail.from_dict(bad) is None


def test_from_dict_empty_dict_is_all_empty() -> None:
    detail = WordDetail.from_dict({})
    assert detail is not None
    assert detail == WordDetail()
    assert detail.is_empty() is True


# --------------------------------------------------------------------------- #
# 2. meaning_zh 兼容 str 与 str[]
# --------------------------------------------------------------------------- #
def test_meaning_zh_str_becomes_single_element() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_MEANING: "我"})
    assert detail is not None
    assert detail.meaning_zh == ("我",)


def test_meaning_zh_str_list_kept() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_MEANING: ["我", "吾"]})
    assert detail is not None
    assert detail.meaning_zh == ("我", "吾")


def test_meaning_zh_blank_str_is_empty() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_MEANING: "   "})
    assert detail is not None
    assert detail.meaning_zh == ()


@pytest.mark.parametrize("bad", [123, {"a": 1}, None, [1, 2], ["", "  "]])
def test_meaning_zh_invalid_types_are_empty(bad) -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_MEANING: bad})
    assert detail is not None
    assert detail.meaning_zh == ()


def test_str_tuple_dedup_and_strip() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_MEANING: [" 我 ", "我", "", "吾"]})
    assert detail is not None
    assert detail.meaning_zh == ("我", "吾")


# --------------------------------------------------------------------------- #
# 3. pos_zh / usage_note_zh
# --------------------------------------------------------------------------- #
def test_pos_zh_list() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_POS: ["代词", "名词"]})
    assert detail is not None
    assert detail.pos_zh == ("代词", "名词")


def test_pos_zh_str_becomes_single() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_POS: "动词"})
    assert detail is not None
    assert detail.pos_zh == ("动词",)


def test_usage_note_non_str_is_empty() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_USAGE: 123})
    assert detail is not None
    assert detail.usage_note_zh == ""


def test_usage_note_stripped() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_USAGE: "  正式 "})
    assert detail is not None
    assert detail.usage_note_zh == "正式"


# --------------------------------------------------------------------------- #
# 4. collocations / examples 容错
# --------------------------------------------------------------------------- #
def test_collocations_parsed() -> None:
    detail = WordDetail.from_dict(
        {
            C.WORD_DETAIL_FIELD_COLLOCATIONS: [
                {"phrase": "私は…", "note": "自我介绍"},
                {"phrase": "私の"},              # 缺 note → 允许
            ]
        }
    )
    assert detail is not None
    assert detail.collocations == (
        Collocation("私は…", "自我介绍"),
        Collocation("私の", ""),
    )


def test_collocations_bare_string_tolerated() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_COLLOCATIONS: ["私は…"]})
    assert detail is not None
    assert detail.collocations == (Collocation("私は…", ""),)


def test_collocations_invalid_items_skipped() -> None:
    detail = WordDetail.from_dict(
        {
            C.WORD_DETAIL_FIELD_COLLOCATIONS: [
                {"note": "无短语"},   # 缺 phrase → 跳过
                123,                   # 非 dict/str → 跳过
                {"phrase": "良い"},
            ]
        }
    )
    assert detail is not None
    assert detail.collocations == (Collocation("良い", ""),)


def test_collocations_non_list_is_empty() -> None:
    detail = WordDetail.from_dict({C.WORD_DETAIL_FIELD_COLLOCATIONS: "oops"})
    assert detail is not None
    assert detail.collocations == ()


def test_examples_parsed() -> None:
    detail = WordDetail.from_dict(
        {
            C.WORD_DETAIL_FIELD_EXAMPLES: [
                {"jp": "私は学生です。", "zh": "我是学生。"},
                {"jp": "行きます。"},        # 缺 zh → 允许
            ]
        }
    )
    assert detail is not None
    assert detail.examples == (
        Example("私は学生です。", "我是学生。"),
        Example("行きます。", ""),
    )


def test_examples_invalid_items_skipped() -> None:
    detail = WordDetail.from_dict(
        {C.WORD_DETAIL_FIELD_EXAMPLES: [{"zh": "无日文"}, "食べます。", None]}
    )
    assert detail is not None
    assert detail.examples == (Example("食べます。", ""),)


# --------------------------------------------------------------------------- #
# 5. Collocation / Example from_dict 单测
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [None, [], 3, {}, {"phrase": ""}, {"phrase": "  "}])
def test_collocation_from_dict_invalid(bad) -> None:
    assert Collocation.from_dict(bad) is None


@pytest.mark.parametrize("bad", [None, [], 3, {}, {"jp": ""}, {"jp": 123}])
def test_example_from_dict_invalid(bad) -> None:
    assert Example.from_dict(bad) is None


# --------------------------------------------------------------------------- #
# 6. is_empty
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "detail",
    [
        WordDetail(),
        WordDetail(meaning_zh=(), pos_zh=(), collocations=(), examples=(), usage_note_zh=""),
    ],
)
def test_is_empty_true(detail: WordDetail) -> None:
    assert detail.is_empty() is True


@pytest.mark.parametrize(
    "detail",
    [
        WordDetail(meaning_zh=("我",)),
        WordDetail(pos_zh=("代词",)),
        WordDetail(collocations=(Collocation("私は…"),)),
        WordDetail(examples=(Example("私は学生です。"),)),
        WordDetail(usage_note_zh="正式"),
    ],
)
def test_is_empty_false(detail: WordDetail) -> None:
    assert detail.is_empty() is False


# --------------------------------------------------------------------------- #
# 7. to_dict / 往返
# --------------------------------------------------------------------------- #
def _full_detail() -> WordDetail:
    return WordDetail(
        meaning_zh=("我", "吾"),
        pos_zh=("代词",),
        collocations=(Collocation("私は…", "自我介绍"),),
        examples=(Example("私は学生です。", "我是学生。"),),
        usage_note_zh="正式、通用。",
    )


def test_to_dict_keys_match_constants() -> None:
    data = _full_detail().to_dict()
    assert set(data) == {
        C.WORD_DETAIL_FIELD_MEANING,
        C.WORD_DETAIL_FIELD_POS,
        C.WORD_DETAIL_FIELD_COLLOCATIONS,
        C.WORD_DETAIL_FIELD_EXAMPLES,
        C.WORD_DETAIL_FIELD_USAGE,
    }
    assert data[C.WORD_DETAIL_FIELD_MEANING] == ["我", "吾"]
    assert data[C.WORD_DETAIL_FIELD_COLLOCATIONS] == [{"phrase": "私は…", "note": "自我介绍"}]


def test_to_dict_from_dict_roundtrip() -> None:
    detail = _full_detail()
    again = WordDetail.from_dict(detail.to_dict())
    assert again == detail


# --------------------------------------------------------------------------- #
# 8. truncated
# --------------------------------------------------------------------------- #
def test_truncated_default_limits() -> None:
    detail = WordDetail(
        meaning_zh=tuple(f"义{i}" for i in range(6)),
        pos_zh=("名词",),
        collocations=tuple(Collocation(f"短语{i}") for i in range(8)),
        examples=tuple(Example(f"例{i}") for i in range(6)),
        usage_note_zh="语气",
    )
    cut = detail.truncated()
    assert len(cut.meaning_zh) == C.WORD_DETAIL_MAX_MEANINGS == 3
    assert len(cut.examples) == C.WORD_DETAIL_MAX_EXAMPLES == 3
    assert len(cut.collocations) == C.WORD_DETAIL_MAX_COLLOCATIONS == 5
    # 词性 / 语气提示不裁剪
    assert cut.pos_zh == ("名词",)
    assert cut.usage_note_zh == "语气"


def test_truncated_custom_limits() -> None:
    detail = WordDetail(
        meaning_zh=("a", "b", "c"),
        collocations=tuple(Collocation(f"p{i}") for i in range(4)),
        examples=tuple(Example(f"e{i}") for i in range(4)),
    )
    cut = detail.truncated(
        {
            C.WORD_DETAIL_FIELD_MEANING: 1,
            C.WORD_DETAIL_FIELD_COLLOCATIONS: 2,
            C.WORD_DETAIL_FIELD_EXAMPLES: 0,
        }
    )
    assert cut.meaning_zh == ("a",)
    assert len(cut.collocations) == 2
    assert cut.examples == ()


def test_truncated_invalid_limits_fall_back_to_default() -> None:
    detail = WordDetail(meaning_zh=tuple(f"义{i}" for i in range(6)))
    cut = detail.truncated({C.WORD_DETAIL_FIELD_MEANING: True})  # bool 非法 → 默认
    assert len(cut.meaning_zh) == C.WORD_DETAIL_MAX_MEANINGS


def test_truncated_shorter_than_limit_unchanged() -> None:
    detail = WordDetail(meaning_zh=("我",), examples=(Example("例"),))
    assert detail.truncated() == detail


# --------------------------------------------------------------------------- #
# 9. 不可变性
# --------------------------------------------------------------------------- #
def test_frozen_dataclasses_are_immutable() -> None:
    detail = WordDetail(meaning_zh=("我",))
    with pytest.raises(Exception):
        detail.meaning_zh = ("你",)  # type: ignore[misc]
    with pytest.raises(Exception):
        Collocation("p").phrase = "x"  # type: ignore[misc]
    with pytest.raises(Exception):
        Example("jp").jp = "x"  # type: ignore[misc]
