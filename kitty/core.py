"""KittyLauncher 核心引擎：Java 探测 / 实例 / 安装 / 启动 / 模组。

依赖 vendored 的 minecraft-launcher-lib（BSD-2-Clause）负责
版本补全、规则过滤、库与资源下载、启动参数拼装这些脏活；
本模块只管 PCL 那套"用户看得见"的逻辑：实例隔离、多 Java、日志、任务。
"""
from __future__ import annotations

import json
import os
import platform
import sys
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import minecraft_launcher_lib as mll
from minecraft_launcher_lib import command as mlc
from minecraft_launcher_lib import fabric as mlf
from minecraft_launcher_lib import forge as mlg
from minecraft_launcher_lib import install as mli
from minecraft_launcher_lib import quilt as mlq
from minecraft_launcher_lib import utils as mlu

# 官方 CDN 偶尔会挂住不返回，requests 默认没有超时 → 任务永远卡在"下载中"。
# 这里给全局兜一个读超时（流式下载时按每个 chunk 计算），避免界面假死。
import requests as _requests  # noqa: E402

_get_orig = _requests.get
_request_orig = _requests.Session.request


def _get_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", 45)
    return _get_orig(*args, **kwargs)


def _request_with_timeout(self, method, url, **kwargs):
    kwargs.setdefault("timeout", 45)
    return _request_orig(self, method, url, **kwargs)


_requests.get = _get_with_timeout
_requests.Session.request = _request_with_timeout


def _install_mirror_hook() -> None:
    """在 timeout 补丁之上再加一层 URL 改写，切换镜像不需要重启进程。"""
    cur_get = _requests.get
    cur_req = _requests.Session.request

    def get(url, *a, **kw):
        return cur_get(_rewrite_url(url) if isinstance(url, str) else url, *a, **kw)

    def request(self, method, url, *a, **kw):
        return cur_req(self, method, _rewrite_url(url) if isinstance(url, str) else url, *a, **kw)

    _requests.get = get
    _requests.Session.request = request


_install_mirror_hook()

from .paths import (  # noqa: E402
    VERSION,
    ACCOUNTS_PATH,
    APP_DIR,
    CONFIG_PATH,
    DATA,
    INSTANCES_DIR,
    INSTANCES_JSON,
    LOGS_DIR,
    MC_DIR,
    ROOT,
)




DEFAULT_CONFIG = {
    "username": "Steve",
    "memoryMB": 4096,
    "javaPath": "",
    "width": 1280,
    "height": 720,
    "selectedInstance": "",
    "theme": "dark",
    "jvmArgs": "",          # 全局追加 JVM 参数，例：-XX:+UseG1GC
    "mirror": "official",   # official | bmclapi
    "azureClientId": "",    # 微软登录用的 Azure 应用 ID
}

# 实例级覆盖，0 / 空串 表示"跟随全局"（PCL 的版本设置就是这么做的）
INSTANCE_SETTING_DEFAULTS = {
    "memoryMB": 0,
    "width": 0,
    "height": 0,
    "javaPath": "",
    "jvmArgs": "",
    "gameArgs": "",
}

# ---------------------------------------------------------------- 配置文件

_lock = threading.RLock()


def load_config() -> dict:
    with _lock:
        if CONFIG_PATH.exists():
            try:
                cfg = json.loads(CONFIG_PATH.read_text("utf-8"))
            except Exception:
                cfg = {}
        else:
            cfg = {}
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg or {})
        return merged


def save_config(patch: dict) -> dict:
    with _lock:
        cfg = load_config()
        for k, v in (patch or {}).items():
            if k in DEFAULT_CONFIG:
                cfg[k] = v
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    if "mirror" in (patch or {}):
        set_mirror(cfg.get("mirror", "official"))
    return cfg


# ---------------------------------------------------------------- 下载镜像

_MIRROR_MAP = {
    "bmclapi": {
        "https://launchermeta.mojang.com": "https://bmclapi2.bangbang93.com",
        "https://piston-meta.mojang.com": "https://bmclapi2.bangbang93.com",
        "https://piston-data.mojang.com": "https://bmclapi2.bangbang93.com",
        "https://libraries.minecraft.net": "https://bmclapi2.bangbang93.com/maven",
        "https://resources.download.minecraft.net": "https://bmclapi2.bangbang93.com/assets",
        "https://maven.minecraftforge.net": "https://bmclapi2.bangbang93.com/maven",
        "https://maven.fabricmc.net": "https://bmclapi2.bangbang93.com/maven",
        "https://maven.neoforged.net": "https://bmclapi2.bangbang93.com/maven",
        "https://meta.fabricmc.net": "https://bmclapi2.bangbang93.com/fabric-meta",
    }
}

_active_mirror = "official"


def _rewrite_url(url: str) -> str:
    table = _MIRROR_MAP.get(_active_mirror) or {}
    for src, dst in table.items():
        if url.startswith(src):
            return dst + url[len(src):]
    return url


def set_mirror(name: str) -> str:
    """切换下载源。官方 CDN 在国内经常抽风，BMCLAPI 是国内镜像（不是盗版源，只是缓存）。"""
    global _active_mirror
    name = (name or "official").lower()
    _active_mirror = name if name in _MIRROR_MAP else "official"
    return _active_mirror


