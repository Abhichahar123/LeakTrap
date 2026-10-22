// Static safety checks for the autofill detector and its popup wiring.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const content = readFileSync(new URL("../content/autofill.js", import.meta.url), "utf8");
const popup = readFileSync(new URL("../popup.js", import.meta.url), "utf8");
const code = content.replace(/\/\/.*$/gm, ""); // ignore comments

test("detector never submits, clicks or navigates", () => {
  for (const banned of [".submit(", "requestSubmit", ".click(", "dispatchEvent(new MouseEvent", "dispatchEvent(new KeyboardEvent",
    "dispatchEvent(new SubmitEvent", "location.", "window.open", "form.action"]) {
    assert.ok(!code.includes(banned), banned);
  }
  assert.deepEqual([...code.matchAll(/new Event\("(\w+)"/g)].map((m) => m[1]).sort(), ["change", "input"]);
});

test("detector has no network, storage, keystroke or submission listeners", () => {
  for (const banned of ["fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "chrome.storage", "localStorage",
    "sessionStorage", "document.cookie", '"keydown"', '"keyup"', '"keypress"', '"submit"', '"paste"', "addEventListener("]) {
    assert.ok(!code.includes(banned), banned);
  }
});

test("detector never parses or inserts HTML and adds no page UI", () => {
  for (const banned of ["innerHTML", "outerHTML", "insertAdjacent", "document.write", "createElement", "attachShadow",
    "appendChild", ".append(", "eval(", "new Function"]) {
    assert.ok(!code.includes(banned), banned);
  }
});

test("detector does not read page text wholesale", () => {
  for (const banned of ["document.body.innerText", "document.body.textContent", "documentElement.textContent",
    "innerText", "getSelection", "XMLSerializer"]) {
    assert.ok(!code.includes(banned), banned);
  }
});

test("values are only compared with empty strings or set through the native setter", () => {
  const reads = [...code.matchAll(/\.value\b(.{0,8})/g)].map((m) => m[0]);
  for (const read of reads) assert.match(read, /^\.value (===|!==) ""/, read);
  assert.match(code, /nativeValueSetter\.call\(el, value\)/);
});

test("password inputs are counted by type only, never read or filled", () => {
  const passwordBranch = code.slice(code.indexOf('=== "password") {'), code.indexOf("continue;", code.indexOf('=== "password") {')));
  assert.ok(!passwordBranch.includes(".value"));
  assert.match(code, /=== "password"\) return \{ id, filled: false, reason: "not allowed" \}/);
});

test("observer is bounded and cleaned up", () => {
  assert.match(code, /OBSERVE_MS = 120_000/);
  assert.match(code, /MAX_RESCANS = 40/);
  assert.match(code, /port\.onDisconnect\.addListener\(stop\)/);
  assert.match(code, /signature === lastSignature\) return/);
});

test("only connections from this extension are accepted", () => {
  assert.match(code, /port\.name !== "leaktrace-autofill" \|\| port\.sender\?\.id !== chrome\.runtime\.id/);
});

test("popup: alias lookup only on an explicit click; fill only from the Fill button", () => {
  assert.match(popup, /\$\("autofill-lookup"\)\.addEventListener\("click", lookupAlias\)/);
  assert.equal(popup.match(/state\.api\.lookupSignups\(/g).length, 1);
  assert.equal(popup.match(/type: "fill"/g).length, 1);
  assert.ok(popup.indexOf('type: "fill"') > popup.indexOf("function fillNow("));
  assert.match(popup, /onclick: \(\) => fillNow\(signup\)/);
  // No signup is ever created from autofill code: creation only goes through the confirm panel.
  assert.equal(popup.match(/state\.api\.createSignup\(/g).length, 1);
  const create = popup.slice(popup.indexOf("function createFromAutofill"), popup.indexOf("// ---------- start"));
  assert.ok(!create.includes("createSignup") && !create.includes("requestSubmit"));
});
