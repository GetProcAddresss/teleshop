import { api } from "../api.js";
import { state, addToCart, cartCount, saveCart } from "../state.js";
import { toast, openSheet, productSkeletons, escapeHtml, fmtMoney, emojiFor } from "../ui.js";
import { haptic } from "../tg.js";
import { openProductDetail } from "./detail.js";

let lastCategoryFetch = 0;

export async function initShop() {
  bindSearch();
  await Promise.all([loadCategories(), loadProducts()]);
}

async function loadCategories() {
  const res = await api.categories();
  if (!res.ok) return;
  state.categories = res.data || [];
  renderChips();
  lastCategoryFetch = Date.now();
}

function renderChips() {
  const scroll = document.getElementById("chipsScroll");
  if (!scroll) return;
  let html = makeChip("All", "");
  state.categories.forEach(c => { html += makeChip(c.name, c.name); });
  scroll.innerHTML = html;
  scroll.querySelectorAll(".chip").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeCategory = btn.dataset.category;
      scroll.querySelectorAll(".chip").forEach(c => c.classList.remove("is-active"));
      btn.classList.add("is-active");
      haptic("selection");
      loadProducts();
    });
  });
}

function makeChip(label, value) {
  const active = state.activeCategory === value ? " is-active" : "";
  return `<button class="chip${active}" data-category="${escapeHtml(value)}">${escapeHtml(label)}</button>`;
}

export async function loadProducts() {
  const grid = document.getElementById("productGrid");
  if (!grid) return;
  grid.innerHTML = productSkeletons(6);

  const res = await api.products({ category: state.activeCategory, search: state.searchQuery });
  if (!res.ok) {
    grid.innerHTML = errorState("Failed to load products", "Retry", () => loadProducts());
    bindRetry(grid);
    return;
  }
  state.products = res.data || [];
  renderProducts();
}

function renderProducts() {
  const grid = document.getElementById("productGrid");
  if (!grid) return;
  if (!state.products.length) {
    grid.innerHTML = emptyState(
      state.searchQuery
        ? "No products match your search"
        : state.activeCategory
          ? "No products in this category yet"
          : "No products available right now"
    );
    return;
  }
  grid.innerHTML = state.products.map(productCard).join("");
  grid.querySelectorAll("[data-pid]").forEach(card => {
    card.addEventListener("click", (e) => {
      if (e.target.closest(".card-btn")) return;
      const id = Number(card.dataset.pid);
      const p = state.products.find(x => x.id === id);
      if (p) openProductDetail(p);
    });
  });
  grid.querySelectorAll(".card-btn[data-add]").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = Number(btn.dataset.add);
      const p = state.products.find(x => x.id === id);
      if (!p || !p.in_stock) return;
      addToCart(p);
      haptic("success");
      toast(`Added "${p.name}" to cart`, "success", 1600);
      btn.textContent = "In cart";
      btn.classList.add("is-in-cart");
    });
  });
}

function productCard(p) {
  const inCart = !!state.cart[p.name];
  const out = !p.in_stock;
  return `
    <article class="product-card${out ? " is-out" : ""}" data-pid="${p.id}" tabindex="0" role="button" aria-label="${escapeHtml(p.name)}">
      <div class="card-thumb">${
        p.image_url
          ? `<img class="thumb-img" src="${escapeHtml(p.image_url)}" alt="${escapeHtml(p.name)}" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{textContent:'${emojiFor(p.name)}'}))"/>`
          : emojiFor(p.name)
      }</div>
      <div class="card-body">
        <div class="card-name">${escapeHtml(p.name)}</div>
        <div class="card-desc">${escapeHtml(p.description || "")}</div>
        <div class="card-footer">
          <span class="card-price">${fmtMoney(p.price)}</span>
          ${out
            ? `<span class="out-badge">Out</span>`
            : `<button class="card-btn${inCart ? " is-in-cart" : ""}" data-add="${p.id}">${inCart ? "In cart" : "Add"}</button>`}
        </div>
      </div>
    </article>`;
}

function emptyState(text) {
  return `<div class="empty-state">
    <div class="empty-icon">🛍️</div>
    <div class="empty-title">Nothing here yet</div>
    <p class="empty-text">${escapeHtml(text)}</p>
    <button class="btn btn-secondary" data-retry>Refresh</button>
  </div>`;
}

function errorState(title, btn, _fn) {
  return `<div class="empty-state">
    <div class="empty-icon">⚠️</div>
    <div class="empty-title">${escapeHtml(title)}</div>
    <p class="empty-text">Check your connection and try again.</p>
    <button class="btn btn-primary" data-retry>${escapeHtml(btn)}</button>
  </div>`;
}

function bindRetry(grid) {
  grid.querySelector("[data-retry]")?.addEventListener("click", () => loadProducts());
}

let _searchTimer;
function bindSearch() {
  const toggle = document.getElementById("searchToggleBtn");
  const drawer = document.getElementById("searchDrawer");
  const input = document.getElementById("searchInput");
  const clear = document.getElementById("searchClear");
  if (!toggle || !drawer || !input) return;

  toggle.addEventListener("click", () => {
    state.searchVisible = !state.searchVisible;
    drawer.hidden = !state.searchVisible;
    if (state.searchVisible) setTimeout(() => input.focus(), 50);
    else {
      input.value = ""; state.searchQuery = "";
      if (clear) clear.hidden = true;
      loadProducts();
    }
  });

  input.addEventListener("input", () => {
    state.searchQuery = input.value.trim();
    if (clear) clear.hidden = !state.searchQuery;
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(loadProducts, 320);
  });

  clear?.addEventListener("click", () => {
    input.value = ""; state.searchQuery = "";
    clear.hidden = true; input.focus();
    loadProducts();
  });
}

document.addEventListener("cart:cleared", () => {
  document.querySelectorAll(".card-btn.is-in-cart").forEach(b => { b.textContent = "Add"; b.classList.remove("is-in-cart"); });
});
