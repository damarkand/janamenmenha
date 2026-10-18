export const COLORS = {
  accent: "#0d966f",
  blue: "#3b82f6",
  amber: "#f59e0b",
  gray: "#cbd5e1",
  indigo: "#6366f1",
  red: "#dc2626"
};

const NS = "http://www.w3.org/2000/svg";

function el(name, attrs = {}, text) {
  const node = document.createElementNS(NS, name);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (text !== undefined) node.textContent = text;
  return node;
}

function empty(container, text) {
  const div = document.createElement("div");
  div.className = "ws-empty";
  div.textContent = text;
  container.replaceChildren(div);
}

export function barChart(container, items, { planKey = null, valueKey = "value", unit = "", height = 180 } = {}) {
  if (!items.length) return empty(container, "Нет данных");

  const width = 640;
  const pad = { top: 12, right: 8, bottom: 24, left: 30 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...items.map(i => Math.max(i[valueKey] || 0, planKey ? i[planKey] || 0 : 0))) * 1.15;
  const step = innerW / items.length;
  const barW = Math.min(28, step * 0.62);
  const y = v => pad.top + innerH - (v / max) * innerH;

  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });

  [0, 0.5, 1].forEach(f => {
    const v = Math.round(max * f / 1.15);
    svg.append(el("line", { x1: pad.left, x2: width - pad.right, y1: y(v), y2: y(v), stroke: "#eef0ee" }));
    svg.append(el("text", { x: pad.left - 6, y: y(v) + 3, "text-anchor": "end" }, String(v)));
  });

  items.forEach((item, i) => {
    const cx = pad.left + step * i + step / 2;
    const value = item[valueKey] || 0;
    const plan = planKey ? item[planKey] || 0 : 0;
    const over = planKey && plan > 0 && value > plan;
    const bar = el("rect", {
      x: cx - barW / 2, y: y(value), width: barW, height: Math.max(0, pad.top + innerH - y(value)), rx: 4,
      fill: item.color || (over ? COLORS.amber : COLORS.accent)
    });
    bar.append(el("title", {}, `${item.label}: ${value}${unit}${planKey ? ` из ${plan}${unit}` : ""}`));
    svg.append(bar);

    if (planKey && plan > 0) {
      svg.append(el("line", {
        x1: cx - barW / 2 - 3, x2: cx + barW / 2 + 3, y1: y(plan), y2: y(plan),
        stroke: COLORS.indigo, "stroke-width": 2, "stroke-linecap": "round"
      }));
    }

    if (item.short !== undefined) {
      svg.append(el("text", { x: cx, y: height - 6, "text-anchor": "middle" }, item.short));
    }
  });

  container.replaceChildren(svg);
}

export function lineChart(container, items, { height = 170 } = {}) {
  if (!items.length) return empty(container, "Нет данных");

  const width = 420;
  const pad = { top: 14, right: 12, bottom: 24, left: 30 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...items.map(i => i.value)) * 1.2;
  const x = i => pad.left + (items.length === 1 ? innerW / 2 : (innerW * i) / (items.length - 1));
  const y = v => pad.top + innerH - (v / max) * innerH;

  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });

  [0, 0.5, 1].forEach(f => {
    const v = Math.round(max * f / 1.2);
    svg.append(el("line", { x1: pad.left, x2: width - pad.right, y1: y(v), y2: y(v), stroke: "#eef0ee" }));
    svg.append(el("text", { x: pad.left - 6, y: y(v) + 3, "text-anchor": "end" }, String(v)));
  });

  const points = items.map((item, i) => `${x(i)},${y(item.value)}`).join(" ");
  const area = `${x(0)},${y(0)} ${points} ${x(items.length - 1)},${y(0)}`;

  svg.append(el("polygon", { points: area, fill: COLORS.accent, opacity: 0.08 }));
  svg.append(el("polyline", { points, fill: "none", stroke: COLORS.accent, "stroke-width": 2.5, "stroke-linejoin": "round" }));

  items.forEach((item, i) => {
    const dot = el("circle", { cx: x(i), cy: y(item.value), r: 3.5, fill: "#fff", stroke: COLORS.accent, "stroke-width": 2 });
    dot.append(el("title", {}, `${item.label}: ${item.value}`));
    svg.append(dot);
    svg.append(el("text", { x: x(i), y: height - 6, "text-anchor": "middle" }, item.short ?? ""));
  });

  container.replaceChildren(svg);
}

export function donutChart(container, segments, { centerLabel = "" } = {}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  if (!total) return empty(container, "Пока пусто");

  const wrap = document.createElement("div");
  wrap.className = "ws-donut";

  const size = 120;
  const r = 46;
  const c = 2 * Math.PI * r;
  const svg = el("svg", { viewBox: `0 0 ${size} ${size}`, role: "img" });
  let offset = 0;

  svg.append(el("circle", { cx: 60, cy: 60, r, fill: "none", stroke: "#eef0ee", "stroke-width": 14 }));

  segments.filter(s => s.value > 0).forEach(s => {
    const len = (s.value / total) * c;
    const arc = el("circle", {
      cx: 60, cy: 60, r, fill: "none", stroke: s.color, "stroke-width": 14,
      "stroke-dasharray": `${len} ${c - len}`, "stroke-dashoffset": -offset, transform: "rotate(-90 60 60)"
    });
    arc.append(el("title", {}, `${s.label}: ${s.value}`));
    svg.append(arc);
    offset += len;
  });

  svg.append(el("text", { x: 60, y: 58, "text-anchor": "middle", style: "font-size:22px;font-weight:650;fill:#202321" }, String(total)));
  svg.append(el("text", { x: 60, y: 76, "text-anchor": "middle" }, centerLabel));

  const list = document.createElement("div");
  list.className = "ws-donut-list";
  segments.forEach(s => {
    const row = document.createElement("span");
    row.className = "ws-legend-item";
    row.innerHTML = `<span class="ws-swatch" style="--sw:${s.color}"></span>`;
    row.append(`${s.label}: ${s.value}`);
    list.append(row);
  });

  wrap.append(svg, list);
  container.replaceChildren(wrap);
}

export function progressBars(container, items) {
  if (!items.length) return empty(container, "Нет назначенных курсов");

  container.replaceChildren(...items.map(item => {
    const row = document.createElement("div");
    row.className = "ws-bar-row";
    row.innerHTML = `
      <span class="ws-bar-label"></span>
      <span class="ws-bar-value"></span>
      <span class="ws-bar-track"><span class="ws-bar-fill"></span></span>`;
    row.querySelector(".ws-bar-label").textContent = item.label;
    row.querySelector(".ws-bar-label").title = item.label;
    row.querySelector(".ws-bar-value").textContent = `${item.value}%`;
    const fill = row.querySelector(".ws-bar-fill");
    fill.style.width = `${Math.max(0, Math.min(100, item.value))}%`;
    if (item.color) fill.style.background = item.color;
    return row;
  }));
}
