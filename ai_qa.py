import math
import os
import json
import re
from urllib import request as urllib_request
from typing import List, Tuple

import fitz
import numpy as np
from PIL import Image
from ocr.ocr_utils import ocr_pdf_to_text
from ocr.ocr_utils import get_reader, preprocess_image
from ocr.document_parser import parse_document
from ocr.account_statement_parser import parse_account_statement_text


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")


def _is_missing_value(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "n/a", "na", "-", "none", "null", "unknown"}
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    if isinstance(value, (int, float)):
        return value == 0
    return False


def _extract_total_premium_due_from_text(text: str) -> float:
    if not text:
        return 0.0
    m = re.search(
        r"TOTAL\s+PREMIUM\s+DUE[^0-9]*([0-9][0-9,\s\.QOolI]*)",
        text,
        re.IGNORECASE,
    )
    if not m:
        return 0.0
    raw = m.group(1)
    s = raw.replace(",", "").replace(" ", "")
    s = s.replace("Q", "0").replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    s = re.sub(r"[^0-9.]", "", s)
    try:
        return float(s)
    except Exception:
        return 0.0


def _sanitize_money(value):
    if value is None:
        return 0.0
    try:
        num = float(value)
    except Exception:
        return 0.0
    # Common OCR artifact: 129620 should be 1296.20
    if num >= 10000 and abs(num - int(num)) < 0.001:
        num = num / 100.0
    return round(num, 2)


