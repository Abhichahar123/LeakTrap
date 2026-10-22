// The detector's pure classification rules, loaded without browser APIs.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../content/autofill.js", import.meta.url), "utf8");
const sandbox = {};
vm.runInNewContext(source, sandbox);
const { classify, formKind, clean } = sandbox.__leaktraceAutofill;
const input = (attrs) => ({ tag: "INPUT", type: "text", ...attrs });

test("loading without chrome APIs only exposes pure helpers (no listeners, no DOM access)", () => {
  assert.deepEqual(Object.keys(sandbox.__leaktraceAutofill).sort(), ["classify", "clean", "formKind"]);
});

for (const [name, attrs, expected] of [
  ["type=email", { type: "email" }, "email"],
  ["autocomplete=email", { autocomplete: "email" }, "email"],
  ["label 'Email address'", { label: "Email address" }, "email"],
  ["name=e-mail", { name: "e-mail" }, "email"],
  ["autocomplete=username", { autocomplete: "username" }, "username"],
  ["name=user_name", { name: "user_name" }, "username"],
  ["id=login", { id: "login" }, "username"],
  ["autocomplete=nickname", { autocomplete: "nickname" }, "nickname"],
  ["label 'Display name'", { label: "Display name" }, "nickname"],
  ["autocomplete=given-name", { autocomplete: "given-name" }, "name"],
  ["label 'First name'", { label: "First name" }, "name"],
  ["name=name", { name: "name" }, "name"],
  // Regression: an explicit autocomplete hint beats label text.
  ["'Email or username' with autocomplete=username", { label: "Email or username", autocomplete: "username" }, "username"],
  ["type=email beats a 'username' label", { type: "email", label: "Username" }, "email"],
]) {
  test(`classifies ${name} as ${expected}`, () => assert.equal(classify(input(attrs)), expected));
}

for (const [name, attrs] of [
  ["password type", { type: "password", name: "email" }],
  ["hidden type", { type: "hidden", name: "email" }],
  ["number/tel/search/checkbox types", { type: "tel", name: "email" }],
  ["search type", { type: "search", name: "username" }],
  ["textarea", { tag: "TEXTAREA", name: "email" }],
  ["select", { tag: "SELECT", name: "email" }],
  ["one-time-code", { autocomplete: "one-time-code", name: "email" }],
  ["current-password autocomplete on text", { autocomplete: "current-password" }],
  ["new-password autocomplete", { autocomplete: "new-password", name: "username" }],
  ["cc-number", { autocomplete: "cc-number" }],
  ["cc-name", { autocomplete: "cc-name", label: "Name on card" }],
  ["OTP by name", { name: "otp", label: "Email code" }],
  ["verification code", { label: "Email verification code" }],
  ["2FA", { name: "2fa_email" }],
  ["security answer", { label: "Security answer", name: "username_hint" }],
  ["security question", { label: "Your security question" }],
  ["card number", { label: "Card number" }],
  ["CVV", { name: "cvv" }],
  ["IBAN", { label: "IBAN" }],
  ["PIN", { label: "PIN" }],
  ["token", { name: "auth_token" }],
  ["captcha", { name: "captcha" }],
  ["family name", { autocomplete: "family-name" }],
  ["last name label", { label: "Last name" }],
  ["surname", { name: "surname" }],
  ["phone", { label: "Phone" }],
  ["street address", { autocomplete: "street-address" }],
  ["search box labelled email", { label: "Search emails" }],
  ["unrelated text", { label: "Company" }],
]) {
  test(`never offers: ${name}`, () => assert.equal(classify(input(attrs)), null));
}

test("form kinds", () => {
  assert.equal(formKind({ passwordCount: 1, newPassword: false, kinds: ["email"] }), "login");
  assert.equal(formKind({ passwordCount: 1, newPassword: true, kinds: ["email"] }), "signup");
  assert.equal(formKind({ passwordCount: 2, newPassword: false, kinds: ["email"] }), "signup");
  assert.equal(formKind({ passwordCount: 0, newPassword: false, kinds: ["email", "nickname"] }), "signup");
  assert.equal(formKind({ passwordCount: 0, newPassword: false, kinds: ["email"] }), "unknown");
  // Regression: a login form that also contains a nickname input is still a login form.
  assert.equal(formKind({ passwordCount: 1, newPassword: false, currentPassword: true, kinds: ["username", "nickname"] }), "login");
  assert.equal(formKind({ passwordCount: 1, newPassword: false, currentPassword: false, kinds: ["email", "name"] }), "signup");
});

test("labels are flattened to short plain text", () => {
  const hostile = '<img src=x onerror=alert(1)>\n\tEmail\u0000 address' + " padding".repeat(20);
  const label = clean(hostile);
  assert.ok(label.length <= 60);
  assert.ok(!/[\u0000-\u001f]/.test(label));
  assert.ok(label.startsWith("<img src=x onerror=alert(1)> Email address"));  // stays text; rendered with textContent
});
