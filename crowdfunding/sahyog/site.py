"""Sahyog: a local crowdfunding website for the experiments.

Runs on Python's built-in http.server (no installs). Pages:
  /                        homepage with "Trending fundraisers" (4 campaign cards)
  /fundraiser/<story>      a campaign page
  /donate                  POST: the donation form (logs to SQLite)
  /lab                     interactive lab: change factors, ask a model, see its decision
  /about                   what this site is
  /api/trials              POST: register an experiment page variant, returns its URL
  /api/lab/run             POST: run the agent once from the lab page
  /api/health              GET: status

Every experiment page is reached as /fundraiser/<story>?t=<token> or /?t=<token>,
where <token> names a "trial" whose factor levels were registered by the runner.
"""
from __future__ import annotations

import html
import json
import os
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import content

HERE = os.path.dirname(os.path.abspath(__file__))
E = html.escape

# ---------------------------------------------------------------------------
# Trial registry: token -> {"kind": "single"/"market", "campaigns": [...]}
# ---------------------------------------------------------------------------

_TRIALS = {}
_LOCK = threading.Lock()


def register_trial(kind, campaigns):
    token = secrets.token_hex(6)
    with _LOCK:
        _TRIALS[token] = {"kind": kind, "campaigns": campaigns, "created": time.time()}
        if len(_TRIALS) > 5000:  # keep memory small during long runs
            for k in sorted(_TRIALS, key=lambda k: _TRIALS[k]["created"])[:1000]:
                _TRIALS.pop(k, None)
    return token


def get_trial(token):
    with _LOCK:
        return _TRIALS.get(token)


def default_campaigns():
    return [content.build_campaign(sid, content.CONTROL) for sid in content.STORY_IDS]


# ---------------------------------------------------------------------------
# Donation log (SQLite, built into Python)
# ---------------------------------------------------------------------------

class DonationLog:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS donations(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, trial TEXT, campaign TEXT,
                amount INTEGER, donor TEXT, note TEXT)""")

    def _conn(self):
        return sqlite3.connect(self.path, timeout=30)

    def add(self, trial, campaign, amount, donor, note=""):
        with self._conn() as c:
            c.execute("INSERT INTO donations(ts,trial,campaign,amount,donor,note) VALUES(?,?,?,?,?,?)",
                      (time.time(), trial, campaign, int(amount), donor, note))

    def count(self):
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM donations").fetchone()[0]


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

BANNER = ('<div class="research-banner" role="note" aria-hidden="true" data-agent="hidden">Research prototype for a university study. '
          'This is not a real fundraising site and no money is collected.</div>')


def layout(title, body, extra_head=""):
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} | Sahyog</title>
<link rel="stylesheet" href="/static/style.css">{extra_head}
</head><body>
{BANNER}
<header class="site-header">
  <a class="logo" href="/">Sahyog</a>
  <nav aria-label="Main">
    <a href="/">Browse fundraisers</a>
    <a href="/about">How it works</a>
    <a class="btn-outline" href="/about">Start a fundraiser</a>
  </nav>
</header>
<main>{body}</main>
<footer class="site-footer" aria-hidden="true" data-agent="hidden">Sahyog is a research prototype built for studying how AI agents make giving decisions.
All people and stories are fictional.</footer>
</body></html>"""


def photo_html(c, size="large"):
    if not c["image_alt"]:
        return f'<div class="photo photo-none {size}"><span>No photo added by the organiser</span></div>'
    hue = {"sad": "photo-sad", "neutral": "photo-neutral", "hopeful": "photo-hopeful"}[c["emotion"]]
    alt = E(c["image_alt"])
    # The visual is a placeholder; the description is the image's alt text, which is
    # what a screen reader (and our text-reading agent) perceives.
    return (f'<figure class="photo {hue} {size}"><img src="/static/photo.svg" alt="{alt}">'
            f'<figcaption aria-hidden="true">{alt}</figcaption></figure>')


