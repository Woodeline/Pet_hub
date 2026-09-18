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
SURPRISED_IDLE_S: Final[float] = 120.0      # 长空闲后单次敲键→惊讶     FR-12

# 生命体征 / 周期动画
BLINK_MIN_S: Final[float] = 3.0             # 眨眼间隔下限              FR-14
BLINK_MAX_S: Final[float] = 6.0             # 眨眼间隔上限              FR-14
BLINK_DURATION_S: Final[float] = 0.15       # 单次眨眼时长
#: 右眼相对左眼的眨眼相位延迟（秒）——制造「不对称眨眼」的生命感（阶段 A5-3）。
#: 必须 < ``BLINK_DURATION_S`` 的一半（0.075），否则两眼会跨过 `_draw_eye` 的
#: ``openness < 0.18`` 弧线眼阈值、视觉上像「两种眼睛」。
BLINK_EYE_DELAY_S: Final[float] = 0.05
BREATH_PERIOD_S: Final[float] = 3.0         # 呼吸周期                  FR-14
#: 呼吸周期抖动幅度（±比例）——回绕时以 ``BREATH_PERIOD_S * (1 ± J)`` 重抽周期（阶段 A5-1）。
#: ``BREATH_PERIOD_S`` 本身是 PRD 锁定值，**不动**；抖动只作用于每次回绕后的重抽。
BREATH_JITTER: Final[float] = 0.10
TAIL_MIN_S: Final[float] = 2.0              # 尾巴摆动周期下限          FR-13
TAIL_MAX_S: Final[float] = 4.0              # 尾巴摆动周期上限          FR-13
EAR_TWITCH_MIN_S: Final[float] = 4.0        # 耳朵抖动间隔下限          FR-13
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

# 偶发小动作（阶段 A5-2）——间隔区间（秒）与单次动作时长（秒）
SURPRISE_MIN_S: Final[float] = 40.0
SURPRISE_MAX_S: Final[float] = 80.0
SURPRISE_DURATION_S: Final[float] = 1.2

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
    # —— 日语学习：学习泡泡次级文字色 + 生词本窗口配色（设计 §7.4）——
    "bubble_sub_text": "#9C8570",   # 暖灰 假名（次级文字）
    "bubble_faint_text": "#B7A99A",  # 淡褐 中文释义（最淡文字）
    "vocab_bg": "#FFFDF8",          # 奶白 生词本窗口底色
    "vocab_text": "#5A4636",        # 深棕 生词本正文文字
    "vocab_level_tag": "#7A9E7E",   # 灰绿 生词本等级标签色
    # —— 日语记忆（JP-17+）：学习泡泡高光 / 按钮条 / 记录窗口状态标签（设计 §7.3）——
    "bubble_gradient_hi": "#FFFFFF",       # 学习泡泡 body 顶部浅高光（质感）
    "jp_button_primary_bg": "#7A9E7E",     # 「记住了」主色填充（正向绿）
    "jp_button_primary_text": "#FFFFFF",   # 「记住了」文字
    "jp_button_primary_hover": "#8FB090",  # 主按钮悬停
    "jp_button_primary_pressed": "#6B8E6F",  # 主按钮按下
    "jp_button_secondary_border": "#9C8570",  # 「新单词」描边
    "jp_button_secondary_text": "#7A5A42",    # 「新单词」文字
    "jp_button_secondary_hover": "#F3EAE0",   # 次按钮悬停填充
    "jp_button_bar_bg": "#FFFDF8",             # 按钮条底色
    "log_status_mastered": "#7A9E7E",     # 状态标签·已掌握（绿）
    "log_status_vocab": "#5B8DB8",        # 状态标签·生词（蓝）
    "log_status_unprocessed": "#B7A99A",  # 状态标签·未处理（灰）
    # —— B 版气泡质感 / 等级角标（设计 §A1.1）——
    "bubble_shadow": "#C9B8A6",           # 气泡底部柔和阴影（绘制时用低 alpha）
    "bubble_divider": "#EFE3D4",          # 气泡「单词/假名」与「翻译/释义」分割线
    "bubble_gradient_bottom": "#F7EEDF",  # 气泡 body 底部渐变略深
    "jp_level_chip_bg": "#7A9E7E",        # 右上角等级 chip 背景
    "jp_level_chip_text": "#FFFFFF",      # 右上角等级 chip 文字
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

# 道具（键盘 / 鼠标）描边色（阶段 B1-3 / G1）——比主体 ink（#141414）略浅，
# 使「道具」与「猫主体」形成一层**描边层级差**（前景猫更重、道具略退）。
# 独立标量模块级常量（照 ``OUTLINE_W`` 先例），**不新增字典键**（避免动 COLORS 全等断言）。
PROP_OUTLINE: Final[str] = "#4A4A4A"

