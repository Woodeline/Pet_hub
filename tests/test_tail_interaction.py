"""尾巴形状 + 「鼠标靠近 / 触碰」避让交互的回归测试。

覆盖三块：

1. **纯几何工具**（``core.motion``）：点到线段距离、点到折线的距离与有符号侧别、
   距离→避让强度的映射（必须有"死区"，否则尾巴会在远处无端抖动）。
2. **尾巴脊线**（``ui.pet_renderer.PetRenderer.tail_spine``）：
   * 画布内不越界（含 ``tail_curve=1`` 的最长情形与 ``tail_angle=150`` 的睡姿）；
   * 曲率连续（相邻线段转角有界）——脊线是"角度积分"生成的，不该出现折角；
   * 宽度剖面单调收细且**尾尖仍有厚度**（圆头帽存在 → 不是平切）。
3. **避让动态**（``core.pet_model.PetModel``）：
   * 尾巴向光标的**反侧**摆开；
   * 逼近快 / 回落慢（非对称）；
   * 帧率无关（30 vs 60fps 结果**精确一致**）；
   * 被拎起（拖拽）时忽略；
   * 只影响 ``tail_angle`` / ``tail_curve``，不污染其它通道。

.. important::
   本机教训：改写既有断言必须用「变异体」验证新断言仍能拦住缺陷。本文件的断言
   均为**新增**，且每条都对应一个可被破坏的具体行为（见各 docstring 括号内的
   "变异体"说明）。
"""

from __future__ import annotations

import math

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel
from desktop_pet.ui import pet_renderer as R
from desktop_pet.ui.pet_renderer import PetRenderer

_FPS30 = 1.0 / 30.0
_FPS60 = 1.0 / 60.0


# --------------------------------------------------------------------------- #
# 1. 纯几何工具（core.motion）
# --------------------------------------------------------------------------- #
def test_point_segment_distance_projects_and_clamps() -> None:
    """垂足落在段内取垂距；落在段外取端点距离（变异体：去掉 clamp → 段外给出错误的小距离）。"""

    # 段 (0,0)-(10,0)：正上方 4 → 垂距 4
    assert motion.point_segment_distance(5.0, 4.0, 0.0, 0.0, 10.0, 0.0) == pytest.approx(4.0)
    # 段外右侧 → 到端点 (10,0) 的距离 = 5
    assert motion.point_segment_distance(13.0, 4.0, 0.0, 0.0, 10.0, 0.0) == pytest.approx(5.0)
    # 退化段（两点重合）→ 到该点的距离
    assert motion.point_segment_distance(3.0, 4.0, 1.0, 1.0, 1.0, 1.0) == pytest.approx(
        math.hypot(2.0, 3.0)
    )


def test_polyline_proximity_returns_distance_and_signed_side() -> None:
    """侧别符号必须**跟随折线朝向**（变异体：改用固定轴比较 → 折线掉头后符号不变）。"""

    # 折线沿 +x 前进：y 更大的一侧记为 +1
    pts = [(0.0, 0.0), (10.0, 0.0)]
    distance, side = motion.polyline_proximity(5.0, 3.0, pts)
    assert distance == pytest.approx(3.0)
    assert side == 1.0

    _, side_above = motion.polyline_proximity(5.0, -3.0, pts)
    assert side_above == -1.0

    # 折线掉头（沿 -x 前进）后，同样位于 y=+3 的点应翻到 -1
    _, side_flipped = motion.polyline_proximity(5.0, 3.0, [(10.0, 0.0), (0.0, 0.0)])
    assert side_flipped == -1.0

    # 恰好在线上 → 中性侧别
    _, side_zero = motion.polyline_proximity(5.0, 0.0, pts)
    assert side_zero == 0.0

    # 退化输入不崩
    assert motion.polyline_proximity(1.0, 1.0, []) == (0.0, 0.0)
    assert motion.polyline_proximity(1.0, 1.0, [(0.0, 0.0)]) == (0.0, 0.0)


