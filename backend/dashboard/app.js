// LeakTrace local dashboard. Plain JavaScript, no dependencies.
// All data is rendered with textContent / DOM nodes, never as HTML.
"use strict";

const API = "/dashboard/api";
const PAGE_SIZE = 20;
const STATUS_LABELS = {
  matched: "Matched", ambiguous: "Ambiguous", no_match: "No match", unprocessed: "Unprocessed",
};
const ACTION_LABELS = { accepted: "Accepted", declined: "Declined", notice_only: "Only saw the notice" };
const state = { userId: null, offsets: { signups: 0, emails: 0, receipts: 0 }, emailStatus: "" };

// ---------- helpers ----------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

const timeFormat = new Intl.DateTimeFormat("en-GB", {
  year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  timeZone: "UTC", hour12: false,
});

function formatTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : `${timeFormat.format(date)} UTC`;
}

function statusBadge(status) {
  const key = status ?? "unprocessed";
  return el("span", { class: `badge badge-${key}` }, STATUS_LABELS[key] ?? key);
}

function setStatus(section, message, isError = false) {
  const box = section.querySelector("[data-status]");
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.setAttribute("role", isError ? "alert" : "status");
}

function scopeQuery(extra = {}) {
  const params = new URLSearchParams(extra);
  if (state.userId !== null) params.set("user_id", state.userId);
  return params.toString();
}

async function getJSON(url, options) {
  let response;
  try {
    response = await fetch(url, { headers: { accept: "application/json" }, ...options });
  } catch {
    throw new Error("Could not reach the LeakTrace server.");
  }
  let body = null;
  try { body = await response.json(); } catch { /* non-JSON error page */ }
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail
      : Array.isArray(body?.detail) ? "Some values are invalid." : `Request failed (HTTP ${response.status}).`;
    throw new Error(detail);
  }
  return body;
}

function renderPager(name, page, reload) {
  const pager = document.querySelector(`[data-pager="${name}"]`);
  const from = page.total === 0 ? 0 : page.offset + 1;
  const to = page.offset + page.items.length;
  pager.replaceChildren(
    el("button", {
      type: "button", "aria-label": "Previous page",
      onclick: () => { state.offsets[name] = Math.max(0, page.offset - page.limit); reload(); },
    }, "Previous"),
    el("span", { "aria-live": "polite" }, `${from}–${to} of ${page.total}`),
    el("button", {
      type: "button", "aria-label": "Next page",
      onclick: () => { state.offsets[name] = page.offset + page.limit; reload(); },
    }, "Next"),
  );
  pager.children[0].disabled = page.offset === 0;
  pager.children[2].disabled = to >= page.total;
}

// ---------- views ----------

async function loadOverview() {
  const section = document.getElementById("view-overview");
  const cards = document.getElementById("overview-cards");
  setStatus(section, "Loading…");
  cards.replaceChildren();
  try {
    const data = await getJSON(`${API}/overview?${scopeQuery()}`);
    const entries = [
      ["Signups", data.signups_total], ["Ingested emails", data.emails_total],
      ["Matched", data.matched], ["Ambiguous", data.ambiguous],
      ["No match", data.no_match], ["Unprocessed", data.unprocessed],
    ];
    cards.replaceChildren(...entries.map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, value))));
    setStatus(section, data.emails_total === 0 && data.signups_total === 0 ? "No records in this scope yet." : "");
  } catch (error) {
    setStatus(section, error.message, true);
  }
}

async function loadSignups() {
  const section = document.getElementById("view-signups");
  const body = document.getElementById("signups-body");
  setStatus(section, "Loading…");
  body.replaceChildren();
  try {
    const page = await getJSON(`${API}/signups?${scopeQuery({ limit: PAGE_SIZE, offset: state.offsets.signups })}`);
    body.replaceChildren(...page.items.map((s) => {
      const markers = [s.alias_masked ? "alias" : null, s.has_nickname ? "nickname" : null,
        s.has_surname_variant ? "surname variant" : null].filter(Boolean).join(", ") || "none";
      return el("tr", {},
        el("td", {}, s.site_name),
        el("td", {}, s.site_domain ?? "—"),
        el("td", {}, s.alias_masked ?? "—"),
        el("td", {}, markers + (s.real_name_required ? " · real name required" : "")),
        el("td", {}, s.email_count),
        el("td", {}, formatTime(s.created_at)));
    }));
    renderPager("signups", page, loadSignups);
    setStatus(section, page.total === 0 ? "No signups in this scope." : "");
  } catch (error) {
    setStatus(section, error.message, true);
  }
}

