"""打包中文详情库全量校验（T05）。

- 依赖最终产物 ``src/desktop_pet/data/jlpt_word_details.json``；
  **文件尚未生成时整体 skip**（不报错），待合并构建后自动生效。
- 覆盖：500 条、id 与 ``jlpt_words.json`` 一一对应无缺无重、字段类型合规、
  不超展示上限、内容非空、无英文残留。
- 另含「合并脚本在小样本上正确工作」的隔离单测（不依赖真实产物）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core import paths
from desktop_pet.core.word_detail import WordDetail

_DETAILS_PATH = paths.word_details_path()
_WORD_BANK_PATH = paths.word_bank_path()

#: 中文内容字段中出现 ≥3 个连续 ASCII 字母视为英文残留（忽略大小写；"JLPT" 白名单放行）
_ENGLISH_RESIDUE = re.compile(r"[A-Za-z]{3,}")
_ALLOWED_TOKENS = {"jlpt"}


@pytest.fixture(scope="module")
def details_payload() -> dict:
    if not _DETAILS_PATH.exists():
        pytest.skip(f"详情库尚未生成：{_DETAILS_PATH}（T05 合并尚未执行）")
    data = json.loads(_DETAILS_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def word_bank() -> dict:
    return json.loads(_WORD_BANK_PATH.read_text(encoding="utf-8"))


def _residue(text: str) -> list[str]:
    hits = []
    for token in _ENGLISH_RESIDUE.findall(text):
        if token.lower() not in _ALLOWED_TOKENS:
            hits.append(token)
    return hits


# --------------------------------------------------------------------------- #
# 1. 结构 / 规模
# --------------------------------------------------------------------------- #
def test_details_root_structure(details_payload: dict) -> None:
    assert details_payload.get("version") == C.WORD_DETAILS_FILE_VERSION
    assert isinstance(details_payload.get("details"), dict)


def test_details_count_matches_word_bank(details_payload: dict, word_bank: dict) -> None:
    details = details_payload["details"]
    assert len(word_bank["words"]) == 500
    assert len(details) == 500
    assert len(details) == len(word_bank["words"])


def test_ids_match_word_bank_exactly(details_payload: dict, word_bank: dict) -> None:
    detail_ids = set(details_payload["details"])
    bank_ids = [item["id"] for item in word_bank["words"]]
    assert len(bank_ids) == len(set(bank_ids)), "jlpt_words.json 自身存在重复 id"
    assert detail_ids == set(bank_ids), "详情库 id 与词库不一致（缺 / 多 / 重）"


# --------------------------------------------------------------------------- #
# 2. 字段类型 / 上限 / 非空 / 无英文残留
# --------------------------------------------------------------------------- #
def test_each_detail_parses_and_non_empty(details_payload: dict) -> None:
    for item_id, raw in details_payload["details"].items():
        detail = WordDetail.from_dict(raw)
        assert detail is not None, f"{item_id}: 无法解析为 WordDetail"
        assert not detail.is_empty(), f"{item_id}: 五要素全空"


def test_field_types_compliant(details_payload: dict) -> None:
    for item_id, raw in details_payload["details"].items():
        assert isinstance(raw, dict), item_id
        assert isinstance(raw.get(C.WORD_DETAIL_FIELD_MEANING), list), item_id
        assert isinstance(raw.get(C.WORD_DETAIL_FIELD_POS), list), item_id
        assert isinstance(raw.get(C.WORD_DETAIL_FIELD_COLLOCATIONS), list), item_id
        assert isinstance(raw.get(C.WORD_DETAIL_FIELD_EXAMPLES), list), item_id
        assert isinstance(raw.get(C.WORD_DETAIL_FIELD_USAGE), str), item_id
        for collocation in raw[C.WORD_DETAIL_FIELD_COLLOCATIONS]:
            assert isinstance(collocation, dict) and isinstance(collocation.get("phrase"), str)
        for example in raw[C.WORD_DETAIL_FIELD_EXAMPLES]:
            assert isinstance(example, dict) and isinstance(example.get("jp"), str)


def test_display_limits_not_exceeded(details_payload: dict) -> None:
    for item_id, raw in details_payload["details"].items():
        detail = WordDetail.from_dict(raw)
        assert detail is not None
        assert len(detail.meaning_zh) <= C.WORD_DETAIL_MAX_MEANINGS, item_id
        assert len(detail.examples) <= C.WORD_DETAIL_MAX_EXAMPLES, item_id
        assert len(detail.collocations) <= C.WORD_DETAIL_MAX_COLLOCATIONS, item_id


def test_no_english_residue_in_chinese_fields(details_payload: dict) -> None:
    offenders: list[str] = []
    for item_id, raw in details_payload["details"].items():
        detail = WordDetail.from_dict(raw)
        assert detail is not None
        texts = (
            list(detail.meaning_zh)
            + list(detail.pos_zh)
            + [detail.usage_note_zh]
            + [item.note for item in detail.collocations]
            + [item.zh for item in detail.examples]
        )
        for text in texts:
            hits = _residue(text)
            if hits:
                offenders.append(f"{item_id}: {text!r} → {hits}")
    assert not offenders, f"发现英文残留：{offenders[:10]}"


# --------------------------------------------------------------------------- #
# 3. 合并脚本隔离单测（小样本，不依赖真实产物）
# --------------------------------------------------------------------------- #
def _load_builder(project_root: Path):
    path = project_root / "tools" / "build_word_details.py"
    spec = importlib.util.spec_from_file_location("build_word_details_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bank_payload(entries: list[tuple[str, str]]) -> dict:
    return {
        "version": 1,
        "words": [
            {"id": item_id, "level": level, "word": "語", "kana": "かな",
             "translation": "译", "meaning": "义"}
            for item_id, level in entries
        ],
    }


def _detail_raw(meaning: str) -> dict:
    return {
        C.WORD_DETAIL_FIELD_MEANING: [meaning],
        C.WORD_DETAIL_FIELD_POS: ["名词"],
        C.WORD_DETAIL_FIELD_COLLOCATIONS: [{"phrase": "フレーズ", "note": "用法"}],
        C.WORD_DETAIL_FIELD_EXAMPLES: [{"jp": "例文。", "zh": "例句。"}],
        C.WORD_DETAIL_FIELD_USAGE: "通用。",
    }


def test_build_script_merges_and_orders(project_root: Path, tmp_path: Path) -> None:
    builder = _load_builder(project_root)

    entries = [(f"{level.lower()}-0001", level) for level in C.JP_LEVELS]
    bank = tmp_path / "jlpt_words.json"
    bank.write_text(json.dumps(_bank_payload(entries), ensure_ascii=False), encoding="utf-8")

    shards = tmp_path / "shards"
    shards.mkdir()
    for level in C.JP_LEVELS:
        item_id = f"{level.lower()}-0001"
        shard = {"level": level, "details": {item_id: _detail_raw(f"义-{level}")}}
        (shards / f"word_details_{level.lower()}_01.json").write_text(
            json.dumps(shard, ensure_ascii=False), encoding="utf-8"
        )

    output = tmp_path / "out.json"
    code = builder.build(shards, bank, output)

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["version"] == C.WORD_DETAILS_FILE_VERSION
    assert list(payload["details"]) == [item_id for item_id, _ in entries]  # 稳定排序


def test_build_script_out_priority_and_dedup(project_root: Path, tmp_path: Path) -> None:
    """out/ 优先：同 id 与扁平目录重复时取 out/ 版本；无 details 的文件跳过。"""

    builder = _load_builder(project_root)
    entries = [(f"{level.lower()}-0001", level) for level in C.JP_LEVELS]
    bank = tmp_path / "jlpt_words.json"
    bank.write_text(json.dumps(_bank_payload(entries), ensure_ascii=False), encoding="utf-8")

    shards = tmp_path / "shards"
    (shards / "out").mkdir(parents=True)
    for level in C.JP_LEVELS:
        item_id = f"{level.lower()}-0001"
        (shards / "out" / f"word_details_{level.lower()}_01.json").write_text(
            json.dumps({"level": level, "details": {item_id: _detail_raw(f"out-{level}")}},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    # 扁平遗留：与 out/ 同 id（更旧）
    (shards / "word_details_n5_01.json").write_text(
        json.dumps({"level": "N5", "details": {"n5-0001": _detail_raw("flat")}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    # 无 details 的噪声文件 → 防御性跳过
    (shards / "_meta.json").write_text(json.dumps({"note": "x"}), encoding="utf-8")

    details, errors, stats = builder.validate_and_merge(shards, bank)

    assert errors == []
    assert stats["dedup_dropped"] == 1
    assert stats["skipped"] == 1
    assert details["n5-0001"].meaning_zh == ("out-N5",)  # out/ 版本胜出


def test_build_script_reports_missing(project_root: Path, tmp_path: Path) -> None:
    builder = _load_builder(project_root)
    entries = [(f"{level.lower()}-0001", level) for level in C.JP_LEVELS]
    bank = tmp_path / "jlpt_words.json"
    bank.write_text(json.dumps(_bank_payload(entries), ensure_ascii=False), encoding="utf-8")
    shards = tmp_path / "shards"
    shards.mkdir()  # 缺全部分片

    code = builder.build(shards, bank, tmp_path / "out.json")

    assert code == 1
    assert not (tmp_path / "out.json").exists()


def test_build_script_reports_over_limit(project_root: Path, tmp_path: Path) -> None:
    builder = _load_builder(project_root)
    entries = [(f"{level.lower()}-0001", level) for level in C.JP_LEVELS]
    bank = tmp_path / "jlpt_words.json"
    bank.write_text(json.dumps(_bank_payload(entries), ensure_ascii=False), encoding="utf-8")

    shards = tmp_path / "shards"
    shards.mkdir()
    for level in C.JP_LEVELS:
        item_id = f"{level.lower()}-0001"
        raw = _detail_raw(f"义-{level}")
        raw[C.WORD_DETAIL_FIELD_MEANING] = ["一", "二", "三", "四"]  # 超上限（>3）
        (shards / f"word_details_{level.lower()}_01.json").write_text(
            json.dumps({"level": level, "details": {item_id: raw}}, ensure_ascii=False),
            encoding="utf-8",
        )

    code = builder.build(shards, bank, tmp_path / "out.json")

    assert code == 1
    assert not (tmp_path / "out.json").exists()
