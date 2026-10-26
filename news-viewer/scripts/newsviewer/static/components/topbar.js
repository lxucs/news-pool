import { navigate, store, toggleTheme } from "../store.js";
import { runLabel } from "../util.js";

const SEARCH_DELAY_MS = 300; // search once typing pauses this long

export default {
  name: "TopBar",
  setup() {
    return { store, toggleTheme };
  },
  data() {
    return { text: store.route.q, timer: null };
  },
  computed: {
    sources() {
      return store.meta ? store.meta.sources : [];
    },
    chips() {
      const r = store.route;
      const chips = [];
      if (r.category) chips.push({ key: "category", label: `类别：${r.category}` });
      if (r.tag) chips.push({ key: "tag", label: `#${r.tag}` });
      if (r.run) {
        const run = (store.meta ? store.meta.runs : []).find((x) => x.run_id === r.run);
        chips.push({ key: "run", label: `运行：${run ? runLabel(run) : r.run}` });
      }
      return chips;
    },
  },
  watch: {
    "store.route.q"(q) {
      if (q !== this.text.trim()) this.text = q;
    },
  },
  methods: {
    onInput() {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => navigate({ q: this.text.trim() }), SEARCH_DELAY_MS);
    },
    setSource(event) {
      navigate({ source: event.target.value, item: "" });
    },
    clearChip(key) {
      navigate({ [key]: "", item: "" });
    },
  },
  template: `
<header class="topbar">
  <button class="icon-btn drawer-btn" title="导航" @click="store.drawerOpen = !store.drawerOpen">☰</button>
  <div class="brand">新闻池</div>
  <div class="search">
    <input id="search" v-model="text" type="search" autocomplete="off"
           placeholder="搜索标题、摘要、标签、笔记…（/）" @input="onInput">
  </div>
  <select class="source-select" :value="store.route.source" title="按来源筛选" @change="setSource">
    <option value="">全部来源</option>
    <option v-for="s in sources" :key="s.name" :value="s.name">{{ s.name }}（{{ s.count }}）</option>
  </select>
  <span v-for="c in chips" :key="c.key" class="chip">
    {{ c.label }}<button class="chip-x" title="移除这个筛选" @click="clearChip(c.key)">×</button>
  </span>
  <span class="spacer"></span>
  <button class="icon-btn" title="深色 / 浅色" @click="toggleTheme">◐</button>
  <button class="icon-btn" title="快捷键（?）" @click="store.helpOpen = true">?</button>
</header>`,
};
