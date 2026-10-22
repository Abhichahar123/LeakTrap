// Pure logic for the LeakTrace extension: validation, payloads and API calls.
// No browser-extension APIs here, so it can be tested with Node.

export const RECEIPT_ACTIONS = ["accepted", "declined", "notice_only"];
const MAX_SITE_NAME = 255;
const MAX_NOTICE_TEXT = 20_000;
const MAX_CONSENT_TEXT = 2_000;
const MAX_VERSION = 100;
const MAX_URL = 2_048;
const LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;

// ---------- hostnames and settings ----------

/** Hostname of an http(s) tab URL, without a leading "www.", or null. */
export function hostnameFromTabUrl(url) {
  if (typeof url !== "string") return null;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  try {
    return normalizeDomain(parsed.hostname);
  } catch {
    return null;
  }
}

/** Lowercase bare domain (punycode for IDNs), or throw. Mirrors the backend rules. */
export function normalizeDomain(value) {
  let domain = String(value ?? "").trim().toLowerCase().replace(/\.$/, "");
  if (!domain) throw new Error("Enter a domain such as example.com.");
  if (/[/:@?#\s]/.test(domain)) throw new Error("Enter only the domain, without https://, paths or ports.");
  try {
    domain = new URL(`http://${domain}`).hostname;
  } catch {
    throw new Error("That is not a valid domain.");
  }
  domain = domain.replace(/^www\./, "");
  const labels = domain.split(".");
  if (domain.length > 253 || labels.length < 2 || !labels.every((l) => LABEL.test(l))) {
    throw new Error("Enter a full domain such as example.com.");
  }
  if (/^\d+$/.test(labels.at(-1))) throw new Error("IP addresses are not accepted.");
  return domain;
}

/** Development backend URL: only http://127.0.0.1:<port> is allowed in this version. */
export function validateBaseUrl(value) {
  const raw = String(value ?? "").trim();
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("Enter a URL such as http://127.0.0.1:8000.");
  }
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1") {
    throw new Error("Only a local development backend at http://127.0.0.1:<port> is supported.");
  }
  if (url.username || url.password || (url.pathname !== "/" && url.pathname !== "") || url.search || url.hash) {
    throw new Error("Enter only the scheme, host and port, e.g. http://127.0.0.1:8000.");
  }
  return url.origin;
}

/** Page address without query string or fragment, which can carry tokens. */
export function policyUrlFromPage(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    return `${parsed.origin}${parsed.pathname}`;
  } catch {
    return null;
  }
}

// ---------- payloads ----------

function cleanLine(value, name, max) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (text.length > max) throw new Error(`${name} must be at most ${max} characters.`);
  return text;
}

/** Body for POST /signups. Never includes user_id: the extension has no way to prove identity. */
export function buildSignupPayload({ siteName, siteDomain, realNameRequired = false, generateNickname = true }) {
  const site_name = cleanLine(siteName, "Website name", MAX_SITE_NAME);
  if (!/[\p{L}\p{N}]/u.test(site_name)) throw new Error("Website name must contain a letter or digit.");
  const payload = {
    site_name,
    site_domain: normalizeDomain(siteDomain),
    real_name_required: Boolean(realNameRequired),
    generate_alias: true,
    generate_nickname: Boolean(generateNickname),
  };
  return payload;
}

export async function sha256Hex(text, subtle = globalThis.crypto?.subtle) {
  if (!subtle) throw new Error("This browser cannot compute SHA-256 here.");
  const digest = await subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Body for POST /consent-receipts. Notice text is reduced to its SHA-256 hash
 * unless storeNoticeText is true.
 */
export async function buildReceiptPayload(form, subtle) {
  const signupId = Number(form.signupId);
  if (!Number.isSafeInteger(signupId) || signupId < 1) throw new Error("Choose a signup first.");
  if (!RECEIPT_ACTIONS.includes(form.action)) throw new Error("Choose what you did: accepted, declined or only saw the notice.");
  const payload = { signup_id: signupId, action: form.action };

  const sourceUrl = String(form.sourceUrl ?? "").trim();
  if (sourceUrl) {
    let parsed;
    try {
      parsed = new URL(sourceUrl);
    } catch {
      throw new Error("Policy URL is not a valid URL.");
    }
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || sourceUrl.length > MAX_URL) {
      throw new Error("Policy URL must be an http or https address without credentials.");
    }
    payload.source_url = sourceUrl;
  }
  const version = cleanLine(form.noticeVersion, "Notice version", MAX_VERSION);
  if (version) payload.notice_version = version;

  const noticeText = String(form.noticeText ?? "");
  if (noticeText.trim()) {
    if (noticeText.length > MAX_NOTICE_TEXT) throw new Error(`Notice text must be at most ${MAX_NOTICE_TEXT} characters.`);
    if (form.storeNoticeText) payload.notice_text = noticeText;
    else payload.content_hash = await sha256Hex(noticeText, subtle);
  }
  const consentText = String(form.consentText ?? "");
  if (consentText.trim()) {
    if (consentText.length > MAX_CONSENT_TEXT) throw new Error(`Consent wording must be at most ${MAX_CONSENT_TEXT} characters.`);
    payload.consent_text = consentText;
  }
  if (form.occurredAt) {
    const when = new Date(form.occurredAt);
    if (Number.isNaN(when.getTime())) throw new Error("Event time is not a valid date.");
    if (when.getTime() > Date.now() + 5 * 60_000) throw new Error("Event time cannot be in the future.");
    payload.reported_occurred_at = when.toISOString();
  }
  if (!payload.source_url && !payload.content_hash && !payload.notice_text && !payload.notice_version && !payload.consent_text) {
    throw new Error("Add at least a policy URL, notice text, version or consent wording.");
  }
  return payload;
}

