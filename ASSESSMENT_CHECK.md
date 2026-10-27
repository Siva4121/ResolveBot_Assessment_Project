# ResolveBot assessment review

## What was checked
- Compared `data/policies.md`, `data/manifest.json`, and `data/shopsphere.db` in the project archive against the supplied assessment archive. All three files were byte-for-byte identical.
- Read `TASK.pdf` (all six pages) and compared the project structure and implementation against the endpoint, tool, policy, safety, confirmation, and submission requirements.
- Added optional Ollama response polishing. The model does not choose tools, make eligibility decisions, or write to the database. If Ollama is not running, the existing deterministic response is returned.
- Updated request validation so a missing `session_id` or `message` returns HTTP 400.
- Updated order ID parsing to accept both `SS-10458` and `SS10458`.
- Added return-policy citations to return proposals and preferred current policy documents over FAQs in retrieval.
- Confirmed Python syntax compilation.
- Smoke-tested tracking, an order belonging to another customer, return proposal, and the yes-confirmation flow against an isolated copy of the database. The original supplied database was not modified.
- Tested API responses: missing fields = 400, missing customer header = 401, unknown customer = 401, valid chat request = 200.

## Important setup
- `.env.example` defaults to `LLM_PROVIDER=ollama` and `OLLAMA_MODEL=qwen2.5:3b`.
- If your installed Ollama model has a different name, update `OLLAMA_MODEL` in `.env` to match `ollama list`.
- Ollama is optional for API startup; unavailable Ollama causes a safe fallback to the deterministic answer.
- The ZIP includes `data/` so you can run it locally. The assessment says not to include `data/` in the actual repository/submission when the evaluator provides their own copy. `.gitignore` excludes `data/`.

## Known limitations
- Intent handling is still primarily rule-based rather than a full LLM tool-calling loop.
- Multi-intent requests, nuanced return questions, and some date phrasing may need more work.
- Policy retrieval uses keyword scoring rather than vector embeddings.
- Session state is in memory and resets when the server restarts.
