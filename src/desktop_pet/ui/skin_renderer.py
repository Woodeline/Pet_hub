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

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap

from desktop_pet.core import constants as C
from desktop_pet.core.skin_pack import SkinPack, load_skin_pack

logger = logging.getLogger(__name__)

__all__ = ["SkinPackRenderer", "build_skin_renderer", "available_skin_packs"]


class SkinPackRenderer:
    """皮肤包帧图渲染器。

    生命期内持有**一份** :class:`SkinPack` 与帧图缓存（``QPixmap``），按注入的
    槽位与相位选帧绘制。加载失败或未启用时 :attr:`active` 为 ``False``，调用方
    应回落矢量渲染。
    """

    def __init__(self, pack: SkinPack) -> None:
        """构造渲染器并预加载**已映射槽位**的帧图为 ``QPixmap``（失败帧记为 None）。

        只预载 ``action_map`` 引用的动作：DyberPet 社区包动辄数百帧
        （Nahida 743 帧，全量解码约 190MB，会击穿 120MB 内存预算），
        其余动作在 :meth:`current_frame` 首次用到时按需加载。
        """

        self._pack: SkinPack = pack
        self._active: bool = True
        #: 帧图缓存：包根相对帧路径 → QPixmap（加载失败的帧为 None，绘制时跳过）。
        self._frames: dict[str, QPixmap | None] = {}
        self._preload_mapped_frames()

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

    @property
    def display_name(self) -> str:
        """皮肤展示名（包元数据 ``meta.name`` 优先，缺省回落目录名）。"""

        return self._pack.meta.name or self._pack.name

    @property
    def author(self) -> str:
        """皮肤作者（包元数据；缺省空串）。"""

        return self._pack.meta.author

    def has_action(self, slot: str) -> bool:
        """指定槽位是否有可用动作。

        ``load_skin_pack`` 已保证每个动作在磁盘上有 ≥1 张帧图，故此处只需
        校验槽位映射与动作定义存在，不必要求帧已进缓存（缓存是按需填充的）。
        """

        spec = self._pack.action_for(slot)
        return spec is not None and bool(spec.frames)

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
        return self._frame(path), spec.anchor

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

        # 画布适配：帧图已在加载时统一缩放到 fitted 尺寸（见 _shrink_to_fit），
        # 绘制只剩「窗口缩放 × anchor 修正（按同一 fit 系数换算）」。
        fitted_w, _fitted_h = self._pack.fitted_size(C.BASE_W, C.BASE_H)
        if fitted_w <= 0.0:
            return
        s = fitted_w / self._pack.width
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.scale(scale, scale)
            painter.translate(ax * s, ay * s)
            painter.drawPixmap(0, 0, pixmap)
        finally:
            painter.restore()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _preload_mapped_frames(self) -> None:
        """预加载 ``action_map`` 引用的全部动作的帧图（惰性容错：失败帧记 None）。"""

        action_dir = self._pack.root / "action"
        seen: set[str] = set()
        for action_name in self._pack.action_map.values():
            spec = self._pack.actions.get(action_name)
            if spec is None:
                continue
            for name in spec.frames:
                if name in seen:
                    continue
                seen.add(name)
                self._frames[name] = self._load_one(action_dir / name)

    def _frame(self, name: str) -> QPixmap | None:
        """按需取帧：缓存未命中时从磁盘加载（含失败记 None，不阻断绘制）。"""

        if name not in self._frames:
            self._frames[name] = self._load_one(self._pack.root / "action" / name)
        return self._frames[name]

    def _load_one(self, path) -> QPixmap | None:
        """读取单张帧图并缩放到 fitted 尺寸；失败返回 ``None``（跳过该帧）。"""

        try:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                logger.warning("皮肤包帧图加载失败（忽略该帧）：%s", path)
                return None
            return self._shrink_to_fit(pixmap)
        except Exception:  # noqa: BLE001 —— 单帧失败不阻断整包
            logger.warning("皮肤包帧图读取异常（忽略该帧）：%s", path, exc_info=True)
            return None

    def _shrink_to_fit(self, pixmap: QPixmap) -> QPixmap:
        """把帧图按 ``fitted_size/pack 尺寸`` 的系数一次性缩放（含放大）。

        社区包帧图普遍 200px 级（Nahida 239×268），若按原尺寸缓存，
        预载帧约 51MB、逼近 120MB 内存预算（FR-31）；统一缩到 fitted 尺寸
        （≤160×180）后单帧 ≤112KB。绘制侧因此无需再做画布适配缩放。
        """

        fitted_w, _ = self._pack.fitted_size(C.BASE_W, C.BASE_H)
        if fitted_w <= 0.0 or self._pack.width <= 0:
            return pixmap
        factor = fitted_w / self._pack.width
        if abs(factor - 1.0) < 1e-3:
            return pixmap
        target_w = max(1, int(round(pixmap.width() * factor)))
        target_h = max(1, int(round(pixmap.height() * factor)))
        return pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )


def available_skin_pack_entries() -> list[tuple[str, str, str]]:
    """列出 ``skins/`` 下**通过校验**的皮肤包 ``(目录名, 显示名, 说明)``。

    - 目录名作为菜单值（``cfg.skin_name`` 口径不变），显示名来自包元数据
      ``meta.name``（缺省回落目录名）；
    - 说明拼装作者 / 版本（缺失部分省略），供皮肤菜单 action 的 toolTip；
    - 校验失败的包不入列（日志已记明跳过原因）。
    """

    from desktop_pet.core.paths import skins_dir

    root = skins_dir()
    if not root.is_dir():
        return []
    entries: list[tuple[str, str, str]] = []
    for cand in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            pack = load_skin_pack(cand)
        except Exception:  # noqa: BLE001 —— 损坏包不入菜单
            continue
        label = pack.meta.name or pack.name
        tips = []
        if pack.meta.author:
            tips.append(f"作者：{pack.meta.author}")
        if pack.meta.version:
            tips.append(f"版本：{pack.meta.version}")
        if pack.meta.credits:
            tips.append(pack.meta.credits)
        entries.append((cand.name, label, " · ".join(tips)))
    return entries


def available_skin_packs() -> list[str]:
    """列出 ``skins/`` 下**通过校验**的皮肤包名（按目录名排序）。

    供托盘「皮肤」子菜单构建；校验失败的包不入列（日志已记明跳过原因）。
    """

    return [name for name, _label, _tip in available_skin_pack_entries()]


def build_skin_renderer(preferred: str = "") -> SkinPackRenderer | None:
    """加载皮肤包并构造渲染器。

    Args:
        preferred: 期望的包名（``cfg.skin_name``）。
            - ``""``（自动）：扫描 ``skins_dir()``，取**首个**校验通过的包；
            - ``"vector"``：显式要求矢量渲染 → 直接返回 ``None``；
            - 其他：优先加载该包，不存在或损坏时**回落自动选择**。

    Returns:
        构造好的 :class:`SkinPackRenderer`；无可用皮肤包（或显式矢量）时返回 ``None``。
    """

    from desktop_pet.core.paths import skins_dir

    name = str(preferred or "").strip()
    if name == C.SKIN_NAME_VECTOR:
        return None

    root = skins_dir()
    if not root.is_dir():
        return None

    candidates = sorted(p for p in root.iterdir() if p.is_dir())
    if name:
        # 指定包优先；找不到时保持原顺序回落自动（不报错，日志说明）。
        head = [p for p in candidates if p.name == name]
        if not head:
            logger.warning("指定的皮肤包不存在：%s（回落自动选择）", name)
        candidates = head + [p for p in candidates if p.name != name]

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
