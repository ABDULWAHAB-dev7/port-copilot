"""Read uploaded document text into the line shape the copilot reasons over.

A real invoice, packing list, bill of lading or certificate of origin is not
typed as 'Key: value' lines, so each type carries a field table: the keys the
copilot understands, and the labels a document may print for them. A field is
emitted only when its value can be read out of the text, so an unreadable
document shows up as a field the draft reports as missing, never as a guess.
Lines the table does not recognise are kept as they are, as text to cite.
"""
import re

from .copilot import DOC_LABEL

DOC_KINDS = ("invoice", "packing_list", "bill_of_lading", "certificate_of_origin")

MAX_LINES = 60
MAX_VALUE = 200

# Labels are matched at the start of a line, most specific first, so a generic
# word such as 'total' cannot claim a line that names something else.
FIELDS = {
    "invoice": (
        ("Invoice No", [r"invoice\s*(?:no|num|number|#)", r"inv\s*(?:no|num|number|#)", r"tax\s*invoice"]),
        ("Invoice Date", [r"invoice\s*date", r"date\s*of\s*invoice", r"date"]),
        ("Supplier", [r"supplier", r"exporter", r"seller", r"consignor", r"shipper"]),
        ("Buyer", [r"buyer", r"importer", r"consignee", r"customer", r"notify"]),
        ("Currency", [r"currency", r"curr\.?\b", r"invoice\s*currency"]),
        ("Invoice Value", [
            r"total\s*invoice\s*value", r"total\s*(?:invoice\s*)?(?:value|amount)",
            r"invoice\s*value", r"invoice\s*amount",
            r"value\s*of\s*(?:goods|shipment)", r"goods\s*value",
            r"fob\s*value", r"cif\s*value", r"cfr\s*value",
            r"amount\b(?!\s*in\s*words)",
            r"total\b(?!\s*(?:package|carton|pallet|qty|quantity|piece|weight|net|gross))",
        ]),
        ("Incoterm", [r"incoterms?", r"terms?\s*of\s*delivery", r"delivery\s*terms?", r"price\s*terms?"]),
        ("HS Code", [
            r"hs\s*(?:code|no|num|number)", r"h\.?\s*s\.?\s*(?:code|no|num|number)",
            r"cth", r"tariff\s*(?:heading|code|item)", r"commodity\s*code", r"customs\s*code",
        ]),
        ("Goods Description", [r"goods\s*description", r"description\s*of\s*goods", r"commodity", r"product\s*description", r"description"]),
    ),
    "packing_list": (
        ("Packing List No", [r"packing\s*list\s*(?:no|num|number|#)", r"packing\s*(?:slip|note)\s*(?:no|#)"]),
        ("Container No", [r"container\s*(?:no|num|number|id|#)", r"cntr", r"equipment\s*(?:no|id)"]),
        ("Total Packages", [
            r"total\s*(?:no\.?\s*of\s*)?packages?", r"no\.?\s*of\s*packages?", r"packages?\s*(?:count|total)",
            r"total\s*(?:cartons?|pallets?|cases?|bags?|drums?|bundles?)",
            r"cartons?\b", r"pallets?\b",
        ]),
        ("Gross Weight", [r"gross\s*weight", r"g\.?\s*w\.?\b", r"total\s*gross"]),
        ("Net Weight", [r"net\s*weight", r"n\.?\s*w\.?\b", r"total\s*net"]),
        ("Marks and Numbers", [r"marks?\s*(?:and|&)?\s*numbers?", r"shipping\s*marks?", r"marks\b"]),
    ),
    "bill_of_lading": (
        ("B/L No", [r"b\s*/?\s*l\s*(?:no|num|number|#)", r"bill\s*of\s*lading\s*(?:no|num|number|#)", r"sea\s*waybill\b"]),
        ("Vessel", [r"vessel\s*(?:name)?", r"ship\s*name", r"carrier\s*vessel", r"ocean\s*vessel"]),
        ("Voyage", [r"voyage\s*(?:no|num|number)?", r"voy\b"]),
        ("Port of Loading", [r"port\s*of\s*loading", r"loading\s*port", r"pol\b", r"place\s*of\s*receipt", r"port\s*of\s*origin"]),
        ("Port of Discharge", [r"port\s*of\s*discharge", r"discharge\s*port", r"pod\b", r"port\s*of\s*(?:final\s*)?destination"]),
        ("Container No", [r"container\s*(?:no|num|number|id|#)", r"cntr", r"equipment\s*(?:no|id)"]),
        ("Packages", [
            r"total\s*(?:no\.?\s*of\s*)?packages?", r"no\.?\s*of\s*packages?", r"packages?\b",
            r"total\s*(?:cartons?|pallets?|cases?)", r"cartons?\b", r"pallets?\b",
        ]),
        ("Gross Weight", [r"gross\s*weight", r"g\.?\s*w\.?\b"]),
        ("Shipper", [r"shipper", r"exporter", r"consignor"]),
        ("Consignee", [r"consignee", r"buyer", r"importer"]),
        ("Freight", [r"freight"]),
    ),
    "certificate_of_origin": (
        ("Certificate No", [r"certificate\s*(?:no|num|number|#)", r"cert\s*(?:no|num|number|#)", r"reference\s*(?:no|number)"]),
        ("Country of Origin", [r"country\s*of\s*origin", r"origin\s*(?:country|of\s*goods)", r"origin"]),
        ("HS Code", [
            r"hs\s*(?:code|no|num|number)", r"h\.?\s*s\.?\s*(?:code|no|num|number)",
            r"cth", r"tariff\s*(?:heading|code|item)",
        ]),
        ("Exemption Notification", [r"exemption\s*notification", r"notification", r"exemption", r"concession"]),
        ("Issued By", [r"issued\s*by", r"issuing\s*(?:authority|agency)", r"chamber"]),
        ("Invoice No", [r"invoice\s*(?:no|num|number|#)"]),
        ("Goods Description", [r"goods\s*description", r"description\s*of\s*goods", r"commodity", r"description"]),
    ),
}


