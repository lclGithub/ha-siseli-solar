"""集成入口：建立会话、协调器，并把平台挂上去。"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SiseliApi, SiseliError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT,
    CONF_DEVICE_ID,
    CONF_EXPIRES_AT,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SHOW_ALL_ALARMS,
    CONF_USER_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PRIORITY_ALARMS,
)
from .coordinator import SiseliCoordinator
from .dashboard import async_ensure_energy_ui

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)

    api = SiseliApi(session, entry.data[CONF_ACCOUNT], entry.data[CONF_PASSWORD])
    api.access_token = entry.data.get(CONF_ACCESS_TOKEN) or None
    api.refresh_token = entry.data.get(CONF_REFRESH_TOKEN) or None
    api.access_expires_at = entry.data.get(CONF_EXPIRES_AT) or 0.0
    api.user_id = entry.data.get(CONF_USER_ID) or None

    # 重启后如果只是复用还没过期的 token，是不会经过登录的，
    # 此时 user_id 为空 —— 而速报的 clientID 必须带 userId，
    # 所以缺了就主动登录一次补上。
    if not api.user_id:
        try:
            info = await api.async_login()
            api.user_id = (info or {}).get("userId")
            _LOGGER.debug("补登录完成，userId=%s", api.user_id)
        except SiseliError as err:
            _LOGGER.warning("补登录失败，实时刷新将不可用：%s", err)

    scan_interval = int(entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL))
    coordinator = SiseliCoordinator(hass, entry, api, entry.data[CONF_DEVICE_ID], scan_interval)

    # 用 async_refresh 而不是 first_refresh：设备离线时也要能把集成加载起来
    await coordinator.async_refresh()

    # 先拿到 138 个告警位定义，后面各平台建实体时名字和数量都齐了
    await coordinator.async_load_alarm_meta()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 把上一版（建全 138 个）遗留下来的非常用告警实体清掉
    await _async_prune_alarms(hass, entry)

    # 自动准备「能量流」看板与能量面板配置（失败不影响集成）
    await async_ensure_energy_ui(hass, entry.data[CONF_DEVICE_ID])

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_prune_alarms(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """删掉注册表里不属于「常用 22 个」的告警实体。

    只在未开启「显示全部告警」时生效。删掉后该实体就不存在了（不是禁用），
    想恢复全部就在集成选项里打开开关，会重新创建 138 个。
    """
    if entry.options.get(CONF_SHOW_ALL_ALARMS, False):
        return

    registry = er.async_get(hass)
    removed = 0
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain != "binary_sensor" or entity.platform != DOMAIN:
            continue
        unique_id = entity.unique_id or ""
        if "_alarm_" not in unique_id:
            continue
        key = unique_id.rsplit("_alarm_", 1)[-1]
        if key in PRIORITY_ALARMS:
            continue
        registry.async_remove(entity.entity_id)
        removed += 1

    if removed:
        _LOGGER.info(
            "精简告警位：移除 %s 个非常用告警实体（可在集成选项里开启全部 138 个）",
            removed,
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: SiseliCoordinator = entry.runtime_data
    await coordinator.async_shutdown_fast()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """选项变更后重载。"""
    await hass.config_entries.async_reload(entry.entry_id)
