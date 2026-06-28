const DEMO_STEP_NAMES = [
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
];

const DEMO_LOGS = [
  "[12:00:01] [init] Demo backend active",
  "[12:00:02] [api] Received WSI upload",
  "[12:00:03] [step1] Scan tissue patches",
  "[12:00:04] [step2] CONCH v1.5 patch encoding",
  "[12:00:05] [step3] TITAN slide embedding",
  "[12:00:06] [step4] Classifier: Benign / Malignant",
  "[12:00:07] [step5] Patch-level malignancy scores",
  "[12:00:08] [step6] Spatial findings",
  "[12:00:09] [step7] Tissue composition",
  "[12:00:10] [step8] Morphological profile",
  "[12:00:11] [step9] UMAP / t-SNE / clustering",
  "[12:00:12] [step10] PDF report generation",
  "[12:00:13] [done] Demo pipeline complete",
];

const DEMO_RESULTS = {
  prediction: "Malignant",
  malignant_prob: 0.821,
  benign_prob: 0.179,
  confidence: 0.821,
  threshold: 0.30,
  training_auc: 0.9727,
  fold_probs: [0.793, 0.855, 0.812, 0.834, 0.809],
  fold_std: 0.022,
  n_folds: 5,
  titan_available: true,
  stability: 1.0,
  n_patches: 8742,
  embed_dim: 768,
  spatial: {
    location: "Upper-right quadrant",
    margin: "Irregular",
    circularity: 0.412,
    largest_region_mm: 18.4,
    n_tumor_foci: 3,
    tumor_patch_count: 2183,
    tumor_fraction: 0.2498,
  },
  tissue: {
    Tumor: 0.2498,
    Stroma: 0.3121,
    "Normal Epithelium": 0.1834,
    "Fat / Adipose": 0.0912,
    Lymphocytes: 0.1023,
    Necrosis: 0.0312,
    "Blood / Vascular": 0.03,
  },
  morph: {
    tumor_stroma_ratio: 0.80,
    tumor_stroma_desc: "Stromal-rich",
    til_score: 0.334,
    til_description: "Moderate TILs",
    nuclear_density_score: 0.441,
    nuclear_density: "High",
    glandular_score: 0.298,
    glandular_architecture: "Partial",
  },
  has_heatmap: true,
  has_pdf: true,
};

const DEMO_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qzQAAAAASUVORK5CYII=";

export async function onRequest(context) {
  const { request, env, params } = context;

  const segs = Array.isArray(params.path)
    ? params.path.join("/")
    : params.path || "";
  const backend = (env.HISTOAI_API_URL || "").replace(/\/+$/, "");

  if (!backend) {
    return handleDemoRequest(request, segs);
  }

  if (request.method === "GET" && segs === "health") {
    try {
      return await fetch(`${backend}/health`);
    } catch (err) {
      return json(
        { error: `Unable to reach backend health endpoint: ${err.message}` },
        502
      );
    }
  }

  const incoming = new URL(request.url);
  const target = `${backend}/api/${segs}${incoming.search}`;

  if (request.method === "POST" && segs === "analyze") {
    const form = await request.formData();

    if (env.HF_TOKEN) form.set("hf_token", env.HF_TOKEN);
    if (env.CLASSIFIER_PATH && !form.get("clf_path")) {
      form.set("clf_path", env.CLASSIFIER_PATH);
    }

    return fetch(target, { method: "POST", body: form });
  }

  return fetch(new Request(target, request));
}

