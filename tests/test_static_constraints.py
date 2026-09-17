"""静态约束回归测试（防止架构腐化）。

- ``core/`` 零 Qt/GUI 依赖（架构 §1.2 硬性要求）。
- 依赖方向单向：``core`` 不 import ``ui``/``app``；``ui`` 不 import ``app``。
- ``src/`` 下无 ``print(``（统一 logging）。
- 无任何图片素材文件（零外部素材承诺）。
- ``constants.py`` 关键阈值与 PRD 一致（防实现与需求漂移）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression, Mood

_QT_PREFIXES = ("PySide6", "PyQt5", "PyQt6", "qtpy")


def _iter_py_files(root: Path):
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_modules(path: Path) -> list[str]:
    """返回文件里所有被 import 的模块名（含 from xxx import 的 xxx）。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


# --------------------------------------------------------------------------- #
# 1. core 零 Qt 依赖
# --------------------------------------------------------------------------- #
def test_core_has_no_qt_imports(src_root: Path) -> None:
    core = src_root / "core"
    offenders: list[str] = []
    for path in _iter_py_files(core):
        for module in _imported_modules(path):
            if module.startswith(_QT_PREFIXES):
                offenders.append(f"{path.name}: {module}")
    assert not offenders, f"core 出现 Qt 依赖（架构违规）：{offenders}"


def test_core_does_not_import_ui_or_app(src_root: Path) -> None:
    core = src_root / "core"
    offenders: list[str] = []
    for path in _iter_py_files(core):
        for module in _imported_modules(path):
            if module.startswith("desktop_pet.ui") or module.startswith("desktop_pet.app"):
                offenders.append(f"{path.name}: {module}")
    assert not offenders, f"core 反向依赖 ui/app（架构违规）：{offenders}"


def test_ui_does_not_import_app(src_root: Path) -> None:
    ui = src_root / "ui"
    offenders: list[str] = []
    for path in _iter_py_files(ui):
        for module in _imported_modules(path):
            if module.startswith("desktop_pet.app"):
                offenders.append(f"{path.name}: {module}")
    assert not offenders, f"ui 反向依赖 app（架构违规）：{offenders}"


def test_core_imports_without_loading_qt(project_root: Path) -> None:
    """在**全新子进程**中导入 core 全模块，断言 PySide6 从未被加载。

    这比进程内 AST 检查更强：直接证明纯逻辑层运行时不依赖 Qt。
    """

    import os
    import subprocess
    import sys

    src = project_root / "src"
    code = (
        "import sys\n"
        "import desktop_pet.core.constants\n"
        "import desktop_pet.core.config\n"
        "import desktop_pet.core.event_aggregator\n"
        "import desktop_pet.core.motion\n"
        "import desktop_pet.core.mood_state_machine\n"
        "import desktop_pet.core.pet_model\n"
        "import desktop_pet.core.paths\n"
        "import desktop_pet.core.vocabulary\n"
        "import desktop_pet.core.vocab_store\n"
        "import desktop_pet.core.mastered_store\n"
        "import desktop_pet.core.daily_log_store\n"
        "import desktop_pet.core.weighted_picker\n"
        "import desktop_pet.core.jisho\n"
        "import desktop_pet.core.jisho_cache_store\n"
        "loaded = [m for m in sys.modules if m.startswith('PySide6')]\n"
        "assert not loaded, 'core 导入过程加载了 Qt: %r' % loaded\n"
        "print('CORE_IS_QT_FREE')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(src)}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60
    )
    assert result.returncode == 0, f"子进程导入失败：{result.stderr}"
    assert "CORE_IS_QT_FREE" in result.stdout


