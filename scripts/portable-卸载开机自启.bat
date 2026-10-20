@echo off
cd /d "%~dp0"
setlocal

rem 卸载开机自启：删除 Startup 目录中的 AIE 快捷方式（不动桌面快捷方式）。

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\AI For Everyone.lnk"

if exist "%LNK%" (
    del "%LNK%"
    if exist "%LNK%" (
        echo [失败] 删除失败：%LNK%
    ) else (
        echo [成功] 已卸载开机自启：
        echo   %LNK%
        echo 下次登录 Windows 时将不再自动启动 AIE。
    )
) else (
    echo [提示] 未找到开机自启快捷方式，无需卸载：
    echo   %LNK%
)
echo.
pause

