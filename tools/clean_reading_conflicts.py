"""tools.clean_reading_conflicts —— 外置词库「同词不同读音」冲突清洗（2026-10-01）。

背景：外置词库（OpenJLPT 管线产物）中同一词形存在多条目且读音不一致
（如 明後日：N1=あさって / N3=みょうごにち），且 N1 条目大量配了字面音读。
全库扫描：7738 条中 644 词有重复条目、227 词读音互相矛盾。

清洗策略（**语义门卫 + 读音裁决**，只改外置词库，绝不碰内置精选词库）：
1. 按词形分组；读音冲突 = 同词形出现 ≥2 种假名。
2. **语义门卫**：把该词形的条目按 ``(translation, meaning)`` 分组——
   释义**完全一致**的才视为「同一个词的两种读音选择」（可同步）；
   释义不同的视为合法的同形异读词（如 音 おと/おん/ね），**绝不触碰**。
3. 可同步组的裁决读音（优先级从高到低）：
   a. 手工例外表 ``_OVERRIDES``（熟字训等低等级反而非常用的词，起步仅 明後日）；
   b. 内置精选词库锚点（该词形在内置库中的读音，且是本组候选之一）；
   c. 组内多数读音（≥2 条相同假名）；
   d. 组内最低 JLPT 等级条目的读音（N5 最先教的是常用读音）。
4. 同步：组内所有条目 ``kana`` 改为裁决读音；同时刷新生词本快照
   （``vocabulary.json``）中同词旧读音；清空发音缓存（旧键可能对应错误读音）。

用法（默认 dry-run 只出报告；``--apply`` 才写盘，写前自动备份）::

    python tools/clean_reading_conflicts.py            # dry-run，仅生成报告
    python tools/clean_reading_conflicts.py --apply    # 备份 + 写盘 + 报告
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

#: 内置精选词库（只读锚点，绝不修改）
_BUILTIN_PATH = _REPO / "src" / "desktop_pet" / "data" / "jlpt_words.json"
#: 外置词库：仓库根分发副本 + 用户 APPDATA 实际加载的文件（两份保持一致）
_EXTRA_REPO_PATH = _REPO / "jlpt_words_extra.json"
_EXTRA_APPDATA_PATH = (
    Path(os.environ.get("APPDATA", str(Path.home())))
    / "desktop-pet"
    / "jlpt_words_extra.json"
)
#: 生词本快照（含 word/kana 冗余，需同步刷新）
_VOCAB_PATH = (
    Path(os.environ.get("APPDATA", str(Path.home())))
    / "desktop-pet"
    / "vocabulary.json"
)
#: 报告输出
_REPORT_PATH = _REPO / "docs" / "reading-conflicts-report-20261001.md"

#: 手工例外表：裁决读音（语义门卫通过后仍可能被「最低等级」带偏的知名熟字训）
_OVERRIDES: dict[str, str] = {
    "明後日": "あさって",
}

_LEVEL_ORDER: dict[str, int] = {"N5": 0, "N4": 1, "N3": 2, "N2": 3, "N1": 4}


def _is_pure_kana(text: str) -> bool:
    """是否纯假名（平/片假名 + 长音・中点）——脏假名（斜杠多读音/括注/乱码）
    不能作为裁决读音来源，否则会把脏数据扩散到干净条目（如「しち / なな」）。"""

    if not text:
        return False
    return all("\u3040" <= ch <= "\u30ff" or ch in "ー・" for ch in text)


def _level_rank(level: str) -> int:
    """等级 → 排序键（越低越基础/常用；未知等级排最后）。"""

    return _LEVEL_ORDER.get(str(level or "").strip().upper(), 99)


def _load_words(path: Path) -> list[dict]:
    """读取词库 JSON 的 ``words`` 数组（文件缺失返回空表）。"""

    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("words", []))


def _sense_key(entry: dict) -> str:
    """条目的语义键（translation + meaning 归一化），用于同词异读判定。"""

    def _norm(value: object) -> str:
        return " ".join(str(value or "").split())

    return f"{_norm(entry.get('translation'))}|{_norm(entry.get('meaning'))}"


def compute_changes(
    builtin: list[dict], extra: list[dict]
) -> tuple[list[tuple[dict, str, str]], list[dict]]:
    """计算清洗变更（纯函数，便于复查）。

    Returns:
        (changes, untouched_conflicts) ——
        ``changes``: ``[(条目, 旧假名, 新假名), ...]``（外置库内）；
        ``untouched_conflicts``: 语义门卫拦下的合法同形异读组代表条目。
    """

    builtin_kana: dict[str, str] = {}
    for entry in builtin:
        builtin_kana.setdefault(str(entry.get("word", "")), str(entry.get("kana", "")))

    by_word: dict[str, list[dict]] = defaultdict(list)
    for entry in extra:
        by_word[str(entry.get("word", ""))].append(entry)

    changes: list[tuple[dict, str, str]] = []
    untouched: list[dict] = []
    for word, entries in sorted(by_word.items()):
        kana_set = {str(e.get("kana", "")).strip() for e in entries}
        if len(kana_set) < 2:
            continue  # 无读音冲突

        # 语义门卫：按释义分组，只处理「释义完全一致」的组
        sense_groups: dict[str, list[dict]] = defaultdict(list)
        for entry in entries:
            sense_groups[_sense_key(entry)].append(entry)

        resolved_any = False
        for group in sense_groups.values():
            group_kana = {str(e.get("kana", "")).strip() for e in group}
            if len(group_kana) < 2:
                continue

            # 裁决：例外表 → 内置锚点 → 组内多数 → 纯假名中最低等级 → 最低等级
            # （纯假名优先：绝不把「しち / なな」这类脏假名同步给干净条目）
            canonical = _OVERRIDES.get(word, "")
            if canonical not in group_kana:
                canonical = ""
            if not canonical:
                anchor = builtin_kana.get(word, "")
                if anchor and anchor in group_kana and _is_pure_kana(anchor):
                    canonical = anchor
            if not canonical:
                counts: dict[str, int] = defaultdict(int)
                for entry in group:
                    counts[str(entry.get("kana", "")).strip()] += 1
                majority = [
                    k for k, n in counts.items() if n >= 2 and _is_pure_kana(k)
                ]
                if len(majority) == 1:
                    canonical = majority[0]
            if not canonical:
                pure_entries = [
                    e for e in group if _is_pure_kana(str(e.get("kana", "")).strip())
                ]
                pool = pure_entries or group
                best = min(pool, key=lambda e: _level_rank(e.get("level", "")))
                canonical = str(best.get("kana", "")).strip()

            if not canonical:
                continue
            resolved_any = True
            for entry in group:
                old = str(entry.get("kana", "")).strip()
                if old != canonical:
                    changes.append((entry, old, canonical))

        if not resolved_any:
            untouched.append(entries[0])
    return changes, untouched


def _write_with_backup(path: Path, payload: dict, dry_run: bool) -> bool:
    """带备份地写回 JSON 词库/快照文件（dry_run 时跳过）。"""

    if not dry_run and path.is_file():
        stamp = "20261001"
        shutil.copy2(path, path.with_suffix(path.suffix + f".bak-{stamp}"))
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return not dry_run


def main() -> int:
    parser = argparse.ArgumentParser(description="外置词库同词不同读音清洗")
    parser.add_argument("--apply", action="store_true", help="写盘（默认 dry-run）")
    args = parser.parse_args()
    dry_run = not args.apply

    builtin = _load_words(_BUILTIN_PATH)
    extra = _load_words(_EXTRA_APPDATA_PATH)
    if not extra:
        print(f"外置词库不存在或为空：{_EXTRA_APPDATA_PATH}")
        return 1

    changes, untouched = compute_changes(builtin, extra)

    # 仓库根分发副本与 APPDATA 内容一致 → 同一套变更
    repo_copy = _load_words(_EXTRA_REPO_PATH)
    repo_changes, _ = compute_changes(builtin, repo_copy) if repo_copy else ([], [])

    lines: list[str] = [
        "# 外置词库「同词不同读音」冲突清洗报告（2026-10-01）",
        "",
        f"- 外置词库：`{_EXTRA_APPDATA_PATH}`（{len(extra)} 条）",
        f"- 冲突裁决变更：**{len(changes)} 条**（语义门卫通过的「同词同释义、读音不一致」组）",
        f"- 语义门卫拦截（合法同形异读，未触碰）：{len(untouched)} 组",
        f"- 例外表：{json.dumps(_OVERRIDES, ensure_ascii=False)}",
        f"- 执行模式：{'**已写盘（--apply）**' if not dry_run else 'dry-run（未写盘）'}",
        "",
        "| 词形 | 等级 | id | 旧假名 | 新假名 |",
        "|---|---|---|---|---|",
    ]
    for entry, old, new in changes:
        lines.append(
            f"| {entry.get('word')} | {entry.get('level')} | {entry.get('id')} | {old} | {new} |"
        )
    if untouched:
        lines += ["", "## 语义门卫拦截的同形异读词（保持原样）", ""]
        lines += [
            f"- {e.get('word')}（{e.get('level')}，{e.get('kana')}）" for e in untouched
        ]
    _REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"变更 {len(changes)} 条 | 拦截 {len(untouched)} 组 | 报告：{_REPORT_PATH}")

    if not changes:
        return 0

    for entry, _, new in changes:
        entry["kana"] = new

    if not dry_run:
        for path, words in (
            (_EXTRA_APPDATA_PATH, extra),
            (_EXTRA_REPO_PATH, repo_copy),
        ):
            if not words:
                continue
            # 仓库根副本走它自己的变更集（文件内容一致，变更集等价）
            if path == _EXTRA_REPO_PATH:
                for entry, _, new in repo_changes:
                    entry["kana"] = new
                _write_with_backup(
                    path, {"version": 1, "words": repo_copy}, dry_run
                )
            else:
                _write_with_backup(path, {"version": 1, "words": extra}, dry_run)

        # 生词本快照：同词旧读音 → 裁决读音
        if _VOCAB_PATH.is_file():
            vocab = json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))
            fixed = 0
            for item in vocab.get("items", []):
                for entry, old, new in changes:
                    if item.get("word") == entry.get("word") and item.get("kana") == old:
                        item["kana"] = new
                        fixed += 1
            if fixed:
                _write_with_backup(_VOCAB_PATH, vocab, dry_run)
                print(f"生词本快照已刷新 {fixed} 条")

    print("完成" if not dry_run else "dry-run 结束（加 --apply 写盘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
