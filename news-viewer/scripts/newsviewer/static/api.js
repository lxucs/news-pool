// The JSON API (api.py). Every non-GET request carries X-News-Viewer, which api.py requires so
// that other web pages cannot write through the user's browser.

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
