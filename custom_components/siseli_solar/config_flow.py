"""配置流程：输入雷零账号密码 → 自动发现设备 → 添加。"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SiseliApi, SiseliAuthError, SiseliError
from .const import (
    CONF_ACCOUNT,
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_EXPIRES_AT,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SHOW_ALL_ALARMS,
    CONF_USER_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCOUNT): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class SiseliSolarConfigFlow(ConfigFlow, domain=DOMAIN):
    """添加集成：账号密码 → 选设备。"""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._account: str = ""
        self._password: str = ""
        self._devices: list[dict[str, Any]] = []
        self._api: SiseliApi | None = None
        self._reauth_entry: ConfigEntry | None = None

    # ---------------------------------------------------------------- 首次添加

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            api = SiseliApi(session, user_input[CONF_ACCOUNT].strip(),
                            user_input[CONF_PASSWORD])
            try:
                await api.async_login()
                devices = await api.async_devices()
            except SiseliAuthError:
                errors["base"] = "invalid_auth"
            except SiseliError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("登录雷零云失败")
                errors["base"] = "unknown"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    self._account = user_input[CONF_ACCOUNT].strip()
                    self._password = user_input[CONF_PASSWORD]
                    self._devices = devices
                    self._api = api
                    if len(devices) == 1:
                        return await self._async_create(devices[0])
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            device = next(d for d in self._devices if str(d["id"]) == user_input[CONF_DEVICE_ID])
            return await self._async_create(device)

        options = {
            str(d["id"]): f"{d.get('name') or '未命名设备'}（DTU {d.get('dtuDtuid') or d['id']}）"
            for d in self._devices
        }
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(options)}),
        )

    async def _async_create(self, device: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(str(device["id"]))
        self._abort_if_unique_id_configured()

        api = self._api
        return self.async_create_entry(
            title=device.get("name") or f"雷零 {device['id']}",
            data={
                CONF_ACCOUNT: self._account,
                CONF_PASSWORD: self._password,
                CONF_DEVICE_ID: str(device["id"]),
                CONF_DEVICE_NAME: device.get("name") or "雷零逆控机",
                "manufacturer": device.get("deviceManufacturerName") or "雷零科技",
                "model": device.get("deviceSortLocaleText") or "逆控一体机",
                "sw_version": device.get("softwareVersion"),
                "serial_number": device.get("serialNumber"),
                CONF_ACCESS_TOKEN: api.access_token if api else None,
                CONF_REFRESH_TOKEN: api.refresh_token if api else None,
                CONF_EXPIRES_AT: api.access_expires_at if api else None,
                CONF_USER_ID: api.user_id if api else None,
            },
        )

    # ---------------------------------------------------------------- 重新认证

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        assert entry is not None

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            api = SiseliApi(session, entry.data[CONF_ACCOUNT], user_input[CONF_PASSWORD])
            try:
                await api.async_login()
            except SiseliAuthError:
                errors["base"] = "invalid_auth"
            except SiseliError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_ACCESS_TOKEN: api.access_token,
                        CONF_REFRESH_TOKEN: api.refresh_token,
                        CONF_EXPIRES_AT: api.access_expires_at,
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"account": entry.data[CONF_ACCOUNT]},
            errors=errors,
        )

    # ---------------------------------------------------------------- 选项

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SiseliOptionsFlow()


class SiseliOptionsFlow(OptionsFlow):
    """轮询间隔。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
        show_all = self.config_entry.options.get(CONF_SHOW_ALL_ALARMS, False)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional("scan_interval", default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                    ),
                    vol.Optional(CONF_SHOW_ALL_ALARMS, default=show_all): bool,
                }
            ),
        )
