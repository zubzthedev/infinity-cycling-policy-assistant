# Ask Oufy

**Ask Oufy** is the Infinity Cycling Club's internal governance and policy
assistant. Executive Committee (EXCO) members sign in with Google, ask
governance/disciplinary questions, and get structured answers drawn **only**
from the club's official policy documents — never invented, never guessed.

Live deployment: **https://ask-oufy-43055331109.us-central1.run.app**

This document is a complete runbook: every account, subscription, API, and
command needed to set this up from scratch, deploy it, and maintain it day
to day. It reflects what was actually built and the real gotchas hit along
the way, not just the original plan.

---

## 1. Architecture at a glance

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI |
| Frontend | Server-rendered Jinja2 templates + vanilla JavaScript (no React/Vue/Angular) |
| Auth | Firebase Authentication (Google Sign-In), Bearer-token only — **no cookies** |
| AI | Google Gemini API (`gemini-3.1-flash-lite`) |
| Policy storage | Google Drive folder (`.md` files), fetched via the Drive API |
| Prompt storage | Local files (`prompts/`), editable via the Admin UI |
| Hosting | Google Cloud Run (Docker container), scale-to-zero |
| Secrets | Google Secret Manager (Gemini key) + keyless service-account identity (Firebase/Drive) |

**Why Bearer tokens, not cookies**: every authenticated request attaches the
Firebase ID token as `Authorization: Bearer <token>`. A page navigation
can't carry that header, so `/library` and `/admin` are public, content-free
HTML shells — the real content and access control live entirely behind
`/api/*` endpoints, fetched client-side after sign-in. This is also why no
CSRF protection is implemented: a third-party site has no way to obtain or
attach a victim's Bearer token.

