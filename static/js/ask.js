// Landing page interactions for Ask Oufy: submit questions and render
// response cards.

function setStatus(message, isError) {
  const statusEl = document.getElementById("ask-status");
  if (!statusEl) return;
  if (!message) {
    statusEl.hidden = true;
    statusEl.textContent = "";
    return;
  }
  statusEl.hidden = false;
  statusEl.textContent = message;
  statusEl.classList.toggle("ask-status-error", Boolean(isError));
}

function showToast(message) {
  let toast = document.getElementById("ask-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "ask-toast";
    toast.className = "ask-toast";
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add("ask-toast-visible");
  clearTimeout(toast._hideTimeout);
  toast._hideTimeout = window.setTimeout(() => {
    toast.classList.remove("ask-toast-visible");
  }, 2200);
}

function exportCardToPdf(card) {
  card.classList.add("print-target");
  window.print();
}

window.addEventListener("afterprint", () => {
  document.querySelectorAll(".print-target").forEach((el) => {
    el.classList.remove("print-target");
  });
});

function renderResponseCard(question, answerHtml) {
  const resultsEl = document.getElementById("ask-results");
  if (!resultsEl) return null;

  const card = document.createElement("article");
  card.className = "response-card";

  const heading = document.createElement("h2");
  heading.className = "response-card-question";
  heading.textContent = question;

  const toolbar = document.createElement("div");
  toolbar.className = "response-card-toolbar";
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.className = "export-pdf-button";
  exportButton.textContent = "Export to PDF";
  exportButton.addEventListener("click", () => exportCardToPdf(card));
  toolbar.appendChild(exportButton);

  const body = document.createElement("div");
  body.className = "response-card-body";
  body.innerHTML = answerHtml;

  card.appendChild(heading);
  card.appendChild(toolbar);
  card.appendChild(body);
  resultsEl.prepend(card);
  return card;
}

function getSelectedSections() {
  const checkboxes = document.querySelectorAll(".section-checkbox");
  if (!checkboxes.length) return null;
  return Array.from(checkboxes)
    .filter((checkbox) => checkbox.checked)
    .map((checkbox) => checkbox.value);
}

async function submitQuestion(question) {
  const submitButton = document.getElementById("ask-submit");
  submitButton.disabled = true;
  setStatus("Ask Oufy is reviewing the club policies...", false);

  try {
    const response = await window.AskOufyAuth.authorizedFetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, sections: getSelectedSections() }),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Request failed (" + response.status + ").");
    }

    const data = await response.json();
    const card = renderResponseCard(question, data.answer_html);
    setStatus("", false);
    showToast("Ask Oufy has answered");
    if (card) {
      card.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    setStatus(error.message || "Something went wrong. Please try again.", true);
  } finally {
    submitButton.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("ask-form");
  const input = document.getElementById("question-input");

  if (form && input) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const question = input.value.trim();
      if (!question) return;
      submitQuestion(question);
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
