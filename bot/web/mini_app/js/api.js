import { tg } from "./tg.js";

const BASE = "";
const TIMEOUT_MS = 10000;
const _etagCache = new Map();

function headers(isPost = false, extra = {}) {
  const h = { ...extra };
  if (isPost) h["Content-Type"] = "application/json";
  if (tg?.initData) h["X-Telegram-Init-Data"] = tg.initData;
  return h;
}

async function request(path, { method = "GET", body, etag = false, signal } = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  const sig = signal || ctrl.signal;
  const opts = { method, headers: headers(method !== "GET", etag && _etagCache.has(path) ? { "If-None-Match": _etagCache.get(path).etag } : {}), signal: sig };
  if (body !== undefined) opts.body = JSON.stringify(body);

  try {
    const res = await fetch(BASE + path, opts);
    if (etag && res.status === 304 && _etagCache.has(path)) {
      return { ok: true, status: 200, data: _etagCache.get(path).data, cached: true };
    }
    let data = null;
    try { data = await res.json(); } catch {}
    if (etag && res.ok) {
      const e = res.headers.get("etag");
      if (e) _etagCache.set(path, { etag: e, data });
    }
    return { ok: res.ok, status: res.status, data };
  } catch (e) {
    if (e.name === "AbortError") return { ok: false, status: 0, data: { error: "Timeout" }, timeout: true };
    return { ok: false, status: 0, data: { error: e.message || "Network" }, network: true };
  } finally {
    clearTimeout(t);
  }
}

export const api = {
  health: () => request("/mini/api/health"),
  categories: () => request("/mini/api/categories", { etag: true }),
  products: (params = {}) => {
    const qs = new URLSearchParams();
    if (params.category) qs.set("category", params.category);
    if (params.search) qs.set("search", params.search);
    const q = qs.toString();
    return request(`/mini/api/products${q ? "?" + q : ""}`, { etag: true });
  },
  user: () => request("/mini/api/user"),
  orders: () => request("/mini/api/orders"),
  topup: (amount) => request("/mini/api/topup", { method: "POST", body: { amount } }),
  buy: (item_name) => request("/mini/api/buy", { method: "POST", body: { item_name } }),
};
