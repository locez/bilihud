# B站弹幕阅读器 (bilihud)

![PyPI version](https://img.shields.io/pypi/v/bilihud.svg)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

一个基于PyQt6和blivedm的B站弹幕阅读器，可以在Linux KDE环境下全屏游戏时显示弹幕。

> [!NOTE]
> 本项目基于 **Vibe Coding**（氛围驱动编码）模式开发，旨在快速实现创意与功能。目前仅在有限环境下进行过测试，未做大量的严谨验证。如有 Bug，欢迎反馈！

## 效果预览

### 一般模式 (Normal)
![Normal Mode](screenshots/normal.png)

### 游戏穿透模式 (Pass-through)
![Pass-through Mode](screenshots/passthrough.png)

## 功能特点

* 实时显示B站直播间弹幕
* 半透明overlay窗口，可在游戏全屏时显示
* 美观的UI界面，支持不同用户等级的颜色标识
* 支持连接/断开直播间
* 显示用户名、舰长/VIP标识
* 支持发送弹幕
* 支持扫码登录
* **注意：** 仅支持 **X11** 环境(包括 XWayland)（推荐 KDE X11）。由于 Wayland 的安全机制，无法实现完美的鼠标穿透（Pass-through）模式，因此暂不支持纯 Wayland 环境。

## 极速上手

### 1. 安装

```bash
# 1. 克隆仓库
git clone https://github.com/locez/bilihud.git
cd bilihud

# 2. 初始化子模块 (blivedm)
git submodule update --init --recursive

# 3. 环境配置与安装 (推荐使用 uv)
# 安装 uv
pip install uv

# 创建虚拟环境并同步依赖
uv sync

# 激活环境
source .venv/bin/activate
```

### 2. 启动

```bash
python -m src.bilihud.main
```

## 隐私说明 & 配置

### 自动登录 (Cookies)

为了提供完整的体验（如显示完整用户名、发送弹幕、显示舰长标识），**BiliHUD** 会尝试自动读取本地浏览器的 Bilibili 登录状态。

*   **读取范围**: 程序仅读取 `.bilibili.com` 域下的 Cookies。
*   **读取目的**: 获取 `SESSDATA` 和 `bili_jct` (CSRF Token) 仅用于与 Bilibili API 进行必要的身份验证。
*   **支持浏览器**: Chrome, Edge, Firefox。
*   **数据安全**: 您的 Cookies 仅在本地内存中使用，**绝不会**被发送到任何第三方服务器。

**注意：** **BiliHUD** 默认会尝试自动读取本地浏览器的 Bilibili 登录状态，如果无法读取，您可以在托盘图标右键菜单中选择"扫码登录"来启用扫码登录功能。



## 打包与发行 (Packaging)

### Arch Linux

本项目已发布至 AUR ([bilihud-git](https://aur.archlinux.org/packages/bilihud-git))。推荐使用 `paru` 或其他 helper 快速安装：

```bash
paru -S bilihud-git
```

此外，`packaging/arch/PKGBUILD` 提供了本地打包的示例文件。

### Gentoo Linux

如果您是 Gentoo 用户，相关包已包含在 [我的个人 overlay](https://github.com/locez/locez-overlay) 中，添加后即可安装。

本地 ebuild 示例文件位于: `packaging/gentoo/`

## 鸣谢

* [blivedm](https://github.com/xfgryujk/blivedm) - B站直播弹幕协议库
* [PyQt6](https://pypi.org/project/PyQt6/) - Python GUI框架
* [qasync](https://github.com/CabbageDevelopment/qasync) - PyQt6与asyncio集成库