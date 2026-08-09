"""Endpoint adapters.

The honest/hollow distinction is always the SAME MODEL with a different amount
of computation per request -- never a different model. That is the attack every
existing attestation layer misses, so it is the only one worth measuring.

  ollama    : reasoning prompt + generous token budget  vs  suppressed + clipped
  anthropic : extended thinking ENABLED  vs  DISABLED and output-capped

For the Anthropic adapter the hollow mode is not a simulation of the attack --
it IS the attack. A provider that silently serves `reasoning_effort: none`
while billing for a reasoning tier produces exactly this: same weights, same
binary, same signed response, less compute.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import urllib.request

# --------------------------------------------------------------- secrets ----


def read_windows_credential(target: str):
    """Read a Generic credential from Windows Credential Manager.

    The secret is returned to the caller and never logged, echoed, or written
    to disk. Pasting a key into a terminal burns it; reading it from the OS
    keystore at point of use does not.
    """
    CRED_TYPE_GENERIC = 1

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wt.DWORD), ("Type", wt.DWORD),
            ("TargetName", wt.LPWSTR), ("Comment", wt.LPWSTR),
            ("LastWritten", wt.FILETIME),
            ("CredentialBlobSize", wt.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
            ("Persist", wt.DWORD), ("AttributeCount", wt.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wt.LPWSTR), ("UserName", wt.LPWSTR),
        ]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    advapi.CredReadW.restype = wt.BOOL
    ptr = ctypes.POINTER(CREDENTIAL)()
    if not advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
        return None
    try:
        blob = ctypes.string_at(ptr.contents.CredentialBlob,
                                ptr.contents.CredentialBlobSize)
    finally:
        advapi.CredFree(ptr)
    for enc in ("utf-16-le", "utf-8"):
        try:
            s = blob.decode(enc).strip("\x00").strip()
            if s.startswith("sk-"):
                return s
        except UnicodeDecodeError:
            continue
    return None


def anthropic_key():
    return (os.environ.get("ANTHROPIC_API_KEY")
            or read_windows_credential("blindkeep-empire:ANTHROPIC_API_KEY"))


# ------------------------------------------------------------- providers ----

class OllamaProvider:
    name = "ollama"

    def __init__(self, model="gemma:2b", url="http://localhost:11434/api/generate"):
        self.model, self.url = model, url

    def query(self, question, mode):
        import endpoint as E
        text, tok = E.query(question, "honest" if mode == "honest" else "hollow")
        return text, {"output_tokens": tok, "thinking_tokens": 0}


class AnthropicProvider:
    """Claude via the Messages API.

    honest : extended thinking enabled with a real budget
    hollow : thinking disabled AND max_tokens capped -- the effort skim

    Both modes send the CUSTOMER'S PROMPT UNCHANGED. Only the serving
    configuration differs, which is precisely the knob a provider controls and
    the customer cannot see.
    """
    name = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    # Haiku 4.5 is the cheapest model supporting extended thinking, and it
    # takes the pre-4.6 form: {"type": "enabled", "budget_tokens": N}, which
    # must be < max_tokens and at least 1024. `effort` is rejected on 4.5.
    def __init__(self, model="claude-haiku-4-5", think_budget=4000,
                 honest_max=5000, hollow_max=300, api_key=None):
        self.model = model
        self.think_budget = think_budget
        self.honest_max = honest_max
        self.hollow_max = hollow_max
        self.key = api_key or anthropic_key()
        if not self.key:
            raise RuntimeError("no Anthropic API key available")

    def query(self, question, mode):
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": question}],
        }
        if mode == "honest":
            body["max_tokens"] = self.honest_max
            body["thinking"] = {"type": "enabled",
                                "budget_tokens": self.think_budget}
        else:
            body["max_tokens"] = self.hollow_max   # no thinking field = no thinking

        req = urllib.request.Request(
            self.URL, data=json.dumps(body).encode(),
            headers={"content-type": "application/json",
                     "x-api-key": self.key,
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read())

        text, think_chars = [], 0
        for blk in d.get("content", []):
            if blk.get("type") == "text":
                text.append(blk.get("text", ""))
            elif blk.get("type") == "thinking":
                think_chars += len(blk.get("thinking", "") or "")
        usage = d.get("usage", {}) or {}
        return "\n".join(text), {
            "output_tokens": usage.get("output_tokens", 0),
            "input_tokens": usage.get("input_tokens", 0),
            "thinking_chars": think_chars,
            "stop_reason": d.get("stop_reason"),
        }


def get_provider(name, **kw):
    if name == "ollama":
        return OllamaProvider(**kw)
    if name == "anthropic":
        return AnthropicProvider(**kw)
    raise ValueError(f"unknown provider: {name}")
