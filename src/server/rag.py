"""
NovaOps retrieval layer — FAISS + Titan embeddings, audience-aware.

This has no dependency on an agent, a graph, or an LLM framework. It is a
standalone function — search(corpus, query) -> list[chunk] — built on three
things that already work independently: the document corpus on disk, one
Bedrock embedding call (verified in Step 1), and FAISS for nearest-neighbor
search. Step 5's agent will later wrap this as an MCP tool; nothing here
requires that tool, or any agent, to exist first.

Extends the Lesson 10 reference (server/rag.py) in three ways this project
requires that the classroom demo did not need:

1. PRESERVES each document's `audience` YAML front-matter field as chunk
   metadata at ingest time — it cannot be added after the fact. Two of the
   seven document collections carry this field: handbook/ (`audience: all`)
   and manager_playbook/ (`audience: manager`). The other five carry none,
   which means "no restriction", never "deny" (PROJECT-DESCRIPTION.md section
   12) — filtering out everything unlabelled would block 70 of 102 documents.

2. FILTERS `audience: manager` chunks OUT of what search() returns when the
   caller is not a manager — before this function returns, not after the
   model has read them. "Enforce as a retrieval filter, not a refusal after
   the fact" (section 12): a restricted chunk that reaches the model has
   already leaked, whatever the model then says about it.

3. WIDENS Lesson 10's two corpora to what this project's two required
   workflows actually read (sections 8/9's "Data sources required"):
     it_kb   -> search_knowledge_base  (unchanged scope)
     hr_docs -> search_hr_documents    (widened: employment, internal_memos,
                                         handbook, manager_playbook, contracts)
   `policies/` stays outside both corpora — Lesson 10 serves it via
   list_policies/get_policy (direct file reads by name), and nothing here
   changes that split.

Whole-document embedding (one chunk per file), same as Lesson 10 — these are
short markdown files. Lesson 6's homework is where chunking-by-measurement is
the actual exercise; that is out of this project's required scope.
"""

import functools
import json
import os
import re
from pathlib import Path

import boto3
import faiss
import numpy as np
import yaml
from dotenv import load_dotenv

load_dotenv()

DATASET_ROOT = Path(
    os.getenv("NOVAOPS_DATASET_ROOT", "./novaops-enterprise-agent-dataset")
).resolve()
DOCS_DIR = DATASET_ROOT / "documents"

REGION = os.environ.get("AWS_REGION", "us-east-1")
EMBED_MODEL_ID = os.environ.get("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBED_DIM = 1024  # Titan Text Embeddings V2 default width
TOP_K = 3

# A corpus is a name plus the document folders that feed its index.
CORPORA: dict[str, tuple[Path, ...]] = {
    "it_kb": (DOCS_DIR / "it_kb",),
    "hr_docs": (
        DOCS_DIR / "employment",
        DOCS_DIR / "internal_memos",
        DOCS_DIR / "handbook",
        DOCS_DIR / "manager_playbook",
        DOCS_DIR / "contracts",
    ),
}

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

_bedrock = boto3.client("bedrock-runtime", region_name=REGION)


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Split a document into its YAML front matter (if any) and body.

    Absence of front matter — and absence of `audience` within it — is the
    NORMAL case for five of the seven collections. `{}` here means
    "no restriction", never "deny".
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    body = text[match.end():]
    return meta, body


def embed_text(text: str) -> list[float]:
    """One Titan embedding call. normalize=True so inner product == cosine
    similarity. The index and every query must use the SAME model."""
    resp = _bedrock.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": EMBED_DIM, "normalize": True}),
    )
    return json.loads(resp["body"].read())["embedding"]