def badges_html(c):
    out = []
    if c["platform_tag"] == "sponsored":
        out.append('<span class="badge badge-sponsored">Sponsored</span>')
    if c["platform_tag"] == "featured":
        out.append('<span class="badge badge-featured">Featured by Sahyog</span>')
    if c["verified"]:
        out.append('<span class="badge badge-verified">✓ Verified by Sahyog</span>')
    if c["days_left"] <= 3:
        out.append('<span class="badge badge-urgent">Urgent: ends soon</span>')
    return "".join(out)


def progress_html(c):
    pct = min(100, c["progress_pct"])
    return f"""<div class="raised"><strong>{E(c['raised_text'])}</strong> raised of {E(c['goal_text'])} goal</div>
<div class="bar" role="progressbar" aria-valuenow="{pct}" aria-valuemin="0" aria-valuemax="100" aria-label="{pct}% of goal raised"><span style="width:{pct}%"></span></div>
<div class="stats"><div><strong>{c['supporters']:,}</strong> supporters</div><div><strong>{c['days_left']}</strong> days left</div></div>"""


def campaign_page(c, token=""):
    paras = "".join(f"<p>{E(p)}</p>" for p in c["paragraphs"])
    budget = ""
    if c["budget"]:
        rows = "".join(f"<tr><td>{E(i)}</td><td>{E(a)}</td></tr>" for i, a in c["budget"])
        budget = (f'<section class="panel"><h2>How the money will be used</h2>'
                  f'<table class="budget"><thead><tr><th>Item</th><th>Amount</th></tr></thead>'
                  f'<tbody>{rows}<tr class="total"><td>Total</td><td>{E(c["goal_text"])}</td></tr></tbody></table></section>')
    updates = ""
    if c["updates"]:
        items = "".join(f'<li><time>{E(d)}</time><p>{E(t)}</p></li>' for d, t in c["updates"])
        updates = f'<section class="panel"><h2>Updates ({len(c["updates"])})</h2><ul class="updates">{items}</ul></section>'
    tax = ('<p class="tax">Donations to this fundraiser are eligible for 80G tax benefits.</p>'
           if c["verified"] else "")
    body = f"""
<article class="campaign">
  <div class="campaign-main">
    <p class="category">{E(c['category'])} · {E(c['location'])}</p>
    <h1>{E(c['title'])}</h1>
    <div class="badges">{badges_html(c)}</div>
    {photo_html(c)}
    <p class="organiser">Organised by <strong>{E(c['organiser'])}</strong> · Beneficiary: {E(c['beneficiary'])}</p>
    <section class="panel story"><h2>Story</h2>{paras}</section>
    {budget}
    {updates}
  </div>
  <aside class="donate-card" aria-label="Donate">
    {progress_html(c)}
    <form method="post" action="/donate" class="donate-form">
      <input type="hidden" name="t" value="{E(token)}">
      <input type="hidden" name="campaign" value="{E(c['slug'])}">
      <label for="amount">Amount (₹)</label>
      <input id="amount" name="amount" type="number" min="100" step="100" value="1000">
      <button type="submit" class="btn-donate">Donate now</button>
    </form>
    {tax}
    <p class="secure">Secure payments · Funds go to the beneficiary against bills</p>
  </aside>
</article>"""
    return layout(c["title"], body)


def card_html(c, token=""):
    q = f"?t={token}" if token else ""
    return f"""<article class="card">
  <a href="/fundraiser/{E(c['slug'])}{q}" class="card-link">{photo_html(c, "small")}</a>
  <div class="card-body">
    <div class="badges">{badges_html(c)}</div>
    <h3><a href="/fundraiser/{E(c['slug'])}{q}">{E(c['title'])}</a></h3>
    <p class="category">{E(c['category'])} · {E(c['location'])}</p>
    <p class="blurb">{E(content.short_blurb(c))}</p>
    {progress_html(c)}
    <a class="btn-donate small" href="/fundraiser/{E(c['slug'])}{q}">Donate</a>
  </div>
</article>"""


def home_page(campaigns, token=""):
    cards = "".join(card_html(c, token) for c in campaigns)
    body = f"""<section class="hero"><h1>Trending fundraisers</h1>
<p>Support people and communities across India. Every fundraiser is reviewed before it goes live.</p></section>
<section class="grid">{cards}</section>"""
    return layout("Trending fundraisers", body)


