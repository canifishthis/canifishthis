# T1274 — The hangup test fails when the runner was started with nohup

Status: IN PROGRESS — lane test/T1274-gate-tests-under-load (part A); B open.

| id | title | status | commits | what's left |
|---|---|---|---|---|
| T1274 | The hangup test fails when the runner was started with nohup | IN PROGRESS | — | A in its PR; then: nohup guard for heavy.sh / before_pr (item 3), diagnose the WaterScreen render-test timeouts (B) |

Source: three chats, 2026-11-28 (before_pr failures on unrelated branches); the cause of A found by another chat the
same night and reproduced in this lane.

## A. `test_app_dev_hangup_stops_every_server_process` (cause found, fixed here)
- Seen: failed in two before_pr runs on unrelated branches (one a ticket file only) with `TimeoutExpired` at 13 s
  (`communicate(timeout=wait_s + 5)`, `pipeline/tests/test_makefile.py`); alone it passes in ~1.6 s.
- Cause: not load. Those runs were detached with `nohup`, which sets SIGHUP to ignored; every child inherits it, and
  bash cannot trap a signal ignored on entry, so `scripts/app-dev.sh` ignored the test's hang-up and never exited.
  Reproduced on origin/main 0c6453995: plain 3/3 pass (1.55 s); under `nohup` 2/2 `TimeoutExpired` at 13.13 s.
- Fix (test only, no timeout raised, no polling): the child starts with SIGHUP, SIGINT and SIGTERM at their default
  (`preexec_fn=_signals_at_default`), so the test no longer depends on how its runner was launched.
- Other tests: only `test_makefile.py` sends a real signal to a child that traps it; `test_mutation_report.py`'s
  SIGINT test fakes `Popen` and `killpg`.

## B. WaterScreen render tests time out under load (open, not touched here)
- Seen: two render tests in `app/packages/ui-native/src/WaterScreen.sources.test.tsx` hit their 40 s timeout, plus a
  vitest "Timeout calling onTaskUpdate", in before_pr runs of two unrelated branches at the same hour; both passed on
  rerun. Not reproduced here (the app suite was not run).
- Cheap look: each `it.each(CASES)` case renders the whole WaterScreen over the fixture release in jsdom, opens every
  fold and presses every press target (`pressedSheets`), with `waitFor` at 20 s (`LOADED`) inside a 40 s test. The
  onTaskUpdate timeout is the main-process starvation T1041 met (`app/vitest.config.ts` maxWorkers = half the cores).
  Not checked: whether those runs were also under nohup (no signal is involved in B, so likely not the cause).

## Work
1. (this PR) A: the test resets the signals for its child.
2. B: time each CASES case alone and under a CPU hog; find what is slow (fixture open per case, the press-every-target
   walk); a test waits on the condition it checks with a generous overall deadline, or moves out of the loaded tier.
   A lane never just raises a timeout to get green.
3. Guard the nohup hole at the runner: proposed, `scripts/heavy.sh` (and `scripts/before_pr.sh`) refuse to start when
   SIGHUP is ignored on entry, naming the fix ("started under nohup: detach with `cmd > log 2>&1 &` or the agent's
   background run instead"), plus one AGENTS line under rule 18. A refusal, not a restore: bash cannot reset a signal
   ignored on entry (checked: `trap` has no effect, `trap -p` shows nothing), so heavy.sh's own `trap on_stop ... HUP`
   is dead under nohup too; detection needs a child, e.g.
   `python3 -c 'import signal,sys; sys.exit(signal.getsignal(signal.SIGHUP) == signal.SIG_IGN)'`.

## Acceptance
A: under `nohup` the hangup test passes; with app-dev.sh really broken (HUP ignored by the script, or the clean-up
killing only the wrapper PID) it still fails. B: the cases pass beside a CPU hog with no timeout raised. Item 3: a run
under nohup is refused with its fix named; a pinned test.

Depends: none. Size: S. Owner: no. Default: n/a.
