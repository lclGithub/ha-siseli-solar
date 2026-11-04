"""传感器平台：按 const.SENSOR_DEFS 生成精选实体。"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENERGY_SUMMARY_DEFS, SENSOR_DEFS
from .coordinator import SiseliCoordinator

_LOGGER = logging.getLogger(__name__)

# 这些 device_class 的实体必须是数值，不能把 valueDisplay 的字符串直接塞进去
NUMERIC_CLASSES = {
    SensorDeviceClass.VOLTAGE,
    SensorDeviceClass.CURRENT,
    SensorDeviceClass.POWER,
    SensorDeviceClass.ENERGY,
    SensorDeviceClass.TEMPERATURE,
    SensorDeviceClass.FREQUENCY,
    SensorDeviceClass.BATTERY,
    SensorDeviceClass.POWER_FACTOR,
}


def _clean(value: Any) -> str:
    """设备偶尔会返回 \\x00 填充，去掉控制字符。"""
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if ch >= " " and ch != "\x7f").strip()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SiseliCoordinator = entry.runtime_data
    data = coordinator.data or {}

    device_info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.device_id)},
        name=entry.data.get("device_name") or "雷零逆控机",
        manufacturer=entry.data.get("manufacturer") or "雷零科技",
        model=entry.data.get("model") or "逆控一体机",
        sw_version=entry.data.get("sw_version"),
        serial_number=entry.data.get("serial_number"),
    )

    entities: list[SiseliSensor] = []
    for index, definition in enumerate(SENSOR_DEFS):
        key = definition["key"]
        # 首次拉取成功后才按实际字段裁剪；设备离线时先全量创建
        if data and key not in data:
            continue
        description = SensorEntityDescription(
            key=key,
            name=definition["name"],
            native_unit_of_measurement=definition.get("unit"),
            device_class=SensorDeviceClass(definition["dc"]) if definition.get("dc") else None,
            state_class=SensorStateClass(definition["sc"]) if definition.get("sc") else None,
            icon=definition.get("icon"),
            entity_registry_enabled_default=definition.get("cat") != "diagnostic",
            entity_category=(
                EntityCategory.DIAGNOSTIC if definition.get("cat") == "diagnostic" else None
            ),
        )
        entities.append(SiseliSensor(coordinator, device_info, description, index))

    # 告警总览：这两条让 138 个告警位在概览里有个紧凑的入口
    entities.append(SiseliAlarmCount(coordinator, device_info))
    entities.append(SiseliActiveAlarms(coordinator, device_info))

    # 云端电量汇总：6 项 × (今日 / 本月)
    for definition in ENERGY_SUMMARY_DEFS:
        for period in ("today", "total"):
            entities.append(
                SiseliEnergySummarySensor(
                    coordinator,
                    device_info,
                    definition["key"],
                    definition["name"],
                    period,
                    definition.get("icon"),
                )
            )

    async_add_entities(entities)


class SiseliSensor(CoordinatorEntity[SiseliCoordinator], SensorEntity):
    """一个云端属性对应一个实体。"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SiseliCoordinator,
        device_info: DeviceInfo,
        description: SensorEntityDescription,
        index: int,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"
        self._attr_device_info = device_info
        self._index = index

    @property
    def available(self) -> bool:
        # 设备离线时仍保留上一帧数值，但标记为不可用
        return super().available and self.coordinator.online

    @property
    def native_value(self) -> float | str | None:
        field = (self.coordinator.data or {}).get(self.entity_description.key)
        if not isinstance(field, dict):
            return None

        raw = field.get("value")
        if raw is None:
            return None

        numeric = (
            self.entity_description.device_class in NUMERIC_CLASSES
            or self.entity_description.state_class is not None
        )
        if numeric:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        display = _clean(field.get("valueDisplay"))
        return display or _clean(raw)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        field = (self.coordinator.data or {}).get(self.entity_description.key) or {}
        attrs: dict[str, Any] = {"siseli_key": self.entity_description.key}
        category = _clean(field.get("categoryDict"))
        if category:
            attrs["属性类别"] = category
        if field.get("valueTypeDict"):
            attrs["数据类型"] = _clean(field.get("valueTypeDict"))
        return attrs


class SiseliEnergySummarySensor(CoordinatorEntity[SiseliCoordinator], SensorEntity):
    """云端电量汇总：今日值或本月至今（来自 stateAttributeSummary/category/monthly）。"""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: SiseliCoordinator,
        device_info: DeviceInfo,
        key: str,
        name: str,
        period: str,
        icon: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._period = period  # "today" | "total"
        prefix = "今日" if period == "today" else "本月"
        self._attr_name = f"云端{prefix}{name}"
        self._attr_unique_id = f"{coordinator.device_id}_energy_{period}_{key}"
        self._attr_icon = icon
        self._attr_device_info = device_info

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.month_energy)

    @property
    def native_value(self) -> float | None:
        item = (self.coordinator.month_energy or {}).get(self._key)
        if not isinstance(item, dict):
            return None
        value = item.get(self._period)
        return float(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = (self.coordinator.month_energy or {}).get(self._key) or {}
        return {
            "siseli_key": self._key,
            "数据来源": "云端月度汇总接口",
            "今日": item.get("today"),
            "本月至今": item.get("total"),
        }


class _AlarmOverviewBase(CoordinatorEntity[SiseliCoordinator], SensorEntity):
    """告警总览类实体的公共部分。"""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SiseliCoordinator, device_info: DeviceInfo) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info

    @property
    def available(self) -> bool:
        return super().available

    @property
    def _alarms(self) -> list[dict[str, Any]]:
        return list(self.coordinator.firing_alarms.values())

    @staticmethod
    def _title(alarm: dict[str, Any]) -> str:
        return (
            (alarm.get("nameI18n") or {}).get("zh-CN")
            or alarm.get("name")
            or alarm.get("key")
            or "未知告警"
        )


class SiseliAlarmCount(_AlarmOverviewBase):
    """当前正在触发的告警数量。"""

    _attr_name = "当前告警数"
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator: SiseliCoordinator, device_info: DeviceInfo) -> None:
        super().__init__(coordinator, device_info)
        self._attr_unique_id = f"{coordinator.device_id}_alarm_count"

    @property
    def native_value(self) -> int:
        return len(self._alarms)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "告警列表": [self._title(a) for a in self._alarms],
            "告警位总数": len(self.coordinator.alarm_meta),
        }


class SiseliActiveAlarms(_AlarmOverviewBase):
    """当前告警的文本摘要，详细内容放属性。"""

    _attr_name = "当前告警"
    _attr_icon = "mdi:alert"

    def __init__(self, coordinator: SiseliCoordinator, device_info: DeviceInfo) -> None:
        super().__init__(coordinator, device_info)
        self._attr_unique_id = f"{coordinator.device_id}_active_alarms"

    @property
    def native_value(self) -> str:
        alarms = self._alarms
        if not alarms:
            return "无"
        return "、".join(self._title(a) for a in alarms)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        details = []
        for alarm in self._alarms:
            details.append({
                "名称": self._title(alarm),
                "key": alarm.get("key"),
                "等级": alarm.get("level"),
                "触发时间": alarm.get("createdAt"),
                "触发值": alarm.get("firedValue"),
            })
        return {"告警详情": details}
