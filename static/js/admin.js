// Administration page: view app status and trigger a reload - policies
// themselves are managed either in the checked-in policies/ folder or,
// day to day, directly in the shared Google Drive folder (see the
// "Managing Policies" notice, shown when POLICY_SOURCE=drive).

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

function showReloadMessage(message, isError) {
  const el = document.getElementById("reload-message");
  if (!el) return;
  el.hidden = false;
  el.textContent = message;
  el.classList.toggle("admin-message-error", Boolean(isError));
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

document.addEventListener("DOMContentLoaded", () => {
  const reloadButton = document.getElementById("reload-button");
  if (reloadButton) {
    reloadButton.addEventListener("click", async () => {
      reloadButton.disabled = true;
      try {
        const response = await window.AskOufyAuth.authorizedFetch("/api/admin/reload", {
          method: "POST",
        });
        if (!response.ok) throw new Error("Reload failed (" + response.status + ").");
        await refreshStatus();
        showReloadMessage("Reloaded successfully.", false);
      } catch (error) {
        showReloadMessage(error.message || "Reload failed.", true);
      } finally {
        reloadButton.disabled = false;
      }
    });
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
  if (user) {
    refreshStatus().catch((error) => {
      const statusEl = document.getElementById("admin-status");
      if (statusEl) statusEl.textContent = error.message || "Could not load status.";
    });
  }
});
