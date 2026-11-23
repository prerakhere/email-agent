// The README's cloud diagram: official Azure icons, every icon placed exactly, light and dark.
//
// To change it, edit the layout below, then from this folder:
//   node cloud.mjs icons cloud.svg cloud-dark.svg
// No packages needed. Icons are embedded in the SVGs: Azure icons from Microsoft's architecture icon
// set (as shipped by the `diagrams` Python package), Gmail and Google Sheets logos from Simple Icons.
import fs from "node:fs";
import path from "node:path";

const [iconDir, outLight, outDark] = process.argv.slice(2);
const icon = (name) => {
  const file = path.join(iconDir, name);
  const mime = name.endsWith(".svg") ? "image/svg+xml" : "image/png";
  return `data:${mime};base64,${fs.readFileSync(file).toString("base64")}`;
};
const ICONS = Object.fromEntries(
  ["user.png", "gmail.svg", "sheets.svg", "timer.png", "function.png", "keyvault.png", "openai.png", "db.png", "insights.png", "alerts.png"]
    .map((n) => [n, icon(n)])
);

const THEMES = {
  light: {
    bg: "#FFFFFF", text: "#1E293B", muted: "#475569", line: "#64748B", userTint: "none",
    google: { fill: "#FFFBEB", stroke: "#F59E0B", title: "#B45309" },
    azure: { fill: "#F0F7FF", stroke: "#3B82F6", title: "#1D4ED8" },
    func: { fill: "#E8EEFF", stroke: "#6366F1", title: "#4338CA" },
  },
  dark: {
    bg: "#0D1117", text: "#E6EDF3", muted: "#9DA7B3", line: "#8B949E", userTint: "invert(1)",
    google: { fill: "#211A0C", stroke: "#F59E0B", title: "#FCD34D" },
    azure: { fill: "#0E1A2B", stroke: "#60A5FA", title: "#93C5FD" },
    func: { fill: "#161D36", stroke: "#818CF8", title: "#A5B4FC" },
  },
};

const W = 980, H = 655, SIZE = 39;   // 70% of the original 56
const FONT = "'Segoe UI', -apple-system, Helvetica, Arial, sans-serif";

function render(t) {
  const out = [];
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const text = (x, y, s, { size = 14, color = t.text, anchor = "middle", weight = 400 } = {}) => {
    const lines = s.split("\n"), lh = size * 1.25, y0 = y - ((lines.length - 1) * lh) / 2;
    lines.forEach((line, i) => out.push(`<text x="${x}" y="${y0 + i * lh}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${color}" text-anchor="${anchor}" dominant-baseline="central">${esc(line)}</text>`));
  };
  const group = (x, y, w, h, c, title, { titleAt = "top" } = {}) => {
    out.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="${c.fill}" stroke="${c.stroke}" stroke-width="1.5"/>`);
    text(titleAt === "top" ? x + 14 : x + w / 2, titleAt === "top" ? y + 20 : y + h - 18, title,
      { size: 15, color: c.title, anchor: titleAt === "top" ? "start" : "middle" });
  };
  // an icon with its label underneath (or to the right)
  const service = (name, x, y, label, { right = false, tint = false } = {}) => {
    out.push(`<image href="${ICONS[name]}" x="${x - SIZE / 2}" y="${y - SIZE / 2}" width="${SIZE}" height="${SIZE}"${tint && t.userTint !== "none" ? ` style="filter:${t.userTint}"` : ""}/>`);
    if (right) text(x + SIZE / 2 + 10, y, label, { anchor: "start" });
    else text(x, y + SIZE / 2 + 15 + (label.split("\n").length - 1) * 8.75, label);
  };
  // a right-angled connector through the given points, with an arrowhead at the end
  const arrow = (pts, { label, at, anchor = "middle", dashed = false } = {}) => {
    const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x},${y}`).join(" ");
    out.push(`<path d="${d}" fill="none" stroke="${t.line}" stroke-width="1.5"${dashed ? ' stroke-dasharray="5 4"' : ""} marker-end="url(#head)"/>`);
    if (label) text(at[0], at[1], label, { size: 12.5, color: t.muted, anchor });
  };

  // ---- You and Google ----
  service("user.png", 70, 300, "You", { tint: true });
  group(165, 70, 170, 310, t.google, "Google");
  service("sheets.svg", 250, 170, "Sheets");
  service("gmail.svg", 250, 300, "Mailbox");

  // ---- Azure ----
  group(420, 30, 530, 570, t.azure, "Azure");
  service("timer.png", 560, 80, "scheduled run", { right: true });
  service("keyvault.png", 790, 80, "Key Vault", { right: true });
  group(560, 125, 160, 345, t.func, "Function App", { titleAt: "bottom" });
  service("function.png", 640, 195, "email triage");
  service("function.png", 640, 375, "email cleanup");
  service("openai.png", 870, 170, "Azure OpenAI");
  service("db.png", 870, 290, "Cosmos DB\n(MongoDB)");
  service("insights.png", 870, 400, "App Insights");
  service("alerts.png", 870, 525, "alert rule");

  // connectors stop just short of each icon's edge (h), and below each icon's label (lb)
  const h = SIZE / 2 + 3, lb = SIZE / 2 + 27;

  // inside Azure
  arrow([[560, 80 + h], [560, 116], [600, 116], [600, 195 - h]]);
  arrow([[790, 80 + h], [790, 116], [690, 116], [690, 195 - h]], { label: "secrets", at: [740, 102], dashed: true });
  arrow([[720, 170], [870 - h, 170]], { label: "redacted text", at: [779, 156] });
  arrow([[720, 290], [870 - h, 290]], { label: "paused approvals", at: [779, 276] });
  arrow([[720, 400], [870 - h, 400]], { label: "logs", at: [779, 386] });
  arrow([[870, 400 + lb], [870, 525 - h]]);

  // between Azure, Google and You
  arrow([[640 - h, 185], [250 + h, 185]], { label: "bills", at: [490, 171] });
  arrow([[640 - h, 205], [390, 205], [390, 295], [250 + h, 295]], { label: "read, label,\nsend digest", at: [490, 231] });
  arrow([[640 - h, 370], [405, 370], [405, 306], [250 + h, 306]], { label: "move approved\nemails to bin", at: [490, 344] });
  arrow([[250 - h, 300], [70 + h, 300]], { label: "digest", at: [133, 286] });
  arrow([[82, 300 + lb], [82, 386], [640 - h, 386]], { label: "approve or reject", at: [300, 400] });
  arrow([[870, 525 + lb], [870, 622], [56, 622], [56, 300 + lb + 2]], { label: "alert email", at: [460, 636] });

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">` +
    `<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${t.line}"/></marker></defs>` +
    `<rect width="${W}" height="${H}" fill="${t.bg}"/>` + out.join("") + `</svg>`;
}

fs.writeFileSync(outLight, render(THEMES.light));
fs.writeFileSync(outDark, render(THEMES.dark));
console.log("wrote", outLight, outDark);
