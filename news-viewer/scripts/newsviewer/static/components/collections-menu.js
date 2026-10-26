import { createCollection, store, toggleCollection } from "../store.js";

export default {
  name: "CollectionsMenu",
  setup() {
    return { store, toggleCollection };
  },
  data() {
    return { name: "" };
  },
  computed: {
    collections() {
      return store.meta ? store.meta.collections : [];
    },
    cids() {
      return store.current ? store.current.cids : [];
    },
  },
  watch: {
    "store.menuOpen"(open) {
      if (open) this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
    },
  },
  mounted() {
    this.onDocumentClick = (event) => {
      if (store.menuOpen && !this.$el.contains(event.target)) store.menuOpen = false;
    };
    document.addEventListener("click", this.onDocumentClick);
  },
  unmounted() {
    document.removeEventListener("click", this.onDocumentClick);
  },
  methods: {
    async create() {
      const name = this.name.trim();
      if (name && (await createCollection(name, true))) this.name = "";
    },
  },
  template: `
<div class="menu-wrap">
  <button class="btn" :class="{ on: cids.length }" title="加入收藏夹（c）" @click="store.menuOpen = !store.menuOpen">
    ⊕ 收藏夹<span v-if="cids.length"> · {{ cids.length }}</span>
  </button>
  <div v-if="store.menuOpen" class="menu">
    <label v-for="c in collections" :key="c.cid" class="menu-row">
      <input type="checkbox" :checked="cids.includes(c.cid)" @change="toggleCollection(c.cid)">
      <span class="ellipsis">{{ c.name }}</span>
    </label>
    <p v-if="!collections.length" class="menu-row muted">还没有收藏夹</p>
    <form class="menu-new" @submit.prevent="create">
      <input ref="input" v-model="name" placeholder="新建收藏夹并加入…">
      <button class="btn small" :disabled="!name.trim()">新建</button>
    </form>
  </div>
</div>`,
};
