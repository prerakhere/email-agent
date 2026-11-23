// The README's agent diagram: hand-drawn look (rough.js), every box placed exactly, light and dark.
//
// To change it, edit the layout below, then from this folder:
//   npm install roughjs@4.6.6
//   curl -sLO https://github.com/google/fonts/raw/main/ofl/architectsdaughter/ArchitectsDaughter-Regular.ttf
//   # optional, keeps each SVG small: embed only the letters the diagram uses
//   uvx --from fonttools pyftsubset ArchitectsDaughter-Regular.ttf --text-file=<(grep -o '"[^"]*"' gen.mjs) \
//       --output-file=font.ttf
//   node gen.mjs font.ttf agent.svg agent-dark.svg
//
// The font (Architects Daughter, SIL Open Font License, see OFL.txt) is embedded in the SVGs.
import fs from "node:fs";
import rough from "roughjs";

const [fontPath, outLight, outDark] = process.argv.slice(2);
const font = fs.readFileSync(fontPath).toString("base64");
const gen = rough.generator();

const THEMES = {
  light: {
    bg: "#FFFFFF", text: "#1E293B", muted: "#64748B", line: "#64748B", soft: "#94A3B8",
    node: "#FFFFFF", nodeStroke: "#475569", minorStroke: "#94A3B8",
    panels: {
      sort: { fill: "#EEF2FF", stroke: "#6366F1", title: "#4338CA" },
      report: { fill: "#F1F5F9", stroke: "#64748B", title: "#334155" },
      clear: { fill: "#ECFDF5", stroke: "#10B981", title: "#047857" },
    },
  },
  dark: {
    bg: "#0D1117", text: "#E6EDF3", muted: "#9DA7B3", line: "#9DA7B3", soft: "#6E7781",
    node: "#161B22", nodeStroke: "#9DA7B3", minorStroke: "#6E7781",
    panels: {
      sort: { fill: "#1B1E3A", stroke: "#818CF8", title: "#A5B4FC" },
      report: { fill: "#1A2029", stroke: "#8B949E", title: "#C9D1D9" },
      clear: { fill: "#0F2620", stroke: "#34D399", title: "#6EE7B7" },
    },
  },
};

const W = 990, H = 765;
const STEP = { w: 150, h: 52 };

function paths(drawable) {
  return gen.toPaths(drawable).map((p) =>
    `<path d="${p.d}" stroke="${p.stroke}" stroke-width="${p.strokeWidth}" fill="${p.fill || "none"}" stroke-linecap="round" stroke-linejoin="round"/>`
  ).join("");
}

function text(x, y, label, { size = 18, color, anchor = "middle" } = {}) {
  const lines = label.split("\n");
  const lh = size * 1.15;
  const y0 = y - ((lines.length - 1) * lh) / 2;
  return lines.map((line, i) =>
    `<text x="${x}" y="${y0 + i * lh}" font-family="DiagramFont, 'Comic Sans MS', cursive" font-weight="400" font-size="${size}" fill="${color}" text-anchor="${anchor}" dominant-baseline="central">${line.replace(/&/g, "&amp;")}</text>`
  ).join("");
}

