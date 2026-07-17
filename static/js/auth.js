// Shared authentication helpers for Ask Oufy's vanilla-JS frontend.
// Every authenticated request attaches the current Firebase ID token as a
// Bearer header - never a cookie - so the browser never sends it
// automatically on a third-party site's behalf.

function showLoginError(message) {
  const el = document.getElementById("login-error");
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
}

async function signInWithGoogle() {
  const provider = new firebase.auth.GoogleAuthProvider();
  try {
    await askOufyAuth.signInWithPopup(provider);
    window.location.href = "/";
  } catch (error) {
    showLoginError("Sign-in failed: " + error.message);
  }
}

async function authorizedFetch(url, options = {}) {
  const user = askOufyAuth.currentUser;
  if (!user) {
    throw new Error("No signed-in user.");
  }
  const token = await user.getIdToken();
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", "Bearer " + token);
  return fetch(url, { ...options, headers });
}

document.addEventListener("DOMContentLoaded", () => {
  const signInButton = document.getElementById("google-sign-in");
  if (signInButton) {
    signInButton.addEventListener("click", signInWithGoogle);
  }
});

// Shows/hides any element marked data-admin-only based on the signed-in
// user's real is_admin status (from the server) - a UI convenience only;
// every admin action is still independently enforced by require_admin.
async function toggleAdminOnlyElements() {
  const elements = document.querySelectorAll("[data-admin-only]");
  if (!elements.length) return;

  try {
    const response = await authorizedFetch("/api/whoami");
    const isAdmin = response.ok && (await response.json()).is_admin;
    elements.forEach((el) => {
      el.hidden = !isAdmin;
    });
  } catch (error) {
    // Non-fatal: admin-only UI elements simply stay hidden.
  }
}

// Pages opt in to the redirect guard by setting
// window.__ASK_OUFY_REQUIRE_AUTH__ = true before this script runs. The page
// itself starts hidden (see the "auth-pending" style in base.html) so it
// never flashes its content before a redirect - it's only revealed once we
// know the visitor should actually see it.
askOufyAuth.onAuthStateChanged((user) => {
  const onLoginPage = window.location.pathname === "/login";
  if (user && onLoginPage) {
    window.location.href = "/";
    return;
  }
  if (!user && window.__ASK_OUFY_REQUIRE_AUTH__) {
    window.location.href = "/login";
    return;
  }

  document.body.classList.remove("auth-pending");
  if (user) {
    toggleAdminOnlyElements();
  }
});

window.AskOufyAuth = { authorizedFetch, signInWithGoogle };
