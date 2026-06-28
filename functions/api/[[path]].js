export async function onRequest(context) {
  const { request, env, params } = context;

  const backend = (env.HISTOAI_API_URL || "").replace(/\/+$/, "");
  if (!backend) {
    return json(
      { error: "HISTOAI_API_URL is not configured in Cloudflare Pages." },
      502
    );
  }

  const segs = Array.isArray(params.path)
    ? params.path.join("/")
    : params.path || "";
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

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
