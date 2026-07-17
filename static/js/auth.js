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
    // The shared onAuthStateChanged handler below checks the allow-list
    // and redirects - nothing further to do here.
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

async function fetchWhoami() {
  try {
    const response = await authorizedFetch("/api/whoami");
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    return null;
  }
}

function applyAdminVisibility(isAdmin) {
  document.querySelectorAll("[data-admin-only]").forEach((el) => {
    el.hidden = !isAdmin;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const signInButton = document.getElementById("google-sign-in");
  if (signInButton) {
    signInButton.addEventListener("click", signInWithGoogle);
  }
});

// The allow-list - not just a valid Firebase sign-in - is what actually
// grants access: every signed-in user is checked against /api/whoami here,
// immediately after sign-in, so an account that isn't invited is rejected
// right away with a clear message instead of being allowed to browse the
// app and only discover it's blocked when it tries to use a feature.
//
// Pages opt in to the redirect guard by setting
// window.__ASK_OUFY_REQUIRE_AUTH__ = true before this script runs. The page
// itself starts hidden (see the "auth-pending" style in base.html) so it
// never flashes its content before a redirect - it's only revealed once we
// know the visitor should actually see it.
askOufyAuth.onAuthStateChanged(async (user) => {
  const onLoginPage = window.location.pathname === "/login";

  if (!user) {
    if (window.__ASK_OUFY_REQUIRE_AUTH__) {
      window.location.href = "/login";
      return;
    }
    document.body.classList.remove("auth-pending");
    return;
  }

  const whoami = await fetchWhoami();
  if (!whoami) {
    await askOufyAuth.signOut();
    if (onLoginPage) {
      showLoginError("This Google account is not authorised to access Ask Oufy.");
    } else {
      window.location.href = "/login";
    }
    return;
  }

  if (onLoginPage) {
    window.location.href = "/";
    return;
  }

  document.body.classList.remove("auth-pending");
  applyAdminVisibility(whoami.is_admin);
});

window.AskOufyAuth = { authorizedFetch, signInWithGoogle };
