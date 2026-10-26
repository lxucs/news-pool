// 由 tests/test_viewer_static.py 在 macOS 的 JavaScriptCore shell（`jsc -m`）下运行。
// 加载这个模块图，就会解析阅读器的每个模块、核对每个导入的名字；正文编译每个组件的模板，
// 并调用纯函数工具做检查。不用 DOM，不联网。
import { compile } from "../news-viewer/scripts/newsviewer/static/vendor/vue.esm-browser.prod.js";
import AppRoot from "../news-viewer/scripts/newsviewer/static/components/app-root.js";
import CollectionsMenu from "../news-viewer/scripts/newsviewer/static/components/collections-menu.js";
import HelpOverlay from "../news-viewer/scripts/newsviewer/static/components/help.js";
import Hl from "../news-viewer/scripts/newsviewer/static/components/highlight.js";
import ItemList from "../news-viewer/scripts/newsviewer/static/components/item-list.js";
import NoteEditor from "../news-viewer/scripts/newsviewer/static/components/note-editor.js";
import ReaderPane from "../news-viewer/scripts/newsviewer/static/components/reader.js";
import SideNav from "../news-viewer/scripts/newsviewer/static/components/sidebar.js";
import ToastBar from "../news-viewer/scripts/newsviewer/static/components/toast.js";
import TopBar from "../news-viewer/scripts/newsviewer/static/components/topbar.js";
import { emptyRoute, parseHash, toHash } from "../news-viewer/scripts/newsviewer/static/router.js";
import {
  dayLabel,
  runLabel,
  safeUrl,
  segments,
  shortTime,
} from "../news-viewer/scripts/newsviewer/static/util.js";

// 模板里只要有 "&"（如 `a && b`），Vue 就会借一个 DOM 元素来解码 HTML 实体；jsc 没有 DOM，
// 所以替它模拟这唯一的一次调用。
const decode = (s) => s.replace(/&quot;/g, '"').replace(/&amp;/g, "&");
globalThis.document = {
  createElement() {
    const el = { html: "" };
    Object.defineProperty(el, "innerHTML", { set(v) { el.html = v; } });
    Object.defineProperty(el, "textContent", { get() { return decode(el.html); } });
    Object.defineProperty(el, "children", {
      get() {
        const m = /foo="([\s\S]*)">$/.exec(el.html);
        return [{ getAttribute: () => decode(m ? m[1] : "") }];
      },
    });
    return el;
  },
};

function check(condition, what) {
  if (!condition) throw new Error(`check failed: ${what}`);
}

const components = {
  AppRoot, CollectionsMenu, HelpOverlay, Hl, ItemList, NoteEditor, ReaderPane, SideNav,
  ToastBar, TopBar,
};
for (const [name, component] of Object.entries(components)) {
  try {
    compile(component.template);
  } catch (err) {
    throw new Error(`${name}: template does not compile: ${err.message}`);
  }
}

const run = parseHash("#/run/20261022-080000");
check(run.view === "latest" && run.run === "20261022-080000", "run deep link");
check(toHash(run) === "#/v/latest?run=20261022-080000", "canonical run hash");
const back = parseHash(
  toHash({ ...emptyRoute(), view: "collection", cid: 3, q: "芯片 量产", item: "0000000000a1" }),
);
check(back.view === "collection" && back.cid === 3, "collection hash");
check(back.q === "芯片 量产" && back.item === "0000000000a1", "query round trip");
check(parseHash("#/item/0000000000a1").item === "0000000000a1", "item deep link");
check(parseHash("").view === "latest", "empty hash");
check(
  JSON.stringify(segments("台积电 3nm 芯片量产", "芯片")) ===
    JSON.stringify([
      { text: "台积电 3nm ", hit: false },
      { text: "芯片", hit: true },
      { text: "量产", hit: false },
    ]),
  "highlight segments",
);
check(safeUrl("javascript:alert(1)") === null, "unsafe url");
check(safeUrl("https://example.com/a") === "https://example.com/a", "safe url");
check(dayLabel("261022", new Date(2026, 9, 22)) === "今天 · 10月22日 周四", "today label");
check(dayLabel("261021", new Date(2026, 9, 22)) === "昨天 · 10月21日 周三", "yesterday label");
check(shortTime("2026-10-21T21:43:39+08:00") === "10-21 21:43", "short time");
check(runLabel({ kind: "adhoc", created_at: "2026-10-22T13:52:20+08:00" }) === "10-22 专题", "run label");
print("ok");
