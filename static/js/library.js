// Policy Library page: fetches the cached policy documents via the
// protected /api/policies endpoint and renders them client-side. Ask
// Oufy's Bearer-token auth model has no way to protect a plain
// server-rendered page navigation, so /library itself is a public shell
// and this API call is where access is actually enforced.

function renderLibrary(documents) {
  const navList = document.getElementById("library-nav-list");
  const content = document.getElementById("library-content");
  if (!navList || !content) return;

  navList.innerHTML = "";
  content.innerHTML = "";

  documents.forEach((doc) => {
    const navLink = document.createElement("a");
    navLink.href = "#" + doc.slug;
    navLink.className = "library-nav-link";
    navLink.textContent = doc.title;
    navList.appendChild(navLink);

    const section = document.createElement("section");
    section.id = doc.slug;
    section.className = "library-document";
    section.dataset.title = doc.title.toLowerCase();
    section.innerHTML = doc.html;
    content.appendChild(section);
  });
}

function scrollToHashTarget() {
  const hash = window.location.hash;
  if (!hash || hash.length < 2) return;
  const target = document.getElementById(hash.slice(1));
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  target.classList.add("library-highlight");
  setTimeout(() => target.classList.remove("library-highlight"), 2000);
}

function wireSearch() {
  const input = document.getElementById("library-search-input");
  if (!input) return;

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    document.querySelectorAll(".library-nav-link").forEach((link) => {
      link.hidden = Boolean(query) && !link.textContent.toLowerCase().includes(query);
    });
    document.querySelectorAll(".library-document").forEach((section) => {
      const matches =
        !query ||
        section.dataset.title.includes(query) ||
        section.textContent.toLowerCase().includes(query);
      section.hidden = !matches;
    });
  });
}

async function loadLibrary() {
  const content = document.getElementById("library-content");
  try {
    const response = await window.AskOufyAuth.authorizedFetch("/api/policies");
    if (!response.ok) {
      throw new Error("Failed to load the policy library (" + response.status + ").");
    }
    const data = await response.json();
    renderLibrary(data.documents);
    wireSearch();
    scrollToHashTarget();
  } catch (error) {
    if (content) {
      content.innerHTML =
        '<p class="library-error">' +
        (error.message || "Could not load the policy library.") +
        "</p>";
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const signOutButton = document.getElementById("sign-out");
  if (signOutButton) {
    signOutButton.addEventListener("click", () => {
      askOufyAuth.signOut().then(() => {
        window.location.href = "/login";
      });
    });
  }
});

// authorizedFetch needs a signed-in user; onAuthStateChanged fires once
// immediately with the current state on every page load.
askOufyAuth.onAuthStateChanged((user) => {
  if (user) {
    loadLibrary();
  }
});
