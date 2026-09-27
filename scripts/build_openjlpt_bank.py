#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 OpenJLPT 开源词库转换为 desktop-pet 外置词库格式（jlpt_words_extra.json）。

数据源：evanclan/OpenJLPT（CC BY-SA 4.0，N5~N1 共 8334 词）。
用户从 https://github.com/evanclan/OpenJLPT 的 ``data/json/vocab/`` 目录下载
``n5.json`` ~ ``n1.json``（或整仓 zip 解包后指向 vocab 目录）即可。

转换规则（对齐 src/desktop_pet/core/vocabulary.py 的词条校验）：
- id      = ``ojl-<md5(word + '\\x1f' + reading) 前 10 位>``——内容寻址，数据集
            升级重跑后 id 保持稳定，避免与内置 ``n5-0001`` 式 id 冲突。
- level   = 原样（N5~N1，逐条校验）。
- word    = 原样；kana = ``reading``。
- translation / meaning = 英文释义（过渡方案；中文释义由后续 AI 管线生成后替换）。

用法：
    python build_openjlpt_bank.py <n5.json 所在目录或单个 json 文件...> [-o 输出路径]

产物可直接经托盘「日语学习 → 导入词库…」导入；产物含 ``_attribution`` 元数据，
**再分发时必须保留**（CC BY-SA 4.0 的署名 + 相同方式共享要求）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from desktop_pet.core.constants import JP_LEVELS  # noqa: E402

VALID_LEVELS = set(JP_LEVELS)

ATTRIBUTION = {
    "dataset": "OpenJLPT (https://github.com/evanclan/OpenJLPT)",
    "license": "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)",
    "level_lists": "Jonathan Waller's JLPT Resources (https://www.tanos.co.uk/jlpt/, CC BY)",
    "examples": "Tatoeba (https://tatoeba.org) — CC BY 2.0 FR",
    "notice": "Redistribution requires attribution and share-alike; translations of the "
    "English glosses are derivative data under the same license.",
}


def entry_id(word: str, reading: str) -> str:
    """内容寻址 id：同一词条在数据集版本升级后保持稳定。"""

    digest = hashlib.md5(f"{word}\x1f{reading}".encode("utf-8")).hexdigest()
    return f"ojl-{digest[:10]}"


def convert_file(path: Path, words: list[dict], seen: dict[str, str]) -> tuple[int, int, int]:
    """转换单个 OpenJLPT vocab JSON。返回 (kept, skipped_bad, duplicate)。"""

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("vocab") or data.get("words") or []
    if not isinstance(data, list):
        raise SystemExit(f"[错误] {path}: 期望词条数组，实际为 {type(data).__name__}")

    kept = bad = dup = 0
    for raw in data:
        if not isinstance(raw, dict):
            bad += 1
            continue
        word = str(raw.get("word") or "").strip()
        reading = str(raw.get("reading") or "").strip()
        meanings = [str(m).strip() for m in (raw.get("meanings") or []) if str(m).strip()]
        level = str(raw.get("level") or "").strip().upper()
        if not word or not reading or not meanings or level not in VALID_LEVELS:
            bad += 1
            continue
        wid = entry_id(word, reading)
        if wid in seen:
            dup += 1
            continue
        seen[wid] = word
        translation = meanings[0]
        meaning = "; ".join(meanings)
        words.append(
            {
                "id": wid,
                "level": level,
                "word": word,
                "kana": reading,
                "romaji": "",
                "translation": translation,
                "meaning": meaning,
            }
        )
        kept += 1
    return kept, bad, dup


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenJLPT → desktop-pet 外置词库转换器")
    parser.add_argument(
        "sources",
        nargs="+",
        help="OpenJLPT vocab JSON 文件（n5.json..n1.json）或其所在目录",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(HERE.parent / "jlpt_words_extra.json"),
        help="输出路径（默认仓库根 jlpt_words_extra.json）",
    )
    args = parser.parse_args()

    files: list[Path] = []
    for src in args.sources:
        p = Path(src)
        if p.is_dir():
            found = sorted(p.glob("n*.json")) or sorted(p.glob("*.json"))
            if not found:
                raise SystemExit(f"[错误] 目录中未找到 JSON：{p}")
            files.extend(found)
        elif p.exists():
            files.append(p)
        else:
            raise SystemExit(f"[错误] 路径不存在：{p}")
    if not files:
        raise SystemExit("[错误] 未指定任何输入文件")

    words: list[dict] = []
    seen: dict[str, str] = {}
    total_kept = total_bad = total_dup = 0
    for f in files:
        kept, bad, dup = convert_file(f, words, seen)
        total_kept += kept
        total_bad += bad
        total_dup += dup
        print(f"[转换] {f.name}: 保留 {kept}, 非法 {bad}, 重复 {dup}")

    payload = {
        "version": 1,
        "_attribution": ATTRIBUTION,
        "_note": "英文释义为过渡方案；导入路径：托盘「日语学习 → 导入词库…」",
        "words": words,
    }
    out = Path(args.output)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n[输出] {out}（共 {len(words)} 条）")

    # 产物自检：desktop-pet 的导入解析器必须能完整吃下这份文件
    from desktop_pet.core.vocabulary import parse_bank_file

    entries, skipped = parse_bank_file(out)
    print(
        f"[自检] 通过 parse_bank_file：有效 {len(entries)} 条，跳过 {skipped} 条"
    )
    if len(entries) != len(words) or skipped != 0:
        raise SystemExit("[错误] 自检未通过：产物存在解析器拒绝的词条")


if __name__ == "__main__":
    main()