# --------------------------------------------------------------------------- #
# 4c. 主题皮肤渐变表（阶段 A）—— 四季自动换肤 + 节日手动
# --------------------------------------------------------------------------- #
# 每套皮肤 = **5 个停靠点**（位置严格 ``0.0 / 0.25 / 0.5 / 0.75 / 1.0``），色值一律 ``#RRGGBB``。
# 渐变方向与主体一致（左上前额 → 右下身体前沿）。所有皮肤为**低饱和粉彩**，
# 同一色相家族「由亮到深」推进，避免高饱和刺眼。
#
# ``default`` **直接引用** ``BODY_GRADIENT_STOPS`` **对象本身**（不是复制字面量）——
# 这样阶段 B 对默认彩虹降饱和时只需改一处，默认皮肤自动跟随。
#
# 本段为纯加法：``COLORS`` / ``BODY_GRADIENT_STOPS`` / ``OUTLINE_W`` 一字未动。
DEFAULT_THEME: Final[str] = "default"
AUTO_THEME: Final[str] = "auto"

THEMES: Final[dict[str, tuple[tuple[float, str], ...]]] = {
    # 默认：品牌柔和全息彩虹（引用既有对象）
    "default": BODY_GRADIENT_STOPS,
    # 春：新芽嫩绿 → 深叶绿
    "spring": (
        (0.00, "#E8F5DC"),
        (0.25, "#CFEAB8"),
        (0.50, "#B2DE96"),
        (0.75, "#93CE79"),
        (1.00, "#74BC60"),
    ),
    # 夏：晴空浅蓝 → 深海蓝
    "summer": (
        (0.00, "#DCEFF7"),
        (0.25, "#B8DFF0"),
        (0.50, "#92CBE6"),
        (0.75, "#6BB5D9"),
        (1.00, "#4A9DC6"),
    ),
    # 秋：暖米 → 枫橙
    "autumn": (
        (0.00, "#FBE7CC"),
        (0.25, "#F5CE9E"),
        (0.50, "#EDB270"),
        (0.75, "#DE9349"),
        (1.00, "#C4762E"),
    ),
    # 冬：雪青白 → 冷靛蓝
    "winter": (
        (0.00, "#EAF1FA"),
        (0.25, "#CBDCEE"),
        (0.50, "#A8C4E0"),
        (0.75, "#84A9CF"),
        (1.00, "#628DBD"),
    ),
    # 春节：桃粉 → 喜庆深红
    "spring_festival": (
        (0.00, "#FBD9DE"),
        (0.25, "#F5B0BC"),
        (0.50, "#EC8698"),
        (0.75, "#DB5D74"),
        (1.00, "#C23A55"),
    ),
    # 圣诞：松针浅绿 → 深松绿
    "christmas": (
        (0.00, "#D6EFE0"),
        (0.25, "#AEDBC0"),
        (0.50, "#82C29E"),
        (0.75, "#57A67C"),
        (1.00, "#2F875C"),
    ),
}

#: 主题取值 → 中文显示名（含 ``auto``；供托盘菜单与配置展示使用）。
THEME_NAMES: Final[dict[str, str]] = {
    "default": "默认",
    "spring": "春",
    "summer": "夏",
    "autumn": "秋",
    "winter": "冬",
    "spring_festival": "春节",
    "christmas": "圣诞",
    "auto": "自动",
}

#: 月份 → 季节皮肤（**仅四季**；节日皮肤只由用户手动选择，见 v1.1 §2.2 G4 决策 a）。
#: 覆盖 1..12 全部月份，值均为 :data:`THEMES` 的键。
THEME_SEASON_MAP: Final[dict[int, str]] = {
    1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
    12: "winter",
}

#: 合法主题取值集合：7 套皮肤 + ``auto``（供 ``AppConfig`` 白名单校验）。
THEME_ALLOWED: Final[frozenset[str]] = frozenset(THEMES) | {AUTO_THEME}

#: 托盘「主题」子菜单标题。
TRAY_MENU_THEME: Final[str] = "主题"

#: 主题重估间隔（毫秒）：每日一次（配合 app 层跨日检测，跨月零点自动换肤）。
THEME_RECHECK_MS: Final[int] = 24 * 60 * 60 * 1000

