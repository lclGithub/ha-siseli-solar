"""二进制传感器平台：138 个告警/故障位。

数据来源是 `/remote/device/state/latest` 里的 `firingAlarms`：
只有正在触发的告警会出现，所以「不在列表里」即视为正常。
每个告警位一个 binary_sensor（device_class=problem），名字取自云端 category=2 定义。
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SHOW_ALL_ALARMS, DOMAIN, PRIORITY_ALARMS
from .coordinator import SiseliCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SiseliCoordinator = entry.runtime_data

    if not coordinator.alarm_initialized:
        await coordinator.async_load_alarm_meta()

    if not coordinator.alarm_meta:
        _LOGGER.warning("没有拿到告警位定义，本次不创建告警实体")
        return

    show_all = bool(entry.options.get(CONF_SHOW_ALL_ALARMS, False))

    device_info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.device_id)},
        name=entry.data.get("device_name") or "雷零逆控机",
        manufacturer=entry.data.get("manufacturer") or "雷零科技",
        model=entry.data.get("model") or "逆控一体机",
        sw_version=entry.data.get("sw_version"),
        serial_number=entry.data.get("serial_number"),
    )

    entities = [
        SiseliAlarmBinarySensor(coordinator, device_info, key, name)
        for key, name in sorted(coordinator.alarm_meta.items(), key=lambda kv: kv[1])
        if show_all or key in PRIORITY_ALARMS
    ]
    _LOGGER.debug("创建 %s 个告警实体（总定义 %s 个）", len(entities), len(coordinator.alarm_meta))
    async_add_entities(entities)


class SiseliAlarmBinarySensor(CoordinatorEntity[SiseliCoordinator], BinarySensorEntity):
    """一个告警位。on = 正在告警。"""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: SiseliCoordinator,
        device_info: DeviceInfo,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._alarm_key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.device_id}_alarm_{key}"
        self._attr_device_info = device_info
        # 只有常用项默认启用，其余想在用的时候到实体设置里单独打开
        self._attr_entity_registry_enabled_default = key in PRIORITY_ALARMS

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.online

    @property
    def is_on(self) -> bool:
        return self._alarm_key in self.coordinator.firing_alarms

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alarm = self.coordinator.firing_alarms.get(self._alarm_key)
        attrs: dict[str, Any] = {"alarm_key": self._alarm_key}
        if not alarm:
            return attrs

        for src, dst in (
            ("createdAt", "触发时间"),
            ("firedValue", "触发值"),
            ("level", "等级"),
            ("status", "状态"),
            ("alarmCodeInDevice", "设备内告警码"),
        ):
            if alarm.get(src) is not None:
                attrs[dst] = alarm[src]

        name_i18n = alarm.get("nameI18n") or {}
        if name_i18n.get("en"):
            attrs["英文名"] = name_i18n["en"]
        if alarm.get("descriptionI18n", {}).get("zh-CN"):
            attrs["说明"] = alarm["descriptionI18n"]["zh-CN"]
        return attrs
