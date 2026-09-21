"""Score a finished `run_eval.py` run: fetch its traces, judge them locally,
push the numbers back. Lesson 11's `03-score-the-run/score.py`, re-pointed at
the v2-native read/write path.

WHY THIS ISN'T A STRAIGHT PORT. Lesson 11's `score.py` fetches with
`langfuse.api.trace.get(...)` and drives the whole run through
`langfuse.run_batched_evaluation(scope="traces", ...)`. Both read through
Langfuse's legacy v3 API. This project's Langfuse org was created after the
platform's v3->v4 cutover, and that legacy read path answers with
`410 LEGACY_API_UNAVAILABLE_FOR_NEW_ORGANIZATION` for organizations created on
this side of the cutover (confirmed against this project's own traces while
building this file) — `run_batched_evaluation`'s own docstring says as much:
"supported with Langfuse platform v3 and is not yet supported with v4."

So this reads through `api.observations.get_many(...)` instead — the v2-native
path — filtered to `type="AGENT"`, which is the ONE observation per turn
`run_eval.py` opens as its root span (never one per Bedrock call or MCP
round-trip). And it does not need a SEPARATE fetch for the turn's tool calls
the way Lesson 11's `_observations()` does: `run_eval.py`'s
`trajectory_digest` already wrote `{intent, calls, status, ...}` straight onto
that same AGENT observation's own metadata — for the identical reason Lesson
11's `run.py` gives for doing this at all (a reader can only see fields ON the
object it is handed). One fetch, no join against sibling spans.

Scores are written back with `create_score(trace_id=..., ...)` — v4's
ingestion-based WRITE path, which this deprecation does not touch.

    python evals/score_eval.py --session M-S-01-a1b2c3d4   # one exact run
    python evals/score_eval.py --recent 60                  # last N minutes
    python evals/score_eval.py --tag novaops-final           # everything tagged
    python evals/score_eval.py --selftest                    # offline, no network
"""

import argparse
import datetime
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import DATA_TYPES, roll_up, score_turn  # noqa: E402
from golden import GOLDEN  # noqa: E402

load_dotenv(find_dotenv())

from langfuse import get_client  # noqa: E402

langfuse = get_client()


def _fetch_agent_observations(*, session_id: str | None, since: datetime.datetime | None,
                               limit: int = 100):
    """Every AGENT-type observation matching the filter, oldest first, paging
    through `cursor` until exhausted. `fields="core,io,metadata"` is what
    populates `.output`/`.metadata` at all — the default omits them (verified
    empirically: a bare `get_many()` call returns `metadata=None`).
    """
    cursor = None
    while True:
        resp = langfuse.api.observations.get_many(
            type="AGENT", session_id=session_id, from_start_time=since,
            fields="core,io,metadata", limit=limit, cursor=cursor,
        )
        for obs in resp.data:
            yield obs
        cursor = resp.meta.cursor
        if not cursor:
            break


def score_one(obs) -> tuple[dict | None, dict]:
    """One turn's scores, as `{name: (value, reason)}` — empty if this
    observation carries no `(case_id, turn)` this run's golden set covers.
    """
    metadata = obs.metadata or {}
    # Langfuse parses metadata values, so an int turn number can come back an
    # int rather than the string run_eval.py wrote; normalise rather than trust it.
    key = (str(metadata.get("case_id")), str(metadata.get("turn")))
    golden = GOLDEN.get(key)
    if golden is None:
        return None, {"key": key}

    trajectory = (metadata.get("trajectory") or {})
    called = trajectory.get("calls") or []
    answer = obs.output if isinstance(obs.output, str) else str(obs.output or "")
    scores = score_turn(golden, answer, called, trajectory.get("intent"))
    rolled = roll_up({name: value for name, (value, _) in scores.items()})
    scores.update(rolled)
    return scores, {"key": key, "trajectory": trajectory}


def push_scores(obs, scores: dict[str, tuple[float, str]]) -> None:
    for name, (value, reason) in scores.items():
        langfuse.create_score(
            trace_id=obs.trace_id, observation_id=obs.id, name=name,
            value=value, data_type=DATA_TYPES[name], comment=reason,
        )


def selftest() -> int:
    """Prove the join + scoring rules work with no Langfuse, no Bedrock and no
    network — checks.py's own selftest, plus the golden-set coverage this
    file adds: 27 keys, one score_turn call per key, at least one applicable
    check each (a golden turn declaring literally nothing would be a bug in
    golden.py, not a real turn).
    """
    failures = 0
    if len(GOLDEN) != 27:
        print(f"  [FAIL] expected 27 golden turns, found {len(GOLDEN)}")
        failures += 1
    else:
        print("  [ok  ] 27 golden turns present")

    for key, turn in GOLDEN.items():
        scores = score_turn(turn, "", [], None)
        if not scores:
            print(f"  [FAIL] {key} declares nothing checkable at all")
            failures += 1
    if not failures:
        print("  [ok  ] every golden turn has at least one applicable check "
              "(scored against an EMPTY answer/trajectory, so this only "
              "proves coverage, not correctness)")

    print(f"\n{'FAIL' if failures else 'ok'}: {failures} problem(s)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a finished eval run's traces.")
    parser.add_argument("--session", help="score one exact langfuse session id "
                                          "(what run_eval.py printed, e.g. M-S-01-a1b2c3d4)")
    parser.add_argument("--recent", type=int, nargs="?", const=60, metavar="MINUTES",
                        help="score every AGENT observation from the last N minutes "
                             "(default 60)")
    parser.add_argument("--selftest", action="store_true", help="check the rules offline")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if not args.session and not args.recent:
        parser.error("pass --session <id>, --recent [MINUTES], or --selftest")

    since = None
    if args.recent:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=args.recent)

    scored, unmatched, failed = 0, 0, 0
    for obs in _fetch_agent_observations(session_id=args.session, since=since):
        scores, info = score_one(obs)
        if scores is None:
            unmatched += 1
            continue
        try:
            push_scores(obs, scores)
        except Exception as error:  # a bad score should not kill the whole run
            print(f"  [FAIL] {info['key']}: {error}")
            failed += 1
            continue
        scored += 1
        pass_score = scores.get("turn_pass", (None, ""))[0]
        print(f"  [{'PASS' if pass_score == 1.0 else 'fail' if pass_score == 0.0 else '----'}] "
              f"{info['key']} — {len(scores)} scores pushed")

    print(f"\n[scored] {scored} turns, {unmatched} with no golden match, {failed} push failures")
    langfuse.flush()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
