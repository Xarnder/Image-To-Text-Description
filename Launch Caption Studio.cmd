@echo off
setlocal
cd /d "%~dp0"
"D:\New_ComfyUI\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\python_embeded\python.exe" -s "%~dp0launcher.py" %*
if errorlevel 1 pause
