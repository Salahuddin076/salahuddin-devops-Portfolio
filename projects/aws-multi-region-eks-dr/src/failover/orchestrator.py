"""Ordered, resumable, guarded failover between two regions.

Steps, in order (the same for both modes; what each does differs):

  1. precheck        target healthy, global-cluster topology as expected;
                     planned: source healthy and lag below the threshold;
                     unplanned: source NOT healthy, last lag recorded as the
                     RPO exposure
  2. fence-source    scale workers to 0 in the old writer region, mark it
                     fenced in the state. Unreachable in unplanned mode:
                     recorded as skipped, region still marked fenced
  3. promote-target  planned: managed switchover (no data loss);
                     unplanned: detach the secondary and promote it
                     (writes not yet replicated are lost)
  4. scale-target    raise the HPA minimum and enable workers in the target
  5. flip-dns        make the target's failover record PRIMARY
  6. postcheck       verify the end state, including "no second writer"

Guards that run before any step:
  - the confirm token must equal the global cluster id;
  - an unfinished run for the other region that already promoted is a
    split brain in the making: refused;
  - more than one unfenced writer (from the database's own view): refused;
  - moving the writer back to a fenced region (failback) needs
    --rebuild-confirmed, and the precheck verifies it is a secondary again.

Every step is idempotent (it checks before it acts), its result is saved to
the state file before the next one starts, and a re-run resumes at the first
step not yet done. Nothing that already succeeded runs twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from failover.audit import AuditLog
from failover.config import Config
from failover.ports import Adapters, Unreachable

MODES = ("planned", "unplanned")
STEP_IDS = ("precheck", "fence-source", "promote-target", "scale-target", "flip-dns", "postcheck")
FINISHED = ("done", "skipped")


# --------------------------------------------------------------------------
# Errors (exit codes are the CLI's)
# --------------------------------------------------------------------------


class FailoverError(Exception):
    exit_code = 1


class ConfirmationError(FailoverError):
    exit_code = 2


class GuardRefused(FailoverError):
    exit_code = 3


class SplitBrainRefused(GuardRefused):
    pass


class FailbackRefused(GuardRefused):
    pass


class RunConflict(GuardRefused):
    pass


class PrecheckFailed(FailoverError):
    exit_code = 4


class LagTooHigh(PrecheckFailed):
    pass


class StepFailed(FailoverError):
    exit_code = 5


class PostcheckFailed(StepFailed):
    pass


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StepOutcome:
    status: str  # "done" | "skipped"
    detail: str


@dataclass(frozen=True)
class PlannedStep:
    number: int
    id: str
    detail: str
    state: str  # "pending" | "done" | "skipped"


@dataclass
class Plan:
    mode: str
    source: str
    target: str
    failback: bool
    steps: list[PlannedStep]
    notes: list[str]
    resumes_run: Optional[str] = None


@dataclass
class RunResult:
    run_id: Optional[str]
    mode: str
    source: str
    target: str
    noop: bool = False
    steps: list[tuple[str, str, str]] = field(default_factory=list)  # (id, status, detail)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_lag(lag: Optional[float]) -> str:
    return "unknown" if lag is None else f"{lag:.1f}s"


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------


class Orchestrator:
    def __init__(
        self,
        config: Config,
        adapters: Adapters,
        store: Any,
        audit: AuditLog,
        clock: Callable[[], datetime] = _utcnow,
        actor: str = "unknown",
        progress: Callable[[str], None] = lambda line: None,
    ) -> None:
        self.config = config
        self.a = adapters
        self.store = store
        self.audit = audit
        self.clock = clock
        self.actor = actor
        self.progress = progress

    # -- shared helpers ---------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        return self.store.load(self.config.global_cluster_id, self.config.primary_region)

    def _resolve(self, state: dict[str, Any], target: Optional[str]) -> tuple[str, str]:
        if target is None:
            run = state.get("run")
            target = run["target"] if run else self.config.other(state["writer_region"])
        source = self.config.other(target)  # raises for an unknown region
        return source, target

    def _log(self, event: str, *, run: Optional[dict[str, Any]] = None, mode: Optional[str] = None,
             source: Optional[str] = None, target: Optional[str] = None, step: Optional[str] = None,
             status: Optional[str] = None, detail: str = "", epoch: Optional[int] = None) -> None:
        record = {
            "ts": _iso(self.clock()),
            "actor": self.actor,
            "global_cluster_id": self.config.global_cluster_id,
            "event": event,
            "run_id": run["run_id"] if run else None,
            "mode": mode or (run["mode"] if run else None),
            "source": source or (run["source"] if run else None),
            "target": target or (run["target"] if run else None),
            "step": step,
            "status": status,
            "detail": detail,
        }
        if epoch is not None:
            record["epoch"] = epoch
        self.audit.write(record)

    # -- plan -------------------------------------------------------------------

    def describe_steps(self, mode: str, source: str, target: str, failback: bool) -> dict[str, str]:
        c = self.config
        t = c.regions[target]
        lag = c.max_replication_lag_seconds
        dns_name = c.record_name or "<record>"
        if mode == "planned":
            pre = (f"{target} deep health OK; {source} healthy (planned needs both); "
                   f"Aurora global writer is {source} and {target} is a member; "
                   f"replication lag into {target} < {lag:g}s")
            fence = (f"scale workers to 0 in {source} (helm: workers.enabled=false); "
                     f"mark {source} fenced in the state file. Must succeed in planned mode")
            promote = (f"failover-global-cluster --switchover to {t.cluster_id} "
                       f"(managed switchover: waits for replication to catch up, no data loss; "
                       f"{source} becomes a secondary)")
        else:
            pre = (f"{target} deep health OK; {source} unhealthy or unreachable (if it is healthy, "
                   f"use planned); Aurora global writer is {source} and {target} is a member; "
                   f"last known lag recorded as the RPO exposure")
            fence = (f"scale workers to 0 in {source} if its EKS API answers; if not, record SKIPPED "
                     f"(workers not confirmed at 0) and mark {source} fenced anyway")
            promote = (f"remove-from-global-cluster {t.cluster_id}, wait until it is a standalone writer "
                       f"(writes not yet replicated from {source} are lost: RPO = lag at failure time)")
        if failback:
            pre += f"; failback: {target} must be a secondary again (--rebuild-confirmed given)"
        return {
            "precheck": pre,
            "fence-source": fence,
            "promote-target": promote,
            "scale-target": (f"{target}: HPA minReplicas {t.active_api_min_replicas}, "
                             f"workers.enabled=true, workers.replicas={t.active_workers}"),
            "flip-dns": (f"Route 53 {dns_name}: {target} -> PRIMARY, {source} -> SECONDARY "
                         f"(one change batch)"),
            "postcheck": (f"{target} healthy, a writer, PRIMARY in DNS, workers > 0; "
                          f"no unfenced second writer; workers 0 in {source} if reachable"),
        }

    def plan(self, mode: str, target: Optional[str] = None) -> Plan:
        if mode not in MODES:
            raise FailoverError(f"mode must be one of {MODES}")
        state = self._load()
        source, target = self._resolve(state, target)
        run = state.get("run")
        resumable = run if run and run["target"] == target and run["mode"] == mode else None
        failback = target in state["fenced"] if not resumable else bool(resumable.get("failback"))
        details = self.describe_steps(mode, source, target, failback)
        steps = []
        for i, sid in enumerate(STEP_IDS, 1):
            done = (resumable or {}).get("steps", {}).get(sid, {}).get("status")
            steps.append(PlannedStep(i, sid, details[sid], done if done in FINISHED else "pending"))
        notes = [f"execute needs: --confirm {self.config.global_cluster_id}"]
        if failback:
            notes.append(f"{target} is fenced in the state file: this is a failback and needs --rebuild-confirmed")
        if state["writer_region"] == target and not run:
            notes.append(f"state already shows {target} as the writer: execute would be a no-op")
        if run and not resumable:
            notes.append(f"run {run['run_id']} ({run['mode']} -> {run['target']}) is unfinished: "
                         f"execute for a different target or mode is refused")
        if mode == "unplanned":
            notes.append("unplanned mode loses writes not yet replicated; prefer planned whenever the source is healthy")
        return Plan(mode, source, target, failback, steps, notes, resumable["run_id"] if resumable else None)

    # -- execute ----------------------------------------------------------------

    def execute(self, mode: str, confirm: str, target: Optional[str] = None,
                rebuild_confirmed: bool = False) -> RunResult:
        if mode not in MODES:
            raise FailoverError(f"mode must be one of {MODES}")
        state = self._load()
        source, target = self._resolve(state, target)

        if confirm != self.config.global_cluster_id:
            msg = (f"confirm token {confirm!r} does not match the global cluster id "
                   f"{self.config.global_cluster_id!r}")
            self._log("refused", mode=mode, source=source, target=target, status="confirm-mismatch", detail=msg)
            raise ConfirmationError(msg)

        run = state.get("run")
        if run:
            promoted = run["steps"].get("promote-target", {}).get("status") in FINISHED
            if run["target"] != target:
                if promoted:
                    msg = (f"split brain refused: unfinished run {run['run_id']} already promoted "
                           f"{run['target']}; promoting {target} too would create two writers. "
                           f"Resume that run (execute --mode {run['mode']} --target {run['target']}) instead")
                    self._log("refused", mode=mode, source=source, target=target, status="split-brain", detail=msg)
                    raise SplitBrainRefused(msg)
                msg = (f"run {run['run_id']} ({run['mode']} -> {run['target']}) is unfinished; "
                       f"resume it, or abandon it by hand in the state file after checking nothing was changed")
                self._log("refused", mode=mode, source=source, target=target, status="run-conflict", detail=msg)
                raise RunConflict(msg)
            if run["mode"] != mode:
                msg = (f"run {run['run_id']} was started in {run['mode']} mode; resume it in the same mode "
                       f"(steps already taken depend on it)")
                self._log("refused", mode=mode, source=source, target=target, status="run-conflict", detail=msg)
                raise RunConflict(msg)
            self._log("run_resumed", run=run, detail=f"resuming at {self._next_step(run)}")
            self.progress(f"Resuming run {run['run_id']} at step {self._next_step(run)}")
        else:
            if state["writer_region"] == target:
                msg = f"state already shows {target} as the writer (epoch {state['epoch']}); nothing to do"
                self._log("noop", mode=mode, source=source, target=target, detail=msg)
                self.progress(msg)
                return RunResult(None, mode, source, target, noop=True)

            failback = target in state["fenced"]
            if failback and not rebuild_confirmed:
                msg = (f"failback refused: {target} is fenced. Confirm its database is a healthy secondary of "
                       f"{source} (after a planned switchover it already is; after an unplanned failover it "
                       f"must be rebuilt, runbooks/failback.md), then re-run with --rebuild-confirmed")
                self._log("refused", mode=mode, source=source, target=target, status="failback", detail=msg)
                raise FailbackRefused(msg)

            writers = self.a.db.writers()
            unfenced = [w for w in writers if w not in state["fenced"]]
            if len(unfenced) > 1:
                msg = (f"split brain refused: {', '.join(unfenced)} accept writes and none is fenced. "
                       f"Stop writes in one of them and fence it before failing over")
                self._log("refused", mode=mode, source=source, target=target, status="split-brain", detail=msg)
                raise SplitBrainRefused(msg)

            now = self.clock()
            run = {
                "run_id": f"{now.strftime('%Y%m%dT%H%M%SZ')}-{mode}-{target}",
                "mode": mode,
                "source": source,
                "target": target,
                "failback": failback,
                "status": "in_progress",
                "started_at": _iso(now),
                "actor": self.actor,
                "steps": {},
            }
            state["run"] = run
            self.store.save(state)
            self._log("run_started", run=run, detail="failback" if failback else "")
            self.progress(f"Run {run['run_id']}: {mode} {'failback' if failback else 'failover'} {source} -> {target}")

        result = RunResult(run["run_id"], mode, source, target)
        handlers = {
            "precheck": self._precheck,
            "fence-source": self._fence,
            "promote-target": self._promote,
            "scale-target": self._scale,
            "flip-dns": self._flip_dns,
            "postcheck": self._postcheck,
        }
        total = len(STEP_IDS)
        for i, sid in enumerate(STEP_IDS, 1):
            prior = run["steps"].get(sid, {})
            if prior.get("status") in FINISHED:
                self._log("step_resume_skip", run=run, step=sid, status=prior["status"],
                          detail="already finished in an earlier attempt")
                self.progress(f"[{i}/{total}] {sid:<15} {prior['status']} earlier: {prior.get('detail', '')}")
                result.steps.append((sid, prior["status"], prior.get("detail", "")))
                continue

            self._log("step_started", run=run, step=sid)
            try:
                outcome = handlers[sid](state, run)
            except PrecheckFailed as exc:
                # Nothing has changed yet: abandon the run so a different
                # mode (or a later attempt) can start cleanly.
                run["status"] = "aborted"
                run["steps"][sid] = {"status": "failed", "at": _iso(self.clock()), "detail": str(exc)}
                state["history"].append(run)
                state["run"] = None
                self.store.save(state)
                self._log("step_failed", run=run, step=sid, status="failed", detail=str(exc))
                self._log("run_aborted", run=run, detail="precheck failed; nothing was changed")
                self.progress(f"[{i}/{total}] {sid:<15} FAILED: {exc}")
                raise
            except Exception as exc:
                run["status"] = "failed"
                run["failed_step"] = sid
                run["steps"][sid] = {"status": "failed", "at": _iso(self.clock()), "detail": str(exc)}
                self.store.save(state)
                self._log("step_failed", run=run, step=sid, status="failed", detail=str(exc))
                self.progress(f"[{i}/{total}] {sid:<15} FAILED: {exc}")
                if isinstance(exc, StepFailed):
                    raise
                raise StepFailed(f"step {sid} failed: {exc}. Fix the cause and re-run the same "
                                 f"execute command to resume at this step") from exc

            run["status"] = "in_progress"
            run.pop("failed_step", None)
            run["steps"][sid] = {"status": outcome.status, "at": _iso(self.clock()), "detail": outcome.detail}
            self.store.save(state)
            self._log("step_" + ("completed" if outcome.status == "done" else "skipped"), run=run, step=sid,
                      status=outcome.status, detail=outcome.detail, epoch=state["epoch"])
            self.progress(f"[{i}/{total}] {sid:<15} {outcome.status}: {outcome.detail}")
            result.steps.append((sid, outcome.status, outcome.detail))

        run["status"] = "completed"
        run["completed_at"] = _iso(self.clock())
        if run.get("failback"):
            state["fenced"].pop(target, None)
        state["history"].append(run)
        state["run"] = None
        self.store.save(state)
        self._log("run_completed", run=run, epoch=state["epoch"],
                  detail=f"{target} is the writer (epoch {state['epoch']}); {source} is fenced")
        self.progress(f"Completed: {target} is the writer (epoch {state['epoch']}); {source} is fenced")
        return result

    @staticmethod
    def _next_step(run: dict[str, Any]) -> str:
        for sid in STEP_IDS:
            if run["steps"].get(sid, {}).get("status") not in FINISHED:
                return sid
        return "end"

    # -- steps ------------------------------------------------------------------

    def _precheck(self, state: dict[str, Any], run: dict[str, Any]) -> StepOutcome:
        source, target, mode = run["source"], run["target"], run["mode"]
        th = self.a.health.check(target)
        if not th.healthy:
            raise PrecheckFailed(f"{target} is not healthy ({th.detail}); failing over would move traffic "
                                 f"to a broken region")
        sh = self.a.health.check(source)
        gc = self.a.db.global_cluster()
        if target not in gc.members or gc.writer_region == target:
            hint = " (failback: it has not been rebuilt as a secondary yet)" if run.get("failback") else ""
            raise PrecheckFailed(f"{target} is not a secondary of global cluster {self.config.global_cluster_id}{hint}")
        if gc.writer_region != source:
            raise PrecheckFailed(f"global writer is {gc.writer_region}, expected {source}")
        lag = self.a.db.replication_lag_seconds(target)
        limit = self.config.max_replication_lag_seconds
        if mode == "planned":
            if not sh.healthy:
                raise PrecheckFailed(f"{source} is not healthy ({sh.detail}); a planned switchover needs "
                                     f"both regions. Use --mode unplanned if {source} is really down")
            if lag is None:
                raise LagTooHigh(f"replication lag into {target} is unknown; planned mode needs it below {limit:g}s")
            if lag >= limit:
                raise LagTooHigh(f"replication lag into {target} is {lag:.1f}s, at or above the {limit:g}s "
                                 f"threshold; wait for it to drop or investigate before switching over")
            return StepOutcome("done", f"{target} healthy, {source} healthy, writer {source}, "
                                       f"lag {lag:.1f}s < {limit:g}s")
        if sh.healthy:
            raise PrecheckFailed(f"{source} is healthy; an unplanned failover would discard un-replicated "
                                 f"writes for nothing. Use --mode planned")
        run["rpo_exposure_seconds"] = lag
        return StepOutcome("done", f"{target} healthy, {source} {'unreachable' if not sh.reachable else 'unhealthy'} "
                                   f"({sh.detail}), writer {source}, last known lag {_fmt_lag(lag)} "
                                   f"(potential data loss)")

    def _fence(self, state: dict[str, Any], run: dict[str, Any]) -> StepOutcome:
        source, mode = run["source"], run["mode"]
        record = {"at": _iso(self.clock()), "run_id": run["run_id"], "mode": mode}
        try:
            self.a.workload.set_scale(source, workers=0)
        except Unreachable as exc:
            if mode == "planned":
                raise StepFailed(f"cannot fence {source} in planned mode: {exc}") from exc
            record["workers_confirmed_zero"] = False
            state["fenced"][source] = record
            return StepOutcome("skipped", f"{source} EKS API unreachable ({exc}); workers NOT confirmed at 0. "
                                          f"{source} marked fenced: scale its workers to 0 before it rejoins "
                                          f"(runbooks/unplanned-failover.md, 'Fence later')")
        record["workers_confirmed_zero"] = True
        state["fenced"][source] = record
        return StepOutcome("done", f"workers in {source} scaled to 0; {source} marked fenced")

    def _promote(self, state: dict[str, Any], run: dict[str, Any]) -> StepOutcome:
        target, mode = run["target"], run["mode"]
        gc = self.a.db.global_cluster()
        cluster = self.config.regions[target].cluster_id
        if mode == "planned":
            if gc.writer_region == target:
                detail = f"{target} was already the global writer (resumed after the switchover)"
            else:
                self.a.db.switchover(target)
                detail = f"managed switchover complete: {cluster} is the global writer"
        else:
            if target in self.a.db.writers() and target not in gc.members:
                detail = f"{cluster} was already detached and writable (resumed after promotion)"
            else:
                self.a.db.detach_and_promote(target)
                detail = (f"{cluster} detached from {self.config.global_cluster_id} and promoted; "
                          f"RPO exposure was {_fmt_lag(run.get('rpo_exposure_seconds'))}")
        if target not in self.a.db.writers():
            raise StepFailed(f"{target} does not accept writes after promotion")
        if state["writer_region"] != target:
            state["writer_region"] = target
            state["epoch"] += 1
        run["epoch"] = state["epoch"]
        return StepOutcome("done", f"{detail}; epoch {state['epoch']}")

    def _scale(self, state: dict[str, Any], run: dict[str, Any]) -> StepOutcome:
        target = run["target"]
        rc = self.config.regions[target]
        self.a.workload.set_scale(target, api_min_replicas=rc.active_api_min_replicas, workers=rc.active_workers)
        got = self.a.workload.get_scale(target)
        if got.api_min_replicas < rc.active_api_min_replicas or got.workers < rc.active_workers:
            raise StepFailed(f"{target} reports api_min={got.api_min_replicas}, workers={got.workers} after scaling")
        return StepOutcome("done", f"{target}: API min replicas {got.api_min_replicas}, workers {got.workers}")

    def _flip_dns(self, state: dict[str, Any], run: dict[str, Any]) -> StepOutcome:
        target, source = run["target"], run["source"]
        active = self.a.dns.active_region()
        if active is None:
            return StepOutcome("skipped", "no failover records yet (bootstrap phase 1): nothing to flip")
        if active == target:
            return StepOutcome("done", f"{target} was already PRIMARY")
        self.a.dns.set_active(target)
        if self.a.dns.active_region() != target:
            raise StepFailed("Route 53 change did not take effect")
        return StepOutcome("done", f"{target} is PRIMARY, {source} is SECONDARY")

    def _postcheck(self, state: dict[str, Any], run: dict[str, Any]) -> StepOutcome:
        target, source = run["target"], run["source"]
        problems: list[str] = []
        notes: list[str] = []
        h = self.a.health.check(target)
        if not h.healthy:
            problems.append(f"{target} unhealthy ({h.detail})")
        writers = self.a.db.writers()
        if target not in writers:
            problems.append(f"{target} is not a writer")
        others = [w for w in writers if w != target and w not in state["fenced"]]
        if others:
            problems.append(f"unfenced second writer: {', '.join(others)}")
        active = self.a.dns.active_region()
        if active is not None and active != target:
            problems.append(f"DNS PRIMARY is {active}")
        rc = self.config.regions[target]
        got = self.a.workload.get_scale(target)
        if got.workers < rc.active_workers:
            problems.append(f"{target} has {got.workers} workers, expected {rc.active_workers}")
        try:
            src = self.a.workload.get_scale(source)
            if src.workers != 0:
                problems.append(f"{source} still runs {src.workers} workers")
        except Unreachable:
            notes.append(f"{source} unreachable: its workers are unverified")
        if problems:
            raise PostcheckFailed("post-checks failed: " + "; ".join(problems))
        detail = f"{target} healthy, writer, {'PRIMARY' if active else 'no DNS yet'}, {got.workers} workers"
        if notes:
            detail += "; " + "; ".join(notes)
        return StepOutcome("done", detail)

    # -- status -----------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        state = self._load()
        gc = self.a.db.global_cluster()
        writers = self.a.db.writers()
        active = self.a.dns.active_region()
        regions = []
        warnings: list[str] = []
        for name in (self.config.primary_region, self.config.dr_region):
            h = self.a.health.check(name)
            if name in gc.members:
                db_role = "writer (global)" if gc.writer_region == name else "secondary (global)"
            elif name in writers:
                db_role = "writer (detached)"
            else:
                db_role = "not attached"
            try:
                sc = self.a.workload.get_scale(name)
                workers, api_min = sc.workers, sc.api_min_replicas
            except Unreachable:
                workers, api_min = None, None
            fenced = state["fenced"].get(name)
            regions.append({
                "region": name,
                "deploy_role": "primary" if name == self.config.primary_region else "dr",
                "health": "healthy" if h.healthy else ("unhealthy" if h.reachable else "unreachable"),
                "health_detail": h.detail,
                "db_role": db_role,
                "replication_lag_seconds": self.a.db.replication_lag_seconds(name) if db_role.startswith("secondary") else None,
                "dns": ("PRIMARY" if active == name else "SECONDARY") if active else "n/a",
                "workers": workers,
                "api_min_replicas": api_min,
                "fenced": bool(fenced),
            })
            if h.healthy is False and name == gc.writer_region and not fenced:
                warnings.append(f"the writer region {name} is {'unhealthy' if h.reachable else 'unreachable'}: "
                                f"declare or rule out an incident before acting (runbooks/unplanned-failover.md)")
            if fenced and workers:
                warnings.append(f"{name} is fenced but runs {workers} workers: scale them to 0 now")
            if fenced and not fenced.get("workers_confirmed_zero", True) and workers is None:
                warnings.append(f"{name} is fenced but its workers were never confirmed at 0 (unreachable)")
            if fenced and name in writers:
                warnings.append(f"{name} is fenced but its cluster still accepts writes: rebuild it as a "
                                f"secondary before it rejoins (runbooks/failback.md)")
        unfenced = [w for w in writers if w not in state["fenced"]]
        if len(unfenced) > 1:
            warnings.append(f"SPLIT BRAIN: {', '.join(unfenced)} accept writes and none is fenced")
        run = state.get("run")
        if run:
            warnings.append(f"run {run['run_id']} is unfinished ({run['status']}) at step {self._next_step(run)}; "
                            f"re-run the same execute command to resume")
        if active and active != state["writer_region"] and not run:
            warnings.append(f"DNS PRIMARY is {active} but the state's writer is {state['writer_region']}")
        return {
            "global_cluster_id": self.config.global_cluster_id,
            "record_name": self.config.record_name,
            "global_writer": gc.writer_region,
            "writers": writers,
            "dns_primary": active,
            "state_writer": state["writer_region"],
            "epoch": state["epoch"],
            "regions": regions,
            "warnings": warnings,
        }