def current_mirror() -> str:
    return _active_mirror


# ---------------------------------------------------------------- Java 探测

_java_cache: dict[str, dict] = {}


def _java_major(version: str) -> int:
    v = (version or "").strip()
    if v.startswith("1."):
        m = re.match(r"1\.(\d+)", v)
        return int(m.group(1)) if m else 8
    m = re.match(r"(\d+)", v)
    return int(m.group(1)) if m else 0


def java_info(path: str) -> dict | None:
    if not path:
        return None
    p = str(Path(path).expanduser())
    if p in _java_cache:
        return _java_cache[p]
    if not os.path.isfile(p) or not os.access(p, os.X_OK):
        return None
    try:
        out = subprocess.run([p, "-version"], capture_output=True, text=True, timeout=15)
        text = (out.stderr or "") + (out.stdout or "")
        m = re.search(r'version "([^"]+)"', text)
        ver = m.group(1) if m else "?"
        if "minecraft/runtime" in p.replace(os.sep, "/"):
            vendor = "Mojang 自带"
        else:
            vendor = "Oracle" if "Oracle" in text else ("Temurin" if "Temurin" in text else ("Homebrew" if "Homebrew" in text else "OpenJDK"))
        info = {"path": p, "version": ver, "major": _java_major(ver), "vendor": vendor}
    except Exception:
        return None
    _java_cache[p] = info
    return info


def _runtime_java_paths() -> list[str]:
    """Mojang 官方 JRE：装版本时顺带下到 data/minecraft/runtime/ 里的那份。"""
    import glob

    # 布局：runtime/<组件>/<平台架构>/<组件>/[jre.bundle/Contents/Home/]bin/java
    pats = [
        str(MC_DIR / "runtime" / "*" / "*" / "*" / "jre.bundle" / "Contents" / "Home" / "bin" / "java"),
        str(MC_DIR / "runtime" / "*" / "*" / "*" / "bin" / "java"),
        str(MC_DIR / "runtime" / "*" / "*" / "*" / "bin" / "java.exe"),
        # 少数旧布局只有两层
        str(MC_DIR / "runtime" / "*" / "*" / "bin" / "java"),
    ]
    found: list[str] = []
    for pat in pats:
        found.extend(sorted(glob.glob(pat), reverse=True))
    return found


def _candidate_java_paths() -> list[str]:
    import glob

    cands: list[str] = list(_runtime_java_paths())
    cfg = load_config()
    if cfg.get("javaPath"):
        cands.append(cfg["javaPath"])
    if os.environ.get("JAVA_HOME"):
        cands.append(os.path.join(os.environ["JAVA_HOME"], "bin", "java"))
    which = shutil.which("java")
    if which:
        cands.append(which)
    for pattern in (
        "/opt/homebrew/opt/openjdk*/bin/java",
        "/usr/local/opt/openjdk*/bin/java",
        "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java",
        "/opt/homebrew/Cellar/openjdk*/*/libexec/openjdk.jdk/Contents/Home/bin/java",
        str(Path.home() / "Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java"),
        str(ROOT.parent / "tools" / "jdk" / "*" / "Contents" / "Home" / "bin" / "java"),
    ):
        cands.extend(sorted(glob.glob(pattern), reverse=True))
    seen, out = set(), []
    for c in cands:
        rp = os.path.realpath(os.path.expanduser(c))
        if rp in seen:
            continue
        seen.add(rp)
        out.append(os.path.expanduser(c))
    return out


def list_java() -> list[dict]:
    infos = []
    for p in _candidate_java_paths():
        info = java_info(p)
        if info and info["major"] >= 8:
            infos.append(info)
    infos.sort(key=lambda i: (-i["major"], i["path"]))
    return infos


def version_java_major(version_id: str, _depth: int = 0) -> int:
    """读版本 json 里声明的 javaVersion.majorVersion；找不到就一直往 inheritsFrom 追。"""
    jf = MC_DIR / "versions" / version_id / f"{version_id}.json"
    if not jf.exists() or _depth > 4:
        return 8
    try:
        data = json.loads(jf.read_text("utf-8"))
    except Exception:
        return 8
    major = (data.get("javaVersion") or {}).get("majorVersion")
    if major:
        return int(major)
    parent = data.get("inheritsFrom")
    if parent:
        return version_java_major(parent, _depth + 1)
    return 8


def pick_java(need_major: int) -> tuple[str | None, dict | None]:
    """挑一个够用且最省的最新 Java：major >= 需求里最小的那个。"""
    javas = list_java()
    if not javas:
        return None, None
    cfg = load_config()
    if cfg.get("javaPath"):
        info = java_info(cfg["javaPath"])
        if info:
            return info["path"], info
    ok = [j for j in javas if j["major"] >= need_major]
    if ok:
        best = min(ok, key=lambda j: j["major"])
        return best["path"], best
    top = max(javas, key=lambda j: j["major"])
    return top["path"], top


# ---------------------------------------------------------------- 实例

def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "-", (name or "").strip())
    return cleaned.strip("-") or "instance"


