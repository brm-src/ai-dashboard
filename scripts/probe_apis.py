#!/usr/bin/env python3
"""
AI API Health Probe — stdlib only (no pip deps)
Probes all configured AI provider APIs, records status + model counts + response times.
Outputs JSON to data/latest.json and appends to data/history/YYYY-MM-DD.json
"""
import os, json, time, sys, urllib.request, urllib.error, ssl
from datetime import datetime, timezone
from pathlib import Path

# ── API Definitions ──────────────────────────────────────────────
APIS = [
    {
        "id": "xiaomi",
        "name": "Xiaomi (Mimo)",
        "url": "https://api.xiaomimimo.com/v1/models",
        "key_env": "XIAOMI_API_KEY",
        "auth": "bearer",
        "tier": "primary",
        "pricing": {"input": 0, "output": 0, "note": "Free tier"},
    },
    {
        "id": "nousresearch",
        "name": "NousResearch",
        "url": "https://inference-api.nousresearch.com/v1/models",
        "key_env": "NOUS_PORTAL_API_KEY",
        "auth": "bearer",
        "tier": "fallback",
        "pricing": {"input": 0, "output": 0, "note": "Portal credit"},
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/models",
        "key_env": "OPENROUTER_API_KEY",
        "auth": "bearer",
        "tier": "fallback",
        "pricing": {"input": None, "output": None, "note": "Varies per model"},
    },
    {
        "id": "google_gemini",
        "name": "Google Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models",
        "key_env": "GEMINI_API_KEY",
        "auth": "query_param",
        "tier": "fallback",
        "pricing": {"input": 0, "output": 0, "note": "Free tier"},
    },
    {
        "id": "groq",
        "name": "Groq",
        "url": "https://api.groq.com/openai/v1/models",
        "key_env": "GROQ_API_KEY",
        "auth": "bearer",
        "tier": "fallback",
        "pricing": {"input": 0, "output": 0, "note": "Free tier"},
    },
    {
        "id": "mistral",
        "name": "Mistral",
        "url": "https://api.mistral.ai/v1/models",
        "key_env": "MISTRAL_API_KEY",
        "auth": "bearer",
        "tier": "fallback",
        "pricing": {"input": 0, "output": 0, "note": "Free tier"},
    },
    {
        "id": "pioneer",
        "name": "Pioneer.ai",
        "url": "https://api.pioneer.ai/v1/models",
        "key_env": "PIONEER_API_KEY",
        "auth": "bearer",
        "tier": "fallback",
        "pricing": {"input": 1.25, "output": 3.75, "note": "Per 1M tokens"},
    },
    {
        "id": "dashscope",
        "name": "DashScope (Qwen)",
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        "key_env": "DASHSCOPE_API_KEY",
        "auth": "bearer",
        "tier": "fallback",
        "pricing": {"input": None, "output": None, "note": "Varies"},
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "url": "https://api.openai.com/v1/models",
        "key_env": "OPENAI_API_KEY",
        "auth": "bearer",
        "tier": "fallback",
        "pricing": {"input": 2.5, "output": 10, "note": "Per 1M (gpt-4.1)"},
    },
    {
        "id": "b_ai",
        "name": "b.ai",
        "url": "https://api.b.ai/v1/models",
        "key_env": "B_AI_API_KEY",
        "auth": "bearer",
        "tier": "fallback",
        "pricing": {"input": None, "output": None, "note": "Multi-model aggregator"},
    },
    {
        "id": "freellmapi",
        "name": "FreeLLMAPI (local)",
        "url": "http://localhost:3001/v1/models",
        "key_env": "FREELLMAPI_UNIFIED_KEY",
        "auth": "bearer",
        "tier": "fallback",
        "pricing": {"input": 0, "output": 0, "note": "Self-hosted"},
        "optional": True,
    },
]

ctx = ssl.create_default_context()

