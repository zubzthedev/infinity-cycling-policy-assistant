// Landing page interactions for Ask Oufy: submit questions, render response
// cards, and wire up example-question shortcuts.

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

function renderResponseCard(answerHtml) {
  const resultsEl = document.getElementById("ask-results");
  if (!resultsEl) return;

  const card = document.createElement("article");
  card.className = "response-card";
  card.innerHTML = answerHtml;
  resultsEl.prepend(card);
}

async function submitQuestion(question) {
  const submitButton = document.getElementById("ask-submit");
  submitButton.disabled = true;
  setStatus("Ask Oufy is reviewing the club policies...", false);

  try {
    const response = await window.AskOufyAuth.authorizedFetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question }),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Request failed (" + response.status + ").");
    }

    const data = await response.json();
    renderResponseCard(data.answer_html);
    setStatus("", false);
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

  document.querySelectorAll(".example-question").forEach((button) => {
    button.addEventListener("click", () => {
      if (!input) return;
      input.value = button.textContent.trim();
      input.focus();
    });
  });

  const signOutButton = document.getElementById("sign-out");
  if (signOutButton) {
    signOutButton.addEventListener("click", () => {
      askOufyAuth.signOut().then(() => {
        window.location.href = "/login";
      });
    });
  }
});
