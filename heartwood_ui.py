"""The Heartwood button: run an audit from a browser, watch it live.

    python heartwood_ui.py

Opens http://127.0.0.1:8731 and serves a small control panel.

WHY THIS RUNS LOCALLY AND NOT ON THE WEBSITE
    An audit needs your API key. A hosted page that collected it would be
    asking you to hand your provider credentials to a third party in order to
    check whether that provider is trustworthy, which is a contradiction. So
    this is a local server: the key is read from your own environment or
    credential store, never travels anywhere except to the provider you are
    auditing, and is never written to the receipt, the log, or the page.

    The listener binds to 127.0.0.1 only. It is not reachable from your
    network.

Stdlib only, like the rest of the verification path.
"""
import html
import json
import pathlib
import queue
import socketserver
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler

import challenges as C
import endpoint as E
import endpoints as EP
import heartwood as H

HERE = pathlib.Path(__file__).parent
PORT = 8731
RUNS = {}          # run_id -> {"q": Queue, "receipt": dict|None, "done": bool}


# --------------------------------------------------------------- the run ----

def run_audit(run_id, cfg):
    """Execute an audit, pushing progress events onto the run's queue."""
    st = RUNS[run_id]
    emit = lambda **kw: st["q"].put(kw)
    try:
        ep = EP.get_endpoint(cfg["provider"], model=cfg.get("model") or None,
                             base_url=cfg.get("base_url") or None)
        fams = [cfg["family"]] if cfg.get("family") else None
        emit(stage="start", msg=f"endpoint: {cfg['provider']} · {ep.model}")

        # --- p0 -----------------------------------------------------------
        if cfg.get("p0"):
            p0 = float(cfg["p0"])
            cal = {"source": "declared", "n": None, "successes": None,
                   "raw_rate": None, "method": "operator-declared",
                   "note": cfg.get("p0_note") or "supplied in the UI"}
            emit(stage="calib", msg=f"p0 = {p0:.3f} (declared, not measured)")
        else:
            n = int(cfg["calib"])
            emit(stage="calib", warn=True, msg=(
                "Calibrating through the endpoint under audit. A provider that "
                "skims during calibration drags p0 down to where it is already "
                "performing, and the audit can never fire. Recorded as "
                "'endpoint_self'."))
            pool = C.make_pool(555555, n, int(cfg["difficulty"]), fams)
            ok = 0
            for i, it in enumerate(pool, 1):
                resp, _ = ep.query(it["q"])
                ok += E.grade(E.extract(resp), it["a"], resp)
                emit(stage="calib", msg=f"calibration {i}/{n} · rate {ok/i:.2f}")
            p0 = H.lower_conf_bound(ok, n, conf=0.99)
            cal = {"source": "endpoint_self", "n": n, "successes": ok,
                   "raw_rate": ok / n, "method": "wilson_lower_99",
                   "note": "measured through the endpoint under audit"}
            emit(stage="calib", msg=f"p0 = {p0:.3f} (99% lower bound on {ok}/{n})")

        p1 = float(cfg["p1"])
        if p0 <= p1:
            emit(stage="error", msg=(
                f"p0 ({p0:.3f}) is at or below your tolerance ({p1}). There is "
                f"no capability gap to test on — every query would be "
                f"uninformative. Raise the difficulty, or lower the tolerance."))
            st["done"] = True
            return

        # --- commit + beacon ---------------------------------------------
        size = int(cfg["pool"])
        seed = int(time.time())
        pool = C.make_pool(seed, size, int(cfg["difficulty"]), fams)
        commitment = C.pool_commitment(pool)
        emit(stage="commit", msg=f"pool committed: {commitment[:40]}…")

        beacon = H.fetch_beacon()
        if beacon.get("randomness") is None or not beacon.get("round"):
            emit(stage="error", msg=(
                "drand is unreachable, so no receipt will be written. A receipt "
                "whose beacon the auditor picked is worthless — choosing it "
                "manufactures a false verdict in about a thousand tries."))
            st["done"] = True
            return
        emit(stage="beacon", msg=f"drand round {beacon['round']} drawn")

        order = H.selection_order(commitment, beacon, len(pool))
        lam = H.kelly_lambda(p0, p1)
        thr = __import__("math").log10(1.0 / float(cfg["alpha"]))
        plan = {"p0": p0, "p1": p1, "alpha": float(cfg["alpha"]), "lambda": lam,
                "pool_size": size, "max_queries": int(cfg["maxq"]),
                "families": fams}

        # --- audit --------------------------------------------------------
        transcript, lw = [], 0.0
        for k, item_id in enumerate(order[:int(cfg["maxq"])], 1):
            it = pool[item_id]
            resp, meta = ep.query(it["q"])
            g = E.grade(E.extract(resp), it["a"], resp)
            transcript.append({"item_id": item_id,
                               "question_sha256": H.sha(it["q"]),
                               "response": resp,
                               "response_sha256": H.sha(resp),
                               "graded": g,
                               "output_tokens": meta.get("output_tokens")})
            lw += __import__("math").log10(1.0 + lam * (p0 - g))
            emit(stage="query", n=k, graded=g, wealth=round(lw, 3),
                 threshold=round(thr, 3),
                 rate=round(sum(t["graded"] for t in transcript) / k, 3),
                 tokens=meta.get("output_tokens"))
            if lw >= thr:
                break

        receipt = H.build_receipt(seed, int(cfg["difficulty"]), commitment,
                                  beacon, plan, cal, transcript, "ui")
        receipt["endpoint"] = {"provider": cfg["provider"], "model": ep.model,
                               "audited_at": time.strftime(
                                   "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        v = H.verify_receipt(receipt)
        anc = H.verify_beacon_online(receipt)
        st["receipt"] = receipt
        emit(stage="done", verdict=receipt["result"]["verdict"],
             queries=receipt["result"]["n_queries"],
             rate=receipt["result"]["observed_rate"],
             peak=round(receipt["result"]["peak_log10_wealth"], 3),
             threshold=round(thr, 3), valid=v["valid"],
             anchored=anc["anchored"], anchor_reason=anc["reason"],
             p0_source=cal["source"])
    except EP.EndpointError as e:
        emit(stage="error", msg=str(e))
    except Exception:                                        # pragma: no cover
        emit(stage="error", msg="unexpected failure:\n"
             + traceback.format_exc()[-600:])
    finally:
        st["done"] = True


# ------------------------------------------------------------- the server ----

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass                                # keep the console for the audit

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE)
        if self.path.startswith("/events/"):
            return self.stream(self.path.rsplit("/", 1)[-1])
        if self.path.startswith("/receipt/"):
            run = RUNS.get(self.path.rsplit("/", 1)[-1])
            if not run or not run.get("receipt"):
                return self._send(404, "no receipt", "text/plain")
            return self._send(200, json.dumps(run["receipt"], indent=2),
                              "application/json")
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/run":
            return self._send(404, "not found", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        cfg = json.loads(self.rfile.read(n) or "{}")
        run_id = f"r{int(time.time()*1000)}"
        RUNS[run_id] = {"q": queue.Queue(), "receipt": None, "done": False}
        threading.Thread(target=run_audit, args=(run_id, cfg),
                         daemon=True).start()
        self._send(200, json.dumps({"run": run_id}), "application/json")

    def stream(self, run_id):
        """Server-sent events: one JSON object per progress step."""
        st = RUNS.get(run_id)
        if not st:
            return self._send(404, "unknown run", "text/plain")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        while True:
            try:
                ev = st["q"].get(timeout=0.5)
            except queue.Empty:
                if st["done"] and st["q"].empty():
                    break
                try:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionAbortedError):
                    return
                continue
            try:
                self.wfile.write(
                    f"data: {json.dumps(ev)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionAbortedError):
                return


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Heartwood — run an audit</title><style>
:root{--bg:#fbf9f6;--panel:#fff;--ink:#1a1714;--muted:#6b625a;--line:#e3ddd4;
--accent:#9a4a1e;--soft:#f3e6dd;--good:#2f6b46;--goodsoft:#e4f0e9;--bad:#9a2a2a;
--badsoft:#f6e4e4;--warn:#8a5a06;--warnsoft:#f7ecd6;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14120f;
--panel:#1c1916;--ink:#efe9e1;--muted:#a49a8e;--line:#2e2924;--accent:#e0895a;
--soft:#2b201a;--good:#6fbf8f;--goodsoft:#16261d;--bad:#e0736f;--badsoft:#2b1917;
--warn:#d9a441;--warnsoft:#2a2214}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:var(--sans);line-height:1.6}
.wrap{max-width:56rem;margin:0 auto;padding:0 1.5rem}
header{padding:2.25rem 0 1.25rem;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:1.5rem;letter-spacing:-.02em}
.sub{color:var(--muted);font-family:var(--mono);font-size:.82rem;margin-top:.15rem}
.lede{color:var(--muted);max-width:44rem;margin:.9rem 0 0}
.tabs{display:flex;gap:.4rem;margin-top:1.2rem;border-bottom:1px solid var(--line)}
.tab{padding:.5rem .95rem;border:1px solid transparent;border-bottom:none;
border-radius:.4rem .4rem 0 0;background:none;color:var(--muted);font:inherit;
font-size:.9rem;cursor:pointer;margin-bottom:-1px}
.tab[aria-selected=true]{background:var(--panel);border-color:var(--line);
color:var(--ink);font-weight:600}
.tab:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible
{outline:2px solid var(--accent);outline-offset:2px}
.panel{padding:1.5rem 0 3rem}.panel[hidden]{display:none}
.grid{display:grid;gap:.9rem 1.1rem;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr))}
label{display:block;font-size:.82rem;color:var(--muted);margin-bottom:.2rem}
label b{color:var(--ink);font-weight:600;font-size:.9rem;display:block}
input,select{width:100%;padding:.45rem .6rem;border:1px solid var(--line);
border-radius:.35rem;background:var(--panel);color:var(--ink);font:inherit;font-size:.9rem}
.hint{font-size:.78rem;color:var(--muted);margin-top:.25rem;display:block}
.act{margin-top:1.4rem;display:flex;gap:.6rem;flex-wrap:wrap;align-items:center}
button.go{padding:.6rem 1.4rem;border-radius:.4rem;border:1px solid var(--accent);
background:var(--accent);color:var(--bg);font:inherit;font-weight:600;cursor:pointer}
button.go[disabled]{opacity:.5;cursor:not-allowed}
button.ghost{padding:.6rem 1rem;border-radius:.4rem;border:1px solid var(--line);
background:var(--panel);color:var(--ink);font:inherit;cursor:pointer}
.log{margin-top:1.4rem;border:1px solid var(--line);border-radius:.5rem;
background:var(--panel);max-height:22rem;overflow:auto;font-family:var(--mono);
font-size:.8rem}
.log div{padding:.3rem .8rem;border-bottom:1px solid var(--line)}
.log div:last-child{border-bottom:none}
.log .miss{color:var(--bad)}.log .hit{color:var(--good)}
.log .warn{background:var(--warnsoft);color:var(--warn);white-space:pre-wrap}
.log .err{background:var(--badsoft);color:var(--bad);white-space:pre-wrap}
.bar{height:5px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:.5rem}
.bar i{display:block;height:100%;background:var(--accent);width:0;transition:width .25s}
.res{margin-top:1.4rem;border:1px solid var(--line);border-radius:.5rem;padding:1.1rem 1.25rem;
background:var(--panel)}
.res.ok{background:var(--goodsoft);border-color:var(--good)}
.res.hit{background:var(--badsoft);border-color:var(--bad)}
.res h2{margin:0 0 .35rem;font-size:1.1rem}.res p{margin:.3rem 0 0;font-size:.9rem}
dl{display:grid;grid-template-columns:auto 1fr;gap:.2rem .9rem;margin:.8rem 0 0;font-size:.85rem}
dt{color:var(--muted);font-family:var(--mono);font-size:.78rem}
dd{margin:0;font-family:var(--mono)}
h3{font-size:1rem;margin:1.5rem 0 .3rem}
p.note,li{color:var(--muted);max-width:44rem}li{margin-bottom:.35rem}
li::marker{color:var(--accent)}li b{color:var(--ink)}
code{font-family:var(--mono);font-size:.87em;background:var(--soft);padding:.06em .3em;border-radius:.2rem}
.quote{margin-top:2rem;border-left:3px solid var(--accent);padding-left:1rem;color:var(--muted);max-width:40rem}
.quote i{color:var(--ink)}.quote small{display:block;margin-top:.25rem;font-size:.78rem}
</style></head><body>
<header><div class=wrap>
<h1>Run a Heartwood audit</h1>
<div class=sub>local · your API key never leaves this machine</div>
<p class=lede>This panel is served by a program on your own computer, bound to
127.0.0.1. It reads your key from your environment or credential store, sends
it only to the provider you are auditing, and never writes it to the receipt,
the log, or this page.</p>
<div class=tabs role=tablist>
<button class=tab id=t-run role=tab aria-selected=true aria-controls=p-run>Run</button>
<button class=tab id=t-help role=tab aria-selected=false aria-controls=p-help>How to read this</button>
</div></div></header>
<main class=wrap>

<section class=panel id=p-run role=tabpanel aria-labelledby=t-run>
<div class=grid>
<div><label><b>Provider</b></label><select id=provider>
<option value=anthropic>Anthropic (Claude)</option>
<option value=openai>OpenAI-compatible</option>
<option value=ollama>Ollama (local)</option></select>
<span class=hint>OpenAI-compatible covers OpenAI, Groq, Together, Mistral,
OpenRouter, vLLM, LM Studio.</span></div>

<div><label><b>Model</b></label><input id=model placeholder="claude-haiku-4-5">
<span class=hint>Exactly as your provider names it.</span></div>

<div><label><b>API base URL</b></label><input id=base_url placeholder="(provider default)">
<span class=hint>Only for OpenAI-compatible or self-hosted servers.</span></div>

<div><label><b>Difficulty</b></label><select id=difficulty>
<option value=1>1 — small local models</option>
<option value=3 selected>3 — mid-size / fast models</option>
<option value=5>5 — frontier models</option></select>
<span class=hint>Too easy and every answer is right whether or not effort was
spent, so nothing is learned. Frontier models need tier 5.</span></div>

<div><label><b>Tolerance (p1)</b></label><input id=p1 type=number step=0.05 min=0.05 max=0.95 value=0.4>
<span class=hint>The success rate you would call a real deficit. Higher catches
milder throttling but costs more queries.</span></div>

<div><label><b>Confidence (α)</b></label><select id=alpha>
<option value=0.05>0.05 — 1 false alarm in 20</option>
<option value=0.01 selected>0.01 — 1 in 100</option>
<option value=0.001>0.001 — 1 in 1000</option></select>
<span class=hint>The most an honest endpoint can be falsely accused.</span></div>

<div><label><b>Known-good rate (p0)</b></label><input id=p0 placeholder="(measure it here)">
<span class=hint><b>Leave blank and this is measured through the endpoint you
are auditing</b> — which a throttling provider can bias downward. Fill it from
a trusted source if you have one.</span></div>

<div><label><b>Calibration queries</b></label><input id=calib type=number min=5 max=200 value=20>
<span class=hint>Ignored if you supplied p0 above.</span></div>

<div><label><b>Max queries</b></label><input id=maxq type=number min=1 max=500 value=60>
<span class=hint>It stops early the moment the evidence is decisive.</span></div>
</div>

<div class=act>
<button class=go id=go>Run audit</button>
<button class=ghost id=save hidden>Download receipt</button>
<span class=hint id=cost></span>
</div>
<div class=bar><i id=prog></i></div>
<div class=log id=log hidden></div>
<div id=result></div>
</section>

<section class=panel id=p-help role=tabpanel aria-labelledby=t-help hidden>
<h3>What this actually does</h3>
<p class=note>It asks your endpoint questions that cannot be answered correctly
without doing the work, then counts how often it succeeds. If a provider is
quietly spending less compute than you are paying for, the answers get worse,
and enough wrong answers is evidence.</p>

<h3>Why the order matters</h3>
<p class=note>The questions are written and hashed <em>before</em> anything is
sent. Then a public random beacon — a value nobody controls, which did not
exist when the questions were locked — chooses which ones get used. So the
auditor cannot cherry-pick questions the endpoint will fail, and the provider
cannot guess which requests are the test. That ordering is what makes the
result something you can show someone else.</p>

<h3>Reading the verdict</h3>
<ul>
<li><b>EFFORT_DEFICIT</b> — the evidence crossed your threshold. At α = 0.01 an
honest endpoint produces this at most once in a hundred audits.</li>
<li><b>NO_EVIDENCE_OF_DEFICIT</b> — <em>not</em> a clean bill of health. It
means no deficit was shown within the queries spent, at the tolerance you set.
Absence of evidence, and it says so rather than pretending otherwise.</li>
</ul>

<h3>The one number to be careful about</h3>
<p class=note><b>p0</b> is the rate an honest endpoint should hit, and
everything is measured against it. If you leave it blank it gets measured
through the very endpoint you are auditing — so a provider that throttles
during calibration too will drag it down to its own performance, and the audit
can never fire. The receipt records which way you did it, so nobody reading it
is misled. Getting p0 from somewhere the provider cannot influence is the
strongest thing you can do for the result.</p>

<h3>What it does not do</h3>
<ul>
<li>It is not privacy tooling. It does not hide your prompts or encrypt
anything — it checks whether work was done.</li>
<li>It cannot catch a cheaper model that answers everything correctly.</li>
<li>It proves the auditor followed the protocol, not that the provider really
said these words. That needs a signature layer on top.</li>
</ul>

<p class=quote><i>&ldquo;Trusted third parties are security holes.&rdquo;</i>
<small>Nick Szabo, 2001. Which includes us: every receipt this produces can be
recomputed by someone who does not trust you or this program.</small></p>
</section>
</main>
<script>
const $=id=>document.getElementById(id);
const tabs=[...document.querySelectorAll('.tab')];
tabs.forEach(t=>t.onclick=()=>tabs.forEach(o=>{const on=o===t;
o.setAttribute('aria-selected',on);$(o.getAttribute('aria-controls')).hidden=!on;}));

let runId=null;
function line(txt,cls){const d=document.createElement('div');
if(cls)d.className=cls;d.textContent=txt;$('log').appendChild(d);
$('log').scrollTop=$('log').scrollHeight;}

$('go').onclick=async()=>{
  $('go').disabled=true;$('save').hidden=true;$('result').innerHTML='';
  $('log').hidden=false;$('log').innerHTML='';$('prog').style.width='0';
  const cfg={provider:$('provider').value,model:$('model').value.trim(),
    base_url:$('base_url').value.trim(),difficulty:$('difficulty').value,
    p1:$('p1').value,alpha:$('alpha').value,p0:$('p0').value.trim(),
    calib:$('calib').value,maxq:$('maxq').value,pool:300,family:''};
  const r=await fetch('/run',{method:'POST',body:JSON.stringify(cfg)});
  runId=(await r.json()).run;
  const es=new EventSource('/events/'+runId);
  es.onmessage=e=>{
    const d=JSON.parse(e.data);
    if(d.stage==='query'){
      const pct=Math.max(0,Math.min(100,100*d.wealth/d.threshold));
      $('prog').style.width=(d.wealth>0?pct:0)+'%';
      line(`q${String(d.n).padStart(3)}  ${d.graded?'correct':'WRONG  '}  `
        +`rate ${d.rate.toFixed(2)}  evidence 10^${d.wealth.toFixed(2)} / 10^${d.threshold.toFixed(0)}`
        +(d.tokens?`  ${d.tokens} tok`:''), d.graded?'hit':'miss');
    } else if(d.stage==='error'){ line(d.msg,'err'); es.close(); $('go').disabled=false;
    } else if(d.stage==='done'){ es.close(); $('go').disabled=false; done(d);
    } else { line(d.msg, d.warn?'warn':''); }
  };
  es.onerror=()=>{es.close();$('go').disabled=false;};
};

function done(d){
  const hit=d.verdict==='EFFORT_DEFICIT';
  $('prog').style.width='100%';
  $('result').innerHTML=`<div class="res ${hit?'hit':'ok'}">
    <h2>${hit?'Evidence of an effort deficit':'No deficit demonstrated'}</h2>
    <p>${hit
      ? `The endpoint underperformed your tolerance by enough to cross the threshold after ${d.queries} queries.`
      : `Nothing was shown within ${d.queries} queries at your tolerance. This is <b>not</b> a clean bill of health — it is absence of evidence.`}</p>
    <dl>
      <dt>verdict</dt><dd>${d.verdict}</dd>
      <dt>queries</dt><dd>${d.queries}</dd>
      <dt>success rate</dt><dd>${(d.rate*100).toFixed(1)}%</dd>
      <dt>evidence</dt><dd>10^${d.peak.toFixed(2)} vs 10^${d.threshold.toFixed(0)} needed</dd>
      <dt>receipt valid</dt><dd>${d.valid}</dd>
      <dt>beacon</dt><dd>${d.anchored===true?'anchored to the real chain':'NOT anchored — '+d.anchor_reason}</dd>
      <dt>p0 source</dt><dd>${d.p0_source}${d.p0_source==='endpoint_self'?'  ← measured through the audited endpoint':''}</dd>
    </dl></div>`;
  $('save').hidden=false;
}
$('save').onclick=()=>{ if(runId) location.href='/receipt/'+runId; };
</script></body></html>"""


def main():
    with Server(("127.0.0.1", PORT), Handler) as srv:
        url = f"http://127.0.0.1:{PORT}"
        print(f"Heartwood control panel: {url}")
        print("Bound to localhost only. Ctrl-C to stop.")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    sys.exit(main() or 0)
