/*
 * Venus Surplus card for Home Assistant.
 *
 * Shows the battery the controller runs: state of charge as a gauge, charge
 * and discharge power, the energy in the pack, what the controller is doing
 * right now, and a chart of the last hours.
 *
 * The card is pointed at the controller's "Target mode" sensor. Its
 * attributes name the Venus entities (SoC, AC power, MPPT, capacity) picked
 * in the setup, so nothing has to be entered twice.
 *
 * Served by the integration at /venus_surplus_files/venus-surplus-card.js.
 */

const VSC_CARD_VERSION = "0.1.0";

const VSC_LABELS = {
  soc: { de: "Ladezustand", en: "State of charge", fr: "État de charge", it: "Stato di carica" },
  charge: { de: "Ladeleistung", en: "Charge power", fr: "Puissance de charge", it: "Potenza di carica" },
  discharge: { de: "Entladeleistung", en: "Discharge power", fr: "Puissance de décharge", it: "Potenza di scarica" },
  energy: { de: "Energie im Speicher", en: "Energy in the battery", fr: "Énergie dans la batterie", it: "Energia nella batteria" },
  mode_charge: { de: "Laden", en: "Charging", fr: "Charge", it: "Carica" },
  mode_discharge: { de: "Entladen", en: "Discharging", fr: "Décharge", it: "Scarica" },
  mode_idle: { de: "Standby", en: "Standby", fr: "Veille", it: "Standby" },
  subtitle: { de: "Marstek Venus – Steuerung", en: "Marstek Venus – control", fr: "Marstek Venus – pilotage", it: "Marstek Venus – controllo" },
  first: { de: "Erste Batterie", en: "First battery", fr: "Première batterie", it: "Prima batteria" },
  first_short: { de: "Batterie", en: "Battery", fr: "Batterie", it: "Batteria" },
  setpoint: { de: "Soll", en: "Setpoint", fr: "Consigne", it: "Setpoint" },
  pv: { de: "Eigene PV", en: "Own PV", fr: "PV propre", it: "FV proprio" },
  history: { de: "Verlauf", en: "History", fr: "Historique", it: "Cronologia" },
  dry_run: { de: "Probelauf", en: "Dry run", fr: "Essai à blanc", it: "Prova a vuoto" },
  live: { de: "Live", en: "Live", fr: "En direct", it: "Live" },
  stale: { de: "Keine aktuelle Entscheidung", en: "No recent decision", fr: "Pas de décision récente", it: "Nessuna decisione recente" },
  no_entity: {
    de: "Wähle den Sensor «Zielmodus» von Venus Surplus Control.",
    en: "Pick the “Target mode” sensor of Venus Surplus Control.",
    fr: "Choisissez le capteur « Mode cible » de Venus Surplus Control.",
    it: "Scegli il sensore «Modalità obiettivo» di Venus Surplus Control.",
  },
  not_found: { de: "Entität nicht gefunden", en: "Entity not found", fr: "Entité introuvable", it: "Entità non trovata" },
  no_history: { de: "Noch kein Verlauf", en: "No history yet", fr: "Pas encore d'historique", it: "Ancora nessuna cronologia" },
};

const VSC_EDITOR_LABELS = {
  entity: { de: "Zielmodus-Sensor", en: "Target mode sensor", fr: "Capteur du mode cible", it: "Sensore della modalità obiettivo" },
  title: { de: "Titel (optional)", en: "Title (optional)", fr: "Titre (facultatif)", it: "Titolo (facoltativo)" },
  first_battery_name: { de: "Name der ersten Batterie (optional)", en: "Name of the first battery (optional)", fr: "Nom de la première batterie (facultatif)", it: "Nome della prima batteria (facoltativo)" },
  hours: { de: "Verlauf: Stunden", en: "History: hours", fr: "Historique : heures", it: "Cronologia: ore" },
  show_illustration: { de: "Haus-Grafik anzeigen", en: "Show the house graphic", fr: "Afficher le dessin de la maison", it: "Mostra il disegno della casa" },
  show_chart: { de: "Verlauf anzeigen", en: "Show the history", fr: "Afficher l'historique", it: "Mostra la cronologia" },
};

const VSC_HISTORY_REFRESH_MS = 120000;
const VSC_PV_MIN_W = 5; // below this an MPPT input counts as dark
const VSC_GAUGE_R = 80;
const VSC_GAUGE_LEN = 2 * Math.PI * VSC_GAUGE_R * 0.75;

function vscLang(hass) {
  return ((hass && hass.language) || "en").split("-")[0];
}
function vscL(hass, key, table) {
  const t = table || VSC_LABELS;
  const row = Object.prototype.hasOwnProperty.call(t, key) ? t[key] : null;
  if (!row) return key;
  const l = vscLang(hass);
  return Object.prototype.hasOwnProperty.call(row, l) ? row[l] : row.en;
}
function vscEsc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function vscLocale(hass) {
  return (hass && hass.locale && hass.locale.language) || (hass && hass.language) || "en";
}
function vscNum(hass, value, digits) {
  try {
    return Number(value).toLocaleString(vscLocale(hass), { minimumFractionDigits: digits, maximumFractionDigits: digits });
  } catch (e) {
    return Number(value).toFixed(digits);
  }
}
/* A numeric state in the unit the card works with; null when not a number. */
function vscValue(hass, entityId, kind) {
  if (!entityId || typeof entityId !== "string") return null;
  const st = hass.states[entityId];
  if (!st) return null;
  return vscScale(st.state, st.attributes && st.attributes.unit_of_measurement, kind);
}
function vscScale(raw, unit, kind) {
  const v = Number.parseFloat(raw);
  if (!Number.isFinite(v)) return null;
  const u = String(unit || "").trim();
  if (kind === "power") return u === "kW" ? v * 1000 : u === "MW" ? v * 1e6 : v; // -> W
  if (kind === "energy") return u === "Wh" ? v / 1000 : u === "MWh" ? v * 1000 : v; // -> kWh
  return v;
}
function vscNiceMax(value) {
  const steps = [500, 1000, 1500, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 15000, 20000];
  for (const s of steps) if (value <= s) return s;
  return Math.ceil(value / 10000) * 10000;
}