def _looks_like_date(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return bool(re.match(r"^\d{2}/\d{2}/\d{4}$", value.strip()))


def _score_account_entry(entry: dict) -> Tuple[float, List[str]]:
    score = 1.0
    reasons: List[str] = []

    if not _looks_like_date(entry.get("effective_date", "")):
        score -= 0.25
        reasons.append("invalid_effective_date")
    debit_note = (entry.get("debit_note") or "").strip()
    if not re.match(r"^B[A-Z0-9\-?]+$", debit_note, re.IGNORECASE):
        score -= 0.2
        reasons.append("suspicious_debit_note")
    policy = (entry.get("policy_number") or "").strip()
    if len(policy) < 5:
        score -= 0.2
        reasons.append("missing_policy_number")
    premium = _sanitize_money(entry.get("premium"))
    if premium <= 0:
        score -= 0.25
        reasons.append("missing_or_zero_premium")
    elif premium > 50000:
        score -= 0.2
        reasons.append("premium_outlier")

    score = max(0.0, min(1.0, score))
    return score, reasons


def _quality_label(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def _fallback_extract_statement_entries(cleaned_text: str) -> List[dict]:
    """
    Fallback extractor for scattered OCR lines:
    looks for repeating (date -> debit note -> premium) blocks.
    """
    lines = [ln.strip() for ln in cleaned_text.splitlines() if ln.strip()]
    date_re = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    debit_re = re.compile(r"^B[A-Z0-9\-?]+$", re.IGNORECASE)
    out: List[dict] = []
    i = 0
    while i < len(lines):
        if date_re.match(lines[i]):
            date_val = lines[i]
            debit_val = None
            premium_val = 0.0

            if i + 1 < len(lines) and debit_re.match(lines[i + 1]):
                debit_val = lines[i + 1]
                i += 1

            if i + 1 < len(lines):
                maybe_premium = lines[i + 1]
                if (not date_re.match(maybe_premium)) and (not debit_re.match(maybe_premium)):
                    premium_val = _sanitize_money(maybe_premium)
                    i += 1

            out.append(
                {
                    "effective_date": date_val,
                    "debit_note": debit_val,
                    "policy_number": "",
                    "nature": 0.0,
                    "premium": premium_val,
                }
            )
        i += 1
    return out


def _postprocess_account_statement(parsed: dict, cleaned_text: str) -> dict:
    if not isinstance(parsed, dict):
        return parsed

    entries = parsed.get("entries", [])
    if isinstance(entries, list) and len(entries) <= 1:
        fallback_entries = _fallback_extract_statement_entries(cleaned_text)
        if len(fallback_entries) > len(entries):
            entries = fallback_entries
            parsed["entries"] = entries

    low_conf_rows = []
    total_score = 0.0
    scored_rows = 0
    if isinstance(entries, list):
        for idx, e in enumerate(entries):
            if isinstance(e, dict):
                e["premium"] = _sanitize_money(e.get("premium"))
                if "nature" in e:
                    e["nature"] = _sanitize_money(e.get("nature"))
                row_score, reasons = _score_account_entry(e)
                e["confidence_score"] = round(row_score, 3)
                e["confidence_label"] = _quality_label(row_score)
                if reasons:
                    e["quality_flags"] = reasons
                if row_score < 0.6:
                    low_conf_rows.append(idx)
                total_score += row_score
                scored_rows += 1

    extracted_total = _sanitize_money(_extract_total_premium_due_from_text(cleaned_text))
    summed = round(sum(_sanitize_money((e or {}).get("premium")) for e in entries if isinstance(e, dict)), 2)

    if extracted_total > 0:
        parsed["total_premium_due"] = extracted_total
        # warn when parsed line-item total is far from stated total
        if summed > 0 and abs(summed - extracted_total) > max(50.0, extracted_total * 0.2):
            warnings = parsed.get("warnings", [])
            if not isinstance(warnings, list):
                warnings = []
            warnings.append("Line-item premiums do not match stated TOTAL PREMIUM DUE; OCR review recommended.")
            parsed["warnings"] = warnings
    else:
        parsed["total_premium_due"] = summed

    avg_score = (total_score / scored_rows) if scored_rows else 0.0
    parsed["extraction_quality"] = {
        "average_entry_confidence_score": round(avg_score, 3),
        "average_entry_confidence_label": _quality_label(avg_score),
        "low_confidence_entry_indexes": low_conf_rows,
        "entries_count": scored_rows,
    }

    return parsed


def _ollama_post(path: str, payload: dict) -> dict:
    url = f"{OLLAMA_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to call Ollama at {url}: {exc}") from exc


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text directly from PDF pages."""
    if not pdf_bytes:
        return ""

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages_text: List[str] = []
    for page in doc:
        pages_text.append(page.get_text("text"))
    return "\n".join(pages_text).strip()


def extract_text_by_page(pdf_bytes: bytes) -> List[dict]:
    """
    Extract per-page text. Prefer direct text, fallback to OCR for scanned pages.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: List[dict] = []
    ocr_reader = get_reader()

    for page_idx, page in enumerate(doc, start=1):
        direct_text = (page.get_text("text") or "").strip()

        if len(direct_text) >= 40:
            pages.append({"page": page_idx, "text": direct_text, "method": "direct"})
            continue

        zoom = 300 / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img = preprocess_image(img)
        ocr_lines = ocr_reader.readtext(
            np.array(img),
            detail=0,
            paragraph=True,
            contrast_ths=0.1,
            adjust_contrast=0.5,
        )
        ocr_text = "\n".join(ocr_lines).strip()
        pages.append({"page": page_idx, "text": ocr_text, "method": "ocr"})

    return pages


def _clean_text_with_ollama(raw_text: str) -> str:
    """
    Fix OCR artifacts and spacing while preserving factual content.
    """
    if not raw_text.strip():
        return ""

    # Deterministic pre-clean before LLM normalization.
    pre = raw_text
    pre_replacements = {
        "Noyember": "November",
        "20z5": "2025",
        "EOWARD": "EDWARD",
        "LEYEL": "LEVEL",
        "MQNGKOK": "MONGKOK",
        "MONGKOX": "MONGKOK",
        "XQWLOON": "KOWLOON",
        "XOWI_OON_": "KOWLOON",
        "Tj": "TJ",
        "T,": "TJ",
    }
    for bad, good in pre_replacements.items():
        pre = pre.replace(bad, good)

    prompt = (
        "Clean and normalize this OCR/document text.\n"
        "Rules:\n"
        "- Keep original meaning and numbers exactly where possible.\n"
        "- Fix broken spacing and line breaks.\n"
        "- Remove obvious OCR garbage characters only.\n"
        "- Normalize common OCR confusion only when obvious: O/Q->0, l/I->1.\n"
        "- Keep section headings and list entries readable.\n"
        "- Return plain cleaned text only, no explanation.\n\n"
        f"{pre[:15000]}"
    )
    result = _ollama_post(
        "/api/generate",
        {"model": CHAT_MODEL, "prompt": prompt, "stream": False},
    )
    cleaned = (result.get("response") or "").strip()
    return cleaned if cleaned else pre


def extract_raw_text(pdf_bytes: bytes) -> str:
    """
    Try direct PDF text first, then OCR fallback.
    """
    pages = extract_text_by_page(pdf_bytes)
    merged = [p["text"] for p in pages if p.get("text", "").strip()]
    source_text = "\n\n".join(merged).strip()
    if source_text:
        return source_text

    # Last fallback to existing OCR util.
    return (ocr_pdf_to_text(pdf_bytes) or "").strip()


def clean_text_with_ollama(raw_text: str) -> str:
    return _clean_text_with_ollama(raw_text)


def extract_best_text(pdf_bytes: bytes) -> str:
    """
    Extract raw text with fallback and then clean with Ollama.
    """
    source_text = extract_raw_text(pdf_bytes)
    if not source_text:
        return ""

    cleaned = clean_text_with_ollama(source_text)
    return cleaned if cleaned else source_text


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> List[str]:
    """Split text into overlapping chunks for embedding retrieval."""
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    text_len = len(text)
    step = max(1, chunk_size - overlap)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += step

    return chunks


def chunk_pages(pages: List[dict], chunk_size: int = 900, overlap: int = 120) -> List[dict]:
    chunks: List[dict] = []
    step = max(1, chunk_size - overlap)

    for page_data in pages:
        text = (page_data.get("text") or "").strip()
        if not text:
            continue
        page = page_data.get("page")
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append({"page": page, "text": chunk})
            start += step
    return chunks


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embed_many(texts: List[str]) -> List[List[float]]:
    vectors: List[List[float]] = []
    for text in texts:
        result = _ollama_post("/api/embeddings", {"model": EMBED_MODEL, "prompt": text})
        vector = result.get("embedding")
        if not vector:
            raise ValueError("Ollama did not return embedding vector.")
        vectors.append(vector)
    return vectors


def _chat_with_context(question: str, context: str) -> str:
    prompt = (
        "You answer questions using ONLY the provided document context.\n"
        "If the answer is not present, say exactly: "
        "'I could not find that in the uploaded document.'\n\n"
        f"Question: {question}\n\n"
        f"Document context:\n{context}\n"
    )
    result = _ollama_post(
        "/api/generate",
        {"model": CHAT_MODEL, "prompt": prompt, "stream": False},
    )
    answer = (result.get("response") or "").strip()
    if not answer:
        raise ValueError("Ollama did not return an answer.")
    return answer


def extract_structured_data_with_ollama(cleaned_text: str, doc_type: str) -> dict:
    """
    Lightweight structured extraction to complement regex parser output.
    """
    if not cleaned_text.strip():
        return {}

    prompt_by_type = {
        "account_statement": (
            "Extract STRICT JSON only with keys:\n"
            "issue_date, address, account_number, total_premium_due, premium_due_date, entries.\n"
            "entries is a list of objects with keys: effective_date, debit_note, policy_number, premium.\n"
            "Use empty string for unknown text fields and 0 for unknown numeric values."
        ),
        "debit_note": (
            "Extract STRICT JSON only with keys:\n"
            "issue_date, insured_or_agent, insurance_class, policy_number, endorsement_number, account_number, financials.\n"
            "financials is a list of objects with keys: category, gross_premium, commission, overriding_insurer, cost, profit.\n"
            "Use empty string for unknown text fields and [] for unknown list fields."
        ),
        "renewal_notice": (
            "Extract STRICT JSON only with keys:\n"
            "issue_date, insured, insurance_class, policy_number, expiry_date, ac_code, total_earning, renewal_premium, entries.\n"
            "entries is a list of objects with keys: label, amount.\n"
            "Use empty string for unknown text fields and 0 for unknown numeric values."
        ),
    }
    schema_prompt = prompt_by_type.get(
        doc_type,
        (
            "Extract STRICT JSON only with keys:\n"
            "issue_date, insured_or_agent, insured, insurance_class, policy_number, endorsement_number, "
            "account_number, address, total_premium_due, premium_due_date, expiry_date, ac_code, "
            "total_earning, renewal_premium."
        ),
    )

    prompt = (
        f"{schema_prompt}\n\n"
        "Rules:\n"
        "- Return valid JSON only.\n"
        "- Do not add markdown, comments, or explanation.\n"
        "- Keep numeric values numeric when clear.\n\n"
        f"Document type: {doc_type}\n\n"
        f"Text:\n{cleaned_text[:14000]}"
    )
    result = _ollama_post(
        "/api/generate",
        {"model": CHAT_MODEL, "prompt": prompt, "stream": False},
    )
    payload = (result.get("response") or "").strip()
    try:
        return json.loads(payload)
    except Exception:
        return {}


def classify_document_type(cleaned_text: str) -> str:
    """
    Classify insurance doc into one supported type.
    Uses keyword heuristics first, then LLM fallback.
    """
    text = (cleaned_text or "").lower()
    if not text.strip():
        return ""

    # Heuristic-first classification for OCR-noisy documents.
    if "statement of account" in text:
        return "account_statement"
    if "debit note" in text:
        return "debit_note"
    if "renewal notice" in text:
        return "renewal_notice"

    prompt = (
        "Classify this insurance document text into exactly one label from:\n"
        "- debit_note\n"
        "- account_statement\n"
        "- renewal_notice\n\n"
        "Return ONLY the label text, no explanation.\n\n"
        f"Text:\n{text[:10000]}"
    )
    result = _ollama_post(
        "/api/generate",
        {"model": CHAT_MODEL, "prompt": prompt, "stream": False},
    )
    label = (result.get("response") or "").strip().lower()
    allowed = {"debit_note", "account_statement", "renewal_notice"}
    return label if label in allowed else ""


def extract_fields_from_pdf(pdf_bytes: bytes, doc_type: str) -> dict:
    """
    Extract fields using parser + LLM merge for noisy scanned docs.
    """
    cleaned_text = extract_best_text(pdf_bytes)
    if not cleaned_text:
        return {"error": "Could not extract meaningful text from PDF."}

    resolved_doc_type = doc_type
    if not resolved_doc_type or resolved_doc_type == "auto":
        resolved_doc_type = classify_document_type(cleaned_text)
    if not resolved_doc_type:
        return {"error": "Could not determine document type."}

    if resolved_doc_type == "account_statement":
        # Build on top of your dedicated account statement parser first.
        parsed = parse_account_statement_text(cleaned_text)
        parsed = _postprocess_account_statement(parsed, cleaned_text)
    else:
        parsed = parse_document(cleaned_text, resolved_doc_type)
    llm_fields = extract_structured_data_with_ollama(cleaned_text, resolved_doc_type)

    if isinstance(parsed, dict) and isinstance(llm_fields, dict):
        for key, value in llm_fields.items():
            if key in parsed and _is_missing_value(parsed.get(key)) and (not _is_missing_value(value)):
                parsed[key] = value

    parsed["_resolved_doc_type"] = resolved_doc_type
    return parsed


def answer_question_from_pdf(pdf_bytes: bytes, question: str) -> dict:
    """
    RAG-lite flow:
    1) Extract PDF text
    2) Chunk + embed
    3) Retrieve top-k chunks
    4) Ask chat model using retrieved context
    """
    if not question or not question.strip():
        raise ValueError("Question is required.")

    raw_text = extract_best_text(pdf_bytes)
    if not raw_text:
        raise ValueError("Could not extract meaningful text from PDF.")

    page_text = extract_text_by_page(pdf_bytes)
    cleaned_pages = []
    for p in page_text:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        cleaned = clean_text_with_ollama(text)
        cleaned_pages.append({"page": p["page"], "text": cleaned or text})

    chunks_with_page = chunk_pages(cleaned_pages) if cleaned_pages else []
    if not chunks_with_page:
        chunks_with_page = [{"page": None, "text": c} for c in chunk_text(raw_text)]
    if not chunks_with_page:
        raise ValueError("No useful text chunks were produced from PDF.")

    # For summarization prompts, skip retrieval and summarize full cleaned text.
    q_lower = question.lower()
    if "summarize" in q_lower or "summary" in q_lower:
        answer = _chat_with_context(question=question, context=raw_text[:12000])
        return {"answer": answer, "top_chunks": [raw_text[:12000]]}

    chunk_vectors = _embed_many([c["text"] for c in chunks_with_page])
    question_vector = _embed_many([question.strip()])[0]

    scored: List[Tuple[float, dict]] = []
    for vec, chunk in zip(chunk_vectors, chunks_with_page):
        score = _cosine_similarity(question_vector, vec)
        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:3]
    top_chunks = [item[1]["text"] for item in top]
    context = "\n\n---\n\n".join(top_chunks)
    top_score = top[0][0] if top else 0.0
    confidence = "high" if top_score >= 0.55 else "medium" if top_score >= 0.40 else "low"

    answer = _chat_with_context(question=question, context=context)

    return {
        "answer": answer,
        "top_chunks": top_chunks,
        "sources": [
            {
                "page": item[1].get("page"),
                "score": round(item[0], 4),
                "snippet": item[1].get("text", "")[:240],
            }
            for item in top
        ],
        "confidence": confidence,
    }
