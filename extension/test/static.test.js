// Static checks over every shipped extension file.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const root = fileURLToPath(new URL("..", import.meta.url));
function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === "test" || name === "node_modules") return [];
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}
const shipped = files(root).map((path) => ({ path, text: readFileSync(path, "utf8") }));

test("no secrets or database details in extension assets", () => {
  for (const { path, text } of shipped) {
    // A runtime account token may be sent as `Bearer ${token}`; no literal token value may appear.
    for (const pattern of [/INGEST_SECRET/i, /Bearer\s+(?!\$\{)[A-Za-z0-9._~+/-]{8,}/, /postgres(ql)?(\+psycopg)?:\/\//i,
      /neon\.tech/i, /npg_/, /DATABASE_URL/, /api[_-]?key/i, /password\s*[:=]\s*["'`]/i, /lt_session/,
      /authorization:\s*["'`](?!Bearer \$\{)/i]) {
      assert.ok(!pattern.test(text), `${path} matches ${pattern}`);
    }
  }
});

test("untrusted data is never inserted as HTML", () => {
  for (const { path, text } of shipped.filter((f) => f.path.endsWith(".js"))) {
    for (const unsafe of ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"]) {
      assert.ok(!text.includes(unsafe), `${path} uses ${unsafe}`);
    }
  }
});

test("page access is limited to injecting the autofill detector from the popup", () => {
  for (const { path, text } of shipped.filter((f) => f.path.endsWith(".js"))) {
    for (const api of ["insertCSS", "registerContentScripts", "chrome.history", "chrome.cookies",
      "chrome.webRequest", "chrome.bookmarks", "chrome.downloads", "chrome.tabs.sendMessage", "runtime.sendMessage"]) {
      assert.ok(!text.includes(api), `${path} uses ${api}`);
    }
    if (!path.endsWith("popup.js")) assert.ok(!text.includes("chrome.scripting"), `${path} uses chrome.scripting`);
  }
  const popup = readFileSync(join(root, "popup.js"), "utf8");
  const calls = [...popup.matchAll(/chrome\.scripting\.(\w+)\(([^)]*)\)/g)];
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1], "executeScript");
  assert.match(calls[0][2], /target: \{ tabId: state\.tab\.id \}, files: \["content\/autofill\.js"\]/);
  assert.ok(!/func:|world:|allFrames/.test(calls[0][2]), "only the bundled file, top frame, isolated world");
});

test("only the tab URL is read, and only from the active tab", () => {
  const popup = readFileSync(join(root, "popup.js"), "utf8");
  assert.equal(popup.match(/chrome\.tabs\.query/g).length, 1);
  assert.match(popup, /chrome\.tabs\.query\(\{ active: true, currentWindow: true \}\)/);
  assert.ok(!/tab\.(title|favIconUrl)/.test(popup));
});

test("network calls happen only from confirm handlers", () => {
  const popup = readFileSync(join(root, "popup.js"), "utf8");
  assert.ok(!popup.includes("fetch("), "popup must call the backend only through the api module");
  for (const call of ["state.api.createSignup(", "state.api.createReceipt("]) {
    const index = popup.indexOf(call);
    assert.ok(index > 0, call);
    const before = popup.slice(0, index);
    assert.ok(before.lastIndexOf("confirmPanel(") > before.lastIndexOf("function "), `${call} must be inside a confirm callback`);
  }
});

test("persistent storage holds only settings; selection uses session storage", () => {
  const allowed = new Set(["baseUrl", "autofillEnabled", "neverSites"]);
  for (const { path, text } of shipped.filter((f) => f.path.endsWith(".js"))) {
    for (const match of text.matchAll(/chrome\.storage\.local\.set\(\{ ?(\w+)/g)) {
      assert.ok(allowed.has(match[1]), `${path} stores ${match[1]}`);
    }
    assert.ok(!text.includes("chrome.storage.sync"), path);
  }
});

test("pages load only local scripts and styles", () => {
  for (const { path, text } of shipped.filter((f) => f.path.endsWith(".html"))) {
    assert.ok(!/<script[^>]*src="https?:/i.test(text) && !/<link[^>]*href="https?:/i.test(text), path);
    assert.ok(!/<script(?![^>]*src=)[^>]*>/i.test(text), `${path} has an inline script`);
    assert.ok(!/\son[a-z]+=/i.test(text), `${path} has an inline event handler`);
  }
});
