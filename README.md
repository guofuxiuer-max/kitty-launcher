# KittyLauncher · 猫咪启动器

> 一个 **PCL 风格**的 Minecraft 启动器，跨平台（macOS / Windows / Linux），Python + PySide6 写的原生桌面程序。
> 因为 PCL2 只跑在 Windows 上，Mac 用户一直缺一个长得像它、用起来也像它的启动器，所以有了这个。

![启动页](screenshots/launch.png)

<details>
<summary>更多截图</summary>

![下载页](screenshots/download.png)
![设置页](screenshots/settings.png)
![日志页](screenshots/logs.png)

</details>

## 特性

- **版本隔离**：每个实例独立 `mods / saves / config / 资源包`，公共库和资源只存一份
- **一键装版本**：原版（正式版 / 快照全量列表）、Fabric、Forge、Quilt
- **离线登录**：填个名字就能进游戏，不用正版账号（也留了微软登录的扩展位）
- **自动挑 Java**：扫本机所有 JDK，按目标版本要求选够用且最新的那个；版本不够会提示
- **模组市场**：内置 Modrinth 搜索，按当前实例的 MC 版本 + 加载器过滤，一键下载到 `mods/`
- **实时日志**：游戏 stdout 实时进日志页，同时落盘到 `data/logs/`
- **深浅双主题**：PCL 那套紫粉配色，一键切换

## 快速开始

### 方式一：直接跑源码（推荐开发者）

```bash
git clone https://github.com/<your-name>/kitty-launcher.git
cd kitty-launcher

# macOS / Linux
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m kitty.main

# Windows
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m kitty.main
```

国内网络加个镜像更快：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 方式二：用脚本

```bash
./scripts/setup.sh     # 建 .venv + 装依赖
./run.sh               # 启动
```

### 方式三：自己打包成 app

```bash
./scripts/build_app.sh          # 需要 pyinstaller，输出 dist/KittyLauncher.app
```

Windows 上执行 `pyinstaller kitty_launcher.spec` 会得到 `dist/KittyLauncher.exe`。

## 目录结构

```
kitty-launcher/
├── kitty/
│   ├── core.py        # 引擎：Java 探测 / 实例 / 安装 / 启动 / 模组（无 Qt 依赖，可单独用）
│   ├── pages.py       # 五个页面
│   ├── widgets.py     # 卡片、导航、标签等小组件
│   ├── theme.py       # 配色 + QSS
│   └── main.py        # 主窗口与入口
├── scripts/
│   ├── setup.sh
│   ├── build_app.sh
│   └── screenshot.sh  # 无头渲染截图，用于 README / 回归
├── data/              # 运行期数据（已 gitignore）
│   ├── minecraft/     # 公共版本库：versions / libraries / assets
│   ├── instances/     # 每个实例的游戏目录
│   └── logs/
├── requirements.txt
└── kitty_launcher.spec
```

数据目录规则：源码运行时在仓库 `data/`；打包成 app 后落到
`~/Library/Application Support/KittyLauncher`（macOS）、
`%APPDATA%\KittyLauncher`（Windows）、`~/.local/share/KittyLauncher`（Linux）。
想强制指定：`export KITTY_DATA=/some/dir`。

## 它是怎么工作的（三层）

1. **`core.py`** —— 真正干活的层
   - `remote_versions()` 拉 Mojang 版本清单
   - `install_vanilla_job()` / `install_loader_job()` 起后台线程下载，进度通过 `current_job()` 轮询
   - `launch()` 拼启动命令 → `Popen` → 后台线程把 stdout 灌进日志缓冲
2. **`pages.py`** —— 只做展示与收集输入，所有耗时操作都丢给 `core` 的线程
3. **`main.py`** —— 窗口壳 + 两个 QTimer（1200ms 轮询任务、900ms 拉日志），所以 UI 永不卡死

底层下载/规则过滤/参数拼装交给 [`minecraft-launcher-lib`](https://github.com/JakobDev/minecraft-launcher-lib)（BSD-2-Clause），
它已经踩平了 macOS ARM64 原生库、legacy 版本参数、natives 解压这些坑。

## 路线图

- [ ] 微软正版登录（OAuth 设备码流程）
- [ ] 整合包导入（`.mrpack` / CurseForge zip）
- [ ] 实例内存 / JVM 参数单独覆盖
- [ ] 下载源切换（BMCLAPI 镜像加速）
- [ ] 皮肤预览
- [ ] Windows / Linux 上的成品包

## 已知限制

- 目前**只做离线登录**；多人正版服需要微软登录（路线图第 1 项）
- 首次装原版要下 200–400 MB 资源，网络差会慢
- Forge 安装依赖官方 installer，首次会比较慢

## 许可证

[MIT](LICENSE)。用的第三方库：PySide6（LGPLv3）、minecraft-launcher-lib（BSD-2-Clause）、requests（Apache-2.0）。

## 致谢

- [PCL2](https://github.com/Meloong-Git/PCL) —— 界面与交互的灵感来源（本项目为独立实现，未使用其代码）
- [minecraft-launcher-lib](https://github.com/JakobDev/minecraft-launcher-lib) —— 启动器底层
- [Modrinth](https://modrinth.com) —— 模组搜索 API