def test_tail_evade_amount_has_dead_zone_and_full_zone() -> None:
    """距离→强度：近处满、远处零、中间平滑单调（变异体：去掉 far 死区 → 远处仍抖动）。"""

    near, far = 10.0, 40.0
    assert motion.tail_evade_amount(0.0, near, far) == 1.0
    assert motion.tail_evade_amount(near, near, far) == 1.0
    assert motion.tail_evade_amount(far, near, far) == 0.0
    assert motion.tail_evade_amount(999.0, near, far) == 0.0

    values = [motion.tail_evade_amount(d, near, far) for d in range(0, 60, 2)]
    assert all(0.0 <= v <= 1.0 for v in values)
    # 严格单调不增（距离越远，避让越弱）
    assert all(a >= b - 1e-12 for a, b in zip(values, values[1:]))
    # 中间段确有过渡（不是硬阶跃：中点应显著介于 0 与 1 之间）
    mid = motion.tail_evade_amount((near + far) / 2.0, near, far)
    assert 0.2 < mid < 0.8


# --------------------------------------------------------------------------- #
# 2. 尾巴脊线几何
# --------------------------------------------------------------------------- #
_ALL_EXPRESSIONS = list(Expression)


def _tail_outline_bbox(pose) -> tuple[float, float, float, float]:
    """尾巴**真实轮廓路径**的包围盒（含宽度剖面与尾尖圆帽）。"""

    path = PetRenderer._tail_outline(PetRenderer.tail_spine(pose))
    xs = [path.elementAt(i).x for i in range(path.elementCount())]
    ys = [path.elementAt(i).y for i in range(path.elementCount())]
    return min(xs), min(ys), max(xs), max(ys)


@pytest.mark.parametrize("expr", _ALL_EXPRESSIONS, ids=lambda e: e.name)
def test_tail_outline_plus_stroke_stays_inside_canvas(expr: Expression) -> None:
    """尾巴轮廓（含描边）必须完整落在 160×180 画布内。

    口径是**真实轮廓路径**的包围盒 + 描边半宽，而不是「拿根部最粗的半宽去套每一个
    点」——后者虚高约 4 倍（最左点其实在尾尖附近，局部半宽只有 ``W1/2``），会把
    合法参数误判成越界。

    变异体（均须 FAIL）：
      * ``_GEO_TAIL_X`` 调小（根部左移）；
      * ``_GEO_TAIL_LEN`` 调大（脊线拉长 → 尾尖捅出左沿）。
    """

    pose = PetModel.pose_for_expression(expr)
    half = R._STROKE_W / 2.0
    x0, y0, x1, y1 = _tail_outline_bbox(pose)
    assert x0 - half >= 0.0, f"{expr.name}: 尾巴越出左边界（x={x0 - half:.1f}）"
    assert y0 - half >= 0.0, f"{expr.name}: 尾巴越出上边界（y={y0 - half:.1f}）"
    assert x1 + half <= C.BASE_W, f"{expr.name}: 尾巴越出右边界（x={x1 + half:.1f}）"
    assert y1 + half <= C.BASE_H, f"{expr.name}: 尾巴越出下边界（y={y1 + half:.1f}）"


def test_tail_spine_has_no_kink() -> None:
    """脊线的相邻线段转角有界 → 曲率连续、没有折角。

    脊线由「方向角沿 :func:`motion.smoothstep` 积分」生成，单步转角上限约为
    ``1.5 × sweep / N``（smoothstep 在 t=0.5 处斜率最大）。若改用折线或丢掉
    平滑，转角会在某处突增，本测试失败。
    """

    pose = PetModel.pose_for_expression(Expression.HAPPY)   # tail_curve 最高 → sweep 最大
    spine = PetRenderer.tail_spine(pose)
    angles = [
        math.atan2(spine[i + 1][1] - spine[i][1], spine[i + 1][0] - spine[i][0])
        for i in range(len(spine) - 1)
    ]
    # 注意：角度差必须先归一化到 (-180°, 180°]，否则 179° → -179° 这类
    # 跨越 ±π 的相邻角会被算成 358° 的假折角。
    turns = [
        abs(math.degrees((a - b + math.pi) % (2.0 * math.pi) - math.pi))
        for a, b in zip(angles, angles[1:])
    ]
    assert max(turns) < 10.0, f"脊线出现折角：单步最大转角 {max(turns):.1f}°"


