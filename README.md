# Customs Copilot

Two tools on one stateless service: a cited query-reply drafter for customs officer queries, and a charge checker for port and CFS invoices. Both take your own documents — uploaded or pasted — and fall back on the bundled samples. Nothing is stored. Drafts and checks; a licensed professional remains responsible for anything filed.

Design: `Customs Copilot - System Design and Architecture` (PDF, kept outside the repo).

## Layout

```
api/index.py        ASGI routes (Starlette), input limits, error mapping
core/copilot.py     intents, chunking, verify gate, drafting, cross-checks
core/intake.py      reads uploaded document text into the lines the copilot cites
core/charges.py     invoice reader, tariff selection, Decimal checks, explanation
core/retrieval.py   dependency-free BM25
core/llm.py         optional Gemini client (urllib, 8 s timeout, never raises)
data/*.json         read-only bundle: shipments, questions, tariffs, cfs_invoices
public/index.html   landing page and both tools (served by Vercel's CDN; by dev.py locally)
public/terms.html, public/privacy.html   legal pages on the shared header and footer
public/assets/      site.css (clay design, header, footer), site.js (menu, scroll motion, status),
                    icons.svg (Hugeicons free set, MIT), skyline.svg (animated footer scene)
public/scroll/      sample footage frames (four stills are used on the page)
scripts/generate_data.py   regenerates data/*.json deterministically
tests/              run_checks.py, test_llm_guard.py
dev.py              local server: API and page on port 8000
```

## Run locally

```bash
pip install -r requirements.txt
python scripts/generate_data.py      # optional; data is committed
python dev.py                        # http://127.0.0.1:8000
```

Tests (standard library, plus httpx for the API checks):

```bash
pip install -r requirements-dev.txt
python tests/run_checks.py
python tests/test_llm_guard.py
```

## AI drafting (optional)

Set `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`). Without a key the service runs in offline mode. Model output is only a proposal: every sentence must cite a real line, quote it exactly, and keep its numbers, or it is rejected and the offline draft is used.

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | `llm_available` shows whether a key is configured |
| GET | `/api/shipments` | ids and document types |
| GET | `/api/questions?shipment_id=` | sample officer questions (404 if unknown shipment) |
| POST | `/api/draft` | `{question, use_llm}` plus either `shipment_id` for a bundled sample or `documents: {invoice, bill_of_lading, packing_list, certificate_of_origin}` with your own text; 400 missing, question over 2000 chars or a document over 20000 chars; 404 unknown shipment |
| GET | `/api/cfs/samples` | sample invoices with the answer key removed |
| POST | `/api/cfs/check` | `{text, tariff_id?}`; 400 missing or over 20000 chars; 422 unreadable or no tariff card |

Errors are `{"error": message}`.

## Deploy (Vercel)

Import the repository in Vercel. `vercel.json` rewrites `/api/*` to the single function in `api/index.py` (30 s cap); `public/` is served from the CDN. Set `GEMINI_API_KEY` in the project's environment variables only if you want AI drafting.

## Known gaps

- The charge reader is a regular expression for the invoice layout in `data/cfs_invoices.json`. Another layout is refused with a message rather than guessed at.
- The drafts reader (`core/intake.py`) is label-based: it reads the fields it has labels for (`Invoice Value`, `HS Code`, `Vessel`, ...) out of your text, and reports a document it read nothing from. A layout whose labels it does not know needs a new label in its field table.
- Uploads are read as text: a `.txt`/`.csv` file, or a PDF that carries a text layer. A scanned page has no text to read, and OCR is not built. The PDF is parsed in the browser with pdf.js (loaded from a CDN only when a PDF is chosen).
- Real tariff cards are out of scope for v1; the bundled card is synthetic.
