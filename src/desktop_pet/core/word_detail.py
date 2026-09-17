"""core.word_detail —— 日语单词详情的中文五要素数据模型（纯逻辑）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

数据契约（设计 §3.1，键为词条的 ``id``）::

    {
      "meaning_zh": ["我"],                       # str 或 str[]，多义项
      "pos_zh": ["代词"],                          # str[]，中文词性标签
      "collocations": [{"phrase": "私は…", "note": "自我介绍常用"}],
      "examples": [{"jp": "私は学生です。", "zh": "我是学生。"}],
      "usage_note_zh": "正式、通用，男女皆可用。"
    }

要点：
- 五字段**均可空**；全部为空视作「本地未命中」（:meth:`WordDetail.is_empty`）。
- 逐字段容错：非法字段静默跳过，绝不抛异常；``meaning_zh`` 兼容 ``str`` 与 ``str[]``。
- 展示上限（释义 ≤3 / 例句 ≤3 / 搭配 ≤5）由 :meth:`WordDetail.truncated` 强制。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desktop_pet.core import constants as C

#: 未显式提供 ``limits`` 时的默认展示上限（键为字段键名，值为上限条数）
DEFAULT_LIMITS: "dict[str, int]" = {
    C.WORD_DETAIL_FIELD_MEANING: C.WORD_DETAIL_MAX_MEANINGS,
    C.WORD_DETAIL_FIELD_EXAMPLES: C.WORD_DETAIL_MAX_EXAMPLES,
    C.WORD_DETAIL_FIELD_COLLOCATIONS: C.WORD_DETAIL_MAX_COLLOCATIONS,
}


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """把 ``str`` / ``str[]`` 安全归一为「去空白、去重、非空」的字符串元组。

    - ``str`` → 单元素元组（空串 → 空元组）。
    - ``list`` / ``tuple`` → 逐项校验，非法项跳过。
    - 其它类型 → 空元组。
    """

    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip() and item.strip() not in result:
                result.append(item.strip())
        return tuple(result)
    return ()


def _as_optional_str(value: Any) -> str:
    """把任意值安全归一为非 ``None`` 的字符串（非字符串 → 空串）。"""

    return value.strip() if isinstance(value, str) else ""


def _positive_limit(value: Any, default: int) -> int:
    """把上限值收敛为非负整数；非法值回落默认（``bool`` 视为非法）。"""

    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    return default


@dataclass(frozen=True)
class Collocation:
    """一条常见搭配（短语 + 可选用法说明）。"""

    phrase: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {"phrase": self.phrase, "note": self.note}

    @classmethod
    def from_dict(cls, data: Any) -> "Collocation | None":
        """逐字段容错构造搭配；``phrase`` 缺失/非字符串/空串则返回 ``None``。

        为稳健起见亦兼容「裸字符串」形式（仅短语，无说明）。
        """

        if isinstance(data, str):
            phrase = data.strip()
            return cls(phrase=phrase) if phrase else None
        if not isinstance(data, dict):
            return None
        phrase = _as_optional_str(data.get("phrase"))
        if not phrase:
            return None
        return cls(phrase=phrase, note=_as_optional_str(data.get("note")))


@dataclass(frozen=True)
class Example:
    """一条典型例句（日文原句 + 中文翻译）。"""

    jp: str
    zh: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {"jp": self.jp, "zh": self.zh}

    @classmethod
    def from_dict(cls, data: Any) -> "Example | None":
        """逐字段容错构造例句；``jp`` 缺失/非字符串/空串则返回 ``None``。

        为稳健起见亦兼容「裸字符串」形式（仅日文，无翻译）。
        """

        if isinstance(data, str):
            jp = data.strip()
            return cls(jp=jp) if jp else None
        if not isinstance(data, dict):
            return None
        jp = _as_optional_str(data.get("jp"))
        if not jp:
            return None
        return cls(jp=jp, zh=_as_optional_str(data.get("zh")))


def _as_collocations(value: Any) -> tuple[Collocation, ...]:
    """把列表归一为搭配元组；非法项跳过，非列表返回空元组。"""

    if not isinstance(value, (list, tuple)):
        return ()
    result: list[Collocation] = []
    for item in value:
        collocation = Collocation.from_dict(item)
        if collocation is not None:
            result.append(collocation)
    return tuple(result)


def _as_examples(value: Any) -> tuple[Example, ...]:
    """把列表归一为例句元组；非法项跳过，非列表返回空元组。"""

    if not isinstance(value, (list, tuple)):
        return ()
    result: list[Example] = []
    for item in value:
        example = Example.from_dict(item)
        if example is not None:
            result.append(example)
    return tuple(result)


@dataclass(frozen=True)
class WordDetail:
    """一个词条的中文五要素详情（只读）。

    Attributes:
        meaning_zh: 中文释义（多义项，去重去空白）。
        pos_zh: 中文词性标签。
        collocations: 常见搭配。
        examples: 典型例句。
        usage_note_zh: 语境 / 语气提示。
    """

    meaning_zh: tuple[str, ...] = ()
    pos_zh: tuple[str, ...] = ()
    collocations: tuple[Collocation, ...] = ()
    examples: tuple[Example, ...] = ()
    usage_note_zh: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典（键名取自 ``core.constants`` 字段常量）。"""

        return {
            C.WORD_DETAIL_FIELD_MEANING: list(self.meaning_zh),
            C.WORD_DETAIL_FIELD_POS: list(self.pos_zh),
            C.WORD_DETAIL_FIELD_COLLOCATIONS: [item.to_dict() for item in self.collocations],
            C.WORD_DETAIL_FIELD_EXAMPLES: [item.to_dict() for item in self.examples],
            C.WORD_DETAIL_FIELD_USAGE: self.usage_note_zh,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "WordDetail | None":
        """逐字段容错构造详情。

        - 非 ``dict`` → ``None``；空 ``dict`` → 全空 :class:`WordDetail`。
        - ``meaning_zh`` 兼容 ``str`` 与 ``str[]``（``str`` → 单元素）。
        - 任何非法字段静默降级为空，绝不抛异常。
        """

        if not isinstance(data, dict):
            return None
        return cls(
            meaning_zh=_as_str_tuple(data.get(C.WORD_DETAIL_FIELD_MEANING)),
            pos_zh=_as_str_tuple(data.get(C.WORD_DETAIL_FIELD_POS)),
            collocations=_as_collocations(data.get(C.WORD_DETAIL_FIELD_COLLOCATIONS)),
            examples=_as_examples(data.get(C.WORD_DETAIL_FIELD_EXAMPLES)),
            usage_note_zh=_as_optional_str(data.get(C.WORD_DETAIL_FIELD_USAGE)),
        )

    def is_empty(self) -> bool:
        """返回五字段是否全部为空（= 本地未命中）。"""

        return not (
            self.meaning_zh
            or self.pos_zh
            or self.collocations
            or self.examples
            or self.usage_note_zh
        )

    def truncated(self, limits: "dict[str, int] | None" = None) -> "WordDetail":
        """按展示上限裁剪释义 / 例句 / 搭配（词性与语气提示不裁剪）。

        Args:
            limits: 字段键名 → 上限条数 的映射；``None`` 时使用 :data:`DEFAULT_LIMITS`。

        Returns:
            裁剪后的新 :class:`WordDetail`（本类不可变）。
        """

        effective = DEFAULT_LIMITS if limits is None else limits
        max_meaning = _positive_limit(
            effective.get(C.WORD_DETAIL_FIELD_MEANING), C.WORD_DETAIL_MAX_MEANINGS
        )
        max_examples = _positive_limit(
            effective.get(C.WORD_DETAIL_FIELD_EXAMPLES), C.WORD_DETAIL_MAX_EXAMPLES
        )
        max_collocations = _positive_limit(
            effective.get(C.WORD_DETAIL_FIELD_COLLOCATIONS), C.WORD_DETAIL_MAX_COLLOCATIONS
        )
        return WordDetail(
            meaning_zh=self.meaning_zh[:max_meaning],
            pos_zh=self.pos_zh,
            collocations=self.collocations[:max_collocations],
            examples=self.examples[:max_examples],
            usage_note_zh=self.usage_note_zh,
        )


__all__ = [
    "Collocation",
    "Example",
    "WordDetail",
    "DEFAULT_LIMITS",
]
