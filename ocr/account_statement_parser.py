from typing import Dict, List
import re
from datetime import datetime

# -----------------------------
# OCR FIXES
# -----------------------------
TEXT_OCR_CORRECTIONS = [
    ('i1', '11'), ('Noyember', 'November'), ('20z5', '2025'),
    ('EOWARD', 'EDWARD'), ('LEYEL', 'LEVEL'),
    ('MQNGKOK', 'MONGKOK'), ('MONGKOX', 'MONGKOK'),
    ('XQWLOON', 'KOWLOON'), ('XOWI_OON_', 'KOWLOON'),
    ('S2E', 'SZE')
]

NUMERIC_OCR_CORRECTIONS = [
    ('O', '0'), ('Q', '0'), ('l', '1'), ('I', '1'),
    ('7o', '70'), ('QQ', '00')
]

def apply_ocr_corrections(text: str, numeric_only=False) -> str:
    for wrong, correct in TEXT_OCR_CORRECTIONS:
        text = text.replace(wrong, correct)
    if numeric_only:
        for wrong, correct in NUMERIC_OCR_CORRECTIONS:
            text = text.replace(wrong, correct)
    return text

# -----------------------------
# DATE PARSING
# -----------------------------
def extract_issue_date(text: str) -> str:
    text = apply_ocr_corrections(text)
    m = re.search(r'Issued Date\s*[:：]?\s*.*?(\d{1,2}\s+[A-Za-z]+\s+\d{4})', text, re.IGNORECASE)
    if m:
        try:
            return datetime.strptime(m.group(1), '%d %B %Y').strftime('%Y-%m-%d')
        except:
            pass
    return ''

def extract_premium_due_date(text: str) -> str:
    text = apply_ocr_corrections(text)
    # find the line before "PREMIUM DUE DATE" for the date
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if 'PREMIUM DUE DATE' in line.upper() and i > 0:
            date_line = lines[i-1].strip()
            try:
                return datetime.strptime(date_line, '%d %B %Y').strftime('%Y-%m-%d')
            except:
                date_line = apply_ocr_corrections(date_line)
                try:
                    return datetime.strptime(date_line, '%d %B %Y').strftime('%Y-%m-%d')
                except:
                    pass
    # fallback
    return extract_issue_date(text)

# -----------------------------
# ADDRESS
# -----------------------------
def extract_address(text: str) -> str:
    lines = text.splitlines()
    address_lines = []
    capture = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Start capturing **after the actual issue date line**
        if re.match(r'\d{1,2}\s+[A-Za-z]+\s+\d{4}', line):
            capture = True
            continue
        # Stop capturing once we hit "EFFECTIVE DATE"
        if 'EFFECTIVE DATE' in line:
            break
        if capture:
            address_lines.append(line)
    return ' '.join(address_lines)

# -----------------------------
# ACCOUNT NUMBER
# -----------------------------
def extract_account_number(text: str) -> str:
    text = apply_ocr_corrections(text)
    m = re.search(r'ACCOUNT NUMBER\s*[:：]?\s*([A-Z0-9]+)', text, re.IGNORECASE)
    return m.group(1) if m else 'N/A'