def load_instances() -> list[dict]:
    with _lock:
        if not INSTANCES_JSON.exists():
            return []
        try:
            data = json.loads(INSTANCES_JSON.read_text("utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []


def save_instances(items: list[dict]) -> None:
    with _lock:
        INSTANCES_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


def get_instance(name: str) -> dict | None:
    for inst in load_instances():
        if inst["name"] == name:
            return inst
    return None


def instance_settings(inst: dict) -> dict:
    """合并「实例设置」与「全局设置」，0 / 空串 视为跟随全局。"""
    cfg = load_config()
    raw = inst.get("settings") or {}
    merged = {}
    merged["memoryMB"] = int(raw.get("memoryMB") or 0) or int(cfg.get("memoryMB") or 4096)
    merged["width"] = int(raw.get("width") or 0) or int(cfg.get("width") or 1280)
    merged["height"] = int(raw.get("height") or 0) or int(cfg.get("height") or 720)
    merged["javaPath"] = raw.get("javaPath") or cfg.get("javaPath") or ""
    merged["jvmArgs"] = " ".join(
        x for x in (str(cfg.get("jvmArgs") or "").strip(), str(raw.get("jvmArgs") or "").strip()) if x
    )
    merged["gameArgs"] = str(raw.get("gameArgs") or "").strip()
    merged["raw"] = dict(raw)
    return merged


def update_instance_settings(name: str, patch: dict) -> dict | None:
    inst = get_instance(name)
    if not inst:
        return None
    raw = dict(inst.get("settings") or {})
    for k in INSTANCE_SETTING_DEFAULTS:
        if k in patch:
            raw[k] = patch[k]
    return update_instance(name, settings=raw)


def instance_dir(name: str) -> Path:
    return INSTANCES_DIR / _safe_name(name)


def create_instance(name: str, mc_version: str, loader: str = "vanilla", loader_version: str = "") -> dict:
    existing = load_instances()
    base, i = name.strip(), 2
    while any(x["name"] == base for x in existing):
        base = f"{name.strip()}-{i}"
        i += 1
    gdir = instance_dir(base)
    for sub in ("mods", "config", "saves", "resourcepacks", "shaderpacks", "logs", "crash-reports"):
        (gdir / sub).mkdir(parents=True, exist_ok=True)
    inst = {
        "name": base,
        "mcVersion": mc_version,
        "versionId": mc_version,
        "loader": loader,
        "loaderVersion": loader_version,
        "created": int(time.time()),
        "lastPlayed": 0,
        "playCount": 0,
    }
    existing.append(inst)
    save_instances(existing)
    return inst


def update_instance(name: str, **patch) -> dict | None:
    items = load_instances()
    for inst in items:
        if inst["name"] == name:
            inst.update(patch)
            save_instances(items)
            return inst
    return None


def delete_instance(name: str) -> bool:
    items = [i for i in load_instances() if i["name"] != name]
    save_instances(items)
    gdir = instance_dir(name)
    if gdir.exists():
        shutil.rmtree(gdir, ignore_errors=True)
    return True


def instance_view(inst: dict) -> dict:
    gdir = instance_dir(inst["name"])
    mods = list((gdir / "mods").glob("*.jar")) if (gdir / "mods").exists() else []
    java_path, java = pick_java(version_java_major(inst["versionId"]))
    return {
        **inst,
        "dir": str(gdir),
        "modCount": len(mods),
        "javaPath": java_path,
        "java": java,
        "installed": is_version_installed(inst["versionId"]),
    }


# ---------------------------------------------------------------- 远程版本

_manifest_cache: dict = {"ts": 0, "data": []}


def remote_versions(force: bool = False) -> list[dict]:
    with _lock:
        if not force and _manifest_cache["data"] and time.time() - _manifest_cache["ts"] < 600:
            return _manifest_cache["data"]
    raw = mlu.get_version_list()
    data = [
        {
            "id": v["id"],
            "type": v["type"],
            "releaseTime": str(v.get("releaseTime", ""))[:19],
            "stable": bool(v.get("type") == "release"),
        }
        for v in raw
    ]
    _manifest_cache.update({"ts": time.time(), "data": data})
    return data


def installed_version_list() -> list[dict]:
    try:
        return mlu.get_installed_versions(str(MC_DIR))
    except Exception:
        return []


def is_version_installed(version_id: str, _depth: int = 0) -> bool:
    """版本 json + 客户端 jar 都在才算装好；带 inheritsFrom 的（Fabric/Forge）看父版本。"""
    base = MC_DIR / "versions" / version_id
    jf = base / f"{version_id}.json"
    if not jf.exists():
        return False
    if (base / f"{version_id}.jar").exists():
        return True
    if _depth > 3:
        return False
    try:
        data = json.loads(jf.read_text("utf-8"))
    except Exception:
        return False
    parent = data.get("inheritsFrom")
    return is_version_installed(parent, _depth + 1) if parent else False


# ---------------------------------------------------------------- 任务(安装)

class Job:
    def __init__(self, job_id: str, title: str):
        self.id = job_id
        self.title = title
        self.status = "排队中"
        self.progress = 0
        self.total = 0
        self.state = "running"     # running | done | error
        self.error = ""
        self.started = time.time()
        self.finished = 0.0

    def view(self) -> dict:
        pct = 0
        if self.total > 0:
            pct = max(0, min(100, int(self.progress * 100 / self.total)))
        return {
            "id": self.id, "title": self.title, "status": self.status,
            "progress": self.progress, "total": self.total, "percent": pct,
            "state": self.state, "error": self.error,
            "elapsed": round((self.finished or time.time()) - self.started, 1),
        }


_jobs: dict[str, Job] = {}
_current_job: str = ""
_jobs_lock = threading.Lock()


def current_job() -> dict | None:
    with _jobs_lock:
        jid = _current_job
    job = _jobs.get(jid) if jid else None
    return job.view() if job else None


def start_job(title: str, fn) -> dict:
    with _jobs_lock:
        for j in _jobs.values():
            if j.state == "running":
                return {"error": "已有任务在跑，等它结束喵"}
        job = Job(uuid.uuid4().hex[:8], title)
        _jobs[job.id] = job
        global _current_job
        _current_job = job.id

    def cb() -> dict:
        def set_status(s):
            job.status = str(s)

        def set_progress(p):
            job.progress = int(p)

        def set_max(m):
            job.total = int(m)

        return {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}

    def runner():
        try:
            fn(job, cb())
            job.state = "done"
            job.status = "完成"
            job.progress = job.total or job.progress
        except Exception as exc:  # noqa: BLE001
            job.state = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "失败"
            log(f"[错误] {job.title} 失败：{job.error}")
        finally:
            job.finished = time.time()

    threading.Thread(target=runner, name=f"job-{job.id}", daemon=True).start()
    return job.view()



def _verify_client_jar(version: str, job: "Job", cb: dict) -> None:
    """下载中断会留下半截 jar，这里按版本清单里的大小校验，坏了删掉重下一次。"""
    jf = MC_DIR / "versions" / version / f"{version}.json"
    jar = MC_DIR / "versions" / version / f"{version}.jar"
    try:
        data = json.loads(jf.read_text("utf-8"))
        expect = ((data.get("downloads") or {}).get("client") or {}).get("size")
    except Exception:
        return
    if not expect or not jar.exists():
        return
    if jar.stat().st_size == expect:
        return
    job.status = "客户端 jar 校验失败，重新下载"
    jar.unlink(missing_ok=True)
    mli.install_minecraft_version(version, str(MC_DIR), callback=cb)


def install_vanilla_job(version: str, instance: str = "") -> dict:
    def work(job: Job, cb):
        job.status = f"安装原版 {version}"
        mli.install_minecraft_version(version, str(MC_DIR), callback=cb)
        _verify_client_jar(version, job, cb)
        if instance:
            update_instance(instance, versionId=version, mcVersion=version, loader="vanilla", loaderVersion="")

    return start_job(f"安装原版 {version}", work)


def loader_versions(loader: str, mc_version: str) -> list[str]:
    try:
        if loader == "fabric":
            return list(mlf.get_all_loader_versions())
        if loader == "quilt":
            return list(mlq.get_all_loader_versions())
        if loader == "forge":
            out = []
            for v in mlg.list_forge_versions():
                if v.startswith(mc_version + "-"):
                    out.append(v.split("-", 1)[1])
            return out
    except Exception:
        pass
    return []


def install_loader_job(instance: str, loader: str) -> dict:
    inst = get_instance(instance)
    if not inst:
        return {"error": "实例不存在"}

    def work(job: Job, cb):
        mc = inst["mcVersion"]
        if not is_version_installed(mc):
            job.status = f"先补原版 {mc}"
            mli.install_minecraft_version(mc, str(MC_DIR), callback=cb)
        need = version_java_major(mc)
        java, _ = pick_java(max(need, 17))
        if loader == "fabric":
            lv = mlf.get_latest_loader_version()
            job.status = f"安装 Fabric {lv}"
            mlf.install_fabric(mc, str(MC_DIR), lv, callback=cb, java=java)
            vid = f"fabric-loader-{lv}-{mc}"
        elif loader == "quilt":
            lv = mlq.get_latest_loader_version()
            job.status = f"安装 Quilt {lv}"
            mlq.install_quilt(mc, str(MC_DIR), lv, callback=cb, java=java)
            vid = f"quilt-loader-{lv}-{mc}"
        elif loader == "forge":
            cands = loader_versions("forge", mc)
            if not cands:
                raise RuntimeError(f"官方没有 {mc} 的 Forge")
            fv = cands[0]
            job.status = f"安装 Forge {fv}"
            mlg.install_forge_version(f"{mc}-{fv}", str(MC_DIR), callback=cb, java=java)
            vid = f"{mc}-forge-{fv}"
        else:
            raise RuntimeError("未知加载器")
        update_instance(instance, versionId=vid, loader=loader, loaderVersion=lv if loader != "forge" else fv)

    return start_job(f"{loader} 安装 · {instance}", work)


# ---------------------------------------------------------------- 启动游戏

_log_buffer: deque = deque(maxlen=6000)
_log_seq = 0
_log_lock = threading.Lock()
_current_proc: subprocess.Popen | None = None
_current_instance = ""
_last_exit: dict = {"code": None, "instance": "", "at": 0, "seen": True, "userStopped": False}
_stop_requested = False


_XML_MSG = re.compile(r"<log4j:Message><!\[CDATA\[(.*?)\]\]></log4j:Message>", re.S)


def clean_line(line: str) -> str:
    """官方 log 配置输出的是 log4j XML 事件（还可能跨多行），转成人能看的一行。"""
    m = _XML_MSG.search(line)
    if m:
        return m.group(1).strip()
    if "[CDATA[" in line:
        tail = line.split("[CDATA[", 1)[1]
        for end in ("]]></log4j:Message>", "]]>", "]]"):
            if end in tail:
                tail = tail.split(end, 1)[0]
                break
        return tail.strip()
    stripped = line.strip()
    if stripped.startswith("<log4j") or stripped.startswith("</log4j") or stripped.startswith("</log4j:Message>"):
        return ""
    return line.rstrip("\n")


def log(line: str) -> None:
    global _log_seq
    line = clean_line(line)
    if not line or not line.strip():
        return
    with _log_lock:
        _log_seq += 1
        _log_buffer.append({"seq": _log_seq, "t": time.strftime("%H:%M:%S"), "line": line})


def get_logs(since: int = 0) -> dict:
    with _log_lock:
        lines = [x for x in _log_buffer if x["seq"] > since]
    return {"lines": lines, "next": _log_seq}


def offline_uuid(username: str) -> str:
    return uuid.uuid3(uuid.NAMESPACE_DNS, "OfflinePlayer:" + username).hex


def build_command(inst: dict) -> dict:
    from . import auth as _auth  # 放在函数内，避免 paths/core 的初始化顺序问题

    cfg = load_config()

    # 有正版账号就用正版身份，否则退回离线
    ident = None
    try:
        ident = _auth.launch_identity()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"正版登录状态失效，请在设置页重新登录：{exc}") from exc

    if ident:
        username = ident["username"]
        player_uuid = ident["uuid"]
        access_token = ident["token"]
    else:
        username = (cfg.get("username") or "Steve").strip() or "Steve"
        player_uuid = offline_uuid(username)
        access_token = "0"
    need = version_java_major(inst["versionId"])
    eff = instance_settings(inst)
    java, jinfo = (None, None)
    if eff["javaPath"]:
        info = java_info(eff["javaPath"])
        if info:
            java, jinfo = info["path"], info
    if not java:
        java, jinfo = pick_java(need)
    if not java:
        raise RuntimeError("没找到可用的 Java，去设置页指一个 java 可执行文件")
    mem = eff["memoryMB"]
    extra_jvm = eff["jvmArgs"].split() if eff["jvmArgs"] else []
    opts = {
        "username": username,
        "uuid": player_uuid,
        "token": access_token,
        "executablePath": java,
        "defaultExecutablePath": java,
        "jvmArguments": [f"-Xmx{mem}M", "-Xms512M", "-Dfile.encoding=UTF-8", *extra_jvm],
        "launcherName": "KittyLauncher",
        "launcherVersion": VERSION,
        "gameDirectory": str(instance_dir(inst["name"])),
        "customResolution": True,
        "resolutionWidth": str(eff["width"]),
        "resolutionHeight": str(eff["height"]),
        "enableLoggingConfig": True,
    }
    cmd = mlc.get_minecraft_command(inst["versionId"], str(MC_DIR), opts)
    if eff["gameArgs"]:
        cmd.extend(eff["gameArgs"].split())
    return {"cmd": cmd, "java": jinfo, "requiredMajor": need, "settings": eff}


def launch(instance: str) -> dict:
    global _current_proc, _current_instance
    inst = get_instance(instance)
    if not inst:
        return {"error": "实例不存在"}
    if _current_proc and _current_proc.poll() is None:
        return {"error": "已经有一个游戏在跑了"}
    if not is_version_installed(inst["versionId"]):
        return {"error": f"版本没装好：{inst['versionId']}"}

    try:
        built = build_command(inst)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    gdir = instance_dir(inst["name"])
    log_file = LOGS_DIR / f"{_safe_name(inst['name'])}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    log(f"===== 启动 {inst['name']} ({inst['versionId']}) =====")
    log("java: " + built["java"]["path"] + f"  ({built['java']['version']})")
    log(" ".join(built["cmd"])[:2000])

    try:
        proc = subprocess.Popen(
            built["cmd"], cwd=str(gdir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, errors="replace",
        )
    except Exception as exc:  # noqa: BLE001
        log(f"[错误] 进程起不来：{exc}")
        return {"error": f"进程起不来：{exc}"}

    _current_proc = proc
    _current_instance = inst["name"]
    update_instance(inst["name"], lastPlayed=int(time.time()), playCount=int(inst.get("playCount", 0)) + 1)

    def pump():
        try:
            with open(log_file, "a", encoding="utf-8", errors="replace") as fh:
                for line in proc.stdout:  # type: ignore[union-attr]
                    clean = clean_line(line)
                    if clean.strip():
                        log(clean)
                        fh.write(clean.rstrip("\n") + "\n")
                        fh.flush()
        finally:
            global _stop_requested
            code = proc.wait()
            _last_exit.update(
                {
                    "code": code,
                    "instance": inst["name"],
                    "at": int(time.time()),
                    "seen": False,
                    "userStopped": _stop_requested,
                }
            )
            _stop_requested = False
            log(f"===== 游戏退出，代码 {code} =====")

    threading.Thread(target=pump, name="log-pump", daemon=True).start()
    return {"pid": proc.pid, "cmd": built["cmd"], "logFile": str(log_file)}


def stop_game() -> dict:
    global _current_proc, _stop_requested
    if not _current_proc or _current_proc.poll() is not None:
        return {"error": "没有在跑的游戏"}
    _stop_requested = True
    _current_proc.terminate()
    try:
        _current_proc.wait(timeout=10)
    except Exception:
        _current_proc.kill()
    return {"ok": True}


def game_status() -> dict:
    running = bool(_current_proc and _current_proc.poll() is None)
    return {
        "running": running,
        "instance": _current_instance if running else "",
        "pid": _current_proc.pid if running and _current_proc else 0,
        "lastExit": dict(_last_exit),
    }


def consume_exit() -> dict | None:
    """UI 取一次退出信息，取完标记已读，避免每轮都弹提示。"""
    if _last_exit.get("seen"):
        return None
    _last_exit["seen"] = True
    return dict(_last_exit)


# ---------------------------------------------------------------- Modrinth

MODRINTH = "https://api.modrinth.com/v2"
_http_headers = {"User-Agent": f"KittyLauncher/{VERSION}"}


def _get_json(url: str, params: dict | None = None, timeout: int = 20):
    import requests

    r = requests.get(url, params=params, headers=_http_headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def modrinth_search(query: str, mc_version: str, loader: str, limit: int = 18, offset: int = 0) -> dict:
    facets = [["project_type:mod"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    if loader and loader != "vanilla":
        facets.append([f"categories:{loader}"])
    try:
        data = _get_json(
            f"{MODRINTH}/search",
            {
                "query": query or "",
                "facets": json.dumps(facets),
                "limit": limit,
                "offset": offset,
                "index": "downloads",
            },
        )
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        if "Timeout" in name or "Connection" in name or "Request" in name:
            return {"error": "连不上 Modrinth（网络问题），稍后再试或者开个代理喵", "hits": []}
        return {"error": f"Modrinth 请求失败：{exc}", "hits": []}
    hits = []
    for h in data.get("hits", []):
        hits.append({
            "id": h.get("project_id"),
            "slug": h.get("slug"),
            "title": h.get("title"),
            "description": h.get("description"),
            "downloads": h.get("downloads"),
            "icon": h.get("icon_url"),
            "author": h.get("author"),
            "categories": h.get("categories", [])[:4],
        })
    return {"hits": hits, "total": data.get("total_hits", len(hits))}


def install_mod_from_modrinth(instance: str, project_id: str) -> dict:
    inst = get_instance(instance)
    if not inst:
        return {"error": "实例不存在"}
    loader = inst.get("loader") or "vanilla"
    mc = inst.get("mcVersion") or ""
    if loader == "vanilla":
        return {"error": "原版实例装不了模组，先用 Fabric/Forge 建实例"}
    try:
        versions = _get_json(
            f"{MODRINTH}/project/{project_id}/version",
            {"loaders": json.dumps([loader]), "game_versions": json.dumps([mc])},
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"查不到适配版本：{exc}"}
    if not versions:
        return {"error": f"这个模组没有 {mc} + {loader} 的版本"}
    target = versions[0]
    files = target.get("files") or []
    primary = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not primary:
        return {"error": "版本里没有文件"}
    mods_dir = instance_dir(instance) / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    dest = mods_dir / primary["filename"]
    import requests

    try:
        with requests.get(primary["url"], headers=_http_headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(1 << 16):
                    fh.write(chunk)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"下载失败：{exc}"}
    log(f"已安装模组 {primary['filename']} → {instance}")
    return {"ok": True, "file": primary["filename"], "version": target.get("version_number"), "size": dest.stat().st_size}


def list_mods(instance: str) -> list[dict]:
    d = instance_dir(instance) / "mods"
    out = []
    if d.exists():
        for f in sorted(d.glob("*.jar")):
            out.append({"file": f.name, "size": f.stat().st_size})
    return out


def remove_mod(instance: str, filename: str) -> dict:
    d = instance_dir(instance) / "mods"
    target = (d / filename).resolve()
    if d.resolve() not in target.parents:
        return {"error": "路径不对"}
    if target.exists():
        target.unlink()
        return {"ok": True}
    return {"error": "文件不存在"}


# ---------------------------------------------------------------- 汇总

def bootstrap() -> dict:
    cfg = load_config()
    instances = [instance_view(i) for i in load_instances()]
    sel = cfg.get("selectedInstance") or (instances[0]["name"] if instances else "")
    if instances and not any(i["name"] == sel for i in instances):
        sel = instances[0]["name"]
    return {
        "config": cfg,
        "instances": instances,
        "selected": sel,
        "java": list_java(),
        "game": game_status(),
        "job": current_job(),
        "platform": f"{platform.system()} {platform.machine()}",
        "mcDir": str(MC_DIR),
        "dataDir": str(DATA),
    }


# ---------------------------------------------------------------- 杂项

def open_path(path: str) -> dict:
    import subprocess
    if not os.path.isdir(path):
        return {"error": "目录不存在"}
    subprocess.Popen(["open", path])
    return {"ok": True, "path": path}


# ---------------------------------------------------------------- 整合包 / 实例交换

from minecraft_launcher_lib import mrpack as _mrpack  # noqa: E402


def modpack_info(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": "文件不存在"}
    if p.suffix.lower() not in (".mrpack", ".zip"):
        return {"error": "只支持 .mrpack（Modrinth 整合包）和 .zip（带 modrinth.index.json 的包）"}
    try:
        info = _mrpack.get_mrpack_information(str(p))
        return {
            "name": info.get("name", p.stem),
            "summary": info.get("summary", ""),
            "version": info.get("versionId", ""),
            "mcVersion": info.get("minecraftVersion", ""),
            "optionalFiles": info.get("optionalFiles", []),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"解析整合包失败：{exc}"}


def import_modpack_job(path: str, name: str = "") -> dict:
    """把 .mrpack 装进一个新实例（mods/config 进实例目录，游戏库进公共目录）。"""
    info = modpack_info(path)
    if info.get("error"):
        return {"error": info["error"]}

    def work(job: Job, cb):
        src = str(Path(path).expanduser())
        mc = info["mcVersion"]
        inst = create_instance(name or info["name"] or Path(src).stem, mc)
        job.status = f"下载整合包文件 · {info['name']}"
        _mrpack.install_mrpack(src, str(MC_DIR), str(instance_dir(inst["name"])), callback=cb)
        vid = _mrpack.get_mrpack_launch_version(src)
        loader = (
            "fabric" if vid.startswith("fabric-loader")
            else "quilt" if vid.startswith("quilt-loader")
            else "neoforge" if "neoforge" in vid
            else "forge" if "forge" in vid
            else "vanilla"
        )
        update_instance(
            inst["name"],
            versionId=vid,
            mcVersion=mc,
            loader=loader,
            modpack={"name": info["name"], "version": info["version"], "enabled": True},
        )
        job.status = "整合包安装完成"

    return start_job(f"导入整合包 · {info['name']}", work)


_EXPORT_SKIP = ("logs", "crash-reports", "downloads", ".cache")


def export_instance(name: str, dest: str) -> dict:
    """把实例打成 zip（不含日志/崩溃报告），方便分享给朋友。"""
    import zipfile

    inst = get_instance(name)
    if not inst:
        return {"error": "实例不存在"}
    src = instance_dir(name)
    dest_path = Path(dest).expanduser()
    manifest = {
        "kittyVersion": 1,
        "name": inst["name"],
        "mcVersion": inst.get("mcVersion", ""),
        "versionId": inst.get("versionId", ""),
        "loader": inst.get("loader", "vanilla"),
        "loaderVersion": inst.get("loaderVersion", ""),
        "settings": inst.get("settings", {}),
    }
    try:
        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("kitty-instance.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for f in src.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(src)
                if rel.parts and rel.parts[0] in _EXPORT_SKIP:
                    continue
                zf.write(f, str(Path("instance") / rel))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"导出失败：{exc}"}
    return {"ok": True, "path": str(dest_path), "size": dest_path.stat().st_size}


def import_instance_zip(path: str, name: str = "") -> dict:
    """导入 export_instance 生成的 zip，变成一个普通实例。"""
    import zipfile

    src = Path(path).expanduser()
    if not src.exists():
        return {"error": "文件不存在"}
    try:
        with zipfile.ZipFile(src) as zf:
            manifest = json.loads(zf.read("kitty-instance.json")) if "kitty-instance.json" in zf.namelist() else {}
            target_name = name or manifest.get("name") or src.stem
            inst = create_instance(target_name, manifest.get("mcVersion") or "未知")
            base = instance_dir(inst["name"])
            for info in zf.infolist():
                if info.is_dir() or not info.filename.startswith("instance/"):
                    continue
                rel = info.filename[len("instance/"):]
                out = (base / rel).resolve()
                if base.resolve() not in out.parents:
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as fh, open(out, "wb") as w:
                    w.write(fh.read())
    except Exception as exc:  # noqa: BLE001
        return {"error": f"导入失败：{exc}"}

    update_instance(
        inst["name"],
        versionId=manifest.get("versionId") or inst["mcVersion"],
        loader=manifest.get("loader", "vanilla"),
        loaderVersion=manifest.get("loaderVersion", ""),
        settings=manifest.get("settings", {}),
    )
    return {"ok": True, "instance": core_view(inst["name"])}


def core_view(name: str) -> dict | None:
    inst = get_instance(name)
    return instance_view(inst) if inst else None


# ---------------------------------------------------------------- 日志诊断

CRASH_RULES: list[tuple[str, str, str, str, str]] = [
    (r"java\.lang\.OutOfMemoryError|Java heap space|GC overhead limit exceeded",
     "err", "内存不够",
     "游戏申请的内存超过了 -Xmx，常见于加了很多模组或开了高视距。",
     "把该实例的内存上限调到 4096~8192 MB；光影 + 大型整合包建议 8G 起。"),
    (r"UnsupportedClassVersionError|class file version|compiled by a more recent version",
     "err", "Java 版本不对",
     "游戏/模组是用更高版本的 Java 编译的，当前 Java 太老。",
     "在设置里换成更高版本的 Java（1.20.5+ 需要 21，26.x 需要 25）。"),
    (r"NoClassDefFoundError|NoSuchMethodError|NoSuchFieldError",
     "err", "模组与游戏版本不匹配",
     "某个模组是针对别的 MC 版本编译的，类/方法对不上。",
     "把报错里提到的那个模组换成与当前游戏版本一致的版本。"),
    (r"Mixin apply failed|InjectionError|mixin.*failed|MixinTransformerError",
     "err", "Mixin 注入失败（模组冲突）",
     "两个模组改了同一段游戏逻辑，或者某个模组版本不对。",
     "按日志里出现的模组名，逐个禁用后二分排查；优先更新 Fabric API。"),
    (r"ModResolutionException|Missing or unsupported mandatory dependencies|requires .* which is missing",
     "err", "缺少前置模组",
     "装了这个模组，但没装它依赖的前置（常见：Fabric API、Architectury、Cloth Config）。",
     "按日志里 missing 的 mod id 去 Modrinth 搜同名模组装上。"),
    (r"Duplicate mods|duplicate mod|two files with the same mod id",
     "err", "模组重复",
     "mods 目录里同一个模组存在两份（常见于手动拖入 + 整合包更新）。",
     "删掉旧的那份，只留一个版本。"),
    (r"Pixel format not accelerated|GLFW error 65542|Failed to create window|Could not initialize GLFW",
     "err", "显卡/图形接口问题",
     "OpenGL 初始化失败，通常是驱动太旧、远程桌面、或虚拟机没有 GPU 加速。",
     "更新显卡驱动；虚拟机里请开启 3D 加速；Mac 上换用原版启动（不要远程桌面跑游戏）。"),
    (r"UnknownHostException|Connection refused|Connection reset|timed out|Failed to download",
     "warn", "网络问题",
     "下载或登录时连不上服务器（国内直连 Mojang 常见）。",
     "设置页把「下载源」切到 BMCLAPI 镜像后重试。"),
    (r"Address already in use",
     "err", "端口被占用",
     "要用的端口已经被别的程序占着（多见于开服，不是客户端）。",
     "换端口，或先关掉占用该端口的程序。"),
    (r"Could not find or load main class|Error: Could not find or load",
     "err", "版本文件损坏",
     "versions 目录里的 jar / json 不完整，通常是下载中断留下的半截文件。",
     "删掉该版本目录，重新安装一次（启动器会自动校验 jar 大小）。"),
    (r"AccessDeniedException|Permission denied|Read-only file system",
     "err", "文件权限问题",
     "游戏目录没有写权限，常见于放在只读磁盘、外接 NTFS 盘、或系统保护目录。",
     "把游戏目录换到用户目录下（设置里能看到当前路径），或用 KITTY_DATA 指定。"),
    (r"Invalid maximum heap size|Could not reserve enough space for object heap",
     "err", "内存参数不合法",
     "设置的 -Xmx 超过了物理内存，或写成了非法值。",
     "把内存上限调到不超过物理内存的 60%。"),
    (r"EXCEPTION_ACCESS_VIOLATION|A fatal error has been detected by the Java Runtime|hs_err_pid",
     "err", "JVM 崩溃（底层）",
     "Java 进程被系统/驱动直接干掉了，通常是显卡驱动、内存条、或 Java 与系统不兼容。",
     "先换一个 Java 版本试；仍然崩就更新显卡驱动；Mac 上检查是否开着「低电量模式」。"),
    (r"Incompatible mod set|incompatible with",
     "err", "模组集合不兼容",
     "Fabric 在加载阶段就判定这组模组不能一起跑。",
     "看日志里列出的冲突模组名，逐个换版本或去掉。"),
]


def analyze_text(text: str) -> list[dict]:
    import re as _re

    hits: list[dict] = []
    seen: set[str] = set()
    for pattern, level, title, detail, fix in CRASH_RULES:
        m = _re.search(pattern, text, _re.IGNORECASE)
        if not m or title in seen:
            continue
        seen.add(title)
        line = ""
        for raw in text.splitlines():
            if _re.search(pattern, raw, _re.IGNORECASE):
                line = raw.strip()[:200]
                break
        hits.append({"level": level, "title": title, "detail": detail, "fix": fix, "evidence": line})
    return hits


def diagnose_instance(name: str) -> dict:
    inst = get_instance(name)
    if not inst:
        return {"error": "实例不存在"}
    gdir = instance_dir(name)
    log_file = gdir / "logs" / "latest.log"
    crash_dir = gdir / "crash-reports"
    crash_file = None
    if crash_dir.exists():
        files = sorted(crash_dir.glob("crash-*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        crash_file = files[0] if files else None

    source = log_file if log_file.exists() else crash_file
    if source is None:
        return {"error": "这个实例还没有日志，先启动一次游戏喵"}

    text = source.read_text("utf-8", errors="replace")
    issues = analyze_text(text)
    if crash_file and crash_file != source:
        issues += [i for i in analyze_text(crash_file.read_text("utf-8", errors="replace")) if i["title"] not in {x["title"] for x in issues}]

    header = []
    for line in text.splitlines()[:80]:
        if "Loading Minecraft" in line or "Backend library" in line or "Setting user" in line:
            header.append(line.strip()[:160])

    return {
        "instance": name,
        "file": str(source),
        "issues": issues,
        "header": header[:4],
        "lines": len(text.splitlines()),
        "logPath": str(log_file),
        "crashPath": str(crash_file) if crash_file else "",
    }


# 模块加载完再把镜像设置应用上（此时 load_config / set_mirror 都已定义）
try:
    set_mirror(load_config().get("mirror", "official"))
except Exception:
    pass
