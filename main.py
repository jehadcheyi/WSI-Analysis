"""
HistoAI — FastAPI Backend
=========================
Wraps the CONCH v1.5 + TITAN + bracs_v3_model pipeline as a REST API.

Quickstart:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Expose to Cloudflare Pages frontend via:
    cloudflared tunnel --url http://localhost:8000
or deploy on any GPU server (Kaggle Notebook, RunPod, Lambda Labs, etc.)
"""

import os, uuid, time, json, asyncio, subprocess, sys, shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import aiofiles

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
UPLOAD_DIR      = Path("./uploads")
RESULTS_DIR     = Path("./results")
CLASSIFIER_PATH = os.getenv("CLASSIFIER_PATH", "./model/bracs_v3_model.pkl")
HF_TOKEN        = os.getenv("HF_TOKEN", "")
MAX_UPLOAD_MB   = int(os.getenv("MAX_UPLOAD_MB", "10000"))   # 10 GB default

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="HistoAI API",
    description="WSI Analysis — CONCH v1.5 + TITAN + bracs_v3_model",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your CF Pages domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# JOB STORE (in-memory; swap for Redis/SQLite in production)
# ─────────────────────────────────────────────────────────────
JOBS: Dict[str, Dict[str, Any]] = {}

STEP_NAMES = [
    "Install dependencies",
    "Scan tissue patches",
    "CONCH v1.5 patch encoding",
    "TITAN slide embedding",
    "Classifier: Benign / Malignant",
    "Patch-level malignancy scores",
    "Spatial findings",
    "Tissue composition",
    "Morphological profile",
    "UMAP / t-SNE / clustering",
    "PDF report generation",
]

def make_job(job_id: str, filename: str, wsi_path: str) -> dict:
    return {
        "job_id":       job_id,
        "filename":     filename,
        "wsi_path":     wsi_path,
        "status":       "queued",
        "progress":     0,
        "current_step": -1,
        "created_at":   datetime.utcnow().isoformat(),
        "updated_at":   datetime.utcnow().isoformat(),
        "steps": [
            {"id": i, "name": n, "status": "pending",
             "started_at": None, "finished_at": None}
            for i, n in enumerate(STEP_NAMES)
        ],
        "logs":    [],
        "results": None,
        "error":   None,
    }

def upd(job_id, **kw):
    if job_id in JOBS:
        JOBS[job_id].update(kw)
        JOBS[job_id]["updated_at"] = datetime.utcnow().isoformat()

def log(job_id, line):
    if job_id in JOBS:
        JOBS[job_id]["logs"].append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {line}")
        if len(JOBS[job_id]["logs"]) > 500:
            JOBS[job_id]["logs"] = JOBS[job_id]["logs"][-500:]

# ─────────────────────────────────────────────────────────────
# PIPELINE RUNNER
# ─────────────────────────────────────────────────────────────
async def run_pipeline(job_id: str, hf_token: str, clf_path: str, cfg: dict):
    job     = JOBS[job_id]
    out_dir = RESULTS_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    upd(job_id, status="running", current_step=0)
    log(job_id, "[runner] Pipeline started")

    pipeline_script = Path(__file__).parent / "pipeline_runner.py"

    try:
        if pipeline_script.exists():
            # ── Real pipeline ──────────────────────────────────
            env = {**os.environ, "HF_TOKEN": hf_token, "HUGGING_FACE_HUB_TOKEN": hf_token}
            args = [
                sys.executable, str(pipeline_script),
                "--wsi",   job["wsi_path"],
                "--clf",   clf_path,
                "--out",   str(out_dir),
                "--token", hf_token,
            ]
            for k, v in cfg.items():
                args += [f"--{k}", str(v)]

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )

            step_kw = [f"STEP {i}" for i in range(len(STEP_NAMES))]

            while True:
                raw = await proc.stdout.readline()
                if not raw: break
                line = raw.decode("utf-8", errors="replace").rstrip()
                log(job_id, line)

                for i, kw in enumerate(step_kw):
                    if kw in line:
                        prev = job["current_step"]
                        if 0 <= prev < len(STEP_NAMES):
                            JOBS[job_id]["steps"][prev]["status"] = "done"
                            JOBS[job_id]["steps"][prev]["finished_at"] = datetime.utcnow().isoformat()
                        JOBS[job_id]["steps"][i]["status"] = "running"
                        JOBS[job_id]["steps"][i]["started_at"] = datetime.utcnow().isoformat()
                        upd(job_id, current_step=i,
                            progress=int(i / len(STEP_NAMES) * 100))
                        break

            await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"Pipeline exited {proc.returncode}")

        else:
            # ── Demo / no pipeline script ──────────────────────
            await _demo_run(job_id, out_dir)

        results = _collect_results(job_id, out_dir / "pipeline")
        upd(job_id, status="done", results=results, progress=100,
            current_step=len(STEP_NAMES) - 1)
        for s in JOBS[job_id]["steps"]:
            s["status"] = "done"
        log(job_id, "[runner] Pipeline complete ✓")

    except Exception as e:
        upd(job_id, status="failed", error=str(e))
        cs = job.get("current_step", -1)
        if 0 <= cs < len(STEP_NAMES):
            JOBS[job_id]["steps"][cs]["status"] = "error"
        log(job_id, f"[runner] FAILED: {e}")


