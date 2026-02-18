import re
from typing import Dict, List
from datetime import datetime
PRIMARY_COPY = "manager"
FALLBACK_COPY = "agent"

# ==================================================
# NORMALIZATION (SAFE)
# ==================================================

def normalize_text(text: str) -> str:
    replacements = {
        # insurance terms
        "OOMEST1C": "DOMESTIC",
        "OOMESTIC": "DOMESTIC",
        "DQMESTIC": "DOMESTIC",
        "XELPER": "HELPER",

        # policy / account noise
        "Roz": "R03",
        "Ros": "R03",
        "ROZ": "R03",

        # account suffix
        "To1": "(T01)",
        "T01)": "(T01)",

        # COPY OCR noise (IMPORTANT)
        "CQPY": "COPY",
        "C0PY": "COPY",
        "COPV": "COPY",
        "COpy": "COPY",
        "CQRY": "COPY",
        "CQFY": "COPY",
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    return text



def extract_first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


# ==================================================
# HEADER EXTRACTION
# ==================================================

def extract_account_number_dn(text: str) -> str:
    m = re.search(
        r"ACC[O0Q]U?N?T\s+N[O0Q][.:;]?\s*([A-Z0-9 ()]+?)(?=\s+(POL|P0L|ENO|CLA)|\Z)",
        text,
        re.IGNORECASE
    )
    acc = m.group(1).strip() if m else ""
    return clean_account_number(acc)

def clean_account_number(acc: str) -> str:
    if not acc:
        return ""

    acc = acc.upper()
    # Fix common OCR mistakes
    acc = acc.replace("O", "0").replace("Q", "0").replace("S", "5")

    # Normalize (T01)
    acc = re.sub(r"\(+T01\)+", "(T01)", acc)

    # Extract base account number, add (T01) if exists
    m = re.search(r"([A-Z0-9]{6,10})\s*(\(T01\))?", acc)
    return f"{m.group(1)} (T01)" if m else acc

def extract_policy_number(text: str) -> str:
    return extract_first(
        r"POLICY\s+N[O0Q][.:;]?\s*([A-Z0-9\-]{10,})",
        text
    )

def extract_endorsement_number_dn(text: str) -> str:
    raw = re.search(
        r"ENO+R[S5]?\s*(?:N[O0Q])?[.:;]?\s*([A-Z0-9\-_ ]+)",
        text,
        re.IGNORECASE
    )
    raw = raw.group(1).strip() if raw else ""
    return clean_endorsement_number(raw)


def clean_endorsement_number(raw: str) -> str:
    if not raw:
        return ""

    raw = raw.upper()
    # Stop at keywords to avoid overcapture
    raw = re.split(r"(CLASS|POLICY|ACC)\b", raw)[0]

    # Remove spaces, underscores, repeated hyphens
    raw = re.sub(r"[\s_]+", "", raw)
    raw = re.sub(r"-+", "-", raw)

    # Fix common OCR errors
    raw = raw.replace("TNOV", "NOV").replace("TNO", "NOV").replace("RNOV", "NOV")

    # Ensure dash between month and number if missing
    m = re.match(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)([A-Z]?)(\d{1,4})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}{m.group(3)}".replace("--", "-")

    return raw

def extract_insured_or_agent(text: str) -> str:
    m = re.search(
        r"(?:INSURED|CUSTOMER)\s+([A-Z ]{6,40})",
        text
    )
    if not m:
        return ""

    name = m.group(1).strip()
    # hard stop before FLAT / ROOM / FLOOR
    name = re.split(r"\bFLAT\b|\bROOM\b|\bFLOOR\b", name)[0]
    return name.strip()

def extract_insurance_class(text: str) -> str:
    m = re.search(
        r"CLAS[S]?\s*([0-9OQ]{2,3})[- ]*([A-Z ]+HELPER)",
        text,
        re.IGNORECASE
    )
    if not m:
        return ""

    code = m.group(1).replace("O", "0").replace("Q", "0")
    cls = m.group(2).upper()
    cls = cls.replace("OOMESTIC", "DOMESTIC").replace("DQMESTIC", "DOMESTIC")
    cls = cls.replace("XELPER", "HELPER")

    return f"{code} {cls}"

# ==================================================
# FINANCIAL EXTRACTION (MANAGER COPY)
# ==================================================

def extract_manager_financials(text: str) -> List[Dict]:
    if not re.search(r"GROSS\s+PREMIUM", text, re.IGNORECASE):
        return []

    nums = re.findall(r"\b\d{2,4}[., ]?\d{0,2}\b", text)
    values = []

    for n in nums:
        n = n.replace(" ", "").replace(",", ".")
        try:
            v = float(n)
            if v > 50:
                values.append(v)
        except:
            pass

    if len(values) < 5:
        return []

    gross = values[-5]
    commission = values[-4]
    overriding = values[-3]
    cost = values[-2]
    profit = values[-1]

    copy_types = detect_copy_types(text)
    if not copy_types:
        copy_types = {"manager"}  # safe default

    results = []
    for c in copy_types:
        results.append({
            "gross_premium": gross,
            "commission": commission,
            "overriding_insurer": overriding,
            "cost": cost,
            "profit": profit,
            "category": c
        })

    return results

def detect_copy_types(text: str) -> set[str]:
    patterns = {
        "manager": r"MANAG[EA]R\s*C[O0]P[YV]",
        "agent": r"AGENT\s*C[O0]P[YV]",
        "account": r"ACCOUNT\s*C[O0]P[YV]",
        "file": r"FILE\s*C[O0]P[YV]",
    }

    found = set()
    for key, pat in patterns.items():
        if re.search(pat, text, re.IGNORECASE):
            found.add(key)

    return found

def split_by_copy(text: str) -> List[str]:
    blocks = []
    current = []

    for line in text.splitlines():
        if "COPY" in line.upper():
            if current:
                blocks.append("\n".join(current))
                current = []
        current.append(line)

    if current:
        blocks.append("\n".join(current))

    return blocks


def is_valid_financial_block(block: str) -> bool:
    b = block.upper()

    # must contain financial headers
    if not re.search(r"GROSS\s+PREMIUM", b):
        return False

    # reject phone/fax heavy blocks
    if re.search(r"\bTEL\b|\bFAX\b", b):
        return False

    # reject address-heavy blocks
    if b.count("ROOM") > 2 or b.count("STREET") > 2:
        return False

    return True


# ==================================================
# MAIN PARSER
# ==================================================

def parse_debit_note_text(raw_text: str, insured_or_agent: str = "") -> Dict:
    text = normalize_text(raw_text)
    print("---------- NORMALIZED TEXT ----------")
    #print(text)
    result = {
        "account_number": extract_account_number_dn(text),
        "policy_number": extract_policy_number(text),
        "endorsement_number": extract_endorsement_number_dn(text),
        "insured_or_agent": extract_insured_or_agent(text) or insured_or_agent,
        "issue_date": extract_first(
            r"DATE[:;]?\s*(\d{1,2}\s+\w+\s+\d{4})", text
        ),
        "insurance_class": extract_insurance_class(text),
        "financials": extract_manager_financials(text),
    }
    result["account_number"] = clean_account_number(
        extract_account_number_dn(text)
    )
    result["insurance_class"] = (
        result["insurance_class"]
        .replace("0O3", "003")
        .replace("O03", "003")
        .replace("0o3", "003")
    )

    raw_endorsement = extract_endorsement_number_dn(text)
    result["endorsement_number"] = clean_endorsement_number(raw_endorsement)


    return result
