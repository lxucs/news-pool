import { store } from "../store.js";
import { segments } from "../util.js";

// 以文本片段高亮搜索词，绝不渲染成 HTML（抓取来的文本不可信）。
export default {
  name: "Hl",
  props: { text: { type: String, default: "" } },
  computed: {
    parts() {
      return segments(this.text, store.route.q);
    },
  },
  template: `<template v-for="(p, i) in parts" :key="i"><mark v-if="p.hit">{{ p.text }}</mark><template v-else>{{ p.text }}</template></template>`,
};
