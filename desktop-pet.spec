# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/desktop_pet/main.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('src/desktop_pet/data/jlpt_words.json', 'desktop_pet/data'),
        ('src/desktop_pet/data/jlpt_word_details.json', 'desktop_pet/data'),
    ],
    hiddenimports=['pynput.keyboard._win32', 'pynput.mouse._win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='desktop-pet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='desktop-pet',
)