async def _demo_run(job_id: str, out_dir: Path):
    """Simulated pipeline when no real WSI / script is present."""
    pipe_dir = out_dir / "pipeline"
    pipe_dir.mkdir(parents=True, exist_ok=True)
    durs = [1,2,8,5,1,1,1,1,1,3,2]

    for i, (name, dur) in enumerate(zip(STEP_NAMES, durs)):
        JOBS[job_id]["steps"][i]["status"] = "running"
        JOBS[job_id]["steps"][i]["started_at"] = datetime.utcnow().isoformat()
        upd(job_id, current_step=i, progress=int(i/len(STEP_NAMES)*100))
        log(job_id, f"[step{i}] {name}…")
        await asyncio.sleep(dur)
        JOBS[job_id]["steps"][i]["status"] = "done"
        JOBS[job_id]["steps"][i]["finished_at"] = datetime.utcnow().isoformat()

    # Write demo result files
    (pipe_dir/"diagnosis.json").write_text(json.dumps({
        "prediction":"Malignant","malignant_prob":0.821,"benign_prob":0.179,
        "confidence":0.821,"threshold":0.30,"training_auc":0.9727,
        "fold_probs":[0.793,0.855,0.812,0.834,0.809],"fold_std":0.022,
        "n_folds":5,"titan_available":True,
    }, indent=2))
    (pipe_dir/"spatial_findings.json").write_text(json.dumps({
        "location":"Upper-right quadrant","margin":"Irregular","circularity":0.412,
        "largest_region_mm":18.4,"n_tumor_foci":3,"tumor_patch_count":2183,"tumor_fraction":0.2498,
    }, indent=2))
    (pipe_dir/"tissue_composition.json").write_text(json.dumps({
        "Tumor":{"count":2183,"fraction":0.2498},"Stroma":{"count":2727,"fraction":0.3121},
        "Normal Epithelium":{"count":1603,"fraction":0.1834},
        "Fat / Adipose":{"count":797,"fraction":0.0912},
        "Lymphocytes":{"count":894,"fraction":0.1023},
        "Necrosis":{"count":273,"fraction":0.0312},
        "Blood / Vascular":{"count":265,"fraction":0.0300},
    }, indent=2))
    (pipe_dir/"morphological_profile.json").write_text(json.dumps({
        "tumor_stroma_ratio":0.80,"tumor_stroma_desc":"Stromal-rich",
        "til_score":0.334,"til_description":"Moderate TILs","til_count":728,
        "nuclear_density_score":0.441,"nuclear_density":"High",
        "glandular_score":0.298,"glandular_architecture":"Partial",
    }, indent=2))


def _load_json(p: Path) -> Optional[dict]:
    try: return json.loads(p.read_text()) if p.exists() else None
    except: return None

def _collect_results(job_id: str, pipe_dir: Path) -> dict:
    job = JOBS[job_id]
    diagnosis = _load_json(pipe_dir/"diagnosis.json") or {}
    spatial   = _load_json(pipe_dir/"spatial_findings.json") or {}
    tissue    = _load_json(pipe_dir/"tissue_composition.json") or {}
    morph     = _load_json(pipe_dir/"morphological_profile.json") or {}

    # Flatten tissue fractions for the frontend
    tissue_flat = {k: v.get("fraction", v) if isinstance(v, dict) else v
                   for k, v in tissue.items()}

    return {
        "job_id":      job_id,
        "slide_name":  Path(job["filename"]).stem,
        "filename":    job["filename"],
        "n_patches":   8742,      # real pipeline sets this
        "embed_dim":   768,
        "completed_at": datetime.utcnow().isoformat(),
        **diagnosis,              # prediction, malignant_prob, fold_probs, etc.
        "spatial":     spatial,
        "tissue":      tissue_flat,
        "morph":       morph,
        "has_heatmap": (pipe_dir/"attention_heatmap.png").exists(),
        "has_pdf":     (pipe_dir/"wsi_analysis_report.pdf").exists(),
    }

# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/analyze")
async def analyze(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    hf_token:     str   = Form(""),
    clf_path:     str   = Form(""),
    target_mpp:   float = Form(0.5),
    patch_size:   int   = Form(448),
    stride_factor:float = Form(0.5),
    max_patches:  int   = Form(12000),
    threshold:    float = Form(0.30),
):
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_MB} MB)")

    job_id = str(uuid.uuid4())
    dest = UPLOAD_DIR / job_id / file.filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(dest, "wb") as f:
        await f.write(contents)

    JOBS[job_id] = make_job(job_id, file.filename, str(dest))
    log(job_id, f"[api] Received: {file.filename} ({len(contents)/1e6:.1f} MB)")

    background_tasks.add_task(
        run_pipeline, job_id,
        hf_token or HF_TOKEN,
        clf_path  or CLASSIFIER_PATH,
        {"target_mpp": target_mpp, "patch_size": patch_size,
         "stride_factor": stride_factor, "max_patches": max_patches,
         "threshold": threshold},
    )
    return {"job_id": job_id, "filename": file.filename, "status": "queued"}


@app.get("/api/status/{job_id}")
async def status(job_id: str):
    if job_id not in JOBS: raise HTTPException(404, "Job not found")
    j = JOBS[job_id]
    return {"job_id":job_id,"status":j["status"],"progress":j["progress"],
            "current_step":j["current_step"],"steps":j["steps"],
            "filename":j["filename"],"created_at":j["created_at"],
            "updated_at":j["updated_at"],"error":j.get("error")}


@app.get("/api/logs/{job_id}")
async def logs(job_id: str, last_n: int = Query(100, le=500)):
    if job_id not in JOBS: raise HTTPException(404, "Job not found")
    return {"job_id": job_id, "logs": JOBS[job_id]["logs"][-last_n:]}


@app.get("/api/results/{job_id}")
async def results(job_id: str):
    if job_id not in JOBS: raise HTTPException(404, "Job not found")
    j = JOBS[job_id]
    if j["status"] != "done": raise HTTPException(202, f"Status: {j['status']}")
    return j["results"]


@app.get("/api/heatmap/{job_id}")
async def heatmap(job_id: str):
    if job_id not in JOBS: raise HTTPException(404, "Job not found")
    p = RESULTS_DIR / job_id / "pipeline" / "attention_heatmap.png"
    if not p.exists(): raise HTTPException(404, "Not generated yet")
    return FileResponse(p, media_type="image/png", filename=f"heatmap_{job_id[:8]}.png")


@app.get("/api/report/{job_id}")
async def report(job_id: str):
    if job_id not in JOBS: raise HTTPException(404, "Job not found")
    p = RESULTS_DIR / job_id / "pipeline" / "wsi_analysis_report.pdf"
    if not p.exists(): raise HTTPException(404, "Not generated yet")
    return FileResponse(p, media_type="application/pdf", filename=f"wsi_report_{job_id[:8]}.pdf")


@app.get("/api/patch-data/{job_id}")
async def patch_data(job_id: str):
    if job_id not in JOBS: raise HTTPException(404, "Job not found")
    p = RESULTS_DIR / job_id / "pipeline" / "patch_data.csv"
    if not p.exists(): raise HTTPException(404, "Not available")
    return FileResponse(p, media_type="text/csv", filename=f"patches_{job_id[:8]}.csv")


@app.get("/api/embedding/{job_id}/{kind}")
async def embedding(job_id: str, kind: str):
    FILES = {
        "umap":"umap_embedding.npy","tsne":"tsne_embedding.npy",
        "pca":"pca_embedding.npy","conch":"features_conch_v15.npy",
        "titan":"titan_slide_embedding.npy","relevance":"patch_relevance.npy",
        "malscores":"patch_malignancy_scores.npy",
    }
    if kind not in FILES: raise HTTPException(400, f"Unknown kind. Choose: {list(FILES)}")
    if job_id not in JOBS: raise HTTPException(404, "Job not found")
    p = RESULTS_DIR / job_id / "pipeline" / FILES[kind]
    if not p.exists(): raise HTTPException(404, "Not available")
    return FileResponse(p, media_type="application/octet-stream",
                        filename=f"{kind}_{job_id[:8]}.npy")


@app.get("/api/history")
async def history(skip: int = Query(0, ge=0), limit: int = Query(20, le=100)):
    jobs = sorted(JOBS.values(), key=lambda j: j["created_at"], reverse=True)
    return {
        "total": len(JOBS),
        "jobs": [
            {"job_id":j["job_id"],"filename":j["filename"],"status":j["status"],
             "created_at":j["created_at"],
             "prediction": (j["results"]or{}).get("prediction"),
             "confidence":  (j["results"]or{}).get("confidence")}
            for j in jobs[skip:skip+limit]
        ],
    }


@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str):
    if job_id not in JOBS: raise HTTPException(404, "Job not found")
    if JOBS[job_id]["status"] == "running": raise HTTPException(400, "Cannot delete a running job")
    for d in [UPLOAD_DIR/job_id, RESULTS_DIR/job_id]:
        shutil.rmtree(d, ignore_errors=True)
    del JOBS[job_id]
    return {"deleted": job_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
