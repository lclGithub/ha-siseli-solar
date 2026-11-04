/**
 * 逆控机「能量分配（实时功率）」
 *
 * 版式 1:1 复刻 HA 原生 hui-energy-distribution-card：
 *   - 同一套 DOM 结构（三行 row + .lines 绝对定位的 SVG 连线层）
 *   - 同一套 CSS（圆 80x80、label 20px、spacer 84px、线条 vector-effect 等）
 *   - 同一组 SVG 路径 d（solar / return / battery-* / grid）
 *   - 同样的流动小圆点实现（沿 getPointAtLength 采样，Web Animations 驱动）
 *   - 图标用 ha-icon + MDI（原生用 ha-svg-icon + @mdi/js 的 path，图形一致）
 * 唯一区别：所有数值来自**实时功率实体（W）**，不是统计 kWh。
 *
 * 零依赖（原生 Web Component + SVG，不用 lit / CDN）。
 */
const SVGNS = "http://www.w3.org/2000/svg";

// ---------------------------------------------------------------- 常量
const CIRCLE_CIRCUMFERENCE = 238.76104; // r=38
const STEP_PX = 2;
const DOT_STROKE_PX = 4;

const PATHS = {
  solar: "M55,0 v15 c0,35 10,30 30,30 h20",
  return: "M45,0 v15 c0,35 -10,30 -30,30 h-20",
  batteryHouse: "M55,100 v-15 c0,-35 10,-30 30,-30 h20",
  batteryGrid: "M45,100 v-15 c0,-35 -10,-30 -30,-30 h-20",
  batterySolar: "M50,0 V100",
  grid: "M0,50 H100",
};

// 底部统计的四行（颜色沿用 CSS 变量，和圆环保持一致）
const STAT_ROWS = [
  { key: "solar", name: "太阳能", color: "var(--_solar)" },
  { key: "grid", name: "电网", color: "var(--_grid-in)" },
  { key: "battery", name: "电池", color: "var(--_batt-out)" },
  { key: "home", name: "我的家", color: "var(--primary-color)" },
];


