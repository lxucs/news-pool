// 应用状态，以及所有与 API 交互的操作。组件读取 `store`、调用这里的函数；
// 除此之外没有别的地方修改状态。
import { reactive } from "./vendor/vue.esm-browser.prod.js";
import { api, ServerGone } from "./api.js";
import { emptyRoute, parseHash, toHash } from "./router.js";

export const DAY_VIEWS = ["latest", "unread"]; // 按日期分组显示的视图
const LIST_KEYS = ["view", "cid", "run", "q", "category", "tag", "source"];
const TOAST_MS = 5000;
const PREFETCH_ROWS = 5; // 用 j / k 选到已加载行的末尾附近时，加载下一页
const THEME_KEY = "news-viewer-theme";

export const store = reactive({
  meta: null,
  route: emptyRoute(),
  items: [],
  total: 0,
  loading: false,
  current: null, // 当前打开的条目：{item, missing, state, cids}
  serverDown: false,
  toast: null, // {text, undo, at}
  menuOpen: false, // 阅读栏的收藏夹菜单
  drawerOpen: false, // 窄屏下的导航抽屉
  helpOpen: false,
});

let listToken = 0; // 一旦发出更新的列表请求，之前请求的响应就作废

export function showToast(text, undo = null) {
  const at = Date.now();
  store.toast = { text, undo, at };
  setTimeout(() => {
    if (store.toast && store.toast.at === at) store.toast = null;
  }, TOAST_MS);
}

function fail(err) {
  if (err instanceof ServerGone) store.serverDown = true;
  else showToast(`出错了：${err.message}`);
}

export async function refreshMeta() {
  try {
    store.meta = await api.meta();
    store.serverDown = false;
  } catch (err) {
    fail(err);
  }
}

export async function loadItems(reset) {
  if (!reset && (store.loading || store.items.length >= store.total)) return;
  const token = ++listToken;
  const r = store.route;
  store.loading = true;
  try {
    const page = await api.items({
      view: r.view,
      cid: r.view === "collection" ? r.cid : "",
      run: r.run,
      q: r.q,
      category: r.category,
      tag: r.tag,
      source: r.source,
      offset: reset ? 0 : store.items.length,
      limit: store.meta ? store.meta.settings.page_size : "",
    });
    if (token !== listToken) return;
    store.items = reset ? page.items : store.items.concat(page.items);
    store.total = page.total;
  } catch (err) {
    if (token === listToken) fail(err);
  } finally {
    if (token === listToken) store.loading = false;
  }
}

export function navigate(changes) {
  window.location.hash = toHash({ ...store.route, ...changes });
}

export async function applyHash() {
  const next = parseHash(window.location.hash);
  const listChanged = LIST_KEYS.some((key) => next[key] !== store.route[key]);
  store.route = next;
  if (listChanged || !store.items.length) await loadItems(true);
  const openId = store.current ? store.current.item.id : "";
  if (next.item !== openId) await openCurrent(next.item);
}

async function openCurrent(id) {
  store.menuOpen = false;
  if (!id) {
    store.current = null;
    return;
  }
  try {
    const detail = await api.item(id);
    if (store.route.item !== id) return; // 加载期间用户已经切到别处
    store.current = detail;
    if (!detail.state.read_at) await setFlags({ read: true });
  } catch (err) {
    store.current = null;
    fail(err);
  }
}

export function openItem(id) {
  store.drawerOpen = false;
  navigate({ item: id });
}

export function closeItem() {
  navigate({ item: "" });
}

export function step(delta) {
  const rows = store.items;
  if (!rows.length) return;
  const index = rows.findIndex((row) => row.id === store.route.item);
  const next = index === -1 ? 0 : Math.min(Math.max(index + delta, 0), rows.length - 1);
  openItem(rows[next].id);
  if (next >= rows.length - PREFETCH_ROWS) loadItems(false);
}

function patchRow(id, state) {
  const row = store.items.find((r) => r.id === id);
  if (!row) return;
  row.starred = Boolean(state.starred_at);
  row.read = Boolean(state.read_at);
  row.hidden = Boolean(state.hidden_at);
  row.has_note = Boolean(state.note);
}