# --------------------------------------------------------------------------- #
# 4b. Design Token（UI 视觉升级 P0）—— 语义色 / 间距 / 字号 / 圆角
# --------------------------------------------------------------------------- #
# 说明：本段为**纯加法**（新字典），**不修改**上方 ``COLORS`` / ``BODY_GRADIENT_STOPS`` /
# ``OUTLINE_W`` 的任何键值（``test_color_palette_matches_prd`` 为 ``==`` 全等断言）。
# ``SEMANTIC_COLORS`` 是面向组件的**语义层**：UI 组件只引用语义名（primary / success …），
# 由语义名到具体色值的映射集中在此，未来换肤只改这一处。其值与既有 ``COLORS`` 保持映射
# 关系（见 ``tests/test_design_tokens.py``），保证渐变过程「改色不改结构」。
#
# P0 只沉淀 token；把它翻译成 QSS / QIcon 由 P1 的 ``ui.theme`` / ``ui.icon_factory`` 负责。
SEMANTIC_COLORS: Final[dict[str, str]] = {
    "primary": "#7A5A42",        # 品牌主色（暖棕，= 气泡正文色）
    "primary_hover": "#8B6B4F",  # 悬停 +8%
    "primary_pressed": "#6B4E3A",# 按下 -8%
    "success": "#7A9E7E",        # 正向操作（「记住了」）
    "success_hover": "#8FB090",
    "success_pressed": "#6B8E6F",
    "info": "#5B8DB8",           # 信息/已掌握状态
    "warning": "#C99A5B",        # 生词状态（从「蓝」改为琥珀，与 info 解耦）
    "muted": "#B7A99A",          # 未处理/辅助
    "destructive": "#C05B5B",    # 危险操作（清空）
    "destructive_hover": "#CE6B6B",
    "surface": "#FFFDF8",        # 卡片/窗口底
    "surface_alt": "#F7EEDF",    # 斑马纹/次级底
    "border": "#EFE3D4",         # 边框
    "text_primary": "#5A4636",   # 正文
    "text_secondary": "#9C8570", # 次级
    "text_faint": "#B7A99A",     # 最淡
}

# 间距刻度（4px 基线：``xs``/``md`` 为 4 的倍数，``sm``/``lg``/``xl`` 命中 8 的倍数）。
SPACING: Final[dict[str, int]] = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}

# 字号刻度（``display > title > body > caption > small`` 严格单调递减）。
FONT_SIZE: Final[dict[str, int]] = {
    "display": 24, "title": 16, "body": 12, "caption": 11, "small": 9,
}

# 圆角刻度（``pill`` 用于胶囊/药丸形控件）。
RADIUS: Final[dict[str, int]] = {"sm": 6, "md": 8, "lg": 12, "pill": 16}

# --------------------------------------------------------------------------- #
# 5. 尺寸 / 缩放（架构 §9.3）
# --------------------------------------------------------------------------- #
BASE_W: Final[int] = 160
BASE_H: Final[int] = 180
SCALES: Final[tuple[float, ...]] = (0.8, 1.0, 1.2)
DEFAULT_SCALE: Final[float] = 1.0

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
# 尾巴沿「远离光标」的方向整体让开 `TAIL_EVADE_MAX_PX × 强度`：根部权重恒为 0
# （永远长在身体上），越靠尾尖让得越多（权重 1）。
#
# 为什么不做"绕根部转一个角度"：尾巴是弯的，刚性旋转下各点只能沿切线移动，
# 光标落在径向或斜上方时会越躲越近（实测 5 个方位里 4 个 Δ 为负）。沿
# 「光标 → 尾巴重心」的反方向位移，则任意方位都至少不会靠近，形状也不乱。
# 逼近用快系数、回落用慢系数（非对称）→ 产生「惊觉后缓缓放松」的余韵。
TAIL_EVADE_NEAR_PX: Final[float] = 9.0     # 判定为「碰到尾巴」的距离（逻辑像素）
TAIL_EVADE_FAR_PX: Final[float] = 40.0     # 超出该距离完全无反应
TAIL_EVADE_MAX_PX: Final[float] = 16.0     # 尾尖最大让开距离（逻辑像素）
TAIL_EVADE_RAMP_P: Final[float] = 2.0      # 位移沿脊线的分配指数（越大 → 越集中在尾尖）
TAIL_EVADE_LIFT: Final[float] = 0.35       # 逃离方向的上翘偏置（只在光标不在上方时施加）
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

