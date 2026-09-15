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
    AI_MODEL,
    CORE_MODELS,
    REPORTS,
    VERIFICATION_GROUP,
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
        growth[growth["lead_days"] == 1].sort_values("rmse")["model"].iloc[0]
    )

    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    for model, group in growth.groupby("model"):
        group = group.sort_values("lead_days")
        colour = _colour(model, best)
        ax.plot(
            group["lead_days"],
            group["rmse"],
            marker="o",
            markersize=3.5,
            linewidth=1.8 if colour != OTHER else 1.1,
            color=colour,
            label=MODEL_LABEL.get(model, model),
            zorder=3 if colour != OTHER else 2,
        )
        ax.annotate(
            MODEL_LABEL.get(model, model),
            (group["lead_days"].iloc[-1], group["rmse"].iloc[-1]),
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
    board["bias_share"] = 100.0 * board["bias"] ** 2 / board["rmse"] ** 2
    best = board.sort_values("rmse")["model"].iloc[0]

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))

    order = board.sort_values("rmse")
    y = np.arange(len(order))
    colours = [_colour(m, best) for m in order["model"]]
    axes[0].barh(y, order["debiased_rmse"], color=colours, label="error left after debiasing")
    axes[0].barh(
        y,
        order["rmse"] - order["debiased_rmse"],
        left=order["debiased_rmse"],
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
            row["bias"], row["debiased_rmse"], s=52, color=colour, zorder=3
        )
        axes[1].annotate(
            MODEL_LABEL.get(row["model"], row["model"]),
            (row["bias"], row["debiased_rmse"]),
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
        index="station", columns="model", values="error", aggfunc="mean"
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
    # Hourly mean irradiance summed over the day, so energy and not power.
    "shortwave_radiation": "daily solar irradiation (Wh/m²)",
}

# Where each variable is verified, for figure captions.  Irradiance is scored
# at the photovoltaic sites against a satellite retrieval, not at the airports.
GROUP_LABEL = {
    "china": "Chinese airport stations",
    "pv": "eight Chinese photovoltaic sites",
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


def figure_rank_reversal_ai() -> None:
    """The same models, three variables, one shared six-month window.

    The two-variable version of this chart uses the full archive, where only
    temperature and wind exist. This one is restricted to the months where all
    three variables and the AI model are present, so the ranks are comparable
    across the whole width of it rather than across different periods.
    """
    # Every column must rank the same models.  JMA GSM publishes no surface
    # radiation, so a chart that ranked seven models on two variables and six on
    # the third would put "sixth of seven" and "last of six" at the same height
    # and invite the reader to compare them.  The set is narrowed to the models
    # present everywhere, and the ones dropped are named in the caption.
    scored_by_variable = {}
    for variable in available(ai=True):
        pairs = load(variable, ai=True)
        group = VERIFICATION_GROUP[variable]
        scored_by_variable[variable] = ai_sets(
            pairs[pairs["group"] == group], variable
        )
    if len(scored_by_variable) < 3:
        return

    shared = set.intersection(
        *(set(frame["model"].unique()) for frame in scored_by_variable.values())
    )
    dropped = sorted(
        set.union(*(set(f["model"].unique()) for f in scored_by_variable.values()))
        - shared
    )

    columns = {}
    for variable, scored in scored_by_variable.items():
        day1 = scored[(scored["lead_days"] == 1) & (scored["model"].isin(shared))]
        board = verify.scorecard(day1).sort_values("rmse").reset_index(drop=True)
        columns[variable] = pd.Series(board.index + 1, index=board["model"])

    table = pd.DataFrame(columns)
    order = list(table.columns)

    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    span = (table.max(axis=1) - table.min(axis=1)).fillna(0)
    for model, row in table.iterrows():
        is_ai = model in IS_AI
        colour = AI_COLOUR if is_ai else _colour(model, best="")
        if not is_ai and span.loc[model] >= 4:
            colour = HIGHLIGHT if model == "cma_grapes_global" else "#0369a1"
        points = [(i, row[c]) for i, c in enumerate(order) if pd.notna(row[c])]
        ax.plot(
            [x for x, _ in points], [y for _, y in points],
            marker="o", markersize=6,
            linewidth=2.6 if (is_ai or span.loc[model] >= 4) else 1.1,
            color=colour, zorder=4 if is_ai else (3 if span.loc[model] >= 4 else 2),
        )
        first_x, first_y = points[0]
        last_x, last_y = points[-1]
        name = MODEL_LABEL.get(model, model)
        weight = "bold" if is_ai else "normal"
        ax.annotate(name, (first_x, first_y), textcoords="offset points",
                    xytext=(-10, -3), ha="right", fontsize=8,
                    color=colour, fontweight=weight)
        ax.annotate(name, (last_x, last_y), textcoords="offset points",
                    xytext=(10, -3), ha="left", fontsize=8,
                    color=colour, fontweight=weight)

    ax.set_xlim(-0.9, len(order) - 1 + 0.9)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(
        [VARIABLE_LABEL.get(c, c).replace(" (", "\n(") for c in order], fontsize=8.5
    )
    ax.invert_yaxis()
    ax.set_yticks(range(1, int(table.max().max()) + 1))
    ax.set_ylabel("Rank at day 1 (1 is best)")
    ax.set_title(
        f"No model is best at everything: {len(table)} models ranked over one "
        f"shared window, 2025-03 to 2025-08",
        fontsize=10.5,
    )
    if dropped:
        names = ", ".join(MODEL_LABEL.get(m, m) for m in dropped)
        ax.text(
            0.5, -0.17,
            f"{names} excluded: not published for every variable in this window",
            transform=ax.transAxes, ha="center", fontsize=7.5, color="#64748b",
        )
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "rank_reversal_ai_window.png", bbox_inches="tight")
    plt.close(fig)



