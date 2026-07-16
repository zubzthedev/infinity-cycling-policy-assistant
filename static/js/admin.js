// Administration page: view app status, upload/replace/delete policies,
// and trigger a manual reload - all via the protected /api/admin/* endpoints.

function renderStatus(data) {
  const statusEl = document.getElementById("admin-status");
  if (!statusEl) return;

  let html =
    "<ul>" +
    "<li>Environment: " + data.environment + "</li>" +
    "<li>Gemini model: " + data.gemini_model + "</li>" +
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

    const actionCell = document.createElement("td");
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "nav-link-button";
    deleteButton.textContent = "Delete";
    deleteButton.addEventListener("click", () => deletePolicy(policy.slug));
    actionCell.appendChild(deleteButton);
    row.appendChild(actionCell);

    body.appendChild(row);
  });
}

function showUploadMessage(message, isError) {
  const el = document.getElementById("upload-message");
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

async function deletePolicy(slug) {
  if (!window.confirm("Delete this policy? This cannot be undone.")) return;
  try {
    const response = await window.AskOufyAuth.authorizedFetch("/api/admin/policies/" + slug, {
      method: "DELETE",
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Delete failed (" + response.status + ").");
    }
    await refreshStatus();
  } catch (error) {
    window.alert(error.message || "Delete failed.");
  }
}

async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await window.AskOufyAuth.authorizedFetch("/api/admin/policies", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Upload failed (" + response.status + ").");
    }
    showUploadMessage("Policy uploaded and reloaded successfully.", false);
    await refreshStatus();
  } catch (error) {
    showUploadMessage(error.message || "Upload failed.", true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const uploadForm = document.getElementById("upload-form");
  const fileInput = document.getElementById("upload-file-input");
  if (uploadForm && fileInput) {
    uploadForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const file = fileInput.files[0];
      if (!file) return;
      uploadFile(file);
    });
  }

  const reloadButton = document.getElementById("reload-button");
  if (reloadButton) {
    reloadButton.addEventListener("click", async () => {
      try {
        const response = await window.AskOufyAuth.authorizedFetch("/api/admin/reload", {
          method: "POST",
        });
        if (!response.ok) throw new Error("Reload failed (" + response.status + ").");
        await refreshStatus();
      } catch (error) {
        window.alert(error.message || "Reload failed.");
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
