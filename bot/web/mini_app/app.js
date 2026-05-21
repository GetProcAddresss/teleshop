/* ── Evrest Market Mini App ── */

const tg = window.Telegram?.WebApp;
const BASE = "";

/* ─────────────────── State ─────────────────── */
const state = {
  products: [],
  categories: [],
  activeCategory: "",
  searchQuery: "",
  cart: {},          // { itemName: { product, qty } }
  user: null,
  orders: [],
  currentPage: "shop",
  searchVisible: false,
};

/* ─────────────────── Init ─────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  if (tg) {
    tg.ready();
    tg.expand();
    applyTgTheme();
  }

  loadTheme();
  bindNav();
  bindSearch();
  bindProfile();

  loadCart();
  updateCartBadge();

  loadCategories();
  loadProducts();
});

/* ─────────────────── Theme ─────────────────── */
function applyTgTheme() {
  if (!tg?.colorScheme) return;
  if (tg.colorScheme === "dark") {
    setDark(true);
  }
}

function loadTheme() {
  const isDark = localStorage.getItem("em_dark") === "1";
  setDark(isDark);
  document.getElementById("darkToggle").checked = isDark;
}

function setDark(on) {
  document.documentElement.setAttribute("data-theme", on ? "dark" : "light");
  localStorage.setItem("em_dark", on ? "1" : "0");
}

/* ─────────────────── API helpers ─────────────────── */
function getHeaders() {
  const h = { "Content-Type": "application/json" };
  if (tg?.initData) h["X-Telegram-Init-Data"] = tg.initData;
  return h;
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: getHeaders(),
    ...opts,
  });
  return res;
}

/* ─────────────────── Navigation ─────────────────── */
function bindNav() {
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => showPage(btn.dataset.page));
  });
}

function showPage(name) {
  if (state.currentPage === name) return;
  state.currentPage = name;

  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));

  document.getElementById("page" + cap(name)).classList.add("active");
  document.querySelector(`.nav-btn[data-page="${name}"]`).classList.add("active");

  if (name === "orders") loadOrders();
  if (name === "profile") loadProfile();
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/* ─────────────────── Search ─────────────────── */
function bindSearch() {
  const btn = document.getElementById("searchToggleBtn");
  const bar = document.getElementById("searchBar");
  const inp = document.getElementById("searchInput");
  const clr = document.getElementById("searchClear");

  btn.addEventListener("click", () => {
    state.searchVisible = !state.searchVisible;
    bar.style.display = state.searchVisible ? "block" : "none";
    if (state.searchVisible) inp.focus();
    else {
      inp.value = "";
      state.searchQuery = "";
      loadProducts();
    }
  });

  inp.addEventListener("input", () => {
    state.searchQuery = inp.value.trim();
    clr.style.display = state.searchQuery ? "inline" : "none";
    debounce("search", () => loadProducts(), 350);
  });

  clr.addEventListener("click", () => {
    inp.value = "";
    state.searchQuery = "";
    clr.style.display = "none";
    loadProducts();
  });
}

const _debounceTimers = {};
function debounce(key, fn, ms) {
  clearTimeout(_debounceTimers[key]);
  _debounceTimers[key] = setTimeout(fn, ms);
}

/* ─────────────────── Categories ─────────────────── */
async function loadCategories() {
  try {
    const res = await apiFetch("/mini/api/categories");
    if (!res.ok) return;
    state.categories = await res.json();
    renderChips();
  } catch (e) {
    /* silently continue */
  }
}

function renderChips() {
  const scroll = document.getElementById("chipsScroll");
  scroll.innerHTML = "";

  const all = makeChip("All", "");
  scroll.appendChild(all);

  state.categories.forEach(cat => {
    scroll.appendChild(makeChip(cat.name, cat.name));
  });
}

function makeChip(label, value) {
  const btn = document.createElement("button");
  btn.className = "chip" + (state.activeCategory === value ? " active" : "");
  btn.dataset.category = value;
  btn.textContent = label;
  btn.addEventListener("click", () => {
    state.activeCategory = value;
    document.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    loadProducts();
  });
  return btn;
}

