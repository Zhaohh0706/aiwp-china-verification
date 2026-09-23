"""Can the committed reports be rebuilt from the committed data?

A repository like this one makes a promise that is easy to break by accident:
the numbers on the page were computed from the parquet next to them. A change to
a scoring rule, a pandas upgrade that alters a groupby default, a debiasing
window edited and not re-run - any of these leaves a page that no longer matches
its own data, and nothing about the page looks wrong.

So: regenerate into a temporary directory, walk the two JSON trees together, and
compare every number. Strings and structure have to match too, because a model
silently dropped from a table is as much a change as a number that moved.

The tolerance is 1e-6 relative, which is also roughly the precision the files are
written at - values are stored rounded to six decimals, so this check resolves a
drift of about that size and no finer. It is meant to catch a rule that changed,
not floating-point noise in the last bit.

    python scripts/check_reproducible.py            # every committed page
    python scripts/check_reproducible.py 2026-08    # one of them
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "reports" / "leaderboard"
RTOL = 1e-6
ATOL = 1e-6


def differences(old, new, path: str = "") -> list[str]:
    """Every place the two trees disagree, named by where it is."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            here = f"{path}.{key}" if path else str(key)
            if key not in old:
                out.append(f"{here}: 重算里多出来的，旧报告没有")
            elif key not in new:
                out.append(f"{here}: 重算里没有了，旧报告有 {old[key]!r}")
            else:
                out += differences(old[key], new[key], here)
        return out
    if isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            return [f"{path}: 长度 {len(old)} → {len(new)}"]
        out = []
        for i, (a, b) in enumerate(zip(old, new)):
            out += differences(a, b, f"{path}[{i}]")
        return out
    if isinstance(old, bool) or isinstance(new, bool):
        return [] if old == new else [f"{path}: {old} → {new}"]
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        if math.isnan(old) and math.isnan(new):
            return []
        if math.isclose(float(old), float(new), rel_tol=RTOL, abs_tol=ATOL):
            return []
        return [f"{path}: {old} → {new}（差 {float(new) - float(old):+.3g}）"]
    return [] if old == new else [f"{path}: {old!r} → {new!r}"]


def main() -> int:
    wanted = sys.argv[1:] or [p.stem for p in sorted(PAGES.glob("*.json"))]
    if not wanted:
        print("没有已提交的榜单页可对账")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        failures = 0
        for tag in wanted:
            committed = PAGES / f"{tag}.json"
            if not committed.exists():
                print(f"{tag}: 找不到 {committed}")
                failures += 1
                continue
            run = subprocess.run(
                [sys.executable, "-m", "aiwp.leaderboard", "--tag", tag, "--out", tmp],
                cwd=ROOT, capture_output=True, text=True,
                env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
            )
            if run.returncode != 0:
                print(f"{tag}: 重算失败\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}")
                failures += 1
                continue
            found = differences(
                json.loads(committed.read_text(encoding="utf-8")),
                json.loads((Path(tmp) / f"{tag}.json").read_text(encoding="utf-8")),
            )
            if found:
                failures += 1
                print(f"\n{tag}: 重算结果与已提交的报告对不上，{len(found)} 处：")
                for line in found[:30]:
                    print(f"  {line}")
                if len(found) > 30:
                    print(f"  ...还有 {len(found) - 30} 处")
            else:
                print(f"{tag}: 一致（{RTOL:g} 相对容差）")

    if failures:
        print(f"\n{failures} 页对不上。要么是数据变了没重出报告，要么是算法改了没说。"
              "两种都要人来判断，不要直接重出了事。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
