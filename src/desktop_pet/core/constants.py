"""core.constants —— 全部枚举与常量的唯一来源（Single Source of Truth）。

**本模块禁止 import 任何图形界面（Qt/GUI）库。** 所有阈值 / 配色 / 尺寸 / 文案集中于此，
其它模块只能引用，不得散落硬编码（架构 §9.2 硬性约定）。
"""

from __future__ import annotations

from enum import Enum, IntEnum, auto
from typing import Final

# --------------------------------------------------------------------------- #
# 1. 枚举定义
# --------------------------------------------------------------------------- #


class Mood(Enum):
    """四态情绪状态机（PRD §5）。"""

    IDLE = auto()
    FOCUS = auto()
    REST = auto()
    SLEEP = auto()


class Expression(Enum):
    """8 种表情（PRD §3.3.1 / §4.5 / FR-11）。"""

    HAPPY = auto()
    FOCUS = auto()
    SLEEPY = auto()
    SURPRISED = auto()
    SULKY = auto()
    YAWN = auto()
    SLEEPING = auto()
    EXCITED = auto()


class Gesture(IntEnum):
    """鼠标 / 唤醒手势（UI → Controller 传递用）。

    使用 IntEnum 便于通过 ``Signal(int)`` 跨 Qt 信号传递。
    """

    NONE = 0
    CLICK = 1
    HOVER = 2
    DRAG = 3
    WAKE = 4


class KeystrokeOutcome(IntEnum):
    """单次按键的聚合判定结果分类。"""

    NORMAL = 0
    HIGH_FREQUENCY = 1
    BURST_START = 2
    BURST_END = 3


# --------------------------------------------------------------------------- #
# 2. 时间阈值（单位：秒，除非显式标注 ms）
# --------------------------------------------------------------------------- #
HIGH_FREQ_WINDOW_MS: Final[float] = 300.0   # 高频判定滚动窗口（ms）  FR-03
HIGH_FREQ_THRESHOLD: Final[int] = 3         # 窗口内 >=3 次判定高频      FR-03
IDLE_START_S: Final[float] = 20.0           # 空闲态起始（无输入 20s）  FR-06
REST_THRESHOLD_S: Final[float] = 120.0      # 休息态阈值（>=120s）      FR-08
SLEEP_THRESHOLD_S: Final[float] = 300.0     # 睡觉态阈值（>=300s）      FR-09
MIN_DWELL_S: Final[float] = 5.0             # 最小驻留防抖（>=5s）      PRD §5
WAKE_SULKY_S: Final[float] = 3.0            # 唤醒后委屈表情时长        FR-09
EXCITED_THRESHOLD_S: Final[float] = 5.0     # 专注态连续高频累计→兴奋   FR-12
SLEEPY_REST_S: Final[float] = 30.0          # 休息态持续 >=30s→犯困     FR-12
SURPRISED_IDLE_S: Final[float] = 120.0      # 长空闲后单次敲键→惊讶     FR-12

# 生命体征 / 周期动画
BLINK_MIN_S: Final[float] = 3.0             # 眨眼间隔下限              FR-14
BLINK_MAX_S: Final[float] = 6.0             # 眨眼间隔上限              FR-14
BLINK_DURATION_S: Final[float] = 0.15       # 单次眨眼时长
BREATH_PERIOD_S: Final[float] = 3.0         # 呼吸周期                  FR-14
TAIL_MIN_S: Final[float] = 2.0              # 尾巴摆动周期下限          FR-13
TAIL_MAX_S: Final[float] = 4.0              # 尾巴摆动周期上限          FR-13
EAR_TWITCH_MIN_S: Final[float] = 4.0        # 耳朵抖动间隔下限          FR-13
EAR_TWITCH_MAX_S: Final[float] = 9.0        # 耳朵抖动间隔上限          FR-13
LOOK_AROUND_PERIOD_S: Final[float] = 6.0    # 空闲左右张望周期          FR-06
YAWN_MIN_S: Final[float] = 15.0             # 呵欠间隔下限              FR-12
YAWN_MAX_S: Final[float] = 30.0             # 呵欠间隔上限              FR-12