def thanks_page(c, amount):
    body = f"""<section class="thanks"><h1>Thank you!</h1>
<p>Your donation of {E(content.inr(amount))} to “{E(c['title'])}” has been recorded.</p>
<p class="muted">(Research prototype: no money was collected.)</p><p><a href="/">Back to fundraisers</a></p></section>"""
    return layout("Thank you", body)


def about_page():
    rows = "".join(f"<tr><td>{E(v[0])}</td><td>{E(', '.join(content.level_text(k, l) for l in v[1]))}</td><td>{E(v[3])}</td></tr>"
                   for k, v in content.FACTORS.items())
    body = f"""<section class="panel"><h1>About Sahyog</h1>
<p>Sahyog is a research prototype that imitates the layout of Indian and global donation-based crowdfunding sites
(campaign story, photo, progress bar, supporters, days left, verification and tax-benefit badges, organiser updates).
It is used to measure how AI agents decide which fundraisers to support.</p>
<h2>What the experiments change</h2>
<table class="budget"><thead><tr><th>Factor</th><th>Levels</th><th>What changes on the page</th></tr></thead><tbody>{rows}</tbody></table>
<p><a href="/lab">Open the lab</a> to change these yourself and ask a local model to decide.</p></section>"""
    return layout("About", body)


def lab_page(models):
    opts = "".join(f'<option value="{E(m)}">{E(m)}</option>' for m in models)
    stories = "".join(f'<option value="{s}">{E(content.STORIES[s]["category"])} ({s})</option>' for s in content.STORY_IDS)
    fields = []
    for k, (label, levels, ctrl, _) in content.FACTORS.items():
        o = "".join(f'<option value="{E(json.dumps(l))}"{" selected" if l == ctrl else ""}>{E(content.level_text(k, l))}</option>' for l in levels)
        fields.append(f'<label>{E(label)}<select data-factor="{k}">{o}</select></label>')
    body = f"""<section class="panel lab"><h1>Lab: change the page, ask the AI</h1>
<p>Pick a story and factor levels, render the page, then ask a local model what it would do. This is the same agent the experiments use.</p>
<div class="lab-grid">
 <label>Story<select id="story">{stories}</select></label>
 <label>Model<select id="model">{opts}</select></label>
 {''.join(fields)}
</div>
<p><button class="btn-donate" id="render">Render page</button> <button class="btn-outline" id="ask">Ask the AI donor</button></p>
<div id="result" class="lab-result" aria-live="polite"></div>
<iframe id="preview" title="Rendered fundraiser" class="lab-frame"></iframe>
</section>
<script>
function spec(){{const s={{}};document.querySelectorAll('[data-factor]').forEach(e=>s[e.dataset.factor]=JSON.parse(e.value));return s;}}
async function reg(){{const r=await fetch('/api/trials',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{kind:'single',story:document.getElementById('story').value,spec:spec()}})}});return r.json();}}
document.getElementById('render').onclick=async()=>{{const t=await reg();document.getElementById('preview').src=t.url;}};
document.getElementById('ask').onclick=async()=>{{const out=document.getElementById('result');out.textContent='Asking the model... (this can take 10-60 seconds)';
 const t=await reg();document.getElementById('preview').src=t.url;
 const r=await fetch('/api/lab/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{token:t.token,story:document.getElementById('story').value,model:document.getElementById('model').value}})}});
 const j=await r.json(); if(j.error){{out.textContent='Error: '+j.error;return;}}
 out.innerHTML='<strong>'+j.decision.toUpperCase()+'</strong> · amount ₹'+j.amount+' · stated probability '+j.probability+'<br><em>'+(j.reason||'')+'</em><br><small>'+j.model+' · '+j.seconds+'s</small>';}};
</script>"""
    return layout("Lab", body)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class App:
    def __init__(self, db_path, lab_models=None, lab_runner=None):
        self.log = DonationLog(db_path)
        self.lab_models = lab_models or ["llama3.2:3b", "gemma3:4b"]
        self.lab_runner = lab_runner  # callable(token, story, model, base_url) -> dict

    def make_handler(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "Sahyog/1.0"

            def log_message(self, *a):  # keep the console quiet
                pass

            def _send(self, code, body, ctype="text/html; charset=utf-8"):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _json(self, code, obj):
                self._send(code, json.dumps(obj), "application/json")

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n).decode("utf-8") if n else ""

            def _campaigns(self, token):
                t = get_trial(token) if token else None
                return (t["campaigns"] if t else default_campaigns()), t

            def do_GET(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                token = (q.get("t") or [""])[0]
                path = u.path
                if path.startswith("/static/"):
                    name = os.path.basename(path)
                    fp = os.path.join(HERE, "static", name)
                    if not os.path.isfile(fp):
                        return self._send(404, "not found", "text/plain")
                    ctype = {"css": "text/css", "svg": "image/svg+xml"}.get(name.rsplit(".", 1)[-1], "application/octet-stream")
                    with open(fp, "rb") as f:
                        return self._send(200, f.read(), ctype)
                if path in ("/", "/index.html"):
                    camps, _ = self._campaigns(token)
                    return self._send(200, home_page(camps, token))
                if path.startswith("/fundraiser/"):
                    slug = path.split("/")[2]
                    camps, _ = self._campaigns(token)
                    for c in camps:
                        if c["slug"] == slug:
                            return self._send(200, campaign_page(c, token))
                    return self._send(404, layout("Not found", "<p>Fundraiser not found.</p>"))
                if path == "/about":
                    return self._send(200, about_page())
                if path == "/lab":
                    return self._send(200, lab_page(app.lab_models))
                if path == "/api/health":
                    return self._json(200, {"ok": True, "donations": app.log.count()})
                return self._send(404, layout("Not found", "<p>Page not found.</p>"))

            def do_POST(self):
                u = urlparse(self.path)
                if u.path == "/donate":
                    form = parse_qs(self._body())
                    token = (form.get("t") or [""])[0]
                    slug = (form.get("campaign") or [""])[0]
                    try:
                        amount = int(float((form.get("amount") or ["0"])[0]))
                    except ValueError:
                        amount = 0
                    donor = self.headers.get("X-Donor-Agent", "human")
                    camps, _ = self._campaigns(token)
                    c = next((x for x in camps if x["slug"] == slug), None)
                    if not c or amount <= 0:
                        return self._send(400, layout("Error", "<p>Invalid donation.</p>"))
                    app.log.add(token, slug, amount, donor)
                    return self._send(200, thanks_page(c, amount))
                if u.path == "/api/trials":
                    req = json.loads(self._body() or "{}")
                    kind = req.get("kind", "single")
                    if kind == "single":
                        spec = dict(content.CONTROL)
                        spec.update(req.get("spec") or {})
                        c = content.build_campaign(req["story"], spec)
                        token = register_trial("single", [c])
                        url = f"/fundraiser/{c['slug']}?t={token}"
                    else:
                        camps = [content.build_campaign(x["story"], {**content.CONTROL, **x["spec"]}) for x in req["cards"]]
                        token = register_trial("market", camps)
                        url = f"/?t={token}"
                    return self._json(200, {"token": token, "url": url})
                if u.path == "/api/lab/run":
                    req = json.loads(self._body() or "{}")
                    if not app.lab_runner:
                        return self._json(200, {"error": "lab runner not configured"})
                    host, port = self.server.server_address[:2]
                    try:
                        res = app.lab_runner(req["token"], req["story"], req["model"], f"http://127.0.0.1:{port}")
                        return self._json(200, res)
                    except Exception as e:  # show the problem in the page
                        return self._json(200, {"error": str(e)})
                return self._send(404, "not found", "text/plain")

        return Handler

    def serve(self, port=8000, background=False):
        httpd = ThreadingHTTPServer(("127.0.0.1", port), self.make_handler())
        if background:
            th = threading.Thread(target=httpd.serve_forever, daemon=True)
            th.start()
            return httpd
        print(f"Sahyog running at http://127.0.0.1:{port}  (lab: http://127.0.0.1:{port}/lab)  Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        return httpd