function render(t) {
  const out = [];
  const seed = { v: 7 };
  const opt = (o) => ({ seed: seed.v++, roughness: 1.1, bowing: 0.8, ...o });

  const panel = (x, y, w, h, key, title) => {
    const p = t.panels[key];
    out.push(paths(gen.rectangle(x, y, w, h, opt({ fill: p.fill, fillStyle: "solid", stroke: p.stroke, strokeWidth: 1.8 }))));
    out.push(text(x + 20, y + 30, title, { size: 21, color: p.title, anchor: "start" }));
  };
  const step = (cx, cy, label, { w = STEP.w, h = STEP.h, minor = false } = {}) => {
    out.push(paths(gen.rectangle(cx - w / 2, cy - h / 2, w, h, opt({ fill: t.node, fillStyle: "solid", stroke: minor ? t.minorStroke : t.nodeStroke, strokeWidth: minor ? 1.2 : 1.5 }))));
    out.push(text(cx, cy, label, { size: 18, color: minor ? t.muted : t.text }));
  };
  const oval = (cx, cy, label, w = 120) => {
    out.push(paths(gen.ellipse(cx, cy, w, 46, opt({ fill: t.node, fillStyle: "solid", stroke: t.nodeStroke, strokeWidth: 1.5 }))));
    out.push(text(cx, cy, label, { size: 18, color: t.muted }));
  };
  const hexagon = (cx, cy, label) => {
    const w = 170, h = 62, k = 22;
    const pts = [[cx - w / 2, cy], [cx - w / 2 + k, cy - h / 2], [cx + w / 2 - k, cy - h / 2], [cx + w / 2, cy], [cx + w / 2 - k, cy + h / 2], [cx - w / 2 + k, cy + h / 2]];
    out.push(paths(gen.polygon(pts, opt({ fill: t.node, fillStyle: "solid", stroke: t.nodeStroke, strokeWidth: 1.5 }))));
    out.push(text(cx, cy, label, { size: 18, color: t.text }));
  };
  // A polyline with an arrowhead at the last point. `label` is drawn at `at`, beside the line.
  const arrow = (pts, { label, at, anchor = "middle", minor = false } = {}) => {
    const colour = minor ? t.soft : t.line;
    out.push(paths(gen.linearPath(pts, opt({ stroke: colour, strokeWidth: 1.4, roughness: 0.7 }))));
    const [x1, y1] = pts[pts.length - 2], [x2, y2] = pts[pts.length - 1];
    const a = Math.atan2(y2 - y1, x2 - x1), s = 10;
    const head = [[x2, y2], [x2 - s * Math.cos(a - 0.4), y2 - s * Math.sin(a - 0.4)], [x2 - s * Math.cos(a + 0.4), y2 - s * Math.sin(a + 0.4)]];
    out.push(paths(gen.polygon(head, { seed: seed.v++, roughness: 0.3, fill: colour, fillStyle: "solid", stroke: colour, strokeWidth: 1 })));
    if (label) out.push(text(at[0], at[1], label, { size: 15, color: t.muted, anchor }));
  };

  // ---- ① Read and sort (left column) ----
  const L = 160, R2 = 385;            // main line x, side branch x
  panel(30, 30, 440, 705, "sort", "① Read and Classify");
  oval(L, 105, "start");
  step(L, 190, "fetch");
  step(L, 275, "prefilter");
  step(L, 360, "redact\nsensitive data", { h: 58 });
  out.push(text(L + 95, 360, "masks numbers, codes\nand links before\nevery model call", { size: 15, color: t.muted, anchor: "start" }));
  step(L, 445, "classify");
  step(R2, 445, "re-read\nfull email", { w: 130, h: 58 });
  step(L, 555, "choose labels");
  step(R2, 555, "extract", { w: 130 });
  oval(L, 670, "downstream ready", 205);
  arrow([[L, 128], [L, 164]]);
  arrow([[L, 216], [L, 249]]);
  arrow([[L, 301], [L, 331]]);
  arrow([[L, 389], [L, 419]]);
  arrow([[L + 75, 434], [R2 - 65, 434]], { label: "unsure", at: [(L + 75 + R2 - 65) / 2, 418] });
  arrow([[R2 - 65, 458], [L + 75, 458]], { label: "once", at: [(L + 75 + R2 - 65) / 2, 475] });
  arrow([[L, 471], [L, 529]]);
  arrow([[L + 75, 555], [R2 - 65, 555]], { label: "bills or\npayments", at: [(L + 75 + R2 - 65) / 2, 525] });
  arrow([[L, 581], [L, 647]]);
  arrow([[R2 - 25, 581], [L + 88, 657]]);

  // ---- ② Label and report and ③ Clear with your OK (right column) ----
  const C = 670, S = 860, X = 745, D0 = 630;   // ② main x, ② side x, ③ main x, ③ done x
  panel(530, 30, 430, 300, "report", "② Label and Summarize");
  step(C, 135, "apply labels");
  step(S, 135, "logging", { w: 120, h: 44, minor: true });
  out.push(text(S, 190, "e.g. log bills to\nGoogle Sheet", { size: 15, color: t.muted }));
  step(C, 255, "summarize &\nsend digest", { w: 170, h: 58 });
  arrow([[C, 161], [C, 226]]);
  arrow([[C + 75, 135], [S - 60, 135]], { minor: true });

  panel(530, 375, 430, 360, "clear", "③ Clear Clutter");
  hexagon(X, 490, "wait for you\n(paused, saved)");
  step(X, 600, "move approved\nemails to bin", { w: 170, h: 58 });
  oval(X, 695, "done");
  arrow([[X, 521], [X, 571]], { label: "approve or reject", at: [X + 12, 546], anchor: "start" });
  arrow([[X, 629], [X, 672]]);

  // ---- handoffs between panels: step to step ----
  arrow([[L + 103, 670], [500, 670], [500, 135], [C - 75, 135]]);
  arrow([[C, 284], [C, 352], [X, 352], [X, 459]], { label: "clutter found", at: [X + 12, 425], anchor: "start" });


  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">` +
    `<style>@font-face{font-family:DiagramFont;font-weight:400;src:url(data:font/ttf;base64,${font}) format("truetype");}</style>` +
    `<rect width="${W}" height="${H}" fill="${t.bg}"/>` + out.join("") + `</svg>`;
}

fs.writeFileSync(outLight, render(THEMES.light));
fs.writeFileSync(outDark, render(THEMES.dark));
console.log("wrote", outLight, outDark);
