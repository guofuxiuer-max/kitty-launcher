# 参与贡献

欢迎提 issue 和 PR。项目只有一个目标：**在 macOS 上把 PCL 那种顺手的感觉做出来**。

> 本项目只支持 macOS。Windows / Linux 的适配 PR 不会合入（没精力维护三套）。

## 开发环境

```bash
git clone <repo> && cd kitty-launcher
./scripts/setup.sh      # 自动挑 Python 3.10+，建 .venv
./run.sh                # 跑起来
```

UI 改了之后重渲染截图，方便对比：

```bash
./scripts/screenshot.sh
```

## 提 issue 前

先跑一遍环境自检，把输出贴进去：

```bash
./run.sh --env
```

日志在「日志」页，或 `data/logs/` 里最新的文件。

## 代码结构

| 文件 | 职责 |
|---|---|
| `kitty/core.py` | 引擎：实例 / 安装 / 启动 / 模组 / 诊断（不依赖 Qt） |
| `kitty/auth.py` | 微软登录（设备码 + Xbox 链 + token 续期） |
| `kitty/skin.py` / `skin3d.py` | 皮肤解析与 3D 渲染（纯 QPainter） |
| `kitty/pages.py` | 六个页面 |
| `kitty/dialogs.py` | 实例设置 / 登录 / 诊断 / 皮肤预览对话框 |
| `kitty/main.py` | 主窗口、导航、启动入口 |
| `kitty/theme.py` | 配色 + QSS |

## PR 约定

- 只改你要改的那一块，别顺手重构
- 动引擎（`core.py`）请说明测试方式：装了哪个版本、在哪个平台
- 新功能请在 README 的路线图里打勾
- 提交信息用中文或英文都行，写清「做了什么」
