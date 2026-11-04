"""自动准备「能量流」看板与能量配置。

设计要点
--------
* 实体 ID 一律从实体注册表按 ``{device_id}_{key}`` 反查，绝不硬编码。
  这样换了设备名（中文名会参与 entity_id 生成）也不会失效。
* HA 没有「集成注册 Lovelace 看板」的公开 API：``DashboardsCollection``
  是 ``lovelace.async_setup`` 里的局部变量，外部拿不到。所以这里用三步：
    1. 内存注入 ``hass.data[LOVELACE_DATA].dashboards``（当次生效）
    2. 注册 frontend 面板（侧边栏立刻出现）
    3. 用 ``LovelaceStorage.async_save`` 落盘配置（核心自己的写法）
  条目本身另外补写 ``lovelace_dashboards`` 存储，保证重启后集合能加载到。
* 全流程 try/except 兜底：任何一步失败都只记日志，不影响集成加载。
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .card_frontend import CARD_FILE, STATIC_URL, async_register_card
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_PATH = "energy-flow"
DASHBOARD_ID = "energy_flow"
TITLE = "能量流"
ICON = "mdi:solar-power"

DASHBOARDS_STORAGE_KEY = "lovelace_dashboards"
DASHBOARDS_STORAGE_VERSION = 1
DASHBOARDS_STORAGE_MINOR_VERSION = 1

# 需要从实体注册表反查的 key（对应 sensor.py 里 SENSOR_DEFS 的 key）
K_PV_POWER = "pvAllInputPower"
K_SOC = "batterySOC"
K_BATT_V = "batteryVoltage"
K_CHARGE = "chargingPower"
K_DISCHARGE = "dischargePower"
K_GRID_V = "gridVoltage"
K_GRID_F = "gridFrequency"
K_LOAD = "offGridOutputPower"
K_STATUS = "deviceOperatingStatusNext"

K_E_PV = "pvGeneratedEnergy"
K_E_LOAD = "totalLoadConsumptionEnergy"
K_E_IMPORT = "dEGridToLoadTotalEE"
K_E_EXPORT = "dEpvToGridTotalEE"
K_E_CHARGE = "totalBatteryChargingEnergy"
K_E_DISCHARGE = "totalDischargingCapacity"

K_D_PV = "pvGeneratedEnergyOfDay"
K_D_LOAD = "dailyLoadConsumptionEnergy"
K_D_IMPORT = "dEGridToLoadTodayEE"
K_D_EXPORT = "dEpvToGridTodayEE"
K_D_CHARGE = "dailyChargingCapacity"
K_D_DISCHARGE = "dailyDischargingCapacity"


def _sid(hass: HomeAssistant, device_id: str, key: str) -> str | None:
    """按 unique_id 反查 sensor 实体 ID。"""
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{device_id}_{key}"
    )


def _overview(hass: HomeAssistant, device_id: str) -> str | None:
    """告警总览实体「当前告警」。"""
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{device_id}_active_alarms"
    )


def _switch_id(hass: HomeAssistant, device_id: str, key: str) -> str | None:
    """按 unique_id 反查 switch 实体 ID。"""
    return er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{device_id}_{key}"
    )


def _rows(hass: HomeAssistant, device_id: str, pairs: list[tuple[str, str]]) -> list[dict]:
    """把 (key, 中文名) 转成 entities 卡片的行，缺失的跳过。"""
    out = []
    for key, name in pairs:
        eid = _sid(hass, device_id, key)
        if eid:
            out.append({"entity": eid, "name": name})
    return out


def _build_dashboard(
    hass: HomeAssistant, device_id: str, custom_card: bool = True
) -> dict[str, Any] | None:
    """构造看板配置；核心功率实体缺失则不建。

    ``custom_card`` 为 False 时（卡片资源注册失败，例如 Lovelace 处于
    YAML 资源模式）退回官方 ``power-sankey``，保证看板里永远有一张能用的
    功率流向图，而不是一个「自定义元素未找到」的坏卡片。
    """
    pv = _sid(hass, device_id, K_PV_POWER)
    charge = _sid(hass, device_id, K_CHARGE)
    discharge = _sid(hass, device_id, K_DISCHARGE)
    if not (pv and charge and discharge):
        _LOGGER.debug("缺少功率实体，跳过能量看板")
        return None

    live_rows = _rows(
        hass,
        device_id,
        [
            (K_PV_POWER, "PV 总功率"),
            (K_SOC, "电池 SOC"),
            (K_BATT_V, "电池电压"),
            (K_CHARGE, "充电功率"),
            (K_DISCHARGE, "放电功率"),
            (K_GRID_V, "电网电压"),
            (K_GRID_F, "电网频率"),
            (K_LOAD, "离网负载功率"),
            (K_STATUS, "运行状态"),
        ],
    )
    alarm = _overview(hass, device_id)
    if alarm:
        live_rows.append({"entity": alarm, "name": "当前告警"})

    today_rows = _rows(
        hass,
        device_id,
        [
            (K_D_PV, "今日发电"),
            (K_D_LOAD, "今日负载用电"),
            (K_D_IMPORT, "今日购电"),
            (K_D_EXPORT, "今日上网"),
            (K_D_CHARGE, "今日充电"),
            (K_D_DISCHARGE, "今日放电"),
        ],
    )
    total_rows = _rows(
        hass,
        device_id,
        [
            (K_E_PV, "PV 累计发电"),
            (K_E_LOAD, "累计负载用电"),
            (K_E_IMPORT, "累计购电"),
            (K_E_EXPORT, "累计上网"),
            (K_E_CHARGE, "累计充电"),
            (K_E_DISCHARGE, "累计放电"),
        ],
    )

    cards: list[dict[str, Any]] = []

    if custom_card:
        # 自定义卡片：带数值的实时功率流向图（图形 + 数字都在上面）
        flow_card: dict[str, Any] = {
            "type": "custom:siseli-power-flow",
            "title": "能量分配（实时功率）",
            "pv": pv,
            "battery_charge": charge,
            "battery_discharge": discharge,
        }
        for field, key in (
            ("grid_import", "pacToUserTotal"),
            ("grid_export", "pacToGridTotal"),
            ("load", K_LOAD),
            ("soc", K_SOC),
        ):
            if eid := _sid(hass, device_id, key):
                flow_card[field] = eid

        # 右上角的实时刷新开关
        if sw := _switch_id(hass, device_id, "realtime"):
            flow_card["realtime_switch"] = sw

        # 底部统计：全部来自云端月度汇总实体（今日 / 本月）
        stats: dict[str, str] = {}
        registry = er.async_get(hass)
        for field, period, key in (
            ("solar_today", "today", "pvGeneratedEnergy"),
            ("solar_month", "total", "pvGeneratedEnergy"),
            ("grid_in_today", "today", "buyElectricityQuantity"),
            ("grid_in_month", "total", "buyElectricityQuantity"),
            ("grid_out_today", "today", "sellElectricityQuantity"),
            ("grid_out_month", "total", "sellElectricityQuantity"),
            ("batt_in_today", "today", "chargeElectricityQuantity"),
            ("batt_in_month", "total", "chargeElectricityQuantity"),
            ("batt_out_today", "today", "dischargeElectricityQuantity"),
            ("batt_out_month", "total", "dischargeElectricityQuantity"),
            ("home_today", "today", "consumeElectricityQuantity"),
            ("home_month", "total", "consumeElectricityQuantity"),
        ):
            eid = registry.async_get_entity_id(
                "sensor", DOMAIN, f"{device_id}_energy_{period}_{key}"
            )
            if eid:
                stats[field] = eid
        if stats:
            flow_card["stats"] = stats

        cards.append(flow_card)
    else:
        # 降级：官方 Sankey（有图形无数字），至少能用
        cards.append(
            {
                "type": "power-sankey",
                "title": "当前功率流",
                "collection_key": "energy_dashboard_now",
            }
        )
    right = {"type": "entities", "title": "关键读数", "state_color": True, "entities": live_rows}
    pair_cards: list[dict[str, Any]] = []
    if _sid(hass, device_id, K_E_PV):
        pair_cards.append(
            {
                "type": "power-sources-graph",
                "title": "功率曲线",
                "collection_key": "energy_dashboard_now",
            }
        )
    pair_cards.append(right)
    cards.append(
        {
            "type": "grid",
            "columns": 2,
            "square": False,
            "cards": pair_cards,
        }
    )
    if today_rows:
        cards.append({"type": "entities", "title": "今日电量", "entities": today_rows})

    # 这几张卡必须带 collection_key，否则不会加入共享的能量集合，
    # 只会渲染一次快照，表现为「永远不刷新」。
    # energy_dashboard = 长期统计（小时粒度，整点后才更新）；
    # 实时功率在「实时」页，用 energy_dashboard_now。
    stats_cards: list[dict[str, Any]] = [
        {"type": "energy-date-selection", "collection_key": "energy_dashboard"},
        {
            "type": "energy-distribution",
            "title": "能量分配（累计电量 kWh）",
            "collection_key": "energy_dashboard",
            "link_dashboard": True,
        },
        {"type": "energy-solar-graph", "collection_key": "energy_dashboard"},
        {"type": "energy-usage-graph", "collection_key": "energy_dashboard"},
        {
            "type": "energy-sources-table",
            "collection_key": "energy_dashboard",
            "show_only_totals": True,
        },
    ]
    if total_rows:
        stats_cards.append(
            {"type": "entities", "title": "累计电量", "entities": total_rows}
        )

    return {
        "title": TITLE,
        "views": [
            {
                "title": "实时",
                "path": "live",
                "icon": "mdi:solar-power-variant",
                "cards": cards,
            },
            {
                "title": "电量统计",
                "path": "stats",
                "icon": "mdi:chart-timeline-variant",
                "cards": stats_cards,
            },
        ],
    }


def _build_sources(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """构造能量配置的 energy_sources，缺实体的源直接不出现。"""
    sources: list[dict[str, Any]] = []

    e_pv = _sid(hass, device_id, K_E_PV)
    if e_pv:
        src: dict[str, Any] = {
            "type": "solar",
            "stat_energy_from": e_pv,
            "config_entry_solar_forecast": None,
        }
        if pv := _sid(hass, device_id, K_PV_POWER):
            src["stat_rate"] = pv
        sources.append(src)

    e_imp, e_exp = _sid(hass, device_id, K_E_IMPORT), _sid(hass, device_id, K_E_EXPORT)
    if e_imp or e_exp:
        src = {
            "type": "grid",
            "stat_energy_from": e_imp,
            "stat_energy_to": e_exp,
            "cost_adjustment_day": 0.0,
        }
        imp = _sid(hass, device_id, "pacToUserTotal")
        exp = _sid(hass, device_id, "pacToGridTotal")
        if imp or exp:
            cfg: dict[str, Any] = {}
            if imp:
                cfg["stat_rate_from"] = imp
            if exp:
                cfg["stat_rate_to"] = exp
            src["power_config"] = cfg
        sources.append(src)

    e_ch, e_dis = _sid(hass, device_id, K_E_CHARGE), _sid(hass, device_id, K_E_DISCHARGE)
    if e_ch and e_dis:
        src = {
            "type": "battery",
            # from = 放电（出电池），to = 充电（入电池）
            "stat_energy_from": e_dis,
            "stat_energy_to": e_ch,
        }
        ch = _sid(hass, device_id, K_CHARGE)
        dis = _sid(hass, device_id, K_DISCHARGE)
        if ch and dis:
            src["power_config"] = {"stat_rate_from": dis, "stat_rate_to": ch}
        sources.append(src)

    return sources


async def _async_persist_item(hass: HomeAssistant, item: dict[str, Any]) -> None:
    """把看板条目补写进 lovelace_dashboards 存储，重启后集合才能加载到。"""
    store: Store[dict[str, Any]] = Store(
        hass,
        DASHBOARDS_STORAGE_VERSION,
        DASHBOARDS_STORAGE_KEY,
        minor_version=DASHBOARDS_STORAGE_MINOR_VERSION,
    )
    data = await store.async_load() or {}
    items: list[dict[str, Any]] = list(data.get("items") or [])
    if any(i.get("url_path") == URL_PATH for i in items):
        return
    items.append(item)
    await store.async_save({"items": items})


async def async_ensure_energy_prefs(hass: HomeAssistant, device_id: str) -> None:
    """把本设备的计量点追加进能量配置（只追加，绝不覆盖已有配置）。"""
    try:
        from homeassistant.components.energy.data import async_get_manager

        manager = await async_get_manager(hass)
        current = manager.data or {}
        existing: list[dict[str, Any]] = list(current.get("energy_sources") or [])

        used: set[str] = set()
        for src in existing:
            for fld in ("stat_energy_from", "stat_energy_to"):
                if val := src.get(fld):
                    used.add(val)

        fresh = [
            src
            for src in _build_sources(hass, device_id)
            if src.get("stat_energy_from") and src["stat_energy_from"] not in used
        ]
        if not fresh:
            return

        await manager.async_update({"energy_sources": existing + fresh})
        _LOGGER.info("已向能量面板追加 %s 个计量源", len(fresh))
    except Exception:  # noqa: BLE001
        _LOGGER.warning("写入能量配置失败，可手动在「设置 → 仪表盘 → 能量」添加", exc_info=True)


async def async_ensure_energy_ui(hass: HomeAssistant, device_id: str) -> None:
    """准备看板 + 能量配置。任何失败都不影响集成。"""
    await async_ensure_energy_prefs(hass, device_id)
    # 自定义卡片必须在看板渲染前注册好；返回 False 说明资源不可用（比如
    # Lovelace 处于 YAML 资源模式），此时看板降级用官方卡片。
    custom_ok = await async_register_card(hass)

    try:
        from homeassistant.components import frontend
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        from homeassistant.components.lovelace.dashboard import LovelaceStorage

        lovelace = hass.data.get(LOVELACE_DATA)
        if lovelace is None:
            _LOGGER.debug("Lovelace 尚未初始化，跳过能量看板")
            return
        if URL_PATH in lovelace.dashboards:
            return

        config = _build_dashboard(hass, device_id, custom_card=custom_ok)
        if config is None:
            return

        if not custom_ok:
            _LOGGER.warning(
                "自定义卡片资源未能注册，看板首卡降级为官方 power-sankey；"
                "如需数字请手动在「设置 → 仪表盘 → 资源」添加 %s/%s",
                STATIC_URL,
                CARD_FILE,
            )

        item = {
            "id": DASHBOARD_ID,
            "url_path": URL_PATH,
            "title": TITLE,
            "icon": ICON,
            "show_in_sidebar": True,
            "require_admin": False,
            "mode": "storage",
        }

        dash = LovelaceStorage(hass, item)
        await _async_persist_item(hass, item)
        lovelace.dashboards[URL_PATH] = dash
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            frontend_url_path=URL_PATH,
            sidebar_title=TITLE,
            sidebar_icon=ICON,
            show_in_sidebar=True,
            require_admin=False,
            config={"mode": "storage"},
        )
        await dash.async_save(config)
        _LOGGER.info("已自动创建「%s」看板：/%s", TITLE, URL_PATH)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("自动创建能量看板失败，不影响集成运行", exc_info=True)
