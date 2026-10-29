"""给没有 ensurepip 的 Python 装一个 pip。

macOS 上系统自带的 python3 是 3.9（太老），Homebrew 版有时又缺 ensurepip，
导致 `python -m venv` 直接失败。这里绕开 ensurepip：
直接从 PyPI 镜像下载 pip 的 wheel，解压进 venv 的 site-packages。

用法：python _bootstrap_pip.py <simple-index-url> <site-packages-dir>
"""
from __future__ import annotations

import io
import pathlib
import re
import sys
import urllib.parse
import urllib.request
import zipfile

UA = {"User-Agent": "KittyLauncher-setup/1.0"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def version_key(name: str) -> tuple:
    m = re.search(r"pip-([0-9][^-]*)-", name)
    if not m:
        return (0,)
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[._]", m.group(1)))


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: _bootstrap_pip.py <simple-index-url> <site-packages-dir>")
        return 2
    index = sys.argv[1].rstrip("/")
    target = pathlib.Path(sys.argv[2])
    target.mkdir(parents=True, exist_ok=True)

    page = index + "/pip/"
    html = fetch(page).decode("utf-8", "replace")
    links = [urllib.parse.urljoin(page + "/", h) for h in re.findall(r'href="([^"]+)"', html)]
    # 去掉 #sha256=xxx 片段再判断文件名
    links = [u.split("#")[0] for u in links]
    wheels = [u for u in links if re.search(r"pip-(\d[^/]*)-py3-none-any\.whl$", u)]
    if not wheels:
        print("没在镜像上找到 pip 的 wheel，检查网络或换 PIP_INDEX_URL")
        return 1
    wheels.sort(key=lambda u: version_key(u.rsplit("/", 1)[-1]))
    wheel = wheels[-1]
    print(f"下载 {wheel.rsplit('/', 1)[-1]}")
    data = fetch(wheel)

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(target)

    # 顺手清掉可能已经存在的旧 pip 目录残留标记
    print(f"pip 已解压到 {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
