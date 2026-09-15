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

from .fetch import IS_AI, MODEL_LABEL
from .run_verification import (
    CORE_MODELS,
    REPORTS,
    ai_sets,
    available,
    load,
    ranking_across_variables,
    sets,
)
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


def figure_lead_growth(china: pd.DataFrame, suffix: str = "", variable_label: str = "daily maximum 2 m temperature (°C)") -> None:
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
    ax.set_ylabel(f"RMSE, {variable_label}")
    ax.set_xticks(sorted(growth["lead_days"].unique()))
    ax.set_xlim(0.8, 6.4)
    ax.set_title(
        f"{variable_label.capitalize()}, nine Chinese airport stations, 2024-07 to 2025-08",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / f"lead_growth{suffix}.png", bbox_inches="tight")
    plt.close(fig)


def figure_bias_vs_skill(china: pd.DataFrame, suffix: str = "", variable_label: str = "daily maximum 2 m temperature (°C)") -> None:
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
    axes[0].set_xlabel(f"RMSE at day 1 — {variable_label}")
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
    axes[1].set_xlabel("Mean bias at day 1   ← low        high →")
    axes[1].set_ylabel("RMSE after removing the bias")
    axes[1].set_title("A small bias is not the same as a good model", fontsize=9.5)


    fig.suptitle(
        f"{variable_label.capitalize()}: every model runs low; "
        f"they differ in how much of that is a constant",
        fontsize=10.5,
        y=1.03,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / f"bias_vs_skill{suffix}.png", bbox_inches="tight")
    plt.close(fig)


def figure_station_bias(china: pd.DataFrame, suffix: str = "", variable_label: str = "daily maximum 2 m temperature (°C)") -> None:
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
    ax.set_title(f"Mean bias at day 1 by station, {variable_label}; blue is low", fontsize=10)
    fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
    fig.tight_layout()
    fig.savefig(FIGURES / f"station_bias{suffix}.png", bbox_inches="tight")
    plt.close(fig)


# Figure text is English throughout: this repository's README is English, and
# the default matplotlib font has no CJK glyphs, which silently renders Chinese
# labels as empty boxes rather than failing.
VARIABLE_LABEL = {
    "temperature_2m": "daily maximum 2 m temperature (°C)",
    "wind_speed_10m": "daily mean 10 m wind speed (m/s)",
}


def figure_rank_reversal() -> None:
    """The finding the whole study turns on: rank depends on the variable.

    A slope chart rather than two bar charts, because the point is not where
    each model sits on either list — it is how far it moves between them.
    """
    table = ranking_across_variables()
    if len(table.columns) < 2:
        return
    left, right = table.columns[0], table.columns[1]

    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    for model, row in table.iterrows():
        change = abs(row[left] - row[right])
        colour = _colour(model, best="")
        if change >= 4:
            colour = HIGHLIGHT if model == "cma_grapes_global" else "#7c3aed"
        ax.plot(
            [0, 1], [row[left], row[right]],
            marker="o", markersize=6,
            linewidth=2.4 if change >= 4 else 1.2,
            color=colour, zorder=3 if change >= 4 else 2,
        )
        ax.annotate(
            MODEL_LABEL.get(model, model), (0, row[left]),
            textcoords="offset points", xytext=(-10, -3),
            ha="right", fontsize=8, color=colour,
        )
        ax.annotate(
            MODEL_LABEL.get(model, model), (1, row[right]),
            textcoords="offset points", xytext=(10, -3),
            ha="left", fontsize=8, color=colour,
        )

    ax.set_xlim(-0.55, 1.55)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([VARIABLE_LABEL.get(left, left), VARIABLE_LABEL.get(right, right)])
    ax.invert_yaxis()
    ax.set_yticks(range(1, len(table) + 1))
    ax.set_ylabel("Rank at day 1 (1 is best)")
    ax.set_title(
        "The best model depends entirely on which variable you asked about",
        fontsize=10.5,
    )
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "rank_reversal.png", bbox_inches="tight")
    plt.close(fig)


AI_COLOUR = "#7c3aed"


def figure_ai_vs_physics() -> None:
    """Where a machine-learned model sits, and how that changes with lead.

    Two panels because the day-1 ranking and the growth rate say different
    things, and quoting either alone misleads. AIFS is mid-pack at day 1 and has
    the flattest error growth in the set; a scorecard at one lead hides that
    entirely.
    """
    for variable in available(ai=True):
        pairs = load(variable, ai=True)
        china = ai_sets(pairs[pairs["group"] == "china"])
        growth = verify.error_growth(china)
        day1 = growth[growth["lead_days"] == 1].set_index("model")["rmse_c"]
        best = day1.idxmin()

        fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.8))
        for model, group in growth.groupby("model"):
            group = group.sort_values("lead_days")
            is_ai = model in IS_AI
            colour = AI_COLOUR if is_ai else _colour(model, best)
            width = 2.4 if is_ai else (1.7 if colour != OTHER else 1.1)
            axes[0].plot(group["lead_days"], group["rmse_c"], marker="o",
                         markersize=3.5, linewidth=width, color=colour,
                         zorder=4 if is_ai else 2)
            # Normalised to its own day-1 value: the shape, not the level.
            axes[1].plot(group["lead_days"], group["rmse_c"] / group["rmse_c"].iloc[0],
                         marker="o", markersize=3.5, linewidth=width, color=colour,
                         zorder=4 if is_ai else 2)
            for ax, series in ((axes[0], group["rmse_c"]), (axes[1], group["rmse_c"] / group["rmse_c"].iloc[0])):
                ax.annotate(MODEL_LABEL.get(model, model),
                            (group["lead_days"].iloc[-1], series.iloc[-1]),
                            textcoords="offset points", xytext=(5, -2),
                            fontsize=7, color=colour,
                            fontweight="bold" if is_ai else "normal")

        label = VARIABLE_LABEL.get(variable, variable)
        axes[0].set_ylabel(f"RMSE, {label}")
        axes[1].set_ylabel("RMSE relative to its own day-1 value")
        for ax in axes:
            ax.set_xlabel("Lead time (days)")
            ax.set_xticks(sorted(growth["lead_days"].unique()))
            ax.set_xlim(0.8, 6.6)
        axes[0].set_title("Absolute error: AIFS starts behind", fontsize=9.5)
        axes[1].set_title("Growth: AIFS degrades the slowest", fontsize=9.5)
        fig.suptitle(
            f"ECMWF AIFS against six physics models, {label}, "
            f"Chinese stations, 2025-03 to 2025-08",
            fontsize=10.5, y=1.03,
        )
        fig.tight_layout()
        suffix = "" if variable == "temperature_2m" else f"_{variable}"
        fig.savefig(FIGURES / f"ai_vs_physics{suffix}.png", bbox_inches="tight")
        plt.close(fig)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    for variable in available():
        pairs = load(variable)
        china = sets(pairs[pairs["group"] == "china"])["core"]
        suffix = "" if variable == "temperature_2m" else f"_{variable}"
        figure_lead_growth(china, suffix, VARIABLE_LABEL.get(variable, variable))
        figure_bias_vs_skill(china, suffix, VARIABLE_LABEL.get(variable, variable))
        figure_station_bias(china, suffix, VARIABLE_LABEL.get(variable, variable))
    figure_rank_reversal()
    figure_ai_vs_physics()
    print(f"figures written to {FIGURES}")


if __name__ == "__main__":
    main()
