import { store } from "../store.js";

export default {
  name: "ToastBar",
  setup() {
    return { store };
  },
  methods: {
    undo() {
      const action = store.toast.undo;
      store.toast = null;
      action();
    },
  },
  template: `
<div v-if="store.toast" class="toast" role="status">
  <span>{{ store.toast.text }}</span>
  <button v-if="store.toast.undo" class="link-btn" @click="undo">撤销</button>
</div>`,
};
