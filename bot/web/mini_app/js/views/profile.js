import { api } from "../api.js";
import { state } from "../state.js";
import { escapeHtml, fmtMoney, openSheet, closeSheet, toast } from "../ui.js";
import { haptic, tg } from "../tg.js";

export async function loadProfile() {
  const name = document.getElementById("profileName");
  const handle = document.getElementById("profileHandle");
  const avatar = document.getElementById("profileAvatar");
  const bal = document.getElementById("balanceVal");

  const res = await api.user();
  if (!res.ok) {
    if (name) name.textContent = "Guest";
    if (handle) handle.textContent = "Open inside Telegram to sign in";
    if (avatar) avatar.textContent = "?";
    if (bal) bal.textContent = "—";
    return;
  }
  state.user = res.data;
  const u = res.data;
  if (name) name.textContent = u.first_name || "User";
  if (handle) handle.textContent = u.username ? "@" + u.username : "";
  if (avatar) avatar.textContent = (u.first_name?.[0] || "U").toUpperCase();
  if (bal) bal.textContent = fmtMoney(u.balance, u.currency);
}

export function bindProfile() {
  document.getElementById("addBalanceBtn")?.addEventListener("click", openTopup);
}

function openTopup() {
  if (!state.user) { toast("Open inside Telegram to top up", "error"); return; }
  haptic("light");
  const cur = state.user.currency || "USD";
  const presets = [100, 500, 1000, 2000, 5000, 10000];
  const html = `
    <div class="topup-title">Top up balance</div>
    <p class="topup-sub">Pay with Telegram Stars. The amount converts to your balance currency.</p>
    <div class="amount-grid">
      ${presets.map(a => `<button class="amount-chip" data-amt="${a}">${a}</button>`).join("")}
    </div>
    <div class="input-row">
      <input id="topupAmt" type="number" inputmode="numeric" min="1" placeholder="Custom amount" />
      <span class="input-suffix">${escapeHtml(cur)}</span>
    </div>
    <button class="btn btn-primary btn-block" id="topupGo">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M12 2l2.5 7.5H22l-6 4.5 2.5 8L12 17l-6.5 5L8 14 2 9.5h7.5z"/></svg>
      Pay with Stars
    </button>`;
  openSheet(html);

  document.querySelectorAll(".amount-chip").forEach(c => {
    c.addEventListener("click", () => {
      document.querySelectorAll(".amount-chip").forEach(x => x.classList.remove("is-active"));
      c.classList.add("is-active");
      document.getElementById("topupAmt").value = c.dataset.amt;
    });
  });
  document.getElementById("topupGo")?.addEventListener("click", submitTopup);
}

async function submitTopup() {
  const input = document.getElementById("topupAmt");
  const amount = Number(input?.value || 0);
  if (!amount || amount < 1) { toast("Enter a valid amount", "error"); return; }
  const btn = document.getElementById("topupGo");
  if (btn) { btn.disabled = true; btn.textContent = "Creating invoice…"; }

  const res = await api.topup(amount);
  if (!res.ok) {
    toast(res.data?.error || "Failed", "error", 3000);
    haptic("error");
    if (btn) { btn.disabled = false; btn.textContent = "Pay with Stars"; }
    return;
  }
  closeSheet();
  haptic("success");
  const link = res.data?.invoice_url;
  if (tg && typeof tg.openInvoice === "function" && link) {
    tg.openInvoice(link, (status) => {
      if (status === "paid") {
        toast("Payment received — balance updated", "success", 2400);
        loadProfile();
      } else if (status === "failed" || status === "cancelled") {
        toast("Payment " + status, "error", 2400);
      }
    });
  } else if (link) {
    window.open(link, "_blank");
  }
}
