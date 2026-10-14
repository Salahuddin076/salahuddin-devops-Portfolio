#!/usr/bin/env python3
"""Simulate a CodeDeploy ECS traffic-shift timeline, minute by minute.

This is a MODEL of the documented semantics of the predefined ECS
deployment configurations, not a recording of a real deployment:

  AllAtOnce                  100% to green at minute 0.
  CanaryPPercentMMinutes     P% at minute 0, the remaining traffic at minute M.
  LinearPPercentEveryMMinutes P% at minute 0, another P% every M minutes,
                             until 100%.

Minute 0 is the moment traffic starts to move, i.e. after the replacement
task set is healthy behind the test listener and BeforeAllowTraffic has
succeeded. After 100% reaches green, AfterAllowTraffic runs and the blue
task set is kept for the termination wait. Until blue is terminated, an
alarm in ALARM state stops the deployment and CodeDeploy reroutes all
traffic back to blue. After that there is nothing left to roll back to.

Simplifications (stated in the docs too): alarm detection is modelled as
instantaneous at the breach minute (CodeDeploy polls alarms, and CloudWatch
needs its evaluation periods first), rerouting is instantaneous, and hook
durations and the manual-reroute wait are not modelled.

Exit codes: 0 on a valid simulation (any outcome), 2 on invalid input.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, field

KNOWN_CONFIGS = (
    "CodeDeployDefault.ECSAllAtOnce",
    "CodeDeployDefault.ECSLinear10PercentEvery1Minutes",
    "CodeDeployDefault.ECSLinear10PercentEvery3Minutes",
    "CodeDeployDefault.ECSCanary10Percent5Minutes",
    "CodeDeployDefault.ECSCanary10Percent15Minutes",
)

_PATTERN = re.compile(
    r"(?:^|\.)ECS(?:"
    r"(?P<all>AllAtOnce)"
    r"|Linear(?P<lp>\d+)PercentEvery(?P<lm>\d+)Minutes?"
    r"|Canary(?P<cp>\d+)Percent(?P<cm>\d+)Minutes?"
    r")$"
)

SUCCEEDED = "SUCCEEDED"
ROLLED_BACK = "ROLLED_BACK"
IN_PROGRESS = "IN_PROGRESS"


class SimulationError(ValueError):
    """Invalid configuration name or simulation input."""


@dataclass(frozen=True)
class ShiftConfig:
    name: str
    kind: str  # "all_at_once" | "canary" | "linear"
    percent: int = 100
    interval_minutes: int = 0

    def describe(self) -> str:
        if self.kind == "all_at_once":
            return "all-at-once, 100% at minute 0"
        if self.kind == "canary":
            return f"canary, {self.percent}% for {self.interval_minutes} min, then 100%"
        return f"linear, +{self.percent}% every {self.interval_minutes} min"

    def green_percent_at(self, minute: int) -> int:
        if minute < 0:
            return 0
        if self.kind == "all_at_once":
            return 100
        if self.kind == "canary":
            return self.percent if minute < self.interval_minutes else 100
        steps = minute // self.interval_minutes + 1
        return min(100, self.percent * steps)

    @property
    def shift_complete_minute(self) -> int:
        if self.kind == "all_at_once":
            return 0
        if self.kind == "canary":
            return self.interval_minutes
        return self.interval_minutes * (math.ceil(100 / self.percent) - 1)


def parse_config(name: str) -> ShiftConfig:
    """Parse a predefined (or identically named custom) ECS deployment config."""
    match = _PATTERN.search(name or "")
    if not match:
        raise SimulationError(
            f"unrecognised deployment config {name!r}; expected one of: " + ", ".join(KNOWN_CONFIGS)
        )
    if match.group("all"):
        return ShiftConfig(name, "all_at_once")
    if match.group("lp"):
        kind, percent, minutes = "linear", int(match.group("lp")), int(match.group("lm"))
    else:
        kind, percent, minutes = "canary", int(match.group("cp")), int(match.group("cm"))
    if not 1 <= percent <= 99:
        raise SimulationError(f"{name}: percent must be between 1 and 99, got {percent}")
    if minutes < 1:
        raise SimulationError(f"{name}: interval must be at least 1 minute, got {minutes}")
    return ShiftConfig(name, kind, percent, minutes)


@dataclass
class Step:
    minute: int
    green_percent: int
    events: list[str] = field(default_factory=list)

    @property
    def blue_percent(self) -> int:
        return 100 - self.green_percent


@dataclass
class Simulation:
    config: str
    model: str
    total_minutes: int
    termination_wait_minutes: int
    alarm_at: int | None
    shift_complete_minute: int
    blue_terminated_minute: int
    outcome: str
    outcome_minute: int | None
    peak_green_percent: int
    steps: list[Step]

    def to_dict(self) -> dict:
        data = asdict(self)
        for step in data["steps"]:
            step["blue_percent"] = 100 - step["green_percent"]
        return data


def simulate(
    config_name: str,
    total_minutes: int,
    alarm_at: int | None = None,
    termination_wait_minutes: int = 0,
) -> Simulation:
    cfg = parse_config(config_name)
    if total_minutes < 0:
        raise SimulationError("total minutes must be >= 0")
    if termination_wait_minutes < 0:
        raise SimulationError("termination wait must be >= 0")
    if alarm_at is not None and alarm_at < 0:
        raise SimulationError("alarm minute must be >= 0")

    complete = cfg.shift_complete_minute
    terminated = complete + termination_wait_minutes
    steps: list[Step] = []
    outcome, outcome_minute = IN_PROGRESS, None
    peak = 0
    previous = 0

    for minute in range(total_minutes + 1):
        green = cfg.green_percent_at(minute)
        step = Step(minute, green)

        # An alarm counts while the deployment is still in progress, i.e.
        # before the blue task set is terminated.
        if alarm_at is not None and minute >= alarm_at and minute < terminated:
            # The alarm is evaluated before this minute's shift step.
            peak = max(peak, previous)
            step.green_percent = 0
            step.events.append(
                "alarm in ALARM: deployment stopped, rollback reroutes 100% to blue"
            )
            steps.append(step)
            outcome, outcome_minute = ROLLED_BACK, minute
            break

        peak = max(peak, green)
        if minute == 0:
            step.events.append(
                f"BeforeAllowTraffic passed; traffic shift starts ({green}% to green)"
            )
        elif green != previous:
            step.events.append(f"shift to {green}% green")
        if minute == complete:
            step.events.append("100% on green; AfterAllowTraffic runs; blue kept on standby")
        if minute == terminated:
            if alarm_at is not None and alarm_at == minute:
                step.events.append("alarm breached as blue was terminated: no automatic rollback")
            step.events.append("blue task set terminated; deployment SUCCEEDED")
            steps.append(step)
            outcome, outcome_minute = SUCCEEDED, minute
            break
        steps.append(step)
        previous = green

    return Simulation(
        config=cfg.name,
        model=cfg.describe(),
        total_minutes=total_minutes,
        termination_wait_minutes=termination_wait_minutes,
        alarm_at=alarm_at,
        shift_complete_minute=complete,
        blue_terminated_minute=terminated,
        outcome=outcome,
        outcome_minute=outcome_minute,
        peak_green_percent=peak,
        steps=steps,
    )


def render_text(sim: Simulation, events_only: bool = False) -> str:
    lines = [
        f"config:      {sim.config}",
        f"model:       {sim.model}",
        f"termination: blue kept {sim.termination_wait_minutes} min after the full shift"
        f" (terminated at minute {sim.blue_terminated_minute})",
        "alarm:       " + ("none" if sim.alarm_at is None else f"breach at minute {sim.alarm_at}"),
        "minute  green   blue  event",
    ]
    for step in sim.steps:
        if events_only and not step.events:
            continue
        events = step.events or [""]
        for index, event in enumerate(events):
            if index == 0:
                row = f"{step.minute:>6}  {step.green_percent:>4}%  {step.blue_percent:>4}%  {event}"
            else:
                row = f"{'':>6}  {'':>5}  {'':>5}  {event}"
            lines.append(row.rstrip())
    if sim.outcome == ROLLED_BACK:
        lines.append(
            f"result: ROLLED_BACK at minute {sim.outcome_minute}; 100% back on blue"
            f" (green peaked at {sim.peak_green_percent}%)"
        )
    elif sim.outcome == SUCCEEDED:
        lines.append(f"result: SUCCEEDED at minute {sim.outcome_minute}; 100% on green, no rollback")
    else:
        lines.append(
            f"result: IN_PROGRESS after {sim.total_minutes} min"
            f" ({sim.steps[-1].green_percent if sim.steps else 0}% on green)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Model a CodeDeploy ECS traffic shift and alarm rollback (a model, not AWS)."
    )
    parser.add_argument("--config", required=True, help="e.g. CodeDeployDefault.ECSCanary10Percent5Minutes")
    parser.add_argument("--minutes", type=int, required=True, help="simulation horizon in minutes")
    parser.add_argument("--alarm-at", type=int, default=None, help="minute an alarm enters ALARM")
    parser.add_argument("--termination-wait", type=int, default=0,
                        help="minutes blue is kept after the full shift (default 0)")
    parser.add_argument("--events-only", action="store_true", help="only print minutes with events")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        sim = simulate(args.config, args.minutes, args.alarm_at, args.termination_wait)
    except SimulationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(sim.to_dict(), indent=2))
    else:
        print(render_text(sim, events_only=args.events_only))
    return 0


if __name__ == "__main__":
    sys.exit(main())
