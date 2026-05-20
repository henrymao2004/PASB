#!/usr/bin/env python3
"""Reference OpenAI-compatible proxy for PASB closed-endpoint deployments.

Use this when your model is reachable only through an internal "Azure-style"
endpoint (e.g. Bytedance modelhub, internal Azure deployment, on-prem LLM
gateway). The proxy accepts the OpenAI `/v1/chat/completions` shape that
Hermes-CLI / OpenClaw emit, and forwards to your upstream while preserving
the load-bearing `tools` + `tool_choice` fields.

PASB depends critically on `tools` + `tool_choice` arriving intact at the
upstream model. The agent CANNOT commit anything to persistent state if the
model never sees the tool definitions, and the entire benchmark silently
collapses to "single-turn polite text". Do not strip these fields.

The same proxy script can serve both the agent backbone (e.g. port 8002 with
upstream=gemini-3.1-p) and the judge (e.g. port 8003 with upstream=kimi-k2.5).
Launch two instances on different ports.

------------------------------------------------------------
Example: agent path (Gemini-3.1-Pro via Bytedance modelhub)
------------------------------------------------------------
  UPSTREAM_BASE_URL=https://aidp.bytedance.net/api/modelhub/online/v2/crawl \
      UPSTREAM_API_KEY=$YOUR_BYTEDANCE_TOKEN \
      UPSTREAM_MODEL=gemini-3.1-p \
      UPSTREAM_API_VERSION=2024-03-01-preview \
      PROXY_PORT=8002 \
      python examples/proxies/openai_compat_proxy.py

------------------------------------------------------------
Example: judge path (internal kimi-k2.5)
------------------------------------------------------------
  UPSTREAM_BASE_URL=https://aidp.bytedance.net/api/modelhub/online/v2/crawl \
      UPSTREAM_API_KEY=$YOUR_BYTEDANCE_TOKEN \
      UPSTREAM_MODEL=kimi-k2.5 \
      UPSTREAM_API_VERSION=2024-03-01-preview \
      PROXY_PORT=8003 \
      python examples/proxies/openai_compat_proxy.py

If your upstream is plain OpenAI-compatible (NOT Azure-style), set
UPSTREAM_CLIENT=openai (default is azure when UPSTREAM_API_VERSION is set).
"""
import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

UPSTREAM_BASE_URL = os.environ["UPSTREAM_BASE_URL"]
UPSTREAM_API_KEY = os.environ["UPSTREAM_API_KEY"]
UPSTREAM_MODEL = os.environ["UPSTREAM_MODEL"]
UPSTREAM_API_VERSION = os.environ.get("UPSTREAM_API_VERSION", "")
UPSTREAM_CLIENT = os.environ.get(
    "UPSTREAM_CLIENT", "azure" if UPSTREAM_API_VERSION else "openai"
).lower()
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8002"))

# Build SDK client (AzureOpenAI for Azure-style endpoints, OpenAI otherwise).
if UPSTREAM_CLIENT == "azure":
    from openai import AzureOpenAI
    client = AzureOpenAI(
        api_key=UPSTREAM_API_KEY,
        azure_endpoint=UPSTREAM_BASE_URL,
        api_version=UPSTREAM_API_VERSION or "2024-03-01-preview",
    )
else:
    from openai import OpenAI
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
        # model never sees the agent's function declarations and the commit
        # pipeline silently fails.
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
    print(f"openai_compat_proxy upstream={UPSTREAM_BASE_URL} "
          f"client={UPSTREAM_CLIENT} model={UPSTREAM_MODEL} "
          f"listening on :{PROXY_PORT}")
    ReusableTCPServer(("", PROXY_PORT), ProxyHandler).serve_forever()
