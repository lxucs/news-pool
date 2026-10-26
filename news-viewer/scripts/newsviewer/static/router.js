// URL hash 记录屏幕上显示的内容，所以任何视图都能加书签，`nv.py up --run` 也能给出直达链接。
// 规范形式：#/v/<view>?run=&q=&category=&tag=&source=&item=，收藏夹则是 #/c/<cid>?…；
// 也接受 #/run/<run_id> 和 #/item/<id> 这样的短链接。
// 不用 URLSearchParams：tests/viewer_js_check.js 在裸 JS 引擎里运行本模块。

const PARAMS = ["run", "q", "category", "tag", "source", "item"];

export function emptyRoute() {
  return { view: "latest", cid: null, run: "", q: "", category: "", tag: "", source: "", item: "" };
}

function decode(text) {
  try {
    return decodeURIComponent(text.replace(/\+/g, " "));
  } catch {
    return "";
  }
}

export function parseHash(hash) {
  const route = emptyRoute();
  const [path, query = ""] = (hash || "").replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decode);
  if (parts[0] === "v" && parts[1]) route.view = parts[1];
  if (parts[0] === "c" && /^\d+$/.test(parts[1] || "")) {
    route.view = "collection";
    route.cid = Number(parts[1]);
  }
  for (const pair of query.split("&")) {
    const at = pair.indexOf("=");
    const key = at === -1 ? pair : pair.slice(0, at);
    if (PARAMS.includes(key)) route[key] = at === -1 ? "" : decode(pair.slice(at + 1));
  }
  if (parts[0] === "run" && parts[1]) route.run = parts[1];
  if (parts[0] === "item" && parts[1]) route.item = parts[1];
  return route;
}

export function toHash(route) {
  const path = route.view === "collection" ? `/c/${route.cid}` : `/v/${route.view}`;
  const query = PARAMS.filter((key) => route[key])
    .map((key) => `${key}=${encodeURIComponent(route[key])}`)
    .join("&");
  return `#${path}${query ? `?${query}` : ""}`;
}