async function handleDemoRequest(request, segs) {
  if (request.method === "GET" && segs === "health") {
    return json({ status: "ok", mode: "demo" });
  }

  if (request.method === "POST" && segs === "analyze") {
    const form = await request.formData();
    const file = form.get("file");
    const filename = file && typeof file === "object" && file.name ? file.name : "Scannedslidetest-1894-25.mrxs";

    return json({
      job_id: demoJobId(filename),
      filename,
      status: "queued",
      mode: "demo",
    });
  }

  if (request.method === "GET" && segs.startsWith("status/")) {
    const jobId = segs.slice("status/".length);
    const filename = filenameFromJobId(jobId);
    return json(demoStatus(jobId, filename));
  }

  if (request.method === "GET" && segs.startsWith("logs/")) {
    const jobId = segs.slice("logs/".length);
    const filename = filenameFromJobId(jobId);
    return json({ job_id: jobId, logs: demoLogs(filename) });
  }

  if (request.method === "GET" && segs.startsWith("results/")) {
    const jobId = segs.slice("results/".length);
    const filename = filenameFromJobId(jobId);
    return json(demoResults(jobId, filename));
  }

  if (request.method === "GET" && segs.startsWith("heatmap/")) {
    const jobId = segs.slice("heatmap/".length);
    const filename = filenameFromJobId(jobId);
    return binaryResponse(
      DEMO_PNG_BASE64,
      "image/png",
      `heatmap_${stemFromFilename(filename)}.png`
    );
  }

  if (request.method === "GET" && segs.startsWith("report/")) {
    const jobId = segs.slice("report/".length);
    const filename = filenameFromJobId(jobId);
    return pdfResponse(
      `Demo report for ${stemFromFilename(filename)}`,
      [
        "HistoAI demo mode is active because HISTOAI_API_URL is not configured.",
        `Filename: ${filename}`,
        "The frontend can still render results using the built-in sample payload.",
      ],
      `wsi_report_${stemFromFilename(filename)}.pdf`
    );
  }

  if (request.method === "GET" && segs === "history") {
    return json({
      total: 1,
      jobs: [
        {
          job_id: demoJobId("Scannedslidetest-1894-25.mrxs"),
          filename: "Scannedslidetest-1894-25.mrxs",
          status: "done",
          created_at: new Date().toISOString(),
          prediction: "Malignant",
          confidence: 0.821,
        },
      ],
    });
  }

  if (request.method === "DELETE" && segs.startsWith("job/")) {
    const jobId = segs.slice("job/".length);
    return json({ deleted: jobId, demo: true });
  }

  return json(
    { error: "HISTOAI_API_URL is not configured in Cloudflare Pages." },
    502
  );
}

function demoJobId(filename) {
  return `demo:${encodeURIComponent(filename)}:${Date.now().toString(36)}`;
}

function filenameFromJobId(jobId) {
  if (!jobId.startsWith("demo:")) return "Scannedslidetest-1894-25.mrxs";
  const parts = jobId.split(":");
  try {
    return decodeURIComponent(parts[1] || "Scannedslidetest-1894-25.mrxs");
  } catch {
    return "Scannedslidetest-1894-25.mrxs";
  }
}

function stemFromFilename(filename) {
  return filename.replace(/\.[^.]+$/, "") || "demo-slide";
}

function demoStatus(jobId, filename) {
  const now = new Date().toISOString();
  return {
    job_id: jobId,
    status: "done",
    progress: 100,
    current_step: DEMO_STEP_NAMES.length - 1,
    filename,
    created_at: now,
    updated_at: now,
    error: null,
    steps: DEMO_STEP_NAMES.map((name, id) => ({
      id,
      name,
      status: "done",
      started_at: now,
      finished_at: now,
    })),
  };
}

function demoLogs(filename) {
  return [
    ` [12:00:01] [init] Demo backend active for ${filename}`.replace(/^ /, ""),
    ...DEMO_LOGS.slice(1),
  ];
}

function demoResults(jobId, filename) {
  return {
    job_id: jobId,
    slide_name: `Demo · ${stemFromFilename(filename)}`,
    filename,
    completed_at: new Date().toISOString(),
    ...DEMO_RESULTS,
  };
}

function binaryResponse(base64, contentType, filename) {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  return new Response(bytes, {
    headers: {
      "content-type": contentType,
      "content-disposition": `inline; filename="${filename}"`,
    },
  });
}

function pdfResponse(title, lines, filename) {
  const pdf = makePdf(title, lines);
  return new Response(pdf, {
    headers: {
      "content-type": "application/pdf",
      "content-disposition": `inline; filename="${filename}"`,
    },
  });
}

function makePdf(title, lines) {
  const content = [
    `BT /F1 18 Tf 72 760 Td (${escapePdfText(title)}) Tj ET`,
    ...lines.map(
      (line, index) =>
        `BT /F1 11 Tf 72 ${730 - index * 18} Td (${escapePdfText(line)}) Tj ET`
    ),
  ].join("\n");

  const objects = [
    "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
    "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
    "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
    "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    `5 0 obj << /Length ${content.length} >> stream\n${content}\nendstream endobj\n`,
  ];

  let pdf = "%PDF-1.4\n";
  const offsets = [0];

  for (const obj of objects) {
    offsets.push(pdf.length);
    pdf += obj;
  }

  const xrefStart = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;

  for (const offset of offsets.slice(1)) {
    pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }

  pdf += `trailer << /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF\n`;
  return pdf;
}

function escapePdfText(text) {
  return String(text)
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)");
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
