# -*- mode: python ; coding: utf-8 -*-
"""desktop-pet —— 单文件分发版打包配置（PyInstaller **onefile**）。

用途：产出**单个** ``dist/desktop-pet.exe``，供 GitHub Releases 分发。
最终用户下载后双击即用：无需安装 Python、无需解压、无需任何附带文件。

与 ``desktop-pet.spec``（onedir）的分工：

======================  ==========================  ==============================
spec                    产物                          用途
======================  ==========================  ==============================
``desktop-pet.spec``    ``dist/desktop-pet/`` 目录    本地 run.bat 调用；启动快
``desktop-pet-onefile.spec``  ``dist/desktop-pet.exe``  对外发布；单文件免解压
======================  ==========================  ==============================

onefile 的代价：每次启动需把内置依赖解包到 ``%TEMP%\\_MEIxxxxxx``，
首次启动比 onedir 慢数秒，属预期行为。

**零外部素材约束**：本配置不引用任何 ``.ico`` / ``.png`` / ``.svg``。
窗口与托盘图标一律由 ``ui/pet_renderer.py`` 的 ``build_tray_icon()``
与 ``ui/icon_factory.py`` 程序化绘制（项目硬约束，见 README）。

构建::

    python -m PyInstaller --noconfirm --clean desktop-pet-onefile.spec
"""

a = Analysis(
    ['src/desktop_pet/main.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('src/desktop_pet/data/jlpt_words.json', 'desktop_pet/data'),
        ('src/desktop_pet/data/jlpt_word_details.json', 'desktop_pet/data'),
    ],
    # pynput 的后端按平台动态导入，静态分析看不到，必须显式声明
    hiddenimports=['pynput.keyboard._win32', 'pynput.mouse._win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 本程序仅使用 QtCore / QtGui / QtWidgets（requirements.txt 已声明该边界）。
        # PySide6-Essentials 仍附带 Quick/Qml/Designer 等约 150MB 无关内容，
        # 逐项排除以压缩单文件体积。这些模块与 Core/Gui/Widgets 无依赖关系
        # （反向依赖才成立），排除后由构建产物的实机启动验证兜底。
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQuickControls2',
        'PySide6.QtDesigner',
        'PySide6.QtUiTools',
        'PySide6.QtTest',
        'PySide6.QtSql',
        'PySide6.QtNetwork',
        'PySide6.QtXml',
        'PySide6.QtConcurrent',
        'PySide6.QtHelp',
        'PySide6.QtDBus',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        'PySide6.QtPrintSupport',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtNfc',
        'PySide6.QtSerialPort',
        'PySide6.QtWebSockets',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtPositioning',
        'PySide6.QtLocation',
        'PySide6.QtBluetooth',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='desktop-pet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 窗口程序：不弹控制台。（启动期日志仍写入 %APPDATA%\desktop-pet\app.log）
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