async function setFlags(flags) {
  const cur = store.current;
  if (!cur) return false;
  const id = cur.item.id;
  try {
    const state = await api.setState(id, flags);
    if (store.current && store.current.item.id === id) store.current.state = state;
    patchRow(id, state);
    refreshMeta();
    return true;
  } catch (err) {
    fail(err);
    return false;
  }
}

export function toggleStar() {
  if (store.current) setFlags({ starred: !store.current.state.starred_at });
}

export function toggleRead() {
  if (store.current) setFlags({ read: !store.current.state.read_at });
}

function dropRow(id) {
  const index = store.items.findIndex((r) => r.id === id);
  if (index === -1) return;
  const neighbour = store.items[index + 1] || store.items[index - 1];
  store.items.splice(index, 1);
  store.total -= 1;
  navigate({ item: neighbour ? neighbour.id : "" });
}

export async function toggleHide() {
  const cur = store.current;
  if (!cur) return;
  const id = cur.item.id;
  const hiding = !cur.state.hidden_at;
  if (!(await setFlags({ hidden: hiding }))) return;
  const leavesView = hiding ? DAY_VIEWS.includes(store.route.view) : store.route.view === "hidden";
  if (leavesView) dropRow(id);
  if (!hiding) return;
  showToast("已隐藏（不感兴趣）", async () => {
    try {
      await api.setState(id, { hidden: false });
      await loadItems(true);
      refreshMeta();
      navigate({ item: id });
    } catch (err) {
      fail(err);
    }
  });
}

export async function markDayRead(day) {
  try {
    await api.markRead({ fetch_day: day });
    for (const row of store.items) if (row.fetch_day === day) row.read = true;
    refreshMeta();
  } catch (err) {
    fail(err);
  }
}

export async function saveNote(id, note) {
  // 出错时交给调用方处理：笔记编辑器显示「保存失败」并保留文本。
  const state = await api.setNote(id, note);
  if (store.current && store.current.item.id === id) store.current.state = state;
  patchRow(id, state);
  refreshMeta();
}

export async function toggleCollection(cid) {
  const cur = store.current;
  if (!cur) return;
  const id = cur.item.id;
  const inside = cur.cids.includes(cid);
  try {
    if (inside) await api.uncollect(cid, id);
    else await api.collect(cid, id);
    cur.cids = inside ? cur.cids.filter((c) => c !== cid) : cur.cids.concat([cid]);
    refreshMeta();
  } catch (err) {
    fail(err);
  }
}

export async function createCollection(name, addCurrent) {
  try {
    const created = await api.createCollection(name);
    if (addCurrent && store.current) {
      await api.collect(created.cid, store.current.item.id);
      store.current.cids = store.current.cids.concat([created.cid]);
    }
    await refreshMeta();
    return created;
  } catch (err) {
    if (err.status === 409) showToast(`已有名为「${name}」的收藏夹`);
    else fail(err);
    return null;
  }
}

export async function renameCollection(cid, name) {
  try {
    await api.updateCollection(cid, { name });
    await refreshMeta();
  } catch (err) {
    if (err.status === 409) showToast(`已有名为「${name}」的收藏夹`);
    else fail(err);
  }
}

export async function deleteCollection(cid) {
  try {
    await api.deleteCollection(cid);
    if (store.current) store.current.cids = store.current.cids.filter((c) => c !== cid);
    if (store.route.view === "collection" && store.route.cid === cid) {
      navigate({ view: "latest", cid: null, item: "" });
    }
    await refreshMeta();
  } catch (err) {
    fail(err);
  }
}

async function ping() {
  try {
    await api.health();
    store.serverDown = false;
  } catch (err) {
    if (err instanceof ServerGone) store.serverDown = true;
  }
}

export function startHeartbeat(seconds) {
  // 只有可见的页面才维持服务运行；忘在后台的标签页不算，服务会照常空闲退出。
  setInterval(() => {
    if (document.visibilityState === "visible") ping();
  }, seconds * 1000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") ping();
  });
}

export function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved) document.documentElement.dataset.theme = saved;
}

export function toggleTheme() {
  const root = document.documentElement;
  const dark = root.dataset.theme
    ? root.dataset.theme === "dark"
    : window.matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  localStorage.setItem(THEME_KEY, root.dataset.theme);
}
