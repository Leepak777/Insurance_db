from ocr.debit_note_parser import parse_debit_note_text
from ocr.account_statement_parser import parse_account_statement_text
from ocr.renewal_notice_parser import parse_renewal_notice_text

def parse_document(raw_text: str, doc_type: str):
    if doc_type == "debit_note":
        return parse_debit_note_text(raw_text)
    if doc_type == "account_statement":
        return parse_account_statement_text(raw_text)
    if doc_type == "renewal_notice":
        return parse_renewal_notice_text(raw_text)
    raise ValueError(f"Unsupported document type: {doc_type}")
