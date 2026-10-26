# Vendored browser library

The viewer has no build step: the page imports this file as it is.

| File | Library | Version | License |
|---|---|---|---|
| `vue.esm-browser.prod.js` | Vue, ES-module browser build (includes the template compiler) | 3.5.44 | MIT (`LICENSE`) |

Source: `https://registry.npmjs.org/vue/-/vue-3.5.44.tgz`, file `package/dist/vue.esm-browser.prod.js`.

sha256: 37d771e9e91c9c7f78d7db53b3e1f43bb7a48ca5f84d41b4aca95a7cebc8eb5b

To upgrade: download the new tarball into an empty temporary directory, copy the same file and
`package/LICENSE` here, update the version, source and sha256 above, and run the suite
(`tests/test_viewer_static.py` checks the checksum and, on macOS, compiles every template against
the new build).
