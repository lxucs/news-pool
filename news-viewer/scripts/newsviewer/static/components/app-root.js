import { store } from "../store.js";
import HelpOverlay from "./help.js";
import ItemList from "./item-list.js";
import ReaderPane from "./reader.js";
import SideNav from "./sidebar.js";
import ToastBar from "./toast.js";
import TopBar from "./topbar.js";

export default {
  name: "AppRoot",
  components: { HelpOverlay, ItemList, ReaderPane, SideNav, ToastBar, TopBar },
  setup() {
    return { store };
  },
  template: `
<div class="app" :class="{ 'has-reader': !!store.route.item }">
  <TopBar />
  <div v-if="store.serverDown" class="banner">
    阅读器服务已停止（空闲太久会自动退出）。请让 agent 重新打开阅读器，或运行 <code>nv.py up</code>，然后刷新本页。
  </div>
  <main class="panes">
    <SideNav />
    <div v-if="store.drawerOpen" class="scrim" @click="store.drawerOpen = false"></div>
    <ItemList />
    <ReaderPane />
  </main>
  <ToastBar />
  <HelpOverlay v-if="store.helpOpen" />
</div>`,
};
