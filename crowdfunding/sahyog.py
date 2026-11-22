#!/usr/bin/env python3
"""Sahyog AI-donor lab: one command for everything.

  python3 sahyog.py check                         is Ollama running, which models are installed, how fast?
  python3 sahyog.py serve                         open the website + lab at http://127.0.0.1:8000
  python3 sahyog.py demo --model llama3.2:3b      one decision, printed step by step
  python3 sahyog.py run --preset standard         Experiment 1 + 2 for both models, then the report
  python3 sahyog.py exp1 | exp2 | analyze         run parts separately
  python3 sahyog.py notebooklm-export / notebooklm-import   (or --models notebooklm with the CLI)

Only Python 3.9+ standard library is needed. Models run in Ollama (https://ollama.com).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sahyog import agent, analysis, content, experiments, site  # noqa: E402

DEFAULT_MODELS = ["llama3.2:3b", "gemma3:4b"]
HERE = os.path.dirname(os.path.abspath(__file__))


def new_run_dir(name=None):
    name = name or time.strftime("run_%Y%m%d_%H%M")
    path = os.path.join(HERE, "results", name)
    os.makedirs(path, exist_ok=True)
    return path


def write_manifest(run_dir, args, models):
    info = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "models": models, "args": {k: v for k, v in vars(args).items() if not callable(v)},
            "python": sys.version.split()[0]}
    try:
        tags = json.loads(agent.http_get("http://127.0.0.1:11434/api/tags"))
        info["ollama_models"] = {m["name"]: {"digest": m.get("digest"), "size": m.get("size"),
                                             "details": m.get("details")} for m in tags.get("models", [])}
        info["ollama_version"] = json.loads(agent.http_get("http://127.0.0.1:11434/api/version")).get("version")
    except Exception:
        pass
    with open(os.path.join(run_dir, f"manifest_{args.cmd}.json"), "w") as f:
        json.dump(info, f, indent=2)


def cmd_check(args):
    print("1) Is Ollama running?")
    try:
        models = agent.OllamaBackend.installed_models()
        print("   yes. Installed models:", ", ".join(models) or "(none)")
    except Exception as e:
        print("   NO. Start the Ollama app (or run `ollama serve`) and try again.\n  ", e)
        return 1
    want = args.models or DEFAULT_MODELS
    missing = [m for m in want if not any(x == m or x.startswith(m + ":") or x == m + ":latest" for x in models)]
    if missing:
        print("2) Missing models. Download them with:")
        for m in missing:
            print(f"     ollama pull {m}")
        return 1
    print("2) All needed models are installed:", ", ".join(want))
    print("3) Timing one real decision per model (first call also loads the model)...")
    httpd, base = experiments.start_site(os.path.join(HERE, "results", "_check.sqlite"))
    times = {}
    for m in want:
        b = agent.OllamaBackend(m)
        reg = agent.http_post_json(base + "/api/trials", {"kind": "single", "story": "heart", "spec": content.CONTROL})
        agent.run_single(base, reg["url"], b, seed=1, act=False)  # warm-up
        t0 = time.time()
        r = agent.run_single(base, reg["url"], b, seed=2, act=False)
        times[m] = time.time() - t0
        print(f"   {m}: {times[m]:.1f} s per decision -> {r['decision']} ({r['reason'][:80]})")
    httpd.shutdown()
    print("4) Estimated time for `run` (both experiments, all models):")
    n_scen = len(content.scenario_list()) - 1
    for name, p in experiments.PRESETS.items():
        calls1 = (n_scen * p["reps"] + p["control_reps"]) * len(content.STORY_IDS)
        total = sum(t * calls1 + t * 1.6 * p["market_trials"] for t in times.values())
        print(f"   {name:9s} {calls1} + {p['market_trials']} decisions per model  ~ {total / 60:.0f} min")
    return 0


def lab_runner(token, story, model, base):
    b = agent.OllamaBackend(model)
    t0 = time.time()
    try:
        r = agent.run_single(base, f"/fundraiser/{story}?t={token}", b, act=True)
    except OSError as e:
        raise RuntimeError(f"Cannot reach Ollama at 127.0.0.1:11434 ({e}). Open the Ollama app, check that "
                           f"`ollama pull {model}` has been done, and try again.")
    return {"decision": r["decision"], "amount": r["amount"], "probability": r["probability"],
            "reason": r["reason"], "model": model, "seconds": round(time.time() - t0, 1)}


def cmd_serve(args):
    models = args.models
    if not models:
        try:
            models = agent.OllamaBackend.installed_models()
        except Exception:
            models = DEFAULT_MODELS
    app = site.App(os.path.join(HERE, "results", "website_donations.sqlite"), models, lab_runner)
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{args.port}/lab")
    app.serve(args.port)


def cmd_demo(args):
    httpd, base = experiments.start_site(os.path.join(HERE, "results", "_demo.sqlite"))
    spec = dict(content.CONTROL)
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        try:
            spec[k] = json.loads(v)  # numbers, true/false
        except ValueError:
            spec[k] = v  # words such as sad, errors, sponsored
    reg = agent.http_post_json(base + "/api/trials", {"kind": "single", "story": args.story, "spec": spec})
    print("STEP 1  OPEN  ", base + reg["url"])
    page = agent.read_page(agent.http_get(base + reg["url"]))
    print("STEP 2  READ   the page as text:\n" + "-" * 60 + "\n" + page + "\n" + "-" * 60)
    b = agent.make_backend(args.model)
    print(f"STEP 3  DECIDE asking {b.name} ...")
    r = agent.run_single(base, reg["url"], b, seed=args.seed, act=True)
    print("        raw reply:", r["raw"])
    print(f"STEP 4  ACT    decision={r['decision']} amount=₹{r['amount']} stated probability={r['probability']}"
          f" donated_through_form={r['acted']}  ({r.get('seconds')} s)")
    httpd.shutdown()


def models_from(args):
    ms = args.models or DEFAULT_MODELS
    return [m if m in ("stub", "notebooklm") else m for m in ms]


def cmd_exp1(args):
    run_dir = new_run_dir(args.run)
    p = experiments.PRESETS[args.preset]
    reps = args.reps or p["reps"]
    creps = args.control_reps or p["control_reps"]
    write_manifest(run_dir, args, models_from(args))
    print(f"Experiment 1 -> {run_dir}  (reps {reps}, control reps {creps})")
    experiments.run_exp1(models_from(args), run_dir, reps, creps, temperature=args.temperature)
    return run_dir


def cmd_exp2(args):
    run_dir = new_run_dir(args.run)
    trials = args.trials or experiments.PRESETS[args.preset]["market_trials"]
    write_manifest(run_dir, args, models_from(args))
    print(f"Experiment 2 -> {run_dir}  ({trials} trials per model)")
    experiments.run_exp2(models_from(args), run_dir, trials, temperature=args.temperature)
    return run_dir


def cmd_analyze(args):
    run_dir = os.path.join(HERE, "results", args.run) if not os.path.isdir(args.run) else args.run
    path, files = analysis.build_report(run_dir)
    print("Report:", path)
    print("Tables:", ", ".join(files))
    if not args.no_browser:
        webbrowser.open("file://" + os.path.abspath(path))


def cmd_run(args):
    args.run = args.run or time.strftime("run_%Y%m%d_%H%M")
    run_dir = cmd_exp1(args)
    cmd_exp2(args)
    args.run = run_dir
    cmd_analyze(args)


def cmd_nlm_export(args):
    run_dir = new_run_dir(args.run)
    path, n = experiments.notebooklm_export(run_dir, args.scenarios, args.reps)
    print(f"Wrote {n} prompts to {path}")
    print("Paste each prompt into NotebookLM, copy its reply into the notebooklm_reply column, save the CSV, then run:")
    print(f"  python3 sahyog.py notebooklm-import {path} --run {os.path.basename(run_dir)}")


def cmd_nlm_import(args):
    run_dir = new_run_dir(args.run)
    n = experiments.notebooklm_import(args.csv, run_dir)
    print(f"Imported {n} NotebookLM decisions into {run_dir}/exp1_trials.jsonl. Now run: "
          f"python3 sahyog.py analyze --run {os.path.basename(run_dir)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--models", nargs="+", help="e.g. llama3.2:3b gemma3:4b (default), or notebooklm, or stub")
        p.add_argument("--run", help="run folder name under results/ (default: run_<date>_<time>)")
        p.add_argument("--preset", default="standard", choices=list(experiments.PRESETS))
        p.add_argument("--temperature", type=float, default=0.8)
        p.add_argument("--no-browser", action="store_true")

    p = sub.add_parser("check"); p.add_argument("--models", nargs="+"); p.set_defaults(f=cmd_check)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8000); p.add_argument("--models", nargs="+")
    p.add_argument("--no-browser", action="store_true"); p.set_defaults(f=cmd_serve)
    p = sub.add_parser("demo"); p.add_argument("--model", default="llama3.2:3b"); p.add_argument("--story", default="heart", choices=content.STORY_IDS)
    p.add_argument("--set", nargs="*", help='factor=level, e.g. emotion=sad goal=80000 verified=true'); p.add_argument("--seed", type=int, default=7)
    p.set_defaults(f=cmd_demo)
    p = sub.add_parser("exp1"); common(p); p.add_argument("--reps", type=int); p.add_argument("--control-reps", type=int); p.set_defaults(f=cmd_exp1)
    p = sub.add_parser("exp2"); common(p); p.add_argument("--trials", type=int); p.set_defaults(f=cmd_exp2)
    p = sub.add_parser("run"); common(p); p.add_argument("--reps", type=int); p.add_argument("--control-reps", type=int)
    p.add_argument("--trials", type=int); p.set_defaults(f=cmd_run)
    p = sub.add_parser("analyze"); p.add_argument("--run", required=True); p.add_argument("--no-browser", action="store_true"); p.set_defaults(f=cmd_analyze)
    p = sub.add_parser("notebooklm-export"); p.add_argument("--run"); p.add_argument("--reps", type=int, default=1)
    p.add_argument("--scenarios", nargs="*", help="scenario keys to include (default: all)"); p.set_defaults(f=cmd_nlm_export)
    p = sub.add_parser("notebooklm-import"); p.add_argument("csv"); p.add_argument("--run", required=True); p.set_defaults(f=cmd_nlm_import)
    a = ap.parse_args()
    return a.f(a) or 0


if __name__ == "__main__":
    rc = main()
    sys.exit(rc if isinstance(rc, int) else 0)