const STYLES = `
  :host {
    --mdc-icon-size: 24px;
    display: block;
    --_solar: var(--energy-solar-color, #ff9800);
    --_grid-in: var(--energy-grid-consumption-color, #488fc2);
    --_grid-out: var(--energy-grid-return-color, #8353d1);
    --_batt-in: var(--energy-battery-in-color, #f06292);
    --_batt-out: var(--energy-battery-out-color, #4db6ac);
  }
  ha-card { min-width: 210px; padding-bottom: 34px; }
  .card-content { position: relative; direction: ltr; }
  .lines {
    position: absolute; bottom: 0; left: 0; width: 100%; height: 146px;
    display: flex; justify-content: center;
    padding: 0 16px 16px; box-sizing: border-box;
  }
  .lines.high { bottom: 100px; height: 156px; }
  .lines .flow { position: relative; width: calc(100% - 160px); height: 100%; max-width: 340px; }
  .lines .flow > svg { width: 100%; height: 100%; display: block; }
  .row { display: flex; justify-content: space-between; max-width: 500px; margin: 0 auto; }
  .circle-container { display: flex; flex-direction: column; align-items: center; position: relative; }
  .circle-container.solar { margin: 0 4px; height: 130px; }
  .circle-container.battery { height: 110px; justify-content: flex-end; }
  .spacer { width: 84px; }
  .grid-spacer { width: 84px; height: 100px; }
  .circle {
    width: 80px; height: 80px;
    border-radius: var(--ha-border-radius-circle, 50%);
    box-sizing: border-box; border: 2px solid;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    text-align: center; font-size: var(--ha-font-size-s, 13px); line-height: 12px;
    position: relative; text-decoration: none; color: var(--primary-text-color);
  }
  ha-icon { padding-bottom: 2px; }
  ha-icon.small { --mdc-icon-size: 12px; }
  .label {
    color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 13px);
    opacity: 1; height: 20px; overflow: hidden; text-overflow: ellipsis;
    max-width: 80px; white-space: nowrap;
  }
  path { stroke: var(--primary-text-color); stroke-width: 1; fill: none; }
  .battery-soc {
    display: inline-flex; align-items: center; justify-content: center;
    font-size: var(--ha-font-size-s, 13px); line-height: 1.2;
  }
  /* 颜色 */
  .solar .circle { border-color: var(--_solar); }
  path.solar { stroke: var(--_solar); }
  .flow-dot.solar { background-color: var(--_solar); }
  .grid .circle { border-color: var(--_grid-in); }
  .consumption { color: var(--_grid-in); }
  path.grid { stroke: var(--_grid-in); }
  .flow-dot.grid, .flow-dot.battery-from-grid { background-color: var(--_grid-in); }
  .return { color: var(--_grid-out); }
  path.return { stroke: var(--_grid-out); }
  .flow-dot.return { background-color: var(--_grid-out); }
  path.battery-from-grid { stroke: var(--_grid-in); }
  .battery .circle { border-color: var(--_batt-out); }
  path.battery-house { stroke: var(--_batt-out); }
  .flow-dot.battery-house { background-color: var(--_batt-out); }
  .battery-in { color: var(--_batt-in); }
  .battery-out { color: var(--_batt-out); }
  path.battery-solar { stroke: var(--_batt-in); }
  .flow-dot.battery-solar { background-color: var(--_batt-in); }
  .home .circle { border-width: 0; border-color: var(--primary-color); }
  .home .circle.border { border-width: 2px; }
  /* 流动小圆点（同原生） */
  .flow-dots { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }
  .flow-dot {
    position: absolute; top: 0; left: 0;
    width: var(--flow-dot-size); height: var(--flow-dot-size);
    margin: calc(var(--flow-dot-size) / -2) 0 0 calc(var(--flow-dot-size) / -2);
    border-radius: var(--ha-border-radius-circle, 50%);
    will-change: transform;
    display: none;
  }
  .flow-dot.active { display: block; }
  .sf-status {
    margin: 4px 12px 8px;
    padding: 6px 8px;
    border-radius: var(--ha-border-radius-sm, 4px);
    background: var(--error-color, #db4437);
    color: var(--text-primary-color, #fff);
    font-size: var(--ha-font-size-xs, 12px);
    line-height: 1.4;
    word-break: break-word;
  }
  .sf-status[hidden] { display: none; }
  /* 右上角实时刷新开关 */
  .rt {
    position: absolute; top: -6px; right: 4px;
    display: flex; align-items: center; gap: 4px;
    z-index: 2;
  }
  .rt-label { font-size: 11px; color: var(--secondary-text-color); }
  .rt ha-switch { --mdc-switch-size: 32px; transform: scale(0.8); transform-origin: right center; }
  /* 每个圆圈下方的统计小块（绝对定位，不影响行高） */
  .node-stats {
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    margin-top: 3px;
    padding: 2px 7px;
    border-radius: 7px;
    background: var(--card-background-color, #fff);
    box-shadow: 0 0 0 1px var(--divider-color, #e8e8e8);
    font-size: 9.5px;
    line-height: 12px;
    white-space: nowrap;
    text-align: center;
    color: var(--secondary-text-color);
    pointer-events: none;
    z-index: 1;
  }
  .node-stats .ns-line { font-variant-numeric: tabular-nums; }`;

const ICON = {
  solar: "mdi:solar-power",
  grid: "mdi:transmission-tower",
  home: "mdi:home",
  arrowLeft: "mdi:arrow-left",
  arrowRight: "mdi:arrow-right",
  arrowDown: "mdi:arrow-down",
  arrowUp: "mdi:arrow-up",
};

function batteryIcon(soc) {
  if (soc === null) return "mdi:battery-high";
  if (soc <= 5) return "mdi:battery-outline";
  const v = Math.min(100, Math.max(10, Math.round(soc / 10) * 10));
  return v >= 100 ? "mdi:battery" : `mdi:battery-${v}`;
}

class SiseliPowerFlowCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._built = false;
    this._els = {};
    this._sampled = new Map();
    this._animations = new Map();
    this._ro = null;
  }

  static getStubConfig() {
    return { title: "能量分配（实时功率）" };
  }

  setConfig(config) {
    if (!config) throw new Error("需要卡片配置");
    this._config = { title: "能量分配（实时功率）", ...config };
    try {
      this._build();
    } catch (err) {
      console.error("[siseli-power-flow] 构建失败", err);
      throw err;
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) return;
    // 兜底：任何异常都不能把整个 Lovelace 视图渲染带崩
    try {
      this._update();
      this._setStatus(null);
} catch (err) {
      // 不静默：卡片底部显示失败原因，否则用户只会看到「数字不动」
      this._setStatus(err && err.message ? err.message : String(err));
      if (!this._errLogged) {
        this._errLogged = true;
        console.error("[siseli-power-flow] 更新失败", err);
      }
    }
  }

  /** 在卡片底部显示/隐藏错误提示，避免「静默冻结」 */
  _setStatus(msg) {
    const el = this._els.status;
    if (!el) return;
    if (msg) {
      el.textContent = "数据更新失败：" + msg;
      el.hidden = false;
    } else if (!el.hidden) {
      el.hidden = true;
      el.textContent = "";
    }
  }

  getCardSize() {
    return 4;
  }

  disconnectedCallback() {
    this._ro?.disconnect();
    for (const a of this._animations.values()) a.cancel();
    this._animations.clear();
  }

  // -------------------------------------------------------------- 工具
  _num(id) {
    if (!id) return null;
    const st = this._hass?.states?.[id];
    if (!st) return null;
    const v = Number.parseFloat(st.state);
    return Number.isFinite(v) ? v : null;
  }

  _fmt(w) {
    if (w === null) return "—";
    const a = Math.abs(w);
    if (a >= 10000) return `${(w / 1000).toFixed(1)} kW`;
    if (a >= 1000) return `${(w / 1000).toFixed(2)} kW`;
    return `${Math.round(w)} W`;
  }

  _el(tag, cls) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
  }

  _icon(name, small) {
    const i = document.createElement("ha-icon");
    i.setAttribute("icon", name);
    if (small) i.className = "small";
    return i;
  }

  // -------------------------------------------------------------- 构建
  _build() {
    const root = this.shadowRoot;
    root.textContent = "";
    this._animations.clear();
    this._sampled.clear();

    const style = document.createElement("style");
    style.textContent = STYLES;
    root.appendChild(style);

    const card = document.createElement("ha-card");
    if (this._config.title) {
      // 属性与 property 都设，避免 ha-card 尚未升级时标题丢失
      card.setAttribute("header", this._config.title);
      card.header = this._config.title;
    }

    const content = this._el("div", "card-content");

    // --- 第一行：太阳能在上 ---
    const row1 = this._el("div", "row");
    row1.appendChild(this._el("div", "spacer"));
    const solarC = this._el("div", "circle-container solar");
    solarC.appendChild(this._label("太阳能"));
    const solarCircle = this._el("div", "circle");
    solarCircle.appendChild(this._icon(ICON.solar));
    const solarVal = this._el("span");
    solarCircle.appendChild(solarVal);
    solarC.appendChild(solarCircle);
    row1.appendChild(solarC);
    row1.appendChild(this._el("div", "spacer"));
    content.appendChild(row1);

    // --- 第二行：电网 / 我的家 ---
    const row2 = this._el("div", "row");
    const gridC = this._el("div", "circle-container grid");
    const gridCircle = this._el("div", "circle");
    gridCircle.appendChild(this._icon(ICON.grid));
    const gridReturn = this._el("span", "return");
    gridReturn.appendChild(this._icon(ICON.arrowLeft, true));
    const gridReturnVal = this._el("span");
    gridReturn.appendChild(gridReturnVal);
    gridCircle.appendChild(gridReturn);
    const gridCons = this._el("span", "consumption");
    gridCons.appendChild(this._icon(ICON.arrowRight, true));
    const gridConsVal = this._el("span");
    gridCons.appendChild(gridConsVal);
    gridCircle.appendChild(gridCons);
    gridC.appendChild(gridCircle);
    gridC.appendChild(this._label("电网"));
    row2.appendChild(gridC);

    const homeC = this._el("div", "circle-container home");
    const homeCircle = this._el("div", "circle border");
    homeCircle.appendChild(this._icon(ICON.home));
    const homeVal = this._el("span");
    homeCircle.appendChild(homeVal);
    homeC.appendChild(homeCircle);
    const homeLabel = this._label("我的家");
    homeC.appendChild(homeLabel);
    row2.appendChild(homeC);
    content.appendChild(row2);

    // --- 第三行：电池在下 ---
    const row3 = this._el("div", "row");
    row3.appendChild(this._el("div", "spacer"));
    const battC = this._el("div", "circle-container battery");
    const battCircle = this._el("div", "circle");
    const socWrap = this._el("div", "battery-soc");
    const battIcon = this._icon(ICON.solar);
    battIcon.setAttribute("icon", "mdi:battery-high");
    socWrap.appendChild(battIcon);
    const socVal = this._el("span");
    socWrap.appendChild(socVal);
    battCircle.appendChild(socWrap);
    const battIn = this._el("span", "battery-in");
    battIn.appendChild(this._icon(ICON.arrowDown, true));
    const battInVal = this._el("span");
    battIn.appendChild(battInVal);
    battCircle.appendChild(battIn);
    const battOut = this._el("span", "battery-out");
    battOut.appendChild(this._icon(ICON.arrowUp, true));
    const battOutVal = this._el("span");
    battOut.appendChild(battOutVal);
    battCircle.appendChild(battOut);
    battC.appendChild(battCircle);
    battC.appendChild(this._label("电池"));
    row3.appendChild(battC);
    row3.appendChild(this._el("div", "spacer"));
    content.appendChild(row3);

    // --- 连线层 ---
    const lines = this._el("div", "lines high");
    const flow = this._el("div", "flow");
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("preserveAspectRatio", "xMidYMid slice");
    const mk = (id, cls, d) => {
      const p = document.createElementNS(SVGNS, "path");
      p.setAttribute("id", id);
      p.setAttribute("class", cls);
      p.setAttribute("d", d);
      p.setAttribute("vector-effect", "non-scaling-stroke");
      svg.appendChild(p);
      return p;
    };
    mk("return", "return", PATHS.return);
    mk("solar", "solar", PATHS.solar);
    mk("battery-house", "battery-house", PATHS.batteryHouse);
    mk("battery-grid", "battery-from-grid", PATHS.batteryGrid);
    mk("battery-solar", "battery-solar", PATHS.batterySolar);
    mk("grid", "grid", PATHS.grid);
    flow.appendChild(svg);

    const dots = this._el("div", "flow-dots");
    flow.appendChild(dots);
    lines.appendChild(flow);
    content.appendChild(lines);

    // --- 右上角：实时刷新开关（同步侧边栏那个 switch）---
    const rt = this._el("div", "rt");
    const rtLabel = this._el("span", "rt-label");
    rtLabel.textContent = "实时刷新";
    const rtSwitch = document.createElement("ha-switch");
    rtSwitch.addEventListener("change", () => {
      const id = this._config.realtime_switch;
      if (!id || !this._hass) return;
      this._hass.callService("switch", rtSwitch.checked ? "turn_on" : "turn_off", {
        entity_id: id,
      });
    });
    rt.appendChild(rtLabel);
    rt.appendChild(rtSwitch);
    content.appendChild(rt);

    card.appendChild(content);

    // --- 每个圆圈下方挂一块统计（绝对定位，不改变行高，因此不会打乱连线层）---
    const statRefs = {};
    const containers = { solar: solarC, grid: gridC, home: homeC, battery: battC };
    for (const r of STAT_ROWS) {
      const box = this._el("div", "node-stats");
      const l1 = this._el("div", "ns-line");
      const l2 = this._el("div", "ns-line");
      box.appendChild(l1);
      box.appendChild(l2);
      containers[r.key].appendChild(box);
      statRefs[r.key] = { today: l1, month: l2 };
    }

    // 更新失败时的可见提示（默认隐藏）
    const status = this._el("div", "sf-status");
    status.hidden = true;
    card.appendChild(status);

    root.appendChild(card);

    this._els = {
      solarVal,
      gridReturn,
      gridReturnVal,
      gridConsVal,
      homeVal,
      homeLabel,
      socVal,
      battIcon,
      battInVal,
      battOutVal,
      lines,
      svg,
      dots,
      status,
      rtSwitch,
      statRefs,
    };
    this._built = true;


    this._ro = new ResizeObserver(() => {
      // 首次渲染时容器宽度可能还是 0，等布局稳定后用它再跑一次
      if (this._lastFlows) {
        this._dotsKey = null;
        this._syncDots(this._lastFlows);
      }
    });
    this._ro.observe(dots);

    this._update();
  }

  _label(text) {
    const s = this._el("span", "label");
    s.textContent = text;
    return s;
  }

  // -------------------------------------------------------------- 更新
  _update() {
    if (!this._hass || !this._built) return;
    const c = this._config;

    const pv = this._num(c.pv) ?? 0;
    const gIn = this._num(c.grid_import) ?? 0;
    const gOut = this._num(c.grid_export) ?? 0;
    const ch = this._num(c.battery_charge) ?? 0;
    const dis = this._num(c.battery_discharge) ?? 0;
    const load = this._num(c.load) ?? 0;
    const soc = this._num(c.soc);

    const e = this._els;
    e.solarVal.textContent = this._fmt(pv);
    e.gridReturnVal.textContent = this._fmt(gOut);
    e.gridConsVal.textContent = this._fmt(gIn);
    e.homeVal.textContent = this._fmt(load);
    e.battInVal.textContent = this._fmt(ch);
    e.battOutVal.textContent = this._fmt(dis);
    e.socVal.textContent = soc === null ? "" : `${Math.round(soc)}%`;
    e.battIcon.setAttribute("icon", batteryIcon(soc));

    // 是否显示箭头（无对应实体时隐藏）
    e.gridReturn.style.display = c.grid_export ? "" : "none";

    // 同步右上角的实时刷新开关
    if (e.rtSwitch && c.realtime_switch) {
      const st = this._hass.states[c.realtime_switch];
      const on = st?.state === "on";
      if (e.rtSwitch.checked !== on) e.rtSwitch.checked = on;
    }

    this._renderStats();
    this._syncDots({ pv, gIn, gOut, ch, dis, load });
  }

  // -------------------------------------------------------------- 统计
  _numOrNull(id) {
    if (!id) return null;
    const st = this._hass?.states?.[id];
    if (!st) return null;
    const v = Number.parseFloat(st.state);
    return Number.isFinite(v) ? v : null;
  }

  _kwh(v, digits = 2) {
    return v === null || v === undefined ? "—" : v.toFixed(digits);
  }

  _renderStats() {
    const refs = this._els.statRefs;
    const s = this._config.stats;
    if (!refs || !s) return;

    const v = (id) => this._numOrNull(id);
    const k = (id) => this._kwh(v(id), 1);

    // 太阳能
    refs.solar.today.textContent = `今 ${k(s.solar_today)}`;
    refs.solar.month.textContent = `月 ${k(s.solar_month)}`;

    // 电网：购电 / 售电
    refs.grid.today.textContent = `今 购${k(s.grid_in_today)} 售${k(s.grid_out_today)}`;
    refs.grid.month.textContent = `月 购${k(s.grid_in_month)} 售${k(s.grid_out_month)}`;

    // 电池：充电 / 放电
    refs.battery.today.textContent = `今 充${k(s.batt_in_today)} 放${k(s.batt_out_today)}`;
    refs.battery.month.textContent = `月 充${k(s.batt_in_month)} 放${k(s.batt_out_month)}`;

    // 我的家
    refs.home.today.textContent = `今 ${k(s.home_today)}`;
    refs.home.month.textContent = `月 ${k(s.home_month)}`;
  }


  // -------------------------------------------------------------- 流动点
  _syncDots(flows) {
    if (!flows) return;
    this._lastFlows = flows;
    const { pv, gIn, gOut, ch, dis, load } = flows;
    const total = pv + gIn + gOut + ch + dis + load || 1;
    const dur = (v) => Math.max(1, 6 - (v / total) * 5);

    const desired = [];
    const has = (v) => v > 0.5;

    // 太阳能 → 我的家
    if (has(pv)) desired.push({ path: "solar", cls: "solar", duration: dur(pv) });
    // 电网 → 我的家
    if (has(gIn)) desired.push({ path: "grid", cls: "grid", duration: dur(gIn) });
    // 我的家 → 电网（反方向）
    if (has(gOut)) desired.push({ path: "return", cls: "return", duration: dur(gOut), reverse: true });
    // 太阳能 → 电池（充电）
    if (has(ch)) desired.push({ path: "battery-solar", cls: "battery-solar", duration: dur(Math.min(ch, pv || ch)) });
    // 电网 → 电池（充电量超过光伏时才走这条路）
    if (has(ch) && ch > pv) desired.push({ path: "battery-grid", cls: "battery-from-grid", duration: dur(ch - pv), reverse: true });
    // 电池 → 我的家（放电）
    if (has(dis)) desired.push({ path: "battery-house", cls: "battery-house", duration: dur(dis) });

    this._renderDots(desired);
  }

  _renderDots(desired) {
    const { dots, svg } = this._els;
    if (!dots || !svg || !dots.offsetWidth) return;

    const key = desired.map((d) => `${d.path}:${d.cls}:${d.duration.toFixed(2)}:${!!d.reverse}`).join("|");
    if (this._dotsKey === key) return;
    this._dotsKey = key;

    for (const a of this._animations.values()) a.cancel();
    this._animations.clear();
    dots.textContent = "";

    for (const d of desired) {
      const dot = this._el("div", `flow-dot ${d.cls} active`);
      dots.appendChild(dot);
      this._animateDot(dot, svg, d);
    }
  }

  _animateDot(dot, svg, spec) {
    const path = svg.querySelector(`#${CSS.escape(spec.path)}`);
    const ctm = path?.getCTM();
    const scale = ctm ? Math.hypot(ctm.a, ctm.b) : 0;
    if (!path || !ctm || !scale) return;

    const layer = this._els.dots;
    layer.style.setProperty("--flow-dot-size", `${2 * scale + DOT_STROKE_PX}px`);

    const geom = [path.getAttribute("d"), ctm.a, ctm.b, ctm.c, ctm.d, ctm.e, ctm.f].join();
    let points = this._sampled.get(geom);
    if (!points) {
      const len = path.getTotalLength();
      const steps = Math.max(1, Math.ceil((len * scale) / STEP_PX));
      points = [];
      for (let i = 0; i <= steps; i++) {
        const pt = path.getPointAtLength((len * i) / steps).matrixTransform(ctm);
        points.push({ transform: `translate(${pt.x}px, ${pt.y}px)` });
      }
      this._sampled.set(geom, points);
    }
    const frames = spec.reverse ? [...points].reverse() : points;
    const anim = dot.animate(frames, {
      duration: spec.duration * 1000,
      iterations: Infinity,
    });
    this._animations.set(dot, anim);
  }
}

if (!customElements.get("siseli-power-flow")) {
  customElements.define("siseli-power-flow", SiseliPowerFlowCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "siseli-power-flow")) {
  window.customCards.push({
    type: "siseli-power-flow",
    name: "逆控机能量分配（实时功率）",
    description: "1:1 复刻原生能量分配版式，数值为实时功率 W",
  });
}