/* ─────────────────── Products ─────────────────── */
async function loadProducts() {
  const grid = document.getElementById("productGrid");
  grid.innerHTML = `<div class="empty-state" id="gridLoader"><div class="spinner"></div><p>Loading products…</p></div>`;

  try {
    const params = new URLSearchParams();
    if (state.activeCategory) params.set("category", state.activeCategory);
    if (state.searchQuery) params.set("search", state.searchQuery);

    const res = await apiFetch(`/mini/api/products?${params}`);
    if (!res.ok) throw new Error("API error");
    state.products = await res.json();
    renderProducts();
  } catch (e) {
    grid.innerHTML = `<div class="no-results">Failed to load products. Pull to refresh.</div>`;
  }
}

function renderProducts() {
  const grid = document.getElementById("productGrid");
  if (!state.products.length) {
    grid.innerHTML = `<div class="no-results">No products found${state.searchQuery ? " for "" + state.searchQuery + """ : ""}.</div>`;
    return;
  }

  grid.innerHTML = "";
  state.products.forEach(p => grid.appendChild(makeProductCard(p)));
}

function makeProductCard(p) {
  const inCart = !!state.cart[p.name];
  const card = document.createElement("div");
  card.className = "product-card" + (p.in_stock ? "" : " out-of-stock");

  const thumbContent = p.custom_emoji_id
    ? `<span style="font-size:2.2rem">✨</span>`
    : `<span class="card-thumb-default">🛍️</span>`;

  const footerContent = p.in_stock
    ? `<button class="card-btn ${inCart ? "btn-in-cart" : ""}" data-name="${esc(p.name)}">
         ${inCart ? "In Cart ✓" : "Add"}
       </button>`
    : `<span class="out-badge">Sold out</span>`;

  card.innerHTML = `
    <div class="card-thumb">${thumbContent}</div>
    <div class="card-body">
      <div class="card-name">${esc(p.name)}</div>
      <div class="card-desc">${esc(p.description)}</div>
      <div class="card-footer">
        <span class="card-price">${formatPrice(p.price)}</span>
        ${footerContent}
      </div>
    </div>`;

  card.querySelector(".card-thumb, .card-name, .card-desc")?.addEventListener("click", () => openSheet(p));
  card.addEventListener("click", e => {
    if (e.target.closest(".card-btn")) return;
    openSheet(p);
  });

  const btn = card.querySelector(".card-btn");
  if (btn) {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      if (inCart) {
        removeFromCart(p.name);
      } else {
        addToCart(p);
      }
    });
  }

  return card;
}

/* ─────────────────── Product Sheet ─────────────────── */
function openSheet(p) {
  const overlay = document.getElementById("productSheet");
  const body = document.getElementById("sheetBody");
  const backdrop = document.getElementById("sheetBackdrop");

  const inCart = !!state.cart[p.name];

  body.innerHTML = `
    <div class="detail-emoji-row">${p.custom_emoji_id ? "✨" : "🛍️"}</div>
    <div class="detail-name">${esc(p.name)}</div>
    <div class="detail-meta">
      <span class="detail-price">${formatPrice(p.price)}</span>
      <span class="detail-stock ${p.in_stock ? "in" : "out"}">${p.in_stock ? "In Stock" : "Out of Stock"}</span>
      ${p.stock_count != null && p.in_stock ? `<span style="font-size:.72rem;color:var(--muted)">${p.stock_count} left</span>` : ""}
    </div>
    <div class="detail-desc">${esc(p.description)}</div>
    <div class="detail-actions">
      ${p.in_stock
        ? `<button class="btn-primary" id="sheetBuyBtn">Buy Now</button>
           <button class="${inCart ? "btn-secondary" : "btn-secondary"}" id="sheetCartBtn">
             ${inCart ? "Remove from Cart" : "Add to Cart"}
           </button>`
        : `<button class="btn-primary" disabled style="flex:1;opacity:.5">Out of Stock</button>`
      }
    </div>`;

  overlay.style.display = "block";
  overlay.removeAttribute("aria-hidden");

  backdrop.onclick = closeSheet;

  const buyBtn = document.getElementById("sheetBuyBtn");
  if (buyBtn) {
    buyBtn.onclick = () => {
      closeSheet();
      buyItem(p);
    };
  }

  const cartBtn = document.getElementById("sheetCartBtn");
  if (cartBtn) {
    cartBtn.onclick = () => {
      if (state.cart[p.name]) {
        removeFromCart(p.name);
        cartBtn.textContent = "Add to Cart";
      } else {
        addToCart(p);
        cartBtn.textContent = "Remove from Cart";
      }
    };
  }
}

