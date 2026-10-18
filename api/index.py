"""ASGI app for the Vercel Python function. Holds no state; reads bundled JSON only."""
import json
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from core import intake, llm
from core.charges import ReadError, TariffError, check_invoice
from core.copilot import draft

MAX_BODY = 256 * 1024
MAX_QUESTION = 2000
MAX_INVOICE = 20000
MAX_DOC = 20000
DATA = ROOT / "data"


@lru_cache(maxsize=None)
def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _error(message, status):
    return JSONResponse({"error": message}, status_code=status)


async def _json_body(request):
    # Read in chunks and stop at the cap, so an oversized body is never held in memory.
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY:
            return None, _error("Request body is too large.", 413)
    try:
        data = json.loads(bytes(raw) or b"{}")
    except ValueError:
        return None, _error("Request body must be valid JSON.", 400)
    if not isinstance(data, dict):
        return None, _error("Request body must be a JSON object.", 400)
    return data, None


def _text(data, key):
    """Return (text, error). A missing or null field is empty; any other non-text value is refused."""
    value = data.get(key)
    if value is None:
        return "", None
    if not isinstance(value, str):
        return None, _error(f"{key} must be text.", 400)
    return value.strip(), None


def _shipment(shipment_id):
    for s in _load("shipments.json"):
        if s["id"] == shipment_id:
            return s
    return None


async def health(request):
    return JSONResponse({
        "status": "ok",
        "llm_available": llm.configured(),
        "model": llm.model_name() if llm.configured() else None,
    })


async def shipments(request):
    items = [
        {"id": s["id"], "docs": sorted(s["docs"].keys())}
        for s in _load("shipments.json")
    ]
    return JSONResponse({"shipments": items})


async def questions(request):
    shipment_id = request.query_params.get("shipment_id", "").strip()
    if not shipment_id:
        return _error("shipment_id is required.", 400)
    if _shipment(shipment_id) is None:
        return _error(f"Unknown shipment '{shipment_id}'.", 404)
    return JSONResponse({"shipment_id": shipment_id, "questions": _load("questions.json")})


async def draft_reply(request):
    data, err = await _json_body(request)
    if err:
        return err
    question, err = _text(data, "question")
    if err:
        return err
    if not question:
        return _error("question is required.", 400)
    if len(question) > MAX_QUESTION:
        return _error(f"question is too long (max {MAX_QUESTION} characters).", 400)

    notes = []
    documents = data.get("documents")
    if documents is not None:
        # Real mode: the caller sends the documents themselves.
        if not isinstance(documents, dict):
            return _error("documents must be an object mapping document type to its text.", 400)
        texts = {}
        for kind, value in documents.items():
            if kind not in intake.DOC_KINDS:
                return _error(f"Unknown document type '{kind}'.", 400)
            if value is not None and not isinstance(value, str):
                return _error(f"The '{kind}' document must be text.", 400)
            text = (value or "").strip()
            if not text:
                continue
            if len(text) > MAX_DOC:
                return _error(f"The '{kind}' document is too long (max {MAX_DOC} characters).", 400)
            texts[kind] = text
        if not texts:
            return _error("documents must include at least one document with text.", 400)
        shipment, notes, read = intake.build(texts)
        shipment_id, source = None, "upload"
    else:
        shipment_id, err = _text(data, "shipment_id")
        if err:
            return err
        if not shipment_id:
            return _error("shipment_id is required.", 400)
        shipment = _shipment(shipment_id)
        if shipment is None:
            return _error(f"Unknown shipment '{shipment_id}'.", 404)
        source, read = "sample", {}

    use_llm = data.get("use_llm") is True and llm.configured()
    result = draft(shipment, question, use_llm=use_llm, llm_call=llm.complete_json if use_llm else None)
    result["notes"] = notes + result["notes"]
    return JSONResponse({"shipment_id": shipment_id, "source": source, "read": read, **result})


async def cfs_samples(request):
    samples = [
        {"id": s["id"], "terminal": s["terminal"], "tariff_id": s["tariff_id"], "text": s["text"]}
        for s in _load("cfs_invoices.json")
    ]
    return JSONResponse({"samples": samples})


async def cfs_check(request):
    data, err = await _json_body(request)
    if err:
        return err
    text, err = _text(data, "text")
    if err:
        return err
    if not text:
        return _error("text is required.", 400)
    if len(text) > MAX_INVOICE:
        return _error(f"text is too long (max {MAX_INVOICE} characters).", 400)
    tariff_id, err = _text(data, "tariff_id")
    if err:
        return err
    tariff_id = tariff_id or None
    try:
        return JSONResponse(check_invoice(text, _load("tariffs.json"), tariff_id))
    except ReadError as e:
        return _error(str(e), 422)
    except TariffError as e:
        return _error(str(e), 422)


routes = [
    Route("/api/health", health, methods=["GET"]),
    Route("/api/shipments", shipments, methods=["GET"]),
    Route("/api/questions", questions, methods=["GET"]),
    Route("/api/draft", draft_reply, methods=["POST"]),
    Route("/api/cfs/samples", cfs_samples, methods=["GET"]),
    Route("/api/cfs/check", cfs_check, methods=["POST"]),
]

app = Starlette(routes=routes)
