import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ApiError, NEVER_SITES_LIMIT, addNeverSite, buildFillPlan, canInspectTab, createApi, fillOptions,
  normalizeNeverSites, parseRecalledSignup, removeNeverSite,
} from "../src/lib.js";

const BASE = "http://127.0.0.1:8000";
const ITEM = { id: 4, site_name: "Shop", site_domain: "shop.example.com", alias: "ab12@leaktrap.xyz", nickname: "Ocelot",
  real_name_required: false, created_at: "2026-10-22T10:00:00Z" };

function fakeFetch(status, body, { raw = false } = {}) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    if (status instanceof Error) throw status;
    return new Response(raw ? body : JSON.stringify(body), { status });
  };
  impl.calls = calls;
  return impl;
}

// ---------- lookup ----------

test("lookup posts only the exact normalized hostname and creates nothing", async () => {
  const fetchImpl = fakeFetch(200, { site_domain: "shop.example.com", items: [ITEM] });
  const items = await createApi(BASE, fetchImpl).lookupSignups("WWW.Shop.Example.com");
  assert.equal(fetchImpl.calls.length, 1);
  assert.equal(fetchImpl.calls[0].url, `${BASE}/autofill/lookup`);
  assert.equal(fetchImpl.calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(fetchImpl.calls[0].init.body), { site_domain: "shop.example.com" });
  assert.ok(!fetchImpl.calls[0].url.includes("signups"));
  assert.deepEqual(items, [{ id: 4, siteName: "Shop", siteDomain: "shop.example.com", alias: "ab12@leaktrap.xyz",
    nickname: "Ocelot", realNameRequired: false }]);
});

test("items for other domains or subdomains are discarded even if the backend returns them", async () => {
  const fetchImpl = fakeFetch(200, { site_domain: "example.com", items: [
    { ...ITEM, site_domain: "shop.example.com" }, { ...ITEM, id: 5, site_domain: "example.com" }, { ...ITEM, id: 6, site_domain: "evil.com" }] });
  const items = await createApi(BASE, fetchImpl).lookupSignups("example.com");
  assert.deepEqual(items.map((i) => i.id), [5]);
});

for (const [name, fetchImpl, pattern] of [
  ["backend unavailable", fakeFetch(new TypeError("Failed to fetch")), /Could not reach/],
  ["500", fakeFetch(500, "boom", { raw: true }), /HTTP 500/],
  ["403 non-local", fakeFetch(403, {}), /only accepts requests from this computer/],
  ["wrong echoed domain", fakeFetch(200, { site_domain: "other.com", items: [] }), /unexpected lookup/],
  ["items not a list", fakeFetch(200, { site_domain: "shop.example.com", items: {} }), /unexpected lookup/],
  ["not JSON", fakeFetch(200, "<html>", { raw: true }), /unexpected response/],
]) {
  test(`lookup failure: ${name}`, async () => {
    await assert.rejects(createApi(BASE, fetchImpl).lookupSignups("shop.example.com"), (e) => e instanceof ApiError && pattern.test(e.message));
  });
}

test("malformed items are dropped and malformed aliases are never used", () => {
  assert.equal(parseRecalledSignup(null), null);
  assert.equal(parseRecalledSignup({ ...ITEM, id: "4" }), null);
  assert.equal(parseRecalledSignup({ ...ITEM, id: 0 }), null);
  assert.equal(parseRecalledSignup({ ...ITEM, site_domain: undefined }), null);
  for (const alias of ["not an email", "<script>@x.com", "a b@leaktrap.xyz", "", 42, null]) {
    assert.equal(parseRecalledSignup({ ...ITEM, alias }).alias, null, String(alias));
  }
  assert.equal(parseRecalledSignup({ ...ITEM, nickname: "   " }).nickname, null);
  assert.equal(parseRecalledSignup({ ...ITEM, real_name_required: "yes" }).realNameRequired, false);
});

// ---------- which tabs ----------

