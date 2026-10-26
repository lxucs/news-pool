import { closeItem, navigate, store, toggleHide, toggleRead, toggleStar } from "../store.js";
import { fullTime, safeUrl } from "../util.js";
import CollectionsMenu from "./collections-menu.js";
import NoteEditor from "./note-editor.js";

const IMPORTANCE_STEPS = 5; // 重要度条的格数
const REGIONS = { CN: "中国", US: "美国", EU: "欧洲", JP: "日本", GLOBAL: "全球" };

export default {
  name: "ReaderPane",
  components: { CollectionsMenu, NoteEditor },
  setup() {
    return {
      store,
      closeItem,
      toggleStar,
      toggleHide,
      toggleRead,
      fullTime,
      safeUrl,
      steps: IMPORTANCE_STEPS,
    };
  },
  computed: {
    cur() {
      return store.current;
    },
    item() {
      return this.cur ? this.cur.item : null;
    },
    state() {
      return this.cur ? this.cur.state : {};
    },
    flags() {
      return (this.item && this.item.flags) || {};
    },
    source() {
      return (this.item && this.item.source) || {};
    },
    importance() {
      const metrics = (this.item && this.item.metrics) || {};
      return typeof metrics.importance === "number" ? metrics.importance : 0;
    },
    filled() {
      return Math.round(this.importance * IMPORTANCE_STEPS);
    },
    keyPoints() {
      return Array.isArray(this.item && this.item.key_points) ? this.item.key_points : [];
    },
    tags() {
      return Array.isArray(this.item && this.item.tags) ? this.item.tags : [];
    },
    entities() {
      const e = (this.item && this.item.entities) || {};
      return [...(e.companies || []), ...(e.products || []), ...(e.people || [])];
    },
    related() {
      return Array.isArray(this.item && this.item.related) ? this.item.related : [];
    },
    cover() {
      return safeUrl(this.item && this.item.cover_image && this.item.cover_image.url);
    },
    region() {
      return (this.item && REGIONS[this.item.region]) || "";
    },
  },
  watch: {
    "store.route.item"() {
      this.$nextTick(() => {
        if (this.$el && this.$el.scrollTo) this.$el.scrollTo(0, 0);
      });
    },
  },
  methods: {
    filterTag(tag) {
      navigate({ tag });
    },
    search(text) {
      navigate({ q: text });
    },
  },
  template: `
<section v-if="item" class="reader">
  <article class="reader-inner">
    <button class="back-btn" @click="closeItem">‹ 返回列表</button>
    <div class="reader-meta">
      <span>{{ item.category }}</span><span>{{ source.name }}</span>
      <span>{{ fullTime(item.published_at) }}</span><span v-if="region">{{ region }}</span>
      <span v-if="item.run_kind === 'adhoc'" class="badge">专题</span>
    </div>
    <div class="reader-badges">
      <span class="importance" :title="'重要度 ' + importance.toFixed(2)">
        <i v-for="n in steps" :key="n" :class="{ on: n <= filled }"></i>
      </span>
      <span v-if="flags.is_breaking" class="badge hot">突发</span>
      <span v-if="flags.is_opinion" class="badge">观点</span>
      <span v-if="flags.needs_review" class="badge warn">待核实</span>
    </div>
    <h1 class="reader-title">{{ item.title_zh || item.title }}</h1>
    <p v-if="item.title && item.title !== item.title_zh" class="orig-title">{{ item.title }}</p>
    <img v-if="cover" :src="cover" class="cover" loading="lazy" referrerpolicy="no-referrer" alt="">
    <p class="lead">{{ item.summary }}</p>
    <p v-if="item.synopsis" class="synopsis">{{ item.synopsis }}</p>
    <ul v-if="keyPoints.length" class="points"><li v-for="(p, i) in keyPoints" :key="i">{{ p }}</li></ul>
    <aside v-if="item.why_it_matters" class="why"><b>为什么重要</b><p>{{ item.why_it_matters }}</p></aside>
    <div v-if="tags.length || entities.length" class="chips">
      <button v-for="t in tags" :key="'t-' + t" class="tag" title="只看这个标签" @click="filterTag(t)">#{{ t }}</button>
      <button v-for="e in entities" :key="'e-' + e" class="entity" title="搜索" @click="search(e)">{{ e }}</button>
    </div>
    <section v-if="related.length" class="related">
      <h3>同一事件的其他报道（{{ related.length }}）</h3>
      <ul>
        <li v-for="r in related" :key="r.id || r.url">
          <a v-if="safeUrl(r.url)" :href="safeUrl(r.url)" target="_blank" rel="noopener noreferrer">{{ r.title }}</a>
          <span v-else>{{ r.title }}</span>
          <span class="muted">{{ r.source_name }} · {{ fullTime(r.published_at) }}</span>
        </li>
      </ul>
    </section>
    <p v-if="cur.missing" class="missing">条目文件缺失（可能已被删除），这里只显示运行清单里的信息。</p>
    <div class="actions">
      <button class="btn" :class="{ on: state.starred_at }" title="星标（s）" @click="toggleStar">
        {{ state.starred_at ? "★ 已星标" : "☆ 星标" }}
      </button>
      <CollectionsMenu />
      <button class="btn" title="不感兴趣，隐藏（h）" @click="toggleHide">
        {{ state.hidden_at ? "取消隐藏" : "⊘ 隐藏" }}
      </button>
      <button class="btn" title="已读 / 未读（m）" @click="toggleRead">
        {{ state.read_at ? "标为未读" : "标为已读" }}
      </button>
      <a v-if="safeUrl(source.url)" class="btn primary" :href="safeUrl(source.url)"
         target="_blank" rel="noopener noreferrer" title="阅读原文（o）">阅读原文 ↗</a>
    </div>
    <NoteEditor :item-id="item.id" :note="state.note || ''" />
  </article>
</section>
<section v-else class="reader reader-empty">
  <div><p>选择一条新闻开始阅读</p><p class="muted">j / k 上下切换 · / 搜索 · ? 全部快捷键</p></div>
</section>`,
};
