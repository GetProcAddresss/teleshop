import { openSheet, closeSheet, escapeHtml, fmtMoney, emojiFor, toast } from "../ui.js";
import { addToCart, state } from "../state.js";
import { api } from "../api.js";
import { haptic, showMainButton, hideMainButton } from "../tg.js";

export function openProductDetail(p) {
  const inStock = !!p.in_stock;
  const stockTag = p.stock_count == null && inStock
    ? `<span class="tag tag-in">In stock</span>`
    : inStock
      ? `<span class="tag tag-stock">${p.stock_count} left</span>`
      : `<span class="tag tag-out">Out of stock</span>`;

  const html = `
    <div class="detail-thumb">${
      p.image_url
        ? `<img class="thumb-img" src="${escapeHtml(p.image_url)}" alt="${escapeHtml(p.name)}" />`
        : emojiFor(p.name)
    }</div>
    <h2 class="detail-name">${escapeHtml(p.name)}</h2>
    <div class="detail-meta">
      <span class="detail-price">${fmtMoney(p.price)}</span>
      ${stockTag}
    </div>
    <div class="detail-desc">${escapeHtml(p.description || "No description")}</div>
    <div class="detail-actions">
      <button class="btn btn-secondary" data-act="cart" ${inStock ? "" : "disabled"}>Add to cart</button>
      <button class="btn btn-primary" data-act="buy" ${inStock ? "" : "disabled"}>Buy now</button>
    </div>`;

  openSheet(html, { onClose: hideMainButton });

  document.querySelector('[data-act="cart"]')?.addEventListener("click", () => {
    addToCart(p);
    toast(`Added "${p.name}" to cart`, "success", 1600);
    closeSheet();
  });
  document.querySelector('[data-act="buy"]')?.addEventListener("click", () => purchase(p));

  showMainButton({
    text: inStock ? `Buy for ${fmtMoney(p.price)}` : "Out of stock",
    onClick: () => inStock && purchase(p),
  });
}

async function purchase(p) {
  haptic("light");
  const btn = document.querySelector('[data-act="buy"]');
  if (btn) { btn.disabled = true; btn.textContent = "Processing…"; }
  const res = await api.buy(p.name);
  if (res.ok) {
    haptic("success");
    showResult(p, res.data?.data);
  } else {
    haptic("error");
    const msg = res.data?.error || "Purchase failed";
    toast(msg, "error", 3200);
    if (btn) { btn.disabled = false; btn.textContent = "Buy now"; }
  }
}

function showResult(p, data) {
  const value = data?.value ?? "";
  const newBalance = data?.new_balance;
  const html = `
    <div class="result-wrap">
      <div class="result-icon">✅</div>
      <div class="result-title">Purchase complete</div>
      <div class="result-sub">Your "${escapeHtml(p.name)}" is ready</div>
      ${value ? `<div class="result-value" id="resVal" title="Tap to copy">${escapeHtml(value)}</div>
                 <div class="result-hint">Tap to copy</div>` : ""}
      ${newBalance != null ? `<div class="result-balance">New balance: <strong>${fmtMoney(newBalance)}</strong></div>` : ""}
      <button class="btn btn-primary btn-block" data-close>Done</button>
    </div>`;
  openSheet(html, { onClose: hideMainButton });
  hideMainButton();
  document.querySelector("[data-close]")?.addEventListener("click", () => closeSheet());
  document.getElementById("resVal")?.addEventListener("click", () => {
    navigator.clipboard?.writeText(value).then(() => toast("Copied", "success", 1200));
  });
}
