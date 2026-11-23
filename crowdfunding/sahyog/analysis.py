"""Turn the raw decision logs into tables, statistics and an HTML report.

Pure Python standard library (no numpy/pandas needed), Python 3.9+.

Outputs (in the run folder):
  results_table.csv        the professor's table: P(fund) per scenario per model
  exp1_summary.csv         full Experiment 1 statistics
  exp1_by_story.csv        the same, split by story (robustness)
  exp2_coefficients.csv    conditional-logit estimates for Experiment 2
  exp2_position.csv        choice share by position on the page
  report.html              everything above, with charts
"""
from __future__ import annotations

import csv
import html
import json
import math
import os
from collections import defaultdict

from . import content

E = html.escape
Z95 = 1.959964


# ---------------------------------------------------------------------------
# Small statistics toolkit
# ---------------------------------------------------------------------------

def wilson(k, n, z=Z95):
    if n == 0:
        return (float("nan"),) * 3
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def norm_p(z):
    """Two-sided p-value for a standard normal z."""
    return math.erfc(abs(z) / math.sqrt(2))


def two_prop_test(k1, n1, k2, n2):
    if min(n1, n2) == 0:
        return float("nan")
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    return norm_p((k1 / n1 - k2 / n2) / se)


def mean_sd(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan"), 0
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m, sd, n


def welch_p(a, b):
    m1, s1, n1 = mean_sd(a)
    m2, s2, n2 = mean_sd(b)
    if n1 < 2 or n2 < 2:
        return float("nan")
    se = math.sqrt(s1 ** 2 / n1 + s2 ** 2 / n2)
    return 1.0 if se == 0 else norm_p((m1 - m2) / se)


def holm(pvals):
    """Holm-Bonferroni adjusted p-values (same order as input)."""
    idx = [i for i, p in enumerate(pvals) if p == p]
    order = sorted(idx, key=lambda i: pvals[i])
    m = len(order)
    adj = [float("nan")] * len(pvals)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


def stars(p):
    if p != p:
        return ""
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_jsonl(path):
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def model_order(rows):
    seen = []
    for r in rows:
        if r["model"] not in seen:
            seen.append(r["model"])
    return seen


# ---------------------------------------------------------------------------
# Experiment 1
# ---------------------------------------------------------------------------

def analyse_exp1(rows):
    scen = content.scenario_list()
    labels = {k: lab for k, lab, _ in scen}
    order = [k for k, _, _ in scen]
    models = model_order(rows)
    out = []
    by_story = []
    for m in models:
        mr = [r for r in rows if r["model"] == m and not r.get("error")]  # connection errors were retried
        valid = [r for r in mr if r.get("valid")]
        ctrl = [r for r in valid if r["scenario"] == "control"]
        kc, nc = sum(r["decision"] == "donate" for r in ctrl), len(ctrl)
        block = []
        for k in order:
            g = [r for r in valid if r["scenario"] == k]
            n_all = len([r for r in mr if r["scenario"] == k])
            if not n_all:
                continue
            kk, n = sum(r["decision"] == "donate" for r in g), len(g)
            p, lo, hi = wilson(kk, n)
            probs = [r.get("probability") for r in g]
            amts = [r.get("amount", 0) for r in g]
            pm, _, _ = mean_sd(probs)
            am, _, _ = mean_sd(amts)
            pc = kc / nc if nc else float("nan")
            pval = two_prop_test(kk, n, kc, nc) if k != "control" else float("nan")
            p_prob = welch_p(probs, [r.get("probability") for r in ctrl]) if k != "control" else float("nan")
            block.append({"model": m, "scenario": k, "label": labels[k], "n": n, "invalid": n_all - n,
                          "donations": kk, "p_fund": p, "ci_low": lo, "ci_high": hi,
                          "diff_vs_control_pp": (p - pc) * 100 if k != "control" else 0.0,
                          "p_value": pval, "mean_stated_prob": pm, "p_value_stated_prob": p_prob,
                          "mean_amount_inr": am})
            for sid in content.STORY_IDS:
                gs = [r for r in g if r["story"] == sid]
                cs = [r for r in ctrl if r["story"] == sid]
                if gs:
                    ps = sum(r["decision"] == "donate" for r in gs) / len(gs)
                    pcs = sum(r["decision"] == "donate" for r in cs) / len(cs) if cs else float("nan")
                    by_story.append({"model": m, "scenario": k, "story": sid, "n": len(gs), "p_fund": ps,
                                     "diff_vs_control_pp": (ps - pcs) * 100 if k != "control" else 0.0})
        adj = holm([b["p_value"] for b in block])
        for b, a in zip(block, adj):
            b["p_holm"] = a
        out.extend(block)
    return out, by_story, models


def professor_table(summary, models):
    """One row per scenario; for each model: P(fund) and change vs control."""
    rows = {}
    order = []
    for s in summary:
        k = s["scenario"]
        if k not in rows:
            rows[k] = {"Scenario": s["label"]}
            order.append(k)
        m = s["model"]
        rows[k][f"{m} P(fund)"] = f"{s['p_fund']:.2f}"
        rows[k][f"{m} 95% CI"] = f"{s['ci_low']:.2f}-{s['ci_high']:.2f}"
        rows[k][f"{m} change vs control (pp)"] = ("" if k == "control" else
                                                  f"{s['diff_vs_control_pp']:+.0f}{stars(s['p_holm'])}")
        rows[k][f"{m} stated probability"] = f"{s['mean_stated_prob']:.2f}" if s["mean_stated_prob"] == s["mean_stated_prob"] else ""
        rows[k][f"{m} n"] = s["n"]
    return [rows[k] for k in order]


# ---------------------------------------------------------------------------
# Experiment 2: conditional logit by Newton-Raphson
# ---------------------------------------------------------------------------

FEATURES = [
    ("pos2", "Position 2 (top right)"), ("pos3", "Position 3 (bottom left)"), ("pos4", "Position 4 (bottom right)"),
    ("sad", "Sad tone (vs neutral)"), ("hopeful", "Hopeful tone (vs neutral)"),
    ("goal_small", "Goal ₹80,000 (vs ₹3 lakh)"), ("goal_large", "Goal ₹25 lakh (vs ₹3 lakh)"),
    ("prog10", "10% raised (vs 40%)"), ("prog90", "90% raised (vs 40%)"),
    ("sup8", "8 supporters (vs 85)"), ("sup1250", "1,250 supporters (vs 85)"),
    ("urgent", "2 days left (vs 21)"), ("verified", "Verified + 80G badge"),
    ("statistical", "Statistical group (vs named person)"), ("errors", "Spelling errors"),
    ("nophoto", "No photo"), ("sponsored", "Sponsored label"), ("featured", "Featured label"),
    ("male", "Male beneficiary (vs female)"),
    ("st_education", "Story: education (vs medical)"), ("st_flood", "Story: flood relief (vs medical)"),
    ("st_livelihood", "Story: livelihood (vs medical)"),
]


def card_features(card, pos):
    s = card["spec"]
    f = {
        "pos2": pos == 1, "pos3": pos == 2, "pos4": pos == 3,
        "sad": s["emotion"] == "sad", "hopeful": s["emotion"] == "hopeful",
        "goal_small": s["goal"] == 80000, "goal_large": s["goal"] == 2500000,
        "prog10": abs(s["progress"] - 0.10) < 1e-9, "prog90": abs(s["progress"] - 0.90) < 1e-9,
        "sup8": s["supporters"] == 8, "sup1250": s["supporters"] == 1250,
        "urgent": s["days_left"] == 2, "verified": bool(s["verified"]),
        "statistical": not s["identified"], "errors": s["writing"] == "errors",
        "nophoto": not s["photo"], "sponsored": s["platform_tag"] == "sponsored",
        "featured": s["platform_tag"] == "featured", "male": s["gender"] == "male",
        "st_education": card["story"] == "education", "st_flood": card["story"] == "flood",
        "st_livelihood": card["story"] == "livelihood",
    }
    return [1.0 if f[k] else 0.0 for k, _ in FEATURES]


def solve(A, b):
    """Gaussian elimination with partial pivoting."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            raise ValueError("singular")
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c:
                fct = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= fct * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def inverse(A):
    n = len(A)
    cols = [solve(A, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def conditional_logit(sets, iters=50, ridge=1e-4):
    """sets = list of (X, chosen_index). Returns beta, se, loglik, null loglik."""
    K = len(sets[0][0][0])
    beta = [0.0] * K
    ll = 0.0
    for _ in range(iters):
        grad = [0.0] * K
        H = [[0.0] * K for _ in range(K)]
        ll = 0.0
        for X, y in sets:
            u = [sum(b * x for b, x in zip(beta, row)) for row in X]
            mx = max(u)
            e = [math.exp(v - mx) for v in u]
            s = sum(e)
            p = [v / s for v in e]
            ll += u[y] - mx - math.log(s)
            xbar = [sum(p[j] * X[j][k] for j in range(len(X))) for k in range(K)]
            for k in range(K):
                grad[k] += X[y][k] - xbar[k]
            for j in range(len(X)):
                d = [X[j][k] - xbar[k] for k in range(K)]
                for a in range(K):
                    if d[a] == 0:
                        continue
                    for c in range(K):
                        H[a][c] += p[j] * d[a] * d[c]
        for k in range(K):
            grad[k] -= ridge * beta[k]
            H[k][k] += ridge
        step = solve(H, grad)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    cov = inverse(H)
    se = [math.sqrt(max(cov[k][k], 0.0)) for k in range(K)]
    ll0 = sum(-math.log(len(X)) for X, _ in sets)
    return beta, se, ll, ll0


def analyse_exp2(rows):
    models = model_order(rows)
    coefs, positions, meta = [], [], []
    for m in models:
        mr = [r for r in rows if r["model"] == m and not r.get("error")]
        valid = [r for r in mr if r.get("valid") and r.get("choice") is not None]
        if not valid:
            continue
        sets = [([card_features(c, i) for i, c in enumerate(r["cards"])], r["choice"]) for r in valid]
        counts = [0, 0, 0, 0]
        for r in valid:
            counts[r["choice"]] += 1
        for i, c in enumerate(counts):
            p, lo, hi = wilson(c, len(valid))
            positions.append({"model": m, "position": i + 1, "chosen": c, "share": p, "ci_low": lo, "ci_high": hi})
        try:
            beta, se, ll, ll0 = conditional_logit(sets)
        except ValueError:
            meta.append({"model": m, "n": len(valid), "invalid": len(mr) - len(valid), "note": "model did not converge"})
            continue
        for (k, lab), b, s in zip(FEATURES, beta, se):
            z = b / s if s > 0 else float("nan")
            coefs.append({"model": m, "feature": k, "label": lab, "coef": b, "se": s,
                          "odds_ratio": math.exp(b), "p_value": norm_p(z) if z == z else float("nan")})
        meta.append({"model": m, "n": len(valid), "invalid": len(mr) - len(valid),
                     "pseudo_r2": 1 - ll / ll0 if ll0 else float("nan")})
    return coefs, positions, meta


# ---------------------------------------------------------------------------
# Writing files
# ---------------------------------------------------------------------------

def write_csv(path, rows):
    if not rows:
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})


def fmt(x, d=2):
    return "" if x != x else f"{x:.{d}f}"


PALETTE = ["#2457d6", "#d9622b", "#1a7f4b", "#8a3ffc", "#b42318"]


def dot_plot(summary, models):
    """P(fund) with 95% CI per scenario, one colour per model, control as a dashed line."""
    order = []
    for s in summary:
        if s["scenario"] not in order:
            order.append(s["scenario"])
    labels = {s["scenario"]: s["label"] for s in summary}
    row_h, left, width = 26, 400, 400
    H = 60 + row_h * len(order)
    X = lambda p: left + p * width
    parts = [f'<svg viewBox="0 0 {left + width + 40} {H}" class="chart" role="img" aria-label="Probability of funding by scenario">']
    for t in (0, .25, .5, .75, 1):
        parts.append(f'<line x1="{X(t)}" x2="{X(t)}" y1="30" y2="{H - 20}" stroke="#e3e6ea"/>'
                     f'<text x="{X(t)}" y="22" text-anchor="middle" font-size="11" fill="#5f6670">{t:.2f}</text>')
    for mi, m in enumerate(models):
        ctrl = next((s for s in summary if s["model"] == m and s["scenario"] == "control"), None)
        if ctrl:
            parts.append(f'<line x1="{X(ctrl["p_fund"])}" x2="{X(ctrl["p_fund"])}" y1="30" y2="{H - 20}" '
                         f'stroke="{PALETTE[mi % 5]}" stroke-dasharray="4 4" opacity=".6"/>')
    for i, k in enumerate(order):
        y = 44 + i * row_h
        parts.append(f'<text x="{left - 10}" y="{y + 4}" text-anchor="end" font-size="12" fill="#1c1f24">{E(labels[k][:64])}</text>')
        for mi, m in enumerate(models):
            s = next((x for x in summary if x["model"] == m and x["scenario"] == k), None)
            if not s or s["n"] == 0:
                continue
            dy = (mi - (len(models) - 1) / 2) * 7
            c = PALETTE[mi % 5]
            parts.append(f'<line x1="{X(s["ci_low"])}" x2="{X(s["ci_high"])}" y1="{y + dy}" y2="{y + dy}" stroke="{c}" stroke-width="1.5"/>'
                         f'<circle cx="{X(s["p_fund"])}" cy="{y + dy}" r="4" fill="{c}"><title>{E(m)}: {s["p_fund"]:.2f} (n={s["n"]})</title></circle>')
    parts.append("</svg>")
    legend = " ".join(f'<span class="key" style="--c:{PALETTE[i % 5]}">{E(m)}</span>' for i, m in enumerate(models))
    return f'<div class="legend">{legend} · dashed line = each model\'s control</div>' + "".join(parts)


def forest_plot(coefs, models):
    feats = [k for k, _ in FEATURES]
    labels = dict(FEATURES)
    row_h, left, width = 24, 300, 440
    vals = [c["coef"] + s * 1.96 * c["se"] for c in coefs for s in (-1, 1) if c["se"] == c["se"]]
    lim = min(6.0, max([abs(v) for v in vals] + [1.0]))
    X = lambda v: left + (max(-lim, min(lim, v)) + lim) / (2 * lim) * width
    H = 50 + row_h * len(feats)
    p = [f'<svg viewBox="0 0 {left + width + 40} {H}" class="chart" role="img" aria-label="Choice model coefficients">',
         f'<line x1="{X(0)}" x2="{X(0)}" y1="24" y2="{H - 14}" stroke="#5f6670"/>',
         f'<text x="{X(-lim)}" y="18" font-size="11" fill="#5f6670">less likely to be chosen</text>',
         f'<text x="{X(lim)}" y="18" font-size="11" text-anchor="end" fill="#5f6670">more likely to be chosen</text>']
    for i, k in enumerate(feats):
        y = 38 + i * row_h
        p.append(f'<text x="{left - 10}" y="{y + 4}" text-anchor="end" font-size="12" fill="#1c1f24">{E(labels[k])}</text>')
        for mi, m in enumerate(models):
            c = next((x for x in coefs if x["model"] == m and x["feature"] == k), None)
            if not c:
                continue
            dy = (mi - (len(models) - 1) / 2) * 7
            col = PALETTE[mi % 5]
            p.append(f'<line x1="{X(c["coef"] - 1.96 * c["se"])}" x2="{X(c["coef"] + 1.96 * c["se"])}" y1="{y + dy}" y2="{y + dy}" stroke="{col}" stroke-width="1.5"/>'
                     f'<circle cx="{X(c["coef"])}" cy="{y + dy}" r="4" fill="{col}"><title>{E(m)}: {c["coef"]:.2f} (SE {c["se"]:.2f})</title></circle>')
    p.append("</svg>")
    return "".join(p)


def html_table(rows, cols=None):
    if not rows:
        return "<p>No data.</p>"
    cols = cols or list(rows[0])
    head = "".join(f"<th>{E(str(c))}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{E(str(r.get(c, '')))}</td>" for c in cols) + "</tr>" for r in rows)
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def example_reasons(rows, models, per=2):
    out = []
    picks = ["control", "emotion=sad", "goal=80000", "verified=yes", "writing=errors", "identified=no"]
    for m in models:
        for k in picks:
            g = [r for r in rows if r["model"] == m and r["scenario"] == k and r.get("valid") and r.get("reason")]
            for r in g[:per]:
                out.append({"model": m, "scenario": k, "story": r["story"], "decision": r["decision"],
                            "amount": r.get("amount"), "reason": r["reason"]})
    return out


def position_check(rows):
    """Does the model prefer whichever fundraiser is shown first (A)?"""
    out = []
    for m in model_order(rows):
        g = [r for r in rows if r["model"] == m and r.get("valid") and r.get("choice") in ("A", "B")]
        if not g:
            continue
        k = sum(r["choice"] == "A" for r in g)
        p, lo, hi = wilson(k, len(g))
        out.append(f"{E(m)}: chose the first-shown fundraiser (A) in {p:.0%} of {len(g)} choices (95% CI {lo:.0%}-{hi:.0%})")
    return ("<p><strong>Position check:</strong> " + "; ".join(out) + ". Positions were balanced by design, so this "
            "bias does not distort the scenario effects.</p>") if out else ""


def build_report(run_dir):
    e1 = load_jsonl(os.path.join(run_dir, "exp1_trials.jsonl"))
    e2 = load_jsonl(os.path.join(run_dir, "exp2_trials.jsonl"))
    stub = any(r.get("backend") == "stub" for r in e1 + e2)
    sections = []
    files = []
    if e1:
        summary, by_story, models = analyse_exp1(e1)
        ptab = professor_table(summary, models)
        write_csv(os.path.join(run_dir, "exp1_summary.csv"), summary)
        write_csv(os.path.join(run_dir, "exp1_by_story.csv"), by_story)
        write_csv(os.path.join(run_dir, "results_table.csv"), ptab)
        files += ["results_table.csv", "exp1_summary.csv", "exp1_by_story.csv"]
        cols = ["model", "label", "n", "p_fund", "ci_low", "ci_high", "diff_vs_control_pp", "p_holm",
                "mean_stated_prob", "mean_amount_inr", "invalid"]
        pretty = [{**s, **{k: fmt(s[k]) for k in ("p_fund", "ci_low", "ci_high", "mean_stated_prob")},
                   "diff_vs_control_pp": "" if s["scenario"] == "control" else f"{s['diff_vs_control_pp']:+.1f}",
                   "p_holm": "" if s["scenario"] == "control" else fmt(s["p_holm"], 3) + " " + stars(s["p_holm"]),
                   "mean_amount_inr": fmt(s["mean_amount_inr"], 0)} for s in summary]
        sections.append(f"""<h2>Experiment 1 · Probability of funding under each scenario</h2>
<p>The agent opens two fundraisers and can fund only one: the target, with ONE thing changed from the control page,
and a rival story left unchanged. P(fund) = share of choices where the target won. The control row (both pages
unchanged) is the baseline; the change vs control is the effect of that one feature. Stated probability = the model's
own confidence that the target is the better choice. Stars mark changes that stay significant after Holm correction
across all scenarios (* p&lt;0.05, ** p&lt;0.01, *** p&lt;0.001).</p>
{position_check(e1)}
{dot_plot(summary, models)}
<h3>Results table</h3>{html_table(ptab)}
<h3>Full statistics</h3>{html_table(pretty, cols)}
<h3>What the models said (sample reasons)</h3>{html_table(example_reasons(e1, models))}""")
    if e2:
        coefs, positions, meta = analyse_exp2(e2)
        write_csv(os.path.join(run_dir, "exp2_coefficients.csv"), coefs)
        write_csv(os.path.join(run_dir, "exp2_position.csv"), positions)
        files += ["exp2_coefficients.csv", "exp2_position.csv"]
        models2 = [x["model"] for x in meta]
        pc = [{**c, "coef": fmt(c["coef"]), "se": fmt(c["se"]), "odds_ratio": fmt(c["odds_ratio"]),
               "p_value": fmt(c["p_value"], 3) + " " + stars(c["p_value"])} for c in coefs]
        pp = [{**p, "share": fmt(p["share"]), "ci_low": fmt(p["ci_low"]), "ci_high": fmt(p["ci_high"])} for p in positions]
        sections.append(f"""<h2>Experiment 2 · Which fundraiser does the agent pick from four?</h2>
<p>Every attribute and position was randomized independently, so each coefficient is the causal effect of that
attribute on being chosen, holding the others fixed (conditional logit; positive = more likely to be chosen).</p>
{html_table(meta)}
{forest_plot(coefs, models2)}
<h3>Coefficients</h3>{html_table(pc, ["model", "label", "coef", "se", "odds_ratio", "p_value"])}
<h3>Choice share by position (1 = top left, 2 = top right, 3 = bottom left, 4 = bottom right)</h3>{html_table(pp)}""")
    warn = ('<p class="warn">This report was built from the STUB test model. The numbers are fake and only show that '
            'the pipeline works. Run with real models before using any result.</p>' if stub else "")
    n1, n2 = len(e1), len(e2)
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>AI donor experiment report</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#1c1f24}}
h1{{margin-bottom:4px}}.meta{{color:#5f6670}}.warn{{background:#fdecea;color:#b42318;padding:10px 14px;border-radius:8px;font-weight:600}}
.tw{{overflow-x:auto}}table{{border-collapse:collapse;font-size:13px;margin:10px 0 24px}}td,th{{border-bottom:1px solid #e3e6ea;padding:5px 8px;text-align:left;vertical-align:top}}
th{{background:#f6f7f9}}.chart{{width:100%;max-width:820px;display:block;margin:10px 0}}
.legend .key{{display:inline-flex;align-items:center;gap:6px;margin-right:14px}}.legend .key::before{{content:"";width:10px;height:10px;border-radius:50%;background:var(--c)}}</style>
</head><body><h1>AI donor experiments: results</h1>
<p class="meta">Run folder: {E(os.path.abspath(run_dir))} · Experiment 1 decisions: {n1} · Experiment 2 decisions: {n2}</p>
{warn}{''.join(sections)}
<p class="meta">Files: {', '.join(files)}</p></body></html>"""
    with open(os.path.join(run_dir, "report.html"), "w") as f:
        f.write(page)
    return os.path.join(run_dir, "report.html"), files