def probe_one(api_def):
    key = os.environ.get(api_def["key_env"], "")
    result = {
        "id": api_def["id"],
        "name": api_def["name"],
        "tier": api_def["tier"],
        "pricing": api_def["pricing"],
        "status": "no_key",
        "http_code": None,
        "response_ms": None,
        "model_count": 0,
        "models": [],
        "error": None,
    }

    if not key:
        if api_def.get("optional"):
            result["status"] = "offline"
            result["error"] = "Service not running"
        return result

    headers = {"User-Agent": "ai-dashboard/1.0"}
    url = api_def["url"]

    if api_def["auth"] == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    elif api_def["auth"] == "query_param":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={key}"

    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        t0 = time.monotonic()
        try:
            resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        except urllib.error.HTTPError as e:
            elapsed = (time.monotonic() - t0) * 1000
            result["http_code"] = e.code
            result["response_ms"] = round(elapsed, 1)
            if e.code in (401, 403):
                result["status"] = "auth_error"
                result["error"] = f"HTTP {e.code}: invalid key"
            elif e.code in (502, 503):
                result["status"] = "down"
                result["error"] = f"HTTP {e.code}: service unavailable"
            elif e.code == 429:
                result["status"] = "rate_limited"
                result["error"] = "Rate limited"
            else:
                result["status"] = "error"
                result["error"] = f"HTTP {e.code}"
            return result

        elapsed = (time.monotonic() - t0) * 1000
        result["http_code"] = resp.status
        result["response_ms"] = round(elapsed, 1)

        body = resp.read().decode("utf-8", errors="replace")
        data = json.loads(body)

        if "data" in data:
            models = [m.get("id", "") for m in data["data"]]
        elif "models" in data:
            models = [m.get("name", "").replace("models/", "") for m in data["models"]]
        else:
            models = []

        result["status"] = "ok"
        result["model_count"] = len(models)
        result["models"] = sorted(models)

    except urllib.error.URLError as e:
        result["status"] = "offline"
        result["error"] = str(e.reason)[:200] if hasattr(e, "reason") else str(e)[:200]
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:200]

    return result


def run_probe():
    now = datetime.now(timezone.utc)
    results = []
    for api_def in APIS:
        print(f"  Probing {api_def['name']}...", end=" ", flush=True)
        r = probe_one(api_def)
        icons = {"ok": "OK", "auth_error": "AUTH", "down": "DOWN", "offline": "OFF",
                 "no_key": "NO_KEY", "timeout": "TIMEOUT", "rate_limited": "RATE", "error": "ERR"}
        print(f"{icons.get(r['status'], '?')} ({r['response_ms'] or '-'}ms)")
        results.append(r)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    total_models = sum(r["model_count"] for r in results)

    snapshot = {
        "timestamp": now.isoformat(),
        "timestamp_unix": int(now.timestamp()),
        "summary": {
            "total_apis": len(results),
            "apis_ok": ok_count,
            "apis_down": len(results) - ok_count,
            "total_models": total_models,
        },
        "apis": results,
    }
    return snapshot


def save_snapshot(snapshot):
    base = Path(__file__).resolve().parent.parent / "data"
    base.mkdir(parents=True, exist_ok=True)

    # Latest
    with open(base / "latest.json", "w") as f:
        json.dump(snapshot, f, indent=2)

    # History (append to daily file)
    date_str = datetime.fromisoformat(snapshot["timestamp"]).strftime("%Y-%m-%d")
    history_path = base / "history" / f"{date_str}.json"

    if history_path.exists():
        with open(history_path) as f:
            history = json.load(f)
    else:
        history = []

    compact = dict(snapshot)
    compact["apis"] = [{k: v for k, v in a.items() if k != "models"} for a in snapshot["apis"]]
    history.append(compact)

    if len(history) > 50:
        history = history[-50:]

    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)

    print(f"\nSaved: data/latest.json + data/history/{date_str}.json")


if __name__ == "__main__":
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k not in os.environ:
                    os.environ[k] = v

    print("AI API Health Probe")
    print("=" * 40)
    snapshot = run_probe()
    save_snapshot(snapshot)
    s = snapshot["summary"]
    print(f"\n{'=' * 40}")
    print(f"  {s['apis_ok']}/{s['total_apis']} APIs OK | {s['total_models']} total models")
