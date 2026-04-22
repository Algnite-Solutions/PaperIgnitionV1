"""CustomIgnition vs Single Re-extraction — F1 resilience visualization.

X-axis: boost number (cumulative likes growing over time)
Y-axis: F1 score
- CustomIgnition active F1: line + star markers
- Single re-extraction F1: line + triangle markers
- Pool candidate F1 spread: faded dots at each boost (shows diversity)
- Shaded delta region between the two lines
"""

import re
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


def parse_log(log_path: str) -> dict:
    """Parse trajectory log, extract per-boost pool candidates + Single baseline."""
    text = Path(log_path).read_text()
    boost_sections = re.split(r"(?=======\s+Boost #)", text)

    boosts = []
    for section in boost_sections:
        if not re.match(r"======\s+Boost #", section):
            continue

        m_header = re.search(r"Boost #(\d+) — (\d+) cumulative likes", section)
        if not m_header:
            continue

        m_gepa = re.search(r"GEPA eval: P=([\d.]+) R=([\d.]+) F1=([\d.]+)", section)
        m_single = re.search(r"Single eval: P=([\d.]+) R=([\d.]+) F1=([\d.]+)", section)

        candidates = []
        for cm in re.finditer(
            r"\[INFO\] 📊 Candidate \(gen (\d+)\): P=([\d.]+) R=([\d.]+) F1=([\d.]+)",
            section,
        ):
            candidates.append({
                "gen": int(cm.group(1)),
                "precision": float(cm.group(2)),
                "recall": float(cm.group(3)),
                "f1": float(cm.group(4)),
            })

        active = None
        if m_gepa:
            target_f1 = float(m_gepa.group(3))
            for c in reversed(candidates):
                if abs(c["f1"] - target_f1) < 0.002:
                    active = c
                    break

        boosts.append({
            "boost": int(m_header.group(1)),
            "cum_likes": int(m_header.group(2)),
            "gepa_f1": float(m_gepa.group(3)) if m_gepa else None,
            "single_f1": float(m_single.group(3)) if m_single else None,
            "candidates": candidates,
            "active": active,
        })

    return {"boosts": boosts}


def main():
    users = [
        ("User A", "scripts/trajectory_full_qizhu_2.log", "#2563eb", "#93c5fd"),
        ("User B", "scripts/trajectory_full_rongcan_2.log", "#dc2626", "#fca5a5"),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for (user_name, log_path, ci_color, single_color), ax in zip(users, axes):
        data = parse_log(log_path)
        boosts = data["boosts"]

        x_ci, y_ci = [], []
        x_s, y_s = [], []

        for b in boosts:
            bx = b["boost"]

            # CustomIgnition active
            if b["gepa_f1"] is not None and b["gepa_f1"] > 0:
                x_ci.append(bx)
                y_ci.append(b["gepa_f1"])

            # Single
            if b["single_f1"] is not None and b["single_f1"] > 0:
                x_s.append(bx)
                y_s.append(b["single_f1"])

            # Pool candidate dots (jittered horizontally for visibility)
            if b["candidates"]:
                valid_cands = [c for c in b["candidates"] if c["f1"] > 0]
                if valid_cands:
                    n_c = len(valid_cands)
                    jitter = np.random.default_rng(seed=bx).uniform(-0.15, 0.15, n_c)
                    f1_vals = [c["f1"] for c in valid_cands]
                    ax.scatter(
                        bx + jitter, f1_vals,
                        s=25, color=ci_color, alpha=0.25,
                        edgecolors="none", zorder=1,
                    )

        # Shaded delta region
        if x_ci and x_s:
            # Align on common boost numbers
            common = sorted(set(x_ci) & set(x_s))
            ci_dict = dict(zip(x_ci, y_ci))
            s_dict = dict(zip(x_s, y_s))
            cx = [c for c in common if ci_dict[c] is not None and s_dict[c] is not None]
            cy_ci = [ci_dict[c] for c in cx]
            cy_s = [s_dict[c] for c in cx]
            if cx:
                ax.fill_between(
                    cx, cy_ci, cy_s,
                    alpha=0.12, color=ci_color, zorder=0,
                    label=f"Δ F1 = +{np.mean([a - b_ for a, b_ in zip(cy_ci, cy_s)]):.3f}",
                )

        # CustomIgnition line
        if x_ci:
            ax.plot(x_ci, y_ci, "-o", color=ci_color, linewidth=2.5, markersize=10,
                    markerfacecolor="white", markeredgewidth=2, markeredgecolor=ci_color,
                    zorder=4, label="CustomIgnition")
            # Annotate values
            for xi, yi in zip(x_ci, y_ci):
                ax.annotate(f"{yi:.2f}", (xi, yi), textcoords="offset points",
                            xytext=(0, 12), fontsize=8, ha="center", color=ci_color,
                            fontweight="bold")

        # Single line
        if x_s:
            ax.plot(x_s, y_s, "--^", color=single_color, linewidth=2, markersize=8,
                    markerfacecolor="white", markeredgewidth=1.5, markeredgecolor=single_color,
                    zorder=3, label="Single re-extraction")
            for xi, yi in zip(x_s, y_s):
                ax.annotate(f"{yi:.2f}", (xi, yi), textcoords="offset points",
                            xytext=(0, -16), fontsize=7, ha="center", color=single_color)

        # X-axis: boost labels + cumulative likes
        all_boosts = sorted(set(x_ci + x_s))
        boost_labels = []
        for b_num in all_boosts:
            b_data = next((b for b in boosts if b["boost"] == b_num), None)
            likes = b_data["cum_likes"] if b_data else b_num * 5
            boost_labels.append(f"#{b_num}\n({likes} likes)")

        ax.set_xticks(all_boosts)
        ax.set_xticklabels(boost_labels, fontsize=8)
        ax.set_ylabel("F1 Score", fontsize=12)
        ax.set_xlabel("Boost (cumulative likes)", fontsize=11)
        ax.set_title(f"{user_name}", fontsize=14, fontweight="bold")
        ax.set_ylim(0, 1.1)
        ax.yaxis.set_major_locator(mticker.MultipleLocator(0.2))
        ax.grid(True, axis="y", alpha=0.2)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.9)

        # Stats
        ci_avg = np.mean(y_ci) if y_ci else 0
        s_avg = np.mean(y_s) if y_s else 0
        ax.text(
            0.02, 0.02,
            f"Pool evals: {sum(len(b['candidates']) for b in boosts)}\n"
            f"CustomIgnition avg: {ci_avg:.3f}\n"
            f"Single avg: {s_avg:.3f}",
            transform=ax.transAxes, fontsize=7,
            va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor="gray", alpha=0.6),
        )

    fig.suptitle("CustomIgnition vs Single Re-extraction — F1 Resilience Across Boosts",
                 fontsize=15, fontweight="bold", y=1.02)
    plt.tight_layout()
    out_path = "scripts/customignition_f1_resilience.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
