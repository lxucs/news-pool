import { store } from "../store.js";

const KEYS = [
  ["j / k", "下一条 / 上一条"],
  ["o", "打开原文"],
  ["s", "星标"],
  ["h", "隐藏（不感兴趣）"],
  ["m", "已读 / 未读"],
  ["c", "收藏夹"],
  ["n", "写笔记"],
  ["/", "搜索"],
  ["Esc", "关闭 / 返回"],
  ["?", "显示这张表"],
];

export default {
  name: "HelpOverlay",
  setup() {
    return { store, KEYS };
  },
  template: `
<div class="overlay" @click.self="store.helpOpen = false">
  <div class="help">
    <h3>快捷键</h3>
    <table><tr v-for="[key, what] in KEYS" :key="key"><td><kbd>{{ key }}</kbd></td><td>{{ what }}</td></tr></table>
  </div>
</div>`,
};
