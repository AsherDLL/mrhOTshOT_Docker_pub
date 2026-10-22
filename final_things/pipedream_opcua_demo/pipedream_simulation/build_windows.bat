@echo off
REM Build script for PIPEDREAM C++ components on Windows
REM Builds Dusttunnel and Lazycargo executables
REM
REM Requirements:
REM - Visual Studio 2019 or later with C++ tools
REM - Windows SDK
REM
REM Usage: build_windows.bat

echo ============================================================
echo   PIPEDREAM Windows Build System
echo ============================================================
echo.

REM Check for Visual Studio
where cl.exe >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Visual Studio C++ compiler not found in PATH
    echo [*] Attempting to locate Visual Studio...

    if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" (
        call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
    ) else if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat" (
        call "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
    ) else (
        echo [-] Could not find Visual Studio installation
        echo [*] Please run this script from Visual Studio Developer Command Prompt
        pause
        exit /b 1
    )
)

echo [+] Visual Studio compiler found
echo.

REM Create build directory
if not exist "build" mkdir build
cd build

echo ============================================================
echo Building DUSTTUNNEL (Windows Persistence Module)
echo ============================================================
echo.

cl.exe /nologo /O2 /MT /W3 ^
    /D "WIN32" /D "NDEBUG" /D "_CONSOLE" ^
    ..\dusttunnel\dusttunnel.cpp ^
    /Fe:dusttunnel.exe ^
    /link wininet.lib advapi32.lib

if %ERRORLEVEL% EQU 0 (
    echo [+] Dusttunnel built successfully: build\dusttunnel.exe
) else (
    echo [-] Dusttunnel build failed
)

echo.
echo ============================================================
echo Building LAZYCARGO (ASRock Driver Exploit Module)
echo ============================================================
echo.

cl.exe /nologo /O2 /MT /W3 ^
    /D "WIN32" /D "NDEBUG" /D "_CONSOLE" ^
    ..\lazycargo\lazycargo.cpp ^
    /Fe:lazycargo.exe ^
    /link advapi32.lib

if %ERRORLEVEL% EQU 0 (
    echo [+] Lazycargo built successfully: build\lazycargo.exe
) else (
    echo [-] Lazycargo build failed
)

cd ..

echo.
echo ============================================================
echo Build Summary
echo ============================================================
echo.

if exist "build\dusttunnel.exe" (
    echo [+] dusttunnel.exe - Windows Persistence Module
) else (
    echo [-] dusttunnel.exe - BUILD FAILED
)

if exist "build\lazycargo.exe" (
    echo [+] lazycargo.exe - ASRock Driver Exploit Module
) else (
    echo [-] lazycargo.exe - BUILD FAILED
)

echo.
echo Build complete. Executables are in the 'build' directory.
echo.
echo WARNING: These are offensive security tools for authorized testing only!
echo ============================================================
echo.

pause