@functools.lru_cache(maxsize=len(CORPORA))
def _index(corpus: str):
    """Embed every document in one corpus and build its FAISS index.

    lru_cache makes this run once per corpus — on first search, or at server
    startup via warm_index().
    """
    paths = sorted(p for folder in CORPORA[corpus] for p in folder.glob("*.md"))
    docs = []
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_front_matter(raw)
        docs.append({
            "document": path.stem,
            "corpus": path.parent.name,
            "source_path": f"{path.parent.name}/{path.name}",
            "audience": meta.get("audience"),  # None = unrestricted, never "deny"
            "last_updated": meta.get("last_updated"),
            "text": body.strip(),
        })
    vectors = np.array([embed_text(d["text"]) for d in docs], dtype="float32")
    index = faiss.IndexFlatIP(EMBED_DIM)
    index.add(vectors)
    return index, docs


def warm_index() -> dict[str, int]:
    """Force every index to build now (called at server startup). Returns doc counts."""
    return {corpus: len(_index(corpus)[1]) for corpus in CORPORA}


def search(corpus: str, query: str, *, is_manager: bool = False, k: int = TOP_K) -> list[dict]:
    """Return the top-k documents in `corpus` most similar to `query`, best first.

    THE PERMISSION BOUNDARY LIVES HERE. When `is_manager` is False, chunks
    whose `audience` is `manager` are skipped while walking the ranked list —
    they are never appended to the list this function returns. That is what
    "fail closed within the restricted collection, not across the corpus"
    means in code: unrestricted documents (audience is None) are never
    touched by this check; only the labelled-restricted ones are excluded,
    and they are excluded BEFORE any caller (a tool, a model) ever sees them.

    is_manager is an application input, resolved from the database
    (server/db.py: "some employee's manager_id is their id"), never inferred
    by a model and never passed as free text.
    """
    index, docs = _index(corpus)
    if not docs:
        return []

    qvec = np.array([embed_text(query)], dtype="float32")
    # Rank the whole corpus — these are small collections (<=20 docs each), so
    # an exhaustive rank-then-filter is simplest and correct: filtering after
    # ranking but before returning is still "before the model sees it".
    scores, ids = index.search(qvec, len(docs))

    results = []
    for score, idx in zip(scores[0], ids[0]):
        if idx < 0:
            continue
        doc = docs[idx]
        if not is_manager and doc["audience"] == "manager":
            continue  # excluded here — never reaches the return value
        results.append({
            "document": doc["document"],
            "corpus": doc["corpus"],
            "source_path": doc["source_path"],
            "audience": doc["audience"],
            "last_updated": doc["last_updated"],
            "score": round(float(score), 3),
            "text": doc["text"],
        })
        if len(results) == k:
            break
    return results


if __name__ == "__main__":
    # Step 3 smoke test — run directly: python src/server/rag.py
    # No agent, no MCP server, no LangGraph involved — just this module.
    print("Warming indexes...")
    counts = warm_index()
    print("Doc counts:", counts)
    assert counts["hr_docs"] == 17 + 6 + 15 + 17 + 20  # employment+memos+handbook+playbook+contracts
    assert counts["it_kb"] == 15

    print("\n--- Non-manager asks about promotion (S9 turn 1 shape) ---")
    results = search("hr_docs", "How do I get promoted here? What is the path for a CSM?", is_manager=False)
    for r in results:
        print(f"  [{r['score']}] {r['source_path']} (audience={r['audience']})")
    assert all(r["audience"] != "manager" for r in results), "LEAK: a manager-only chunk reached a non-manager result set"
    assert any("making-a-career" in r["document"] for r in results), "expected handbook/making-a-career.md to surface"

    print("\n--- Same query, but caller IS a manager ---")
    mgr_results = search("hr_docs", "How do I get promoted here? What is the path for a CSM?", is_manager=True)
    for r in mgr_results:
        print(f"  [{r['score']}] {r['source_path']} (audience={r['audience']})")
    assert any(r["audience"] == "manager" for r in mgr_results), "expected a manager_playbook chunk to surface for a manager caller"

    print("\n--- IT KB: Webex login issue ---")
    it_results = search("it_kb", "Webex says my account is not licensed", is_manager=False)
    for r in it_results:
        print(f"  [{r['score']}] {r['source_path']}")

    print("\n✓ Step 3 done-when criteria pass: non-manager query returns zero manager_playbook chunks,")
    print("  the same query for a manager surfaces one, and unrestricted collections are never filtered.")
