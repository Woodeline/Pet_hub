"""工程师自测：记忆曲线（间隔重复）—— MasteredStore v2 SRS 状态与调度 API。

覆盖：
1. v2 字段落盘回读：``add(stage=, due_at=)`` → JSON 往返保真（stage / due_at /
   last_review_at / review_count）。
2. v1 向后兼容：无 SRS 字段的旧文件逐字段容错读入（stage=0 / due_at=""），
   非法值（越界 stage / 负数 count / bool 伪装 int）回落缺省。
3. 到期查询：``due_items`` 只含未毕业且 ``due_at <= now`` 的记录、按字典序升序
   （定长 UTC ISO 字符串字典序即时间序）；毕业记录（stage=len）永不出现。
4. ``earliest_due_iso``：全部排期中的最小 ``due_at``（含未来）；空集合 / 全毕业 → ""。
5. ``apply_review``：stage / due_at / last_review_at 写入且 ``review_count`` +1；
   毕业形态（due_at=""）落盘后 ``due_items`` / ``earliest_due_iso`` 均不再命中。
6. ``set_due_at``：仅改到期时刻（超时顺延 / 迁移补排期），阶段与计数原样保留。

遵循项目测试隔离约定：数据落 tmp_path，core 层零时钟（ISO 字符串由测试注入）。
"""

from __future__ import annotations

import json
from pathlib import Path

from desktop_pet.core import constants as C
from desktop_pet.core.mastered_store import MasteredItem, MasteredStore
from desktop_pet.core.vocabulary import VocabEntry

_ISO_T0 = "2025-01-01T00:00:00Z"
_ISO_T1 = "2025-01-02T00:00:00Z"


def _entry(i: int, level: str = "N5") -> VocabEntry:
    """构造第 ``i`` 个测试词条（id 形如 ``n5-0001``）。"""

    return VocabEntry(
        id=f"{level.lower()}-{i:04d}",
        level=level,
        word=f"語{i}",
        kana="かな",
        translation="译",
        meaning="义",
    )


def _store(tmp_path: Path, name: str = "mastered.json") -> MasteredStore:
    store = MasteredStore(tmp_path / name)
    store.load()
    return store


# --------------------------------------------------------------------------- #
# 1. v2 字段落盘回读
# --------------------------------------------------------------------------- #
def test_add_with_srs_fields_roundtrip(tmp_path: Path) -> None:
    """add 携带 stage/due_at → 内存与重新加载后的记录字段保真。"""

    store = _store(tmp_path)
    assert store.add(_entry(1), _ISO_T0, stage=2, due_at=_ISO_T1) is True

    item = store.get("n5-0001")
    assert item is not None
    assert item.stage == 2
    assert item.due_at == _ISO_T1
    assert item.last_review_at == _ISO_T0  # 掌握瞬间 = 初次 last_review_at
    assert item.review_count == 0

    reloaded = _store(tmp_path)
    again = reloaded.get("n5-0001")
    assert again == item  # JSON 往返保真（frozen dataclass 全字段相等）


def test_add_default_and_duplicate(tmp_path: Path) -> None:
    """缺省 SRS 初态：stage=0 / due_at=""；按 id 去重（重复 add 返回 False）。"""

    store = _store(tmp_path)
    assert store.add(_entry(1), _ISO_T0) is True
    assert store.add(_entry(1), _ISO_T1, stage=3, due_at=_ISO_T1) is False

    item = store.get("n5-0001")
    assert item is not None
    assert item.stage == 0
    assert item.due_at == ""


# --------------------------------------------------------------------------- #
# 2. v1 向后兼容 + 容错缺省
# --------------------------------------------------------------------------- #
def test_load_v1_file_without_srs_fields(tmp_path: Path) -> None:
    """v1 文件（无 SRS 字段）读入：stage=0 / due_at="" / count=0，必填字段不受影响。"""

    path = tmp_path / "mastered.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {
                        "id": "n5-0001",
                        "level": "N5",
                        "word": "語1",
                        "kana": "かな",
                        "translation": "译",
                        "mastered_at": _ISO_T0,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = MasteredStore(path)
    store.load()

    item = store.get("n5-0001")
    assert item is not None
    assert item.mastered_at == _ISO_T0
    assert item.stage == 0
    assert item.due_at == ""
    assert item.last_review_at == ""
    assert item.review_count == 0


def test_from_dict_tolerates_bad_srs_values() -> None:
    """SRS 字段非法值逐项回落缺省（绝不因脏数据丢整条记录）。"""

    total = len(C.REVIEW_INTERVALS_DAYS)
    item = MasteredItem.from_dict(
        {
            "id": "n5-0001",
            "level": "N5",
            "word": "語1",
            "kana": "かな",
            "translation": "译",
            "mastered_at": _ISO_T0,
            "stage": total + 5,       # 越界 → 0
            "due_at": 123,            # 非字符串 → ""
            "last_review_at": "   ",  # 空白 → ""
            "review_count": -3,       # 负数 → 0
        }
    )
    assert item is not None
    assert item.stage == 0
    assert item.due_at == ""
    assert item.last_review_at == ""
    assert item.review_count == 0

    # stage 上界（毕业态）合法；bool 伪装 int 被拒
    assert MasteredItem.from_dict(
        {
            "id": "n5-0001",
            "level": "N5",
            "word": "語1",
            "kana": "かな",
            "translation": "译",
            "mastered_at": _ISO_T0,
            "stage": total,
            "review_count": True,  # bool → 非法 → 0
        }
    ).stage == total


