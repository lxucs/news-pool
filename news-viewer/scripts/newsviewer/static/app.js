// 入口：挂载应用、跟随 URL hash、快捷键、心跳。
import { createApp } from "./vendor/vue.esm-browser.prod.js";
import AppRoot from "./components/app-root.js";
import {
  applyHash,
  closeItem,
  initTheme,
  refreshMeta,
  startHeartbeat,
  step,
  store,
  toggleHide,
  toggleRead,
  toggleStar,
} from "./store.js";
import { safeUrl } from "./util.js";

function typing(target) {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

function openOriginal() {
  const url = store.current && safeUrl((store.current.item.source || {}).url);
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}

function escape() {
  if (store.helpOpen) store.helpOpen = false;
  else if (store.menuOpen) store.menuOpen = false;
  else if (store.drawerOpen) store.drawerOpen = false;
  else closeItem();
}

const KEYS = {
  j: () => step(1),
  k: () => step(-1),
  o: openOriginal,
  s: toggleStar,
  h: toggleHide,
  m: toggleRead,
  c: () => {
    if (store.current) store.menuOpen = !store.menuOpen;
  },
  n: () => document.querySelector(".note textarea")?.focus(),
  "/": () => document.getElementById("search")?.focus(),
  "?": () => {
    store.helpOpen = !store.helpOpen;
  },
  Escape: escape,
};

function onKey(event) {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (typing(event.target)) {
    if (event.key === "Escape") event.target.blur();
    return;
  }
  const action = KEYS[event.key];
  if (!action) return;
  event.preventDefault();
  action();
}

async function main() {
  initTheme();
  createApp(AppRoot).mount("#app");
  window.addEventListener("hashchange", applyHash);
  window.addEventListener("keydown", onKey);
  await refreshMeta();
  await applyHash();
  if (store.meta) startHeartbeat(store.meta.settings.heartbeat_s);
}

main();
