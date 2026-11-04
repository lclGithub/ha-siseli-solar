"""注册自定义卡片的静态资源与 Lovelace 资源。

自定义卡片必须作为 Lovelace resource 注册才能用 ``custom:`` 前缀引用。
这里做两件事：
  1. 把 ``frontend/`` 目录挂到 http 静态路径 ``/siseli_solar_frontend``（只做一次）
  2. 往 Lovelace resources 里登记一条 module 资源（幂等；版本变了会更新 URL）

注：``hass.data`` 在集成条目重载时不会清空，所以不能用一个「已注册」布尔值
一劳永逸地短路——那样改了 JS 也永远不会生效。静态路径只注册一次，
资源则在每次 setup 时比对版本号。

两项都是可选增强：失败只记日志，不影响集成与实体。
"""

from __future__ import annotations

import hashlib
import logging
import os

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

STATIC_URL = "/siseli_solar_frontend"
CARD_FILE = "siseli-power-flow.js"
# 兜底版本号：正常情况用 JS 文件内容的哈希，不再手工维护。
# 之前的教训：手工常量会和「已加载进内存的模块」不一致——
# 改了 JS 却没重启，重载条目时旧模块会把资源 URL 改回旧版本，
# 浏览器于是加载了带 bug 的老 JS。
CARD_VERSION = 6

DATA_STATIC = "card_static_registered"
DATA_VERSION = "card_resource_version"


async def _async_card_version(hass: HomeAssistant) -> str:
    """用 JS 文件内容哈希作为版本号，JS 一变 URL 就变。

    读文件走 executor，避免在事件循环里做阻塞 I/O（HA 会警告）。
    """
    path = os.path.join(os.path.dirname(__file__), "frontend", CARD_FILE)

    def _read() -> str:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:10]

    try:
        return await hass.async_add_executor_job(_read)
    except OSError:
        return str(CARD_VERSION)


async def _async_register_static(hass: HomeAssistant) -> bool:
    if hass.data.get(DATA_STATIC):
        return True
    try:
        from homeassistant.components.http import StaticPathConfig

        static_dir = os.path.join(os.path.dirname(__file__), "frontend")
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, static_dir, False)]
        )
        hass.data[DATA_STATIC] = True
        _LOGGER.debug("自定义卡片静态目录已挂载：%s", static_dir)
        return True
    except Exception:  # noqa: BLE001
        _LOGGER.warning("挂载卡片静态目录失败，自定义卡片将不可用", exc_info=True)
        return False


async def _async_register_resource(hass: HomeAssistant) -> bool:
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        lovelace = hass.data.get(LOVELACE_DATA)
        if lovelace is None:
            _LOGGER.debug("Lovelace 未初始化，跳过卡片资源注册")
            return False

        resources = lovelace.resources
        try:
            items = list(resources.async_items())
        except Exception:  # noqa: BLE001
            items = []

        version = await _async_card_version(hass)
        desired = f"{STATIC_URL}/{CARD_FILE}?v={version}"
        existing = next(
            (item for item in items if CARD_FILE in (item.get("url") or "")), None
        )

        if existing is None:
            await resources.async_create_item({"res_type": "module", "url": desired})
            _LOGGER.info("已注册自定义卡片资源 %s", desired)
        elif existing.get("url") != desired and existing.get("id"):
            await resources.async_update_item(existing["id"], {"url": desired})
            _LOGGER.info(
                "自定义卡片资源已更新：%s -> ?v=%s",
                existing.get("url"),
                version,
            )
        else:
            _LOGGER.debug("自定义卡片资源已是最新 v%s", version)

        hass.data[DATA_VERSION] = version
        return True
    except Exception:  # noqa: BLE001
        _LOGGER.warning("注册卡片资源失败，可手动在「仪表盘 → 资源」添加", exc_info=True)
        return False


async def async_register_card(hass: HomeAssistant) -> bool:
    """挂静态目录 + 注册/升级 Lovelace 资源。

    返回 True 表示自定义卡片可用；False 时调用方应降级到官方卡片。
    """
    static_ok = await _async_register_static(hass)
    resource_ok = await _async_register_resource(hass)
    return static_ok and resource_ok
