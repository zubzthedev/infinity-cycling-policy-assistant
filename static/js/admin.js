// Administration page: view app status, reload, and edit the prompt
// framework. Policies themselves are managed either in the checked-in
// policies/ folder or, day to day, directly in the shared Google Drive
// folder (see the "Managing Policies" notice, shown when POLICY_SOURCE=drive).

function renderStatus(data) {
  const statusEl = document.getElementById("admin-status");
  if (!statusEl) return;

  let html =
    "<ul>" +
    "<li>Environment: " + data.environment + "</li>" +
    "<li>Gemini model: " + data.gemini_model + "</li>" +
    "<li>Policy source: " + data.policy_source + "</li>" +
    "<li>Prompts loaded: " + (data.prompts_loaded ? "yes" : "no") + "</li>" +
    "<li>Policies loaded: " + data.policies.length + "</li>" +
    "<li>Policy load errors: " + data.policy_load_errors.length + "</li>" +
    "</ul>";

  if (data.policy_load_errors.length) {
    const errorItems = data.policy_load_errors
      .map((e) => "<li>" + e.filename + ": " + e.error + "</li>")
      .join("");
    html += '<p>Load errors:</p><ul class="admin-errors">' + errorItems + "</ul>";
  }

  statusEl.innerHTML = html;

  const driveNotice = document.getElementById("drive-notice");
  if (driveNotice) {
    driveNotice.hidden = data.policy_source !== "drive";
  }
}

function renderPoliciesTable(policiesList) {
  const body = document.getElementById("policies-table-body");
  if (!body) return;
  body.innerHTML = "";

  policiesList.forEach((policy) => {
    const row = document.createElement("tr");

    const titleCell = document.createElement("td");
    titleCell.textContent = policy.title;
    row.appendChild(titleCell);

    const filenameCell = document.createElement("td");
    filenameCell.textContent = policy.filename;
    row.appendChild(filenameCell);

    const slugCell = document.createElement("td");
    slugCell.textContent = policy.slug;
    row.appendChild(slugCell);

    body.appendChild(row);
  });
}

function showMessage(elementId, message, isError) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.hidden = false;
  el.textContent = message;
  el.classList.toggle("admin-message-error", Boolean(isError));
  el.classList.toggle("admin-message-success", !isError);
}

function hideMessage(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.hidden = true;
}

async function refreshStatus() {
  const response = await window.AskOufyAuth.authorizedFetch("/api/admin/status");
  if (!response.ok) {
    throw new Error("Failed to load status (" + response.status + ").");
  }
  const data = await response.json();
  renderStatus(data);
  renderPoliciesTable(data.policies);
}

async function handleReloadClick() {
  const reloadButton = document.getElementById("reload-button");
  if (!reloadButton) return;

  const originalText = reloadButton.textContent;
  reloadButton.disabled = true;
  reloadButton.textContent = "Reloading...";
  hideMessage("reload-message");

  try {
    const response = await window.AskOufyAuth.authorizedFetch("/api/admin/reload", {
      method: "POST",
    });
    if (!response.ok) throw new Error("Reload failed (" + response.status + ").");
    await refreshStatus();
    showMessage(
      "reload-message",
      "Reloaded successfully at " + new Date().toLocaleTimeString() + ".",
      false
    );
  } catch (error) {
    showMessage("reload-message", error.message || "Reload failed.", true);
  } finally {
    reloadButton.disabled = false;
    reloadButton.textContent = originalText;
  }
}

async function loadPromptsIntoForm() {
  const response = await window.AskOufyAuth.authorizedFetch("/api/admin/prompts");
  if (!response.ok) {
    throw new Error("Failed to load prompts (" + response.status + ").");
  }
  const data = await response.json();
  document.getElementById("prompt-system").value = data.system;
  document.getElementById("prompt-response-rules").value = data.response_rules;
  document.getElementById("prompt-examples").value = data.examples;
}

async function handleSavePromptsClick() {
  const saveButton = document.getElementById("save-prompts-button");
  if (!saveButton) return;

  const payload = {
    system: document.getElementById("prompt-system").value,
    response_rules: document.getElementById("prompt-response-rules").value,
    examples: document.getElementById("prompt-examples").value,
  };

  const originalText = saveButton.textContent;
  saveButton.disabled = true;
  saveButton.textContent = "Saving...";
  hideMessage("prompts-message");

  try {
    const response = await window.AskOufyAuth.authorizedFetch("/api/admin/prompts", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Save failed (" + response.status + ").");
    }
    await refreshStatus();
    showMessage(
      "prompts-message",
      "Saved and reloaded at " + new Date().toLocaleTimeString() + ".",
      false
    );
  } catch (error) {
    showMessage("prompts-message", error.message || "Save failed.", true);
  } finally {
    saveButton.disabled = false;
    saveButton.textContent = originalText;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const reloadButton = document.getElementById("reload-button");
  if (reloadButton) {
    reloadButton.addEventListener("click", handleReloadClick);
  }

  const savePromptsButton = document.getElementById("save-prompts-button");
  if (savePromptsButton) {
    savePromptsButton.addEventListener("click", handleSavePromptsClick);
  }

  const signOutButton = document.getElementById("sign-out");
  if (signOutButton) {
    signOutButton.addEventListener("click", () => {
      askOufyAuth.signOut().then(() => {
        window.location.href = "/login";
      });
    });
  }
});

askOufyAuth.onAuthStateChanged((user) => {
  if (!user) return;

  refreshStatus().catch((error) => {
    const statusEl = document.getElementById("admin-status");
    if (statusEl) statusEl.textContent = error.message || "Could not load status.";
  });

  loadPromptsIntoForm().catch((error) => {
    showMessage("prompts-message", error.message || "Could not load prompts.", true);
  });
});