/** Human-readable lines describing exactly what will be sent. */
export function describePayload(payload) {
  const labels = {
    site_name: "Website name", site_domain: "Website domain", real_name_required: "Site requires real name",
    generate_alias: "Generate alias", generate_nickname: "Generate nickname", signup_id: "Signup ID",
    action: "Reported action", source_url: "Policy URL", notice_version: "Notice version",
    content_hash: "Notice text SHA-256 (text not sent)", notice_text: "Notice text (stored)",
    consent_text: "Consent wording", reported_occurred_at: "Reported event time (UTC)",
  };
  return Object.entries(payload).map(([key, value]) => {
    let shown = typeof value === "boolean" ? (value ? "yes" : "no") : String(value);
    if (key === "notice_text" || key === "consent_text") shown = `${value.length} characters`;
    return [labels[key] ?? key, shown];
  });
}

// ---------- API ----------

export class ApiError extends Error {
  constructor(message, status = null) {
    super(message);
    this.status = status;
  }
}

function errorMessage(status, body) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => {
      const field = Array.isArray(d?.loc) ? d.loc.filter((p) => p !== "body").join(".") : "";
      const msg = String(d?.msg ?? "invalid").replace(/^Value error, /, "");
      return field ? `${field}: ${msg}` : msg;
    }).join("; ");
  }
  if (status === 403) return "The backend refused the request (it only accepts requests from this computer).";
  return `The backend returned HTTP ${status}.`;
}

export function createApi(baseUrl, fetchImpl = globalThis.fetch) {
  const origin = validateBaseUrl(baseUrl);
  async function call(path, init) {
    let response;
    try {
      response = await fetchImpl(`${origin}${path}`, {
        ...init,
        headers: { accept: "application/json", ...(init?.body ? { "content-type": "application/json" } : {}) },
        credentials: "omit",
        cache: "no-store",
      });
    } catch {
      throw new ApiError(`Could not reach the LeakTrace backend at ${origin}. Is it running?`);
    }
    let body = null;
    try {
      body = await response.json();
    } catch {
      // Non-JSON body: handled below.
    }
    if (!response.ok) throw new ApiError(errorMessage(response.status, body), response.status);
    if (body === null || typeof body !== "object") throw new ApiError("The backend returned an unexpected response.");
    return body;
  }
  return {
    origin,
    async createSignup(payload) {
      const body = await call("/signups", { method: "POST", body: JSON.stringify(payload) });
      if (!Number.isSafeInteger(body.id) || typeof body.site_name !== "string") {
        throw new ApiError("The backend returned an unexpected signup response.");
      }
      // Only what the backend actually returned; nothing is filled in locally.
      return {
        id: body.id, siteName: body.site_name, siteDomain: body.site_domain ?? null,
        alias: typeof body.alias === "string" ? body.alias : null,
        nickname: typeof body.nickname === "string" ? body.nickname : null,
        realNameRequired: Boolean(body.real_name_required),
      };
    },
    /** Saved signups for exactly this hostname (no subdomain matching). Never creates anything. */
    async lookupSignups(host) {
      const domain = normalizeDomain(host);
      const body = await call("/autofill/lookup", { method: "POST", body: JSON.stringify({ site_domain: domain }) });
      if (body.site_domain !== domain || !Array.isArray(body.items)) {
        throw new ApiError("The backend returned an unexpected lookup response.");
      }
      return body.items.map(parseRecalledSignup).filter((s) => s !== null && s.siteDomain === domain);
    },
    async createReceipt(payload) {
      const body = await call("/consent-receipts", { method: "POST", body: JSON.stringify(payload) });
      if (!Number.isSafeInteger(body.id)) throw new ApiError("The backend returned an unexpected receipt response.");
      return body;
    },
  };
}

