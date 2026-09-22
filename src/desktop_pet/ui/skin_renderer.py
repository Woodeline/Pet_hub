"""ui.skin_renderer —— 皮肤包帧图渲染通道（Phase 2）。

把 :class:`~desktop_pet.core.skin_pack.SkinPack` 加载出的帧图（透明 PNG）
渲染到宠物画布。与 :class:`~desktop_pet.ui.pet_renderer.PetRenderer` 的矢量
团子猫是**互斥**的两条渲染路径：启用皮肤包时，窗口走本渲染器；否则走矢量。

职责边界（对齐 core 红线精神，本模块在 ui 层故可用 Qt）：

- 只做「帧图加载 + 按槽位/相位选帧 + 绘制」，**不做**任何状态机 / 姿态决策；
- 槽位由调用方（窗口/控制器）注入，本模块只负责把槽位解析为动作、把动作
  解析为当前帧；
- 帧切换相位用**单调秒数**驱动（由窗口帧循环注入），帧图序列按
  ``frame_refresh`` 切帧、按 ``act_num`` 循环复用，**不**使用运行期 ``random``
  （可复现性红线，与 :meth:`PetRenderer.set_decor_phase` 同源）。
"""

from __future__ import annotations

import logging

from PySide6.QtGui import QPainter, QPixmap

from desktop_pet.core import constants as C
from desktop_pet.core.skin_pack import SkinPack, load_skin_pack

logger = logging.getLogger(__name__)

__all__ = ["SkinPackRenderer"]


class SkinPackRenderer:
    """皮肤包帧图渲染器。

    生命期内持有**一份** :class:`SkinPack` 与帧图缓存（``QPixmap``），按注入的
    槽位与相位选帧绘制。加载失败或未启用时 :attr:`active` 为 ``False``，调用方
    应回落矢量渲染。
    """

    def __init__(self, pack: SkinPack) -> None:
        """构造渲染器并预加载所有帧图为 ``QPixmap``（失败帧记为 None）。"""

        self._pack: SkinPack = pack
        self._active: bool = True
        #: 帧图缓存：包根相对帧路径 → QPixmap（加载失败的帧为 None，绘制时跳过）。
        self._frames: dict[str, QPixmap | None] = {}
        self._load_frames()

    # ------------------------------------------------------------------ #
    # 只读探针
    # ------------------------------------------------------------------ #
    @property
    def active(self) -> bool:
        """是否成功持有可绘制的皮肤包（有任一动作帧可用即视为激活）。"""

        return self._active and any(p is not None for p in self._frames.values())

    @property
    def pack_name(self) -> str:
        """皮肤包名（目录名）。"""

        return self._pack.name

    def has_action(self, slot: str) -> bool:
        """指定槽位是否有可用动作（含帧图加载成功）。"""

        spec = self._pack.action_for(slot)
        if spec is None:
            return False
        return any(self._frames.get(f) is not None for f in spec.frames)

    # ------------------------------------------------------------------ #
    # 选帧
    # ------------------------------------------------------------------ #
    def current_frame(
        self, slot: str, phase_s: float
    ) -> tuple[QPixmap | None, tuple[int, int]]:
        """返回指定槽位在当前相位应显示的帧及其 ``anchor`` 偏移。

        Args:
            slot: 槽位（``default`` / ``drag`` / ``fall`` / ``patpat`` …）。
            phase_s: 单调秒数（由窗口帧循环注入）。

        Returns:
            ``(QPixmap | None, (anchor_x, anchor_y))``；槽位无动作或帧加载失败
            时返回 ``(None, (0, 0))``，调用方据此回落。
        """

        spec = self._pack.action_for(slot)
        if spec is None:
            return None, (0, 0)
        if not spec.frames:
            return None, (0, 0)

        expanded = spec.expanded_frames
        total = len(expanded)
        if total == 0:
            return None, (0, 0)

        # 帧率：frame_refresh 秒一帧，act_num 展开后循环。
        idx = int(phase_s / spec.frame_refresh_s) % total
        path = expanded[idx]
        pixmap = self._frames.get(path)
        return pixmap, spec.anchor

    # ------------------------------------------------------------------ #
    # 绘制
    # ------------------------------------------------------------------ #
    def paint(
        self,
        painter: QPainter,
        slot: str,
        phase_s: float,
        scale: float,
    ) -> None:
        """在 ``painter`` 上绘制当前帧。

        Args:
            painter: 目标绘制器（调用方已 attach 到窗口）。
            slot: 当前槽位。
            phase_s: 单调秒数。
            scale: 缩放系数（与矢量渲染共用同一套画布缩放）。
        """

        pixmap, (ax, ay) = self.current_frame(slot, phase_s)
        if pixmap is None or pixmap.isNull():
            return

        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            # 画布基准：皮肤包帧图按包内 width/height 尺寸设计，缩放至逻辑画布。
            # anchor 是相对宠物固定位置的像素平移修正，映射到画布后叠加。
            painter.scale(scale, scale)
            painter.translate(ax, ay)
            target_w = self._pack.width
            target_h = self._pack.height
            painter.drawPixmap(0, 0, target_w, target_h, pixmap)
        finally:
            painter.restore()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _load_frames(self) -> None:
        """预加载所有动作的全部帧图为 ``QPixmap``（惰性容错：失败帧记 None）。"""

        action_dir = self._pack.root / "action"
        for spec in self._pack.actions.values():
            for name in spec.frames:
                if name in self._frames:
                    continue
                path = action_dir / name
                try:
                    pixmap = QPixmap(str(path))
                    if pixmap.isNull():
                        logger.warning("皮肤包帧图加载失败（忽略该帧）：%s", path)
                        self._frames[name] = None
                    else:
                        self._frames[name] = pixmap
                except Exception:  # noqa: BLE001 —— 单帧失败不阻断整包
                    logger.warning("皮肤包帧图读取异常（忽略该帧）：%s", path, exc_info=True)
                    self._frames[name] = None


def build_skin_renderer() -> SkinPackRenderer | None:
    """从 ``skins/`` 目录加载**第一个可用的**皮肤包并构造渲染器。

    扫描 ``skins_dir()`` 下的一级子目录，逐个尝试 :func:`load_skin_pack`；
    首个加载成功且帧图可用者胜出。全部失败返回 ``None``（调用方回落矢量渲染）。

    返回:
        构造好的 :class:`SkinPackRenderer`；无可用皮肤包时返回 ``None``。
    """

    from desktop_pet.core.paths import skins_dir

    root = skins_dir()
    if not root.is_dir():
        return None

    candidates = sorted(p for p in root.iterdir() if p.is_dir())
    for cand in candidates:
        try:
            pack = load_skin_pack(cand)
        except Exception as exc:  # noqa: BLE001 —— 单个皮肤包损坏不阻断
            logger.warning("跳过损坏的皮肤包 %s：%s", cand.name, exc)
            continue
        renderer = SkinPackRenderer(pack)
        if renderer.active:
            logger.info("已启用皮肤包：%s", renderer.pack_name)
            return renderer
    return None