# 交互
HOVER_TRIGGER_S: Final[float] = 1.0         # 悬停抚摸触发时长          FR-28
CLICK_ANIM_S: Final[float] = 1.5            # 点击弹跳动画时长          FR-27
DRAG_THRESHOLD_PX: Final[int] = 5           # 拖动判定像素阈值          FR-18
BUBBLE_MIN_GAP_S: Final[float] = 3.0        # 相邻气泡最小间隔          FR-30

# 临时动作时长
TEMP_EXPRESSION_S: Final[float] = 2.0       # 默认临时表情时长
SURPRISED_ANIM_S: Final[float] = 1.2        # 惊讶表情时长

# 敲键盘动画时间线（FR-02）——单次敲击拆为「落指 → 回弹」两段。
# 左右分工（最接近真实打字）：**活动侧落指**（arm_*_press / finger_*_curl），
# **非活动侧抬腕**（arm_*_lift）。抬腕在「落指阶段」即升到位 → 高频连打
# （间隔 < PRESS_DOWN_S）时抬腕依然可见，天然避开「被自己打断」的问题。
# 具体包络见 ``core.pet_model.PetModel._keystroke_envelope``。
PRESS_DOWN_S: Final[float] = 0.14           # 落指下压时长（30fps ≥4 帧） FR-02
PRESS_REBOUND_S: Final[float] = 0.18        # 回弹复位时长（30fps ≥5 帧） FR-02
PRESS_ANIM_S: Final[float] = PRESS_DOWN_S + PRESS_REBOUND_S  # 单次敲击总时长
PRESS_BODY_SQUASH: Final[float] = 0.04      # 敲击瞬间身体轻微下沉量    FR-02
PRESS_LIFT_PEAK: Final[float] = 1.0         # 抬腕通道峰值（非活动侧，0→1）
PRESS_CURL_PEAK: Final[float] = 1.0         # 手指弯曲通道峰值（活动侧，0→1）

# --------------------------------------------------------------------------- #
# 3. 帧率（FR-34）
# --------------------------------------------------------------------------- #
FPS_ACTIVE: Final[int] = 30
FPS_IDLE: Final[int] = 15
FPS_SLEEP: Final[int] = 8


def interval_for_fps(fps: int) -> int:
    """把帧率转换为 QTimer 的毫秒间隔（下限 1ms，避免除零/过密）。"""

    safe_fps = max(1, int(fps))
    return max(1, int(round(1000.0 / safe_fps)))


# --------------------------------------------------------------------------- #
# 4. 配色方案（PRD §4.2 全部 HEX）
# --------------------------------------------------------------------------- #
COLORS: Final[dict[str, str]] = {
    # —— 重构后配色（视觉基准：参考图「圆球团子猫 + 柔和全息彩虹 + 粗黑描边」）——
    "ink": "#141414",         # 近黑 主体粗描边 / 眼睛 / 嘴
    "blush": "#FFB3C7",       # 柔和粉 腮红
    "white": "#FFFFFF",       # 纯白 眼睛高光 / 前爪
    "mouse_body": "#3A3A3A",  # 深灰 鼠标仓体 / 键盘底座
    "mouse_hi": "#8A8A8A",    # 中灰 鼠标分割线 / 滚轮
    # —— 气泡相关（沿用，未改）——
    "bubble_bg": "#FFFDF8",   # 奶白 气泡底
    "bubble_text": "#7A5A42",  # 暖棕 气泡字
    "glow_yellow": "#FFD08A",  # 暖黄 专注/兴奋光晕
    "glow_blue": "#B9D4E8",   # 淡蓝 睡觉柔光
    # —— 兼容保留：ui.bubble 仍引用此描边色（色值集中定义在 core）——
    "warm_brown": "#8B6B4F",
}

# 主体「柔和全息彩虹」渐变（左上前额 → 右下身体前沿的对角线性渐变）。
# 低饱和、粉彩感，避免高饱和刺眼；供 ui.pet_renderer 构造 QLinearGradient。
BODY_GRADIENT_STOPS: Final[tuple[tuple[float, str], ...]] = (
    (0.00, "#A8E6A1"),  # 薄荷绿（左上 / 头顶）
    (0.25, "#FFF7A8"),  # 奶油黄
    (0.50, "#FFC7A0"),  # 暖橙
    (0.75, "#FFA8D5"),  # 粉
    (1.00, "#A8D8F0"),  # 天空蓝（右下 / 身体前沿）
)

