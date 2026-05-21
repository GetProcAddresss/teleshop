import { api } from "../api.js";
import { state } from "../state.js";
import { escapeHtml, fmtMoney, fmtDate, toast } from "../ui.js";

export async function loadOrders() {
  const list = document.getElementById("ordersList");
  if (!list) return;
  list.innerHTML = `<div class="empty-state"><div class="empty-icon">⏳</div><div class="empty-title">Loading…</div></div>`;

  const res = await api.orders();
  if (!res.ok) {
    if (res.status === 401) {
      list.innerHTML = signinHtml();
    } else {
      list.innerHTML = `<div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <div class="empty-title">Couldn't load orders</div>
        <p class="empty-text">${escapeHtml(res.data?.error || "Try again later")}</p>
        <button class="btn btn-primary" data-retry>Retry</button>
      </div>`;
      list.querySelector("[data-retry]")?.addEventListener("click", loadOrders);
    }
    return;
  }
  state.orders = res.data || [];
  render();
}

function render() {
  const list = document.getElementById("ordersList");
  if (!state.orders.length) {
    list.innerHTML = `<div class="empty-state">
      <div class="empty-icon">📭</div>
      <div class="empty-title">No orders yet</div>
      <p class="empty-text">Your purchases will appear here.</p>
    </div>`;
    return;
  }
  // Group by date (today / yesterday / earlier)
  const groups = { Today: [], Yesterday: [], Earlier: [] };
  const now = new Date();
  const tKey = now.toDateString();
  const yKey = new Date(now.getTime() - 86400000).toDateString();
  state.orders.forEach(o => {
    const d = o.bought_at ? new Date(o.bought_at) : null;
    const k = d ? d.toDateString() : "";
    if (k === tKey) groups.Today.push(o);
    else if (k === yKey) groups.Yesterday.push(o);
    else groups.Earlier.push(o);
  });

  let html = "";
  for (const [label, items] of Object.entries(groups)) {
    if (!items.length) continue;
    html += `<div class="orders-group-title">${label}</div>`;
    html += items.map(orderCard).join("");
  }
  list.innerHTML = html;

  list.querySelectorAll(".order-card").forEach(c => {
    c.addEventListener("click", () => c.classList.toggle("is-expanded"));
    c.querySelector(".order-value-wrap")?.addEventListener("click", (e) => {
      e.stopPropagation();
      const text = e.currentTarget.dataset.val || "";
      navigator.clipboard?.writeText(text).then(() => toast("Copied", "success", 1200));
    });
  });
}

function orderCard(o) {
  return `<div class="order-card">
    <div class="order-header">
      <div>
        <div class="order-name">${escapeHtml(o.item_name)}</div>
        <div class="order-date">${escapeHtml(fmtDate(o.bought_at))}</div>
      </div>
      <span class="order-price">${fmtMoney(o.price)}</span>
    </div>
    ${o.value ? `<div class="order-value-wrap" data-val="${escapeHtml(o.value)}">${escapeHtml(o.value)}<span class="copy-hint">Tap to copy</span></div>` : ""}
  </div>`;
}

function signinHtml() {
  return `<div class="empty-state">
    <div class="empty-icon">🔐</div>
    <div class="empty-title">Open inside Telegram</div>
    <p class="empty-text">Sign-in is automatic when you launch this app from the Telegram bot.</p>
  </div>`;
}
