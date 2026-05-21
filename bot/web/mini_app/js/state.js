const CART_KEY = "em_cart_v2";

export const state = {
  products: [],
  categories: [],
  activeCategory: "",
  searchQuery: "",
  cart: {},
  user: null,
  orders: [],
  currentPage: "shop",
  searchVisible: false,
  pendingProductId: null,
};

const _subs = new Set();
export function subscribe(fn) { _subs.add(fn); return () => _subs.delete(fn); }
export function emit(evt, payload) { _subs.forEach(fn => fn(evt, payload)); }

export function loadCart() {
  try {
    const raw = localStorage.getItem(CART_KEY);
    state.cart = raw ? JSON.parse(raw) : {};
  } catch { state.cart = {}; }
}
export function saveCart() {
  try { localStorage.setItem(CART_KEY, JSON.stringify(state.cart)); } catch {}
  emit("cart:change");
}
export function cartCount() {
  return Object.values(state.cart).reduce((s, it) => s + (it.qty || 0), 0);
}
export function cartTotal() {
  return Object.values(state.cart).reduce((s, it) => s + (it.product?.price || 0) * (it.qty || 0), 0);
}
export function addToCart(product) {
  const key = product.name;
  if (!state.cart[key]) state.cart[key] = { product, qty: 0 };
  state.cart[key].qty += 1;
  saveCart();
}
export function removeFromCart(key) {
  delete state.cart[key];
  saveCart();
}