def _ordinal(n: int) -> str:
    """1st, 2nd, 3rd — not 3th."""
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }".replace(" ", "")


def _ai_titles(growth: pd.DataFrame) -> tuple[str, str]:
    """Panel titles read off the curves rather than written from memory.

    The first version of this figure was titled "AIFS starts behind" and "AIFS
    degrades the slowest". Both were true of temperature. On irradiance AIFS is
    level at day 1 and third on growth, and the titles would have contradicted
    the lines underneath them.
    """
    board = growth.pivot(index="model", columns="lead_days", values="rmse")
    if AI_MODEL not in board.index:
        return "Absolute error by lead time", "Growth relative to day 1"

    first, last = board.columns.min(), board.columns.max()
    day1_rank = int(board[first].rank().loc[AI_MODEL])
    gap = 100.0 * (board.loc[AI_MODEL, first] / board[first].min() - 1.0)
    relative = board.div(board[first], axis=0)
    growth_rank = int(relative[last].rank().loc[AI_MODEL])
    far_rank = int(board[last].rank().loc[AI_MODEL])

    if day1_rank == 1:
        start = "AIFS leads from day 1"
    elif gap < 2.0:
        start = "AIFS is level at day 1"
    else:
        start = f"AIFS starts {gap:.0f}% behind"
    finish = f", first by day {last}" if far_rank == 1 and day1_rank != 1 else ""
    left = f"Absolute error: {start}{finish}"

    right = (
        "Growth: AIFS degrades the slowest"
        if growth_rank == 1
        else f"Growth: AIFS is {_ordinal(growth_rank)} of {len(board)}"
    )
    return left, right


def figure_ai_vs_physics() -> None:
    """Where a machine-learned model sits, and how that changes with lead.

    Two panels because the day-1 ranking and the growth rate say different
    things, and quoting either alone misleads. Which of them flatters AIFS
    depends on the variable, so both panel titles are computed.
    """
    for variable in available(ai=True):
        pairs = load(variable, ai=True)
        group = VERIFICATION_GROUP[variable]
        scored = ai_sets(pairs[pairs["group"] == group], variable)
        growth = verify.error_growth(scored)
        day1 = growth[growth["lead_days"] == 1].set_index("model")["rmse"]
        best = day1.idxmin()

        fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.8))
        for model, block in growth.groupby("model"):
            block = block.sort_values("lead_days")
            is_ai = model in IS_AI
            colour = AI_COLOUR if is_ai else _colour(model, best)
            width = 2.4 if is_ai else (1.7 if colour != OTHER else 1.1)
            axes[0].plot(block["lead_days"], block["rmse"], marker="o",
                         markersize=3.5, linewidth=width, color=colour,
                         zorder=4 if is_ai else 2)
            # Normalised to its own day-1 value: the shape, not the level.
            axes[1].plot(block["lead_days"], block["rmse"] / block["rmse"].iloc[0],
                         marker="o", markersize=3.5, linewidth=width, color=colour,
                         zorder=4 if is_ai else 2)
            for ax, series in (
                (axes[0], block["rmse"]),
                (axes[1], block["rmse"] / block["rmse"].iloc[0]),
            ):
                ax.annotate(MODEL_LABEL.get(model, model),
                            (block["lead_days"].iloc[-1], series.iloc[-1]),
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
        left_title, right_title = _ai_titles(growth)
        axes[0].set_title(left_title, fontsize=9.5)
        axes[1].set_title(right_title, fontsize=9.5)
        fig.suptitle(
            f"ECMWF AIFS against the physics models, {label}, "
            f"{GROUP_LABEL.get(group, group)}, 2025-03 to 2025-08",
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
    figure_rank_reversal_ai()
    figure_ai_vs_physics()
    print(f"figures written to {FIGURES}")


if __name__ == "__main__":
    main()