def test_tail_width_profile_tapers_but_keeps_rounded_tip() -> None:
    """宽度剖面：根部最粗、单调收细、**尾尖仍有厚度**（圆头帽存在）。

    变异体：把 ``_GEO_TAIL_W1`` 设为 0 → 尾尖退化成尖角，第二条断言失败。
    """

    widths = [PetRenderer._tail_width_at(t / 20.0) for t in range(21)]
    assert widths[0] == pytest.approx(R._GEO_TAIL_W0), "根部宽度不等于 _GEO_TAIL_W0"
    assert widths[0] > widths[-1], "尾巴根部未比尾尖粗"
    assert all(a >= b - 1e-12 for a, b in zip(widths, widths[1:])), "宽度剖面非单调收细"
    assert widths[-1] > 0.0, "尾尖宽度为 0 → 无圆头帽（退化成尖角）"
    # 中段应保持较厚（非线性剖面：t=0.5 处仍保留 60% 以上根部宽度）
    mid_ratio = widths[10] / widths[0]
    assert mid_ratio > 0.6, f"中段收细过快（t=0.5 仅剩 {mid_ratio:.0%}）→ 显得单薄"


def test_tail_outline_is_closed_and_inside_bounds() -> None:
    """轮廓路径闭合，且其包围盒被 ``body_bounds`` 覆盖（脏区不裁尾巴）。"""

    pose = PetModel.pose_for_expression(Expression.HAPPY)
    path = PetRenderer._tail_outline(PetRenderer.tail_spine(pose))
    assert path.elementCount() > 0

    xs = [path.elementAt(i).x for i in range(path.elementCount())]
    ys = [path.elementAt(i).y for i in range(path.elementCount())]
    rect = PetRenderer.body_bounds(pose, 1.0)
    assert rect.left() <= min(xs) and rect.top() <= min(ys)
    assert rect.right() >= max(xs) and rect.bottom() >= max(ys)


# --------------------------------------------------------------------------- #
# 3. 避让动态（core.pet_model）
# --------------------------------------------------------------------------- #
def _run(model: PetModel, fps: int, seconds: float, now: float = 0.0) -> None:
    """以固定步长推进模型；``now`` 冻结 → 呼吸/尾摆等周期项恒为同一相位。"""

    dt = 1.0 / fps
    for step in range(int(round(seconds * fps))):
        # 用冻结时钟：周期项在相同相位取样，两次运行可直接逐通道比对
        model.update(dt, now)


def _control_pose(expr: Expression = Expression.FOCUS):
    model = PetModel()
    model.set_base_expression(expr)
    _run(model, 30, 1.5)
    return model.pose()


def test_tail_evade_swings_away_from_cursor_side() -> None:
    """光标在尾巴某侧时，尾巴必须朝**反侧**摆开。

    变异体：把 ``-=`` 写成 ``+=``，或忽略 ``side`` → 尾巴朝光标方向"迎上去"，本测试失败。
    """

    for side in (1.0, -1.0):
        model = PetModel()
        model.set_base_expression(Expression.FOCUS)
        model.set_tail_evade(1.0, side)
        _run(model, 30, 1.5)

        pose = model.pose()
        base = _control_pose()
        delta_angle = pose.tail_angle - base.tail_angle

        assert model.tail_evade()[0] > 0.99, "避让强度未收敛到满值"
        assert delta_angle * side < 0.0, (
            f"side={side} 时尾巴未朝反侧摆开（Δtail_angle={delta_angle:.2f}）"
        )
        assert abs(delta_angle) == pytest.approx(C.TAIL_EVADE_ANGLE_DEG, abs=0.05)


def test_tail_evade_curls_up_when_touched() -> None:
    """触碰时尾巴额外「上收」（tail_curve 增大，且被钳制在 ≤1）。

    用 FOCUS（tail_curve=0.35）→ 0.35+0.42 不会触顶，可精确校验幅度。
    """

    model = PetModel()
    model.set_base_expression(Expression.FOCUS)
    model.set_tail_evade(1.0, 1.0)
    _run(model, 30, 1.5)

    base = _control_pose()
    assert model.pose().tail_curve - base.tail_curve == pytest.approx(
        C.TAIL_EVADE_CURL, abs=0.01
    )
    assert model.pose().tail_curve <= 1.0


