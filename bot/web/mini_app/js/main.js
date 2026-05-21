import { initTg, tg, haptic, hideMainButton, hideBackButton } from "./tg.js";
import { applyTheme, bindThemeSegment, bindToggleButton, watchSystem } from "./theme.js";
import { loadCart, cartCount, state, subscribe } from "./state.js";
import { bindSheet } from "./ui.js";
import { initShop } from "./views/shop.js";
import { renderCart, bindCart } from "./views/cart.js";
import { loadOrders } from "./views/orders.js";
import { loadProfile, bindProfile } from "./views/profile.js";

const PAGES = ["shop", "cart", "orders", "profile"];

function init() {
  initTg();
  applyTheme();
  watchSystem();
  bindToggleButton();
  bindThemeSegment();
  bindSheet();
  bindNav();
  bindCart();
  bindProfile();
  loadCart();
  updateCartBadge();

  document.addEventListener("cart:change", updateCartBadge);

  initShop();

  // Hash routing (optional, supports deep links)
  window.addEventListener("hashchange", routeFromHash);
  routeFromHash(true);

  // Online/offline indicator
  window.addEventListener("online", () => document.getElementById("offlineBanner")?.setAttribute("hidden", ""));
  window.addEventListener("offline", () => document.getElementById("offlineBanner")?.removeAttribute("hidden"));

  // Register service worker
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/mini/sw.js", { scope: "/mini/" }).catch(() => {});
  }

  // Header scroll shadow
  document.querySelectorAll(".page").forEach(p => {
    p.addEventListener("scroll", () => {
      const h = document.getElementById("appHeader");
      if (!h) return;
      h.classList.toggle("is-scrolled", p.scrollTop > 4);
    }, { passive: true });
  });
}

function bindNav() {
  document.querySelectorAll(".nav-btn[data-page]").forEach(btn => {
    btn.addEventListener("click", () => {
      const page = btn.dataset.page;
      location.hash = "#/" + page;
    });
  });
}

function routeFromHash(initial = false) {
  let page = (location.hash || "").replace("#/", "").trim();
  if (!PAGES.includes(page)) page = "shop";
  showPage(page, initial);
}

function showPage(name, initial = false) {
  if (state.currentPage === name && !initial) return;
  state.currentPage = name;

  document.querySelectorAll(".page").forEach(p => p.classList.remove("is-active"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("is-active"));

  const pageEl = document.getElementById("page" + cap(name));
  const navBtn = document.querySelector(`.nav-btn[data-page="${name}"]`);
  if (pageEl) pageEl.classList.add("is-active");
  if (navBtn) navBtn.classList.add("is-active");

  // Reset Telegram buttons by default
  hideMainButton(); hideBackButton();
  haptic("selection");

  if (name === "cart") renderCart();
  else if (name === "orders") loadOrders();
  else if (name === "profile") loadProfile();
}

function updateCartBadge() {
  const badge = document.getElementById("cartBadge");
  if (!badge) return;
  const n = cartCount();
  if (n > 0) { badge.textContent = String(n); badge.hidden = false; }
  else { badge.hidden = true; }
}

function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

document.addEventListener("DOMContentLoaded", init);
