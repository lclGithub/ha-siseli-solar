"""四色/雷零 IoT 云异步客户端（签名算法已完整复刻，无需浏览器）。

签名流程（来自门户前端 umi.js 的请求拦截器）：
    1. 参与签名的参数只有三个：IOT-Open-AppID / IOT-Open-Nonce / IOT-Open-Body-Hash，
       按 key 升序拼成 k=v&k=v（不做 URL 编码）。
    2. 该字符串先整体 Base64，得到 msg。
    3. 密钥 = AES-128-CBC(ZeroPadding) 解密内置 openAppSecret，
       Key = md5hex(appId)[0:16]，IV = md5hex(appId)[16:32]（均按 ASCII 取）。
    4. sign = md5( HMAC-SHA256(msg, key) )，md5 吃的是 32 字节原始 digest。
    5. Body-Hash = sha256hex(请求体原文)，参与签名但不作为请求头发送。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import random
import string
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import aiohttp

HOST = "urayzero.siseli.com"
BASE_URL = f"https://{HOST}/apis"

OPEN_APP_ID = "rBrTRfAPXz"
OPEN_APP_SECRET = "I4D0KRr2339z3pQ/at91V9BpFAOe54DaTafwSm6suIQ="

# derive_sign_key(OPEN_APP_ID, OPEN_APP_SECRET) 的结果，固化以省掉 AES 依赖
SIGN_KEY = "CJbrtLtqFES62bJ3ZW7c"

TOKEN_ERROR_CODES = {8, 9}
AUTH_ERROR_CODES = {7, 37, 41, 44, 20007}  # 密码错 / AppID / nonce / 签名 / 账号
OFFLINE_CODES = {70001, 71000}             # Device is busy / offline

TIMEOUT = 25


# --------------------------------------------------------------------------- 异常

class SiseliError(Exception):
    """接口返回了非 0 code。"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class SiseliAuthError(SiseliError):
    """账号或密码错误、AppID 被拒等认证问题。"""


class SiseliDeviceOffline(SiseliError):
    """设备离线 / 忙，本轮拿不到数据。"""


# --------------------------------------------------------------------------- 签名