# --------------------------------------------------------------------------- #
# 2. 无 print(（统一 logging）
# --------------------------------------------------------------------------- #
def test_no_print_calls_in_src(src_root: Path) -> None:
    offenders: list[str] = []
    for path in _iter_py_files(src_root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                offenders.append(f"{path.relative_to(src_root.parent)}:{node.lineno}")
    assert not offenders, f"src 下存在 print 调用（应使用 logging）：{offenders}"


# --------------------------------------------------------------------------- #
# 2b. UI 层不得出现裸十六进制色值（色值必须走 COLORS / SEMANTIC_COLORS）
# --------------------------------------------------------------------------- #
#: 合法 ``#RRGGBB`` 色值（``#RRGGBB`` 这类占位因 R/G/B 非十六进制字符而不会被命中）。
_HEX_LITERAL_RE = re.compile(r"#[0-9A-Fa-f]{6}")


def _docstring_constant_ids(path: Path) -> set[int]:
    """返回模块 / 类 / 函数级 docstring 对应 ``ast.Constant`` 节点的 id 集合。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))
    return ids


def test_ui_has_no_bare_hex_color_literals(src_root: Path) -> None:
    """``src/desktop_pet/ui/`` 下字符串字面量不得含 ``#RRGGBB`` 裸色值（docstring 除外）。

    色值统一由 ``core.constants`` 的 ``COLORS`` / ``SEMANTIC_COLORS`` 提供；QSS 里的色值
    也必须由 token 拼装，不得写死。任何裸色值都应改用 token 取值。
    """

    ui = src_root / "ui"
    offenders: list[str] = []
    for path in _iter_py_files(ui):
        skip_ids = _docstring_constant_ids(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip_ids
            ):
                match = _HEX_LITERAL_RE.search(node.value)
                if match:
                    offenders.append(f"{path.name}:{node.lineno}: 裸色值 {match.group(0)}")
    assert not offenders, f"UI 层出现裸十六进制色值（应改用 token）：{offenders}"


# --------------------------------------------------------------------------- #
# 3. 零外部图片素材
# --------------------------------------------------------------------------- #
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
                   ".tif", ".tiff", ".qrc", ".xpm"}


def test_no_image_assets(project_root: Path) -> None:
    offenders = [
        str(p.relative_to(project_root))
        for p in project_root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in _IMAGE_SUFFIXES
        and ".venv" not in p.parts
        and "__pycache__" not in p.parts
    ]
    assert not offenders, f"发现图片素材（违背零外部素材承诺）：{offenders}"


# --------------------------------------------------------------------------- #
# 4. 常量与 PRD 一致（防漂移）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "attr,expected",
    [
        ("HIGH_FREQ_WINDOW_MS", 300.0),
        ("HIGH_FREQ_THRESHOLD", 3),
        ("IDLE_START_S", 20.0),
        ("REST_THRESHOLD_S", 120.0),
        ("SLEEP_THRESHOLD_S", 300.0),
        ("MIN_DWELL_S", 5.0),
        ("WAKE_SULKY_S", 3.0),
        ("EXCITED_THRESHOLD_S", 5.0),
        ("SLEEPY_REST_S", 30.0),
        ("SURPRISED_IDLE_S", 120.0),
        ("BLINK_MIN_S", 3.0),
        ("BLINK_MAX_S", 6.0),
        ("BREATH_PERIOD_S", 3.0),
        ("TAIL_MIN_S", 2.0),
        ("TAIL_MAX_S", 4.0),
        ("YAWN_MIN_S", 15.0),
        ("YAWN_MAX_S", 30.0),
        ("HOVER_TRIGGER_S", 1.0),
        ("CLICK_ANIM_S", 1.5),
        ("DRAG_THRESHOLD_PX", 5),
        ("BUBBLE_MIN_GAP_S", 3.0),
        ("FPS_ACTIVE", 30),
        ("FPS_IDLE", 15),
        ("FPS_SLEEP", 8),
        ("BASE_W", 160),
        ("BASE_H", 180),
        ("CONFIG_VERSION", 1),
        ("JP_BUBBLE_DURATION_S", 30),
        ("JP_BUBBLE_MIN_DURATION_S", 2.0),
        ("JP_BUBBLE_MAX_DURATION_S", 300.0),
        ("JP_DAILY_LIMIT", 15),
        ("JP_VOCAB_WEIGHT", 3.0),
        ("MASTERED_VERSION", 1),
        ("DAILY_LOG_VERSION", 1),
        ("JISHO_TIMEOUT_S", 5.0),
        ("JISHO_MAX_DEFINITIONS", 6),
        ("JISHO_CACHE_VERSION", 1),
        ("JISHO_CACHE_TTL_DAYS", 7),
    ],
)
def test_constants_match_prd(attr: str, expected) -> None:
    assert getattr(C, attr) == expected, f"{attr} 与 PRD 不一致"


def test_scales_match_prd() -> None:
    assert C.SCALES == (0.8, 1.0, 1.2)


def test_jp_config_option_tiers_match_prd() -> None:
    """B 版档位收敛：时长 {15,30,60}、每日数量 {5,10,15,20,30}，且默认值命中档位。"""

    assert C.JP_BUBBLE_DURATION_OPTIONS == (15, 30, 60)
    assert C.JP_DAILY_LIMIT_OPTIONS == (5, 10, 15, 20, 30)
    assert C.JP_BUBBLE_DURATION_S in C.JP_BUBBLE_DURATION_OPTIONS
    assert C.JP_DAILY_LIMIT in C.JP_DAILY_LIMIT_OPTIONS
    assert set(C.JP_BUBBLE_DURATION_LABELS) == set(C.JP_BUBBLE_DURATION_OPTIONS)
    assert set(C.JP_DAILY_LIMIT_LABELS) == set(C.JP_DAILY_LIMIT_OPTIONS)


def test_jisho_url_and_cache_constants_defined() -> None:
    """Jisho 联网 / 缓存常量存在且取值合理。"""

    assert C.JISHO_API_URL.startswith("https://")
    assert C.JISHO_CACHE_FILENAME.endswith(".json")
    assert C.JISHO_CACHE_TTL_DAYS > 0


def test_mood_has_four_states() -> None:
    assert {m.name for m in Mood} == {"IDLE", "FOCUS", "REST", "SLEEP"}


def test_expression_count_matches_prd() -> None:
    assert len(list(Expression)) == 8


def test_color_palette_matches_prd() -> None:
    """重构后配色（视觉基准：参考图「柔和全息彩虹 + 粗黑描边」）。

    旧版奶油/焦糖暖调配色已被参考图风格取代；保留气泡相关键不变。
    """

    expected = {
        "ink": "#141414",         # 近黑 主体粗描边 / 眼睛 / 嘴
        "blush": "#FFB3C7",       # 柔和粉 腮红
        "white": "#FFFFFF",       # 纯白 高光 / 前爪
        "mouse_body": "#3A3A3A",  # 深灰 鼠标 / 键盘底座
        "mouse_hi": "#8A8A8A",    # 中灰 鼠标分割线 / 滚轮
        "bubble_bg": "#FFFDF8",
        "bubble_text": "#7A5A42",
        "glow_yellow": "#FFD08A",
        "glow_blue": "#B9D4E8",
        "warm_brown": "#8B6B4F",  # 兼容保留：ui.bubble 描边仍引用
        # —— 日语学习新增（设计 §7.4）——
        "bubble_sub_text": "#9C8570",    # 假名次级文字
        "bubble_faint_text": "#B7A99A",  # 释义最淡文字
        "vocab_bg": "#FFFDF8",           # 生词本底色
        "vocab_text": "#5A4636",         # 生词本正文
        "vocab_level_tag": "#7A9E7E",    # 等级标签色
        # —— 日语记忆新增（设计 §7.3）——
        "bubble_gradient_hi": "#FFFFFF",          # 学习泡泡浅高光
        "jp_button_primary_bg": "#7A9E7E",        # 「记住了」主色
        "jp_button_primary_text": "#FFFFFF",
        "jp_button_primary_hover": "#8FB090",
        "jp_button_primary_pressed": "#6B8E6F",
        "jp_button_secondary_border": "#9C8570",
        "jp_button_secondary_text": "#7A5A42",
        "jp_button_secondary_hover": "#F3EAE0",
        "jp_button_bar_bg": "#FFFDF8",
        "log_status_mastered": "#7A9E7E",
        "log_status_vocab": "#5B8DB8",
        "log_status_unprocessed": "#B7A99A",
        # —— B 版气泡质感 / 等级角标（设计 §A1.1）——
        "bubble_shadow": "#C9B8A6",
        "bubble_divider": "#EFE3D4",
        "bubble_gradient_bottom": "#F7EEDF",
        "jp_level_chip_bg": "#7A9E7E",
        "jp_level_chip_text": "#FFFFFF",
    }
    assert C.COLORS == expected


def test_body_gradient_and_outline_defined() -> None:
    """新增的柔和全息彩虹渐变与粗黑描边常量存在且取值合理。"""

    stops = C.BODY_GRADIENT_STOPS
    assert len(stops) >= 4, "彩虹渐变停靠点过少"
    positions = [p for p, _ in stops]
    assert positions == sorted(positions), "渐变停靠点必须单调递增"
    assert positions[0] == 0.0 and positions[-1] == 1.0, "渐变须覆盖 0→1"
    for _pos, hexv in stops:
        assert hexv.startswith("#") and len(hexv) == 7, f"非法色值：{hexv}"
    # 粗黑描边：明显厚于细线，体现参考图的厚重卡通风
    assert C.OUTLINE_W >= 3.0, f"主体描边过细（{C.OUTLINE_W}）"


def test_no_pure_black_outline_in_palette() -> None:
    """PRD §4.2：无纯黑描边。"""

    assert "#000000" not in {v.upper() for v in C.COLORS.values()}


def test_bubble_texts_cover_all_expressions() -> None:
    for expr in Expression:
        assert expr in C.BUBBLE_TEXTS, f"表情 {expr.name} 缺少气泡文案"
