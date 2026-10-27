"""Optional local LLM response polishing via Ollama.

The LLM never makes business decisions or executes tools. Python remains the
source of truth for order ownership, eligibility, confirmations, and database writes.
"""
import json
import os
import urllib.error
import urllib.request


def polish_answer(answer: str) -> str:
    """Rewrite a factual answer in friendly language; safely fall back if unavailable."""
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider in {"", "none", "off", "disabled"}:
        return answer
    if provider != "ollama":
        # Unsupported providers deliberately fall back to deterministic responses.
        return answer

    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b").strip()
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        timeout = max(1, min(float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "12")), 25))
    except ValueError:
        timeout = 12

    prompt = (
        "You are a wording assistant for ShopSphere customer support. "
        "Rewrite the supplied answer to sound clear, polite, and concise. "
        "Do not add facts, assumptions, policy details, or promises. "
        "Preserve all names, order IDs, item IDs, dates, numbers, eligibility decisions, "
        "and the meaning. Do not use markdown. Return only the rewritten answer.\n\n"
        f"Answer to rewrite:\n{answer}"
    )
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "Rewrite only. Never make decisions or invent information."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data.get("message", {}).get("content", "").strip()
        # Reject empty or suspiciously long rewrites; the deterministic answer is safer.
        if not content or len(content) > max(1200, len(answer) * 4):
            return answer
        return content
    except (OSError, ValueError, KeyError, urllib.error.URLError, TimeoutError):
        # Ollama may be stopped or unavailable on the evaluator's computer.
        # The API should continue to work without an LLM.
        return answer
