@echo off
cd /d "%~dp0"
setlocal

rem 在桌面创建 AIE 快捷方式（指向本便携包内的 aife\aife.exe）
rem 用法：双击运行；请勿移动本文件，需与 aife 目录保持同级。

set "TARGET=%~dp0aife\aife.exe"
set "LNK=%USERPROFILE%\Desktop\AI For Everyone.lnk"

if not exist "%TARGET%" (
    echo [失败] 未找到 "%TARGET%"。
    echo 请在本便携包目录内运行本脚本（与 aife 文件夹同级）。
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');$s.TargetPath='%TARGET%';$s.WorkingDirectory='%~dp0';$s.IconLocation='%TARGET%,0';$s.Description='AI For Everyone - one-command local LLM deployment';$s.Save()"

if exist "%LNK%" (
    echo [成功] 已在桌面创建快捷方式：
    echo   %LNK%
    echo 双击即可打开 AIE 桌面窗口。
) else (
    echo [失败] 快捷方式创建失败：%LNK%
)
echo.
pause

