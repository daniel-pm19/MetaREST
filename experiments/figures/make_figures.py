"""Figuras del paper a partir de experiments/results/*.csv.

    cd experiments && uv run --no-project --python 3.12 --with matplotlib python figures/make_figures.py

Escribe figures/fig_*.png y .pdf. Solo lee CSVs: no llama al LLM ni a ninguna API.
"""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
RES = HERE.parent / "results"
C1, C2, C3 = "#4f46e5", "#94a3b8", "#f59e0b"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})


def rows(name):
    with (RES / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save(fig, name):
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(HERE / f"{name}.{ext}", dpi=200)
    plt.close(fig)
    print("->", name)


def fig_rq1():
    apis = ["pokeapi", "crossref"]
    pre = [float(rows(f"{a}_rq1.csv")[0]["valid_rate_pre"]) * 100 for a in apis]
    post = [float(rows(f"{a}_rq1.csv")[0]["valid_rate_post"]) * 100 for a in apis]
    fig, ax = plt.subplots(figsize=(4.6, 3.2))
    x = range(len(apis))
    ax.bar([i - 0.19 for i in x], pre, 0.38, label="Antes del filtro", color=C2)
    ax.bar([i + 0.19 for i in x], post, 0.38, label="Después del filtro", color=C1)
    for i, (a, b) in enumerate(zip(pre, post)):
        ax.text(i - 0.19, a + 1, f"{a:.0f}%", ha="center", fontsize=8)
        ax.text(i + 0.19, b + 1, f"{b:.0f}%", ha="center", fontsize=8)
    ax.set_xticks(list(x), ["PokeAPI", "Crossref"])
    ax.set_ylim(0, 110)
    ax.set_ylabel("MRs válidas (%)")
    ax.set_title("RQ1: validez antes y después del filtro")
    ax.legend(frameon=False, loc="lower left", fontsize=8)
    save(fig, "fig_rq1_validity")


def fig_rq2():
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2), sharey=True)
    for ax, api in zip(axes, ["pokeapi", "crossref"]):
        data = [r for r in rows(f"{api}_rq2.csv") if r["threshold"] == "0.95"]
        runs = sorted({r["run"] for r in data})
        for k, (s, color, label) in enumerate([("generated", C2, "Generadas"), ("post_diversity", C1, "Tras el filtro")]):
            vals = [float(next(r for r in data if r["run"] == run and r["set"] == s)["redundancy_rate"]) * 100 for run in runs]
            ax.bar([i + (k - 0.5) * 0.38 for i in range(len(runs))], vals, 0.38, color=color, label=label)
        ax.set_xticks(range(len(runs)), [r.split("_")[-1] for r in runs])
        ax.set_title(api.capitalize() if api == "crossref" else "PokeAPI")
    axes[0].set_ylabel("MRs redundantes (%)")
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("RQ2: redundancia con similitud ≥ 0,95", fontsize=10)
    save(fig, "fig_rq2_redundancy")


def fig_coverage():
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    labels, ops, params = [], [], []
    for api, name in [("pokeapi", "PokeAPI"), ("crossref", "Crossref")]:
        for r in rows(f"{api}_coverage.csv"):
            if r["group"] in ("metarest_selected",):
                labels.append(name)
                ops.append(float(r["ops_rate"]) * 100)
                params.append(float(r["params_rate"]) * 100)
    x = range(len(labels))
    ax.bar([i - 0.19 for i in x], ops, 0.38, color=C1, label="Operaciones")
    ax.bar([i + 0.19 for i in x], params, 0.38, color=C3, label="Parámetros")
    for i, (a, b) in enumerate(zip(ops, params)):
        ax.text(i - 0.19, a + 1, f"{a:.0f}%", ha="center", fontsize=8)
        ax.text(i + 0.19, b + 1, f"{b:.0f}%", ha="center", fontsize=8)
    ax.set_xticks(list(x), labels)
    ax.set_ylim(0, 112)
    ax.set_ylabel("Cobertura del OpenAPI (%)")
    ax.set_title("Cobertura de las MRs que pasan el filtro")
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    save(fig, "fig_coverage")


def fig_rq3():
    summary = rows("demo_manual_rq3_summary.csv")
    matrix = rows("demo_manual_rq3_fault_matrix.csv")
    techs = [c for c in matrix[0] if c != "fault"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.4, 3.6), gridspec_kw={"width_ratios": [1, 1.25]})
    names = [r["combination"] for r in summary]
    rates = [float(r["detection_rate"]) * 100 for r in summary]
    a1.barh(names, rates, color=C1)
    for i, r in enumerate(summary):
        a1.text(rates[i] + 1, i, f"{r['faults_detected']}/{r['faults_total']}", va="center", fontsize=8)
    a1.set_xlim(0, 120)
    a1.set_xlabel("Fallos detectados (%)")
    a1.set_title("RQ3: detección en la API demo")
    a1.invert_yaxis()
    faults = [r["fault"] for r in matrix]
    data = [[int(r[t]) for t in techs] for r in matrix]
    im = a2.imshow(data, cmap="Blues", aspect="auto")
    a2.set_xticks(range(len(techs)), techs)
    a2.set_yticks(range(len(faults)), faults, fontsize=8)
    for i, row in enumerate(data):
        for j, v in enumerate(row):
            a2.text(j, i, v, ha="center", va="center", color="white" if v > 2 else "black", fontsize=8)
    a2.set_title("Ítems que detectan cada fallo")
    a2.spines[:].set_visible(False)
    fig.colorbar(im, ax=a2, fraction=0.04)
    save(fig, "fig_rq3_detection")


if __name__ == "__main__":
    fig_rq1()
    fig_rq2()
    fig_coverage()
    if (RES / "demo_manual_rq3_summary.csv").exists():
        fig_rq3()