def _md5hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def derive_sign_key(app_id: str, secret_b64: str) -> str:
    """从 AppID + openAppSecret 还原 HMAC 密钥（等价于前端 Ye()）。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    h = _md5hex(app_id.encode())
    key, iv = h[:16].encode(), h[16:32].encode()
    raw = base64.b64decode(secret_b64)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    out = dec.update(raw) + dec.finalize()
    return out.decode("utf-8").rstrip("\x00").strip()


def _nonce(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    rng = random.SystemRandom()
    return "".join(rng.choice(alphabet) for _ in range(length))


def build_sign(params: dict[str, str], sign_key: str = SIGN_KEY) -> str:
    query = "&".join(f"{k}={params[k]}" for k in sorted(params))
    message = base64.b64encode(query.encode()).decode()
    digest = hmac.new(sign_key.encode(), message.encode(), hashlib.sha256).digest()
    return hashlib.md5(digest).hexdigest()


def sign_headers(body: str | None, app_id: str = OPEN_APP_ID,
                 sign_key: str = SIGN_KEY) -> dict[str, str]:
    """生成 IOT-Open-* 三个请求头。body 为实际发送的原始字符串。"""
    body_str = body or ""
    nonce = _nonce()
    body_hash = hashlib.sha256(body_str.encode()).hexdigest() if body_str else ""
    params = {
        "IOT-Open-AppID": app_id,
        "IOT-Open-Body-Hash": body_hash,
        "IOT-Open-Nonce": nonce,
    }
    return {
        "IOT-Open-AppID": app_id,
        "IOT-Open-Nonce": nonce,
        "IOT-Open-Sign": build_sign(params, sign_key),
    }


# --------------------------------------------------------------------------- 客户端

class SiseliApi:
    """一个账号对应一个实例；内部维护 access/refresh token 与自动续期。"""

    def __init__(self, session: aiohttp.ClientSession, account: str, password: str) -> None:
        self._session = session
        self.account = account
        self.password = password
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.access_expires_at: float = 0.0
        self.refresh_expires_at: float = 0.0
        self.user_id: str | None = None
        self._lock = asyncio.Lock()

    # -- 底层 ---------------------------------------------------------

    async def _request(self, method: str, path: str, payload: Any = None,
                       *, signed: bool = False, with_token: bool = True,
                       body_str: str | None = None) -> Any:
        url = f"{BASE_URL}{path}"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN",
            "Content-Type": "application/json;charset=UTF-8",
            "IOT-Time-Zone": "Asia/Shanghai",
            "Origin": f"https://{HOST}",
            "Referer": f"https://{HOST}/",
        }
        if with_token and self.access_token:
            headers["IOT-Token"] = self.access_token

        data: str | None = body_str
        if data is None and payload is not None:
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        if signed:
            headers.update(sign_headers(data))

        try:
            async with self._session.request(
                method, url, data=data.encode() if data is not None else None,
                headers=headers, timeout=aiohttp.ClientTimeout(total=TIMEOUT),
            ) as resp:
                text = await resp.text()
        except asyncio.TimeoutError as err:
            raise SiseliError(-1, "请求超时") from err
        except aiohttp.ClientError as err:
            raise SiseliError(-1, f"网络错误: {err}") from err

        try:
            body = json.loads(text)
        except json.JSONDecodeError as err:
            raise SiseliError(-2, f"响应不是 JSON: {text[:200]}") from err

        code = body.get("code")
        if code != 0:
            message = body.get("message") or body.get("localMessage") or "unknown"
            if code in AUTH_ERROR_CODES:
                raise SiseliAuthError(code, message)
            if code in OFFLINE_CODES:
                raise SiseliDeviceOffline(code, message)
            raise SiseliError(code, message)
        return body.get("data")

    async def _authed(self, method: str, path: str, payload: Any = None) -> Any:
        await self.async_ensure_token()
        try:
            return await self._request(method, path, payload)
        except SiseliError as err:
            if err.code not in TOKEN_ERROR_CODES:
                raise
            await self.async_refresh()
            return await self._request(method, path, payload)

    # -- 认证 ---------------------------------------------------------

    async def async_login(self) -> dict:
        body = json.dumps({
            "account": self.account,
            "password": _md5hex(self.password.encode()),
        }, separators=(",", ":"))
        data = await self._request("POST", "/login/account", signed=True,
                                   with_token=False, body_str=body)
        self._store_tokens(data)
        return data

    async def async_refresh(self) -> dict:
        if not self.refresh_token:
            return await self.async_login()
        body = json.dumps({
            "accessToken": self.access_token,
            "refreshToken": self.refresh_token,
        }, separators=(",", ":"))
        try:
            data = await self._request("POST", "/login/refresh/access/token", signed=True,
                                       with_token=False, body_str=body)
        except SiseliError:
            return await self.async_login()
        self._store_tokens(data)
        return data

    async def async_ensure_token(self) -> None:
        async with self._lock:
            if not self.access_token:
                await self.async_login()
            elif time.time() > self.access_expires_at - 300:
                await self.async_refresh()

    def _store_tokens(self, data: dict) -> None:
        self.access_token = data["accessToken"]
        self.refresh_token = data["refreshToken"]
        self.user_id = data.get("userId")
        now = time.time()
        self.access_expires_at = now + int(data.get("accessTokenWillExpiredInMillis", 7_200_000)) / 1000
        self.refresh_expires_at = now + int(
            data.get("refreshTokenWillExpiredInMillis", 2_592_000_000)) / 1000

    # -- 业务 ---------------------------------------------------------

    async def async_devices(self) -> list[dict]:
        """page 从 1 开始，传 0 会报 20101 Iillegal argument。"""
        page = await self._authed("POST", "/device/list", {"count": 50, "page": 1})
        return (page or {}).get("list") or []

    async def async_state_latest(self, device_id: str) -> dict:
        """返回完整 payload：含 fields（遥测）与 firingAlarms（正在触发的告警）。"""
        query = f"deviceId={device_id}&dataSource=2"
        data = await self._authed("GET", f"/remote/device/state/latest?{query}")
        return data or {}

    async def async_attribute_groups(self, device_id: str, category: int = 1) -> list[dict]:
        query = f"deviceId={device_id}&category={category}"
        data = await self._authed("GET", f"/device/query/attribute/group?{query}")
        return (data or {}).get("attributesGroups") or []

    async def async_monthly_energy(
        self, device_id: str, month: str | None = None
    ) -> dict[str, dict[str, float]]:
        """取「光伏逆变器电量类」的月度汇总。

        云端会返回整月按天的 timePoints，这里同时算出：
          total = 本月至今合计（只统计 isRealValue 的点）
          today = 当天那一个点（即云端口径的今日值）

        返回 {属性key: {"total": float, "today": float, "unit": str}}，
        属性 key 有：pvGeneratedEnergy / buyElectricityQuantity /
        sellElectricityQuantity / chargeElectricityQuantity /
        dischargeElectricityQuantity / consumeElectricityQuantity
        """
        if month is None:
            month = datetime.now().strftime("%Y-%m")
        today = datetime.now().strftime("%Y-%m-%d")

        query = urlencode(
            {
                "deviceId": device_id,
                "summaryCategoryKey": "pvInverterElectricityQuantityClass",
            }
        )
        data = await self._authed(
            "POST",
            f"/deviceOverView/stateAttributeSummary/category/monthly?{query}",
            {"time": month},
        )

        out: dict[str, dict[str, float]] = {}
        for item in (data or {}).get("properties") or []:
            prop = item.get("property") or {}
            key = prop.get("key")
            if not key:
                continue
            points = item.get("timePoints") or []
            total = 0.0
            today_value = 0.0
            for p in points:
                value = p.get("value")
                if value is None:
                    continue
                if p.get("time") == today:
                    today_value = float(value)
                if p.get("isRealValue"):
                    total += float(value)
            out[key] = {
                "total": round(total, 2),
                "today": round(today_value, 2),
                "unit": prop.get("unit") or "kWh",
            }
        return out

    # -- 实时刷新（速报） ---------------------------------------------

    async def async_fast_supported(self, device_id: str) -> bool:
        data = await self._authed(
            "GET", f"/remote/device/state/report/fast/supported?deviceId={device_id}"
        )
        return bool(data)

    async def async_fast_start(
        self, device_id: str, client_id: str, scene: int = 1
    ) -> dict:
        """开启速报。

        scene 必须是枚举码（1 = DEVICE_LIVE_ENERGY_FLOW），传名字会被告知
        invalid format —— 服务端按 code 反序列化，和 swagger 的 enum 名称不一致。
        返回 {"reportPeriodInMills": 3000, "willStopInMills": 180000,
              "shouldRenewalInMills": 60000}
        """
        return await self._authed(
            "POST",
            f"/remote/device/state/report/fast/start?deviceId={device_id}",
            {"clientID": client_id, "scene": scene},
        )

    async def async_fast_stop(self, device_id: str, client_id: str) -> None:
        await self._authed(
            "POST",
            f"/remote/device/state/report/fast/stop?deviceId={device_id}",
            {"clientID": client_id},
        )