def _clean(value):
    value = re.sub(r"\s+", " ", value or "").strip()
    return value.strip(":;,-–—|#. ").strip()[:MAX_VALUE]


# A label the field table only partly matched, e.g. 'Total Invoice' leaving
# 'Value: USD 42,780.50'. Stripped only when a value remains behind it.
TAIL = re.compile(r"^(?:(?:value|amount|total|number|date|code|of|issue|details?)\b[\s:]*)+", re.I)


def _lines(text):
    out = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            out.append(line)
    return out


def _match(lines, labels):
    """The first line carrying one of these labels, with its value."""
    pattern = re.compile(r"^(?:" + "|".join(labels) + r")(?!\w)\s*[:\-–—#]?\s*(.*)$", re.I)
    for n, line in enumerate(lines):
        found = pattern.match(line)
        if not found:
            continue
        value = _clean(found.group(1))
        if value:
            trimmed = _clean(TAIL.sub("", value))
            value = trimmed or value
        if not value and n + 1 < len(lines):
            # A label printed on its own line, with the value underneath.
            nxt = lines[n + 1]
            if ":" not in nxt and len(nxt) <= 60:
                value = _clean(nxt)
        if value:
            return value, n
    return None, None


def _fields(kind, lines):
    found = []
    for key, labels in FIELDS.get(kind, ()):
        value, at = _match(lines, labels)
        if value is not None:
            found.append((key, value, at))
    return found


def read(kind, text):
    """One document -> (lines for the copilot, how many fields were read)."""
    lines = _lines(text)
    found = _fields(kind, lines)
    out = [f"{key}: {value}" for key, value, _ in found]
    taken = {at for _, _, at in found}
    for n, line in enumerate(lines):
        if len(out) >= MAX_LINES:
            break
        if n in taken or line in out:
            continue
        out.append(line if ":" in line else f"Text: {line}")
    return out, len(found)


def sniff(text):
    """How many fields each document type can read from this text."""
    lines = _lines(text)
    return {kind: len(_fields(kind, lines)) for kind in DOC_KINDS}


def build(texts):
    """{kind: raw text} -> (shipment for the copilot, notes, fields read)."""
    docs, notes, report = {}, [], {}
    for kind in DOC_KINDS:
        raw = texts.get(kind)
        if not raw:
            continue
        lines, count = read(kind, raw)
        report[kind] = count
        if lines:
            docs[kind] = lines
        label = DOC_LABEL[kind][0]
        scores = sniff(raw)
        best = max(scores, key=lambda k: scores[k])
        if best != kind and scores[best] >= 2 and scores[best] > scores[kind] + 1:
            notes.append(
                f"The file loaded as the {label} reads like a {DOC_LABEL[best][0]}. "
                "Check which document you uploaded."
            )
        elif count == 0:
            notes.append(
                f"Nothing was read from the uploaded {label}. It needs labelled fields, "
                "such as 'Invoice Value' or 'HS Code'. The text is passed on as it is, "
                "but no field was guessed at."
            )
    return {"id": "UPLOAD", "docs": docs}, notes, report
