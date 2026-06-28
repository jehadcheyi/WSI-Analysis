// ──────────────────────────────────────────────────────────────
//  Cloudflare Pages Function — secure backend proxy
//  Route: /api/*  (catch-all)
//
//  Reads from the Cloudflare Pages environment:
//    • HISTOAI_API_URL  → plaintext VARIABLE  (your backend base URL)
//    • HF_TOKEN         → encrypted SECRET    (HuggingFace token)
//    • CLASSIFIER_PATH  → optional VARIABLE   (default classifier .pkl path)
//
//  The HF token lives only in Cloudflare and is injected into the
//  /api/analyze request server-side, so it never reaches the browser.
//
//  Set them with Wrangler (or the CF dashboard → Settings → Variables):
//    wrangler pages secret put HF_TOKEN
//    wrangler pages deployment ... (vars in wrangler.toml / dashboard)
// ──────────────────────────────────────────────────────────────

export async function onRequest(context) {
  const { request, env, params } = context;

  const backend = (env.HISTOAI_API_URL || "").replace(/\/+$/, "");
  if (!backend) {
    return json(
      { error: "HISTOAI_API_URL is not configured in Cloudflare Pages." },
      502
    );
  }

  // Rebuild the path that followed /api/  (catch-all segments)
  const segs = Array.isArray(params.path)
    ? params.path.join("/")
    : params.path || "";
  const incoming = new URL(request.url);
  const target = `${backend}/api/${segs}${incoming.search}`;

  // ── Inject the Cloudflare secret into the analyze upload ──────
  if (request.method === "POST" && segs === "analyze") {
    const form = await request.formData();

    // Always use the token stored in Cloudflare when present;
    // fall back to a client-supplied token only if no secret is set.
    if (env.HF_TOKEN) form.set("hf_token", env.HF_TOKEN);

    // Default the classifier path if the caller didn't pick one.
    if (env.CLASSIFIER_PATH && !form.get("clf_path")) {
      form.set("clf_path", env.CLASSIFIER_PATH);
    }

    // fetch() sets a fresh multipart boundary + content-type for us.
    return fetch(target, { method: "POST", body: form });
  }

  // ── Transparent pass-through for every other /api/* endpoint ──
  // (status, logs, results, heatmap, report, history, delete, …)
  return fetch(new Request(target, request));
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
