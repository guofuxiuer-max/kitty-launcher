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

def _data_root() -> Path:
    """数据目录：开发时用仓库里的 data/，打包成 app 后用系统用户目录。"""
    env = os.environ.get("KITTY_DATA")
    if env:
        return Path(env).expanduser()
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "KittyLauncher"
        if os.name == "nt":
            return Path(os.environ.get("APPDATA", Path.home())) / "KittyLauncher"
        return Path.home() / ".local" / "share" / "KittyLauncher"
    return Path(__file__).resolve().parent.parent / "data"


APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
DATA = _data_root()
MC_DIR = DATA / "minecraft"
INSTANCES_DIR = DATA / "instances"
LOGS_DIR = DATA / "logs"
CONFIG_PATH = DATA / "config.json"
INSTANCES_JSON = DATA / "instances.json"

for d in (DATA, MC_DIR, INSTANCES_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "username": "Steve",
    "memoryMB": 4096,
    "javaPath": "",
    "width": 1280,
    "height": 720,
    "selectedInstance": "",
    "theme": "dark",
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
        return cfg


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
    cfg = load_config()
    username = (cfg.get("username") or "Steve").strip() or "Steve"
    need = version_java_major(inst["versionId"])
    java, jinfo = pick_java(need)
    if not java:
        raise RuntimeError("没找到可用的 Java，去设置页指一个 java 可执行文件")
    mem = int(cfg.get("memoryMB") or 4096)
    opts = {
        "username": username,
        "uuid": offline_uuid(username),
        "token": "0",
        "executablePath": java,
        "defaultExecutablePath": java,
        "jvmArguments": [f"-Xmx{mem}M", "-Xms512M", "-Dfile.encoding=UTF-8"],
        "launcherName": "KittyLauncher",
        "launcherVersion": "1.0.0",
        "gameDirectory": str(instance_dir(inst["name"])),
        "customResolution": True,
        "resolutionWidth": str(cfg.get("width") or 1280),
        "resolutionHeight": str(cfg.get("height") or 720),
        "enableLoggingConfig": True,
    }
    cmd = mlc.get_minecraft_command(inst["versionId"], str(MC_DIR), opts)
    return {"cmd": cmd, "java": jinfo, "requiredMajor": need}


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
_http_headers = {"User-Agent": "KittyLauncher/1.0.0 (macOS)"}


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