# 主体粗黑描边宽度（scale=1.0 的逻辑像素；参考图为厚重卡通描边）。
OUTLINE_W: Final[float] = 3.2

# --------------------------------------------------------------------------- #
# 5. 尺寸 / 缩放（架构 §9.3）
# --------------------------------------------------------------------------- #
BASE_W: Final[int] = 160
BASE_H: Final[int] = 180
SCALES: Final[tuple[float, ...]] = (0.8, 1.0, 1.2)
DEFAULT_SCALE: Final[float] = 1.0
# 宠物本体锚点：本体底部中心对齐窗口底边中点（§9.3）
PET_ANCHOR_X: Final[float] = BASE_W / 2.0

# --------------------------------------------------------------------------- #
# 6. 配置常量（架构 §9.6）
# --------------------------------------------------------------------------- #
CONFIG_VERSION: Final[int] = 1
CONFIG_DIR_NAME: Final[str] = "desktop-pet"
CONFIG_FILE_NAME: Final[str] = "config.json"
LOG_FILE_NAME: Final[str] = "app.log"
DEFAULT_WINDOW_X: Final[int] = -1  # -1 = 自动（主屏右下角）
DEFAULT_WINDOW_Y: Final[int] = -1
DEFAULT_MARGIN_PX: Final[int] = 40  # 默认位置距主屏右下角内缩（A-03）

AUTOSTART_REG_PATH: Final[str] = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_REG_KEY: Final[str] = "DesktopPet"
APP_DISPLAY_NAME: Final[str] = "大圣喵酱"

# --------------------------------------------------------------------------- #
# 7. 动画平滑系数（帧率无关插值，架构 §9.4）
# --------------------------------------------------------------------------- #
POSE_SMOOTH_K: Final[float] = 9.0       # 姿态插值平滑系数
BREATH_AMPLITUDE_PX: Final[float] = 3.5  # 呼吸起伏幅度
TAIL_AMPLITUDE_DEG: Final[float] = 14.0  # 尾巴基础摆幅（度）
EAR_TWITCH_AMPLITUDE_DEG: Final[float] = 8.0  # 耳朵抖动幅度（度）
LOOK_AROUND_AMPLITUDE_PX: Final[float] = 3.0  # 左右张望瞳孔偏移幅度

# --------------------------------------------------------------------------- #
# 7b. 尾巴「避让」交互（鼠标靠近 / 触碰尾巴时的反应，FR-13 扩展）
# --------------------------------------------------------------------------- #
# 语义：光标与尾巴中心线的距离 → 避让强度 0→1（`NEAR_PX` 内为满强度，`FAR_PX` 外为 0）。
# 尾巴向光标的**反侧**摆开 `TAIL_EVADE_ANGLE_DEG × 强度`，同时轻微上收
# `TAIL_EVADE_CURL × 强度`（"警觉地一缩"）。
# 逼近用快系数、回落用慢系数（非对称）→ 产生「惊觉后缓缓放松」的余韵。
TAIL_EVADE_NEAR_PX: Final[float] = 9.0     # 判定为「碰到尾巴」的距离（逻辑像素）
TAIL_EVADE_FAR_PX: Final[float] = 40.0     # 超出该距离完全无反应
TAIL_EVADE_ANGLE_DEG: Final[float] = 30.0  # 最大侧向摆开角（度）
TAIL_EVADE_CURL: Final[float] = 0.42       # 最大上收量（叠加到 tail_curve）
TAIL_EVADE_ATTACK_K: Final[float] = 16.0   # 避让响应平滑系数（快）
TAIL_EVADE_RELEASE_K: Final[float] = 4.2   # 避让回落平滑系数（慢）

# 气泡时序（PRD §4.3）
BUBBLE_FADE_IN_S: Final[float] = 0.2
BUBBLE_FADE_OUT_S: Final[float] = 0.3
BUBBLE_MIN_DURATION_S: Final[float] = 2.0
BUBBLE_MAX_DURATION_S: Final[float] = 4.0

# 气泡几何（逻辑像素，PRD §4.3）
BUBBLE_CORNER_RADIUS: Final[float] = 8.0
BUBBLE_PAD_X: Final[float] = 10.0
BUBBLE_PAD_Y: Final[float] = 6.0
BUBBLE_MAX_WIDTH: Final[float] = 200.0
BUBBLE_FONT_SIZE: Final[int] = 12
BUBBLE_TAIL_W: Final[float] = 10.0
BUBBLE_TAIL_H: Final[float] = 7.0
BUBBLE_GAP_TO_PET: Final[float] = 6.0  # 气泡与头顶间距