function closeSheet() {
  const overlay = document.getElementById("productSheet");
  overlay.style.display = "none";
  overlay.setAttribute("aria-hidden", "true");
}

/* ─────────────────── Cart ─────────────────── */
function loadCart() {
  try {
    state.cart = JSON.parse(localStorage.getItem("em_cart") || "{}");
  } catch { state.cart = {}; }
}

function saveCart() {
  localStorage.setItem("em_cart", JSON.stringify(state.cart));
}

function addToCart(product) {
  state.cart[product.name] = { product };
  saveCart();
  updateCartBadge();
  showToast(`"${product.name}" added to cart`);
  renderProducts();
}

function removeFromCart(name) {
  delete state.cart[name];
  saveCart();
  updateCartBadge();
  renderProducts();
  renderCart();
}

function updateCartBadge() {
  const count = Object.keys(state.cart).length;
  const badge = document.getElementById("cartBadge");
  if (count > 0) {
    badge.textContent = count;
    badge.style.display = "flex";
  } else {
    badge.style.display = "none";
  }
}

function renderCart() {
  const list = document.getElementById("cartList");
  const summary = document.getElementById("cartSummary");
  const items = Object.values(state.cart);

  if (!items.length) {
    list.innerHTML = `<div class="cart-empty"><div class="cart-empty-icon">🛒</div><p>Your cart is empty.<br>Browse the shop to add items.</p></div>`;
    summary.style.display = "none";
    return;
  }

  list.innerHTML = "";
  let total = 0;

  items.forEach(({ product: p }) => {
    total += p.price;
    const row = document.createElement("div");
    row.className = "cart-item";
    row.innerHTML = `
      <div class="cart-item-icon">${p.custom_emoji_id ? "✨" : "🛍️"}</div>
      <div class="cart-item-info">
        <div class="cart-item-name">${esc(p.name)}</div>
        <div class="cart-item-price">${formatPrice(p.price)}</div>
      </div>
      <div class="cart-item-actions">
        <button class="btn-buy-item" data-name="${esc(p.name)}">Buy</button>
        <button class="btn-remove-item" data-name="${esc(p.name)}">✕</button>
      </div>`;

    row.querySelector(".btn-buy-item").onclick = () => buyItem(p);
    row.querySelector(".btn-remove-item").onclick = () => removeFromCart(p.name);
    list.appendChild(row);
  });

  document.getElementById("cartSubtotal").textContent = formatPrice(total);
  summary.style.display = "block";

  document.getElementById("checkoutAllBtn").onclick = checkoutAll;
}

async function checkoutAll() {
  const items = Object.values(state.cart);
  if (!items.length) return;

  for (const { product } of items) {
    const ok = await buyItem(product, true);
    if (!ok) break;
  }
}

/* ─────────────────── Buy flow ─────────────────── */
async function buyItem(product, silent = false) {
  if (!tg?.initData) {
    showToast("Open this app from the Telegram bot");
    return false;
  }

  try {
    const res = await apiFetch("/mini/api/buy", {
      method: "POST",
      body: JSON.stringify({ item_name: product.name }),
    });

    const data = await res.json();

    if (res.ok && data.ok) {
      removeFromCart(product.name);
      if (!silent) showPurchaseResult(data.data);
      else showToast(`✓ Purchased: ${product.name}`);
      return true;
    }

    if (res.status === 402) {
      if (!silent) openTopUpSheet(product.price);
      else showToast("Insufficient balance — add funds in Profile");
      return false;
    }

    showToast(data.error || "Purchase failed");
    return false;

  } catch (e) {
    showToast("Network error. Please try again.");
    return false;
  }
}

