"""Scenario checks: planted charge mistakes, cited drafts, and the API contract. Run: python tests/run_checks.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.charges import check_invoice  # noqa: E402
from core.copilot import draft  # noqa: E402

DATA = ROOT / "data"
failures = []


def expect(cond, msg):
    if not cond:
        failures.append(msg)


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def check_charges():
    tariffs = load("tariffs.json")
    for inv in load("cfs_invoices.json"):
        result = check_invoice(inv["text"], tariffs, inv["tariff_id"])
        got = sorted(f["code"] for f in result["flags"])
        want = sorted(inv["gold"]["flags"])
        expect(got == want, f"{inv['id']}: flags {got} expected {want}")


def check_drafts():
    shipments = {s["id"]: s for s in load("shipments.json")}
    questions = load("questions.json")
    for sid, shipment in shipments.items():
        for q in questions:
            result = draft(shipment, q)
            ids = {f"{d}:{n}" for d, lines in shipment["docs"].items() for n in range(1, len(lines) + 1)}
            for s in result["sentences"]:
                expect(s["cite"] in ids, f"{sid}: cite {s['cite']} not in shipment")
                expect(s["quote"] in next(
                    l for d, lines in shipment["docs"].items() for n, l in enumerate(lines, 1)
                    if f"{d}:{n}" == s["cite"]), f"{sid}: quote not in cited line")
            expect(result["status"].startswith("DRAFT - not sent"), "status text changed")

    gap = draft(shipments["SHP-1002"], "Provide the CTH declared for this shipment.")
    expect("Certificate of Origin" not in gap["missing"], "SHP-1002 has a certificate; should not be missing")
    gap = draft(shipments["SHP-1002"], "What is the country of origin of the goods?")
    expect(gap["missing"] == [], "SHP-1002 origin should be present")
    gap = draft(shipments["SHP-1002"], "Which vessel and voyage carry this consignment?")
    expect("Bill of Lading" in gap["missing"], "SHP-1002 has no bill of lading; should be reported missing")
    expect(any("HS code differs" in n for n in draft(shipments["SHP-1002"], "CTH?")["notes"]),
           "HS mismatch note missing for SHP-1002")


def check_api():
    try:
        from starlette.testclient import TestClient
    except ImportError:
        print("skip: API checks need httpx (pip install -r requirements-dev.txt)")
        return
    from api.index import app
    c = TestClient(app)
    expect(c.get("/api/health").json()["status"] == "ok", "health")
    shipments = c.get("/api/shipments").json()["shipments"]
    expect(len(shipments) == 3, "shipment list length")
    expect(c.get("/api/questions?shipment_id=SHP-1001").status_code == 200, "questions ok")
    expect(c.get("/api/questions?shipment_id=NOPE").status_code == 404, "unknown shipment 404 on questions")
    expect(c.post("/api/draft", json={"shipment_id": "NOPE", "question": "x"}).status_code == 404, "draft 404")
    expect(c.post("/api/draft", json={"shipment_id": "SHP-1001", "question": ""}).status_code == 400, "draft 400")
    expect(c.post("/api/draft", json={"shipment_id": "SHP-1001", "question": "x" * 2001}).status_code == 400, "question limit")
    body = c.post("/api/draft", json={"shipment_id": "SHP-1001", "question": "What is the HS code?"}).json()
    expect(body["mode"] == "offline" and body["sentences"], "draft offline with sentences")
    samples = c.get("/api/cfs/samples").json()["samples"]
    expect(all("gold" not in s and "flags" not in s for s in samples), "answer key leaked in samples")
    expect(c.post("/api/cfs/check", json={"text": "hello"}).status_code == 422, "unreadable invoice 422")
    expect(c.post("/api/cfs/check", json={"text": "x" * 20001}).status_code == 400, "invoice limit 400")
    ok = c.post("/api/cfs/check", json={"text": samples[0]["text"], "tariff_id": "SAMPLE_A"})
    expect(ok.status_code == 200 and ok.json()["flags"] == [], "clean invoice has no flags")
    backwards = samples[0]["text"].replace("GATE OUT: 2026-10-06", "GATE OUT: 2026-09-30")
    expect(c.post("/api/cfs/check", json={"text": backwards}).status_code == 422, "gate out before gate in must be 422")
    twice = samples[0]["text"].replace("LINE 2 | DOC", "LINE 9 | STORAGE | Storage days | 2 | 300.00 | 600.00\nLINE 2 | DOC")
    codes = [f["code"] for f in c.post("/api/cfs/check", json={"text": twice}).json()["flags"]]
    expect("DUPLICATE" in codes, "second storage line must be flagged")
    string_flag = c.post("/api/draft", json={"shipment_id": "SHP-1001", "question": "hs?", "use_llm": "true"}).json()
    expect(string_flag["mode"] == "offline", "use_llm must be a real boolean")
    expect(c.post("/api/draft", json={"shipment_id": ["SHP-1001"], "question": "q"}).status_code == 400, "non-text shipment_id must be refused")
    expect(c.post("/api/draft", json={"shipment_id": "SHP-1001", "question": ["q"]}).status_code == 400, "non-text question must be refused")
    expect(c.post("/api/draft", json={"documents": {"invoice": 5}, "question": "q"}).status_code == 400, "non-text document must be refused")
    expect(c.post("/api/cfs/check", json={"text": samples[0]["text"], "tariff_id": 99}).status_code == 400, "non-text tariff_id must be refused")

    def oversized():
        yield b'{"question":"'
        for _ in range(30):
            yield b"a" * 10000
        yield b'"}'
    expect(c.post("/api/draft", content=oversized(), headers={"content-type": "application/json"}).status_code == 413, "oversized streamed body must be refused")


def check_regressions():
    from core.charges import ReadError
    from core.copilot import draft
    tariffs = load("tariffs.json")
    shipments = {s["id"]: s for s in load("shipments.json")}
    base = load("cfs_invoices.json")[0]["text"]

    for label, text in [
        ("negative amount", base.replace("LINE 2 | DOC | Documentation | 1 | 300.00 | 300.00", "LINE 2 | DOC | Documentation | 1 | -300.00 | -300.00")),
        ("thousands separator", base.replace("1500.00 | 1500.00", "1,500.00 | 1,500.00")),
        ("fractional storage days", base.replace("| 2 | 300.00 | 600.00", "| 2.5 | 300.00 | 600.00")),
        ("duplicate footer", base.replace("GST: 432.00", "GST: 432.00\nGST: 999.00")),
    ]:
        try:
            check_invoice(text, tariffs, "SAMPLE_A")
            expect(False, f"{label} must be rejected, not silently accepted")
        except ReadError:
            pass

    proposal = [{"text": "a", "cite": ["invoice:1"], "quote": "x"}, {"text": "b", "cite": {"id": 1}, "quote": "x"}]
    result = draft(shipments["SHP-1001"], "CTH?", use_llm=True, llm_call=lambda prompt: proposal)
    expect(result["mode"] == "offline" and len(result["rejected"]) == 2, "unhashable LLM citations must be rejected, not crash")


if __name__ == "__main__":
    check_charges()
    check_drafts()
    check_api()
    check_regressions()
    if failures:
        print("FAILED")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("All scenario checks passed.")
