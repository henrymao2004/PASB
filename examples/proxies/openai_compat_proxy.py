#!/usr/bin/env python3
"""Reference OpenAI-compatible proxy for PASB internal/closed backends.

Use this when your model is reachable only via an internal endpoint that
doesn't speak the public OpenRouter / OpenAI dialect — e.g. Azure deployment,
Bytedance modelhub, Anthropic internal — but accepts something OpenAI-shaped
under the hood.

PASB depends critically on `tools` + `tool_choice` being forwarded VERBATIM to
the upstream model. The agent CANNOT commit anything to persistent state if
the upstream model never sees the tool definitions, and the entire benchmark
collapses to "single-turn polite text". Do not strip these fields.

Same proxy can serve both the agent backbone (port 8002 for example) and the
judge (e.g. an internal kimi-k2.5 deployment). Configure each downstream
separately by overriding env vars when launching:

  # Agent path
  UPSTREAM_BASE_URL=https://your-azure-endpoint   UPSTREAM_API_KEY=...   \\
      UPSTREAM_MODEL=gemini-3.1-p   PROXY_PORT=8002   python openai_compat_proxy.py

  # Judge path (parallel proxy instance)
  UPSTREAM_BASE_URL=https://your-kimi-endpoint   UPSTREAM_API_KEY=...   \\
      UPSTREAM_MODEL=kimi-k2.5   PROXY_PORT=8003   python openai_compat_proxy.py

Then in .env:
  PASB_BACKEND=custom_proxy
  PASB_BACKBONE_URL=http://localhost:8002/v1
  PASB_BACKBONE_MODEL=gemini-3.1-p
  PASB_BACKBONE_API_KEY=any-string

  PASB_JUDGE_BASE_URL=http://localhost:8003/v1
  PASB_JUDGE_MODEL=kimi-k2.5
  PASB_JUDGE_API_KEY=any-string
"""
import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from openai import OpenAI  # swap to AzureOpenAI if your upstream is Azure-style

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

UPSTREAM_BASE_URL = os.environ.get("UPSTREAM_BASE_URL", "https://api.openai.com/v1")
UPSTREAM_API_KEY = os.environ.get("UPSTREAM_API_KEY", "")
UPSTREAM_MODEL = os.environ.get("UPSTREAM_MODEL", "")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8002"))

if not UPSTREAM_API_KEY:
    raise SystemExit("UPSTREAM_API_KEY env var is required")
if not UPSTREAM_MODEL:
    raise SystemExit("UPSTREAM_MODEL env var is required")

client = OpenAI(api_key=UPSTREAM_API_KEY, base_url=UPSTREAM_BASE_URL)

# Whitelist of OpenAI-API fields forwarded verbatim. PASB-critical: tools, tool_choice.
_FORWARD_FIELDS = (
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "response_format",
    "stop",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "logit_bias",
    "n",
    "seed",
    "user",
)


class ProxyHandler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        self.send_response(status)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        if self.path in ("/v1/models", "/api/v1/models"):
            self._json(200, {"object": "list",
                             "data": [{"id": UPSTREAM_MODEL, "object": "model"}]})
        elif self.path == f"/v1/models/{UPSTREAM_MODEL}":
            self._json(200, {"id": UPSTREAM_MODEL, "object": "model"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/show":
            self._json(200, {"name": UPSTREAM_MODEL, "model": UPSTREAM_MODEL,
                             "details": {"family": "custom", "parameter_size": "unknown"}})
            return

        if self.path != "/v1/chat/completions":
            self.send_response(404); self.end_headers(); return

        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length))

        kwargs = {
            "model": UPSTREAM_MODEL,
            "messages": req.get("messages", []),
            "max_tokens": req.get("max_tokens", 8192),
            "temperature": req.get("temperature", 0.0),
            "stream": req.get("stream", False),
            "extra_headers": {"X-PASB-Trace": str(uuid.uuid4())},
        }
        # PASB-critical: forward tools / tool_choice. Without these the upstream
        # model never sees the agent's function declarations and commit pipeline
        # silently fails.
        for k in _FORWARD_FIELDS:
            if k in req and req[k] is not None:
                kwargs[k] = req[k]

        if kwargs.get("tools"):
            logging.info(
                f"forwarding {len(kwargs['tools'])} tools "
                f"(tool_choice={kwargs.get('tool_choice', 'auto')})"
            )

        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:
            logging.error(f"upstream error: {e}")
            self._json(500, {"error": str(e)})
            return

        self.send_response(200)
        if kwargs["stream"]:
            self.send_header("Content-type", "text/event-stream")
            self.end_headers()
            for chunk in resp:
                self.wfile.write(f"data: {json.dumps(chunk.model_dump())}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp.model_dump()).encode())


class ReusableTCPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"openai_compat_proxy upstream={UPSTREAM_BASE_URL} model={UPSTREAM_MODEL} "
          f"listening on :{PROXY_PORT}")
    ReusableTCPServer(("", PROXY_PORT), ProxyHandler).serve_forever()
