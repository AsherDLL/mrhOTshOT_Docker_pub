# PyInstaller spec file for building Windows executables
# This builds all the Industroyer2 payload components as Windows .exe files

# To build:
#   pyinstaller build_windows_exe.spec

block_cipher = None

# PService_PPD.exe - Dummy SCADA process
pservice_analysis = Analysis(
    ['PService_PPD.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pservice_pyz = PYZ(pservice_analysis.pure, pservice_analysis.zipped_data, cipher=block_cipher)

pservice_exe = EXE(
    pservice_pyz,
    pservice_analysis.scripts,
    pservice_analysis.binaries,
    pservice_analysis.zipfiles,
    pservice_analysis.datas,
    [],
    name='PService_PPD',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window (background process)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    onefile=True,  # Single file executable
)

# industroyer2_characteristics.exe
characteristics_analysis = Analysis(
    ['industroyer2_characteristics.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

characteristics_pyz = PYZ(characteristics_analysis.pure, characteristics_analysis.zipped_data, cipher=block_cipher)

characteristics_exe = EXE(
    characteristics_pyz,
    characteristics_analysis.scripts,
    characteristics_analysis.binaries,
    characteristics_analysis.zipfiles,
    characteristics_analysis.datas,
    [],
    name='industroyer2_characteristics',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Console window for output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,  # Single file executable
)

# industroyer2_initial_access.exe
initial_access_analysis = Analysis(
    ['industroyer2_initial_access.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

initial_access_pyz = PYZ(initial_access_analysis.pure, initial_access_analysis.zipped_data, cipher=block_cipher)

initial_access_exe = EXE(
    initial_access_pyz,
    initial_access_analysis.scripts,
    initial_access_analysis.binaries,
    initial_access_analysis.zipfiles,
    initial_access_analysis.datas,
    [],
    name='industroyer2_initial_access',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,  # Single file executable
)

# industroyer2_simulation.exe - ONEFILE with all dependencies
industroyer2_analysis = Analysis(
    ['industroyer2_simulation.py'],
    pathex=['.', '../perform_malware_simulations'],  # Add path to find raw_iec104
    binaries=[],
    datas=[],
    hiddenimports=['c104', 'raw_iec104', 'socket', 'struct', 'time', 'enum'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

industroyer2_pyz = PYZ(industroyer2_analysis.pure, industroyer2_analysis.zipped_data, cipher=block_cipher)

# ONEFILE configuration - everything bundled into single executable
industroyer2_exe = EXE(
    industroyer2_pyz,
    industroyer2_analysis.scripts,
    industroyer2_analysis.binaries,
    industroyer2_analysis.zipfiles,
    industroyer2_analysis.datas,
    [],
    name='industroyer2_simulation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Compress executable
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,  # Explicitly set onefile mode
)
