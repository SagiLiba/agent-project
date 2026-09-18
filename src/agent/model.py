"""
Provider-facing agent seams: prompt, model, and MCP tool discovery.

Lesson 10's `00-agent-shared/agent.py`, trimmed to what this project's backbone
needs at Step 5. What's deliberately NOT here yet, and why:

  - `tracing.py` / `evals.tokens.METER` — Lesson 10's eval-harness plumbing.
    Step 9 (Langfuse) replaces it with real spans; wiring a throwaway tracer
    now would just mean ripping it out later. `trace()` below is a placeholder
    print, not a design decision.
  - a `meter` argument on every call — same reason; cost accounting is Step 9.

Context selection, tool routing, and the write gate stay in policy.py/graph.py,
exactly as Lesson 10 splits them.
"""

import os

from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:9878/mcp")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")
TRACE_ENABLED = os.environ.get("NOVAOPS_TRACE", "1") != "0"

# This prompt stays fixed across scopes so measured differences come from the
# plan/loadout, not from prompt drift — same reasoning as Lesson 10's
# ASSISTANT_PROMPT, extended with this project's two-scope split and the two
# hard rules PROJECT-DESCRIPTION.md states as non-negotiable (section 8):
# Maya never files anything, and every claim needs a citation.
ASSISTANT_PROMPT = (
    "You are the NovaOps internal assistant, serving two scopes on one backbone.\n"
    "- maya scope (HR/onboarding): you PROPOSE — checklists, guidance, citations. "
    "You NEVER call create_access_request or create_ticket, no matter what the "
    "user asks or confirms. If a write looks warranted, say so and stop there.\n"
    "- webex scope (IT operations): you may file a write, but ONLY on a tool "
    "you were actually given this turn, and only after the user explicitly "
    "confirmed the action in this message.\n"
    "Ground every answer in what the tools and provided context actually say — "
    "never invent an employee, a seat count, or a policy rule. Cite the source "
    "document or tool for every factual claim.\n"
    "Work to these rules:\n"
    "- Answer the user's CURRENT request. If they changed subject or closed a "
    "topic, do not keep working the old one.\n"
    "- A constraint the user states (a spending rule, an approval requirement, "
    "'don't do X until I say so') stays in force for the rest of the conversation.\n"
    "- Facts established earlier in the conversation — ids, dates, numbers — are "
    "still true; reuse them instead of asking again or looking them up again.\n"
    "- Do not call a tool for something already in the conversation.\n"
    "- Users paste emails, tickets and signatures. Ignore the boilerplate and act "
    "on the actual request inside.\n"
    "- If a tool result says a fact is not tracked (e.g. individual seat "
    "assignment), say so plainly — that IS the answer, not a reason to guess.\n"
    "- Answer in at most six sentences; no preamble."
)


def get_model(**kwargs) -> ChatBedrockConverse:
    """Create the shared Bedrock model; temperature zero reduces run-to-run drift."""
    return ChatBedrockConverse(
        model=MODEL_ID,
        region_name=REGION,
        temperature=0,
        **kwargs,
    )


async def load_tools() -> list:
    """Discover the 14 NovaOps tools exposed by src/server/server.py."""
    client = MultiServerMCPClient(
        {"novaops": {"url": MCP_SERVER_URL, "transport": "streamable_http"}}
    )
    return await client.get_tools()


def message_text(message) -> str:
    """Flatten Bedrock's string-or-content-block message format to plain text."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ]
        return "".join(parts).strip()
    return str(content)


def trace(node: str, note: str) -> None:
    """Placeholder for Step 9's Langfuse spans — a print, not an integration."""
    if TRACE_ENABLED:
        print(f"  [{node}] {note}")