# --------------------------------------------------------------------------- #
# 3/4. 到期查询与最早排期
# --------------------------------------------------------------------------- #
def test_due_items_sorted_and_excludes_future_and_graduated(tmp_path: Path) -> None:
    """due_items：仅未毕业且到期；按 due_at 升序；毕业记录永不命中。"""

    store = _store(tmp_path)
    # 到期时间乱序插入，验证排序（字典序 = 时间序）
    store.add(_entry(1), _ISO_T0, stage=0, due_at="2025-01-05T00:00:00Z")
    store.add(_entry(2), _ISO_T0, stage=1, due_at="2025-01-03T00:00:00Z")
    store.add(_entry(3), _ISO_T0, stage=2, due_at="2025-06-01T00:00:00Z")   # 未来
    store.add(_entry(4), _ISO_T0, stage=len(C.REVIEW_INTERVALS_DAYS), due_at="")  # 毕业
    store.add(_entry(5), _ISO_T0, stage=0, due_at="")                        # 未排期

    due = store.due_items("2025-01-10T00:00:00Z")
    assert [item.id for item in due] == ["n5-0002", "n5-0001"]

    # 严格早于（边界：due_at == now 算到期）
    boundary = store.due_items("2025-01-03T00:00:00Z")
    assert [item.id for item in boundary] == ["n5-0002"]


def test_earliest_due_iso(tmp_path: Path) -> None:
    """earliest_due_iso：全排期的最小 due_at（含未来）；空 / 全毕业 → ""。"""

    store = _store(tmp_path)
    assert store.earliest_due_iso() == ""

    store.add(_entry(1), _ISO_T0, stage=0, due_at="2025-03-01T00:00:00Z")
    store.add(_entry(2), _ISO_T0, stage=0, due_at="2025-02-01T00:00:00Z")
    assert store.earliest_due_iso() == "2025-02-01T00:00:00Z"

    store.add(_entry(3), _ISO_T0, stage=len(C.REVIEW_INTERVALS_DAYS), due_at="2024-01-01T00:00:00Z")
    assert store.earliest_due_iso() == "2025-02-01T00:00:00Z"  # 毕业记录不参与


# --------------------------------------------------------------------------- #
# 5. apply_review：推进 / 毕业
# --------------------------------------------------------------------------- #
def test_apply_review_advances_stage_and_counts(tmp_path: Path) -> None:
    """复习通过：stage / due_at / last_review_at 更新且 review_count +1。"""

    store = _store(tmp_path)
    store.add(_entry(1), _ISO_T0, stage=0, due_at="2025-01-01T12:00:00Z")

    assert (
        store.apply_review(
            "n5-0001", stage=1, due_at="2025-01-04T12:00:00Z", reviewed_at=_ISO_T1
        )
        is True
    )
    item = store.get("n5-0001")
    assert item is not None
    assert item.stage == 1
    assert item.due_at == "2025-01-04T12:00:00Z"
    assert item.last_review_at == _ISO_T1
    assert item.review_count == 1
    assert store.apply_review("n5-missing", stage=1, due_at="", reviewed_at=_ISO_T1) is False


def test_apply_review_graduation_removes_from_scheduling(tmp_path: Path) -> None:
    """毕业（stage=len / due_at=""）落盘后不再被 due_items / earliest_due_iso 命中。"""

    store = _store(tmp_path)
    store.add(_entry(1), _ISO_T0, stage=len(C.REVIEW_INTERVALS_DAYS) - 1, due_at="2025-01-01T00:00:00Z")

    assert store.due_items(_ISO_T1) == [store.get("n5-0001")]
    assert (
        store.apply_review(
            "n5-0001",
            stage=len(C.REVIEW_INTERVALS_DAYS),
            due_at="",
            reviewed_at=_ISO_T1,
        )
        is True
    )
    assert store.due_items("2030-01-01T00:00:00Z") == []
    assert store.earliest_due_iso() == ""
    item = store.get("n5-0001")
    assert item is not None
    assert item.stage == len(C.REVIEW_INTERVALS_DAYS)
    assert item.review_count == 1


# --------------------------------------------------------------------------- #
# 6. set_due_at：仅顺延，不推进阶段 / 不计数
# --------------------------------------------------------------------------- #
def test_set_due_at_only_changes_due(tmp_path: Path) -> None:
    """超时顺延 / 迁移补排期：只有 due_at 变化，stage / last_review_at / count 保留。"""

    store = _store(tmp_path)
    store.add(_entry(1), _ISO_T0, stage=2, due_at="")
    assert store.set_due_at("n5-0001", "2025-01-02T01:00:00Z") is True

    item = store.get("n5-0001")
    assert item is not None
    assert item.due_at == "2025-01-02T01:00:00Z"
    assert item.stage == 2
    assert item.last_review_at == _ISO_T0
    assert item.review_count == 0
    assert store.set_due_at("n5-missing", _ISO_T1) is False
