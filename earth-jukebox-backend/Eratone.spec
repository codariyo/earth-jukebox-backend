# -*- mode: python ; coding: utf-8 -*-
# Eratone masaustu uygulamasi (eratone_app.py) -> dist\Eratone\Eratone.exe  (onedir, penceresiz)
# Derle: powershell -ExecutionPolicy Bypass -File build_eratone.ps1
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Faz 5: world-sound muzik sistemi (world-sound/worldsound). app/audio.py calisma aninda sys.path'e
# ekler; derlemede de bulunsun diye pathex'e konur ve paketin tum modulleri gomulur.
sys.path.insert(0, 'world-sound')

hiddenimports = ['app.main']
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('app')
hiddenimports += collect_submodules('worldsound')
hiddenimports += ['sounddevice', '_sounddevice', 'scipy.signal', 'soundfile', 'edge_tts']

a = Analysis(
    ['eratone_app.py'],
    pathex=['world-sound'],
    binaries=[],
    # Arayuz dosyalari: app/main.py FRONTEND_DIR = <paket>/frontend/static
    # _sounddevice_data: PortAudio DLL'i (ses karti erisimi)
    # worldsound/samples: gercek enstruman kayitlari (sampler.py SAMPLES_DIR = <paket>/worldsound/samples)
    # _soundfile_data: libsndfile DLL'i (OGG kayitlarini cozer)
    datas=[('frontend/static', 'frontend/static'), ('world-sound/worldsound/samples', 'worldsound/samples')]
          + collect_data_files('_sounddevice_data') + collect_data_files('_soundfile_data'),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # tkinter (world-sound/test_app.py) ve test araclari exe'ye girmesin
    excludes=['tkinter', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Eratone',
    icon='assets/eratone.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name='Eratone',
)