function showPurchaseResult(data) {
  const overlay = document.getElementById("productSheet");
  const body = document.getElementById("sheetBody");
  const backdrop = document.getElementById("sheetBackdrop");

  body.innerHTML = `
    <div class="purchase-result">
      <div class="result-icon">🎉</div>
      <div class="result-title">Purchase Complete!</div>
      <div style="font-size:.82rem;color:var(--muted);margin-bottom:10px">${esc(data.item_name)}</div>
      <div class="result-value" title="Tap to copy">${esc(data.value || "—")}</div>
      <div class="result-hint">Tap the value above to copy it.</div>
      <div style="margin-top:16px;font-size:.8rem;color:var(--muted)">New balance: ${formatPrice(data.new_balance)}</div>
      <button class="btn-primary" style="margin-top:16px;width:100%" id="closeResultBtn">Done</button>
    </div>`;

  overlay.style.display = "block";
  overlay.removeAttribute("aria-hidden");
  backdrop.onclick = closeSheet;
  document.getElementById("closeResultBtn").onclick = closeSheet;

  const valDiv = body.querySelector(".result-value");
  if (valDiv) {
    valDiv.onclick = () => {
      navigator.clipboard?.writeText(data.value || "").then(() => showToast("Copied!")).catch(() => {});
    };
  }

  if (state.user) {
    state.user.balance = data.new_balance;
    updateBalanceDisplay();
  }
}

/* ─────────────────── Top-up Sheet ─────────────────── */
function openTopUpSheet(suggestedAmount = null) {
  const overlay = document.getElementById("productSheet");
  const body = document.getElementById("sheetBody");
  const backdrop = document.getElementById("sheetBackdrop");

  const presets = [5, 10, 20, 50, 100];
  const defaultAmt = suggestedAmount ? Math.ceil(suggestedAmount) : 10;

  body.innerHTML = `
    <div class="topup-sheet">
      <div class="topup-title">Add Balance</div>
      <div class="topup-sub">Top up your Evrest Market balance with Telegram Stars.</div>
      <div class="amount-grid">
        ${presets.map(v => `<button class="amount-chip${v === defaultAmt ? " selected" : ""}" data-val="${v}">${v} ${state.user?.currency || ""}</button>`).join("")}
      </div>
      <div class="amount-input-row">
        <input type="number" class="amount-input" id="topupAmount" value="${defaultAmt}" min="1" placeholder="Amount" />
        <span style="color:var(--muted);font-size:.88rem">${state.user?.currency || ""}</span>
      </div>
      <button class="btn-primary full-width" id="topupConfirm">Pay with Stars ⭐</button>
    </div>`;

  overlay.style.display = "block";
  overlay.removeAttribute("aria-hidden");
  backdrop.onclick = closeSheet;

  const amtInput = document.getElementById("topupAmount");

  body.querySelectorAll(".amount-chip").forEach(chip => {
    chip.onclick = () => {
      body.querySelectorAll(".amount-chip").forEach(c => c.classList.remove("selected"));
      chip.classList.add("selected");
      amtInput.value = chip.dataset.val;
    };
  });

  document.getElementById("topupConfirm").onclick = async () => {
    const amount = parseFloat(amtInput.value);
    if (!amount || amount <= 0) { showToast("Enter a valid amount"); return; }
    await doTopUp(amount);
  };
}

async function doTopUp(amount) {
  const btn = document.getElementById("topupConfirm");
  if (btn) { btn.disabled = true; btn.textContent = "Creating invoice…"; }

  try {
    const res = await apiFetch("/mini/api/topup", {
      method: "POST",
      body: JSON.stringify({ amount }),
    });
    const data = await res.json();

    if (res.ok && data.invoice_url) {
      closeSheet();
      if (tg?.openInvoice) {
        tg.openInvoice(data.invoice_url, status => {
          if (status === "paid") {
            showToast("Payment successful! Balance will update shortly.");
            setTimeout(loadProfile, 3000);
          }
        });
      } else {
        window.open(data.invoice_url, "_blank");
      }
    } else {
      showToast(data.error || "Failed to create invoice");
      if (btn) { btn.disabled = false; btn.textContent = "Pay with Stars ⭐"; }
    }
  } catch (e) {
    showToast("Network error. Please try again.");
    if (btn) { btn.disabled = false; btn.textContent = "Pay with Stars ⭐"; }
  }
}

