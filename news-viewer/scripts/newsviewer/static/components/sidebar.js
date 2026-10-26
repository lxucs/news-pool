import { createCollection, deleteCollection, navigate, renameCollection, store } from "../store.js";
import { runLabel } from "../util.js";

const VIEWS = [
  { key: "latest", label: "最新" },
  { key: "unread", label: "未读" },
  { key: "starred", label: "★ 星标" },
  { key: "notes", label: "✎ 有笔记" },
  { key: "hidden", label: "⊘ 已隐藏" },
];
const RECENT_RUNS = 7; // runs listed before 更多
const EMPTY_META = { runs: [], categories: [], collections: [], counts: {} };

export default {
  name: "SideNav",
  setup() {
    return { store, VIEWS, RECENT_RUNS, runLabel };
  },
  data() {
    return { allRuns: false };
  },
  computed: {
    meta() {
      return store.meta || EMPTY_META;
    },
    runs() {
      return this.allRuns ? this.meta.runs : this.meta.runs.slice(0, RECENT_RUNS);
    },
  },
  methods: {
    go(changes) {
      store.drawerOpen = false;
      navigate({ ...changes, item: "" });
    },
    toggleFilter(key, value) {
      this.go({ [key]: store.route[key] === value ? "" : value });
    },
    async addCollection() {
      const name = (window.prompt("新收藏夹的名字") || "").trim();
      if (name) await createCollection(name, false);
    },
    async rename(c) {
      const name = (window.prompt("重命名收藏夹", c.name) || "").trim();
      if (name && name !== c.name) await renameCollection(c.cid, name);
    },
    async remove(c) {
      if (window.confirm(`删除收藏夹「${c.name}」？其中的新闻不会被删除。`)) {
        await deleteCollection(c.cid);
      }
    },
  },
  template: `
<nav class="side" :class="{ open: store.drawerOpen }">
  <div class="side-group">
    <button v-for="v in VIEWS" :key="v.key" class="side-item"
            :class="{ active: store.route.view === v.key }" @click="go({ view: v.key, cid: null })">
      <span>{{ v.label }}</span><span class="count">{{ meta.counts[v.key] }}</span>
    </button>
  </div>
  <div class="side-group">
    <div class="side-head">
      <span>收藏夹</span>
      <button class="icon-btn small" title="新建收藏夹" @click="addCollection">＋</button>
    </div>
    <div v-for="c in meta.collections" :key="c.cid" class="side-row"
         :class="{ active: store.route.view === 'collection' && store.route.cid === c.cid }">
      <button class="side-item" :title="c.description || c.name"
              @click="go({ view: 'collection', cid: c.cid })">
        <span class="ellipsis">{{ c.name }}</span><span class="count">{{ c.count }}</span>
      </button>
      <span class="row-actions">
        <button class="icon-btn small" title="重命名" @click="rename(c)">✎</button>
        <button class="icon-btn small" title="删除收藏夹" @click="remove(c)">×</button>
      </span>
    </div>
    <p v-if="!meta.collections.length" class="side-empty">还没有收藏夹</p>
  </div>
  <div v-if="meta.categories.length" class="side-group">
    <div class="side-head"><span>类别</span></div>
    <button v-for="c in meta.categories" :key="c.name" class="side-item"
            :class="{ active: store.route.category === c.name }"
            @click="toggleFilter('category', c.name)">
      <span class="ellipsis">{{ c.name || "未分类" }}</span><span class="count">{{ c.count }}</span>
    </button>
  </div>
  <div v-if="meta.runs.length" class="side-group">
    <div class="side-head"><span>运行</span></div>
    <button v-for="r in runs" :key="r.run_id" class="side-item" :title="r.focus || r.run_id"
            :class="{ active: store.route.run === r.run_id }" @click="toggleFilter('run', r.run_id)">
      <span class="run-label">
        <span>{{ runLabel(r) }}</span><span v-if="r.focus" class="run-focus">{{ r.focus }}</span>
      </span>
      <span class="count">{{ r.item_count }}</span>
    </button>
    <button v-if="meta.runs.length > RECENT_RUNS" class="link-btn side-more" @click="allRuns = !allRuns">
      {{ allRuns ? "收起" : "更多" }}
    </button>
  </div>
</nav>`,
};
