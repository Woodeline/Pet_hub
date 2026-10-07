"""ui.icon_factory（程序化矢量图标工厂）回归测试。

守护 P1 的图标不变式：

- 六个图标名齐全；未知名抛 ``ValueError``。
- 每个图标都能渲染出**非空、24×24、含不透明像素**的 pixmap（证明真画了东西）。
- 六个图标的像素摘要**互不相同**（防止「返回同一张空白图」的假实现）。
- 自定义 ``color`` 确实改变像素。
- 绘制前后项目内**不产生任何图片素材文件**（零外部素材承诺）。
"""

from __future__ import annotations

import hashlib

import pytest

from desktop_pet.core import constants as C
from desktop_pet.ui import icon_factory

# 与 test_static_constraints 保持一致的图片后缀集合。
_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".tif", ".tiff", ".qrc", ".xpm",
}


def _opaque_pixel_count(image) -> int:
    """统计不透明像素数（alpha > 0）。"""

    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                count += 1
    return count


def _signature(image) -> str:
    """对图像原始字节取哈希，作为「像素摘要」。"""

    return hashlib.sha256(bytes(image.constBits())).hexdigest()


# --------------------------------------------------------------------------- #
# 1. 图标名清单
# --------------------------------------------------------------------------- #
def test_icon_names_complete() -> None:
    """图标名齐全（卡片化改版新增 speaker；词库纠错新增 pencil）。"""

    assert icon_factory.ICON_NAMES == (
        "close", "retry", "remove", "trash", "speaker", "pencil",
    )


# --------------------------------------------------------------------------- #
# 2. 每个图标都能渲染出非空内容
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", icon_factory.ICON_NAMES)
def test_make_icon_renders_nonempty(qapp, name: str) -> None:
    """每个图标非空、尺寸正确、含不透明像素。"""

    icon = icon_factory.make_icon(name)
    assert not icon.isNull(), f"{name} 返回空图标"
    pixmap = icon.pixmap(24, 24)
    assert not pixmap.isNull(), f"{name} pixmap 为空"
    assert pixmap.width() == 24 and pixmap.height() == 24, f"{name} 尺寸非 24×24"
    assert _opaque_pixel_count(pixmap.toImage()) > 0, f"{name} 是空白图（没有画出任何像素）"


# --------------------------------------------------------------------------- #
# 3. 六个图标互不相同
# --------------------------------------------------------------------------- #
def test_icons_are_visually_distinct(qapp) -> None:
    """六个图标的像素摘要两两不同（防止假实现：所有 name 返回同一张图）。"""

    signatures = {
        name: _signature(icon_factory.make_icon(name).pixmap(24, 24).toImage())
        for name in icon_factory.ICON_NAMES
    }
    assert len(set(signatures.values())) == len(icon_factory.ICON_NAMES), (
        f"存在重复图标：{signatures}"
    )


# --------------------------------------------------------------------------- #
# 4. 未知图标名 → ValueError
# --------------------------------------------------------------------------- #
def test_make_icon_unknown_name_raises(qapp) -> None:
    """未知图标名抛 ``ValueError``。"""

    with pytest.raises(ValueError):
        icon_factory.make_icon("nope")


# --------------------------------------------------------------------------- #
# 5. 自定义颜色生效
# --------------------------------------------------------------------------- #
def test_make_icon_custom_color_changes_pixels(qapp) -> None:
    """自定义 ``color`` 时像素摘要与默认色不同，且颜色确实被使用。"""

    default_icon = icon_factory.make_icon("close")
    custom_icon = icon_factory.make_icon("close", color="#FF0000")
    default_sig = _signature(default_icon.pixmap(24, 24).toImage())
    custom_sig = _signature(custom_icon.pixmap(24, 24).toImage())
    assert default_sig != custom_sig, "自定义颜色未改变像素"

    # 进一步验证：自定义红色图里存在偏红像素。
    image = custom_icon.pixmap(24, 24).toImage()
    reddish = any(
        image.pixelColor(x, y).alpha() > 0 and image.pixelColor(x, y).red() > 150
        for y in range(image.height())
        for x in range(image.width())
    )
    assert reddish, "自定义红色未反映到像素"


def test_default_color_comes_from_semantic_tokens(qapp) -> None:
    """默认色即 ``SEMANTIC_COLORS["text_secondary"]``（与显式传该色像素一致）。"""

    default_sig = _signature(icon_factory.make_icon("close").pixmap(24, 24).toImage())
    explicit_sig = _signature(
        icon_factory.make_icon(
            "close", color=C.SEMANTIC_COLORS["text_secondary"]
        ).pixmap(24, 24).toImage()
    )
    assert default_sig == explicit_sig


def test_make_icon_respects_size(qapp) -> None:
    """``size`` 参数真实生效：内置位图尺寸随 size 变化（默认 24）。"""

    big = {(s.width(), s.height()) for s in icon_factory.make_icon("close", size=48).availableSizes()}
    assert (48, 48) in big, f"size=48 未生效，实际内含尺寸：{big}"

    default_sizes = {
        (s.width(), s.height()) for s in icon_factory.make_icon("close").availableSizes()
    }
    assert (24, 24) in default_sizes, f"默认尺寸非 24×24：{default_sizes}"


# --------------------------------------------------------------------------- #
# 6. 不落盘任何图片素材
# --------------------------------------------------------------------------- #
def test_icon_rendering_creates_no_image_assets(qapp, project_root) -> None:
    """把六个图标各绘制一轮后，项目内图片素材文件数仍为 0。"""

    for name in icon_factory.ICON_NAMES:
        icon_factory.make_icon(name, size=32)

    offenders = [
        str(path.relative_to(project_root))
        for path in project_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in _IMAGE_SUFFIXES
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
        and "skins" not in path.parts  # 用户本地皮肤包投放区（gitignore，含第三方素材）
        and "third_party" not in path.parts  # 用户本地克隆的第三方数据仓库（gitignore）
    ]
    assert not offenders, f"图标绘制落盘了图片素材：{offenders}"
