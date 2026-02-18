from ocr_utils import local_ocr_pdf_to_text
from document_parser import parse_document

def scan_pdf_local(pdf_path, doc_type):
    raw_text = local_ocr_pdf_to_text(pdf_path)

    print("---------- RAW TEXT ----------")
    print(raw_text)

    parsed = parse_document(raw_text, doc_type)

    print("\n---------- PARSED OUTPUT ----------")
    print(parsed)


if __name__ == "__main__":
    #scan_pdf_local(
    #    pdf_path="20251111110318532(1).pdf",
    #    doc_type="debit_note"
    #)
    #scan_pdf_local(
    #    pdf_path="20251111110325145(1).pdf",
    #    doc_type="renewal_notice"
    #)
    scan_pdf_local(
        pdf_path="20251111110330603(1).pdf",
        doc_type="account_statement"
    )

