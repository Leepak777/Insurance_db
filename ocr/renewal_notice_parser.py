import re
from typing import Dict, List
from datetime import datetime
# ================================
# TEXT NORMALIZATION
# ================================

def normalize_ocr_text(raw_text: str) -> str:
    """
    Preserve line structure, remove empty lines and trailing spaces
    """
    if not raw_text:
        return ""
    text = raw_text.replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    lines = [" ".join(line.split()) for line in lines]  # collapse inner spaces
    return "\n".join(lines)


# ================================
# SAFE REGEX EXTRACTORS
# ================================

def extract_first(pattern: str, text: str, flags=0) -> str:
    match = re.search(pattern, text, flags)
    if not match:
        return ""
    if match.lastindex:
        return match.group(1).strip()
    return match.group(0).strip()


def extract_date_after(label: str, text: str) -> str:
    pattern = rf"{label}.*?(\d{{2}}/\d{{2}}/\d{{4}})"
    return extract_first(pattern, text, re.IGNORECASE | re.DOTALL)


def extract_policy_number_r(text: str) -> str:
    match = re.search(r"POLICY\s*NO\.?\s*[:\-]?\s*([A-Z0-9\-]+)", text, re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).replace(" ", "").strip()


def extract_ac_code(text: str) -> str:
    return extract_first(r"ACICODE\s+([A-Z0-9]+)", text, re.IGNORECASE)


def extract_insured_name(text: str) -> str:
    start = re.search(r"\bINSURED\b", text, re.IGNORECASE)
    end = re.search(r"\bPOLICY\s*NO", text, re.IGNORECASE)
    if not start or not end:
        return ""
    segment = text[start.end():end.start()]
    segment = re.sub(r"CLASS\s+OF\s+INSURANCE", "", segment, flags=re.IGNORECASE)
    segment = re.split(r"\bROOM\b|\bBLOCK\b|\bFLAT\b|\bUNIT\b", segment, flags=re.IGNORECASE)[0]
    return segment.strip(" {").strip()


def extract_insurance_class_r(text: str) -> str:
    return extract_first(r"\bBUSINESS\s+INSURANCE\b", text, re.IGNORECASE)


# ================================
# MONEY CLEANING
# ================================

def clean_money(raw: str) -> float:
    if not raw:
        return 0.0
    raw = re.sub(r"[^\d\s,]", "", raw)  # remove OCR noise
    digits = re.findall(r"\d+", raw)
    if not digits:
        return 0.0
    return float("".join(digits))


def extract_total_earning(text: str) -> float:
    match = re.search(r"TOTAL.*?\n(.*)", text, re.IGNORECASE)
    if not match:
        return 0.0
    return clean_money(match.group(1))


def extract_renewal_premium(text: str) -> float:
    match = re.search(r"RENEWAL\s+PREMIUM.*?(\d[\d\s,]+)", text, re.IGNORECASE | re.DOTALL)
    return clean_money(match.group(1)) if match else 0.0


# ================================
# RENEWAL ENTRIES
# ================================
def fix_ocr_numbers(line: str) -> str:
    """
    Fix common OCR misreads in numeric strings.
    """
    # Map common OCR errors to likely digits
    corrections = {
        'Q': '0',
        'o': '0',
        'O': '0',
        'z': '2',
        'Z': '2',
        'l': '1',
        '|': '1',
        'I': '1',
    }
    for wrong, right in corrections.items():
        line = line.replace(wrong, right)
    return line
def extract_renewal_entries(text: str) -> List[Dict]:
    """
    Extract employee entries and their earnings from OCR text.
    Handles collapsed lines and associates each label with the correct amount.
    """

    # Extract block between EMPLOYEES and TOTAL
    block_match = re.search(r"EMPLOYEES.*?(?=TOTAL)", text, re.IGNORECASE | re.DOTALL)
    if not block_match:
        return []

    block = block_match.group(0)

    # Split block into lines
    lines = [line.strip() for line in block.split("\n") if line.strip()]

    # First line after EMPLOYEES contains labels
    labels_line = lines[1] if len(lines) > 1 else ""
    # Remove OCR artifacts
    labels_line_clean = re.sub(r"[^A-Za-z0-9\s\-/\(\)]", "", labels_line)

    # Split labels by numbers 1,2,3,4
    labels = re.split(r"\s(?=\d[\.\-]?)", labels_line_clean)
    labels = [l.strip() for l in labels if l.strip()]

    # Lines after labels_line until TOTAL are amounts
    # Lines after labels line contain amounts
    amount_lines = lines[2:]

    amounts = []
    for line in amount_lines:
        clean_line = fix_ocr_numbers(line)
        
        # Find all numbers (with commas or periods)
        num_strs = re.findall(r"[\d,]+\.\d+|[\d,]+", clean_line)
        
        # Pick the largest numeric value in the line
        if num_strs:
            # Remove commas
            num_strs_clean = [s.replace(",", "") for s in num_strs]
            # Convert to float and pick max
            nums = [float(s) for s in num_strs_clean]
            amount = max(nums)
        else:
            amount = 0.0

        amounts.append(amount)

    # Map labels to amounts
    entries = []
    for i, label in enumerate(labels):
        amount = amounts[i] if i < len(amounts) else 0.0
        entries.append({"label": label, "amount": amount})

    return entries
# ==================================================
# MAIN PARSER
# ==================================================

def parse_renewal_notice_text(raw_text: str, insured_or_agent: str = "") -> Dict:
    # Step 1: Normalize OCR
    text = normalize_ocr_text(raw_text)
    print("---------- NORMALIZED TEXT ----------")
    print(text)

    issue_date = extract_date_after("ISSUE DATE", text)
    expiry_date = extract_date_after("EXPIRY DATE", text)

    insured = extract_insured_name(text)
    insurance_class = extract_insurance_class_r(text)
    policy_number = extract_policy_number_r(text)
    ac_code = extract_ac_code(text)

    renewal_entries = extract_renewal_entries(text)
    total_earning = extract_total_earning(text)
    renewal_premium = extract_renewal_premium(text)

    return {
        "issue_date": issue_date,
        "insured": insured,
        "insurance_class": insurance_class,
        "policy_number": policy_number,
        "expiry_date": expiry_date,
        "ac_code": ac_code,
        "renewal_entries": renewal_entries,
        "total_earning": total_earning,
        "renewal_premium": renewal_premium,
        "uploaded_by": insured_or_agent
    }