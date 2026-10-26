// Pure helpers: dates, links, highlighting. tests/viewer_js_check.js checks them.

const WEEKDAYS = "日一二三四五六";
const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;

export function dayLabel(fetchDay, now = new Date()) {
  // fetch_day is yymmdd, the item directory's name.
  if (!/^\d{6}$/.test(fetchDay || "")) return "日期未知";
  const date = new Date(
    2000 + Number(fetchDay.slice(0, 2)),
    Number(fetchDay.slice(2, 4)) - 1,
    Number(fetchDay.slice(4, 6)),
  );
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((today - date) / 86400000);
  const label = `${date.getMonth() + 1}月${date.getDate()}日 周${WEEKDAYS[date.getDay()]}`;
  if (days === 0) return `今天 · ${label}`;
  if (days === 1) return `昨天 · ${label}`;
  return label;
}

export function shortTime(iso) {
  // In the timestamp's own offset (the pool writes +08:00 by default): "10-21 21:43".
  const m = ISO_RE.exec(iso || "");
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : "";
}

export function fullTime(iso) {
  const m = ISO_RE.exec(iso || "");
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : "";
}

export function safeUrl(url) {
  // Fetched data is untrusted: only http(s) URLs become links or images.
  return /^https?:\/\//i.test(url || "") ? url : null;
}

export function runLabel(run) {
  const m = ISO_RE.exec(run.created_at || "");
  const day = m ? `${m[2]}-${m[3]}` : run.run_id;
  return run.kind === "adhoc" ? `${day} 专题` : `${day} 每日`;
}

export function segments(text, query) {
  // [{text, hit}] runs, so search terms are highlighted without rendering any HTML.
  const source = text || "";
  const terms = (query || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return [{ text: source, hit: false }];
  const lower = source.toLowerCase();
  const marks = new Array(source.length).fill(false);
  for (const term of terms) {
    for (let at = lower.indexOf(term); at !== -1; at = lower.indexOf(term, at + term.length)) {
      marks.fill(true, at, at + term.length);
    }
  }
  const out = [];
  for (let i = 0; i < source.length; i++) {
    const last = out[out.length - 1];
    if (last && last.hit === marks[i]) last.text += source[i];
    else out.push({ text: source[i], hit: marks[i] });
  }
  return out;
}
