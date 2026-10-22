import { normalizeNeverSites, removeNeverSite, validateBaseUrl } from "./src/lib.js";
import { el, show } from "./src/dom.js";

const form = document.getElementById("settings-form");
const input = document.getElementById("base-url");
const status = document.getElementById("status");

function say(message, isError = false) {
  status.textContent = message;
  status.classList.toggle("error", isError);
}

try {
  const { baseUrl } = await chrome.storage.local.get("baseUrl");
  if (baseUrl) input.value = baseUrl;
} catch {
  say("Could not read the saved setting.", true);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const baseUrl = validateBaseUrl(input.value);
    await chrome.storage.local.set({ baseUrl });
    input.value = baseUrl;
    say(`Saved. The popup will use ${baseUrl}.`);
  } catch (error) {
    say(error.message, true);
  }
});

document.getElementById("clear").addEventListener("click", async () => {
  try {
    await chrome.storage.local.remove("baseUrl");
    input.value = "";
    say("Cleared. The popup is disabled until a backend URL is saved.");
  } catch {
    say("Could not clear the setting.", true);
  }
});

// ---------- autofill settings ----------

const autofillToggle = document.getElementById("autofill-enabled");
const neverList = document.getElementById("never-list");
const autofillStatus = document.getElementById("autofill-status");

function sayAutofill(message, isError = false) {
  autofillStatus.textContent = message;
  autofillStatus.classList.toggle("error", isError);
}

async function renderNeverList() {
  const { neverSites } = await chrome.storage.local.get("neverSites");
  const sites = normalizeNeverSites(neverSites);
  if (!sites.length) {
    show(neverList, el("li", { class: "hint" }, "None."));
    return;
  }
  show(neverList, sites.map((host) => el("li", {}, `${host} `, el("button", {
    type: "button", class: "secondary", "aria-label": `Allow suggestions on ${host} again`,
    onclick: async () => {
      await chrome.storage.local.set({ neverSites: removeNeverSite(sites, host) });
      sayAutofill(`Suggestions allowed again on ${host}.`);
      await renderNeverList();
    },
  }, "Remove"))));
}

try {
  const { autofillEnabled } = await chrome.storage.local.get("autofillEnabled");
  autofillToggle.checked = autofillEnabled !== false;
  await renderNeverList();
} catch {
  sayAutofill("Could not read the autofill settings.", true);
}

autofillToggle.addEventListener("change", async () => {
  try {
    await chrome.storage.local.set({ autofillEnabled: autofillToggle.checked });
    sayAutofill(autofillToggle.checked ? "Autofill suggestions are on." : "Autofill suggestions are off.");
  } catch {
    sayAutofill("Could not save the autofill setting.", true);
  }
});

document.getElementById("never-clear").addEventListener("click", async () => {
  try {
    await chrome.storage.local.set({ neverSites: [] });
    sayAutofill("Cleared. Suggestions may appear again on those sites.");
    await renderNeverList();
  } catch {
    sayAutofill("Could not clear the list.", true);
  }
});
