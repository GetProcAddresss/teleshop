import { tg, setHeaderColors } from "./tg.js";

const KEY = "em_theme_mode";
const MODES = ["auto", "light", "dark"];

let mql = null;

export function getStoredMode() {
  const v = localStorage.getItem(KEY);
  return MODES.includes(v) ? v : "auto";
}

function resolveScheme(mode) {
  if (mode === "light") return "light";
  if (mode === "dark") return "dark";
  if (tg?.colorScheme) return tg.colorScheme;
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) return "dark";
  return "light";
}

export function applyTheme(mode = getStoredMode(), persist = true) {
  const scheme = resolveScheme(mode);
  document.documentElement.setAttribute("data-theme", scheme);
  if (persist) localStorage.setItem(KEY, mode);
  setHeaderColors();
  document.dispatchEvent(new CustomEvent("theme:change", { detail: { mode, scheme } }));
}

export function bindThemeSegment(rootSel = '[role="radiogroup"]') {
  const root = document.querySelector(rootSel);
  if (!root) return;
  const buttons = root.querySelectorAll("[data-theme-mode]");
  const sync = () => {
    const mode = getStoredMode();
    buttons.forEach(b => {
      const on = b.dataset.themeMode === mode;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-checked", on ? "true" : "false");
    });
  };
  buttons.forEach(b => b.addEventListener("click", () => {
    applyTheme(b.dataset.themeMode);
    sync();
  }));
  document.addEventListener("theme:change", sync);
  sync();
}

export function bindToggleButton(btnSel = "#themeToggleBtn") {
  const btn = document.querySelector(btnSel);
  if (!btn) return;
  btn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    localStorage.setItem(KEY, next);
  });
}

export function watchSystem() {
  if (!window.matchMedia) return;
  mql = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => { if (getStoredMode() === "auto") applyTheme("auto", false); };
  if (mql.addEventListener) mql.addEventListener("change", onChange);
  else mql.addListener(onChange);
  if (tg && typeof tg.onEvent === "function") {
    try { tg.onEvent("themeChanged", () => { if (getStoredMode() === "auto") applyTheme("auto", false); }); } catch {}
  }
}
