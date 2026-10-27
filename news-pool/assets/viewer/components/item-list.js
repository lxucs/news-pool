import { DAY_VIEWS, loadItems, markDayRead, openItem, store } from "../store.js";
import { dayLabel, shortTime } from "../util.js";
import Hl from "./highlight.js";

const VIEW_TITLES = {
  latest: "最新",
  unread: "未读",
  starred: "星标",
  notes: "有笔记",
  hidden: "已隐藏",
};
const EMPTY_TEXT = {
  latest: "新闻池里还没有新闻：先让 agent 抓一次新闻",
  unread: "都读完了",
  starred: "还没有星标的新闻（打开一条，按 s）",
  notes: "还没有写过笔记",
  hidden: "没有隐藏的新闻",
  collection: "这个收藏夹还是空的",
};
const LOAD_MORE_PX = 400; // 列表滚动到离底部这么近时加载下一页

export default {
  name: "ItemList",
  components: { Hl },
  setup() {
    return { store, openItem, markDayRead, shortTime };
  },
  computed: {
    title() {
      const r = store.route;
      if (r.q) return `搜索「${r.q}」`;
      if (r.view === "collection") {
        const c = (store.meta ? store.meta.collections : []).find((x) => x.cid === r.cid);
        return c ? `收藏夹 · ${c.name}` : "收藏夹";
      }
      return VIEW_TITLES[r.view] || "新闻";
    },
    groups() {
      if (!DAY_VIEWS.includes(store.route.view) || store.route.q) {
        return [{ key: "all", label: "", items: store.items, unread: false }];
      }
      const groups = [];
      for (const item of store.items) {
        let group = groups[groups.length - 1];
        if (!group || group.key !== item.fetch_day) {
          group = { key: item.fetch_day, label: dayLabel(item.fetch_day), items: [], unread: false };
          groups.push(group);
        }
        group.items.push(item);
        if (!item.read) group.unread = true;
      }
      return groups;
    },
    emptyText() {
      const r = store.route;
      if (r.q) return "没有匹配的新闻";
      if (r.category || r.tag || r.source || r.run) return "没有符合筛选条件的新闻";
      return EMPTY_TEXT[r.view] || "没有新闻";
    },
    listKey() {
      const r = store.route;
      return [r.view, r.cid, r.run, r.q, r.category, r.tag, r.source].join("|");
    },
  },
  watch: {
    listKey() {
      this.$el.scrollTop = 0;
    },
    "store.route.item"(id) {
      this.$nextTick(() => {
        const card = id ? this.$el.querySelector(`[data-id="${id}"]`) : null;
        if (card) card.scrollIntoView({ block: "nearest" });
      });
    },
  },
  methods: {
    onScroll(event) {
      const el = event.target;
      if (el.scrollHeight - el.scrollTop - el.clientHeight < LOAD_MORE_PX) loadItems(false);
    },
  },
  template: `
<section class="list" @scroll.passive="onScroll">
  <div class="list-head"><h2>{{ title }}</h2><span class="muted">{{ store.total }} 条</span></div>
  <template v-for="g in groups" :key="g.key">
    <div v-if="g.label" class="day-head">
      <span>{{ g.label }}</span>
      <button v-if="g.unread" class="link-btn" @click="markDayRead(g.key)">全部已读</button>
    </div>
    <article v-for="it in g.items" :key="it.id" :data-id="it.id" class="card"
             :class="{ unread: !it.read, active: it.id === store.route.item }" @click="openItem(it.id)">
      <h3 class="card-title"><span v-if="!it.read" class="dot"></span><Hl :text="it.title_zh || it.title" /></h3>
      <p class="card-summary"><Hl :text="it.summary" /></p>
      <div class="card-meta">
        <span>{{ it.category }}</span><span>{{ it.source_name }}</span><span>{{ shortTime(it.published_at) }}</span>
        <span v-if="it.starred" class="star-on">★</span><span v-if="it.has_note">✎</span>
        <span v-if="it.missing" class="warn-text">缺文件</span>
      </div>
    </article>
  </template>
  <div v-if="store.loading" class="list-foot">加载中…</div>
  <div v-else-if="!store.items.length" class="empty">{{ emptyText }}</div>
</section>`,
};
