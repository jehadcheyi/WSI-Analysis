# HistoAI — WSI Analysis Platform

Full-stack computational pathology web app:
**Cloudflare Pages** (frontend) + **FastAPI on GPU server** (backend).

```
Model stack: CONCH v1.5 (patch) + TITAN (slide) + bracs_v3_model (classifier)
CV-AUC: 0.9727  ·  Threshold: 0.30  ·  Input: 2304-d (mean+max+std pooling)
```

---

## Repo structure

```
histoai/
├── index.html            ← single-page app (no build step needed)
├── _headers              ← Cloudflare Pages security headers
├── _redirects            ← SPA routing (/* → /index.html 200)
├── functions/
│   └── api/
│       └── [[path]].js   ← CF Pages Function: injects HF_TOKEN secret + proxies /api/*
├── wrangler.toml         ← CF Pages config (vars + where to put the secret)
│
├── main.py               ← FastAPI server (11 REST endpoints)
├── requirements.txt
├── Dockerfile            ← CUDA 11.8 + openslide + all pipeline deps
├── docker-compose.yml
├── .env.example
├── model/
│   └── bracs_v3_model.pkl  ← classifier (you add this)
│
└── deploy.yml            ← GitHub Actions → Cloudflare Pages
```

---

## 1 — GitHub setup

```bash
# Clone or create repo
git init histoai && cd histoai
# copy these files in, then:
git add .
git commit -m "init: HistoAI WSI platform"
git remote add origin https://github.com/jehadcheyi/histoai.git
git push -u origin main
```

Add these **GitHub Secrets** (Settings → Secrets → Actions):

| Secret | Value |
|--------|-------|
| `CLOUDFLARE_API_TOKEN` | CF API token with Pages:Edit permission |
| `CLOUDFLARE_ACCOUNT_ID` | Your Cloudflare account ID |

---

## 2 — Cloudflare Pages setup

**Option A — Connect GitHub (recommended)**

