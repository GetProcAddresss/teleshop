import { haptic } from "./tg.js";

/* ───── Toast ───── */
let toastTimer = null;
export function toast(msg, kind = "info", ms = 2400) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.className = "toast" + (kind && kind !== "info" ? ` toast-${kind}` : "");
  requestAnimationFrame(() => el.classList.add("is-show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("is-show"), ms);
  if (kind === "error") haptic("error");
  else if (kind === "success") haptic("success");
}

/* ───── Sheet ───── */
let _closeFn = null;
export function openSheet(html, { onClose } = {}) {
  const overlay = document.getElementById("sheetOverlay");
  const body = document.getElementById("sheetBody");
  if (!overlay || !body) return;
  body.innerHTML = html;
  overlay.hidden = false;
  overlay.removeAttribute("aria-hidden");
  document.body.style.overflow = "hidden";
  _closeFn = onClose || null;
  haptic("light");
}
export function closeSheet() {
  const overlay = document.getElementById("sheetOverlay");
  if (!overlay) return;
  overlay.hidden = true;
  overlay.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  const fn = _closeFn; _closeFn = null;
  if (typeof fn === "function") fn();
}
export function bindSheet() {
  document.getElementById("sheetBackdrop")?.addEventListener("click", closeSheet);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("sheetOverlay")?.hidden) closeSheet();
  });
}

/* ───── Skeletons ───── */
export function productSkeletons(n = 6) {
  let h = "";
  for (let i = 0; i < n; i++) {
    h += `<div class="skeleton-card"><div class="skeleton-thumb"></div>
      <div class="skeleton-line lg skeleton-block"></div>
      <div class="skeleton-line md skeleton-block"></div>
      <div class="skeleton-line sm skeleton-block" style="margin-bottom:12px"></div></div>`;
  }
  return h;
}

/* ───── Helpers ───── */
export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

export function fmtMoney(value, currency = "RUB") {
  const n = Number(value || 0);
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency}`;
  }
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function emojiFor(name) {
  const n = String(name || "").toLowerCase();
  if (/gpt|ai|chat/.test(n)) return "🤖";
  if (/key|license|code/.test(n)) return "🔑";
  if (/account|premium|sub/.test(n)) return "👑";
  if (/vpn|proxy/.test(n)) return "🛡️";
  if (/game|steam/.test(n)) return "🎮";
  return "📦";
}
