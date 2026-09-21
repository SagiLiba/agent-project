"""Register three LLM-as-a-judge evaluators in Langfuse, and the rules that
fire them — Lesson 11 exercise `04-llm-judge/evaluator-judges.py`, ported
as-is (its config-write endpoints are unaffected by the v3-read deprecation
`score_eval.py`'s docstring explains; this file never reads a trace or
observation, only writes evaluator/rule config).

    main() -> build each payload -> create the evaluator -> attach its rule

`score_eval.py`'s deterministic checks run on YOUR machine because they need
GOLDEN-DATASETS.json. These three run on LANGFUSE'S servers: register a
rubric and a firing rule once, and every matching observation afterward is
judged automatically — including runs nobody thought to score.

    faithfulness   is every claim in the answer supported by evidence the
                   assistant actually had this turn or established earlier?
                   Section 6.5's own rule — "must never state that access was
                   granted" — is exactly a faithfulness question: an
                   AccessDecision claiming a grant has nothing behind it.
    completeness   does the answer put the whole picture together? This is
                   `W-I-02`'s own test in code: naming only the entitled team
                   members and dropping Noam is a completeness failure the
                   deterministic `fact_recall` check also catches (Noam is a
                   required_fact) — the two are meant to agree.
    correctness    does it satisfy the request AND respect the constraints in
                   force? Section 12's "action_confirmed gates visibility; the
                   approval record gates the write" is a correctness question
                   whenever a stale quoted "go ahead" is in play.

**Before you can `--enable` this file at all**: Langfuse refuses to create an
`llm_as_judge` evaluator it cannot resolve a model for. That means an LLM
Connection with your OWN model credentials, configured once in the Langfuse
UI (Settings -> LLM Connections) — a decision this script will not make for
you, the same way Lesson 11's own script raises rather than guessing.

    python evals/register_judges.py --dry-run   # print payloads, call nothing
    python evals/register_judges.py             # register, rules start PAUSED
    python evals/register_judges.py --enable     # register and start judging
    python evals/register_judges.py --delete     # remove all three
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

SAMPLING = 1.0

# Every judge reads the same four things off the ONE AGENT observation
# run_eval.py opens per turn — the same reason score_eval.py needs no
# separate tool-call fetch: `jsonPath` pulls exactly the slice each rubric
# needs out of `metadata.trajectory`, so a judge never pays prompt tokens on
# OTEL resource attributes, SDK version, or the project's own public key.
MAPPING = [
    {"variable": "request", "source": "input"},
    {"variable": "answer", "source": "output"},
    {"variable": "tool_results", "source": "metadata", "jsonPath": "$.trajectory.calls"},
    {"variable": "state", "source": "metadata", "jsonPath": "$.trajectory.state"},
]

_EVIDENCE = """### The user's request
{{request}}

### What the tools returned this turn
{{tool_results}}

### Established earlier in this conversation
Facts and constraints the assistant carried into this turn. A rule the USER stated has
no tool result behind it and is still valid grounding.
{{state}}

### The assistant's answer
{{answer}}"""

_SCALE = """

