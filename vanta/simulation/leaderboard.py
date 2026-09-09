"""Plain-text leaderboard rendering for the replay (ARCHITECTURE.md §34, §41).

Terminal output only — no dependency, no colour codes, nothing that breaks in a
screenshot. §51 is explicit that polish is not the priority; this exists to make the
mechanism's behaviour legible, not to look like a product.
"""

from __future__ import annotations

from vanta.simulation.replay import Checkpoint, SimulationResult

__all__ = ["render_checkpoint", "render_dataset", "render_report", "render_summary"]

_HEADER = (
    f"{'#':>2}  {'MINER':<14} {'SCORE':>7} {'EMA':>7} {'PROBQ':>7} {'BRIER':>7} "
    f"{'RETQ':>7} {'CALIB':>7} {'WEIGHT':>7} {'DIR%':>6} {'RETERR':>8} {'N':>6}"
)
_RULE = "-" * len(_HEADER)


def render_checkpoint(checkpoint: Checkpoint, *, title: str | None = None) -> str:
    heading = title or f"AFTER {checkpoint.valid_tasks} VALID TASKS"
    lines = [heading, _RULE, _HEADER, _RULE]
    for row in checkpoint.rows:
        marker = "*" if row.provisional else " "
        lines.append(
            f"{row.rank:>2}{marker} {row.name:<14} "
            f"{row.mean_score:>7.4f} {row.ema_reputation:>7.4f} "
            f"{row.probability_quality:>7.4f} {row.brier:>7.4f} "
            f"{row.return_score:>7.4f} {row.calibration:>7.4f} "
            f"{row.weight:>7.4f} {row.directional_accuracy * 100:>5.1f}% "
            f"{row.mean_absolute_return_error:>8.5f} {row.forecast_count:>6}"
        )
    return "\n".join(lines)


def render_dataset(result: SimulationResult) -> str:
    dataset = result.dataset
    days = (dataset.end_time - dataset.start_time) / 86_400
    return "\n".join(
        [
            "DATASET",
            _RULE,
            f"source            {dataset.source}",
            f"symbol            {dataset.symbol}",
            f"interval          {dataset.interval_seconds}s",
            f"start             {dataset.start_time}",
            f"end               {dataset.end_time}",
            f"candles           {dataset.candle_count} ({days:.1f} days)",
            f"horizon           {result.config.horizon_seconds}s",
            f"task spacing      {result.config.task_spacing}s",
            f"lookback          {result.config.lookback_candles} candles",
        ]
    )


def render_summary(result: SimulationResult) -> str:
    consensus = result.consensus
    return "\n".join(
        [
            "TASK ACCOUNTING",
            _RULE,
            f"attempted         {result.attempted_tasks}",
            f"valid (scored)    {result.valid_tasks}",
            f"void (flat)       {result.void_tasks}",
            f"unresolvable      {result.unresolvable_tasks}",
            f"incomplete        {result.incomplete_tasks}",
            "",
            "VANTA CONSENSUS",
            _RULE,
            f"directional acc   {consensus.directional_accuracy * 100:.2f}%",
            f"mean brier        {consensus.mean_brier:.4f}",
            f"mean p(up)        {consensus.mean_probability:.4f}",
            f"mean dispersion   {consensus.mean_dispersion:.4f}",
        ]
    )


def render_report(result: SimulationResult) -> str:
    blocks = [
        "VANTA — HISTORICAL REPLAY",
        "=" * len(_RULE),
        "",
        render_dataset(result),
        "",
        render_summary(result),
        "",
    ]
    for checkpoint in result.checkpoints:
        blocks.extend([render_checkpoint(checkpoint), ""])
    blocks.extend(
        [
            render_checkpoint(
                result.final, title=f"FINAL — {result.final.valid_tasks} VALID TASKS"
            ),
            "",
            "* provisional (inside the 10-forecast probation window, §20)",
        ]
    )
    return "\n".join(blocks)