async function loadEmails() {
  const section = document.getElementById("view-emails");
  const body = document.getElementById("emails-body");
  setStatus(section, "Loading…");
  body.replaceChildren();
  const params = { limit: PAGE_SIZE, offset: state.offsets.emails };
  if (state.emailStatus) params.status = state.emailStatus;
  try {
    const page = await getJSON(`${API}/emails?${scopeQuery(params)}`);
    body.replaceChildren(...page.items.map((m) => el("tr", {},
      el("td", {}, formatTime(m.received_at)),
      el("td", {}, statusBadge(m.match_status)),
      el("td", {}, m.match_confidence ?? "—"),
      el("td", {}, m.site_name ? `${m.site_name}${m.site_domain ? ` (${m.site_domain})` : ""}`
        : m.recipient_known ? "Known alias" : "Unknown alias"),
      el("td", {}, m.sender_domain ?? "—"),
      el("td", {}, el("button", {
        type: "button", "aria-label": `Show match details for email ${m.id}`,
        onclick: () => showEmailDetail(m.id),
      }, "Details")))));
    renderPager("emails", page, loadEmails);
    setStatus(section, page.total === 0 ? "No ingested emails in this scope." : "");
  } catch (error) {
    setStatus(section, error.message, true);
  }
}

function list(items) {
  return el("ul", {}, ...items.map((item) => el("li", {}, item)));
}

async function showEmailDetail(id) {
  const panel = document.getElementById("email-detail");
  const body = document.getElementById("email-detail-body");
  panel.hidden = false;
  body.replaceChildren(el("p", { role: "status" }, "Loading…"));
  try {
    const d = await getJSON(`${API}/emails/${encodeURIComponent(id)}?${scopeQuery()}`);
    const rows = [
      ["Status", statusBadge(d.match_status)], ["Confidence", d.match_confidence ?? "—"],
      ["Received", formatTime(d.received_at)], ["Recorded", formatTime(d.created_at)],
      ["Signup", d.signup_id ? `#${d.signup_id} ${d.site_name ?? ""}` : "Recipient alias not recognised"],
      ["Site domain", d.site_domain ?? "—"], ["Sender domain (claimed)", d.sender_domain ?? "—"],
    ];
    body.replaceChildren(
      el("p", { class: "notice", role: "note" }, d.notice),
      el("dl", {}, ...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])),
      el("p", { class: "hint" }, d.stored_details),
      el("h4", {}, "Limitations"), list(d.limitations));
  } catch (error) {
    body.replaceChildren(el("p", { class: "error", role: "alert" }, error.message));
  }
  panel.focus();
}

async function runCheck(event) {
  event.preventDefault();
  const section = document.getElementById("view-check");
  const result = document.getElementById("check-result");
  const payload = {};
  for (const [key, value] of new FormData(event.target)) {
    if (String(value).trim()) payload[key] = String(value).trim();
  }
  if (state.userId !== null) payload.user_id = state.userId;
  result.replaceChildren();
  setStatus(section, "Checking…");
  try {
    const r = await getJSON("/matcher/check", {
      method: "POST", headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(payload),
    });
    const matches = r.matches.length === 0 ? [el("p", {}, "No signups in this scope match these clues.")]
      : r.matches.map((m) => el("article", { class: "result" },
        el("h4", {}, `${m.site_name}${m.site_domain ? ` (${m.site_domain})` : ""} — confidence: ${m.confidence}`),
        list(m.signals.map((s) => `${s.type}: ${s.explanation}`))));
    result.replaceChildren(
      el("p", {}, "Result: ", statusBadge(r.status), ` confidence: ${r.confidence}`),
      ...matches,
      ...(r.warnings.length ? [el("h4", {}, "Warnings"), list(r.warnings)] : []),
      el("h4", {}, "Limitations"), list(r.limitations));
    setStatus(section, "");
  } catch (error) {
    setStatus(section, error.message, true);
  }
}

// ---------- consent receipts ----------

function actionLabel(action) {
  return action ? (ACTION_LABELS[action] ?? action) : "Not recorded";
}

function sourceLabel(r) {
  return r.evidence_basis === "user_reported" ? "Manual · user-reported (not verified)" : "Unknown source";
}

async function loadReceipts() {
  const section = document.getElementById("view-receipts");
  const body = document.getElementById("receipts-body");
  setStatus(section, "Loading…");
  body.replaceChildren();
  try {
    const page = await getJSON(`/consent-receipts?${scopeQuery({ limit: PAGE_SIZE, offset: state.offsets.receipts })}`);
    body.replaceChildren(...page.items.map((r) => {
      const kept = [r.source_url ? "URL" : null, r.content_hash ? "hash" : null,
        r.notice_text_stored ? "notice text" : null, r.consent_text_stored ? "consent wording" : null,
        r.notice_version ? "version" : null].filter(Boolean).join(", ") || "none";
      return el("tr", {},
        el("td", {}, formatTime(r.recorded_at)),
        el("td", {}, r.site_name ? `${r.site_name}${r.site_domain ? ` (${r.site_domain})` : ""}` : "Signup deleted"),
        el("td", {}, actionLabel(r.action)),
        el("td", {}, sourceLabel(r)),
        el("td", {}, kept),
        el("td", {}, el("button", {
          type: "button", "aria-label": `Show details for receipt ${r.id}`,
          onclick: () => showReceiptDetail(r.id),
        }, "Details")));
    }));
    renderPager("receipts", page, loadReceipts);
    setStatus(section, page.total === 0 ? "No consent receipts in this scope yet." : "");
  } catch (error) {
    setStatus(section, error.message, true);
  }
}

