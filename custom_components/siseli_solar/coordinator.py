"""数据协调器：轮询云端实时状态，处理离线/忙、重认证、以及「实时刷新」速报模式。"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SiseliApi, SiseliAuthError, SiseliDeviceOffline, SiseliError
from .const import (
    MONTH_ENERGY_INTERVAL,
    DOMAIN,
    FAST_ACTIVE_INTERVAL,
    FAST_MAX_SECONDS,
    FAST_RENEW_SECONDS,
    FAST_SCENE_CODE,
)

_LOGGER = logging.getLogger(__name__)

BUSY_CODE = 70001  # Device is busy：设备正在处理上一条指令，属瞬时状态
NETWORK_CODES = {-1, -2}  # 网络错误 / 非 JSON 响应：多半是 DNS 或链路抖动
MAX_TOLERATED_FAILURES = 3


class SiseliCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """每 <scan_interval> 秒拉一次 /remote/device/state/latest。"""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: SiseliApi,
        device_id: str,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_id}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry = entry
        self.api = api
        self.device_id = device_id
        self.online: bool = True
        self.base_interval = timedelta(seconds=scan_interval)

        # 告警（category=2）
        self.firing_alarms: dict[str, dict[str, Any]] = {}
        self.alarm_meta: dict[str, str] = {}
        self.alarm_initialized = False

        # 「实时刷新」状态
        self.fast_active: bool = False
        self.fast_until: float | None = None
        self._renew_unsub: CALLBACK_TYPE | None = None
        self._deadline_unsub: CALLBACK_TYPE | None = None
        self._offline_logged = False
        self._failures = 0

        # 云端电量汇总（今日 / 本月至今）
        self.month_energy: dict[str, dict[str, Any]] = {}
        self._month_energy_at: float = 0.0

    # ---------------------------------------------------------------- 轮询

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            payload = await self.api.async_state_latest(self.device_id)
        except SiseliAuthError as err:
            raise ConfigEntryAuthFailed(f"登录失效：{err}") from err
        except SiseliDeviceOffline as err:
            if err.code == BUSY_CODE:
                # 设备忙不是离线：保留上一帧，availability 不动，下一轮再试
                _LOGGER.debug("设备忙，本轮跳过")
                return self.data or {}
            # 真离线：保留上一帧数值，但实体标记不可用
            self.online = False
            if not self._offline_logged:
                _LOGGER.debug("设备本轮不可达：%s", err)
                self._offline_logged = True
            return self.data or {}
        except SiseliError as err:
            if err.code in NETWORK_CODES:
                # DNS/链路抖动：单次失败不要让 200 多个实体一起变不可用，
                # 连续失败 MAX_TOLERATED_FAILURES 次才真正判失败。
                self._failures += 1
                if self._failures < MAX_TOLERATED_FAILURES and self.data:
                    _LOGGER.debug(
                        "网络抖动（第 %s 次），保留上一帧：%s", self._failures, err
                    )
                    return self.data
                self._failures = 0
            raise UpdateFailed(str(err)) from err

        self.online = True
        self._offline_logged = False
        self._failures = 0

        self._parse_alarms(payload.get("firingAlarms") or [])

        # 月度电量汇总顺带刷新（有节流，不是每轮都请求）
        await self._async_refresh_month_energy()

        fields = payload.get("fields") or {}
        return {
            key: value
            for key, value in fields.items()
            if isinstance(value, dict) and value.get("value") is not None
        }

    # ---------------------------------------------------------------- 月度电量

    async def _async_refresh_month_energy(self) -> None:
        """取云端月度电量汇总；按 MONTH_ENERGY_INTERVAL 节流。"""
        now = time.monotonic()
        if self.month_energy and now - self._month_energy_at < MONTH_ENERGY_INTERVAL:
            return
        try:
            data = await self.api.async_monthly_energy(self.device_id)
        except SiseliError as err:
            _LOGGER.debug("月度电量获取失败：%s", err)
            return
        if data:
            self.month_energy = data
            self._month_energy_at = now

    # ---------------------------------------------------------------- 告警

    def _parse_alarms(self, alarms: list[dict[str, Any]]) -> None:
        """firingAlarms 里只保留仍在生效的（disappearedAt 为空）。

        多个告警可能共享同一个 key（不同时刻各触发一次），取最新那条。
        """
        active: dict[str, dict[str, Any]] = {}
        for alarm in alarms:
            key = alarm.get("key")
            if not key or alarm.get("disappearedAt"):
                continue
            created = alarm.get("createdAt") or ""
            prev = active.get(key)
            if prev is None or str(created) > str(prev.get("createdAt") or ""):
                active[key] = alarm
        self.firing_alarms = active

    async def async_load_alarm_meta(self) -> None:
        """拉一次 category=2 的 138 个告警位定义（key → 中文名）。"""
        if self.alarm_initialized:
            return
        try:
            groups = await self.api.async_attribute_groups(self.device_id, 2)
        except SiseliError as err:
            _LOGGER.warning("获取告警位定义失败：%s", err)
            return

        meta: dict[str, str] = {}
        for group in groups:
            for attr in group.get("attributes") or []:
                key = attr.get("key")
                if key:
                    meta[key] = attr.get("name") or key
        if meta:
            self.alarm_meta = meta
            self.alarm_initialized = True
            _LOGGER.debug("载入 %s 个告警位定义", len(meta))

    # ---------------------------------------------------------------- 速报

    @property
    def client_id(self) -> str:
        """clientID 必须匹配 ^user_<userId>_<6 位字母数字$。

        用 entry_id 的哈希做后缀，重启后仍是同一个 ID，可以关掉上次遗留的速报。
        """
        suffix = hashlib.md5(self.entry.entry_id.encode()).hexdigest()[:6]
        return f"user_{self.api.user_id}_{suffix}"

    async def async_check_fast_supported(self) -> bool:
        try:
            return await self.api.async_fast_supported(self.device_id)
        except SiseliError as err:
            _LOGGER.debug("查询速报能力失败：%s", err)
            return False

    async def async_start_fast(self) -> None:
        """开启速报：3 秒上报，180 秒有效期，每 60 秒续订一次。"""
        if self.fast_active:
            return

        result = await self.api.async_fast_start(
            self.device_id, self.client_id, FAST_SCENE_CODE
        )
        self.fast_active = True
        self.fast_until = None
        _LOGGER.info(
            "已开启实时刷新：上报周期 %s ms，%s 秒后失效，每 %s 秒续订（%s）",
            (result or {}).get("reportPeriodInMills"),
            (result or {}).get("willStopInMills", 0) // 1000,
            FAST_RENEW_SECONDS,
            self.client_id,
        )

        # 提速轮询
        self.update_interval = timedelta(seconds=FAST_ACTIVE_INTERVAL)

        # 定期续订（云端 180 秒自动失效，必须在 60 秒时续）
        self._renew_unsub = async_track_time_interval(
            self.hass, self._async_renew_fast, timedelta(seconds=FAST_RENEW_SECONDS)
        )
        # 安全阀：最长开 30 分钟，避免忘记关
        self._deadline_unsub = async_call_later(
            self.hass, FAST_MAX_SECONDS, self._async_fast_timeout
        )
        self.async_update_listeners()

    async def async_stop_fast(self) -> None:
        """关闭速报并恢复原轮询间隔。"""
        self._cancel_fast_timers()
        if not self.fast_active:
            return

        self.fast_active = False
        self.update_interval = self.base_interval
        try:
            await self.api.async_fast_stop(self.device_id, self.client_id)
            _LOGGER.info("已关闭实时刷新，轮询恢复为 %s", self.base_interval)
        except SiseliError as err:
            _LOGGER.warning("关闭速报失败（会在 3 分钟内自然失效）：%s", err)
        self.async_update_listeners()

    async def _async_renew_fast(self, _now: Any = None) -> None:
        if not self.fast_active:
            return
        try:
            await self.api.async_fast_start(
                self.device_id, self.client_id, FAST_SCENE_CODE
            )
            _LOGGER.debug("速报已续订")
        except SiseliError as err:
            _LOGGER.warning("续订速报失败，将自动关闭：%s", err)
            await self.async_stop_fast()

    async def _async_fast_timeout(self, _now: Any = None) -> None:
        _LOGGER.info("实时刷新已开启 %s 分钟，自动关闭", FAST_MAX_SECONDS // 60)
        await self.async_stop_fast()

    def _cancel_fast_timers(self) -> None:
        for attr in ("_renew_unsub", "_deadline_unsub"):
            unsub = getattr(self, attr)
            if unsub is not None:
                unsub()
                setattr(self, attr, None)

    async def async_shutdown_fast(self) -> None:
        """卸载集成时清理定时器并尽力关掉速报。"""
        self._cancel_fast_timers()
        if self.fast_active:
            self.fast_active = False
            try:
                await self.api.async_fast_stop(self.device_id, self.client_id)
            except SiseliError:
                pass