1. Go to [pages.cloudflare.com](https://pages.cloudflare.com) → Create a project → Connect to Git
2. Pick `jehadcheyi/histoai`
3. Build settings:
   - **Framework preset**: None
   - **Build command**: *(leave empty)*
   - **Build output directory**: `frontend`
4. Save → Deploy

Every push to `main` auto-deploys via the GitHub Action **and** Cloudflare's own Git integration (use one or the other).

> Build output directory is the repo root (`.`) — `index.html`, `_headers`,
> `_redirects` and the `functions/` directory all live at the top level.

**Option B — Manual deploy with Wrangler**

```bash
npm install -g wrangler
wrangler pages deploy . --project-name histoai
```

---

## 2b — Cloudflare variables & secrets (HF token)

The frontend is static, so the HuggingFace token is kept in a
**Cloudflare Pages secret** and injected server-side by the Pages Function.
You do **not** need to paste the token into the browser field unless you want
that one-request override.

Set these in **Pages → your project → Settings → Variables and Secrets**
(or via Wrangler):

| Name | Type | Value |
|------|------|-------|
| `HISTOAI_API_URL` | **Variable** (plaintext) | Backend base URL, e.g. `https://histoai.your-server.com` |
| `CLASSIFIER_PATH` | **Variable** (plaintext) | *(optional)* `model/bracs_v3_model.pkl` |
| `HF_TOKEN` | **Secret** (encrypted) | Your HuggingFace token `hf_xxx` |

```bash
# Variable (plaintext) — also lives in wrangler.toml [vars]
wrangler pages project ...    # or set HISTOAI_API_URL in the dashboard

# Secret (encrypted) — NEVER commit this
wrangler pages secret put HF_TOKEN
```

The Cloudflare Function at `functions/api/[[path]].js` injects `HF_TOKEN`
into `/api/analyze` and forwards every `/api/*` request to the backend.
`HISTOAI_API_URL` must point at a running backend, for example a local FastAPI
server exposed with Cloudflare Tunnel:

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
cloudflared tunnel --url http://localhost:8000
```

Paste the tunnel URL into `HISTOAI_API_URL`, then upload a slide and run
analysis. If you are using the direct backend URL in the app UI instead, the
same Cloudflare secret still gets injected server-side when requests pass
through Pages.

---

## 3 — Backend deployment

### Option A: Local + Cloudflare Tunnel (free, for Kaggle/local GPU)

```bash
cd backend
pip install -r requirements.txt
HF_TOKEN=hf_xxx uvicorn main:app --host 0.0.0.0 --port 8000

# Expose to the internet:
cloudflared tunnel --url http://localhost:8000
# Copy the tunnel URL (e.g. https://xxxx.trycloudflare.com)
# Paste it into the frontend's API URL field
```

### Option B: Kaggle Notebook (free T4 GPU)

1. Create a Kaggle notebook.
2. Upload `backend/main.py` as a dataset or paste it.
3. Run:

```python
!pip install fastapi uvicorn aiofiles python-multipart pyngrok -q
import subprocess, threading

def run():
    subprocess.run(["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"])

threading.Thread(target=run, daemon=True).start()

from pyngrok import ngrok
tunnel = ngrok.connect(8000)
print("Backend URL:", tunnel.public_url)
# Paste tunnel.public_url into frontend API URL field
```

### Option C: Docker on GPU server (RunPod / Lambda / vast.ai)

```bash
cd backend
cp .env.example .env          # add your HF_TOKEN
# Place bracs_v3_model.pkl in ./model/
docker compose up --build -d

# Point a domain / Cloudflare Proxy at port 8000
```

---

## 4 — Connecting frontend to backend

In the live site, go to **Upload & Analyze** and enter your backend URL:

```
https://xxxx.trycloudflare.com     ← Cloudflare Tunnel
https://api.histoai.com             ← Custom domain
http://localhost:8000               ← Local dev
```

Click **Save URL** — it persists in `localStorage`. The topbar shows ● Online / ● Offline.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/analyze` | Upload WSI + start pipeline |
| `GET`  | `/api/status/{job_id}` | Real-time step progress |
| `GET`  | `/api/logs/{job_id}` | Terminal log stream |
| `GET`  | `/api/results/{job_id}` | Full results JSON |
| `GET`  | `/api/heatmap/{job_id}` | attention_heatmap.png |
| `GET`  | `/api/report/{job_id}` | wsi_analysis_report.pdf |
| `GET`  | `/api/patch-data/{job_id}` | patch_data.csv |
| `GET`  | `/api/embedding/{job_id}/{kind}` | .npy arrays (umap/tsne/conch/titan/relevance) |
| `GET`  | `/api/history` | Past analyses |
| `DELETE` | `/api/job/{job_id}` | Remove job + files |
| `GET`  | `/health` | Server health |

Swagger UI: `http://your-backend/docs`

---

## Frontend features (all in `frontend/index.html`)

- **Upload & Analyze** — drag-and-drop WSI, HF token, classifier path, live 11-step tracker with terminal log
- **Results** — diagnosis hero (probability ring + 5-fold bars), stats grid, 4 tabs: Spatial / Tissue / Morphology / Fold Detail
- **Heatmap Viewer** — attention heatmap canvas, top-3 patch crop cards
- **Cluster Explorer** — UMAP/t-SNE scatter, K-Means + HDBSCAN, color by tissue / relevance / cluster
- **History** — persistent across sessions (localStorage), load any past result
- **PDF Report** — 10-page preview, download button
- **Settings** — all CONFIG params (MPP, patch size, threshold, HDBSCAN, etc.)
- **API Docs** — endpoint table, URL config, live connection test

No framework, no build step, no npm — pure HTML/CSS/JS, deploys as-is to Cloudflare Pages.

---

## Notes

- **No secrets in frontend** — `HF_TOKEN` is stored as an encrypted Cloudflare **secret** and injected by the Pages Function (`functions/api/[[path]].js`) server-side. It is never stored in, or exposed to, the static HTML.
- **CORS** — the backend allows all origins by default. Tighten to your CF Pages domain in production:
  ```python
  allow_origins=["https://histoai.pages.dev", "https://yourdomain.com"]
  ```
- **Large files** — Cloudflare's free tier has a 100 MB request body limit. For multi-GB WSIs, upload directly to the backend (bypass CF proxy for the `/api/analyze` endpoint), or use a presigned upload URL pattern.
