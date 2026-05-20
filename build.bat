@echo off
setlocal

rem ============================================================
rem build.bat - builds LabLayoutTool .exe + installer + zips
rem Run this from the project folder: build.bat
rem Requires:
rem   .venv\Scripts\pip install -r requirements.txt
rem   .venv\Scripts\pip install -r requirements-dev.txt
rem   Inno Setup 6 (https://jrsoftware.org/isinfo.php) — optional
rem ============================================================

rem Pre-flight: verify build dependencies are installed in the venv.
.venv\Scripts\python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo ERROR: PyInstaller not found in .venv. Install build dependencies:
    echo        .venv\Scripts\pip install -r requirements-dev.txt
    exit /b 1
)

rem Pre-flight: verify the phoenix-commons submodule is initialised
rem (ADR-015 — submodule + editable install is the official transport).
rem A fresh clone needs `git submodule update --init --recursive` before
rem `pip install -r requirements.txt` can resolve the `-e ./commons` line.
if not exist "commons\src\phoenix_commons\__init__.py" (
    echo.
    echo ERROR: phoenix-commons submodule missing. Run:
    echo        git submodule update --init --recursive
    echo        .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)
.venv\Scripts\python -c "import phoenix_commons" >nul 2>&1
if errorlevel 1 (
    echo ERROR: phoenix_commons not importable from .venv. Re-install:
    echo        .venv\Scripts\pip install -e .\commons
    exit /b 1
)

rem Read version from version.py via Python so whitespace / quoting in the
rem source file can't break the parse (the previous findstr+tokens approach
rem silently produced an empty VERSION on tab indentation or odd spacing).
for /f "delims=" %%v in ('.venv\Scripts\python -c "from version import __version__; print(__version__)"') do set "VERSION=%%v"

if not defined VERSION (
    echo ERROR: Could not read version from version.py.
    exit /b 1
)

echo ============================================================
echo  Building Lab Layout Tool v%VERSION%
echo ============================================================
echo.

rem Step 0: sanity checks + sync embedded QSS from source
echo [0/4] Running sanity checks...
findstr /C:"Current Version: v%VERSION%" README.md >nul
if errorlevel 1 (
    echo.
    echo ERROR: README.md "Current Version" line does not match version.py v%VERSION%.
    echo        Bump the README before building.
    exit /b 1
)

.venv\Scripts\python -m py_compile version.py app.py paths.py updater.py ui\style.py ui\components.py ui\main_window.py ui\pbc.py cad\blocks.py cad\layout.py cad\bricscad.py cad\pbc.py cad\migrate.py
if errorlevel 1 (
    echo.
    echo ERROR: Python compile check failed.
    exit /b 1
)
rem Phase 3A retrofit: tools\embed_qss.py was retired. Commons owns the
rem canonical QSS + the generated embedded fallback (per phase 2.1) +
rem the brand-profile sentinel substitution (per ADR-016). PyInstaller's
rem --collect-all phoenix_commons (below) bundles them into _internal/.
echo [0/4] Sanity checks passed.
echo.

rem Step 1: PyInstaller
echo [1/4] Running PyInstaller...
.venv\Scripts\pyinstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --icon=LLT_Normal.ico ^
    --name=LabLayoutTool ^
    --add-data="LLT_Normal.ico;." ^
    --add-data="LLT_Transparent.png;." ^
    --add-data="config;config" ^
    --add-data="blocks;blocks" ^
    --add-data="templates;templates" ^
    --add-data="jobs/Quick_Test_Building.json;jobs" ^
    --add-data="jobs/thorough-test.json;jobs" ^
    --collect-all=phoenix_commons ^
    --collect-submodules=PySide6.QtCore ^
    --collect-submodules=PySide6.QtGui ^
    --collect-submodules=PySide6.QtWidgets ^
    --hidden-import=win32com ^
    --hidden-import=win32com.client ^
    --hidden-import=pythoncom ^
    app.py

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed.
    exit /b 1
)
if not exist "dist\LabLayoutTool\LabLayoutTool.exe" (
    echo.
    echo ERROR: PyInstaller output missing LabLayoutTool.exe.
    exit /b 1
)
if not exist "dist\LabLayoutTool\_internal" (
    echo.
    echo ERROR: PyInstaller output missing _internal runtime folder.
    exit /b 1
)
echo [1/4] PyInstaller complete.
echo.

rem Step 2: Inno Setup installer (optional — skipped if not installed)
echo [2/4] Building installer with Inno Setup...

set "ISCC="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo.
    echo WARNING: Inno Setup 6 not found. Skipping installer creation.
    echo          Download from: https://jrsoftware.org/isinfo.php
    echo.
    goto zips
)

if not exist installer.iss (
    echo WARNING: installer.iss not present. Skipping installer creation.
    goto zips
)

"%ISCC%" /DMyAppVersion=%VERSION% installer.iss
if errorlevel 1 (
    echo.
    echo ERROR: Inno Setup build failed.
    exit /b 1
)
if not exist "dist\LabLayoutToolSetup.exe" (
    echo.
    echo ERROR: Installer output missing dist\LabLayoutToolSetup.exe.
    exit /b 1
)
echo [2/4] Installer created: dist\LabLayoutToolSetup.exe
echo.

rem Step 3: Create zips
:zips
echo [3/4] Creating zip archives...

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\LabLayoutTool\*' -DestinationPath 'dist\LabLayoutTool.zip' -Force"
if errorlevel 1 (
    echo.
    echo ERROR: Auto-updater zip creation failed.
    exit /b 1
)
echo   Created: dist\LabLayoutTool.zip  (auto-updater)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\LabLayoutTool' -DestinationPath 'dist\LabLayoutTool_FullInstall.zip' -Force"
if errorlevel 1 (
    echo.
    echo ERROR: Full install zip creation failed.
    exit /b 1
)
echo   Created: dist\LabLayoutTool_FullInstall.zip  (manual install)

echo.
echo [4/4] Verifying release artifacts...
if not exist "dist\LabLayoutTool.zip" (
    echo ERROR: Missing dist\LabLayoutTool.zip.
    exit /b 1
)
if not exist "dist\LabLayoutTool_FullInstall.zip" (
    echo ERROR: Missing dist\LabLayoutTool_FullInstall.zip.
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$z='dist\LabLayoutTool.zip'; Add-Type -AssemblyName System.IO.Compression.FileSystem; $zip=[System.IO.Compression.ZipFile]::OpenRead($z); try { $names=$zip.Entries.FullName | ForEach-Object { $_ -replace '\\','/' }; if ($names -notcontains 'LabLayoutTool.exe') { exit 2 }; if (-not ($names | Where-Object { $_ -like '_internal/*' })) { exit 3 } } finally { $zip.Dispose() }"
if errorlevel 1 (
    echo.
    echo ERROR: Auto-updater zip must contain LabLayoutTool.exe and _internal\* at its root.
    exit /b 1
)
echo [4/4] Artifact verification passed.

echo.
echo ============================================================
echo  Build complete - v%VERSION%
echo ============================================================
echo.
echo  dist\LabLayoutTool\LabLayoutTool.exe   ^<-- test this first
echo  dist\LabLayoutToolSetup.exe            ^<-- installer
echo  dist\LabLayoutTool.zip                 ^<-- auto-updater zip
echo  dist\LabLayoutTool_FullInstall.zip     ^<-- manual install zip
echo.
echo  Upload to GitHub Release:
echo    - LabLayoutTool.zip                  (required for auto-updater)
echo    - LabLayoutToolSetup.exe             (recommended for new users)
echo.

endlocal