# ---------------------------------------
# GLOBAL OCR CLEAN
# ---------------------------------------
def clean_global_ocr(text):
    replacements = {
        'T,': 'TJ',
        'Tj': 'TJ',
        't,': 'TJ',
        'T.': 'TJ',
        'PFF25o': 'PFF250',
        'Ro': 'R0',
        'Q': '0',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


# ---------------------------------------
# CLEAN NUMERIC (nature & premium)
# ---------------------------------------
def clean_number(raw: str):
    if not raw:
        return 0.0

    raw = raw.strip()

    # Detect spaced thousand pattern like: 1 296 20
    spaced_match = re.match(r'^(\d)\s+(\d{3})\s+(\d{2})$', raw)
    if spaced_match:
        return float(
            spaced_match.group(1)
            + spaced_match.group(2)
            + "."
            + spaced_match.group(3)
        )

    # Fix OCR mistakes
    s = raw.replace("Q", "0")
    s = s.replace("O", "0")
    s = s.replace("l", "1")

    # Remove spaces
    s = re.sub(r"\s+", "", s)

    # Remove commas
    s = s.replace(",", "")

    # Keep only digits and dot
    s = re.sub(r"[^0-9.]", "", s)

    try:
        return float(s)
    except:
        return 0.0


# ---------------------------------------
# EXTRACT POLICY + NATURE
# ---------------------------------------
def extract_policy_nature_pairs(big_row_text):
    pairs = []

    # Match: policy_token  number)
    pattern = re.compile(
        r'([A-Za-z0-9,\-]+)\s+([\dOQol.,]+)\)',
        re.IGNORECASE
    )

    for match in pattern.finditer(big_row_text):
        policy_raw = match.group(1)
        nature_raw = match.group(2)

        # Clean policy OCR
        policy = (
            policy_raw
            .replace(" ", "")
            .replace(",", "")
            .replace("o", "0")
            .replace("O", "0")
            .replace("l", "1")
        )

        # Clean nature OCR
        nature = (
            nature_raw
            .replace("O", "0")
            .replace("Q", "0")
            .replace("o", "0")
            .replace("l", "1")
            .replace(",", "")
        )

        try:
            nature = float(nature)
        except:
            nature = 0.0

        pairs.append({
            "policy_number": policy,
            "nature": nature
        })

    return pairs
# ---------------------------------------
# EXTRACT DATE + DEBIT + PREMIUM (STATE PARSER)
# ---------------------------------------

def extract_header_premium_from_block(text):
    """
    Extract the first numeric line that comes before the first date/debit pair.
    This is the premium for the initial header entry.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    date_pattern = re.compile(r'^\d{2}/\d{2}/\d{4}$')
    debit_pattern = re.compile(r'^B[\w\-?]+$', re.IGNORECASE)

    for i, line in enumerate(lines):
        # If this line is a date, we have reached structured entries
        if date_pattern.match(line):
            # Look one line above for the header premium
            if i > 0:
                prev_line = lines[i-1]
                if re.search(r'\d', prev_line):
                    return clean_number(prev_line)
            break

    return 0.0

def extract_header_entry(text):
    """
    Extract the very first entry in the header:
    EFFECTIVE DATE DEBIT NOTE NO. ...
    And the first premium between the header and the next debit date block.
    """
    # Find the header line
    header_match = re.search(
        r'EFFECTIVE\s+DATE\s+DEBIT\s+NOTE\s+NO\.\s*(\d{2}/\d{2}/\d{4})\s+(B[\w\-?]+)',
        text,
        re.IGNORECASE
    )
    if not header_match:
        return None

    entry = {
        "effective_date": header_match.group(1),
        "debit_note": header_match.group(2),
        "premium": extract_header_premium_from_block(text)
    }

    return entry

def extract_date_debit_premium(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    entries = []

    date_pattern = re.compile(r'^\d{2}/\d{2}/\d{4}$')
    debit_pattern = re.compile(r'^B[\w\-?]+$', re.IGNORECASE)

    i = 0
    while i < len(lines):
        line = lines[i]

        if date_pattern.match(line):

            entry = {
                "effective_date": line,
                "debit_note": None,
                "premium": 0.0
            }

            # Next line should be debit
            if i + 1 < len(lines) and debit_pattern.match(lines[i + 1]):
                entry["debit_note"] = lines[i + 1]
                i += 1

            # Next line might be premium
            if i + 1 < len(lines):
                next_line = lines[i + 1]

                # If next line is NOT another date and NOT debit → treat as premium
                if (not date_pattern.match(next_line)
                        and not debit_pattern.match(next_line)):

                    if re.search(r'\d', next_line):
                        entry["premium"] = clean_number(next_line)
                        i += 1

            entries.append(entry)

        i += 1

    return entries


# ---------------------------------------
# MAIN PARSER
# ---------------------------------------
def parse_entries(normalized_text):
    text = clean_global_ocr(normalized_text)
    entries = []

    # Extract policy + nature block
    big_row_match = re.search(
        r'PREM[1I]UM\s*(.*?)(?:T[O0]TAL)\s+HXS',
        text,
        re.DOTALL | re.IGNORECASE
    )

    policy_nature_pairs = []
    if big_row_match:
        big_row = big_row_match.group(1)
        policy_nature_pairs = extract_policy_nature_pairs(big_row)

    structured_entries = []

    # first header entry
    header_entry = extract_header_entry(text)
    if header_entry:
        structured_entries.append(header_entry)

    # remaining column entries
    structured_entries.extend(extract_date_debit_premium(text))

    # Align by index
    for i in range(len(structured_entries)):

        policy = None
        nature = None

        if i < len(policy_nature_pairs):
            policy = policy_nature_pairs[i]["policy_number"]
            nature = policy_nature_pairs[i]["nature"]

        entries.append({
            "effective_date": structured_entries[i]["effective_date"],
            "debit_note": structured_entries[i]["debit_note"],
            "policy_number": policy,
            "nature": nature,
            "premium": structured_entries[i]["premium"]
        })

    return entries

# -----------------------------
# MAIN PARSER
# -----------------------------
def parse_account_statement_text(raw_text: str, insured_or_agent: str = "") -> Dict:
    text = apply_ocr_corrections(raw_text)
    print("---------- NORMALIZED TEXT ----------")
    print(text)
    issue_date = extract_issue_date(text)
    premium_due_date = extract_premium_due_date(text)
    account_number = extract_account_number(text)
    address = extract_address(text)
    entries = parse_entries(text)
    total_premium_due = round(
    sum(e['premium'] for e in entries if isinstance(e.get('premium'), (int, float))),
    2
)

    if total_premium_due == 0.0:
        total_premium_due = round(sum(e.get('premium', 0) for e in entries), 2)

    warnings = []
    if any(not e.get('policy_number') for e in entries):
        warnings.append("Some policy numbers missing or unreliable.")

    return {
        'issue_date': issue_date,
        'premium_due_date': premium_due_date,
        'account_number': account_number,
        'address': address,
        'total_premium_due': total_premium_due,
        'entries': entries,
        'warnings': warnings
    }