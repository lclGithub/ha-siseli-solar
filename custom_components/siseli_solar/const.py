"""常量定义：域名、配置键、默认参数、精选实体清单。"""

from __future__ import annotations

DOMAIN = "siseli_solar"
MANUFACTURER = "雷零科技 (四色云)"

CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
CONF_USER_ID = "user_id"
CONF_SHOW_ALL_ALARMS = "show_all_alarms"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 600

# ---- 实时刷新（速报）----
# 云端 scene 是枚举码而不是名字：swagger 写 ["DEVICE_LIVE_ENERGY_FLOW"]，
# 但服务端按 code 反序列化，传字符串会 20101 invalid format，只能传 1。
FAST_SCENE_CODE = 1
# 开启速报时把 HA 轮询压到 5 秒（设备端是 3 秒上报一次）
FAST_ACTIVE_INTERVAL = 5
# 云端 180 秒自动失效，必须每 60 秒续订
FAST_RENEW_SECONDS = 60
# 安全阀：最长开 30 分钟
FAST_MAX_SECONDS = 1800

# ---------------------------------------------------------------------------
# 告警位：云端 category=2 共 138 个，全部建成 binary_sensor。
# 下面这 22 个是真正需要日常盯的（市电、电池、过温、逆变保护、计量、PV 安全），
# 默认启用；其余 116 个默认禁用，需要时在实体设置里单独打开。
# ---------------------------------------------------------------------------
PRIORITY_ALARMS: frozenset[str] = frozenset({
    # 市电 / 并网
    "noGrid",                        # 无市电
    # 电池
    "socLow",                        # 电池SOC低
    "batteryVoltageTooLow",          # 电池电压过低
    "tqfBatteryVoltageTooHigh",      # 电池电压过高
    "batNotOpen",                    # 电池开关未打开
    "batteryReversePolarity",        # 电池反接
    "bmsWarning",                    # 电池管理系统信息异常
    "bmsMalfunction",                # BMS故障
    "batteryCommunicationFailure",   # 电池通讯故障
    "batteryOverTemperature",        # 电池过温
    # 温度 / 散热
    "inverterOvertemperature",       # INV过温
    "boostOvertemperature",          # Boost过温
    "llcOvertemperature",            # LLC过温
    "fanFail",                       # 风扇异常
    # 离网输出
    "epsLoadNormal",                 # 离网过载
    "offGridOutputShortCircuit",     # 离网输出短路
    # 计量 / CT
    "meterFailure",                  # 电表通信异常
    "ctReverseConnection",           # CT反接
    # PV 安全
    "pvInputOvervoltage",            # 输入PV电压过高
    "panelInsulationResLow",         # 面板绝缘阻抗ISO过低
    "gfciFaultHigh",                 # GFCI过高
    # 控制板
    "eepromRWFailure",               # 存储器EEPROM读写异常
})