async function showReceiptDetail(id) {
  const panel = document.getElementById("receipt-detail");
  const body = document.getElementById("receipt-detail-body");
  panel.hidden = false;
  body.replaceChildren(el("p", { role: "status" }, "Loading…"));
  try {
    const r = await getJSON(`/consent-receipts/${encodeURIComponent(id)}?${scopeQuery()}`);
    const rows = [
      ["Site", r.site_name ? `${r.site_name}${r.site_domain ? ` (${r.site_domain})` : ""}` : "Signup deleted"],
      ["Reported action", actionLabel(r.action)],
      ["Source", sourceLabel(r)],
      ["Recorded by LeakTrace (server time)", formatTime(r.recorded_at)],
      ["Reported event time (unverified)", r.reported_occurred_at ? formatTime(r.reported_occurred_at) : "Not reported"],
      ["Notice URL (not fetched)", r.source_url ?? "—"],
      ["Notice version", r.notice_version ?? "—"],
      ["Notice hash", r.content_hash ?? "—"],
    ];
    body.replaceChildren(
      el("p", { class: "notice", role: "note" }, r.legal_notice),
      el("dl", {}, ...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])),
      el("p", { class: "hint" }, r.timestamp_note),
      el("h4", {}, "Notice text"),
      r.notice_text ? el("div", { class: "prewrap" }, r.notice_text) : el("p", {}, "Not stored."),
      el("h4", {}, "Consent prompt wording"),
      r.consent_text ? el("div", { class: "prewrap" }, r.consent_text) : el("p", {}, "Not stored."));
  } catch (error) {
    body.replaceChildren(el("p", { class: "error", role: "alert" }, error.message));
  }
  panel.focus();
}

async function sha256Hex(text) {
  if (!globalThis.crypto?.subtle) throw new Error("This browser cannot compute the hash here; tick “Also store the notice text”.");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function createReceipt(event) {
  event.preventDefault();
  const form = event.target;
  const status = document.getElementById("receipt-form-status");
  status.classList.remove("error");
  status.textContent = "Saving…";
  try {
    const payload = {};
    for (const [key, value] of new FormData(form)) {
      if (String(value).trim()) payload[key] = key === "notice_text" || key === "consent_text" ? String(value) : String(value).trim();
    }
    payload.signup_id = Number(payload.signup_id);
    if (payload.reported_occurred_at) {
      const when = new Date(payload.reported_occurred_at);
      if (Number.isNaN(when.getTime())) throw new Error("The event time is not a valid date.");
      payload.reported_occurred_at = when.toISOString();
    }
    if (payload.notice_text && !document.getElementById("receipt-store-text").checked) {
      payload.content_hash = await sha256Hex(payload.notice_text);
      delete payload.notice_text;
    }
    const saved = await getJSON(`/consent-receipts?${scopeQuery()}`, {
      method: "POST", headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(payload),
    });
    form.reset();
    status.textContent = `Saved receipt ${saved.id} as user-reported.`;
    state.offsets.receipts = 0;
    await loadReceipts();
  } catch (error) {
    status.textContent = error.message;
    status.classList.add("error");
  }
}

// ---------- tabs and scope ----------

const loaders = {
  overview: loadOverview, signups: loadSignups, emails: loadEmails, check: () => {}, receipts: loadReceipts,
};

function selectTab(tab, focus = false) {
  for (const t of document.querySelectorAll('[role="tab"]')) {
    const selected = t === tab;
    t.setAttribute("aria-selected", String(selected));
    t.tabIndex = selected ? 0 : -1;
    document.getElementById(t.getAttribute("aria-controls")).hidden = !selected;
  }
  if (focus) tab.focus();
  loaders[tab.id.replace("tab-", "")]();
}

function currentTab() {
  return document.querySelector('[role="tab"][aria-selected="true"]');
}

document.addEventListener("DOMContentLoaded", () => {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  for (const tab of tabs) {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      const index = tabs.indexOf(tab);
      const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      selectTab(tabs[(next + tabs.length) % tabs.length], true);
    });
  }

  document.getElementById("scope-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const raw = document.getElementById("scope-user").value.trim();
    const error = document.getElementById("scope-error");
    if (raw && !/^[1-9]\d{0,18}$/.test(raw)) {
      error.textContent = "User ID must be a positive whole number.";
      error.hidden = false;
      return;
    }
    error.hidden = true;
    state.userId = raw || null;
    state.offsets = { signups: 0, emails: 0, receipts: 0 };
    document.getElementById("email-detail").hidden = true;
    document.getElementById("receipt-detail").hidden = true;
    selectTab(currentTab());
  });

  document.getElementById("email-status").addEventListener("change", (event) => {
    state.emailStatus = event.target.value;
    state.offsets.emails = 0;
    loadEmails();
  });
  document.getElementById("email-detail-close").addEventListener("click", () => {
    document.getElementById("email-detail").hidden = true;
  });
  document.getElementById("check-form").addEventListener("submit", runCheck);
  document.getElementById("receipt-form").addEventListener("submit", createReceipt);
  document.getElementById("receipt-detail-close").addEventListener("click", () => {
    document.getElementById("receipt-detail").hidden = true;
  });

  loadOverview();
});