/** Copy text; returns true on success. Must be called from a user click. */
export async function copyText(text, clipboard = globalThis.navigator?.clipboard) {
  if (!text || !clipboard?.writeText) return false;
  try {
    await clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

// ---------- autofill ----------

// Plain lowercase address, as the backend generates (letters, digits, . _ + -).
const ALIAS_SHAPE = /^[a-z0-9](?:[a-z0-9._+-]{0,62}[a-z0-9])?@[a-z0-9-]+(?:\.[a-z0-9-]+)+$/;
const BLOCKED_HOSTS = new Set(["chromewebstore.google.com", "chrome.google.com", "microsoftedge.microsoft.com"]);
export const NEVER_SITES_LIMIT = 500;

/** A recalled signup, or null when the item is malformed. Only backend values are used. */
export function parseRecalledSignup(item) {
  if (!item || typeof item !== "object" || !Number.isSafeInteger(item.id) || item.id < 1) return null;
  if (typeof item.site_name !== "string" || typeof item.site_domain !== "string") return null;
  const alias = typeof item.alias === "string" && ALIAS_SHAPE.test(item.alias) ? item.alias : null;
  const nickname = typeof item.nickname === "string" && item.nickname.trim() ? item.nickname : null;
  return {
    id: item.id, siteName: item.site_name, siteDomain: item.site_domain, alias, nickname,
    realNameRequired: item.real_name_required === true,
  };
}

/** Whether the detector may be injected into a tab with this URL. */
export function canInspectTab(url) {
  const host = hostnameFromTabUrl(url);
  if (!host) return false;
  try {
    return !BLOCKED_HOSTS.has(new URL(url).hostname.toLowerCase());
  } catch {
    return false;
  }
}

/** Valid, de-duplicated opt-out hostnames from storage (anything malformed is dropped). */
export function normalizeNeverSites(value) {
  if (!Array.isArray(value)) return [];
  const out = [];
  for (const host of value) {
    try {
      const domain = normalizeDomain(host);
      if (!out.includes(domain)) out.push(domain);
    } catch {
      // ignore malformed entries
    }
  }
  return out.slice(0, NEVER_SITES_LIMIT);
}

export function addNeverSite(list, host) {
  const domain = normalizeDomain(host);
  const sites = normalizeNeverSites(list).filter((h) => h !== domain);
  return [domain, ...sites].slice(0, NEVER_SITES_LIMIT);
}

export function removeNeverSite(list, host) {
  const domain = normalizeDomain(host);
  return normalizeNeverSites(list).filter((h) => h !== domain);
}

const KIND_LABELS = { email: "Email", username: "Username", nickname: "Nickname", name: "Name" };

/**
 * Which detected fields may be offered for this signup, and whether each is
 * ticked by default. Fields that already have a value are never ticked by
 * default; ticking one means the user explicitly approves replacing it.
 */
export function fillOptions(fields, signup) {
  if (!signup || !Array.isArray(fields)) return [];
  const options = [];
  for (const f of fields) {
    if (!f || typeof f.id !== "string" || !KIND_LABELS[f.kind]) continue;
    const identifier = f.kind === "email" || f.kind === "username";
    if (f.form !== "signup" && !identifier) continue;
    let value = null;
    let ticked = false;
    if (identifier && signup.alias) {
      value = signup.alias;
      ticked = f.empty === true;
    } else if (f.kind === "nickname" && signup.nickname) {
      value = signup.nickname;
      ticked = f.empty === true;
    } else if (f.kind === "name" && signup.nickname && !signup.realNameRequired) {
      value = signup.nickname; // canary nickname in a name field: offered, never ticked by default
    }
    if (value === null) continue;
    options.push({ id: f.id, kind: f.kind, kindLabel: KIND_LABELS[f.kind], label: f.label, empty: f.empty === true, value, ticked });
  }
  return options;
}

/** The plan sent to the page after the user clicks Fill. */
export function buildFillPlan(options, selectedIds, signup) {
  const selected = new Set(selectedIds);
  const fields = options.filter((o) => selected.has(o.id)).map((o) => ({ id: o.id, kind: o.kind, overwrite: !o.empty }));
  if (!fields.length) throw new Error("Tick at least one field to fill.");
  return { alias: signup.alias ?? null, nickname: signup.nickname ?? null, fields };
}
