"""开关平台：实时刷新（开启云端速报，把上报周期压到 3 秒）。"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SiseliError
from .const import DOMAIN, FAST_ACTIVE_INTERVAL, FAST_MAX_SECONDS
from .coordinator import SiseliCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SiseliCoordinator = entry.runtime_data

    device_info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.device_id)},
        name=entry.data.get("device_name") or "雷零逆控机",
        manufacturer=entry.data.get("manufacturer") or "雷零科技",
        model=entry.data.get("model") or "逆控一体机",
        sw_version=entry.data.get("sw_version"),
        serial_number=entry.data.get("serial_number"),
    )

    async_add_entities([SiseliRealtimeSwitch(coordinator, device_info)])


class SiseliRealtimeSwitch(SwitchEntity):
    """实时刷新开关。

    开启后云端让 DTU 每 3 秒上报一次，HA 的轮询同时提速到 5 秒；
    云端 180 秒自动失效，集成每 60 秒续订，最长开 30 分钟后自动关。
    """

    _attr_has_entity_name = True
    _attr_name = "实时刷新"
    _attr_icon = "mdi:flash"
    _attr_should_poll = False

    def __init__(self, coordinator: SiseliCoordinator, device_info: DeviceInfo) -> None:
        self.coordinator = coordinator
        self._attr_device_info = device_info
        self._attr_unique_id = f"{coordinator.device_id}_realtime"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
        # 上次异常退出可能留下还在生效的速报（180 秒自然失效），顺手清掉
        if self.coordinator.api.user_id:
            try:
                await self.coordinator.api.async_fast_stop(
                    self.coordinator.device_id, self.coordinator.client_id
                )
            except SiseliError:
                pass

    @property
    def is_on(self) -> bool:
        return self.coordinator.fast_active

    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "轮询间隔": (
                f"{FAST_ACTIVE_INTERVAL} 秒"
                if self.coordinator.fast_active
                else f"{int(self.coordinator.base_interval.total_seconds())} 秒"
            ),
            "设备上报周期": "3 秒" if self.coordinator.fast_active else "约 60 秒",
            "自动关闭": f"开启 {FAST_MAX_SECONDS // 60} 分钟后",
            "client_id": self.coordinator.client_id,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self.coordinator.api.user_id:
            raise HomeAssistantError(
                "缺少 userId，无法构造速报用的 clientID；请在集成页面重新加载一次"
            )

        if not await self.coordinator.async_check_fast_supported():
            raise HomeAssistantError("这台设备不支持速报（fast report）")

        try:
            await self.coordinator.async_start_fast()
        except SiseliError as err:
            raise HomeAssistantError(f"开启实时刷新失败：{err}") from err

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_stop_fast()
        self.async_write_ha_state()
