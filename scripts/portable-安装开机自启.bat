@echo off
cd /d "%~dp0"
setlocal

rem 安装开机自启：在用户 Startup 目录创建 AIE 快捷方式（指向本便携包内 exe）
rem Windows 登录时自动启动 AIE 桌面窗口。卸载请运行 portable-卸载开机自启.bat。
rem 用法：双击运行；请勿移动本文件，需与 aife 目录保持同级。

set "TARGET=%~dp0aife\aife.exe"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\AI For Everyone.lnk"

if not exist "%TARGET%" (
    echo [失败] 未找到 "%TARGET%"。
    echo 请在本便携包目录内运行本脚本（与 aife 文件夹同级）。
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');$s.TargetPath='%TARGET%';$s.WorkingDirectory='%~dp0';$s.IconLocation='%TARGET%,0';$s.Description='AI For Everyone - one-command local LLM deployment';$s.Save()"

if exist "%LNK%" (
    echo [成功] 已安装开机自启：
    echo   %LNK%
    echo 下次登录 Windows 时将自动启动 AIE。
) else (
    echo [失败] 开机自启安装失败：%LNK%
)
echo.
pause

