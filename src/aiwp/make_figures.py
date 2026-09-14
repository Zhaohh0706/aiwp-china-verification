"""Three figures, each answering one question.

Which model is best, and by how much; how much of each model's error is a
constant that a single correction would remove; and where the errors sit by
station. Nothing decorative.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .fetch import MODEL_LABEL
from .run_verification import CORE_MODELS, REPORTS, load, sets
from . import verify

plt.rcParams.update(
    {
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "font.size": 9,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
    }
)

FIGURES = REPORTS / "figures"
HIGHLIGHT = "#b91c1c"  # CMA GRAPES, the model this study exists to place
BEST = "#047857"  # whichever model wins
OTHER = "#94a3b8"


def _colour(model: str, best: str) -> str:
    if model == "cma_grapes_global":
        return HIGHLIGHT
    if model == best:
        return BEST
    return OTHER


def figure_lead_growth(china: pd.DataFrame) -> None:
    growth = verify.error_growth(china)
    best = (
        growth[growth["lead_days"] == 1].sort_values("rmse_c")["model"].iloc[0]
    )

    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    for model, group in growth.groupby("model"):
        group = group.sort_values("lead_days")
        colour = _colour(model, best)
        ax.plot(
            group["lead_days"],
            group["rmse_c"],
            marker="o",
            markersize=3.5,
            linewidth=1.8 if colour != OTHER else 1.1,
            color=colour,
            label=MODEL_LABEL.get(model, model),
            zorder=3 if colour != OTHER else 2,
        )
        ax.annotate(
            MODEL_LABEL.get(model, model),
            (group["lead_days"].iloc[-1], group["rmse_c"].iloc[-1]),
            textcoords="offset points",
            xytext=(5, -2),
            fontsize=7,
            color=colour,
        )
    ax.set_xlabel("Lead time (days)")
    ax.set_ylabel("RMSE of daily maximum (°C)")
    ax.set_xticks(sorted(growth["lead_days"].unique()))
    ax.set_xlim(0.8, 6.4)
    ax.set_title(
        "Daily maximum temperature at nine Chinese airport stations, 2024-07 to 2025-08",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "lead_growth.png", bbox_inches="tight")
    plt.close(fig)


def figure_bias_vs_skill(china: pd.DataFrame) -> None:
    """How much of each model's error is a constant offset."""
    board = verify.scorecard(china[china["lead_days"] == 1])
    board["bias_share"] = 100.0 * board["bias_c"] ** 2 / board["rmse_c"] ** 2
    best = board.sort_values("rmse_c")["model"].iloc[0]

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))

    order = board.sort_values("rmse_c")
    y = np.arange(len(order))
    colours = [_colour(m, best) for m in order["model"]]
    axes[0].barh(y, order["debiased_rmse_c"], color=colours, label="error left after debiasing")
    axes[0].barh(
        y,
        order["rmse_c"] - order["debiased_rmse_c"],
        left=order["debiased_rmse_c"],
        color=colours,
        alpha=0.35,
        label="the part a constant would remove",
    )
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([MODEL_LABEL.get(m, m) for m in order["model"]], fontsize=8)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("RMSE at day 1 (°C)")
    axes[0].set_title("Error, split into offset and the rest", fontsize=9.5)
    axes[0].legend(fontsize=7, frameon=False, loc="lower right")

    for _, row in board.iterrows():
        colour = _colour(row["model"], best)
        axes[1].scatter(
            row["bias_c"], row["debiased_rmse_c"], s=52, color=colour, zorder=3
        )
        axes[1].annotate(
            MODEL_LABEL.get(row["model"], row["model"]),
            (row["bias_c"], row["debiased_rmse_c"]),
            textcoords="offset points",
            xytext=(6, 3),
            fontsize=7.5,
            color=colour,
        )
    axes[1].axvline(0, color="#334155", linewidth=0.8, linestyle="--")
    axes[1].set_xlabel("Mean bias at day 1 (°C)   ← cold        warm →")
    axes[1].set_ylabel("RMSE after removing the bias (°C)")
    axes[1].set_title("A small bias is not the same as a good model", fontsize=9.5)
    axes[1].set_xlim(-1.9, 0.4)

    fig.suptitle(
        "Every model runs cold on the daily maximum; they differ in how much else is wrong",
        fontsize=10.5,
        y=1.03,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "bias_vs_skill.png", bbox_inches="tight")
    plt.close(fig)


def figure_station_bias(china: pd.DataFrame) -> None:
    day1 = china[china["lead_days"] == 1]
    table = day1.pivot_table(
        index="station", columns="model", values="error_c", aggfunc="mean"
    )
    table = table[[m for m in CORE_MODELS if m in table.columns]]

    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    limit = float(np.nanmax(np.abs(table.to_numpy())))
    image = ax.imshow(table.to_numpy(), cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")

    ax.set_xticks(range(len(table.columns)))
    ax.set_xticklabels(
        [MODEL_LABEL.get(m, m) for m in table.columns], rotation=30, ha="right", fontsize=8
    )
    ax.set_yticks(range(len(table.index)))
    ax.set_yticklabels(table.index, fontsize=8)
    for i in range(table.shape[0]):
        for j in range(table.shape[1]):
            value = table.iat[i, j]
            ax.text(
                j, i, f"{value:.1f}", ha="center", va="center", fontsize=7,
                color="white" if abs(value) > 0.6 * limit else "#1f2937",
            )
    ax.set_title("Mean bias at day 1 by station (°C); blue is cold", fontsize=10)
    fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
    fig.tight_layout()
    fig.savefig(FIGURES / "station_bias.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    pairs = load()
    china = sets(pairs[pairs["group"] == "china"])["core"]
    figure_lead_growth(china)
    figure_bias_vs_skill(china)
    figure_station_bias(china)
    print(f"figures written to {FIGURES}")


if __name__ == "__main__":
    main()
