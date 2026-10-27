# ResolveBot — Junior AI Developer Assessment

## Run locally
Python 3.10+ recommended.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` in your browser to test the API. Send a `POST` request to `/chat` with header `X-Customer-Id: C1009`, content type `application/json`, and body:
```json
{"session_id":"demo-1","message":"Where is order SS-10458?"}
```
Use a customer ID present in the supplied database. The working folder provided for local testing includes `data/`. Per the assessment instructions, remove `data/` from your repository/submission if the evaluator will provide their own data copy.

## How it works
- `main.py`: FastAPI endpoint, header/customer validation, session ownership.
- `tools.py`: database tools, ownership checks, return eligibility, warranty dates and write-time revalidation.
- `policy_search.py`: loads Markdown documents and manifest metadata; filters superseded/future documents and retrieves matching sections.
- `assistant.py`: routes messages, builds replies, tracks one pending proposal per session, and only writes after a clear yes.
- The five required tool functions are `get_orders`, `search_policy` (in `policy_search.py`), `check_return_eligibility`, `create_return_request`, and `create_support_ticket`.

## Assumptions
- `APP_TODAY` is the date used for business rules; defaults to 2026-07-01 and does not use the system date for return/warranty decisions.
- A proposal is confirmed only by a clear affirmative response such as `yes`, `confirm`, or `go ahead` in the next message.
- The assessment asks for a single endpoint and no UI. The assistant uses Python rules for intent handling and all business decisions. When `LLM_PROVIDER=ollama`, Ollama is used only to polish ordinary final answers; it never chooses tools, changes eligibility, or writes to the database. If Ollama is unavailable, the deterministic answer is returned and the API still works.
- Return item matching uses words in the customer message and asks a clarifying question when it cannot identify exactly one item.
- Cancellation is represented by a support ticket as required; the order record itself is not modified.

## Local LLM (Ollama)
Install Ollama from https://ollama.com/download/windows, then download a model (the default is `qwen2.5:3b`):

```powershell
ollama run qwen2.5:3b
```

Copy `.env.example` to `.env`. The default settings use:
- `LLM_PROVIDER=ollama`
- `OLLAMA_MODEL=qwen2.5:3b`
- `OLLAMA_BASE_URL=http://localhost:11434`

To run fully without a model, set `LLM_PROVIDER=none`. Ollama is optional: if it is not running or the model is missing, the API falls back to its deterministic response. This avoids making the assessment fail just because the evaluator does not have Ollama installed.

## Limitations
- The intent parser is rule-based and can miss varied natural-language phrasing; the Ollama model is intentionally not allowed to decide which tools run.
- Policy retrieval is keyword-based rather than embedding-based. Current documents are filtered by `manifest.json`, and policy documents are preferred over FAQs when matching.
- Some more complex multi-intent messages and date phrases are not fully handled.
- The session store is in memory and will reset on process restart; for production, use persistent session storage.
- No automated tests are included, per assessment instructions. Test the critical flows manually using the examples below.

## Manual examples
1. `Where is order SS-10458?` — returns order status and ETA, or the exact safe not-found response.
2. `Return the speaker from SS-10458, I changed my mind.` — checks eligibility and asks for confirmation; no row is written yet.
3. `yes` in the same session — writes one return request.
4. `How many days do I have to return something?` — searches current policy sections and returns citations.
5. `What is the weather?` — returns `out_of_scope`.

## AI coding assistance
AI assistance was used to help draft and organize the initial implementation. The code should be reviewed and understood before submission.