SCORING
Return a value from 0.0 to 1.0 in steps of 0.1. If your judgement falls between two
steps, round DOWN — 0.87 becomes 0.8, 0.62 becomes 0.6.
Reserve 1.0 for an answer you found nothing to criticise in. If you name a defect, the
score is below 1.0; do not award 1.0 and then describe a problem.
State the score's reason in at most two sentences, naming the specific claim, omission
or constraint responsible. Do not narrate arithmetic or your deliberation."""

JUDGES = {
    "faithfulness": (
        "You are a strict evaluator scoring FAITHFULNESS — whether the ANSWER is "
        "grounded in evidence the assistant actually had.\n"
        "score = the proportion of the answer's factual claims that are supported.\n"
        "Two sources count as grounding, and they are NOT equal:\n"
        "  - THIS TURN'S TOOL RESULTS are the freshest evidence and always win.\n"
        "  - ESTABLISHED CONTEXT — facts and rules from earlier in the conversation, "
        "including ones the user stated — is valid grounding on its own. A turn that "
        "needed no lookup and answered from context is fully grounded.\n"
        "STALENESS IS UNFAITHFUL: a claim repeating an earlier value that this turn's "
        "tool results contradict or supersede is NOT supported. Fresh evidence "
        "overrides remembered evidence.\n"
        "Claiming an action was taken, or will be taken, with no tool call behind it is "
        "NOT supported — this includes claiming access was GRANTED or ENABLED: this "
        "system's own AccessDecision schema has no such status, and an answer implying "
        "one anyway is unfaithful by definition, not just imprecise.\n"
        "Judge what the answer actually SAYS. Do not deduct for an overstatement the "
        "answer itself already qualifies, and do not invent an implication in order to "
        "penalise it.\n"
        "Score by the evidence alone; ignore whether a claim is true in the real world. "
        "An answer that correctly says the evidence does not cover something is "
        "faithful. A tool result may be truncated — do not penalise a claim merely "
        "because the excerpt stops early." + _SCALE + _EVIDENCE
    ),
    "completeness": (
        "You are a strict evaluator scoring COMPLETENESS — whether the ANSWER puts the "
        "whole picture together, or only part of it.\n"
        "score = the proportion of what this turn required that the answer states.\n"
        "Work from OMISSIONS. Read the request and the evidence, list what a useful "
        "answer to this turn had to contain, then check the answer for each item. An "
        "item present in the tool results and relevant to the request, but absent from "
        "the answer, is a missing part and must lower the score. When a lookup returns "
        "MULTIPLE people or records, every one of them belongs in the answer, including "
        "the unremarkable ones — naming only the interesting subset and silently "
        "dropping the rest is a completeness failure even when every stated claim is true.\n"
        "Accept paraphrase and different formatting of the same fact — '1 August 2026' "
        "and '2026-08-01' are the same fact. Do not credit a fact the answer only "
        "alludes to without stating.\n"
        "Do not penalise the answer for adding relevant context beyond the literal "
        "question, and do not reward padding. Judge coverage, not length." + _SCALE + _EVIDENCE
    ),
    "correctness": (
        "You are a strict evaluator scoring CORRECTNESS of one turn in a support "
        "conversation.\n"
        "  1.0 = satisfies the request and respects every constraint still in force.\n"
        "  0.5 = satisfies the request but mishandles a constraint, or respects the "
        "constraints while only partly answering.\n"
        "  0.0 = misses the request entirely, invents a fact, or ignores a constraint "
        "in a way that would cause real harm.\n"
        "Place the answer between these anchors according to how much damage the flaw "
        "would do to the person relying on it.\n"
        "Be strict about invented specifics and ignored constraints; be lenient about "
        "wording, format and brevity. A constraint can be lifted or satisfied by a "
        "later user message INCLUDING the one being graded — 'do not file until I say "
        "so' is satisfied the moment the user says so, even if that instruction arrives "
        "wrapped in quoted or forwarded text elsewhere in the SAME message; a stale "
        "instruction quoted from an OLDER message never overrides the caller's own "
        "current words. When the request is genuinely ambiguous, asking the user which "
        "they meant is CORRECT and guessing is not." + _SCALE + _EVIDENCE
    ),
}


def _request(method: str, path: str, payload: dict | None = None, unstable: bool = True) -> dict:
    """Call the Langfuse public API with HTTP Basic auth (public key : secret key)."""

    base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
    auth = base64.b64encode(
        f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
    ).decode()
    request = urllib.request.Request(
        f"{base}/api/public{'/unstable' if unstable else ''}{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        method=method,
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:400]
        raise SystemExit(f"Langfuse {method} {path} failed ({error.code}): {detail}")


def _get(path: str, unstable: bool = True) -> dict:
    return _request("GET", path, unstable=unstable)


def model_config() -> dict | None:
    """Which model Langfuse runs these judges on, discovered from the project.

    The judges run on Langfuse's servers, so the model is whatever the
    project's LLM Connection exposes — NOT this repo's own `.env` model id,
    which those servers cannot see.
    """

    connections = _get("/llm-connections?limit=10", unstable=False).get("data", [])
    for connection in connections:
        models = connection.get("customModels") or []
        if models:
            return {"provider": connection["provider"], "model": models[0]}
    return None


def evaluator_payload(name: str, prompt: str, config: dict | None) -> dict:
    payload = {
        "type": "llm_as_judge",
        "name": name,
        "prompt": prompt,
        "outputDefinition": {
            "dataType": "NUMERIC",
            "score": {"description": "A value from 0.0 (worst) to 1.0 (best), per the rubric."},
            "reasoning": {"description": "At most two sentences naming the specific "
                                         "claim, omission or constraint behind the score."},
        },
    }
    if config:
        payload["modelConfig"] = config
    return payload


def rule_payload(name: str, enabled: bool) -> dict:
    return {
        "name": name,
        "evaluator": {"type": "llm_as_judge", "name": name, "scope": "project"},
        # No "trace" target exists — only "observation"/"experiment". run_eval.py
        # opens exactly one AGENT observation per turn (its root span, named
        # "<case_id> · turn <n>"), so filtering to AGENT gives one judgement
        # per turn, never one per Bedrock call or MCP round-trip.
        "target": "observation",
        "enabled": enabled,
        "sampling": SAMPLING,
        "filter": [
            {"type": "stringOptions", "column": "type", "operator": "any of",
             "value": ["AGENT"]}
        ],
        "mapping": MAPPING,
    }


def find(path: str, name: str) -> dict | None:
    for item in _get(f"{path}?limit=100").get("data", []):
        if item.get("name") == name:
            return item
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Register the Langfuse LLM judges.")
    parser.add_argument("--dry-run", action="store_true", help="print payloads, call nothing")
    parser.add_argument("--delete", action="store_true", help="remove the judges and rules")
    parser.add_argument("--enable", action="store_true", help="start judging immediately")
    args = parser.parse_args()

    if args.dry_run:
        config = model_config()
        print(json.dumps(
            {name: {"evaluator": evaluator_payload(name, prompt, config),
                    "evaluation_rule": rule_payload(name, args.enable)}
             for name, prompt in JUDGES.items()},
            indent=2,
        ))
        return 0

    if args.delete:
        for name in JUDGES:
            for path in ("/evaluation-rules", "/evaluators"):
                existing = find(path, name)
                if existing:
                    _request("DELETE", f"{path}/{urllib.parse.quote(existing['id'], safe='')}")
                    print(f"[deleted] {path[1:]:<17} {name}")
                else:
                    print(f"[absent ] {path[1:]:<17} {name}")
        return 0

    config = model_config()
    if not config:
        raise SystemExit(
            "No LLM connection with a custom model in this Langfuse project, so a "
            "judge would have nothing to call.\nSet one up first: Langfuse UI -> "
            "Settings -> LLM Connections -> add a connection with your own model "
            "credentials and at least one custom model. This is a decision (whose "
            "credentials, which model, what it costs), not a formality — this "
            "script will not make it for you."
        )
    print(f"[model  ] {config['provider']} / {config['model']}\n")

    for name, prompt in JUDGES.items():
        if find("/evaluators", name):
            print(f"[exists ] evaluator {name} — delete first to change its rubric")
        else:
            _request("POST", "/evaluators", evaluator_payload(name, prompt, config))
            print(f"[created] evaluator {name}")

        if find("/evaluation-rules", name):
            print(f"[exists ] rule      {name}")
        else:
            _request("POST", "/evaluation-rules", rule_payload(name, args.enable))
            print(f"[created] rule      {name} "
                  f"({'judging new traces' if args.enable else 'PAUSED — rerun with --enable'})")

    print("\nRules only judge observations created AFTER the rule exists — rerun "
          "evals/run_eval.py to see scores appear.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
