"""Real endpoints, for auditing a provider you actually pay.

The difference between this file and providers.py is the whole difference
between a demo and a tool.

providers.py is a RESEARCH HARNESS: its query() takes a `mode`, and it plays
BOTH sides -- it simulates the dishonest provider in order to prove the
protocol separates honest from skimmed serving. That was the right thing to
build to establish the result, and it is useless to a customer, because a
customer has an endpoint and no mode to pass.

Everything here takes a question and returns an answer. There is no mode, no
scenario, and no way for the auditor to influence how the endpoint serves the
request. That is what makes a receipt produced from these clients mean
something: nothing in the loop knows whether the endpoint is honest.

One rule these clients follow that matters more than it looks: they never cap
output length. The audit must observe what the endpoint does naturally -- an
auditor who imposes a tight token budget has skimmed the endpoint themselves
and would measure their own constraint.

Supported today:

    anthropic   Claude, via the Messages API
    openai      any OpenAI-compatible /chat/completions endpoint. That covers
                OpenAI, Groq, Together, Mistral, DeepSeek, Fireworks,
                OpenRouter, vLLM, LM Studio and most self-hosted servers --
                pass --base-url.
    ollama      a local Ollama daemon

Stdlib only, like everything else on the verification path.
"""
import json
import os
import urllib.error
import urllib.request

# Generous, not restrictive: enough room for a model to deliberate in the
# visible response if that is how it works. Effort is tokens generated wherever
# they appear -- capping this would hide exactly what we came to measure.
MAX_TOKENS = 8000
TIMEOUT = 300


class EndpointError(RuntimeError):
    """A request failed in a way the auditor must see, not silently score."""


def _stored_key(target):
    """Windows Credential Manager fallback, so a key never has to be pasted.

    A pasted key ends up in shell history and scrollback. providers.py already
    reads the credential store; reusing it means the audit client works on a
    machine where the key was stored properly, with no env var and no --api-key.
    Absent or unreadable store is not an error -- callers fall back to env.
    """
    try:
        from providers import read_windows_credential
        return read_windows_credential(target)
    except Exception:
        return None


def _post(url, body, headers, timeout=TIMEOUT):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise EndpointError(f"HTTP {e.code} from {url}: {detail}") from None
    except Exception as e:
        raise EndpointError(f"{type(e).__name__} calling {url}: {e}") from None


class AnthropicEndpoint:
    name = "anthropic"

    def __init__(self, model="claude-haiku-4-5", api_key=None, base_url=None):
        self.model = model
        self.url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        self.key = (api_key or os.environ.get("ANTHROPIC_API_KEY")
                    or _stored_key("blindkeep-empire:ANTHROPIC_API_KEY"))
        if not self.key:
            raise EndpointError(
                "no API key. Set ANTHROPIC_API_KEY, store it in the Windows "
                "Credential Manager as 'blindkeep-empire:ANTHROPIC_API_KEY', "
                "or pass --api-key.")

    def query(self, question):
        body = {"model": self.model, "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": question}]}
        d = _post(self.url, body,
                  {"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        text, thinking = [], 0
        for blk in d.get("content", []):
            if blk.get("type") == "text":
                text.append(blk.get("text", ""))
            elif blk.get("type") == "thinking":
                thinking += len(blk.get("thinking", "") or "")
        u = d.get("usage", {}) or {}
        return "\n".join(text), {"output_tokens": u.get("output_tokens", 0),
                                 "input_tokens": u.get("input_tokens", 0),
                                 "thinking_chars": thinking,
                                 "stop_reason": d.get("stop_reason")}


class OpenAICompatEndpoint:
    """Any /chat/completions endpoint. base_url is the part before /chat/..."""
    name = "openai"

    def __init__(self, model="gpt-5", api_key=None,
                 base_url="https://api.openai.com/v1"):
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        # Many self-hosted servers need no key at all, so an absent key is not
        # an error here the way it is for a hosted API.
        self.key = api_key or os.environ.get("OPENAI_API_KEY") or ""

    def query(self, question):
        body = {"model": self.model, "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": question}]}
        headers = {"authorization": f"Bearer {self.key}"} if self.key else {}
        d = _post(self.url, body, headers)
        ch = (d.get("choices") or [{}])[0]
        text = (ch.get("message") or {}).get("content") or ""
        u = d.get("usage", {}) or {}
        return text, {"output_tokens": u.get("completion_tokens", 0),
                      "input_tokens": u.get("prompt_tokens", 0),
                      "thinking_chars": 0,
                      "stop_reason": ch.get("finish_reason")}


class OllamaEndpoint:
    name = "ollama"

    def __init__(self, model="gemma:2b", api_key=None,
                 base_url="http://localhost:11434"):
        self.model = model
        self.url = base_url.rstrip("/") + "/api/generate"

    def query(self, question):
        d = _post(self.url, {"model": self.model, "prompt": question,
                             "stream": False}, {})
        return d.get("response", ""), {
            "output_tokens": d.get("eval_count", 0),
            "input_tokens": d.get("prompt_eval_count", 0),
            "thinking_chars": 0, "stop_reason": d.get("done_reason")}


ENDPOINTS = {"anthropic": AnthropicEndpoint,
             "openai": OpenAICompatEndpoint,
             "ollama": OllamaEndpoint}


def get_endpoint(name, **kw):
    if name not in ENDPOINTS:
        raise EndpointError(
            f"unknown endpoint {name!r}. Available: {', '.join(ENDPOINTS)}. "
            f"For any OpenAI-compatible service use --provider openai with "
            f"--base-url.")
    kw = {k: v for k, v in kw.items() if v is not None}
    return ENDPOINTS[name](**kw)