**Why Drive for policies, not a database or upload form**: EXCO members are
non-technical. A shared Google Drive folder is a UI they already know, it
has built-in sharing/versioning, and it solves Cloud Run's ephemeral-disk
problem for free (Drive storage isn't tied to the container). Prompts
(system instructions, response format rules) are different — they're
engineering-tuned, not committee-managed — so those stay on local disk with
a simple in-app editor under Admin.

---

## 2. Accounts and subscriptions required

| What | Used for | Notes |
|---|---|---|
| A Google account for the club | Owns everything below | We used `teaminfinitycycling@gmail.com` |
| Google Cloud Platform (GCP) project | Hosting, Secret Manager, Drive API | Project ID: `infinity-bot-232c3`. **Requires a linked billing account** (a payment method) even though usage should stay within free-tier limits for a small committee app |
| Firebase project | Google Sign-In auth | Same project as GCP — a Firebase project *is* a GCP project |
| Google Drive | Policy document storage | Any Drive folder under the club account, shared with a service account (below) |
| Google AI Studio / Gemini API key | AI answers | Currently a personal-account key — see [§9 Known gaps](#9-known-gaps--future-work) |
| GitHub | Source control | `https://github.com/zubzthedev/infinity-cycling-policy-assistant` — currently under a personal GitHub account |

---

## 3. One-time cloud setup (do this once)

### 3.1 Create the Firebase/GCP project

1. Sign in to [Firebase console](https://console.firebase.google.com) with the club's Google account.
2. **Add project** → name it (ours is `infinity-bot-232c3`, auto-generated from a display name — Firebase appends random characters to the ID, note the exact ID shown in **Project settings → General**).
3. Skip Google Analytics (not needed).

### 3.2 Enable Google Sign-In

1. **Build → Authentication → Get started**.
2. Enable the **Google** sign-in provider, pick a support email.

### 3.3 Register a web app and get the public config

1. **Project settings → General → Your apps** → click **`</>`** to register a web app.
2. Copy the four values from the shown `firebaseConfig`: `apiKey`, `authDomain`, `projectId`, `appId`. These are **public by design** (safe in client-side JS/browser) — access control is enforced server-side, not by hiding this config.
3. **Project settings → Authentication → Settings → Authorized domains**: add your Cloud Run domain (e.g. `ask-oufy-43055331109.us-central1.run.app`) once you know it (step 6). `localhost` is already included by default.

### 3.4 Generate a service account key (for local dev only)

1. **Project settings → Service accounts → Generate new private key** → downloads a JSON file.
2. Save it **outside the repository** (e.g. a dedicated folder like `C:\Users\<you>\ask-oufy-secrets\`), never commit it.
3. Note the `client_email` field inside it (looks like `firebase-adminsdk-fbsvc@infinity-bot-232c3.iam.gserviceaccount.com`) — you'll need it in the next step. **Cloud Run does not use this file** — it runs *as* this service account directly (keyless), see §6.

### 3.5 Set up the Google Drive policy folder

1. Create a folder in Google Drive under the club account, e.g. "Ask Oufy Policies".
2. Upload the `.md` policy files into it (copy the 5 samples from `policies/` in the repo as a starting point, or replace with real club policies).
3. **Share** the folder with the service account's `client_email` (from §3.4), **Viewer** access is enough.
4. Enable the Drive API for the project:
   `https://console.cloud.google.com/apis/library/drive.googleapis.com?project=infinity-bot-232c3`
5. Note the folder ID from its URL: `https://drive.google.com/drive/folders/<THIS_PART>`.

### 3.6 Get a Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey), sign in, **Create API key**.
2. **Check which models your key actually has quota for** before picking a default — we discovered the hard way that `gemini-2.5-flash` returns a 404 ("no longer available to new users") on a fresh key, and some models return 429 (quota exhausted) on the free tier. Query available models:
   ```bash
   curl "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_KEY"
   ```
   We settled on **`gemini-3.1-flash-lite`**, which worked reliably on a free-tier key. Re-check this if Google changes model availability again.

---

## 4. Environment variables reference

Copy `.env.example` to `.env` for local development and fill these in:

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `local` or `production` — production requires `GEMINI_API_KEY` and `AUTHORISED_USERS` to be set (fails fast at startup otherwise) |
| `GEMINI_API_KEY` | Secret. From §3.6 |
| `GEMINI_MODEL` | Default `gemini-3.1-flash-lite` — see the quota note above |
| `GEMINI_TIMEOUT_SECONDS` | Hard timeout for a Gemini call (default 30) |
| `FIREBASE_PROJECT_ID`, `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_APP_ID` | Public Firebase web config, from §3.3 |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the service account JSON (§3.4), **local dev only** — leave unset in Cloud Run |
| `AUTHORISED_USERS` | Comma-separated emails allowed to sign in at all |
| `ADMIN_USERS` | Comma-separated emails with Admin panel access — must also be in `AUTHORISED_USERS` |
| `POLICY_SOURCE` | `local` (reads `POLICY_DIR` on disk) or `drive` (fetches from Drive) |
| `POLICY_DIR` | Local policy directory, used when `POLICY_SOURCE=local` (default `policies`) |
| `DRIVE_FOLDER_ID` | Required when `POLICY_SOURCE=drive`, from §3.5 |
| `PROMPT_DIR` | Prompt fragment directory (default `prompts`) — always local disk, never Drive |
| `LOG_QUESTIONS` / `LOG_RESPONSES` | Reserved for future audit logging (not currently implemented — see §9) |
| `RATE_LIMIT_PER_MINUTE` | Per-user request cap on `/api/ask` (default 10) |

**Never commit `.env`** — it's git-ignored. Firebase's web config values
are safe to share (they're meant to be public); `GEMINI_API_KEY` and the
service account JSON are the two real secrets.

---

## 5. Local development

```bash
python -m venv .venv
./.venv/Scripts/activate      # source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
cp .env.example .env          # fill in values from §4
uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/api/health` — should report all 5 sample
policies loaded. Then `http://127.0.0.1:8000/login` to sign in.

Run tests / lint / type-check:

```bash
pytest
ruff check app tests
mypy app
```

---

## 6. Docker

```bash
docker build -t ask-oufy:local .
docker run -p 8080:8080 --env-file .env \
  -v "/path/to/ask-oufy-secrets:/secrets:ro" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/firebase-service-account.json \
  ask-oufy:local
```

**Windows/Git Bash note**: prefix with `MSYS_NO_PATHCONV=1` — Git Bash
otherwise mangles the `/secrets/...` container path into a Windows path.

The container runs as a non-root user and reads Cloud Run's `$PORT` env var
(defaults to 8080 locally).

---

## 7. Cloud Run deployment

### 7.1 Install and configure gcloud CLI

```powershell
winget install --id Google.CloudSDK
```

```bash
gcloud auth login                              # opens a browser
gcloud config set project infinity-bot-232c3
```

### 7.2 Link billing (one-time, via Console — needs a payment method)

`https://console.cloud.google.com/billing?project=infinity-bot-232c3` →
link or create a billing account. Cloud Run/Cloud Build require this even
if usage stays free-tier.

### 7.3 Enable required APIs (one-time)

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com artifactregistry.googleapis.com \
  --project infinity-bot-232c3
```

### 7.4 Create the Gemini secret (one-time)

```bash
grep "^GEMINI_API_KEY=" .env | cut -d= -f2- | tr -d '\n' | \
  gcloud secrets create gemini-api-key --data-file=- --project infinity-bot-232c3
```

Grant the Firebase service account read access:

```bash
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:firebase-adminsdk-fbsvc@infinity-bot-232c3.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project infinity-bot-232c3

gcloud projects add-iam-policy-binding infinity-bot-232c3 \
  --member="serviceAccount:firebase-adminsdk-fbsvc@infinity-bot-232c3.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter" --condition=None
```

### 7.5 Deploy

```bash
gcloud run deploy ask-oufy \
  --source . \
  --region us-central1 \
  --project infinity-bot-232c3 \
  --service-account firebase-adminsdk-fbsvc@infinity-bot-232c3.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --min-instances=0 --max-instances=2 --memory=512Mi \
  --set-env-vars "ENVIRONMENT=production,GEMINI_MODEL=gemini-3.1-flash-lite,GEMINI_TIMEOUT_SECONDS=30,FIREBASE_PROJECT_ID=infinity-bot-232c3,FIREBASE_API_KEY=<from §3.3>,FIREBASE_AUTH_DOMAIN=infinity-bot-232c3.firebaseapp.com,FIREBASE_APP_ID=<from §3.3>,AUTHORISED_USERS=<emails>,ADMIN_USERS=<emails>,POLICY_SOURCE=drive,DRIVE_FOLDER_ID=<from §3.5>" \
  --set-secrets "GEMINI_API_KEY=gemini-api-key:latest"
```

Key points:
- **`--service-account`**: the app runs *as* the Firebase service account. `GOOGLE_APPLICATION_CREDENTIALS` is deliberately **not set** — both `firebase-admin` and our own Drive API client fall back to Application Default Credentials, which resolve automatically to this identity. No key file is ever uploaded to Cloud Run.
- **`--allow-unauthenticated`** is correct here — Cloud Run's own IAM auth would require Google Cloud identities; *our* Firebase-based allow-list is the real access control.
- **`--min-instances=0`** gives true scale-to-zero; `--max-instances=2` caps cost.
- `gcloud run deploy --source .` builds the Docker image via Cloud Build automatically — no manual `docker push` needed.

After deploying, add the printed Service URL to Firebase's **Authorized
domains** (§3.3) if you haven't already, or sign-in will fail with
*"This domain is not authorised for OAuth."*

---

## 8. Day-to-day administration

Sign in as a user listed in `ADMIN_USERS`, then visit `/admin`:

- **Application Status** — loaded policy count, load errors, current Gemini model, policy source.
- **Reload policies & prompts** — re-fetches from Drive (or local disk) and reloads prompt files, without restarting the app. Use this after editing files in the Drive folder.
- **Prompt Engineering** — edit the System Prompt / Response Rules / Examples directly and save. **This writes to local disk and does not survive a Cloud Run redeploy** — it's a working/testing tool, not permanent storage. For permanent prompt changes, edit `prompts/*.md` in the repo and redeploy.

**Managing policies**: add, edit, or delete `.md` files directly in the
shared Drive folder, then click **Reload** in Admin. There is no upload
form in the app — Drive's own UI replaces that.

**Adding/removing users**: update `AUTHORISED_USERS` / `ADMIN_USERS` and
redeploy (or update the Cloud Run service's env vars directly via
`gcloud run services update ask-oufy --update-env-vars ...`).

---

## 9. Known gaps / future work

- **Gemini API key is on a personal Google account**, not the club's. Fine for free-tier testing; should move to a club-controlled billing account before real committee reliance, given usage costs would otherwise land personally.
- **No audit logging** — questions asked, response times, and policies cited are not currently logged for compliance/audit purposes. Deliberately skipped for now; straightforward to add later if needed.
- **Prompt edits via Admin don't persist across redeploys** (local disk only) — see §8.
- **GitHub repo is under a personal account** — consider transferring to a club-owned GitHub organisation/account.
- **No automated CI** — tests/lint/type-check are run manually before each deploy.

---

## 10. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| "This domain is not authorised for OAuth" | Add the exact domain to Firebase Authentication → Settings → Authorized domains (§3.3) |
| Sign-in succeeds but immediately "not authorised" | Email isn't in `AUTHORISED_USERS` — this is enforced at sign-in time, not just per-endpoint |
| White screen after sign-in | Should be fixed (static assets are now cache-busted per deploy), but if seen again: hard-refresh / clear cache — likely a stale cached JS/CSS mismatch |
| `/healthz` returns a generic Google 404 | Cloud Run's `*.run.app` domain reserves that exact path at the infrastructure layer — the health check lives at `/api/health` instead |
| Drive policies show 0 loaded, 1 error | Check: Drive API enabled for the project, folder shared with the service account email, `DRIVE_FOLDER_ID` correct, billing enabled |
| Gemini call fails with 404 "no longer available" | The model name is deprecated for new API keys — check `https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_KEY` for what's actually available |
| Gemini call fails with 429 | Free-tier quota exhausted for that specific model — try a `-lite` variant or wait |
| Docker `-v /secrets:...` path broken on Windows | Prefix the command with `MSYS_NO_PATHCONV=1` in Git Bash |

---

## 11. Repository layout

```
app/            FastAPI application (routers, auth, policies, prompts, gemini, config)
policies/       Seed policy Markdown (used when POLICY_SOURCE=local)
prompts/        System prompt, response rules, examples
templates/      Jinja2 page shells
static/         CSS, vanilla JS, images
tests/          pytest suite
Dockerfile, .dockerignore
requirements.txt, requirements-dev.txt
```
