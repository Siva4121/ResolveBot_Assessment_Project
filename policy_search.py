
import json
import re
from pathlib import Path


def load_docs(policies_path, manifest_path, app_today):
    """Load only current policy documents effective by APP_TODAY."""

    text = Path(policies_path).read_text(encoding="utf-8")

    with open(manifest_path, encoding="utf-8") as file:
        manifest_items = json.load(file)

    manifest = {
        item["doc_id"]: item
        for item in manifest_items
    }

    # Each document starts with a level-one Markdown heading.
    chunks = re.split(r"(?m)(?=^# )", text)
    docs = []

    for chunk in chunks:
        if not chunk.strip():
            continue

        # Matches: **Document ID:** returns_policy
        match = re.search(
            r"\*\*Document ID:\*\*\s*([^ \t·]+)",
            chunk
        )

        if not match:
            continue

        doc_id = match.group(1)
        metadata = manifest.get(doc_id)

        # Ignore documents not listed in the manifest.
        if not metadata:
            continue

        # Ignore superseded documents and future policies.
        if metadata.get("status") != "current":
            continue

        effective_date = metadata.get("effective_date", "9999-99-99")

        if effective_date > app_today:
            continue

        title = chunk.splitlines()[0].lstrip("# ").strip()

        # Split the document into sections and subsections.
        sections = re.split(
            r"(?m)(?=^#{2,3}\s+§)",
            chunk
        )

        for section_text in sections:
            if not section_text.strip():
                continue

            section_match = re.search(
                r"§\d+(?:\.\d+)?",
                section_text
            )

            docs.append({
                "doc_id": doc_id,
                "title": title,
                "doc_type": metadata.get("doc_type", "faq"),
                "section": (
                    section_match.group(0)
                    if section_match
                    else "§1"
                ),
                "text": section_text.strip()
            })

    return docs


def search_policy(query, docs, limit=4):
    """Find relevant sections, preferring authoritative policies."""

    query_words = set(
        re.findall(r"[a-z0-9]+", query.lower())
    )

    scored = []

    for document in docs:
        document_text = document["text"].lower()

        document_words = set(
            re.findall(r"[a-z0-9]+", document_text)
        )

        score = len(query_words & document_words)

        # Give relevant policy sections a small relevance boost.
        query_lower = query.lower()

        if "return" in query_lower and "return" in document_text:
            score += 2

        if "warranty" in query_lower and "warranty" in document_text:
            score += 2

        if "shipping" in query_lower and "shipping" in document_text:
            score += 2

        if document["doc_type"] == "policy" and score > 0:
            score += 3

        if score > 0:
            scored.append((score, document))

    # Python sorting is stable, preserving original order for ties.
    scored.sort(key=lambda item: item[0], reverse=True)

    return [
        {
            "doc_id": document["doc_id"],
            "section": document["section"],
            "text": document["text"]
        }
        for score, document in scored[:limit]
    ]