for (const [url, ok] of [
  ["https://shop.example.com/register", true], ["http://example.org/login", true],
  ["chrome://settings", false], ["chrome-extension://abc/popup.html", false], ["file:///tmp/x.html", false],
  ["https://chromewebstore.google.com/detail/x", false], ["https://chrome.google.com/webstore", false],
  ["about:blank", false], ["http://127.0.0.1:8000/dashboard", false], ["https://localhost/", false],
]) {
  test(`canInspectTab(${url}) is ${ok}`, () => assert.equal(canInspectTab(url), ok));
}

// ---------- never-for-this-site ----------

test("never list is per exact hostname and isolated from other hosts", () => {
  let list = addNeverSite([], "WWW.Shop.Example.com");
  assert.deepEqual(list, ["shop.example.com"]);
  list = addNeverSite(list, "shop.example.com");
  assert.deepEqual(list, ["shop.example.com"]);
  list = addNeverSite(list, "login.shop.example.com");
  assert.deepEqual(list, ["login.shop.example.com", "shop.example.com"]);
  assert.ok(!list.includes("example.com"));
  assert.deepEqual(removeNeverSite(list, "shop.example.com"), ["login.shop.example.com"]);
});

test("never list from storage is cleaned and bounded", () => {
  assert.deepEqual(normalizeNeverSites(undefined), []);
  assert.deepEqual(normalizeNeverSites("shop.example.com"), []);
  assert.deepEqual(normalizeNeverSites(["shop.example.com", "bad host", "SHOP.example.com", 5, "x"]), ["shop.example.com"]);
  const many = Array.from({ length: NEVER_SITES_LIMIT + 50 }, (_, i) => `s${i}.example.com`);
  assert.equal(normalizeNeverSites(many).length, NEVER_SITES_LIMIT);
});

// ---------- fill options and plans ----------

const SIGNUP = { id: 4, alias: "ab12@leaktrap.xyz", nickname: "Ocelot", realNameRequired: false };
const field = (id, kind, form = "signup", empty = true) => ({ id, kind, form, empty, label: `${kind} label` });

test("signup form: identifier and nickname ticked when empty; name offered unticked", () => {
  const options = fillOptions([field("f1", "email"), field("f2", "nickname"), field("f3", "name")], SIGNUP);
  assert.deepEqual(options.map((o) => [o.id, o.value, o.ticked]), [
    ["f1", "ab12@leaktrap.xyz", true], ["f2", "Ocelot", true], ["f3", "Ocelot", false]]);
});

test("login form: only the identifier field, never nickname or name", () => {
  const options = fillOptions([field("f1", "username", "login"), field("f2", "nickname", "login"), field("f3", "name", "login")], SIGNUP);
  assert.deepEqual(options.map((o) => o.id), ["f1"]);
});

test("non-empty fields are offered but never ticked by default", () => {
  const [option] = fillOptions([field("f1", "email", "login", false)], SIGNUP);
  assert.equal(option.ticked, false);
  assert.equal(option.empty, false);
});

test("real-name-required signups never offer name fields; no nickname means no nickname fill", () => {
  const options = fillOptions([field("f1", "email"), field("f2", "name"), field("f3", "nickname")],
    { ...SIGNUP, nickname: null, realNameRequired: true });
  assert.deepEqual(options.map((o) => o.id), ["f1"]);
});

test("no alias: identifier fields are not offered (no guessing or substitution)", () => {
  assert.deepEqual(fillOptions([field("f1", "email")], { ...SIGNUP, alias: null }), []);
});

test("fill plan contains only ticked fields and marks replacements explicitly", () => {
  const options = fillOptions([field("f1", "email", "signup", true), field("f2", "nickname", "signup", false)], SIGNUP);
  assert.deepEqual(buildFillPlan(options, ["f1"], SIGNUP), { alias: "ab12@leaktrap.xyz", nickname: "Ocelot",
    fields: [{ id: "f1", kind: "email", overwrite: false }] });
  assert.deepEqual(buildFillPlan(options, ["f1", "f2"], SIGNUP).fields[1], { id: "f2", kind: "nickname", overwrite: true });
  assert.throws(() => buildFillPlan(options, [], SIGNUP), /Tick at least one/);
  assert.throws(() => buildFillPlan(options, ["not-offered"], SIGNUP), /Tick at least one/);
});