# --------------------------------------------------------------------------- #
# 8. 表情 → 姿态模板（PRD §4.5 视觉差异表）
# --------------------------------------------------------------------------- #
# 每一表情在各姿态通道上的**增量**（相对中性姿态），未列出通道取中性值 0。
# 通道含义见 core.pet_model.PetPose 字段。
EXPRESSION_POSES: Final[dict[Expression, dict[str, float]]] = {
    # 开心：弯月眯眼、上扬笑弧、耳微前倾、尾巴大幅摆动、腮红加深
    Expression.HAPPY: {
        "eye_open_l": 0.12, "eye_open_r": 0.12, "eye_curve": 1.0,
        "mouth_curve": 0.9, "mouth_open": 0.05,
        "ear_l_tilt": 6.0, "ear_r_tilt": 6.0,
        "tail_curve": 0.9, "blush_alpha": 0.85,
    },
    # 专注：睁大圆眼、紧闭短线嘴、竖立耳、轻摆尾
    Expression.FOCUS: {
        "eye_open_l": 1.0, "eye_open_r": 1.0, "eye_curve": 0.0,
        "pupil_dilate": 0.35, "mouth_curve": 0.0, "mouth_open": 0.0,
        "ear_l_angle": -12.0, "ear_r_angle": -12.0,
        "ear_l_tilt": -4.0, "ear_r_tilt": -4.0,
        "tail_curve": 0.35, "blush_alpha": 0.35,
    },
    # 犯困：半闭下垂眼、小圆嘴、耳微耷拉、慢摆尾
    Expression.SLEEPY: {
        "eye_open_l": 0.35, "eye_open_r": 0.35, "eye_curve": -0.25,
        "mouth_curve": 0.15, "mouth_open": 0.12,
        "ear_l_angle": 18.0, "ear_r_angle": 18.0,
        "tail_curve": 0.25, "blush_alpha": 0.4,
        "body_y": 3.0, "head_y": 2.0,
    },
    # 惊讶：圆睁带高光、小○嘴、耳后仰、尾巴僵直、身体后仰
    Expression.SURPRISED: {
        "eye_open_l": 1.25, "eye_open_r": 1.25, "eye_curve": 0.0,
        "pupil_dilate": 0.8, "mouth_curve": 0.1, "mouth_open": 0.85,
        "ear_l_angle": -22.0, "ear_r_angle": -22.0,
        "tail_curve": 0.0, "head_tilt": 0.0,
        "body_y": -4.0, "head_y": -2.0,
    },
    # 委屈：上缘下弯眼、波浪嘴、耳完全耷拉、尾下垂不摆、眼角水光
    Expression.SULKY: {
        "eye_open_l": 0.5, "eye_open_r": 0.5, "eye_curve": -0.9,
        "mouth_curve": -0.7, "mouth_open": 0.1,
        "ear_l_angle": 32.0, "ear_r_angle": 32.0,
        "ear_l_tilt": 10.0, "ear_r_tilt": 10.0,
        "tail_curve": 0.05, "tail_angle": 20.0, "tear_alpha": 0.9,
        "blush_alpha": 0.3, "body_y": 4.0, "head_y": 3.0,
    },
    # 打呵欠：闭眼、大张○嘴（带舌）、耳后压、尾僵直、身体上提拉伸
    Expression.YAWN: {
        "eye_open_l": 0.0, "eye_open_r": 0.0, "eye_curve": 1.0,
        "mouth_curve": 0.0, "mouth_open": 1.0, "tongue_show": 0.7,
        "ear_l_angle": -8.0, "ear_r_angle": -8.0,
        "tail_curve": 0.0, "body_y": -6.0, "body_squash": -0.12,
        "head_y": -4.0, "blush_alpha": 0.3,
    },
    # 睡觉：闭眼弧线、小~嘴、耳耷拉、尾蜷起、ZZZ、淡蓝光、呼吸起伏
    Expression.SLEEPING: {
        "eye_open_l": 0.0, "eye_open_r": 0.0, "eye_curve": 1.0,
        "mouth_curve": 0.1, "mouth_open": 0.0,
        "ear_l_angle": 30.0, "ear_r_angle": 30.0,
        "tail_curve": 1.0, "tail_angle": 150.0,
        "blush_alpha": 0.35, "zzz_alpha": 0.9, "glow_alpha": 0.5,
        "body_y": 5.0, "body_squash": 0.06, "head_y": 4.0,
    },
    # 兴奋：星形睁大眼、大张笑、耳竖立抖动、尾高速摆动、暖黄光晕
    Expression.EXCITED: {
        "eye_open_l": 1.35, "eye_open_r": 1.35, "eye_curve": 0.6,
        "pupil_dilate": 0.6, "mouth_curve": 1.0, "mouth_open": 0.75,
        "ear_l_angle": -16.0, "ear_r_angle": -16.0,
        "tail_curve": 1.0, "blush_alpha": 0.9, "glow_alpha": 0.75,
        "body_y": -3.0, "head_y": -2.0,
    },
}

