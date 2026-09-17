#!/usr/bin/env python3
"""tools/build_word_details.py —— 中文详情分片合并 + 结构校验（**仅构建期运行**）。

分片实际布局（多 worker 并行产出，故为**多文件分片**而非「每级单文件」）::

    _wd_shards/
        out/                       # 优先：word_details_<level>_<nn>.json（等级小写）
            word_details_n5_01.json ... n1_04.json
        word_details_n5_01.json    # 扁平遗留：内容更旧
        ...
        input/                     # 输入词表（含 "words" 无 "details"）——必须跳过

分片文件结构::

    {"level": "N5", "details": {"n5-0001": {五要素}, ...}}

用法（默认读 ``_wd_shards``，写出 ``src/desktop_pet/data/jlpt_word_details.json``）::

    python tools/build_word_details.py
    python tools/build_word_details.py --shards-dir _wd_shards --output out.json

流程（架构 §5.2 T05）：
1. **扫描式收集**：``<shards>/out/*.json``（优先）→ ``<shards>/*.json``（扁平遗留）；
   不进入 ``input/`` 等子目录；对无 ``details`` 的文件防御性跳过。
2. **按 id 去重，``out/`` 优先**（同一 id 两处都有时取 ``out/`` 版本）。
3. 结构校验：id 与 ``jlpt_words.json`` 严格一一对应（无缺 / 无重 / 无多余）、字段类型合规、
   不超过展示上限（释义≤3 / 例句≤3 / 搭配≤5）、内容非空。
4. 稳定排序（按 ``jlpt_words.json`` 词条原序）写出 ``{"version":1,"details":{...}}``。

任何校验失败 → 记录错误并**以非零码退出**（不写出目标文件），便于分片回流补齐。
本脚本**不进入运行时依赖**，仅在内容生成阶段手动执行。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from desktop_pet.core import constants as C  # noqa: E402
from desktop_pet.core.word_detail import WordDetail  # noqa: E402

logger = logging.getLogger("build_word_details")

DEFAULT_SHARDS_DIR = _REPO_ROOT / "_wd_shards"
DEFAULT_WORD_BANK = _SRC_ROOT / "desktop_pet" / "data" / C.WORD_BANK_FILE_NAME
DEFAULT_OUTPUT = _SRC_ROOT / "desktop_pet" / "data" / C.WORD_DETAILS_FILE_NAME

#: 各字段允许的展示上限（与 :data:`core.constants` 一致）
_LIMITS: dict[str, int] = {
    C.WORD_DETAIL_FIELD_MEANING: C.WORD_DETAIL_MAX_MEANINGS,
    C.WORD_DETAIL_FIELD_EXAMPLES: C.WORD_DETAIL_MAX_EXAMPLES,
    C.WORD_DETAIL_FIELD_COLLOCATIONS: C.WORD_DETAIL_MAX_COLLOCATIONS,
}

#: 定向英文残留修复（仅针对已知词条，键为 id；值按顺序依次 ``str.replace``）。
#: 例：``n3-0092`` 的 ``usage_note_zh`` 原句夹杂英文单词 ``workplace`` → 「职场」。
_TEXT_FIXES: dict[str, tuple[tuple[str, str], ...]] = {
    "n3-0092": ((" workplace ", "职场"), ("workplace", "职场")),
}


# --------------------------------------------------------------------------- #
# 读取 / 收集
# --------------------------------------------------------------------------- #
def load_word_bank_ids(word_bank_path: Path) -> list[str]:
    """读取 ``jlpt_words.json`` 的词条 id 列表（保持文件顺序）。"""

    data = json.loads(Path(word_bank_path).read_text(encoding="utf-8"))
    words = data.get("words") if isinstance(data, dict) else None
    if not isinstance(words, list):
        raise ValueError(f"词库 words 字段不是数组：{word_bank_path}")
    ids: list[str] = []
    for item in words:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id.strip():
            ids.append(item_id.strip())
    return ids


def iter_shard_files(shards_dir: Path) -> list[Path]:
    """返回待扫描的分片文件（``out/`` 优先，其次扁平根目录）。

    **只取 ``<shards_dir>/out/*.json`` 与 ``<shards_dir>/*.json`` 两级**，
    不递归进入 ``input/`` 等子目录（输入词表无 ``details``，须跳过）。
    """

    root = Path(shards_dir)
    files: list[Path] = []
    out_dir = root / "out"
    if out_dir.is_dir():
        files.extend(sorted(out_dir.glob("*.json")))
    files.extend(sorted(root.glob("*.json")))
    return files


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def _is_str_list(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value)


def _check_field_types(item_id: str, raw: Any, errors: list[str]) -> bool:
    """校验单条原始数据的字段类型；返回是否类型合规。"""

    if not isinstance(raw, dict):
        errors.append(f"{item_id}: 记录不是对象")
        return False

    ok = True
    meaning = raw.get(C.WORD_DETAIL_FIELD_MEANING)
    if not (isinstance(meaning, str) or _is_str_list(meaning)):
        errors.append(f"{item_id}: meaning_zh 必须是 str 或 str[]")
        ok = False

    pos = raw.get(C.WORD_DETAIL_FIELD_POS)
    if not (isinstance(pos, str) or _is_str_list(pos)):
        errors.append(f"{item_id}: pos_zh 必须是 str 或 str[]")
        ok = False

    usage = raw.get(C.WORD_DETAIL_FIELD_USAGE)
    if not isinstance(usage, str):
        errors.append(f"{item_id}: usage_note_zh 必须是 str")
        ok = False

    collocations = raw.get(C.WORD_DETAIL_FIELD_COLLOCATIONS)
    if not isinstance(collocations, list) or not all(
        isinstance(item, dict) for item in collocations
    ):
        errors.append(f"{item_id}: collocations 必须是 obj[]")
        ok = False
    else:
        for index, item in enumerate(collocations):
            if not isinstance(item.get("phrase"), str) or not item.get("phrase", "").strip():
                errors.append(f"{item_id}: collocations[{index}].phrase 必须是非空 str")
                ok = False
            if "note" in item and not isinstance(item.get("note"), str):
                errors.append(f"{item_id}: collocations[{index}].note 必须是 str")
                ok = False

    examples = raw.get(C.WORD_DETAIL_FIELD_EXAMPLES)
    if not isinstance(examples, list) or not all(isinstance(item, dict) for item in examples):
        errors.append(f"{item_id}: examples 必须是 obj[]")
        ok = False
    else:
        for index, item in enumerate(examples):
            if not isinstance(item.get("jp"), str) or not item.get("jp", "").strip():
                errors.append(f"{item_id}: examples[{index}].jp 必须是非空 str")
                ok = False
            if "zh" in item and not isinstance(item.get("zh"), str):
                errors.append(f"{item_id}: examples[{index}].zh 必须是 str")
                ok = False

    return ok


def _check_limits(item_id: str, detail: WordDetail, errors: list[str]) -> None:
    """校验展示上限（释义 / 例句 / 搭配）。"""

    checks = (
        (C.WORD_DETAIL_FIELD_MEANING, len(detail.meaning_zh)),
        (C.WORD_DETAIL_FIELD_EXAMPLES, len(detail.examples)),
        (C.WORD_DETAIL_FIELD_COLLOCATIONS, len(detail.collocations)),
    )
    for field, count in checks:
        limit = _LIMITS[field]
        if count > limit:
            errors.append(f"{item_id}: {field} 共 {count} 条，超过上限 {limit}")


def _apply_text_fixes(item_id: str, raw: dict[str, Any]) -> None:
    """对已知词条做定向英文残留修复（就地修改 ``usage_note_zh``）。"""

    fixes = _TEXT_FIXES.get(item_id)
    if not fixes:
        return
    text = raw.get(C.WORD_DETAIL_FIELD_USAGE)
    if isinstance(text, str):
        for old, new in fixes:
            text = text.replace(old, new)
        raw[C.WORD_DETAIL_FIELD_USAGE] = text


def validate_and_merge(
    shards_dir: Path, word_bank_path: Path
) -> tuple[dict[str, WordDetail], list[str], dict[str, int]]:
    """扫描并校验全部分片，返回 ``({id: WordDetail}, errors, stats)``。

    ``errors`` 非空即视为构建失败（不写出目标文件）。
    ``stats`` 含：``files``（扫描文件数）、``accepted``（含 details 的分片数）、
    ``skipped``（无 details / 读取失败被跳过的分片数）、``dedup_dropped``（按 id 去重丢弃数）、
    ``entries``（合并后唯一详情条数）。
    """

    errors: list[str] = []
    details: dict[str, WordDetail] = {}
    seen: set[str] = set()
    stats = {"files": 0, "accepted": 0, "skipped": 0, "dedup_dropped": 0, "entries": 0}

    bank_ids = load_word_bank_ids(word_bank_path)
    bank_id_set = set(bank_ids)

    for path in iter_shard_files(shards_dir):
        stats["files"] += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("分片读取失败，已跳过（%s）：%s", path, exc)
            errors.append(f"分片读取失败（{path}）：{exc}")
            stats["skipped"] += 1
            continue
        raw_details = payload.get("details") if isinstance(payload, dict) else None
        if not isinstance(raw_details, dict):
            logger.info("跳过非详情分片（无 details）：%s", path)
            stats["skipped"] += 1
            continue
        stats["accepted"] += 1

        for item_id, raw in raw_details.items():
            if not isinstance(item_id, str) or not item_id.strip():
                errors.append(f"{path.name}: 出现非法 id（{item_id!r}）")
                continue
            item_id = item_id.strip()
            if item_id not in bank_id_set:
                errors.append(f"{item_id}: 不在 jlpt_words.json 中（多余 id）")
                continue
            if item_id in seen:
                stats["dedup_dropped"] += 1
                continue
            if not _check_field_types(item_id, raw, errors):
                continue
            _apply_text_fixes(item_id, raw)
            detail = WordDetail.from_dict(raw)
            if detail is None or detail.is_empty():
                errors.append(f"{item_id}: 五要素全空（内容缺失）")
                continue
            _check_limits(item_id, detail, errors)
            seen.add(item_id)
            details[item_id] = detail

    missing = [item_id for item_id in bank_ids if item_id not in details]
    if missing:
        preview = "、".join(missing[:10])
        errors.append(f"缺少 {len(missing)} 条详情（示例：{preview}）")

    stats["entries"] = len(details)
    return details, errors, stats


# --------------------------------------------------------------------------- #
# 写出
# --------------------------------------------------------------------------- #
def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """原子写 JSON（``mkstemp`` + ``flush/fsync`` + ``os.replace``）。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix="word-details-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass
        raise


def build(shards_dir: Path, word_bank_path: Path, output_path: Path) -> int:
    """执行合并构建；返回进程退出码（0 成功 / 1 校验失败）。"""

    details, errors, stats = validate_and_merge(Path(shards_dir), Path(word_bank_path))
    logger.info(
        "扫描分片：共 %d 个文件（接受 %d / 跳过 %d）",
        stats["files"], stats["accepted"], stats["skipped"],
    )
    logger.info("按 id 去重丢弃 %d 条（out/ 优先）", stats["dedup_dropped"])
    logger.info("合并得到唯一详情 %d 条", stats["entries"])

    if errors:
        for message in errors:
            logger.error("%s", message)
        logger.error("校验失败：共 %d 处问题，未写出目标文件", len(errors))
        return 1

    bank_ids = load_word_bank_ids(word_bank_path)
    ordered = {item_id: details[item_id] for item_id in bank_ids if item_id in details}
    payload = {
        "version": C.WORD_DETAILS_FILE_VERSION,
        "details": {item_id: detail.to_dict() for item_id, detail in ordered.items()},
    }
    _atomic_write_json(Path(output_path), payload)
    logger.info("已写出 %d 条详情 → %s", len(ordered), output_path)
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="合并并校验中文详情分片（仅构建期运行）")
    parser.add_argument(
        "--shards-dir", type=Path, default=DEFAULT_SHARDS_DIR,
        help=f"分片目录（默认 {DEFAULT_SHARDS_DIR}）",
    )
    parser.add_argument(
        "--word-bank", type=Path, default=DEFAULT_WORD_BANK,
        help=f"词库文件（默认 {DEFAULT_WORD_BANK}）",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"输出文件（默认 {DEFAULT_OUTPUT}）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    try:
        return build(args.shards_dir, args.word_bank, args.output)
    except Exception:  # noqa: BLE001 —— CLI 边界
        logger.exception("构建详情库失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
