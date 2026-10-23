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
  assert.match(code, /signature === lastSignature && !force\) return/);
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

test("'Fill form on this page' only opens the per-field review; filling still needs the Fill button", () => {
  const start = popup.indexOf("function offerFill(");
  const offer = popup.slice(start, popup.indexOf("\nfunction ", start + 1));
  assert.ok(offer.length > 0);
  assert.ok(!offer.includes('type: "fill"') && !offer.includes("postMessage"), "offerFill must not fill");
  assert.match(offer, /fillTargetCheck\(signup, state\.host\)/);
  assert.match(offer, /renderSuggestion\(\)/);
});

test("the tab hostname comes from the browser tab URL, never from the page", () => {
  assert.match(popup, /state\.host = host;/);
  assert.match(popup, /const host = hostnameFromTabUrl\(state\.tabUrl\);/);
  assert.ok(!/message\.(host|hostname|url)/.test(popup));
});

test("an outdated extension without the scripting permission explains how to fix it", () => {
  assert.match(popup, /if \(!chrome\.scripting\?\.executeScript\)/);
  assert.match(popup, /click the reload icon on LeakTrace/);
});

test("injection or connection failures are reported, not silent", () => {
  assert.match(popup, /autofill\.unavailable = "LeakTrace can't look at the fields on this page\."/);
  assert.match(popup, /autofill\.unavailable = "Lost the connection to this page/);
});

test("Fill form rescans first and distinguishes 'no answer' from 'no fields'", () => {
  const start = popup.indexOf("async function offerFill(");
  const offer = popup.slice(start, popup.indexOf("\nfunction ", start + 1));
  assert.match(offer, /await requestRescan\(\)/);
  assert.match(offer, /The page didn't answer LeakTrace/);
  assert.match(offer, /No supported email, username or nickname fields were found on this page\./);
  assert.match(code, /message\?\.type === "rescan"/);
});

test("detector stats contain only counts", () => {
  const scanBody = code.slice(code.indexOf("function scan()"), code.indexOf("const nativeValueSetter"));
  assert.match(scanBody, /const stats = \{ inputs: 0, password: 0, hidden: 0, type: 0, sensitive: 0, phone: 0, unrecognized: 0, unreadableFrames: 0 \}/);
  for (const m of scanBody.matchAll(/stats(?:\.(\w+)|\[(\w+)\])\s*(\+=|=)/g)) assert.ok(m[3] === "+=", m[0]);
});
