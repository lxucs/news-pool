# 内置的浏览器库

阅读器没有构建步骤：页面直接 import 这个文件。

| 文件 | 库 | 版本 | 许可证 |
|---|---|---|---|
| `vue.esm-browser.prod.js` | Vue 的 ES 模块浏览器构建（含模板编译器） | 3.5.44 | MIT（`LICENSE`） |

来源：`https://registry.npmjs.org/vue/-/vue-3.5.44.tgz` 里的 `package/dist/vue.esm-browser.prod.js`。

sha256: 37d771e9e91c9c7f78d7db53b3e1f43bb7a48ca5f84d41b4aca95a7cebc8eb5b

升级方法：把新版本的 tarball 下载到一个空的临时目录，把同一个文件和 `package/LICENSE` 复制到这里，更新上面的版本、来源和 sha256，然后跑测试（`tests/test_viewer_static.py` 会核对 sha256；在 macOS 上还会用新版本编译每一个模板）。