# --------------------------------------------------------------------------- #
# 8b. 偶发小动作 → 姿态增量表（阶段 A5-2）
# --------------------------------------------------------------------------- #
# 每种小动作 = 一组**姿态增量**（相对当前目标姿态叠加），仅使用既有姿态通道
# （body_y / body_squash / head_tilt / ear_*_tilt / tail_angle / tail_curve / look_x / look_y）。
# 键为 :class:`desktop_pet.core.pet_model.SurpriseKind` 的**成员名**（字符串）——
# constants 不能 import pet_model（会形成循环依赖），故以 ``.name`` 为键；pet_model 侧
# 用 ``SurpriseKind.name`` 查表。增量会被 ``motion.surprise_envelope`` 包络加权。
SURPRISE_POSES: Final[dict[str, dict[str, float]]] = {
    # 伸懒腰：身体上提拉伸、耳朵前倾、尾巴上抬
    "STRETCH": {
        "body_y": -5.0, "body_squash": -0.10,
        "ear_l_tilt": -3.0, "ear_r_tilt": -3.0,
        "tail_angle": -8.0, "tail_curve": 0.15,
    },
    # 甩尾：尾巴快速摆一下、视线微偏
    "TAIL_FLICK": {
        "tail_angle": 22.0, "tail_curve": 0.5, "look_x": -2.0,
    },
    # 抖耳：两耳一高一低抖动、头部微倾
    "EAR_FLICK": {
        "ear_l_tilt": -12.0, "ear_r_tilt": 9.0, "head_tilt": 3.0,
    },
    # 看角落：瞳孔与头一起偏向一角
    "GLANCE_CORNER": {
        "look_x": 3.0, "look_y": -2.0, "head_tilt": -4.0,
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

# —— 托盘通用菜单文案（减少动效开关：对应 prefers-reduced-motion）——
TRAY_MENU_REDUCE_MOTION: Final[str] = "减少动效"
TRAY_MENU_REDUCE_MOTION_TIP: Final[str] = "关闭窗口淡入淡出与加载动画，对动效敏感时更友好"
TRAY_NOTIFY_REDUCE_MOTION_ON: Final[str] = "已开启「减少动效」"
TRAY_NOTIFY_REDUCE_MOTION_OFF: Final[str] = "已关闭「减少动效」"

# --------------------------------------------------------------------------- #
# 10. 日语学习（JP-01~JP-16）—— 难度 / 节奏 / 排版 / 文件 / 文案
# --------------------------------------------------------------------------- #
# —— 难度等级（由易到难，有序元组；与词库 level / 配置 jp_level 统一口径）——
JP_LEVELS: Final[tuple[str, ...]] = ("N5", "N4", "N3", "N2", "N1")
JP_DEFAULT_LEVEL: Final[str] = "N5"
#: 等级 → 菜单/筛选显示文案（当前与等级同文字，保留为字典以便未来扩展描述）
JP_LEVEL_LABELS: Final[dict[str, str]] = {level: level for level in JP_LEVELS}

# —— 出现节奏（独立随机间隔，挂在既有帧循环上，不新开 QTimer）——
JP_WORD_MIN_INTERVAL_S: Final[float] = 25.0
JP_WORD_MAX_INTERVAL_S: Final[float] = 50.0

# —— 学习泡泡排版（四行多字号，固定内容宽度保证「测量换行宽 == 绘制换行宽」）——
JP_BUBBLE_WORD_FONT_SIZE: Final[int] = 16          # 日语单词（加粗）
JP_BUBBLE_KANA_FONT_SIZE: Final[int] = 12          # 假名读音
JP_BUBBLE_TRANSLATION_FONT_SIZE: Final[int] = 11   # 中文翻译
JP_BUBBLE_MEANING_FONT_SIZE: Final[int] = 9        # 中文释义
JP_BUBBLE_MAX_WIDTH: Final[float] = 240.0          # 学习泡泡固定内容宽度
JP_BUBBLE_FONT_FAMILY: Final[str] = "Microsoft YaHei"
BUBBLE_LINE_SPACING: Final[float] = 3.0            # 多行泡泡行距（PRD 原命名，不加 JP 前缀）

# —— 词库 / 生词本文件与版本 ——
WORD_BANK_DIR_NAME: Final[str] = "data"
WORD_BANK_FILE_NAME: Final[str] = "jlpt_words.json"
WORD_BANK_VERSION: Final[int] = 1
VOCAB_FILE_NAME: Final[str] = "vocabulary.json"
VOCAB_VERSION: Final[int] = 1

# —— 生词本窗口尺寸 ——
VOCAB_WINDOW_W: Final[int] = 440
VOCAB_WINDOW_H: Final[int] = 360

# —— 托盘菜单文案 ——
JP_MENU_TITLE: Final[str] = "日语学习"
JP_MENU_LEVEL: Final[str] = "难度"
JP_MENU_VOCAB: Final[str] = "生词本…"

# —— 托盘通知文案（JP_NOTIFY_REMEMBER_ADDED 用 str.format(word=..., kana=...)）——
JP_NOTIFY_REMEMBER_ADDED: Final[str] = "已加入生词本：{word}（{kana}）"
JP_NOTIFY_REMEMBER_DUPLICATE: Final[str] = "已在生词本中"
JP_NOTIFY_NEED_BUBBLE: Final[str] = "已开启日语学习～先打开「气泡提示」，单词才会显示哦"
JP_NOTIFY_BANK_UNAVAILABLE: Final[str] = "日语词库不可用，已跳过日语单词展示"

# —— 生词本窗口文案 ——
JP_VOCAB_WINDOW_TITLE: Final[str] = "生词本"
JP_VOCAB_FILTER_ALL: Final[str] = "全部"
JP_VOCAB_LEVEL_FILTER_LABEL: Final[str] = "等级："
JP_VOCAB_COL_WORD: Final[str] = "单词"
JP_VOCAB_COL_KANA: Final[str] = "假名"
JP_VOCAB_COL_TRANSLATION: Final[str] = "翻译"
JP_VOCAB_COL_LEVEL: Final[str] = "等级"
JP_VOCAB_BTN_REMOVE: Final[str] = "删除选中"
JP_VOCAB_BTN_CLEAR: Final[str] = "清空…"
JP_VOCAB_BTN_CLOSE: Final[str] = "关闭"
JP_VOCAB_EMPTY_TEXT: Final[str] = "还没有生词哦～ 打开「日语学习」后，把想记的单词加进来吧"
JP_VOCAB_STATUS_TEMPLATE: Final[str] = "共 {count} 个生词"
JP_VOCAB_CLEAR_CONFIRM_TITLE: Final[str] = "清空生词本"
JP_VOCAB_CLEAR_CONFIRM_TEXT: Final[str] = "确定要清空全部生词吗？此操作不可撤销。"

# --------------------------------------------------------------------------- #
# 11. 日语记忆（JP-17+）—— 时长 / 上限 / 权重 / 三态 / 文件 / 按钮条 / 托盘 / 记录窗口
# --------------------------------------------------------------------------- #
# —— 学习泡泡时长（档位枚举 {15,30,60}，默认 30；MIN/MAX 仅作 UI 展示安全钳制，见设计 §A5.1）——
JP_BUBBLE_DURATION_S: Final[int] = 30
JP_BUBBLE_DURATION_OPTIONS: Final[tuple[int, ...]] = (15, 30, 60)
JP_BUBBLE_DURATION_LABELS: Final[dict[int, str]] = {15: "15 秒", 30: "30 秒", 60: "60 秒"}
JP_BUBBLE_MIN_DURATION_S: Final[float] = 2.0
JP_BUBBLE_MAX_DURATION_S: Final[float] = 300.0

# —— 每日展示上限（档位枚举 {5,10,15,20,30}，默认 15）与生词加权抽取 ——
JP_DAILY_LIMIT: Final[int] = 15
JP_DAILY_LIMIT_OPTIONS: Final[tuple[int, ...]] = (5, 10, 15, 20, 30)
JP_DAILY_LIMIT_LABELS: Final[dict[int, str]] = {
    5: "5 个", 10: "10 个", 15: "15 个", 20: "20 个", 30: "30 个",
}
JP_VOCAB_WEIGHT: Final[float] = 3.0

# —— 已掌握集合 / 每日记录 文件与版本 ——
MASTERED_FILE_NAME: Final[str] = "mastered.json"
MASTERED_VERSION: Final[int] = 1
DAILY_LOG_FILE_NAME: Final[str] = "daily_log.json"
DAILY_LOG_VERSION: Final[int] = 1

# —— 每日记录三态（一次展示恰好落一种终态；与设计 §7.6 一致）——
DAILY_LOG_STATUS_MASTERED: Final[str] = "mastered"
DAILY_LOG_STATUS_VOCAB: Final[str] = "vocab"
DAILY_LOG_STATUS_UNPROCESSED: Final[str] = "unprocessed"
DAILY_LOG_STATUSES: Final[tuple[str, ...]] = (
    DAILY_LOG_STATUS_MASTERED,
    DAILY_LOG_STATUS_VOCAB,
    DAILY_LOG_STATUS_UNPROCESSED,
)

# —— 气泡按钮条（几何 / 文案 / 字号，见设计 §3.1）——
JP_BUTTON_MASTERED: Final[str] = "记住了"
JP_BUTTON_VOCAB: Final[str] = "新单词"
JP_BUTTON_RADIUS: Final[int] = 16
JP_BUTTON_PAD_X: Final[int] = 14
JP_BUTTON_PAD_Y: Final[int] = 8
JP_BUTTON_BAR_GAP_PX: Final[int] = 6
JP_BUTTON_BAR_PAD: Final[int] = 6
JP_BUTTON_FONT_SIZE: Final[int] = 12

# —— 托盘菜单文案（B 版：显示时长 / 每日数量 / 立即显示）——
JP_MENU_LOG: Final[str] = "学习记录…"
JP_MENU_DURATION: Final[str] = "显示时长"
JP_MENU_DAILY_LIMIT: Final[str] = "每日数量"
JP_MENU_SHOW_NOW: Final[str] = "立即显示一个新单词"

# —— 记忆闭环通知文案（str.format(word=..., kana=...)）——
JP_NOTIFY_MASTERED_ADDED: Final[str] = "已标记为掌握：{word}（{kana}）"
JP_NOTIFY_MASTERED_DUPLICATE: Final[str] = "这个单词已经掌握啦"
JP_NOTIFY_LEVEL_DONE: Final[str] = "该等级单词已全部掌握，切换难度继续学习吧~"
JP_NOTIFY_TODAY_DONE: Final[str] = "今日学习完成，明天继续加油！"
JP_NOTIFY_SHOW_NOW: Final[str] = "已立即显示：{word}（{kana}）"
JP_NOTIFY_SHOW_NOW_BLOCKED: Final[str] = "现在还不能显示新单词哦～"
# —— 手动「立即显示」不受每日上限约束（用户决策）；以下为手动路径专用反馈文案 ——
# 每次手动点击都必须给出可见反馈，严禁静默返回（历史缺陷：与自动路径共用一次性标志位）。
JP_NOTIFY_SHOW_NOW_OVER_LIMIT: Final[str] = (
    "已立即显示：{word}（{kana}）｜今日已完成 {count}/{limit}，已超出今日目标"
)
JP_NOTIFY_POOL_EXHAUSTED: Final[str] = "{level} 的词都学完了，换个难度试试～"
JP_NOTIFY_JP_OFF: Final[str] = "请先开启「日语学习」哦～"
JP_NOTIFY_SHOW_NOW_FAILED: Final[str] = "显示单词时出错了，请稍后重试"

# —— 学习记录窗口文案 / 尺寸 ——
JP_LOG_WINDOW_TITLE: Final[str] = "学习记录"
JP_LOG_WINDOW_W: Final[int] = 560
JP_LOG_WINDOW_H: Final[int] = 420
JP_LOG_DATE_LABEL: Final[str] = "日期："
JP_LOG_STATUS_LABEL: Final[str] = "状态："
JP_LOG_FILTER_ALL: Final[str] = "全部"
JP_LOG_STATUS_MASTERED: Final[str] = "已掌握"
JP_LOG_STATUS_VOCAB: Final[str] = "生词"
JP_LOG_STATUS_UNPROCESSED: Final[str] = "未处理"
JP_LOG_COL_WORD: Final[str] = "单词"
JP_LOG_COL_KANA: Final[str] = "假名"
JP_LOG_COL_TRANSLATION: Final[str] = "翻译"
JP_LOG_COL_SHOWN_AT: Final[str] = "展示时间"
JP_LOG_COL_STATUS: Final[str] = "状态"
JP_LOG_EMPTY_TEXT: Final[str] = "这一天还没有学习记录哦～"
JP_LOG_STATUS_TEMPLATE: Final[str] = (
    "当日 {shown}/{limit} 条 · 已掌握 {mastered} · 生词 {vocab} · 未处理 {unprocessed}"
)

# --------------------------------------------------------------------------- #
# 12. 单词详情（B 版 JC-*）—— 窗口
# --------------------------------------------------------------------------- #
# —— 单词详情窗口（尺寸 / 基础字段标签 / 通用按钮）——
# 说明：详情窗口已重写为「纯中文五要素」（见 §13），此处仅保留窗口几何、
# 基础字段标签与通用按钮文案。
WORD_DETAIL_WINDOW_TITLE: Final[str] = "单词详情"
WORD_DETAIL_WINDOW_W: Final[int] = 420
WORD_DETAIL_WINDOW_H: Final[int] = 560
WORD_DETAIL_LABEL_KANA: Final[str] = "假名"
WORD_DETAIL_RETRY: Final[str] = "重试"
WORD_DETAIL_CLOSE: Final[str] = "关闭"
WORD_DETAIL_NO_VALUE: Final[str] = "—"

# --------------------------------------------------------------------------- #
# 13. 中文详情五要素 / 用户缓存 / DeepSeek 联网（增量改造）
# --------------------------------------------------------------------------- #
# —— 五要素字段键名（与 JSON 契约严格一致，唯一来源）——
WORD_DETAIL_FIELD_MEANING: Final[str] = "meaning_zh"       # 中文释义（str 或 str[]）
WORD_DETAIL_FIELD_POS: Final[str] = "pos_zh"               # 中文词性标签（str[]）
WORD_DETAIL_FIELD_COLLOCATIONS: Final[str] = "collocations"  # 常见搭配（obj[]）
WORD_DETAIL_FIELD_EXAMPLES: Final[str] = "examples"         # 典型例句（obj[]）
WORD_DETAIL_FIELD_USAGE: Final[str] = "usage_note_zh"       # 语境 / 语气提示（str）

# —— 展示上限（统一口径，避免版面漂移）——
WORD_DETAIL_MAX_MEANINGS: Final[int] = 3        # 释义 ≤3 条
WORD_DETAIL_MAX_EXAMPLES: Final[int] = 3        # 例句 ≤3 条
WORD_DETAIL_MAX_COLLOCATIONS: Final[int] = 5    # 搭配 ≤5 条

# —— 打包内置详情库（只读，随包分发）——
WORD_DETAILS_FILE_NAME: Final[str] = "jlpt_word_details.json"
WORD_DETAILS_FILE_VERSION: Final[int] = 1

# —— 用户级联网结果缓存（TTL=0 表示永久有效，判定在 app 层）——
WORD_DETAILS_CACHE_FILENAME: Final[str] = "word_details_cache.json"
WORD_DETAILS_CACHE_VERSION: Final[int] = 1
WORD_DETAILS_CACHE_TTL_DAYS: Final[int] = 0

# —— DeepSeek 联网（OpenAI 兼容接口；仅标准库 urllib，默认超时 10s / 重试 1）——
LLM_ENDPOINT: Final[str] = "https://api.deepseek.com/v1/chat/completions"
LLM_MODEL: Final[str] = "deepseek-chat"
LLM_TIMEOUT_S: Final[float] = 10.0
LLM_RETRIES: Final[int] = 1
LLM_TEMPERATURE: Final[float] = 0.3
LLM_RESPONSE_FORMAT_TYPE: Final[str] = "json_object"
#: 系统提示：约束模型只输出一个 JSON 对象
LLM_PROMPT_SYSTEM: Final[str] = (
    "你是严谨的日语词典编辑，只输出一个 JSON 对象，不要任何解释或 Markdown 代码围栏。"
)
#: 用户提示模板（``str.format``；模板内的 JSON 花括号已转义为双花括号）
LLM_PROMPT_USER_TEMPLATE: Final[str] = (
    "请为日语词「{word}」（假名：{kana}，JLPT 等级：{level}，参考中文词义：{translation}）"
    "生成中文学习详情。严格只输出 JSON："
    '{{"meaning_zh":["…"],"pos_zh":["…"],'
    '"collocations":[{{"phrase":"…","note":"…"}}],'
    '"examples":[{{"jp":"…","zh":"…"}}],"usage_note_zh":"…"}}。'
    "要求：全部为简体中文；meaning_zh 1~3 条；pos_zh 为中文词性标签；collocations ≤5 条；"
    "examples 1~3 条（日文原句+中文翻译）；usage_note_zh 一句语境/语气提示；不确定的字段留空。"
)

# —— 详情窗口中文分组标题 / 状态 / 来源标注 / 文案 ——
WORD_DETAIL_LABEL_MEANING_ZH: Final[str] = "中文释义"
WORD_DETAIL_LABEL_POS_ZH: Final[str] = "词性"
WORD_DETAIL_LABEL_COLLOCATIONS: Final[str] = "常见搭配"
WORD_DETAIL_LABEL_EXAMPLES: Final[str] = "典型例句"
WORD_DETAIL_LABEL_USAGE: Final[str] = "语境语气"
WORD_DETAIL_EMPTY_GROUP: Final[str] = "暂无"
WORD_DETAIL_LOADING: Final[str] = "联网查询中…"
WORD_DETAIL_NOT_FOUND: Final[str] = "未找到该词的详情"
WORD_DETAIL_ERROR_TEMPLATE: Final[str] = "联网获取失败：{msg}"
WORD_DETAIL_OFFLINE_HINT: Final[str] = "未配置密钥，联网后可获取"
WORD_DETAIL_SOURCE_LOCAL: Final[str] = "来源：本地词库"
WORD_DETAIL_SOURCE_CACHE: Final[str] = "来源：用户缓存"
WORD_DETAIL_SOURCE_NET: Final[str] = "来源：联网获取"

__all__ = [
    "Mood",
    "Expression",
    "Gesture",
    "COLORS",
    # 色彩微调（阶段 B1）
    "PROP_OUTLINE",
    # 主题皮肤（阶段 A）
    "THEMES",
    "DEFAULT_THEME",
    "AUTO_THEME",
    "THEME_NAMES",
    "THEME_SEASON_MAP",
    "THEME_ALLOWED",
    "TRAY_MENU_THEME",
    "THEME_RECHECK_MS",
    # Design Token（UI 视觉升级 P0）
    "SEMANTIC_COLORS",
    "SPACING",
    "FONT_SIZE",
    "RADIUS",
    "EXPRESSION_POSES",
    "NEUTRAL_POSE",
    "BUBBLE_TEXTS",
    "interval_for_fps",
    # 动效去机械化（阶段 A5）
    "BREATH_JITTER",
    "BLINK_EYE_DELAY_S",
    "SURPRISE_MIN_S",
    "SURPRISE_MAX_S",
    "SURPRISE_DURATION_S",
    "SURPRISE_POSES",
    # 日语学习
    "JP_LEVELS",
    "JP_DEFAULT_LEVEL",
    "JP_LEVEL_LABELS",
    "JP_WORD_MIN_INTERVAL_S",
    "JP_WORD_MAX_INTERVAL_S",
    "JP_BUBBLE_WORD_FONT_SIZE",
    "JP_BUBBLE_KANA_FONT_SIZE",
    "JP_BUBBLE_TRANSLATION_FONT_SIZE",
    "JP_BUBBLE_MEANING_FONT_SIZE",
    "JP_BUBBLE_MAX_WIDTH",
    "JP_BUBBLE_FONT_FAMILY",
    "BUBBLE_LINE_SPACING",
    "WORD_BANK_DIR_NAME",
    "WORD_BANK_FILE_NAME",
    "WORD_BANK_VERSION",
    "VOCAB_FILE_NAME",
    "VOCAB_VERSION",
    "VOCAB_WINDOW_W",
    "VOCAB_WINDOW_H",
    # 日语记忆
    "JP_BUBBLE_DURATION_S",
    "JP_BUBBLE_DURATION_OPTIONS",
    "JP_BUBBLE_DURATION_LABELS",
    "JP_BUBBLE_MIN_DURATION_S",
    "JP_BUBBLE_MAX_DURATION_S",
    "JP_DAILY_LIMIT",
    "JP_DAILY_LIMIT_OPTIONS",
    "JP_DAILY_LIMIT_LABELS",
    "JP_VOCAB_WEIGHT",
    "MASTERED_FILE_NAME",
    "MASTERED_VERSION",
    "DAILY_LOG_FILE_NAME",
    "DAILY_LOG_VERSION",
    "DAILY_LOG_STATUS_MASTERED",
    "DAILY_LOG_STATUS_VOCAB",
    "DAILY_LOG_STATUS_UNPROCESSED",
    "DAILY_LOG_STATUSES",
    "JP_BUTTON_MASTERED",
    "JP_BUTTON_VOCAB",
    "JP_BUTTON_RADIUS",
    "JP_BUTTON_PAD_X",
    "JP_BUTTON_PAD_Y",
    "JP_BUTTON_BAR_GAP_PX",
    "JP_BUTTON_BAR_PAD",
    "JP_BUTTON_FONT_SIZE",
    "JP_MENU_LOG",
    "JP_MENU_DURATION",
    "JP_MENU_DAILY_LIMIT",
    "JP_MENU_SHOW_NOW",
    "TRAY_MENU_REDUCE_MOTION",
    "TRAY_MENU_REDUCE_MOTION_TIP",
    "TRAY_NOTIFY_REDUCE_MOTION_ON",
    "TRAY_NOTIFY_REDUCE_MOTION_OFF",
    "JP_NOTIFY_MASTERED_ADDED",
    "JP_NOTIFY_MASTERED_DUPLICATE",
    "JP_NOTIFY_LEVEL_DONE",
    "JP_NOTIFY_TODAY_DONE",
    "JP_NOTIFY_SHOW_NOW",
    "JP_NOTIFY_SHOW_NOW_BLOCKED",
    "JP_NOTIFY_SHOW_NOW_OVER_LIMIT",
    "JP_NOTIFY_POOL_EXHAUSTED",
    "JP_NOTIFY_JP_OFF",
    "JP_NOTIFY_SHOW_NOW_FAILED",
    "JP_LOG_WINDOW_TITLE",
    "JP_LOG_WINDOW_W",
    "JP_LOG_WINDOW_H",
    "JP_LOG_DATE_LABEL",
    "JP_LOG_STATUS_LABEL",
    "JP_LOG_FILTER_ALL",
    "JP_LOG_STATUS_MASTERED",
    "JP_LOG_STATUS_VOCAB",
    "JP_LOG_STATUS_UNPROCESSED",
    "JP_LOG_COL_WORD",
    "JP_LOG_COL_KANA",
    "JP_LOG_COL_TRANSLATION",
    "JP_LOG_COL_SHOWN_AT",
    "JP_LOG_COL_STATUS",
    "JP_LOG_EMPTY_TEXT",
    "JP_LOG_STATUS_TEMPLATE",
    # 单词详情窗口（基础几何 / 标签 / 通用按钮）
    "WORD_DETAIL_WINDOW_TITLE",
    "WORD_DETAIL_WINDOW_W",
    "WORD_DETAIL_WINDOW_H",
    "WORD_DETAIL_LABEL_KANA",
    "WORD_DETAIL_RETRY",
    "WORD_DETAIL_CLOSE",
    "WORD_DETAIL_NO_VALUE",
    # 中文详情五要素 / 用户缓存 / DeepSeek 联网（增量改造 §13）
    "WORD_DETAIL_FIELD_MEANING",
    "WORD_DETAIL_FIELD_POS",
    "WORD_DETAIL_FIELD_COLLOCATIONS",
    "WORD_DETAIL_FIELD_EXAMPLES",
    "WORD_DETAIL_FIELD_USAGE",
    "WORD_DETAIL_MAX_MEANINGS",
    "WORD_DETAIL_MAX_EXAMPLES",
    "WORD_DETAIL_MAX_COLLOCATIONS",
    "WORD_DETAILS_FILE_NAME",
    "WORD_DETAILS_FILE_VERSION",
    "WORD_DETAILS_CACHE_FILENAME",
    "WORD_DETAILS_CACHE_VERSION",
    "WORD_DETAILS_CACHE_TTL_DAYS",
    "LLM_ENDPOINT",
    "LLM_MODEL",
    "LLM_TIMEOUT_S",
    "LLM_RETRIES",
    "LLM_TEMPERATURE",
    "LLM_RESPONSE_FORMAT_TYPE",
    "LLM_PROMPT_SYSTEM",
    "LLM_PROMPT_USER_TEMPLATE",
    "WORD_DETAIL_LABEL_MEANING_ZH",
    "WORD_DETAIL_LABEL_POS_ZH",
    "WORD_DETAIL_LABEL_COLLOCATIONS",
    "WORD_DETAIL_LABEL_EXAMPLES",
    "WORD_DETAIL_LABEL_USAGE",
    "WORD_DETAIL_EMPTY_GROUP",
    "WORD_DETAIL_LOADING",
    "WORD_DETAIL_NOT_FOUND",
    "WORD_DETAIL_ERROR_TEMPLATE",
    "WORD_DETAIL_OFFLINE_HINT",
    "WORD_DETAIL_SOURCE_LOCAL",
    "WORD_DETAIL_SOURCE_CACHE",
    "WORD_DETAIL_SOURCE_NET",
]
