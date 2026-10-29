"""微软正版登录（OAuth 2.0 设备码流程）。

链路：
    Microsoft 账号
      → 设备码授权（拿 access_token / refresh_token）
      → Xbox Live 认证（user.auth.xboxlive.com）
      → XSTS 授权（xsts.auth.xboxlive.com）
      → Minecraft Services（api.minecraftservices.com/authentication/login_with_xbox）
      → 玩家档案（/minecraft/profile）得到 name + uuid

为什么用设备码而不是浏览器回调：设备码只要一个 client_id，不需要在本地起回调服务器，
也不会和 macOS 的端口占用/防火墙打架；玩家在浏览器里输 8 位码即可。

client_id 需要自己注册一个 Azure 应用（免费，见 README「微软登录」一节），
本项目不内置任何第三方 client_id —— 用别人的属于滥用。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import requests
from minecraft_launcher_lib import microsoft_account as ms

from .paths import ACCOUNTS_PATH, VERSION

DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
SCOPE = "XboxLive.signin offline_access"
UA = {"User-Agent": f"KittyLauncher/{VERSION}"}
TIMEOUT = 25

# XSTS 常见错误码 → 人话
XSTS_ERRORS = {
    "2148916233": "这个微软账号还没有 Xbox 档案，先去 xbox.com 登录一次创建（免费）",
    "2148916235": "该账号所在地区不支持 Xbox Live",
    "2148916236": "需要在 xbox.com 完成成人验证",
    "2148916237": "需要在 xbox.com 完成成人验证",
    "2148916238": "未成年账号需要家长在家庭组里同意",
    "2148916227": "该 Xbox 账号已被封禁",
}


# ---------------------------------------------------------------- 存取

def _load() -> dict:
    if ACCOUNTS_PATH.exists():
        try:
            data = json.loads(ACCOUNTS_PATH.read_text("utf-8"))
            if isinstance(data, dict):
                data.setdefault("items", [])
                data.setdefault("active", "")
                return data
        except Exception:
            pass
    return {"active": "", "items": []}


def _save(data: dict) -> None:
    ACCOUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACCOUNTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, ACCOUNTS_PATH)
    try:
        os.chmod(ACCOUNTS_PATH, 0o600)  # 里面有 refresh token，只有自己能读
    except Exception:
        pass


def list_accounts() -> list[dict]:
    return _load()["items"]


def active_account() -> dict | None:
    data = _load()
    for item in data["items"]:
        if item.get("id") == data.get("active"):
            return item
    return None


def set_active(account_id: str) -> None:
    data = _load()
    data["active"] = account_id
    _save(data)


def remove_account(account_id: str) -> None:
    data = _load()
    data["items"] = [i for i in data["items"] if i.get("id") != account_id]
    if data.get("active") == account_id:
        data["active"] = data["items"][0]["id"] if data["items"] else ""
    _save(data)


def _upsert(account: dict) -> dict:
    data = _load()
    data["items"] = [i for i in data["items"] if i.get("id") != account["id"]]
    data["items"].append(account)
    data["active"] = account["id"]
    _save(data)
    return account


# ---------------------------------------------------------------- 设备码流程

def start_device_login(client_id: str) -> dict:
    client_id = (client_id or "").strip()
    if not client_id:
        raise RuntimeError("先填 Azure 应用（客户端）ID")
    r = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": client_id, "scope": SCOPE},
        headers=UA,
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        detail = ""
        try:
            detail = r.json().get("error_description", "")
        except Exception:
            detail = r.text[:200]
        raise RuntimeError(f"申请设备码失败：{detail or r.status_code}")
    d = r.json()
    return {
        "device_code": d["device_code"],
        "user_code": d["user_code"],
        "verification_uri": d.get("verification_uri") or d.get("verification_url", ""),
        "expires_in": int(d.get("expires_in", 900)),
        "interval": int(d.get("interval", 5)),
        "message": d.get("message", ""),
    }


def poll_device_login(device_code: str, client_id: str) -> dict:
    """返回 {status: pending|ok|expired|declined|error, tokens?, error?}"""
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": device_code,
        },
        headers=UA,
        timeout=TIMEOUT,
    )
    try:
        d = r.json()
    except Exception:
        return {"status": "error", "error": f"返回不是 JSON（HTTP {r.status_code}）"}

    if "access_token" in d:
        return {"status": "ok", "tokens": d}
    err = d.get("error", "")
    desc = d.get("error_description", "")
    if err == "authorization_pending":
        return {"status": "pending"}
    if err == "slow_down":
        return {"status": "pending", "slow": True}
    if err in ("expired_token", "code_expired"):
        return {"status": "expired", "error": "验证码过期了，重新生成一个"}
    if err == "authorization_declined":
        return {"status": "declined", "error": "你在浏览器里点了拒绝"}
    if err in ("invalid_client", "unauthorized_client"):
        return {
            "status": "error",
            "error": "client_id 不对，或应用没开启「允许公共客户端流程」（Public client flows）",
        }
    return {"status": "error", "error": desc or err or f"HTTP {r.status_code}"}


# ---------------------------------------------------------------- Xbox → Minecraft

def _xbox_chain(ms_access_token: str) -> dict:
    xbl = ms.authenticate_with_xbl(ms_access_token)
    if "Token" not in xbl:
        raise RuntimeError(f"Xbox Live 认证失败：{str(xbl)[:200]}")
    userhash = (xbl.get("DisplayClaims") or {}).get("xui", [{}])[0].get("uhs", "")
    xsts = ms.authenticate_with_xsts(xbl["Token"])
    if "Token" not in xsts:
        xerr = str(xsts.get("XErr", ""))
        raise RuntimeError(XSTS_ERRORS.get(xerr, f"XSTS 授权失败（XErr {xerr or '?'}）"))
    mc_token = ms.authenticate_with_minecraft(userhash, xsts["Token"])
    if "access_token" not in mc_token:
        raise RuntimeError(f"Minecraft 认证失败：{str(mc_token)[:200]}")
    profile = ms.get_profile(mc_token["access_token"])
    if "id" not in profile:
        raise RuntimeError("这个账号没有 Minecraft Java 版（需要先购买）")
    return {
        "mcAccessToken": mc_token["access_token"],
        "mcExpiresAt": int(time.time()) + int(mc_token.get("expires_in", 86400)),
        "name": profile["name"],
        "uuid": profile["id"],
        "skins": profile.get("skins", []),
    }


def complete_login(tokens: dict, client_id: str) -> dict:
    """设备码拿到 token 之后：跑 Xbox 链、存账号。"""
    chain = _xbox_chain(tokens["access_token"])
    account = {
        "id": uuid.uuid4().hex,
        "kind": "microsoft",
        "clientId": client_id,
        "msRefreshToken": tokens.get("refresh_token", ""),
        **chain,
        "addedAt": int(time.time()),
    }
    return _upsert(account)


def refresh_account(account: dict) -> dict:
    """用 refresh_token 换新的 access_token，再跑一遍 Xbox 链。"""
    client_id = account.get("clientId") or ""
    refresh_token = account.get("msRefreshToken") or ""
    if not client_id or not refresh_token:
        raise RuntimeError("账号信息不完整，请重新登录")
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "scope": SCOPE,
        },
        headers=UA,
        timeout=TIMEOUT,
    )
    d = r.json() if r.content else {}
    if "access_token" not in d:
        raise RuntimeError(f"登录已失效，请重新登录（{d.get('error', 'unknown')}）")
    chain = _xbox_chain(d["access_token"])
    account = {**account, **chain}
    if d.get("refresh_token"):
        account["msRefreshToken"] = d["refresh_token"]
    return _upsert(account)


def ensure_fresh(account: dict, slack: int = 180) -> dict:
    if int(account.get("mcExpiresAt") or 0) - slack < time.time():
        return refresh_account(account)
    return account


# ---------------------------------------------------------------- 给启动器用

def launch_identity() -> dict | None:
    """返回 {username, uuid, token}；没有正版账号就返回 None（走离线）。"""
    account = active_account()
    if not account:
        return None
    account = ensure_fresh(account)
    return {
        "username": account["name"],
        "uuid": str(account.get("uuid", "")).replace("-", ""),
        "token": account["mcAccessToken"],
        "kind": "microsoft",
    }


def status() -> dict:
    """给设置页显示用的摘要。"""
    acc = active_account()
    if not acc:
        return {"loggedIn": False, "name": "", "uuid": "", "expiresIn": 0, "accounts": len(list_accounts())}
    return {
        "loggedIn": True,
        "name": acc.get("name", ""),
        "uuid": acc.get("uuid", ""),
        "expiresIn": max(0, int(acc.get("mcExpiresAt", 0) - time.time())),
        "accounts": len(list_accounts()),
        "clientId": acc.get("clientId", ""),
    }
