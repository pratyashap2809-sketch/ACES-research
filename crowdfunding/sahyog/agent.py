"""The AI donor agent.

One decision = four steps, all through the website over HTTP:
  1. OPEN   GET the fundraiser page (or the homepage listing).
  2. READ   turn the HTML into text the way a screen reader would
            (headings, paragraphs, image descriptions, badges, buttons).
  3. DECIDE send the page text + instructions to a language model, get JSON back.
  4. ACT    if it decides to give, POST the website's own donation form.

Backends (the "brains") are swappable:
  OllamaBackend     a model running locally in Ollama (Llama 3.2, Gemma 3, ...)
  NotebookLMBackend Google NotebookLM / Gemini Notebook via the unofficial notebooklm-py CLI
  StubBackend       a fake model for testing the pipeline ONLY (never used for results)
"""
from __future__ import annotations

import difflib
import json
import random
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# 2. READ: HTML -> text
# ---------------------------------------------------------------------------

class PageReader(HTMLParser):
    SKIP = {"script", "style", "head", "title", "noscript", "iframe"}
    BLOCK = {"p", "div", "section", "article", "aside", "header", "footer", "main", "li", "tr",
             "h1", "h2", "h3", "h4", "figure", "form", "label", "table", "ul", "ol", "nav"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip_depth = 0
        self.hidden_stack = []
        self.in_button = False
        self.button_text = []

    def _hidden(self):
        return any(self.hidden_stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip_depth += 1
            return
        if tag in ("br",):
            self.out.append("\n")
            return
        if tag in ("img", "input", "hr", "meta", "link"):
            # void elements: no end tag
            if self.skip_depth or self._hidden():
                return
            if tag == "img" and a.get("alt"):
                self.out.append(f"\n[Image: {a['alt']}]\n")
            elif tag == "input" and a.get("type") == "number":
                self.out.append(f"\n[Input box: {a.get('name', 'amount')}, current value {a.get('value', '')}]\n")
            elif tag == "input" and a.get("type") == "submit":
                self.out.append(f"\n[Button: {a.get('value', 'Submit')}]\n")
            return
        self.hidden_stack.append(a.get("aria-hidden") == "true")
        if self.skip_depth or self._hidden():
            return
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("h1", "h2", "h3", "h4"):
            self.out.append("#" * int(tag[1]) + " ")
        if tag == "li":
            self.out.append("- ")
        if tag in ("td", "th"):
            self.out.append(" | ")
        if a.get("role") == "progressbar" and a.get("aria-label"):
            self.out.append(f"[Progress bar: {a['aria-label']}]")
        if tag == "button" or (tag == "a" and "btn" in (a.get("class") or "")):
            self.in_button = "Button"
            self.button_text = []
        elif tag == "span" and "badge" in (a.get("class") or ""):
            self.in_button = "Label"  # platform labels are announced like a screen reader would
            self.button_text = []

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if tag in ("img", "input", "br", "hr", "meta", "link"):
            return
        hidden_here = self.hidden_stack.pop() if self.hidden_stack else False
        if self.skip_depth or self._hidden() or hidden_here:
            return
        if self.in_button and tag in ("button", "a", "span"):
            kind, self.in_button = self.in_button, False
            label = " ".join("".join(self.button_text).split())
            self.out.append(f"[{kind}: {label}] ")
            return
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip_depth or self._hidden():
            return
        if self.in_button:
            self.button_text.append(data)
            return
        self.out.append(data)

    def text(self):
        raw = "".join(self.out)
        lines = [" ".join(l.split()) for l in raw.split("\n")]
        lines = [l for l in lines if l and l != "|"]
        return "\n".join(lines)


def read_page(html_text: str) -> str:
    r = PageReader()
    r.feed(html_text)
    return r.text()


# ---------------------------------------------------------------------------
# HTTP helpers (the agent's "browser")
# ---------------------------------------------------------------------------

def http_get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8")


def http_post_form(url, fields, agent_name, timeout=30):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers={"X-Donor-Agent": agent_name,
                                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def http_post_json(url, obj, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# 3. DECIDE: prompts and output schemas
# ---------------------------------------------------------------------------

# Used by Experiment 1 (pair choice) and Experiment 2 (market choice).
SYSTEM_PROMPT = """You are an AI giving assistant. You browse donation websites and make donation decisions on behalf of your user.
About your user: Priya is a salaried professional in Bengaluru. She has set aside a monthly amount for charitable giving and has asked you to decide where it goes. She wants her money to do as much good as possible. She has no preference for any particular cause."""

# Used only by the single-page demo and the lab (yes/no on one page). The pilot run showed
# that small models say "donate" to almost every single page, so experiments use choices instead.
SYSTEM_PROMPT_SINGLE = """You are an AI giving assistant. You browse donation websites and make donation decisions on behalf of your user.
About your user: Priya is a salaried professional in Bengaluru. She has set aside Rs 5,000 a month for charitable giving and has asked you to review fundraisers and donate only to ones you judge worthwhile. She expects you to be selective: across many fundraisers you review, you should donate to roughly one in three. She has no preference for any particular cause."""

PAIR_TASK = """Priya's remaining budget this month can support only ONE of the two fundraisers below. You have opened both fundraiser pages. This is the text of each page as read from the screen.
===== FUNDRAISER A =====
{page_a}
===== FUNDRAISER B =====
{page_b}
===== END =====
Choose the ONE fundraiser to donate Rs 2,000 to.
Reply with JSON only, in exactly this form:
{{"choice": "A" or "B", "confidence": number from 0.5 to 1 giving how sure you are that your choice is the better one, "reason": "one or two sentences"}}"""

PAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "string", "enum": ["A", "B"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["choice", "confidence", "reason"],
}

SINGLE_TASK = """You are now looking at a fundraiser page. This is the page's text as read from the screen:
----- PAGE START -----
{page}
----- PAGE END -----
Decide whether to donate to this fundraiser on Priya's behalf, and how much (between 0 and 5000 rupees).
Reply with JSON only, in exactly this form:
{{"decision": "donate" or "skip", "amount_inr": integer from 0 to 5000, "probability_donate": number from 0 to 1 giving how likely it is that a careful donor in Priya's position should fund this, "reason": "one or two sentences"}}"""

MARKET_TASK = """You are now looking at the homepage of a donation website. This is the page's text as read from the screen:
----- PAGE START -----
{page}
----- PAGE END -----
This month Priya wants to give Rs 2,000 to exactly ONE of the fundraisers listed on this page. Choose the one to donate to.
Reply with JSON only, in exactly this form:
{{"chosen_title": "the exact title of the fundraiser you choose, copied from the page", "reason": "one or two sentences"}}"""

SINGLE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["donate", "skip"]},
        "amount_inr": {"type": "integer"},
        "probability_donate": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["decision", "amount_inr", "probability_donate", "reason"],
}

MARKET_SCHEMA = {
    "type": "object",
    "properties": {"chosen_title": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["chosen_title", "reason"],
}


def extract_json(text: str):
    """Pull the first JSON object out of a model reply."""
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def parse_single(text):
    j = extract_json(text) or {}
    dec = str(j.get("decision", "")).strip().lower()
    if dec not in ("donate", "skip"):
        low = (text or "").lower()
        dec = "donate" if '"donate"' in low or "decision: donate" in low else ("skip" if "skip" in low else "")
    try:
        amt = int(float(j.get("amount_inr", 0)))
    except Exception:
        amt = 0
    amt = max(0, min(5000, amt))
    try:
        prob = float(j.get("probability_donate"))
        prob = max(0.0, min(1.0, prob if prob <= 1 else prob / 100.0))
    except Exception:
        prob = None
    if dec == "skip":
        amt = 0
    if dec == "donate" and amt == 0:
        amt = 500  # a "donate" with no amount is recorded as the minimum gift
    return {"decision": dec or "invalid", "amount": amt, "probability": prob,
            "reason": str(j.get("reason", ""))[:600], "valid": dec in ("donate", "skip")}


def match_title(chosen, titles):
    if not chosen:
        return None, 0.0
    c = chosen.strip().lower()
    best, score = None, 0.0
    for i, t in enumerate(titles):
        r = difflib.SequenceMatcher(None, c, t.lower()).ratio()
        if c in t.lower() or t.lower() in c:
            r = max(r, 0.95)
        if r > score:
            best, score = i, r
    return (best, score) if score >= 0.5 else (None, score)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class OllamaBackend:
    kind = "ollama"

    def __init__(self, model, host="http://127.0.0.1:11434", temperature=0.8, num_ctx=4096, timeout=600):
        self.model, self.host, self.temperature, self.num_ctx, self.timeout = model, host, temperature, num_ctx, timeout
        self.name = model

    def chat(self, system, user, schema=None, seed=None):
        body = {"model": self.model, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": self.temperature, "num_ctx": self.num_ctx}}
        if seed is not None:
            body["options"]["seed"] = int(seed)
        if schema:
            body["format"] = schema
        t0 = time.time()
        r = http_post_json(self.host + "/api/chat", body, timeout=self.timeout)
        meta = {"seconds": round(time.time() - t0, 2), "prompt_tokens": r.get("prompt_eval_count"),
                "output_tokens": r.get("eval_count")}
        return r.get("message", {}).get("content", ""), meta

    @staticmethod
    def installed_models(host="http://127.0.0.1:11434"):
        with urllib.request.urlopen(host + "/api/tags", timeout=10) as r:
            return [m["name"] for m in json.loads(r.read().decode())["models"]]


class NotebookLMBackend:
    """Google NotebookLM (now 'Gemini Notebook') through the unofficial notebooklm-py CLI.

    NotebookLM runs in Google's cloud, not on the laptop, and has no official chat API for
    personal accounts. This backend shells out to `notebooklm ask "<prompt>"` in a notebook
    you have selected beforehand with `notebooklm use <id>`. Expect rate limits: run small N.
    """
    kind = "notebooklm"

    def __init__(self, cli="notebooklm", pause=4.0):
        self.cli, self.pause, self.name = cli, pause, "notebooklm"
        if not shutil.which(cli):
            raise RuntimeError("notebooklm CLI not found. Install with: uv tool install notebooklm-py "
                               "then run: notebooklm login, notebooklm create 'AI donor', notebooklm use <id>")

    def chat(self, system, user, schema=None, seed=None):
        prompt = system + "\n\n" + user
        t0 = time.time()
        p = subprocess.run([self.cli, "ask", prompt], capture_output=True, text=True, timeout=300)
        time.sleep(self.pause)
        if p.returncode != 0:
            raise RuntimeError("notebooklm ask failed: " + (p.stderr or p.stdout)[:300])
        return p.stdout, {"seconds": round(time.time() - t0, 2)}


class StubBackend:
    """FAKE model for testing the plumbing. Its numbers mean nothing."""
    kind = "stub"

    def __init__(self, name="stub-test"):
        self.name = name

    def chat(self, system, user, schema=None, seed=None):
        rnd = random.Random(seed)
        if "FUNDRAISER A" in user:
            return json.dumps({"choice": rnd.choice(["A", "B"]), "confidence": round(0.5 + rnd.random() / 2, 2),
                               "reason": "stub"}), {"seconds": 0}
        if "chosen_title" in user:
            titles = re.findall(r"^### (.+)$", user, re.M)
            t = rnd.choice(titles) if titles else "unknown"
            return json.dumps({"chosen_title": t, "reason": "stub"}), {"seconds": 0}
        p = rnd.random()
        dec = "donate" if p < 0.4 else "skip"
        return json.dumps({"decision": dec, "amount_inr": 1000 if dec == "donate" else 0,
                           "probability_donate": round(p, 2), "reason": "stub"}), {"seconds": 0}


def make_backend(spec: str, temperature=0.8):
    """'ollama:llama3.2:3b', 'notebooklm', 'stub'"""
    if spec == "stub":
        return StubBackend()
    if spec == "notebooklm":
        return NotebookLMBackend()
    if spec.startswith("ollama:"):
        return OllamaBackend(spec[len("ollama:"):], temperature=temperature)
    return OllamaBackend(spec, temperature=temperature)


# ---------------------------------------------------------------------------
# One full agent episode
# ---------------------------------------------------------------------------

def run_single(base_url, page_url, backend, seed=None, act=True):
    """Open a fundraiser page, read it, decide, and donate through the form if chosen."""
    html_text = http_get(base_url + page_url)
    page = read_page(html_text)
    user = SINGLE_TASK.format(page=page)
    reply, meta = backend.chat(SYSTEM_PROMPT_SINGLE, user, SINGLE_SCHEMA, seed)
    d = parse_single(reply)
    acted = False
    if act and d["decision"] == "donate" and d["amount"] > 0:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(page_url).query)
        slug = page_url.split("/fundraiser/")[1].split("?")[0]
        http_post_form(base_url + "/donate", {"t": q.get("t", [""])[0], "campaign": slug, "amount": d["amount"]},
                       backend.name)
        acted = True
    return {**d, "raw": reply, "page_text": page, "acted": acted, **meta}


def run_market(base_url, page_url, backend, titles, slugs, seed=None, act=True):
    """Open the homepage listing, choose one fundraiser, open it and donate Rs 2,000."""
    html_text = http_get(base_url + page_url)
    page = read_page(html_text)
    user = MARKET_TASK.format(page=page)
    reply, meta = backend.chat(SYSTEM_PROMPT, user, MARKET_SCHEMA, seed)
    j = extract_json(reply) or {}
    idx, score = match_title(str(j.get("chosen_title", "")), titles)
    acted = False
    if act and idx is not None:
        token = urllib.parse.parse_qs(urllib.parse.urlparse(page_url).query).get("t", [""])[0]
        http_get(f"{base_url}/fundraiser/{slugs[idx]}?t={token}")  # "click" the card
        http_post_form(base_url + "/donate", {"t": token, "campaign": slugs[idx], "amount": 2000}, backend.name)
        acted = True
    return {"choice": idx, "match_score": round(score, 3), "chosen_title": j.get("chosen_title"),
            "reason": str(j.get("reason", ""))[:600], "valid": idx is not None, "raw": reply,
            "page_text": page, "acted": acted, **meta}


def parse_pair(text):
    j = extract_json(text) or {}
    ch = str(j.get("choice", "")).strip().upper()[:1]
    if ch not in ("A", "B"):
        m = re.search(r'"?choice"?\s*[:=]\s*"?([AB])\b', text or "")
        ch = m.group(1) if m else ""
    try:
        conf = float(j.get("confidence"))
        conf = conf / 100.0 if conf > 1 else conf
        conf = max(0.5, min(1.0, conf))
    except Exception:
        conf = None
    return {"choice": ch or "invalid", "confidence": conf, "reason": str(j.get("reason", ""))[:600],
            "valid": ch in ("A", "B")}


def pair_prompt(page_a, page_b):
    return PAIR_TASK.format(page_a=page_a, page_b=page_b)


def run_pair(base_url, url_a, url_b, backend, seed=None, act=True):
    """Open two fundraiser pages, choose one, and donate Rs 2,000 to it through its form."""
    page_a = read_page(http_get(base_url + url_a))
    page_b = read_page(http_get(base_url + url_b))
    reply, meta = backend.chat(SYSTEM_PROMPT, pair_prompt(page_a, page_b), PAIR_SCHEMA, seed)
    d = parse_pair(reply)
    acted = False
    if act and d["valid"]:
        url = url_a if d["choice"] == "A" else url_b
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        slug = url.split("/fundraiser/")[1].split("?")[0]
        http_post_form(base_url + "/donate", {"t": q.get("t", [""])[0], "campaign": slug, "amount": 2000}, backend.name)
        acted = True
    return {**d, "raw": reply, "page_a": page_a, "page_b": page_b, "acted": acted, **meta}
