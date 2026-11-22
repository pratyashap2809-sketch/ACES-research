"""Experiment designs and the runner.

Experiment 1 (scenario table, "A/B tests"):
    The agent sees ONE fundraiser page and decides donate/skip + amount + a stated probability.
    Each scenario changes ONE factor from the control page. Every scenario is run on all four
    stories, several repetitions each, so a result is never tied to one particular story.

Experiment 2 (marketplace choice, like ACES):
    The agent sees the homepage with four fundraiser cards and picks ONE to give Rs 2,000 to.
    Card positions and attributes are randomized independently on every trial, so a conditional
    logit model recovers the causal effect of each attribute (and of position) on being chosen.

All raw results go to JSON Lines files (one line per decision) so runs can be resumed,
audited and re-analysed.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time

from . import agent, content, site

PRESETS = {
    #            reps per scenario x story, control reps per story, market trials
    "quick":    {"reps": 1, "control_reps": 3, "market_trials": 20},
    "standard": {"reps": 5, "control_reps": 15, "market_trials": 100},
    "full":     {"reps": 10, "control_reps": 30, "market_trials": 300},
}


def stable_seed(*parts):
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16)


def _done_keys(path, key_fields):
    done = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("error"):
                        continue  # failed trials are retried on the next run
                    done.add(tuple(r[k] for k in key_fields))
                except Exception:
                    pass
    return done


class Progress:
    def __init__(self, total, label):
        self.total, self.label, self.n, self.t0 = total, label, 0, time.time()

    def step(self, extra=""):
        self.n += 1
        el = time.time() - self.t0
        eta = el / self.n * (self.total - self.n)
        print(f"\r[{self.label}] {self.n}/{self.total}  elapsed {el/60:5.1f} min  ETA {eta/60:5.1f} min  {extra[:60]:<60}",
              end="", flush=True)

    def done(self):
        print()


def start_site(db_path, port=0):
    app = site.App(db_path)
    httpd = app.serve(port=port, background=True)
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


# ---------------------------------------------------------------------------
# Experiment 1
# ---------------------------------------------------------------------------

def exp1_plan(reps, control_reps, stories):
    plan = []
    for key, label, spec in content.scenario_list():
        n = control_reps if key == "control" else reps
        for sid in stories:
            for r in range(n):
                plan.append((key, label, spec, sid, r))
    return plan


def run_exp1(models, out_dir, reps, control_reps, stories=None, temperature=0.8, base_url=None, act=True):
    stories = stories or content.STORY_IDS
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "exp1_trials.jsonl")
    httpd = None
    if not base_url:
        httpd, base_url = start_site(os.path.join(out_dir, "donations.sqlite"))
    keys = ("model", "scenario", "story", "rep")
    done = _done_keys(path, keys)
    plan = exp1_plan(reps, control_reps, stories)
    for model in models:
        backend = agent.make_backend(model, temperature)
        todo = [p for p in plan if (backend.name, p[0], p[3], p[4]) not in done]
        random.Random(stable_seed("order", model)).shuffle(todo)  # interleave conditions over time
        prog = Progress(len(todo), f"Exp1 {backend.name}")
        streak = 0
        with open(path, "a") as f:
            for key, label, spec, sid, r in todo:
                seed = stable_seed("exp1", backend.name, key, sid, r)
                reg = agent.http_post_json(base_url + "/api/trials", {"kind": "single", "story": sid, "spec": spec})
                try:
                    res = agent.run_single(base_url, reg["url"], backend, seed=seed, act=act)
                    err = None
                except Exception as e:
                    res, err = {"decision": "error", "valid": False}, str(e)[:300]
                factor = key.split("=")[0] if "=" in key else "control"
                row = {"exp": 1, "model": backend.name, "backend": backend.kind, "scenario": key, "label": label,
                       "factor": factor, "story": sid, "rep": r, "seed": seed, "temperature": temperature,
                       "spec": spec, "ts": time.time(), "error": err, **res}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                prog.step(f"{key} · {sid} · {res.get('decision')}")
                streak = streak + 1 if err else 0
                if streak >= 3:
                    raise SystemExit(f"\nStopped: 3 errors in a row ({err}). Is Ollama running and is {backend.name} installed? "
                                     "Fix it and run the same command again; it resumes where it stopped.")
        prog.done()
    if httpd:
        httpd.shutdown()
    return path


# ---------------------------------------------------------------------------
# Experiment 2
# ---------------------------------------------------------------------------

def random_card_spec(rnd):
    s = dict(content.CONTROL)
    s["emotion"] = rnd.choice(["neutral", "sad", "hopeful"])
    s["goal"] = rnd.choice([80000, 300000, 2500000])
    s["progress"] = rnd.choice([0.10, 0.40, 0.90])
    s["supporters"] = rnd.choice([8, 85, 1250])
    s["days_left"] = rnd.choice([2, 21])
    s["verified"] = rnd.random() < 0.5
    s["identified"] = rnd.random() < 0.5
    s["writing"] = "errors" if rnd.random() < 0.5 else "clean"
    s["photo"] = rnd.random() < 0.5
    s["gender"] = rnd.choice(["female", "male"])
    return s


def market_trial(rnd):
    order = content.STORY_IDS[:]
    rnd.shuffle(order)  # position of each story on the page
    cards = [{"story": sid, "spec": random_card_spec(rnd)} for sid in order]
    if rnd.random() < 0.5:
        rnd.choice(cards)["spec"]["platform_tag"] = "sponsored"
    if rnd.random() < 0.5:
        free = [c for c in cards if c["spec"]["platform_tag"] == "none"]
        rnd.choice(free)["spec"]["platform_tag"] = "featured"
    return cards


def run_exp2(models, out_dir, trials, temperature=0.8, base_url=None, act=True):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "exp2_trials.jsonl")
    httpd = None
    if not base_url:
        httpd, base_url = start_site(os.path.join(out_dir, "donations.sqlite"))
    done = _done_keys(path, ("model", "trial"))
    for model in models:
        backend = agent.make_backend(model, temperature)
        todo = [t for t in range(trials) if (backend.name, t) not in done]
        prog = Progress(len(todo), f"Exp2 {backend.name}")
        streak = 0
        with open(path, "a") as f:
            for t in todo:
                rnd = random.Random(stable_seed("exp2-design", t))  # same pages for every model
                cards = market_trial(rnd)
                reg = agent.http_post_json(base_url + "/api/trials", {"kind": "market", "cards": cards})
                built = [content.build_campaign(c["story"], {**content.CONTROL, **c["spec"]}) for c in cards]
                titles = [b["title"] for b in built]
                slugs = [b["slug"] for b in built]
                seed = stable_seed("exp2", backend.name, t)
                try:
                    res = agent.run_market(base_url, reg["url"], backend, titles, slugs, seed=seed, act=act)
                    err = None
                except Exception as e:
                    res, err = {"choice": None, "valid": False}, str(e)[:300]
                row = {"exp": 2, "model": backend.name, "backend": backend.kind, "trial": t, "seed": seed,
                       "temperature": temperature, "cards": cards, "titles": titles, "ts": time.time(),
                       "error": err, **res}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                prog.step(f"trial {t} · chose {res.get('choice')}")
                streak = streak + 1 if err else 0
                if streak >= 3:
                    raise SystemExit(f"\nStopped: 3 errors in a row ({err}). Is Ollama running and is {backend.name} installed? "
                                     "Fix it and run the same command again; it resumes where it stopped.")
        prog.done()
    if httpd:
        httpd.shutdown()
    return path


# ---------------------------------------------------------------------------
# Manual NotebookLM protocol (works without any unofficial tools)
# ---------------------------------------------------------------------------

def notebooklm_export(out_dir, scenarios=None, reps=1):
    """Write the exact prompts the agent would send, for pasting into NotebookLM by hand."""
    import csv
    os.makedirs(out_dir, exist_ok=True)
    httpd, base = start_site(os.path.join(out_dir, "donations.sqlite"))
    keep = set(scenarios) if scenarios else None
    rows = []
    for key, label, spec, sid, r in exp1_plan(reps, reps, content.STORY_IDS):
        if keep and key not in keep:
            continue
        reg = agent.http_post_json(base + "/api/trials", {"kind": "single", "story": sid, "spec": spec})
        page = agent.read_page(agent.http_get(base + reg["url"]))
        prompt = agent.SYSTEM_PROMPT + "\n\n" + agent.SINGLE_TASK.format(page=page)
        rows.append({"id": f"{key}|{sid}|{r}", "scenario": key, "label": label, "story": sid, "rep": r,
                     "prompt": prompt, "notebooklm_reply": ""})
    httpd.shutdown()
    path = os.path.join(out_dir, "notebooklm_prompts.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path, len(rows)


def notebooklm_import(csv_path, out_dir):
    """Read the filled-in CSV (column notebooklm_reply) and append decisions to exp1_trials.jsonl."""
    import csv
    path = os.path.join(out_dir, "exp1_trials.jsonl")
    scen = {k: (lab, spec) for k, lab, spec in content.scenario_list()}
    n = 0
    with open(csv_path, newline="") as f, open(path, "a") as out:
        for row in csv.DictReader(f):
            if not row.get("notebooklm_reply", "").strip():
                continue
            d = agent.parse_single(row["notebooklm_reply"])
            key = row["scenario"]
            out.write(json.dumps({"exp": 1, "model": "notebooklm", "backend": "notebooklm-manual",
                                  "scenario": key, "label": scen[key][0],
                                  "factor": key.split("=")[0] if "=" in key else "control",
                                  "story": row["story"], "rep": int(row["rep"]), "spec": scen[key][1],
                                  "ts": time.time(), "error": None, **d, "raw": row["notebooklm_reply"]},
                                 ensure_ascii=False) + "\n")
            n += 1
    return n