/* ─────────────────── Orders ─────────────────── */
async function loadOrders() {
  const list = document.getElementById("ordersList");
  list.innerHTML = `<div class="empty-state"><div class="spinner"></div><p>Loading orders…</p></div>`;

  if (!tg?.initData) {
    list.innerHTML = `<div class="empty-state"><p>Open this app from the Telegram bot to view orders.</p></div>`;
    return;
  }

  try {
    const res = await apiFetch("/mini/api/orders");
    if (res.status === 401) {
      list.innerHTML = `<div class="empty-state"><p>Start the bot first, then come back.</p></div>`;
      return;
    }
    if (!res.ok) throw new Error();
    state.orders = await res.json();
    renderOrders();
  } catch {
    list.innerHTML = `<div class="empty-state"><p>Failed to load orders.</p></div>`;
  }
}

function renderOrders() {
  const list = document.getElementById("ordersList");
  if (!state.orders.length) {
    list.innerHTML = `<div class="empty-state"><p>No orders yet.</p></div>`;
    return;
  }

  list.innerHTML = "";
  state.orders.forEach(o => {
    const card = document.createElement("div");
    card.className = "order-card";
    card.innerHTML = `
      <div class="order-header">
        <div class="order-name">${esc(o.item_name)}</div>
        <div class="order-price">${formatPrice(o.price)}</div>
      </div>
      <div class="order-date">${formatDate(o.bought_at)}</div>
      ${o.value ? `<div class="order-value-preview">${esc(o.value)}</div>` : ""}`;

    if (o.value) {
      card.addEventListener("click", () => card.classList.toggle("expanded"));
    }
    list.appendChild(card);
  });
}

/* ─────────────────── Profile ─────────────────── */
function bindProfile() {
  document.getElementById("darkToggle").addEventListener("change", e => {
    setDark(e.target.checked);
  });

  document.getElementById("addBalanceBtn").addEventListener("click", () => {
    openTopUpSheet();
  });
}

async function loadProfile() {
  if (!tg?.initData) {
    const user = tg?.initDataUnsafe?.user;
    if (user) setProfileUI({ first_name: user.first_name, username: user.username, balance: null });
    return;
  }

  try {
    const res = await apiFetch("/mini/api/user");
    if (!res.ok) {
      const user = tg?.initDataUnsafe?.user;
      if (user) setProfileUI({ first_name: user.first_name, username: user.username, balance: null });
      return;
    }
    state.user = await res.json();
    setProfileUI(state.user);
  } catch {
    /* ignore */
  }
}

function setProfileUI(user) {
  const nameEl = document.getElementById("profileName");
  const handleEl = document.getElementById("profileHandle");
  const avatarEl = document.getElementById("profileAvatar");
  const balEl = document.getElementById("balanceVal");

  nameEl.textContent = user.first_name || "User";
  handleEl.textContent = user.username ? `@${user.username}` : "";
  avatarEl.textContent = (user.first_name || "U")[0].toUpperCase();

  if (user.balance != null) {
    balEl.textContent = formatPrice(user.balance);
  } else {
    balEl.textContent = "Start the bot to view balance";
    balEl.style.fontSize = ".9rem";
  }
}

function updateBalanceDisplay() {
  if (state.user != null) {
    document.getElementById("balanceVal").textContent = formatPrice(state.user.balance);
  }
}

/* ─────────────────── When cart page shown ─────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelector(".nav-btn[data-page='cart']").addEventListener("click", () => {
    setTimeout(renderCart, 50);
  });
});

/* ─────────────────── Toast ─────────────────── */
let _toastTimer;
function showToast(msg) {
  const toast = document.getElementById("toast");
  toast.textContent = msg;
  toast.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
}

/* ─────────────────── Helpers ─────────────────── */
function esc(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatPrice(amount) {
  const currency = state.user?.currency || "";
  return `${parseFloat(amount).toFixed(2)} ${currency}`.trim();
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  } catch { return iso; }
}
