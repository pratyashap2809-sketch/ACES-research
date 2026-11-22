# AI donors on a crowdfunding site

This project measures **how AI agents decide which crowdfunding campaigns to fund**. It extends the ACES study ("What Is Your AI Agent Buying?", arXiv 2508.02630) from shopping to donating.

It has three parts:

- **Sahyog**: a local crowdfunding website, modelled on Ketto, Milaap, GoFundMe and Kickstarter.
- **An AI donor agent**: it opens a fundraiser page, reads it, asks a locally running model (Llama 3.2 or Gemma 3, via Ollama) whether to give, and donates through the site's own form.
- **Experiments**: they change one thing on the page at a time (emotion, goal size, progress, verification badge, and so on) and fill in the results table automatically.

Everything runs on your laptop. It needs only Python 3.9 or newer, with no packages to install, plus Ollama.

## Quick start (Mac)

```bash
cd crowdfunding
bash setup_mac.sh                        # installs the models, checks speed
python3 sahyog.py serve                  # website + lab at http://127.0.0.1:8000/lab
python3 sahyog.py run --preset quick     # short trial run (both experiments + report)
python3 sahyog.py run --preset standard  # the real run
```

The results go to `results/<run name>/`:

| File | What it is |
| --- | --- |
| `results_table.csv` | The main table: P(fund) for each scenario and model, with 95% CI and the change vs control |
| `report.html` | All results with charts. Open it in a browser |
| `exp1_summary.csv` | Full Experiment 1 statistics (n, CI, p-values, Holm-corrected p, stated probability, amount) |
| `exp1_by_story.csv` | Experiment 1 split by story, to check effects hold across all four campaigns |
| `exp2_coefficients.csv` | Experiment 2 conditional-logit estimates (effect of each attribute on being chosen) |
| `exp2_position.csv` | Experiment 2 choice share by position on the page |
| `exp1_trials.jsonl`, `exp2_trials.jsonl` | Every single decision: the page text the agent read, the model's raw reply, timing |
| `donations.sqlite` | The website's own donation log (every donation the agent submitted) |
| `manifest_*.json` | Model versions (Ollama digests), settings, date |

## Commands

| Command | What it does |
| --- | --- |
| `python3 sahyog.py check` | Is Ollama running, are the models installed, how many seconds per decision, how long each preset will take |
| `python3 sahyog.py serve` | Runs the website and the lab page, where you change factors and ask a model live |
| `python3 sahyog.py demo --model llama3.2:3b --set emotion=sad goal=80000` | One decision, shown step by step (open, read, decide, act) |
| `python3 sahyog.py run --preset quick\|standard\|full` | Experiment 1 + Experiment 2 + report |
| `python3 sahyog.py exp1 ...`, `exp2 ...`, `analyze --run NAME` | Run the parts separately. Runs resume where they stopped if interrupted |
| `python3 sahyog.py notebooklm-export --scenarios control emotion=sad` | Writes prompts to paste into NotebookLM by hand |
| `python3 sahyog.py notebooklm-import FILE.csv --run NAME` | Reads NotebookLM's replies back in |

## Code layout

```
sahyog.py              command-line entry point
sahyog/content.py      the 4 stories, the 13 factors and their levels, page content builder
sahyog/site.py         the website (pages, donate form, lab, trial registry, SQLite log)
sahyog/agent.py        the donor agent: page reader, prompts, model backends, act
sahyog/experiments.py  Experiment 1 and 2 designs and runner, NotebookLM manual protocol
sahyog/analysis.py     statistics (Wilson CI, tests, Holm, conditional logit) and report
sahyog/static/         CSS and placeholder image
setup_mac.sh           one-time setup
```

## About NotebookLM

NotebookLM was renamed Gemini Notebook in July 2026. It runs in Google's cloud and cannot run locally, and Google offers no chat API for personal accounts. This project therefore uses **Gemma 3**, Google's open model, as the local Google model. NotebookLM is tested in two other ways:

1. **Manual:** `notebooklm-export` writes the exact prompts the agent would send. You paste each into a notebook, copy each reply into the CSV, and run `notebooklm-import`.
2. **Automated (experimental):** install the unofficial `notebooklm-py` CLI (`uv tool install notebooklm-py`, then `notebooklm login` and `notebooklm use <id>`), then run with `--models notebooklm`. It relies on undocumented Google APIs and is rate-limited, so keep the run small.
