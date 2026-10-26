import { saveNote } from "../store.js";

const SAVE_DELAY_MS = 800; // 停止输入这么久后保存

export default {
  name: "NoteEditor",
  props: {
    itemId: { type: String, required: true },
    note: { type: String, default: "" },
  },
  data() {
    return { text: this.note, status: "", timer: null, dirtyFor: null };
  },
  watch: {
    itemId() {
      // 先保存上一个条目里输入的内容，再显示这个条目的笔记。
      this.flush();
      this.text = this.note;
      this.status = "";
    },
  },
  unmounted() {
    this.flush();
  },
  methods: {
    onInput() {
      this.dirtyFor = this.itemId;
      this.status = "未保存";
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.flush(), SAVE_DELAY_MS);
    },
    async flush() {
      clearTimeout(this.timer);
      if (!this.dirtyFor) return;
      const id = this.dirtyFor;
      const text = this.text;
      this.dirtyFor = null;
      if (id === this.itemId) this.status = "保存中…";
      try {
        await saveNote(id, text);
        if (id === this.itemId) this.status = "已保存";
      } catch (err) {
        if (id === this.itemId) {
          this.status = "保存失败";
          this.dirtyFor = id;
        }
      }
    },
  },
  template: `
<section class="note">
  <div class="note-head"><span>笔记</span><span class="muted">{{ status }}</span></div>
  <textarea v-model="text" rows="4" placeholder="写点什么：为什么值得留意、要跟进什么…（自动保存）"
            @input="onInput" @blur="flush"></textarea>
</section>`,
};
