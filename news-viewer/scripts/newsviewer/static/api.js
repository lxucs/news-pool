// JSON API（api.py）。每个非 GET 请求都带 X-News-Viewer 头：api.py 要求有它，
// 这样其他网页就不能借用户的浏览器写入数据。

export class ServerGone extends Error {}

async function request(method, path, body) {
  const init = { method, headers: {} };
  if (method !== "GET") init.headers["X-News-Viewer"] = "1";
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    throw new ServerGone(String(err));
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function query(params) {
  return Object.entries(params)
    .filter(([, value]) => value !== "" && value !== null && value !== undefined)
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
    .join("&");
}

export const api = {
  health: () => request("GET", "/api/health"),
  meta: () => request("GET", "/api/meta"),
  items: (params) => request("GET", `/api/items?${query(params)}`),
  item: (id) => request("GET", `/api/items/${id}`),
  setState: (id, flags) => request("PATCH", `/api/items/${id}/state`, flags),
  setNote: (id, note) => request("PUT", `/api/items/${id}/note`, { note }),
  markRead: (body) => request("POST", "/api/read", body),
  createCollection: (name, description = "") =>
    request("POST", "/api/collections", { name, description }),
  updateCollection: (cid, changes) => request("PATCH", `/api/collections/${cid}`, changes),
  deleteCollection: (cid) => request("DELETE", `/api/collections/${cid}`),
  collect: (cid, id) => request("PUT", `/api/collections/${cid}/items/${id}`),
  uncollect: (cid, id) => request("DELETE", `/api/collections/${cid}/items/${id}`),
};
