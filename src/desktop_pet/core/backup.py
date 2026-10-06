"""core.backup —— 用户数据一键备份与还原（纯 stdlib zipfile，零 Qt、零时钟）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得自取时钟**：
``created_at`` 由 app 层注入 ISO8601 字符串，原样写入 manifest。

备份包结构（zip）：

.. code-block:: text

    manifest.json                  ← {"version": 1, "app_version": "...", "created_at": "...", "files": [...]}
    config.json / vocabulary.json / ...   ← 仅收录 :data:`BACKUP_FILES` 中实际存在的文件

安全与健壮性约定：

- **白名单**：打包与还原都只接受 :data:`constants.BACKUP_FILES` 中的文件名，
  拒绝任何带路径分隔符 / ``..`` / 白名单之外的条目（zip 路径穿越防护）；
- **还原原子写**：先写入同目录临时文件再 ``os.replace``，既有文件先留档为
  ``<name>.pre-restore-<n>``（不覆盖旧留档），与各 store 的损坏备份范式一致；
- 损坏 / 非法备份包显式抛 :class:`BackupError`（携带用户可读原因），绝不静默清空。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)

_MANIFEST_NAME: str = "manifest.json"


class BackupError(Exception):
    """备份 / 还原失败（携带用户可读原因）。"""


def _validate_entry_name(name: str) -> str:
    """校验备份包内条目名：仅允许白名单文件名，返回规范化后的名字。"""

    normalized = str(name).strip().replace("\\", "/")
    if (
        not normalized
        or "/" in normalized
        or normalized.startswith(".")
        or ".." in normalized
    ):
        raise BackupError(f"备份包含非法条目：{name!r}")
    if normalized == _MANIFEST_NAME:
        return normalized
    if normalized not in C.BACKUP_FILES:
        raise BackupError(f"备份包含未知文件：{normalized!r}")
    return normalized


def create_backup(
    files: Mapping[str, Path],
    out_path: Path,
    *,
    app_version: str,
    created_at: str,
) -> Path:
    """把数据文件打包为 zip 备份（``files``：压缩包内文件名 → 源路径）。

    - 键必须在 :data:`constants.BACKUP_FILES` 白名单内；源文件不存在则跳过
      （首次使用可能尚未生成全部文件，属正常）；
    - ``manifest.json`` 记录版本 / 应用版本 / 创建时间 / 实际收录文件清单；
    - 目录不存在时自动创建；写入失败（OSError / zip 错误）抛 :class:`BackupError`。
    """

    out_path = Path(out_path)
    included: list[str] = []
    for name in C.BACKUP_FILES:
        if name not in files:
            continue
        src = Path(files[name])
        if src.is_file():
            included.append(name)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            manifest = {
                "version": C.BACKUP_MANIFEST_VERSION,
                "app_version": str(app_version),
                "created_at": str(created_at),
                "files": list(included),
            }
            archive.writestr(_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
            for name in included:
                archive.write(Path(files[name]), arcname=name)
    except BackupError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 统一转 BackupError，调用方给用户可读反馈
        logger.exception("创建备份失败：%s", out_path)
        raise BackupError(f"无法写入备份文件：{exc}") from exc
    logger.info("备份完成：%s（收录 %d 个文件）", out_path, len(included))
    return out_path


def read_manifest(zip_path: Path) -> dict[str, Any]:
    """读取并校验备份包 manifest（非法包抛 :class:`BackupError`）。"""

    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise BackupError("备份文件不存在")
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            names = archive.namelist()
            if _MANIFEST_NAME not in names:
                raise BackupError("不是有效的备份包（缺少 manifest.json）")
            raw = archive.read(_MANIFEST_NAME).decode("utf-8")
    except zipfile.BadZipFile as exc:
        raise BackupError(f"备份文件损坏（不是有效的 zip）：{exc}") from exc
    except OSError as exc:
        raise BackupError(f"无法读取备份文件：{exc}") from exc

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BackupError(f"备份清单损坏（manifest.json 无法解析）：{exc}") from exc
    if not isinstance(manifest, dict):
        raise BackupError("备份清单结构非法（根节点不是对象）")
    version = manifest.get("version")
    if version != C.BACKUP_MANIFEST_VERSION:
        raise BackupError(f"不支持的备份版本：{version!r}")
    return manifest


def restore_backup(zip_path: Path, dest_dir: Path) -> list[str]:
    """把备份包中的数据文件还原到 ``dest_dir``（逐文件原子写 + 既有文件留档）。

    只还原 manifest ``files`` 清单内、且仍在白名单中的文件；备份包中缺失的
    文件跳过（增量备份语义）。返回实际还原的文件名列表。

    Raises:
        BackupError: 备份包损坏 / manifest 非法 / 包含白名单之外的条目。
    """

    manifest = read_manifest(zip_path)
    listed = manifest.get("files")
    if not isinstance(listed, list) or not all(isinstance(name, str) for name in listed):
        raise BackupError("备份清单 files 字段非法")

    dest_dir = Path(dest_dir)
    restored: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            for name in listed:
                normalized = _validate_entry_name(name)
                if normalized not in archive.namelist():
                    logger.warning("备份包缺少清单声明的文件（跳过）：%s", normalized)
                    continue
                payload = archive.read(normalized)
                _atomic_write(dest_dir / normalized, payload)
                restored.append(normalized)
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        logger.exception("还原备份失败：%s", zip_path)
        raise BackupError(f"还原过程中失败：{exc}") from exc
    logger.info("备份已还原到 %s：%s", dest_dir, restored)
    return restored


def _atomic_write(target: Path, payload: bytes) -> None:
    """原子写单文件：既有文件先留档（``.pre-restore-<n>``），临时文件 + ``os.replace``。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        _preserve_existing(target)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{target.name}-", suffix=".restore-tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass
        raise


def _preserve_existing(target: Path) -> None:
    """把既有文件留档为 ``<name>.pre-restore-<n>``（绝不覆盖旧留档）。"""

    suffix = C.BACKUP_PRE_RESTORE_SUFFIX
    candidate = target.with_name(f"{target.name}{suffix}")
    counter = 1
    while candidate.exists():
        candidate = target.with_name(f"{target.name}{suffix}-{counter}")
        counter += 1
    try:
        os.replace(target, candidate)
        logger.info("还原留档：%s → %s", target, candidate)
    except OSError as exc:
        raise BackupError(f"无法留档既有文件 {target.name}：{exc}") from exc


__all__ = ["BackupError", "create_backup", "read_manifest", "restore_backup"]