class VenusSurplusCard extends HTMLElement {
  setConfig(config) {
    this._config = {
      hours: 6,
      show_illustration: true,
      show_chart: true,
      ...config,
    };
    const h = Number(this._config.hours);
    this._config.hours = Number.isFinite(h) ? Math.min(48, Math.max(1, h)) : 6;
    this._signature = null;
    this._history = null;
    this._historyKey = null;
    this._historyAt = 0;
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  static getConfigElement() {
    return document.createElement("venus-surplus-card-editor");
  }

  static getStubConfig(hass) {
    const id = Object.keys(hass.states).find(
      (e) => e.startsWith("sensor.") && hass.states[e].attributes && hass.states[e].attributes.soc_entity && "ac_power_entity" in hass.states[e].attributes
    );
    return { entity: id || "" };
  }

  getCardSize() {
    return this._config && this._config.show_chart ? 8 : 5;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  connectedCallback() {
    if (!this._resize && typeof ResizeObserver !== "undefined") {
      this._resize = new ResizeObserver(() => this._drawChart());
    }
    if (this._resize) this._resize.observe(this);
    this._timer = window.setInterval(() => this._loadHistory(), VSC_HISTORY_REFRESH_MS);
  }

  disconnectedCallback() {
    if (this._resize) this._resize.disconnect();
    window.clearInterval(this._timer);
  }

  /* Everything the card reads, as numbers. */
  _read() {
    const hass = this._hass;
    const st = hass.states[this._config.entity];
    if (!st) return null;
    const a = st.attributes || {};
    if (!a.soc_entity || !("ac_power_entity" in a)) return { st, wrong: true };
    const sign = a.ac_power_inverted ? -1 : 1;
    const acRaw = vscValue(hass, a.ac_power_entity, "power");
    const ac = acRaw === null ? null : acRaw * sign; // positive = delivering into the house
    const soc = vscValue(hass, a.soc_entity, "plain");
    let capacity = vscValue(hass, a.capacity_entity, "energy");
    if (capacity === null || capacity <= 0) capacity = Number(a.capacity_fallback_kwh) || null;
    const pvIds = Array.isArray(a.pv_entities) ? a.pv_entities.filter((e) => typeof e === "string") : [];
    let pv = null;
    const pvList = [];
    pvIds.forEach((id, i) => {
      const v = vscValue(hass, id, "power");
      if (v !== null) pv = (pv || 0) + v;
      pvList.push({ n: i + 1, w: v });
    });
    // The first battery, if the setup has one: power positive = discharging.
    let primary = null;
    if (typeof a.primary_power_entity === "string" && a.primary_power_entity) {
      const pRaw = vscValue(hass, a.primary_power_entity, "power");
      const pSoc = vscValue(hass, a.primary_soc_entity, "plain");
      const pw = pRaw === null ? null : pRaw * (a.primary_power_inverted ? -1 : 1);
      primary = {
        soc: pSoc === null ? null : Math.min(100, Math.max(0, pSoc)),
        power: pw,
        mode: pw === null || Math.abs(pw) < 50 ? "idle" : pw > 0 ? "discharge" : "charge",
      };
    }
    const decided = a.decided_at ? new Date(a.decided_at) : null;
    return {
      primary,
      st,
      a,
      soc: soc === null ? null : Math.min(100, Math.max(0, soc)),
      charge: ac === null ? null : Math.max(0, -ac),
      discharge: ac === null ? null : Math.max(0, ac),
      energy: soc === null || capacity === null ? null : (capacity * Math.min(100, Math.max(0, soc))) / 100,
      pv,
      hasPv: pvIds.length > 0,
      pvList,
      decided: decided && !Number.isNaN(decided.getTime()) ? decided : null,
      sunUp: hass.states["sun.sun"] ? hass.states["sun.sun"].state === "above_horizon" : true,
    };
  }

  _update() {
    if (!this._config || !this._hass) return;
    const hass = this._hass;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `<style>${VSC_STYLE}</style><ha-card><div class="top"></div><div class="chart"></div></ha-card>`;
      this._top = this._root.querySelector(".top");
      this._chart = this._root.querySelector(".chart");
    }
    if (!this._config.entity) {
      this._signature = null;
      this._top.innerHTML = `<div class="note">${vscEsc(vscL(hass, "no_entity"))}</div>`;
      this._chart.innerHTML = "";
      return;
    }
    const d = this._read();
    if (!d) {
      this._signature = null;
      this._top.innerHTML = `<div class="note">${vscEsc(vscL(hass, "not_found"))}: ${vscEsc(this._config.entity)}</div>`;
      this._chart.innerHTML = "";
      return;
    }
    if (d.wrong) {
      this._signature = null;
      this._top.innerHTML = `<div class="note">${vscEsc(vscL(hass, "no_entity"))}</div>`;
      this._chart.innerHTML = "";
      return;
    }
    const signature = [
      d.st.state, d.a.decided_at, d.a.dry_run, d.a.reason, d.a.last_command, d.a.last_command_power, d.primary && d.primary.soc, d.primary && d.primary.mode, d.soc, d.charge, d.discharge, d.energy, d.pv, d.pvList.map((x) => x.w).join(","), d.sunUp, vscLang(hass),
      this._config.title, this._config.show_illustration, this._config.first_battery_name,
    ].join("|");
    if (signature !== this._signature) {
      this._signature = signature;
      this._top.innerHTML = this._renderTop(d);
    }
    this._chart.style.display = this._config.show_chart ? "" : "none";
    if (this._config.show_chart) this._loadHistory();
  }

  /* The controller's reason in the user's language: the state of the reason
     sensor on the same device, as Home Assistant words it. */
  _reasonText() {
    const hass = this._hass;
    const reg = hass.entities && hass.entities[this._config.entity];
    if (!reg || !reg.device_id || typeof hass.formatEntityState !== "function") return "";
    const id = Object.keys(hass.entities).find(
      (e) => hass.entities[e].device_id === reg.device_id && hass.entities[e].translation_key === "reason" && e.startsWith("sensor.")
    );
    const st = id && hass.states[id];
    if (!st || ["unknown", "unavailable"].includes(st.state)) return "";
    return hass.formatEntityState(st);
  }

  _renderTop(d) {
    const hass = this._hass;
    const mode = ["charge", "discharge"].includes(d.st.state) ? d.st.state : "idle";
    const stateText = typeof hass.formatEntityState === "function" ? hass.formatEntityState(d.st) : d.st.state;
    const reason = this._reasonText() || stateText;
    // The power the controller asked for. In a dry run nothing is written,
    // so the measured power stays at zero and this is the only number to see.
    const cmdW = Number(d.a.last_command_power);
    const setpoint = mode !== "idle" && d.a.last_command === mode && Number.isFinite(cmdW) && cmdW > 0 ? ` · ${vscL(hass, "setpoint")} ${vscNum(hass, cmdW, 0)} W` : "";
    const chip = (m) => `<span class="chip ${m}${m === mode ? " on" : ""}"><span class="cdot"></span>${vscEsc(vscL(hass, "mode_" + m) + (m === mode ? setpoint : ""))}</span>`;
    const reg = hass.entities && hass.entities[this._config.entity];
    const device = reg && reg.device_id && hass.devices ? hass.devices[reg.device_id] : null;
    const title = this._config.title || (device && (device.name_by_user || device.name)) || "Venus";
    const fresh = d.decided && Date.now() - d.decided.getTime() < 5 * 60000;
    const time = d.decided ? d.decided.toLocaleTimeString(vscLocale(hass), { hour: "2-digit", minute: "2-digit" }) : "";
    const socKnown = d.soc !== null;
    const socLen = socKnown ? (VSC_GAUGE_LEN * d.soc) / 100 : 0;
    const socClass = !socKnown ? "none" : d.soc <= 15 ? "low" : d.soc <= 30 ? "mid" : "ok";
    const bars = socKnown ? Math.max(0, Math.min(4, Math.round(d.soc / 25))) : 0;
    const watt = (v) => (v === null ? "–" : vscNum(hass, Math.round(v), 0));
    const tile = (cls, icon, value, unit, label, active) => `
      <div class="tile ${cls}${active ? " active" : ""}">
        <div class="badge"><ha-icon icon="${icon}"></ha-icon></div>
        <div><div class="value">${value} <span class="unit">${unit}</span></div><div class="label">${vscEsc(label)}</div></div>
      </div>`;
    const tiles = [
      tile("c", "mdi:arrow-up", (d.charge ? "+ " : "") + watt(d.charge), "W", vscL(hass, "charge"), d.charge > 0),
      tile("d", "mdi:arrow-down", watt(d.discharge), "W", vscL(hass, "discharge"), d.discharge > 0),
      tile("e", "mdi:battery-charging", d.energy === null ? "–" : vscNum(hass, d.energy, 1), "kWh", vscL(hass, "energy"), false),
    ];
    if (d.primary) {
      const pp = d.primary.power;
      const sub = `${this._config.first_battery_name || vscL(hass, "first")}${pp === null || d.primary.mode === "idle" ? "" : ` · ${vscL(hass, "mode_" + d.primary.mode)} ${vscNum(hass, Math.round(Math.abs(pp)), 0)} W`}`;
      tiles.push(tile(`f m-${d.primary.mode}`, "mdi:home-battery", d.primary.soc === null ? "–" : vscNum(hass, d.primary.soc, 0), "%", sub, d.primary.mode !== "idle"));
    }
    // The Venus' own PV shows up by itself once an MPPT input delivers.
    const mpptOn = d.pvList.filter((x) => x.w !== null && x.w >= VSC_PV_MIN_W);
    if (mpptOn.length) tiles.push(tile("p", "mdi:solar-power", watt(d.pv), "W", vscL(hass, "pv"), true));
    const mpptTop = Math.max(1, ...mpptOn.map((x) => x.w));
    const mppt = mpptOn.length
      ? `<div class="mppt">${mpptOn
          .map(
            (x) => `<div class="mp"><div class="mp-h"><span>MPPT ${Number(x.n)}</span><b>${watt(x.w)} W</b></div>
              <div class="mp-bar"><i style="width:${Math.max(4, Math.round((100 * x.w) / mpptTop))}%"></i></div></div>`
          )
          .join("")}</div>`
      : "";

    return `
      <div class="head">
        <div class="head-l">
          <ha-icon class="head-icon" icon="mdi:battery-charging"></ha-icon>
          <div>
            <div class="title">${vscEsc(title)}</div>
            <div class="sub">${vscEsc(vscL(hass, "subtitle"))}${d.a.dry_run ? ` <span class="dry">${vscEsc(vscL(hass, "dry_run"))}</span>` : ""}</div>
          </div>
        </div>
        <div class="live ${fresh ? "on" : "off"}" title="${vscEsc(vscL(hass, fresh ? "live" : "stale"))}">
          <span class="dot"></span>${fresh ? vscEsc(vscL(hass, "live")) + " · " : ""}${vscEsc(time)}
        </div>
      </div>
      <div class="body${this._config.show_illustration ? "" : " no-art"}">
        ${this._config.show_illustration ? `<div class="art">${this._renderArt(d, mode)}</div>` : ""}
        <div class="gauge">
          <svg viewBox="0 0 200 180" role="img" aria-label="${vscEsc(vscL(hass, "soc"))}">
            <path class="track" d="M 43.43 156.57 A 80 80 0 1 1 156.57 156.57" />
            <path class="arc ${socClass}" d="M 43.43 156.57 A 80 80 0 1 1 156.57 156.57" stroke-dasharray="${socLen.toFixed(1)} ${VSC_GAUGE_LEN.toFixed(1)}" />
            <text class="pct" x="100" y="104" text-anchor="middle">${socKnown ? vscNum(hass, d.soc, 0) : "–"}<tspan class="pct-unit" dx="4">%</tspan></text>
            <text class="pct-label" x="100" y="128" text-anchor="middle">${vscEsc(vscL(hass, "soc"))}</text>
            <g class="batt ${socClass}" transform="translate(79 142)">
              <rect class="shell" x="0" y="0" width="38" height="18" rx="4" /><rect class="tip" x="39.5" y="5" width="3" height="8" rx="1.2" />
              ${[0, 1, 2, 3].map((i) => (i < bars ? `<rect class="bar" x="${4 + i * 8}" y="4" width="6" height="10" rx="1" />` : "")).join("")}
            </g>
          </svg>
        </div>
        <div class="tiles">${tiles.join("")}</div>
      </div>
      <div class="status">
        <span class="reason mode-${mode}"><span class="cdot"></span>${vscEsc(reason)}</span>
        <span class="chips">${chip("charge")}${chip("discharge")}${chip("idle")}</span>
      </div>
      ${mppt}`;
  }

  /* PV panel, the batteries and the house, with the flow between them. A
     first battery of the setup stands next to the Venus, each with its SoC. */
  _renderArt(d, mode) {
    const hass = this._hass;
    const two = !!d.primary;
    const firstName = String(this._config.first_battery_name || vscL(hass, "first_short"));
    const shift = two ? 40 : 0;
    const bars = (soc) => (soc === null ? 0 : Math.max(0, Math.min(4, Math.round(soc / 25))));
    const pct = (soc) => (soc === null ? "–" : `${vscNum(hass, soc, 0)} %`);
    const box = (x, cls, soc, name) => `
        <g class="unit ${cls}">
          <rect class="box" x="${x}" y="50" width="34" height="62" rx="6" />
          <rect class="box-cap" x="${x + 11}" y="46" width="12" height="5" rx="1.5" />
          <rect class="box-inner" x="${x + 6}" y="57" width="22" height="48" rx="3" />
          ${[0, 1, 2, 3].map((i) => (i < bars(soc) ? `<rect class="lvl" x="${x + 10}" y="${92 - i * 10}" width="14" height="7" rx="1.5" />` : "")).join("")}
          ${two ? `<text class="cap-soc" x="${x + 17}" y="129" text-anchor="middle">${vscEsc(pct(soc))}</text><text class="cap-name" x="${x + 17}" y="141" text-anchor="middle">${vscEsc(name)}</text>` : ""}
        </g>`;
    // The arrows follow whichever battery is working.
    const modes = [mode, two ? d.primary.mode : "idle"];
    const flowIn = modes.includes("charge") ? " on-charge" : "";
    const flowOut = modes.includes("discharge") ? " on-discharge" : "";
    const rays = [0, 45, 90, 135, 180, 225, 270, 315].map((a) => `<line x1="52" y1="6" x2="52" y2="1.5" transform="rotate(${a} 52 20)" />`).join("");
    return `
      <svg viewBox="0 0 ${260 + shift} ${two ? 146 : 130}" aria-hidden="true">
        <path class="ground" d="M2 112 Q${130 + shift / 2} 100 ${258 + shift} 112 L${258 + shift} 120 L2 120 Z" />
        ${d.sunUp ? `<g class="sun"><circle cx="52" cy="20" r="9" />${rays}</g>` : `<path class="moon" d="M54 9a11 11 0 1 0 8 19a9.5 9.5 0 0 1-8-19z" />`}
        <path class="post" d="M30 84 V112 M62 96 V112" />
        <path class="panel" d="M8 46 L58 40 L84 96 L30 104 Z" />
        <path class="panel-lines" d="M25 44 L49 101 M42 42 L67 98.5 M15.3 65.3 L66.7 58.7 M22.7 84.7 L75.3 77.3" />
        <path class="flow${flowIn}" d="M88 76 H108" /><path class="tip${flowIn}" d="M104 70 L111 76 L104 82" />
        ${two ? box(114, "mode-" + d.primary.mode, d.primary.soc, firstName.length > 9 ? firstName.slice(0, 8) + "…" : firstName) : ""}
        ${box(114 + shift, "mode-" + mode, d.soc, "Venus")}
        ${d.pv !== null && d.pv >= VSC_PV_MIN_W ? `<path class="panel own" d="M${117 + shift} 27 L${145 + shift} 23 L${147 + shift} 34 L${115 + shift} 38 Z" /><path class="pv-flow" d="M${131 + shift} 37 V45" />` : ""}
        <g transform="translate(${shift} 0)">
          <path class="flow${flowOut}" d="M152 76 H172" /><path class="tip${flowOut}" d="M168 70 L175 76 L168 82" />
          <path class="wall" d="M186 70 L186 112 L246 112 L246 70 Z" />
          <rect class="chimney" x="232" y="44" width="8" height="18" />
          <path class="roof" d="M178 72 L216 42 L254 72 Z" />
          <rect class="window" x="194" y="80" width="15" height="15" rx="1.5" /><path class="window-bars" d="M201.5 80 V95 M194 87.5 H209" />
          <rect class="window" x="223" y="80" width="15" height="15" rx="1.5" /><path class="window-bars" d="M230.5 80 V95 M223 87.5 H238" />
        </g>
      </svg>`;
  }

  /* ------------------------------------------------------------ history */

  _loadHistory() {
    const hass = this._hass;
    if (!hass || !this._config || !this._config.show_chart || !this._root) return;
    const st = hass.states[this._config.entity];
    const a = (st && st.attributes) || {};
    const ids = [a.ac_power_entity, a.soc_entity].filter((e) => typeof e === "string" && e);
    const pvIds = (Array.isArray(a.pv_entities) ? a.pv_entities : []).filter((e) => typeof e === "string" && e);
    if (ids.length < 2) return;
    const key = `${ids.concat(pvIds).join(",")}|${this._config.hours}`;
    const changed = key !== this._historyKey;
    const due = Date.now() - this._historyAt >= VSC_HISTORY_REFRESH_MS - 1000;
    if (this._loading || (!changed && !due)) return;
    if (changed) this._history = null;
    this._loading = true;
    this._historyKey = key;
    this._historyAt = Date.now();
    const end = new Date();
    const start = new Date(end.getTime() - this._config.hours * 3600000);
    hass
      .callWS({
        type: "history/history_during_period",
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        entity_ids: ids.concat(pvIds),
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      })
      .then((res) => {
        const unit = (id) => (hass.states[id] && hass.states[id].attributes && hass.states[id].attributes.unit_of_measurement) || "";
        const series = (id, kind) =>
          (Array.isArray(res && res[id]) ? res[id] : [])
            .map((p) => ({ t: Number(p.lu) * 1000, v: vscScale(p.s, unit(id), kind) }))
            .filter((p) => Number.isFinite(p.t) && p.v !== null);
        const sign = a.ac_power_inverted ? -1 : 1;
        this._history = {
          start: start.getTime(),
          end: end.getTime(),
          ac: series(ids[0], "power").map((p) => ({ t: p.t, v: p.v * sign })),
          soc: series(ids[1], "plain"),
          pv: pvIds.map((id) => series(id, "power")),
        };
      })
      .catch(() => {
        this._history = { start: start.getTime(), end: end.getTime(), ac: [], soc: [], pv: [] };
      })
      .finally(() => {
        this._loading = false;
        this._drawChart();
      });
  }

  /* Time-weighted mean per bucket of a step series; null where nothing is known. */
  _buckets(points, start, end, n) {
    const out = new Array(n).fill(null);
    if (!points.length) return out;
    const width = (end - start) / n;
    let i = 0;
    let current = null;
    for (let b = 0; b < n; b++) {
      const b0 = start + b * width;
      const b1 = b0 + width;
      let sum = 0;
      let known = 0;
      let cursor = b0;
      while (i < points.length && points[i].t <= b0) current = points[i++].v;
      let j = i;
      while (j < points.length && points[j].t < b1) {
        if (current !== null) {
          sum += current * (points[j].t - cursor);
          known += points[j].t - cursor;
        }
        cursor = points[j].t;
        current = points[j].v;
        j++;
      }
      i = j;
      if (current !== null) {
        sum += current * (b1 - cursor);
        known += b1 - cursor;
      }
      if (known > 0) out[b] = sum / known;
    }
    return out;
  }

  _drawChart() {
    if (!this._chart || !this._config || !this._config.show_chart || !this._hass) return;
    const hass = this._hass;
    const h = this._history;
    const head = (pvOn) => `<div class="chart-head"><div class="chart-title"><ha-icon icon="mdi:chart-line"></ha-icon>${vscEsc(vscL(hass, "history"))}</div>
      <div class="legend"><span class="k c"></span>${vscEsc(vscL(hass, "charge"))}<span class="k d"></span>${vscEsc(vscL(hass, "discharge"))}${pvOn ? `<span class="k p"></span>${vscEsc(vscL(hass, "pv"))}` : ""}<span class="k s"></span>${vscEsc(vscL(hass, "soc"))}</div></div>`;
    if (!h) {
      this._chart.innerHTML = head(false);
      return;
    }
    if (!h.ac.length && !h.soc.length) {
      this._chart.innerHTML = `${head(false)}<div class="note">${vscEsc(vscL(hass, "no_history"))}</div>`;
      return;
    }
    const W = Math.max(280, Math.round(this._chart.clientWidth || 600));
    const H = 190;
    const m = { l: 44, r: 40, t: 8, b: 22 };
    const pw = W - m.l - m.r;
    const ph = H - m.t - m.b;
    const n = Math.max(30, Math.min(240, Math.floor(pw / 3)));
    const ac = this._buckets(h.ac, h.start, h.end, n);
    const soc = this._buckets(h.soc, h.start, h.end, n);
    const charge = ac.map((v) => (v === null ? null : Math.max(0, -v)));
    const discharge = ac.map((v) => (v === null ? null : Math.max(0, v)));
    const pvB = (h.pv || []).map((pts) => this._buckets(pts, h.start, h.end, n));
    const pvSum = soc.map((_, i) => {
      let sum = null;
      for (const b of pvB) if (b[i] !== null) sum = (sum || 0) + Math.max(0, b[i]);
      return sum;
    });
    const pvOn = pvSum.some((v) => v !== null && v >= VSC_PV_MIN_W);
    const peak = Math.max(0, ...charge.map((v) => v || 0), ...discharge.map((v) => v || 0), ...(pvOn ? pvSum.map((v) => v || 0) : [0]));
    const max = vscNiceMax(Math.max(500, peak));
    const x = (i) => m.l + ((i + 0.5) / n) * pw;
    const yP = (v) => m.t + ph - (Math.min(max, v) / max) * ph;
    const yS = (v) => m.t + ph - (Math.min(100, Math.max(0, v)) / 100) * ph;
    const base = m.t + ph;

    const line = (values, y) => {
      let dPath = "";
      let open = false;
      values.forEach((v, i) => {
        if (v === null) {
          open = false;
          return;
        }
        dPath += `${open ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
        open = true;
      });
      return dPath;
    };
    const area = (values) => {
      let dPath = "";
      let first = -1;
      const close = (last) => {
        if (first >= 0) dPath += `L${x(last).toFixed(1)} ${base} L${x(first).toFixed(1)} ${base} Z `;
        first = -1;
      };
      values.forEach((v, i) => {
        if (v === null) {
          close(i - 1);
          return;
        }
        dPath += `${first < 0 ? "M" : "L"}${x(i).toFixed(1)} ${yP(v).toFixed(1)} `;
        if (first < 0) first = i;
      });
      close(values.length - 1);
      return dPath;
    };

    const powerLabel = (v) => (max >= 2000 ? `${vscNum(hass, v / 1000, v % 1000 ? 1 : 0)} kW` : `${vscNum(hass, v, 0)} W`);
    let grid = "";
    for (const f of [0, 0.5, 1]) {
      const gy = (m.t + ph - f * ph).toFixed(1);
      grid += `<line class="grid" x1="${m.l}" y1="${gy}" x2="${W - m.r}" y2="${gy}" />`;
      grid += `<text class="axis" x="${m.l - 6}" y="${gy}" dy="3.5" text-anchor="end">${vscEsc(powerLabel(max * f))}</text>`;
      grid += `<text class="axis" x="${W - m.r + 6}" y="${gy}" dy="3.5">${Math.round(f * 100)} %</text>`;
    }
    const hours = this._config.hours;
    const stepH = [1, 2, 3, 4, 6, 12].find((s) => hours / s <= Math.max(2, Math.floor(pw / 70))) || 12;
    const t0 = new Date(h.start);
    t0.setMinutes(0, 0, 0);
    let ticks = "";
    for (let t = t0.getTime(); t <= h.end; t += 3600000) {
      const dt = new Date(t);
      if (t < h.start || dt.getHours() % stepH !== 0) continue;
      const tx = (m.l + ((t - h.start) / (h.end - h.start)) * pw).toFixed(1);
      ticks += `<line class="grid v" x1="${tx}" y1="${m.t}" x2="${tx}" y2="${base}" />`;
      ticks += `<text class="axis" x="${tx}" y="${H - 5}" text-anchor="middle">${vscEsc(dt.toLocaleTimeString(vscLocale(hass), { hour: "2-digit", minute: "2-digit" }))}</text>`;
    }

    this._chart.innerHTML = `${head(pvOn)}
      <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${vscEsc(vscL(hass, "history"))}">
        ${grid}${ticks}
        <path class="area c" d="${area(charge)}" /><path class="ln c" d="${line(charge, yP)}" />
        <path class="area d" d="${area(discharge)}" /><path class="ln d" d="${line(discharge, yP)}" />
        ${pvOn ? `<path class="ln p" d="${line(pvSum, yP)}" />` : ""}
        <path class="ln s" d="${line(soc, yS)}" />
      </svg>`;
  }
}

const VSC_STYLE = `
  :host { --vsc-charge: #2fbf71; --vsc-discharge: #3b9cff; --vsc-warn: #f2a33a; --vsc-low: #e5534b; --vsc-pv: #f5b82e; display: block; container-type: inline-size; }
  ha-card { padding: 16px; overflow: hidden; }
  .note { color: var(--secondary-text-color); padding: 12px 4px; }
  .head-l { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .head-icon { --mdc-icon-size: 34px; color: var(--secondary-text-color); flex: none; }
  .head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  .title { font-size: 1.35em; font-weight: 600; line-height: 1.2; }
  .sub { color: var(--secondary-text-color); margin-top: 2px; }
  .dry { margin-left: 6px; padding: 1px 7px; border-radius: 9px; font-size: 0.8em; background: color-mix(in srgb, var(--vsc-warn) 22%, transparent); color: var(--primary-text-color); }
  .live { color: var(--secondary-text-color); font-size: 0.85em; white-space: nowrap; display: flex; align-items: center; gap: 6px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--disabled-text-color, #888); }
  .live.on .dot { background: var(--vsc-charge); box-shadow: 0 0 6px var(--vsc-charge); }

  .body { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1.05fr) minmax(0, 1.1fr); gap: 16px; align-items: center; margin-top: 8px; }
  .body.no-art { grid-template-columns: minmax(0, 1.15fr) minmax(0, 1.1fr); }
  .art svg, .gauge svg { width: 100%; height: auto; display: block; }
  .gauge svg { max-width: 300px; margin: 0 auto; }
  .track { fill: none; stroke: color-mix(in srgb, var(--primary-text-color) 14%, transparent); stroke-width: 16; stroke-linecap: round; }
  .arc { fill: none; stroke-width: 16; stroke-linecap: round; transition: stroke-dasharray 0.6s ease; }
  .arc.ok { stroke: var(--vsc-charge); } .arc.mid { stroke: var(--vsc-warn); } .arc.low { stroke: var(--vsc-low); } .arc.none { stroke: transparent; }
  .pct { font-size: 46px; font-weight: 700; fill: var(--primary-text-color); }
  .pct-unit { font-size: 24px; font-weight: 600; }
  .pct-label { font-size: 13px; fill: var(--secondary-text-color); }
  .batt .shell { fill: none; stroke: var(--primary-text-color); stroke-width: 2; opacity: 0.8; }
  .batt .tip { fill: var(--primary-text-color); opacity: 0.8; }
  .batt .bar { fill: var(--vsc-charge); } .batt.mid .bar { fill: var(--vsc-warn); } .batt.low .bar { fill: var(--vsc-low); }

  .tiles { display: grid; gap: 10px; }
  .tile { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--divider-color); background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); min-width: 0; }
  .badge { flex: none; width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background: color-mix(in srgb, var(--primary-text-color) 9%, transparent); color: var(--secondary-text-color); }
  .value { font-size: 1.3em; font-weight: 600; line-height: 1.15; white-space: nowrap; }
  .unit { font-size: 0.72em; font-weight: 500; }
  .label { color: var(--secondary-text-color); font-size: 0.85em; }
  .tile.c.active .badge { background: color-mix(in srgb, var(--vsc-charge) 24%, transparent); color: var(--vsc-charge); }
  .tile.c.active .value { color: var(--vsc-charge); }
  .tile.d.active .badge { background: color-mix(in srgb, var(--vsc-discharge) 24%, transparent); color: var(--vsc-discharge); }
  .tile.d.active .value { color: var(--vsc-discharge); }
  .tile.c .value { color: var(--vsc-charge); } .tile.d .value { color: var(--vsc-discharge); }
  .tile.c:not(.active) .value, .tile.d:not(.active) .value { opacity: 0.75; }
  .tile.f.m-charge .badge { background: color-mix(in srgb, var(--vsc-charge) 24%, transparent); color: var(--vsc-charge); }
  .tile.f.m-discharge .badge { background: color-mix(in srgb, var(--vsc-discharge) 24%, transparent); color: var(--vsc-discharge); }
  .tile.p.active .badge { background: color-mix(in srgb, var(--vsc-pv) 24%, transparent); color: var(--vsc-pv); }

  .art .sun circle { fill: var(--vsc-pv); } .art .sun line { stroke: var(--vsc-pv); stroke-width: 2; stroke-linecap: round; }
  .art .moon { fill: color-mix(in srgb, var(--primary-text-color) 45%, transparent); }
  .art .ground { fill: color-mix(in srgb, var(--vsc-charge) 14%, transparent); }
  .art .post { stroke: color-mix(in srgb, var(--primary-text-color) 45%, transparent); stroke-width: 3; stroke-linecap: round; fill: none; }
  .art .panel { fill: #2459c4; stroke: #8fb6ff; stroke-width: 1.5; stroke-linejoin: round; }
  .art .panel-lines { stroke: #8fb6ff; stroke-width: 1; fill: none; opacity: 0.85; }
  .art .wall { fill: color-mix(in srgb, var(--primary-text-color) 18%, var(--card-background-color, #fff)); }
  .art .roof, .art .chimney { fill: color-mix(in srgb, var(--primary-text-color) 38%, var(--card-background-color, #fff)); }
  .art .window { fill: #f7b84a; } .art .window-bars { stroke: color-mix(in srgb, var(--primary-text-color) 55%, transparent); stroke-width: 1.2; }
  .art .flow { fill: none; stroke-width: 3.5; stroke-linecap: round; stroke-dasharray: 5 7; stroke: color-mix(in srgb, var(--primary-text-color) 18%, transparent); }
  .art .tip { fill: none; stroke-width: 3.5; stroke-linecap: round; stroke-linejoin: round; stroke: color-mix(in srgb, var(--primary-text-color) 18%, transparent); }
  .art .flow.on-charge { stroke: var(--vsc-charge); animation: vsc-in 0.9s linear infinite; }
  .art .tip.on-charge { stroke: var(--vsc-charge); }
  .art .flow.on-discharge { stroke: var(--vsc-discharge); animation: vsc-in 0.9s linear infinite; }
  .art .tip.on-discharge { stroke: var(--vsc-discharge); }
  .art .box { fill: color-mix(in srgb, var(--primary-text-color) 80%, var(--card-background-color, #fff)); stroke: color-mix(in srgb, var(--primary-text-color) 40%, transparent); stroke-width: 1.5; }
  .art .box-cap { fill: color-mix(in srgb, var(--primary-text-color) 55%, transparent); }
  .art .box-inner { fill: color-mix(in srgb, var(--primary-text-color) 12%, var(--card-background-color, #000)); }
  .art .lvl { fill: color-mix(in srgb, var(--primary-text-color) 55%, transparent); }
  .art .mode-charge .lvl { fill: var(--vsc-charge); }
  .art .mode-discharge .lvl { fill: var(--vsc-discharge); }
  .art .cap-soc { font-size: 11px; font-weight: 600; fill: var(--primary-text-color); }
  .art .cap-name { font-size: 9.5px; fill: var(--secondary-text-color); }

  .art .panel.own { stroke-width: 1.2; }
  .art .pv-flow { fill: none; stroke: var(--vsc-pv); stroke-width: 3; stroke-linecap: round; stroke-dasharray: 3 4; animation: vsc-in 0.9s linear infinite; }
  .mppt { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin-top: 12px; }
  .mp { padding: 8px 12px; border-radius: 12px; border: 1px solid var(--divider-color); background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); }
  .mp-h { display: flex; justify-content: space-between; gap: 8px; font-size: 0.9em; color: var(--secondary-text-color); }
  .mp-h b { color: var(--primary-text-color); white-space: nowrap; }
  .mp-bar { height: 6px; border-radius: 3px; margin-top: 6px; overflow: hidden; background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); }
  .mp-bar i { display: block; height: 100%; border-radius: 3px; background: var(--vsc-pv); }
  .status { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; margin-top: 14px; }
  .reason, .chip { display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; border: 1px solid var(--divider-color); background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); }
  .reason { padding: 7px 16px 7px 12px; font-weight: 600; min-width: 0; }
  .chips { display: inline-flex; flex-wrap: wrap; gap: 8px; }
  .chip { padding: 5px 13px 5px 10px; font-size: 0.9em; color: var(--secondary-text-color); }
  .cdot { width: 10px; height: 10px; border-radius: 50%; flex: none; background: var(--disabled-text-color, #888); }
  .chip.charge .cdot, .reason.mode-charge .cdot { background: var(--vsc-charge); }
  .chip.discharge .cdot, .reason.mode-discharge .cdot { background: var(--vsc-discharge); }
  .reason.mode-charge, .chip.charge.on { border-color: var(--vsc-charge); background: color-mix(in srgb, var(--vsc-charge) 16%, transparent); color: var(--primary-text-color); }
  .reason.mode-discharge, .chip.discharge.on { border-color: var(--vsc-discharge); background: color-mix(in srgb, var(--vsc-discharge) 16%, transparent); color: var(--primary-text-color); }
  .chip.idle.on { border-color: var(--secondary-text-color); color: var(--primary-text-color); }
  @keyframes vsc-in { to { stroke-dashoffset: -12; } }
  @media (prefers-reduced-motion: reduce) { .art .flow, .art .pv-flow { animation: none !important; } .arc { transition: none; } }

  .chart { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--divider-color); }
  .chart svg { display: block; max-width: 100%; }
  .chart-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px 14px; margin-bottom: 6px; }
  .chart-title { font-weight: 600; display: flex; align-items: center; gap: 8px; }
  .chart-title ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
  .legend { color: var(--secondary-text-color); font-size: 0.85em; display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px; }
  .legend .k { width: 10px; height: 10px; border-radius: 50%; margin-left: 10px; }
  .legend .k.c { background: var(--vsc-charge); } .legend .k.d { background: var(--vsc-discharge); }
  .legend .k.p { background: var(--vsc-pv); }
  .legend .k.s { background: var(--secondary-text-color); border-radius: 2px; height: 4px; width: 14px; }
  .grid { stroke: var(--divider-color); stroke-width: 1; } .grid.v { opacity: 0.5; }
  .axis { font-size: 11px; fill: var(--secondary-text-color); }
  .ln { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .ln.c { stroke: var(--vsc-charge); } .ln.d { stroke: var(--vsc-discharge); }
  .ln.p { stroke: var(--vsc-pv); stroke-dasharray: 5 4; }
  .ln.s { stroke: var(--secondary-text-color); stroke-width: 1.8; }
  .area { stroke: none; } .area.c { fill: color-mix(in srgb, var(--vsc-charge) 26%, transparent); } .area.d { fill: color-mix(in srgb, var(--vsc-discharge) 26%, transparent); }

  @container (max-width: 640px) {
    .body, .body.no-art { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
    .art { display: none; }
  }
  @container (max-width: 420px) {
    .body, .body.no-art { grid-template-columns: minmax(0, 1fr); }
    .gauge svg { max-width: 230px; }
    .tiles { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
    .tile { padding: 8px 10px; gap: 8px; }
    .badge { width: 32px; height: 32px; --mdc-icon-size: 20px; }
    .value { font-size: 1.1em; }
  }
`;

customElements.define("venus-surplus-card", VenusSurplusCard);

class VenusSurplusCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        const config = { ...this._config, ...ev.detail.value };
        if (!config.title) delete config.title;
        if (!config.first_battery_name) delete config.first_battery_name;
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = { hours: 6, show_illustration: true, show_chart: true, ...this._config };
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { filter: { integration: "venus_surplus", domain: "sensor" } } } },
      { name: "title", selector: { text: {} } },
      { name: "first_battery_name", selector: { text: {} } },
      { name: "hours", selector: { number: { min: 1, max: 48, step: 1, mode: "box" } } },
      { name: "show_illustration", selector: { boolean: {} } },
      { name: "show_chart", selector: { boolean: {} } },
    ];
    this._form.computeLabel = (schema) => vscL(this._hass, schema.name, VSC_EDITOR_LABELS);
  }
}

customElements.define("venus-surplus-card-editor", VenusSurplusCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "venus-surplus-card",
  name: "Venus Surplus",
  description: "State of charge, charge and discharge power and the history of the battery run by Venus Surplus Control.",
  preview: true,
  documentationURL: "https://github.com/prusuino/ha_venus_surplus_control#dashboard-card",
});

console.info(`%c VENUS-SURPLUS-CARD %c ${VSC_CARD_VERSION} `, "background:#2fbf71;color:#fff;font-weight:700", "background:#333;color:#fff");
