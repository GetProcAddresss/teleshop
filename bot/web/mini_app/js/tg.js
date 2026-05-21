export const tg = window.Telegram?.WebApp || null;

export function initTg() {
  if (!tg) return;
  try {
    tg.ready();
    tg.expand();
    if (typeof tg.enableClosingConfirmation === "function") tg.enableClosingConfirmation();
    if (typeof tg.disableVerticalSwipes === "function") tg.disableVerticalSwipes();
  } catch {}
}

export function setHeaderColors() {
  if (!tg) return;
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  const surface = isDark ? "#1A2031" : "#FFFFFF";
  const bg = isDark ? "#0F1422" : "#F1ECE2";
  try {
    if (typeof tg.setHeaderColor === "function") tg.setHeaderColor(surface);
    if (typeof tg.setBackgroundColor === "function") tg.setBackgroundColor(bg);
  } catch {}
}

export function haptic(type = "light") {
  try {
    const hf = tg?.HapticFeedback;
    if (!hf) return;
    if (type === "success" || type === "warning" || type === "error") hf.notificationOccurred(type);
    else if (type === "selection") hf.selectionChanged();
    else hf.impactOccurred(type);
  } catch {}
}

export function mainButton() { return tg?.MainButton || null; }
export function backButton() { return tg?.BackButton || null; }

export function showMainButton({ text, onClick, color, textColor }) {
  const mb = mainButton(); if (!mb) return;
  try {
    if (color) mb.setParams({ color, text_color: textColor || "#ffffff", text });
    else mb.setText(text);
    mb.offClick(window.__mb_handler);
    window.__mb_handler = onClick;
    mb.onClick(window.__mb_handler);
    mb.show();
    mb.enable();
  } catch {}
}

export function hideMainButton() {
  const mb = mainButton(); if (!mb) return;
  try {
    mb.hide();
    if (window.__mb_handler) { mb.offClick(window.__mb_handler); window.__mb_handler = null; }
  } catch {}
}

export function showBackButton(onClick) {
  const bb = backButton(); if (!bb) return;
  try {
    bb.offClick(window.__bb_handler);
    window.__bb_handler = onClick;
    bb.onClick(window.__bb_handler);
    bb.show();
  } catch {}
}

export function hideBackButton() {
  const bb = backButton(); if (!bb) return;
  try {
    bb.hide();
    if (window.__bb_handler) { bb.offClick(window.__bb_handler); window.__bb_handler = null; }
  } catch {}
}
