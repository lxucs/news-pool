import { store } from "../store.js";
import { segments } from "../util.js";

// Search terms highlighted as text segments, never as HTML (fetched text is untrusted).
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
