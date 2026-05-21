import { state, removeFromCart, cartTotal, cartCount, saveCart } from "../state.js";
import { escapeHtml, fmtMoney, emojiFor, toast } from "../ui.js";
import { api } from "../api.js";
import { haptic, showMainButton, hideMainButton } from "../tg.js";

export function renderCart() {
  const list = document.getElementById("cartList");
  const summary = document.getElementById("cartSummary");
  const sub = document.getElementById("cartSubtotal");
  if (!list || !summary) return;

  const items = Object.entries(state.cart);
  if (!items.length) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🛒</div>
        <div class="empty-title">Your cart is empty</div>
        <p class="empty-text">Browse the shop and tap "Add" to start a cart.</p>
      </div>`;
    summary.hidden = true;
    hideMainButton();
    return;
  }
  list.innerHTML = items.map(([key, it]) => `
    <div class="cart-item">
      <div class="cart-item-icon">${emojiFor(it.product.name)}</div>
      <div class="cart-item-info">
        <div class="cart-item-name">${escapeHtml(it.product.name)}${it.qty > 1 ? ` × ${it.qty}` : ""}</div>
        <div class="cart-item-price">${fmtMoney(it.product.price * it.qty)}</div>
      </div>
      <div class="cart-item-actions">
        <button class="btn-icon-sm" data-rm="${escapeHtml(key)}" aria-label="Remove">✕</button>
      </div>
    </div>`).join("");

  list.querySelectorAll("[data-rm]").forEach(btn => {
    btn.addEventListener("click", () => {
      removeFromCart(btn.dataset.rm);
      renderCart();
    });
  });

  sub.textContent = fmtMoney(cartTotal());
  summary.hidden = false;

  showMainButton({
    text: `Checkout • ${fmtMoney(cartTotal())}`,
    onClick: checkoutAll,
  });
}

export function bindCart() {
  document.getElementById("checkoutAllBtn")?.addEventListener("click", checkoutAll);
  document.addEventListener("cart:change", () => {
    if (state.currentPage === "cart") renderCart();
  });
}

async function checkoutAll() {
  const items = Object.entries(state.cart);
  if (!items.length) return;
  haptic("medium");
  const btn = document.getElementById("checkoutAllBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Processing…"; }

  let ok = 0, fail = 0; let lastErr = "";
  for (const [key, it] of items) {
    for (let i = 0; i < it.qty; i++) {
      const res = await api.buy(it.product.name);
      if (res.ok) ok++;
      else { fail++; lastErr = res.data?.error || "Failed"; }
    }
  }

  if (ok) {
    state.cart = {};
    saveCart();
    document.dispatchEvent(new Event("cart:cleared"));
    renderCart();
    toast(fail ? `${ok} ok, ${fail} failed: ${lastErr}` : `Bought ${ok} item${ok > 1 ? "s" : ""}`, fail ? "info" : "success", 3000);
    haptic(fail ? "warning" : "success");
  } else {
    toast(lastErr || "Checkout failed", "error", 3000);
    haptic("error");
    if (btn) { btn.disabled = false; btn.textContent = "Checkout All"; }
  }
}
