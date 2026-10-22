// LeakTrace autofill detector. Injected only into the tab where the user opened
// the LeakTrace popup (activeTab). It:
// - classifies inputs from attributes and labels only (never page text wholesale);
// - never reads password values, and never looks at password, one-time-code,
//   payment, security-question or hidden fields beyond counting password inputs;
// - fills nothing until the popup sends a plan the user confirmed;
// - never submits forms or clicks anything, and adds no UI to the page.
// Runs in the extension's isolated world; page scripts cannot call it.
(() => {
  "use strict";
  const g = globalThis;
  if (g.__leaktraceAutofill) return; // already installed in this tab; each popup connection rescans

  const MAX_INPUTS_PER_DOCUMENT = 200;
  const MAX_FIELDS = 20;
  const MAX_FRAMES = 10;
  const MAX_LABEL = 60;
  const OBSERVE_MS = 120_000;
  const MAX_RESCANS = 40;
  const RESCAN_DELAY_MS = 300;

  // Field descriptions containing any of these are never offered or filled.
  const SENSITIVE = new RegExp([
    "pass(word|wd|code|phrase)?", "\\bpin\\b", "otp", "one.?time", "2fa", "mfa", "totp", "verif\\w*.?code",
    "auth\\w*.?code", "security", "secret", "answer", "question", "token", "captcha", "card", "cc.?(num|name|exp|csc)",
    "cvv", "cvc", "expir", "iban", "swift", "routing", "account.?(number|no)", "ssn", "social.?security", "tax.?id",
    "coupon", "promo", "search", "zip", "postal", "phone", "mobile", "\\btel\\b", "street", "address.?line",
    "billing", "shipping", "home.?address", "city",
    "birth", "\\bdob\\b", "last.?name", "sur.?name", "family.?name",
  ].join("|"), "i");
  const BLOCKED_AUTOCOMPLETE = /(^|\s)(one-time-code|current-password|new-password|cc-\S+|family-name|tel\S*|street-address|address-\S+|postal-code|bday\S*)(\s|$)/;
  const FILLABLE_TYPES = new Set(["", "text", "email"]);

  function clean(text, max = MAX_LABEL) {
    const value = String(text ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
  }

  /** Classify a field description: "email", "username", "nickname", "name" or null. Pure. */
  function classify(d) {
    if (String(d.tag ?? "").toLowerCase() !== "input") return null;
    const type = String(d.type ?? "").toLowerCase();
    if (!FILLABLE_TYPES.has(type)) return null;
    const ac = String(d.autocomplete ?? "").toLowerCase();
    if (BLOCKED_AUTOCOMPLETE.test(ac)) return null;
    const hay = [d.name, d.id, d.placeholder, d.label, d.ariaLabel].map((v) => String(v ?? "")).join(" ").toLowerCase();
    if (SENSITIVE.test(hay)) return null;
    const tokens = new Set(ac.split(/\s+/).filter(Boolean));
    // The site's own autocomplete hint wins; label and name heuristics come second.
    if (type === "email" || tokens.has("email")) return "email";
    if (tokens.has("username")) return "username";
    if (tokens.has("nickname")) return "nickname";
    if (tokens.has("given-name") || tokens.has("name")) return "name";
    if (/e-?mail/.test(hay)) return "email";
    if (/user.?(name|id)|login.?(id|name)|\blogin\b|account.?name|\bidentifier\b/.test(hay)) return "username";
    if (/nick.?name|display.?name|screen.?name|public.?name/.test(hay)) return "nickname";
    if (/first.?name|given.?name|full.?name|your.?name/.test(hay) || String(d.name ?? "").toLowerCase() === "name") return "name";
    return null;
  }

  /** "signup", "login" or "unknown" from what a form contains. Pure. */
  function formKind({ passwordCount, newPassword, currentPassword = false, kinds }) {
    if (newPassword || passwordCount >= 2) return "signup";
    // A single password field marked current-password is a login form, even if
    // it also has other inputs (those are then not offered).
    if (passwordCount === 1 && currentPassword) return "login";
    if (kinds.includes("nickname") || kinds.includes("name")) return "signup";
    if (passwordCount === 1) return "login";
    return "unknown";
  }

  g.__leaktraceAutofill = { classify, formKind, clean };
  if (typeof chrome === "undefined" || !chrome.runtime?.onConnect) return; // loaded for testing only

  // ---------- DOM ----------

  let nextId = 1;
  const ids = new WeakMap();
  const refs = new Map();

  function idFor(el) {
    if (!ids.has(el)) {
      const id = `f${nextId++}`;
      ids.set(el, id);
      refs.set(id, new WeakRef(el));
    }
    return ids.get(el);
  }

  function labelText(el) {
    const doc = el.ownerDocument;
    const parts = [];
    for (const label of el.labels ?? []) parts.push(label.textContent);
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) for (const id of labelledBy.split(/\s+/)) parts.push(doc.getElementById(id)?.textContent);
    return clean(parts.filter(Boolean).join(" "), 120);
  }

  function describe(el) {
    return {
      tag: el.tagName, type: el.getAttribute("type") ?? "", autocomplete: el.getAttribute("autocomplete") ?? "",
      name: el.getAttribute("name") ?? "", id: el.id ?? "", placeholder: el.getAttribute("placeholder") ?? "",
      label: labelText(el), ariaLabel: el.getAttribute("aria-label") ?? "",
    };
  }

  function visible(el) {
    if (!el.isConnected || el.disabled || el.readOnly || el.getAttribute("aria-hidden") === "true") return false;
    if (el.closest("[hidden], [inert]")) return false;
    const style = el.ownerDocument.defaultView.getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none" && el.getClientRects().length > 0;
  }

  function documents() {
    const docs = [{ doc: document, frame: false }];
    const queue = [...document.querySelectorAll("iframe, frame")];
    while (queue.length && docs.length <= MAX_FRAMES) {
      const frame = queue.shift();
      let inner = null;
      try {
        inner = frame.contentDocument; // null or throws for cross-origin frames: skipped
      } catch {
        inner = null;
      }
      if (inner?.documentElement) {
        docs.push({ doc: inner, frame: true });
        queue.push(...inner.querySelectorAll("iframe, frame"));
      }
    }
    return docs;
  }

  function scan() {
    const fields = [];
    for (const { doc, frame } of documents()) {
      const inputs = [...doc.querySelectorAll("input")].slice(0, MAX_INPUTS_PER_DOCUMENT);
      const groups = new Map(); // form (or document) -> candidates and password counts
      for (const el of inputs) {
        const key = el.form ?? doc;
        if (!groups.has(key)) groups.set(key, { passwordCount: 0, newPassword: false, currentPassword: false, candidates: [] });
        const group = groups.get(key);
        if ((el.getAttribute("type") ?? "").toLowerCase() === "password") {
          // Only the element's type and autocomplete attribute are looked at, never its value.
          group.passwordCount += 1;
          const hint = el.getAttribute("autocomplete") ?? "";
          if (/new-password/i.test(hint)) group.newPassword = true;
          if (/current-password/i.test(hint)) group.currentPassword = true;
          continue;
        }
        if (!visible(el)) continue;
        const d = describe(el);
        const kind = classify(d);
        if (kind) group.candidates.push({ el, kind, d });
      }
      for (const group of groups.values()) {
        const kinds = group.candidates.map((c) => c.kind);
        const form = formKind({ ...group, kinds });
        for (const { el, kind, d } of group.candidates) {
          // Login and unknown forms: offer only the identifier field.
          if (form !== "signup" && (kind === "nickname" || kind === "name")) continue;
          fields.push({
            id: idFor(el), kind, form, frame,
            label: clean(d.label || d.ariaLabel || d.placeholder || d.name || d.id || kind),
            empty: el.value === "",
          });
          if (fields.length >= MAX_FIELDS) return fields;
        }
      }
    }
    return fields;
  }

  const nativeValueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;

  function fill(plan) {
    const values = { email: plan.alias, username: plan.alias, nickname: plan.nickname, name: plan.nickname };
    return (Array.isArray(plan.fields) ? plan.fields : []).map(({ id, kind, overwrite }) => {
      const el = refs.get(id)?.deref();
      // Re-check everything at fill time: the page may have changed since the scan.
      if (!el || !visible(el)) return { id, filled: false, reason: "field is gone or hidden" };
      if ((el.getAttribute("type") ?? "").toLowerCase() === "password") return { id, filled: false, reason: "not allowed" };
      if (classify(describe(el)) !== kind) return { id, filled: false, reason: "field changed" };
      const value = values[kind];
      if (typeof value !== "string" || !value) return { id, filled: false, reason: "no value for this field" };
      if (el.value !== "" && overwrite !== true) return { id, filled: false, reason: "already has a value" };
      nativeValueSetter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return { id, filled: true };
    });
  }

  // ---------- popup connection ----------

  chrome.runtime.onConnect.addListener((port) => {
    if (port.name !== "leaktrace-autofill" || port.sender?.id !== chrome.runtime.id) return;
    let observer = null;
    let timer = null;
    let stopTimer = null;
    let rescans = 0;
    let lastSignature = "";

    function report() {
      const fields = scan();
      const signature = JSON.stringify(fields);
      if (signature === lastSignature) return; // no duplicate suggestions
      lastSignature = signature;
      port.postMessage({ type: "fields", fields });
    }
    function stop() {
      observer?.disconnect();
      observer = null;
      clearTimeout(timer);
      clearTimeout(stopTimer);
    }

    report();
    observer = new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        rescans += 1;
        report();
        if (rescans >= MAX_RESCANS) stop();
      }, RESCAN_DELAY_MS);
    });
    observer.observe(document.documentElement, {
      childList: true, subtree: true, attributes: true,
      attributeFilter: ["type", "hidden", "disabled", "readonly", "style", "class", "aria-hidden", "autocomplete"],
    });
    stopTimer = setTimeout(stop, OBSERVE_MS);

    port.onMessage.addListener((message) => {
      if (message?.type === "fill") {
        port.postMessage({ type: "filled", results: fill(message.plan ?? {}) });
      } else if (message?.type === "stop") {
        stop();
      }
    });
    port.onDisconnect.addListener(stop);
  });
})();