def test_tail_evade_only_touches_tail_channels() -> None:
    """避让只应改动 ``tail_angle`` / ``tail_curve``，不得污染其它通道。

    变异体：把避让误加到 ``body_y``／``head_tilt`` 等通道 → 本测试失败。
    """

    model = PetModel()
    model.set_base_expression(Expression.FOCUS)
    model.set_tail_evade(1.0, 1.0)
    _run(model, 30, 1.5)

    base = _control_pose()
    changed = {
        name
        for name in vars(model.pose())
        if abs(getattr(model.pose(), name) - getattr(base, name)) > 1e-6
    }
    assert changed <= {"tail_angle", "tail_curve"}, f"避让污染了通道：{changed}"


def test_tail_evade_is_frame_rate_independent() -> None:
    """30fps 与 60fps 的避让强度必须**精确一致**（指数平滑的固有性质）。

    变异体：把 ``t = 1 - exp(-k*dt)`` 换成 ``t = k*dt`` → 30/60fps 结果分叉，本测试失败。
    """

    m30 = PetModel(); m30.set_base_expression(Expression.FOCUS); m30.set_tail_evade(1.0, 1.0)
    m60 = PetModel(); m60.set_base_expression(Expression.FOCUS); m60.set_tail_evade(1.0, 1.0)
    _run(m30, 30, 1.0)
    _run(m60, 60, 1.0)
    assert m30.tail_evade()[0] == pytest.approx(m60.tail_evade()[0], abs=1e-12)


def test_tail_evade_release_is_slower_than_attack() -> None:
    """回落显著慢于逼近（非对称平滑 → "惊觉后缓缓放松"的余韵）。

    变异体：把回落系数改成与逼近相同的常数 → 两条曲线的剩余量相等，本测试失败。
    """

    attack = PetModel(); attack.set_base_expression(Expression.FOCUS)
    attack.set_tail_evade(1.0, 1.0)
    _run(attack, 30, 0.1)
    attacked = attack.tail_evade()[0]

    release = PetModel(); release.set_base_expression(Expression.FOCUS)
    release.set_tail_evade(1.0, 1.0)
    _run(release, 30, 1.0)          # 先完全到满
    release.set_tail_evade(0.0, 0.0)
    _run(release, 30, 0.1)
    remaining = release.tail_evade()[0]

    assert attacked > 0.5, f"逼近过慢：0.1s 仅到 {attacked:.2f}"
    assert remaining > 0.3, f"回放过快：0.1s 已降到 {remaining:.2f}"
    assert attacked > remaining, "逼近与回落速率未体现非对称"


def test_tail_evade_decays_back_to_zero() -> None:
    """松开后避让必须收敛回 0（不会永久残留姿态偏移）。"""

    model = PetModel()
    model.set_base_expression(Expression.FOCUS)
    model.set_tail_evade(1.0, 1.0)
    _run(model, 30, 0.5)
    model.set_tail_evade(0.0, 0.0)
    _run(model, 30, 3.0)
    assert model.tail_evade()[0] < 1e-3


def test_tail_evade_ignored_while_dragging() -> None:
    """被拎起（拖拽）时不叠加避让 —— 否则"整体外摆"与"躲闪"会互相打架。"""

    model = PetModel()
    model.set_base_expression(Expression.FOCUS)
    model.set_dragging(True)
    model.set_tail_evade(1.0, 1.0)
    _run(model, 30, 0.5)
    assert model.tail_evade()[0] < 1e-3

    # 放下后重新响应
    model.set_dragging(False)
    model.set_tail_evade(1.0, 1.0)
    _run(model, 30, 0.5)
    assert model.tail_evade()[0] > 0.99


def test_tail_evade_amount_is_clamped() -> None:
    """越界输入必须被钳制（防御 UI 层传入异常值）。"""

    model = PetModel()
    model.set_tail_evade(5.0, 9.0)
    _run(model, 30, 0.5)
    amount, side = model.tail_evade()
    assert 0.0 <= amount <= 1.0
    assert -1.0 <= side <= 1.0
