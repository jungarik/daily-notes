// Telegram Mini App integration (no-op in a plain browser).
export const tg = (typeof window !== "undefined" && window.Telegram && window.Telegram.WebApp) || null;
export let INIT_DATA = "";

export function initTelegram() {
  if (!tg) return;
  try {
    tg.ready();
    tg.expand();
    tg.setHeaderColor && tg.setHeaderColor("#191919");
    tg.setBackgroundColor && tg.setBackgroundColor("#1e1e1e");
    INIT_DATA = tg.initData || "";
  } catch (e) { /* ignore */ }
}

export function haptic() {
  try { tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged(); } catch (e) {}
}
