@echo off
rem 本机启动 Qdrant(需先下载 Windows 版二进制到本目录,文件名为 qdrant.exe)
rem 下载地址:https://github.com/qdrant/qdrant/releases 选择 x86_64-pc-windows-msvc 版本
rem 解压后将 qdrant.exe 放到本目录
cd /d %~dp0
if not exist qdrant.exe (
    echo [ERROR] 未找到 qdrant.exe
    echo 请从 https://github.com/qdrant/qdrant/releases 下载 Windows 版解压后放入本目录
    exit /b 1
)
echo 启动 Qdrant 成功:http://localhost:6333/dashboard
qdrant.exe --config-path config.yaml
