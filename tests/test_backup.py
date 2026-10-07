"""工程师自测：core.backup —— 一键备份与还原（zip 打包 / 白名单 / 原子还原）。

覆盖：
1. 打包：manifest 字段、只收录存在的白名单文件、缺失源跳过、白名单外键忽略。
2. 还原：内容一致、既有文件留档（.pre-restore）、manifest 声明但缺失的文件跳过。
3. 拒绝：非 zip、缺 manifest、版本不符、路径穿越条目、白名单外条目。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.backup import BackupError, create_backup, read_manifest, restore_backup


def _sources(tmp_path: Path) -> dict[str, Path]:
    """构造两个真实源文件（config / vocab）+ 一个缺失源（mastered）。"""

    config = tmp_path / "config.json"
    vocab = tmp_path / "vocabulary.json"
    config.write_text('{"window_x": 7}', encoding="utf-8")
    vocab.write_text('{"version": 1, "items": []}', encoding="utf-8")
    return {
        C.CONFIG_FILE_NAME: config,
        C.VOCAB_FILE_NAME: vocab,
        C.MASTERED_FILE_NAME: tmp_path / "mastered.json",  # 不存在 → 打包时跳过
    }


# --------------------------------------------------------------------------- #
# 打包
# --------------------------------------------------------------------------- #
def test_create_backup_writes_manifest_and_files(tmp_path: Path) -> None:
    """打包：manifest 记录版本 / 应用版本 / 创建时间 / 实际收录清单。"""

    out = tmp_path / "out" / "backup.zip"
    create_backup(_sources(tmp_path), out, app_version="0.6.2", created_at="2025-01-01T00:00:00Z")

    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
    assert names == {"manifest.json", C.CONFIG_FILE_NAME, C.VOCAB_FILE_NAME}

    manifest = read_manifest(out)
    assert manifest["version"] == C.BACKUP_MANIFEST_VERSION
    assert manifest["app_version"] == "0.6.2"
    assert manifest["created_at"] == "2025-01-01T00:00:00Z"
    assert set(manifest["files"]) == {C.CONFIG_FILE_NAME, C.VOCAB_FILE_NAME}


def test_create_backup_skips_nonexistent_sources(tmp_path: Path) -> None:
    """全部源缺失：仍生成含空 files 清单的合法备份。"""

    out = tmp_path / "empty.zip"
    create_backup({C.CONFIG_FILE_NAME: tmp_path / "nope.json"}, out, app_version="x", created_at="")
    assert read_manifest(out)["files"] == []


def test_create_backup_rejects_keys_outside_whitelist(tmp_path: Path) -> None:
    """白名单之外的键：快速失败（调用方 bug 早暴露），绝不打包未知/敏感文件。"""

    src = tmp_path / "secret.txt"
    src.write_text("secret", encoding="utf-8")
    out = tmp_path / "w.zip"
    with pytest.raises(BackupError):
        create_backup({"secret.txt": src}, out, app_version="x", created_at="")


def test_backup_roundtrip_bank_files(tmp_path: Path) -> None:
    """多词库条目（``banks/<id>.json``）：打包与还原写回子目录。"""

    registry = tmp_path / "bank_registry.json"
    registry.write_text('{"version": 1, "banks": []}', encoding="utf-8")
    bank_file = tmp_path / "banks" / "bk-abc.json"
    bank_file.parent.mkdir()
    bank_file.write_text('{"version": 1, "words": []}', encoding="utf-8")

    out = tmp_path / "b.zip"
    create_backup(
        {
            C.BANK_REGISTRY_FILENAME: registry,
            f"{C.BANKS_DIR_NAME}/bk-abc.json": bank_file,
        },
        out,
        app_version="v",
        created_at="",
    )
    manifest = read_manifest(out)
    assert manifest["files"] == sorted([C.BANK_REGISTRY_FILENAME, f"{C.BANKS_DIR_NAME}/bk-abc.json"])

    dest = tmp_path / "dest"
    restore_backup(out, dest)
    assert (dest / C.BANK_REGISTRY_FILENAME).is_file()
    assert (dest / C.BANKS_DIR_NAME / "bk-abc.json").read_text(encoding="utf-8") == '{"version": 1, "words": []}'


def test_backup_rejects_bank_path_escape(tmp_path: Path) -> None:
    """banks 条目带二级路径 / 穿越：拒绝。"""

    out = tmp_path / "evil.zip"
    with zipfile.ZipFile(out, "w") as archive:
        manifest = {
            "version": C.BACKUP_MANIFEST_VERSION,
            "app_version": "v",
            "created_at": "",
            "files": [f"{C.BANKS_DIR_NAME}/../evil.json"],
        }
        archive.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(BackupError):
        restore_backup(out, tmp_path / "dest")


# --------------------------------------------------------------------------- #
# 还原
# --------------------------------------------------------------------------- #
def test_restore_roundtrip_and_preserve_existing(tmp_path: Path) -> None:
    """还原内容一致；目标目录既有文件留档为 .pre-restore。"""

    out = tmp_path / "backup.zip"
    create_backup(_sources(tmp_path), out, app_version="v", created_at="")

    dest = tmp_path / "dest"
    dest.mkdir()
    existing = dest / C.CONFIG_FILE_NAME
    existing.write_text("old-content", encoding="utf-8")

    restored = restore_backup(out, dest)
    assert set(restored) == {C.CONFIG_FILE_NAME, C.VOCAB_FILE_NAME}
    assert (dest / C.CONFIG_FILE_NAME).read_text(encoding="utf-8") == '{"window_x": 7}'
    assert (dest / C.VOCAB_FILE_NAME).read_text(encoding="utf-8") == '{"version": 1, "items": []}'
    preserved = [p for p in dest.iterdir() if p.name.startswith(C.CONFIG_FILE_NAME + C.BACKUP_PRE_RESTORE_SUFFIX)]
    assert len(preserved) == 1
    assert preserved[0].read_text(encoding="utf-8") == "old-content"


def test_restore_preserves_older_archives(tmp_path: Path) -> None:
    """既有留档已存在：递增序号，绝不覆盖旧留档。"""

    out = tmp_path / "b.zip"
    create_backup(_sources(tmp_path), out, app_version="v", created_at="")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / C.CONFIG_FILE_NAME).write_text("first", encoding="utf-8")
    (dest / (C.CONFIG_FILE_NAME + C.BACKUP_PRE_RESTORE_SUFFIX)).write_text("older", encoding="utf-8")

    restore_backup(out, dest)
    names = {p.name for p in dest.iterdir()}
    assert C.CONFIG_FILE_NAME + C.BACKUP_PRE_RESTORE_SUFFIX in names
    assert C.CONFIG_FILE_NAME + C.BACKUP_PRE_RESTORE_SUFFIX + "-1" in names
    assert (dest / (C.CONFIG_FILE_NAME + C.BACKUP_PRE_RESTORE_SUFFIX)).read_text(encoding="utf-8") == "older"


def test_restore_skips_missing_declared_file(tmp_path: Path) -> None:
    """manifest 声明了但包内缺失的文件：跳过不炸（增量备份语义）。"""

    out = tmp_path / "b.zip"
    create_backup(_sources(tmp_path), out, app_version="v", created_at="")
    # 重写 zip：manifest 声明 mastered.json，但包内没有该文件
    repacked = tmp_path / "repacked.zip"
    with zipfile.ZipFile(out) as src, zipfile.ZipFile(repacked, "w") as dst:
        for name in src.namelist():
            if name != C.VOCAB_FILE_NAME:
                dst.writestr(name, src.read(name))
    manifest = json.loads(zipfile.ZipFile(repacked).read("manifest.json"))
    manifest["files"].append(C.VOCAB_FILE_NAME)  # 声明但缺失
    with zipfile.ZipFile(repacked, "w") as dst:
        dst.writestr("manifest.json", json.dumps(manifest))
        dst.writestr(C.CONFIG_FILE_NAME, '{"x": 1}')

    dest = tmp_path / "dest2"
    restored = restore_backup(repacked, dest)
    assert restored == [C.CONFIG_FILE_NAME]


# --------------------------------------------------------------------------- #
# 拒绝非法备份包
# --------------------------------------------------------------------------- #
def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(BackupError):
        read_manifest(tmp_path / "nope.zip")


def test_not_a_zip_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_text("plain text", encoding="utf-8")
    with pytest.raises(BackupError):
        read_manifest(bad)


def test_zip_without_manifest_raises(tmp_path: Path) -> None:
    bare = tmp_path / "bare.zip"
    with zipfile.ZipFile(bare, "w") as archive:
        archive.writestr(C.CONFIG_FILE_NAME, "{}")
    with pytest.raises(BackupError):
        restore_backup(bare, tmp_path / "dest")


def test_unsupported_version_raises(tmp_path: Path) -> None:
    out = tmp_path / "b.zip"
    create_backup(_sources(tmp_path), out, app_version="v", created_at="")
    repacked = tmp_path / "v99.zip"
    with zipfile.ZipFile(out) as src, zipfile.ZipFile(repacked, "w") as dst:
        for name in src.namelist():
            payload = src.read(name)
            if name == "manifest.json":
                payload = json.dumps({**json.loads(payload), "version": 99}).encode("utf-8")
            dst.writestr(name, payload)
    with pytest.raises(BackupError):
        restore_backup(repacked, tmp_path / "dest")


def test_path_traversal_entry_raises(tmp_path: Path) -> None:
    """路径穿越条目（``..\\evil``）：还原时拒绝，绝不写到目标目录之外。"""

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        manifest = {
            "version": C.BACKUP_MANIFEST_VERSION,
            "app_version": "v",
            "created_at": "",
            "files": ["..\\evil.json"],
        }
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("../evil.json", "{}")

    dest = tmp_path / "dest"
    with pytest.raises(BackupError):
        restore_backup(evil, dest)
    assert not (tmp_path / "evil.json").exists()


def test_unknown_filename_raises(tmp_path: Path) -> None:
    """白名单之外的文件名：拒绝还原。"""

    evil = tmp_path / "unknown.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        manifest = {
            "version": C.BACKUP_MANIFEST_VERSION,
            "app_version": "v",
            "created_at": "",
            "files": ["unknown.json"],
        }
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("unknown.json", "{}")
    with pytest.raises(BackupError):
        restore_backup(evil, tmp_path / "dest")


def test_constants_backup_version_pinned() -> None:
    assert C.BACKUP_MANIFEST_VERSION == 1
    assert C.CONFIG_FILE_NAME in C.BACKUP_FILES
    assert C.LOG_FILE_NAME not in C.BACKUP_FILES