# 中性姿态（Idle 常态）基线值
NEUTRAL_POSE: Final[dict[str, float]] = {
    "body_y": 0.0,
    "body_squash": 0.0,
    "head_y": 0.0,
    "head_tilt": 0.0,
    "look_x": 0.0,
    "look_y": 0.0,
    "eye_open_l": 1.0,
    "eye_open_r": 1.0,
    "eye_curve": 0.4,
    "pupil_dilate": 0.2,
    "mouth_curve": 0.4,
    "mouth_open": 0.0,
    "tongue_show": 0.0,
    "ear_l_angle": 0.0,
    "ear_r_angle": 0.0,
    "ear_l_tilt": 0.0,
    "ear_r_tilt": 0.0,
    "arm_l_press": 0.0,
    "arm_r_press": 0.0,
    "arm_l_lift": 0.0,
    "arm_r_lift": 0.0,
    "finger_l_curl": 0.0,
    "finger_r_curl": 0.0,
    "arm_dangle": 0.0,
    "tail_angle": 0.0,
    "tail_curve": 0.5,
    "blush_alpha": 0.6,
    "glow_alpha": 0.0,
    "tear_alpha": 0.0,
    "zzz_alpha": 0.0,
}

# --------------------------------------------------------------------------- #
# 9. 气泡台词（PRD §5 台词表，按表情分组）
# --------------------------------------------------------------------------- #
BUBBLE_TEXTS: Final[dict[Expression | Mood, list[str]]] = {
    Expression.HAPPY: ["嘿嘿，摸摸头~", "好开心！(≧▽≦)", "被你摸到啦~"],
    Expression.FOCUS: ["一起加油！💪", "你敲得真快！", "我陪你一起努力~"],
    Expression.EXCITED: ["哇！好快好快！", "冲鸭！٩(๑>◡<๑)۶", "状态拉满！"],
    Expression.SLEEPY: ["有点困了呢…", "歇一会儿吧~", "要不要喝口水？"],
    Expression.SURPRISED: ["咦？你回来啦！", "吓我一跳！", "突然冒出来~"],
    Expression.SULKY: ["唔…打扰我做梦了…", "哼，人家还没睡够…", "轻一点啦…"],
    Expression.YAWN: ["哈啊~ 好困…", "该休息啦~", "打个大大的呵欠~"],
    Expression.SLEEPING: ["Zzz…", "嘘，我在做梦呢~"],
    Mood.IDLE: ["需要我陪着你吗？", "我在呢~", "要不要摸摸我呀？"],
    Mood.REST: ["歇一会儿吧~", "要不要喝口水？", "揉揉眼睛继续加油~"],
    Mood.SLEEP: ["Zzz…", "嘘，我在做梦呢~"],
}

# 托盘提示 / 通知文案
TRAY_TOOLTIP: Final[str] = f"{APP_DISPLAY_NAME} · 桌面宠物"
BUBBLE_MAX_WIDTH_PX: Final[float] = BUBBLE_MAX_WIDTH

__all__ = [
    "Mood",
    "Expression",
    "Gesture",
    "KeystrokeOutcome",
    "COLORS",
    "EXPRESSION_POSES",
    "NEUTRAL_POSE",
    "BUBBLE_TEXTS",
    "interval_for_fps",
]
