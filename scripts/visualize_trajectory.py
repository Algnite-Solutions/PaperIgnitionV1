"""
Visualize profile pool trajectory: session assignments + GEPA vs Single F1 comparison.

Reconstructs session/milestone structure from DB (read-only, no API calls)
and generates a matplotlib figure.

Usage:
    python scripts/visualize_trajectory.py --user "Qi Zhu" --plot trajectory.png

    # Read scores from trajectory JSON output
    python scripts/visualize_trajectory.py --user "Qi Zhu" --json results/qi_zhu.json --plot trajectory.png

    # With manual F1 scores (GEPA then Single, boost #2 onward)
    python scripts/visualize_trajectory.py --user "Qi Zhu" \\
        --gepa-f1 0.333 0.333 0.452 0.519 --single-f1 0.4 0.35 0.5 0.48 --plot trajectory.png
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.profile_optimizer import build_sessions, fetch_recommendations_from_db, find_like_milestones


def build_session_assignments(
    all_sessions: list[dict],
    milestones: list[tuple[int, int]],
) -> list[dict]:
    """For each boost, compute which sessions are train vs val vs unseen."""
    boosts = []
    prev_train_indices = set()

    for step_idx, (session_cutoff, cumulative_likes) in enumerate(milestones):
        prev_cutoff = milestones[step_idx - 1][0] if step_idx > 0 else -1
        train_indices = set(range(prev_cutoff + 1, session_cutoff + 1))
        val_indices = prev_train_indices.copy()

        boosts.append({
            "boost_num": step_idx + 1,
            "cumulative_likes": cumulative_likes,
            "train_indices": train_indices,
            "val_indices": val_indices,
            "train_sessions": len(train_indices),
            "val_sessions": len(val_indices),
        })

        prev_train_indices = train_indices

    return boosts


def plot_trajectory(
    all_sessions: list[dict],
    boosts: list[dict],
    gepa_f1: list[float | None],
    single_f1: list[float | None],
    output_path: str,
):
    """Generate dual-curve trajectory visualization."""
    n_sessions = len(all_sessions)
    n_boosts = len(boosts)

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(max(14, n_sessions * 0.7), 3 + n_boosts * 0.8 + 3),
        gridspec_kw={"height_ratios": [n_boosts * 0.8, 3], "hspace": 0.35},
    )

    # Colors
    C_TRAIN = "#4C72B0"
    C_VAL = "#DD8452"
    C_UNSEEN = "#F0F0F0"
    C_GEPA = "#4C72B0"
    C_SINGLE = "#DD8452"

    # --- Top panel: session assignment heatmap ---
    data = np.zeros((n_boosts, n_sessions))
    for row, boost in enumerate(boosts):
        for i in range(n_sessions):
            if i in boost["train_indices"]:
                data[row, i] = 1
            elif i in boost["val_indices"]:
                data[row, i] = 2
            else:
                data[row, i] = 0

    from matplotlib.colors import ListedColormap
    cmap = ListedColormap([C_UNSEEN, C_TRAIN, C_VAL])

    ax_top.imshow(data, cmap=cmap, aspect="auto", vmin=0, vmax=2, interpolation="nearest")

    # Session labels on x-axis
    dates = [s["day"] for s in all_sessions]
    step = max(1, n_sessions // 12)
    ax_top.set_xticks(range(n_sessions))
    ax_top.set_xticklabels(
        [dates[i][5:] if i % step == 0 else "" for i in range(n_sessions)],
        rotation=45, ha="right", fontsize=8,
    )
    ax_top.set_xlabel("Session (day)", fontsize=10)

    # Boost labels on y-axis — show both F1 scores
    labels = []
    for i, boost in enumerate(boosts):
        g = f"G={gepa_f1[i]:.2f}" if gepa_f1[i] is not None else "G=—"
        s = f"S={single_f1[i]:.2f}" if single_f1[i] is not None else "S=—"
        labels.append(f"Boost #{boost['boost_num']} ({boost['cumulative_likes']} likes)\n{g}  {s}")
    ax_top.set_yticks(range(n_boosts))
    ax_top.set_yticklabels(labels, fontsize=9)

    # Annotate T/V
    for row, boost in enumerate(boosts):
        for col in range(n_sessions):
            val = data[row, col]
            if val == 1:
                ax_top.text(col, row, "T", ha="center", va="center",
                           fontsize=6, color="white", fontweight="bold")
            elif val == 2:
                ax_top.text(col, row, "V", ha="center", va="center",
                           fontsize=6, color="white", fontweight="bold")

    ax_top.set_title("Session Assignments per Boost  (T=Train, V=Validation)", fontsize=12, fontweight="bold")

    legend_patches = [
        mpatches.Patch(color=C_TRAIN, label="Training (new likes)"),
        mpatches.Patch(color=C_VAL, label="Validation (previous train)"),
        mpatches.Patch(color=C_UNSEEN, label="Not yet seen"),
    ]
    ax_top.legend(handles=legend_patches, loc="upper left", fontsize=8,
                  framealpha=0.9, bbox_to_anchor=(1.01, 1.0))

    ax_top.set_xticks(np.arange(-0.5, n_sessions, 1), minor=True)
    ax_top.set_yticks(np.arange(-0.5, n_boosts, 1), minor=True)
    ax_top.grid(which="minor", color="white", linewidth=0.5)

    # --- Bottom panel: dual F1 curves ---
    valid_gepa = [(i, boosts[i]["boost_num"], boosts[i]["cumulative_likes"], gepa_f1[i])
                  for i in range(n_boosts) if gepa_f1[i] is not None]
    valid_single = [(i, boosts[i]["boost_num"], boosts[i]["cumulative_likes"], single_f1[i])
                    for i in range(n_boosts) if single_f1[i] is not None]

    if valid_gepa:
        bn = [x[1] for x in valid_gepa]
        f1 = [x[3] for x in valid_gepa]
        likes = [x[2] for x in valid_gepa]
        ax_bot.plot(bn, f1, "o-", color=C_GEPA, linewidth=2.5,
                    markersize=8, markerfacecolor="white", markeredgewidth=2,
                    label="GEPA Pool")
        for b, f, _ in zip(bn, f1, likes):
            ax_bot.annotate(f"{f:.3f}", (b, f), textcoords="offset points",
                           xytext=(-15, 12), ha="center", fontsize=9,
                           fontweight="bold", color=C_GEPA)

    if valid_single:
        bn = [x[1] for x in valid_single]
        f1 = [x[3] for x in valid_single]
        ax_bot.plot(bn, f1, "s--", color=C_SINGLE, linewidth=2,
                    markersize=7, markerfacecolor="white", markeredgewidth=2,
                    label="Single Re-extract")
        for b, f in zip(bn, f1):
            ax_bot.annotate(f"{f:.3f}", (b, f), textcoords="offset points",
                           xytext=(15, 12), ha="center", fontsize=9,
                           fontweight="bold", color=C_SINGLE)

    # Delta annotations where both are available
    for i in range(n_boosts):
        if gepa_f1[i] is not None and single_f1[i] is not None:
            bn = boosts[i]["boost_num"]
            delta = gepa_f1[i] - single_f1[i]
            mid_y = (gepa_f1[i] + single_f1[i]) / 2
            color = "#2ca02c" if delta > 0 else "#d62728"
            sign = "+" if delta >= 0 else ""
            ax_bot.annotate(f"{sign}{delta:.3f}", (bn, mid_y),
                           ha="center", fontsize=8, color=color,
                           fontweight="bold", fontstyle="italic")

    ax_bot.set_xlabel("Boost #", fontsize=10)
    ax_bot.set_ylabel("Weighted F1", fontsize=10)
    ax_bot.set_title("GEPA Pool vs Single Re-extraction  (eval on train+val, time-decay)", fontsize=11, fontweight="bold")
    ax_bot.set_xticks([b["boost_num"] for b in boosts])
    all_f1 = [x for x in gepa_f1 + single_f1 if x is not None]
    ax_bot.set_ylim(0, min(1.0, max(all_f1) * 1.3) if all_f1 else 1.0)
    ax_bot.legend(fontsize=10, loc="upper left")
    ax_bot.grid(axis="y", alpha=0.3)
    ax_bot.spines["top"].set_visible(False)
    ax_bot.spines["right"].set_visible(False)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Saved trajectory plot to {output_path}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Visualize profile pool trajectory")
    parser.add_argument("--user", required=True, help="Username")
    parser.add_argument("--plot", required=True, help="Output plot path (e.g. trajectory.png)")
    parser.add_argument("--gepa-f1", nargs="+", type=float, default=None,
                        help="GEPA F1 scores (boost #2 onward)")
    parser.add_argument("--single-f1", nargs="+", type=float, default=None,
                        help="Single F1 scores (boost #2 onward)")
    parser.add_argument("--json", type=str, default=None,
                        help="Read scores from trajectory JSON output")
    parser.add_argument("--config", type=str, default=None, help="Backend config path")
    args = parser.parse_args()

    # 1. Build sessions
    print(f"Fetching sessions for {args.user}...")
    papers = fetch_recommendations_from_db(args.user, args.config)
    all_sessions, _ = build_sessions(papers)
    total_likes = sum(1 for s in all_sessions for c in s["candidates"] if c.get("label") == 1)
    print(f"  {len(all_sessions)} sessions, {total_likes} total likes")

    # 2. Find milestones
    milestones = find_like_milestones(all_sessions, step=5)
    if not milestones:
        print("No milestones found")
        sys.exit(1)
    n_boosts = len(milestones)
    print(f"  {n_boosts} boost checkpoints")

    # 3. Build session assignments
    boosts = build_session_assignments(all_sessions, milestones)
    for b in boosts:
        print(f"  Boost #{b['boost_num']}: train={b['train_sessions']} sessions, "
              f"val={b['val_sessions']} sessions, {b['cumulative_likes']} likes")

    # 4. Get F1 scores
    gepa_f1 = [None] * n_boosts
    single_f1 = [None] * n_boosts

    if args.json:
        with open(args.json) as f:
            data = json.load(f)
        for t in data.get("trajectory", []):
            idx = t["step"] - 1
            if idx < n_boosts:
                gepa_f1[idx] = t.get("gepa_f1")
                single_f1[idx] = t.get("single_f1")
    else:
        if args.gepa_f1:
            for i, score in enumerate(args.gepa_f1):
                idx = i + 1  # scores start from boost #2
                if idx < n_boosts:
                    gepa_f1[idx] = score
        if args.single_f1:
            for i, score in enumerate(args.single_f1):
                idx = i + 1
                if idx < n_boosts:
                    single_f1[idx] = score

    print(f"\n  GEPA F1:   {gepa_f1}")
    print(f"  Single F1: {single_f1}")

    # 5. Plot
    plot_trajectory(all_sessions, boosts, gepa_f1, single_f1, args.plot)


if __name__ == "__main__":
    main()