# ---------------------------------------------------------------------------
# 精选实体：只保留这台 12KW 单相机真正有意义的字段（约 60 个）。
# 字段含义已逐条对照过云端 gatherAttributes 的中文名与实时值。
#   key:         云端属性键
#   name:        HA 实体名（中文）
#   unit:        单位
#   dc:          device_class
#   sc:          state_class
#   icon:        图标（可选）
#   cat:         "diagnostic" 表示归到诊断类（默认不显示在概览）
# ---------------------------------------------------------------------------
SENSOR_DEFS: tuple[dict, ...] = (
    # ---------------- PV ----------------
    {"key": "pv1Voltage", "name": "PV1 电压", "unit": "V", "dc": "voltage", "sc": "measurement"},
    {"key": "pv1InputCurrent", "name": "PV1 电流", "unit": "A", "dc": "current", "sc": "measurement"},
    {"key": "pv1InputPower", "name": "PV1 功率", "unit": "W", "dc": "power", "sc": "measurement"},
    {"key": "pv2Voltage", "name": "PV2 电压", "unit": "V", "dc": "voltage", "sc": "measurement"},
    {"key": "pv2InputCurrent", "name": "PV2 电流", "unit": "A", "dc": "current", "sc": "measurement"},
    {"key": "pv2InputPower", "name": "PV2 功率", "unit": "W", "dc": "power", "sc": "measurement"},
    {"key": "pvAllInputPower", "name": "PV 总功率", "unit": "W", "dc": "power", "sc": "measurement",
     "icon": "mdi:solar-power"},
    {"key": "generationPower", "name": "光伏功率(统计)", "unit": "kW", "dc": "power", "sc": "measurement"},
    {"key": "pvGeneratedEnergyOfDay", "name": "PV 今日发电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "pvGeneratedEnergy", "name": "PV 累计发电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},

    # ---------------- 电池 ----------------
    {"key": "batterySOC", "name": "电池 SOC", "unit": "%", "dc": "battery", "sc": "measurement",
     "icon": "mdi:battery"},
    {"key": "soh", "name": "电池 SOH", "unit": "%", "sc": "measurement", "icon": "mdi:battery-heart-variant"},
    {"key": "batteryVoltage", "name": "电池电压", "unit": "V", "dc": "voltage", "sc": "measurement"},
    {"key": "batteryCurrent", "name": "电池电流", "unit": "A", "dc": "current", "sc": "measurement"},
    {"key": "batteryTemperature", "name": "电池温度", "unit": "°C", "dc": "temperature", "sc": "measurement"},
    {"key": "bms_MaxChargeCurr", "name": "BMS 允许最大充电电流", "unit": "A", "dc": "current", "sc": "measurement",
     "cat": "diagnostic"},
    {"key": "bms_MaxDischargeCurr", "name": "BMS 允许最大放电电流", "unit": "A", "dc": "current", "sc": "measurement",
     "cat": "diagnostic"},
    {"key": "chargingPower", "name": "充电功率", "unit": "W", "dc": "power", "sc": "measurement",
     "icon": "mdi:battery-arrow-up"},
    {"key": "dischargePower", "name": "放电功率", "unit": "W", "dc": "power", "sc": "measurement",
     "icon": "mdi:battery-arrow-down"},
    {"key": "totalBatteryChargeAndDischargePower", "name": "电池充放电功率", "unit": "W", "dc": "power",
     "sc": "measurement"},
    {"key": "ykBatteryType", "name": "电池类型", "icon": "mdi:battery-outline"},

    # ---------------- 电网 ----------------
    {"key": "gridVoltage", "name": "电网电压", "unit": "V", "dc": "voltage", "sc": "measurement",
     "icon": "mdi:transmission-tower"},
    {"key": "iac_R", "name": "电网电流", "unit": "A", "dc": "current", "sc": "measurement"},
    {"key": "gridFrequency", "name": "电网频率", "unit": "Hz", "dc": "frequency", "sc": "measurement"},
    {"key": "powerFactor", "name": "功率因数", "dc": "power_factor", "sc": "measurement"},
    {"key": "pactouserR", "name": "电网取电功率(R)", "unit": "W", "dc": "power", "sc": "measurement"},
    {"key": "pacToUserTotal", "name": "电网取电总功率", "unit": "W", "dc": "power", "sc": "measurement",
     "icon": "mdi:transmission-tower-import"},
    {"key": "pacToGridR", "name": "馈入电网功率(R)", "unit": "W", "dc": "power", "sc": "measurement"},
    {"key": "pacToGridTotal", "name": "馈入电网总功率", "unit": "W", "dc": "power", "sc": "measurement",
     "icon": "mdi:transmission-tower-export"},
    {"key": "totalGridLinePower", "name": "电网功率", "unit": "W", "dc": "power", "sc": "measurement"},

    # ---------------- 负载 ----------------
    {"key": "load_power", "name": "负载功率(统计)", "unit": "kW", "dc": "power", "sc": "measurement",
     "icon": "mdi:home-lightning-bolt"},
    {"key": "gridSiteLoad", "name": "网侧负载功率", "unit": "W", "dc": "power", "sc": "measurement"},
    {"key": "pLocalLoadtotal", "name": "单机负载总功率", "unit": "W", "dc": "power", "sc": "measurement"},
    {"key": "offGridOutputPower", "name": "离网负载功率", "unit": "W", "dc": "power", "sc": "measurement"},
    {"key": "epsVacR", "name": "离网输出电压", "unit": "V", "dc": "voltage", "sc": "measurement"},
    {"key": "epsIacR", "name": "离网输出电流", "unit": "A", "dc": "current", "sc": "measurement"},

    # ---------------- 温度 / 运行 ----------------
    {"key": "inv_Temp", "name": "逆变器温度", "unit": "°C", "dc": "temperature", "sc": "measurement"},
    {"key": "boost_Temp", "name": "IPM 温度", "unit": "°C", "dc": "temperature", "sc": "measurement"},
    {"key": "lccTemp", "name": "LLC 散热器温度", "unit": "°C", "dc": "temperature", "sc": "measurement"},
    {"key": "deviceOperatingStatusNext", "name": "运行状态", "icon": "mdi:state-machine"},
    {"key": "fanSpeed", "name": "风扇转速", "unit": "rpm", "sc": "measurement", "icon": "mdi:fan"},
    {"key": "totalRunTimeDH", "name": "累计运行时长", "icon": "mdi:clock-outline", "cat": "diagnostic"},
    {"key": "invMainErrorCode", "name": "主故障码", "cat": "diagnostic"},
    {"key": "invWarnSubCode", "name": "警告子码", "cat": "diagnostic"},
    {"key": "ctModeStatus", "name": "CT 模式", "cat": "diagnostic"},

    # ---------------- 电量统计 ----------------
    {"key": "dailyLoadConsumptionEnergy", "name": "今日负载用电量", "unit": "kWh", "dc": "energy",
     "sc": "total_increasing"},
    {"key": "totalLoadConsumptionEnergy", "name": "累计负载用电量", "unit": "kWh", "dc": "energy",
     "sc": "total_increasing"},
    {"key": "dailyChargingCapacity", "name": "今日充电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "totalBatteryChargingEnergy", "name": "累计充电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "dailyDischargingCapacity", "name": "今日放电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "totalDischargingCapacity", "name": "累计放电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "dEpvToGridTodayEE", "name": "今日上网电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "dEpvToGridTotalEE", "name": "累计上网电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "dEGridToLoadTodayEE", "name": "今日购电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "dEGridToLoadTotalEE", "name": "累计购电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "dESelfToLoadTodayEE", "name": "今日自用电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},
    {"key": "dESelfToLoadTotalEE", "name": "累计自用电量", "unit": "kWh", "dc": "energy", "sc": "total_increasing"},

    # ---------------- 设备信息（诊断） ----------------
    {"key": "armFirmwareVersionName", "name": "ARM 固件版本", "cat": "diagnostic"},
    {"key": "dspSoftwareVersionName", "name": "DSP 软件版本", "cat": "diagnostic"},
    {"key": "modbusProtocolVersion", "name": "Modbus 版本", "cat": "diagnostic"},
    {"key": "ratedPower", "name": "额定功率", "unit": "W", "dc": "power", "cat": "diagnostic"},
)

# ---------------------------------------------------------------------------
# 云端电量汇总（/deviceOverView/stateAttributeSummary/category/monthly）
# 一次调用返回整月按天数据，可同时算出「今日」与「本月至今」。
# 这组数据的「买电量/卖电量」口径比设备自带的今日购电/上网更准。
# ---------------------------------------------------------------------------
ENERGY_SUMMARY_DEFS: tuple[dict, ...] = (
    {"key": "pvGeneratedEnergy", "name": "发电量", "icon": "mdi:solar-power"},
    {"key": "buyElectricityQuantity", "name": "购电量", "icon": "mdi:transmission-tower-import"},
    {"key": "sellElectricityQuantity", "name": "售电量", "icon": "mdi:transmission-tower-export"},
    {"key": "chargeElectricityQuantity", "name": "充电量", "icon": "mdi:battery-arrow-up"},
    {"key": "dischargeElectricityQuantity", "name": "放电量", "icon": "mdi:battery-arrow-down"},
    {"key": "consumeElectricityQuantity", "name": "用电量", "icon": "mdi:home-lightning-bolt"},
)

# 月度电量刷新间隔（秒）：这数据每小时才变一次，没必要跟着 60 秒轮询
MONTH_ENERGY_INTERVAL = 600
