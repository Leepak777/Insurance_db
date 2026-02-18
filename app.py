# app.py
from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify
from db import (
    insert_debit_note,
    insert_account_statement,
    insert_renewal_notice,
    fetch_all_documents,
    fetch_debit_note_by_id,
    fetch_account_statement_by_id,
    fetch_renewal_notice_by_id
)
import io
import sys
import os
import webbrowser
import threading
import fitz
from PIL import Image
import numpy as np
import easyocr

if getattr(sys, 'frozen', False):
    # Running from PyInstaller bundle
    template_dir = os.path.join(sys._MEIPASS, 'templates')
    static_dir = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
else:
    # Running normally
    app = Flask(__name__)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'xlsx', 'txt'}


# ---------------- HELPERS ----------------
def allowed_file(filename):
    return (
        filename and
        '.' in filename and
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def first(form, key, default=''):
    return form.get(key, [default])[0]


# ---------------- DOWNLOAD FILE ----------------
@app.route('/download/<doc_type>/<int:doc_id>')
def download_file(doc_type, doc_id):
    if doc_type == 'debit_note':
        doc = fetch_debit_note_by_id(doc_id)
    elif doc_type == 'account_statement':
        doc = fetch_account_statement_by_id(doc_id)
    elif doc_type == 'renewal_notice':
        doc = fetch_renewal_notice_by_id(doc_id)
    else:
        return "Unknown document type", 400

    if not doc:
        return "File not found", 404
    if not doc.get('file_data'):
        return "No file attached", 404

    filename = doc.get('file_name') or f"{doc_type}_{doc_id}.bin"

    return send_file(
        io.BytesIO(doc['file_data']),
        as_attachment=True,
        download_name=filename
    )


# ---------------- INDEX ----------------
@app.route('/', methods=['GET'])
def index():
    doc_type = request.args.get('doc_type', 'all')
    sort_by = request.args.get('sort_by', 'id')
    sort_order = request.args.get('sort_order', 'asc')

    filter_fields = request.args.getlist('filter_field[]')
    filter_ops = request.args.getlist('filter_op[]')
    filter_values = request.args.getlist('filter_value[]')

    filters = []
    filters_zipped = []

    for f, op, v in zip(filter_fields, filter_ops, filter_values):
        if f and op and v:
            filters.append({'field': f, 'op': op, 'value': v})
            filters_zipped.append((f, op, v))

    data = fetch_all_documents(
        doc_type=doc_type,
        filters=filters,
        sort_by=sort_by,
        sort_order=sort_order
    )

    return render_template(
        'index.html',
        data=data,
        doc_type=doc_type,
        sort_by=sort_by,
        sort_order=sort_order,
        filters_zipped=filters_zipped
    )


# ---------------- CREATE DOCUMENT ----------------
@app.route('/create/<doc_type>', methods=['GET', 'POST'])
def create_doc(doc_type):
    if request.method == 'GET':
        # Provide full default main_data to avoid NoneType errors in template
        main_data = {
            "issue_date": "",
            "insured_or_agent": "",
            "insured": "",
            "insurance_class": "",
            "policy_number": "",
            "endorsement_number": "",
            "account_number": "",
            "expiry_date": "",
            "ac_code": "",
            "total_earning": 0,
            "renewal_premium": 0,
            "uploaded_by": "",
            "file_name": "",
            "file_data": None,
            "financials": [],
            "entries": []
        }
        return render_template(
            'create.html',
            doc_type=doc_type or "",
            main_data=main_data
        )

    form = request.form.to_dict(flat=False)
    file = request.files.get('document_file')

    file_name = None
    file_data = None

    if file and file.filename:
        if not allowed_file(file.filename):
            return "Invalid file type", 400
        file_name = file.filename
        file_data = file.read()

    try:
        uploaded_by = first(form, 'uploaded_by', '')

        # -------- DEBIT NOTE --------
        if doc_type == 'debit_note':
            main_data = {
                'issue_date': first(form, 'issue_date', ''),
                'insured_or_agent': first(form, 'insured_or_agent', ''),
                'insurance_class': first(form, 'insurance_class', ''),
                'policy_number': first(form, 'policy_number', ''),
                'endorsement_number': first(form, 'endorsement_number', ''),
                'account_number': first(form, 'account_number', ''),
                'uploaded_by': uploaded_by,
                'file_name': file_name,
                'file_data': file_data
            }

            financials = []
            for i, category in enumerate(form.get('category[]', [])):
                if not category.strip():
                    continue
                financials.append({
                    'category': category,
                    'gross_premium': form.get('gross_premium[]', [''])[i],
                    'commission': form.get('commission[]', [''])[i],
                    'overriding_insurer': form.get('overriding_insurer[]', [''])[i],
                    'cost': form.get('cost[]', [''])[i],
                    'profit': form.get('profit[]', [''])[i]
                })

            insert_debit_note(main_data, financials)

        # -------- ACCOUNT STATEMENT --------
        elif doc_type == 'account_statement':
            main_data = {
                'issue_date': first(form, 'issue_date', ''),
                'address': first(form, 'address', ''),
                'account_number': first(form, 'account_number', ''),
                'total_premium_due': first(form, 'total_premium_due', ''),
                'premium_due_date': first(form, 'premium_due_date', ''),
                'uploaded_by': uploaded_by,
                'file_name': file_name,
                'file_data': file_data
            }

            entries = []
            for i, eff in enumerate(form.get('effective_date[]', [])):
                if not eff.strip():
                    continue
                entries.append({
                    'effective_date': eff,
                    'debit_note': form.get('debit_note[]', [''])[i],
                    'policy_number': form.get('policy_number[]', [''])[i],
                    'premium': form.get('premium[]', [''])[i]
                })

            insert_account_statement(main_data, entries)

        # -------- RENEWAL NOTICE --------
        elif doc_type == 'renewal_notice':
            main_data = {
                'issue_date': first(form, 'issue_date', ''),
                'insured': first(form, 'insured', ''),
                'insurance_class': first(form, 'insurance_class', ''),
                'policy_number': first(form, 'policy_number', ''),
                'expiry_date': first(form, 'expiry_date', ''),
                'ac_code': first(form, 'ac_code', ''),
                'total_earning': first(form, 'total_earning', '0'),
                'renewal_premium': first(form, 'renewal_premium', '0'),
                'uploaded_by': uploaded_by,
                'file_name': file_name,
                'file_data': file_data
            }

            entries = []
            for i, label in enumerate(form.get('label[]', [])):
                if not label.strip():
                    continue
                entries.append({
                    'label': label,
                    'amount': form.get('amount[]', [''])[i]
                })

            insert_renewal_notice(main_data, entries)

        else:
            return "Unknown document type", 400

        return redirect(url_for('index'))

    except Exception as e:
        return f"Error: {e}", 500

@app.route('/delete/<doc_type>/<int:doc_id>', methods=['POST'])
def delete_doc(doc_type, doc_id):
    from db import delete_debit_note, delete_account_statement, delete_renewal_notice

    try:
        if doc_type == 'debit_note':
            delete_debit_note(doc_id)
        elif doc_type == 'account_statement':
            delete_account_statement(doc_id)
        elif doc_type == 'renewal_notice':
            delete_renewal_notice(doc_id)
        else:
            return "Unknown document type", 400
        return redirect(url_for('index'))
    except Exception as e:
        return f"Error: {e}", 500

@app.route('/edit/<doc_type>/<int:doc_id>', methods=['GET', 'POST'])
def edit_doc(doc_type, doc_id):
    from db import fetch_all_documents, update_debit_note, update_account_statement, update_renewal_notice

    # Fetch existing document
    if doc_type == 'debit_note':
        main_data = fetch_debit_note_by_id(doc_id)
    elif doc_type == 'account_statement':
        main_data = fetch_account_statement_by_id(doc_id)
    elif doc_type == 'renewal_notice':
        main_data = fetch_renewal_notice_by_id(doc_id)
    else:
        return "Unknown document type", 400

    if not main_data:
        return "Document not found", 404

    if request.method == 'GET':
        # Ensure sub-entry lists exist so template loops never break
        if doc_type == 'debit_note':
            main_data.setdefault('financials', [])
        else:
            main_data.setdefault('entries', [])

        # Also ensure all expected keys exist
        defaults = {
            "issue_date": "", "insured_or_agent": "", "insured": "", "insurance_class": "",
            "policy_number": "", "endorsement_number": "", "account_number": "",
            "expiry_date": "", "ac_code": "", "total_earning": 0, "renewal_premium": 0,
            "uploaded_by": "", "file_name": "", "file_data": None
        }
        for k, v in defaults.items():
            main_data.setdefault(k, v)

        return render_template('create.html', doc_type=doc_type, main_data=main_data)

    # POST → update
    form = request.form.to_dict(flat=False)
    file = request.files.get('document_file')

    file_name = main_data.get('file_name')
    file_data = main_data.get('file_data')

    if file and file.filename:
        if not allowed_file(file.filename):
            return "Invalid file type", 400
        file_name = file.filename
        file_data = file.read()

    uploaded_by = first(form, 'uploaded_by', '')

    try:
        if doc_type == 'debit_note':
            main_data_update = {
                'id': doc_id,
                'issue_date': first(form, 'issue_date', ''),
                'insured_or_agent': first(form, 'insured_or_agent', ''),
                'insurance_class': first(form, 'insurance_class', ''),
                'policy_number': first(form, 'policy_number', ''),
                'endorsement_number': first(form, 'endorsement_number', ''),
                'account_number': first(form, 'account_number', ''),
                'uploaded_by': uploaded_by,
                'file_name': file_name,
                'file_data': file_data
            }
            financials = []
            for i, category in enumerate(form.get('category[]', [])):
                if not category.strip():
                    continue
                financials.append({
                    'category': category,
                    'gross_premium': form.get('gross_premium[]', [''])[i],
                    'commission': form.get('commission[]', [''])[i],
                    'overriding_insurer': form.get('overriding_insurer[]', [''])[i],
                    'cost': form.get('cost[]', [''])[i],
                    'profit': form.get('profit[]', [''])[i]
                })
            update_debit_note(main_data_update, financials)

        elif doc_type == 'account_statement':
            main_data_update = {
                'id': doc_id,
                'issue_date': first(form, 'issue_date', ''),
                'address': first(form, 'address', ''),
                'account_number': first(form, 'account_number', ''),
                'total_premium_due': first(form, 'total_premium_due', ''),
                'premium_due_date': first(form, 'premium_due_date', ''),
                'uploaded_by': uploaded_by,
                'file_name': file_name,
                'file_data': file_data
            }
            entries = []
            for i, eff in enumerate(form.get('effective_date[]', [])):
                if not eff.strip():
                    continue
                entries.append({
                    'effective_date': eff,
                    'debit_note': form.get('debit_note[]', [''])[i],
                    'policy_number': form.get('policy_number[]', [''])[i],
                    'premium': form.get('premium[]', [''])[i]
                })
            update_account_statement(main_data_update, entries)

        elif doc_type == 'renewal_notice':
            main_data_update = {
                'id': doc_id,
                'issue_date': first(form, 'issue_date', ''),
                'insured': first(form, 'insured', ''),
                'insurance_class': first(form, 'insurance_class', ''),
                'policy_number': first(form, 'policy_number', ''),
                'expiry_date': first(form, 'expiry_date', ''),
                'ac_code': first(form, 'ac_code', ''),
                'total_earning': first(form, 'total_earning', '0'),
                'renewal_premium': first(form, 'renewal_premium', '0'),
                'uploaded_by': uploaded_by,
                'file_name': file_name,
                'file_data': file_data
            }
            entries = []
            for i, label in enumerate(form.get('label[]', [])):
                if not label.strip():
                    continue
                entries.append({
                    'label': label,
                    'amount': form.get('amount[]', [''])[i]
                })
            update_renewal_notice(main_data_update, entries)

        else:
            return "Unknown document type", 400

        return redirect(url_for('index'))

    except Exception as e:
        return f"Error: {e}", 500


# ---------------- SCAN PDF ----------------
from ocr.document_parser import parse_document
from ocr.ocr_utils import ocr_pdf_to_text
reader = None

@app.route('/scan_pdf', methods=['POST'])
def scan_pdf():
    file = request.files.get('document_file')
    existing_file_url = request.form.get('existing_file_url')
    doc_type = request.form.get('doc_type', '')

    if file:
        pdf_bytes = file.read()
    elif existing_file_url:
        # Fetch the existing PDF from your preview route
        from urllib.request import urlopen
        pdf_bytes = urlopen(existing_file_url).read()
    else:
        return jsonify({"error": "Please upload a PDF file"}), 400

    try:
        raw_text = ocr_pdf_to_text(pdf_bytes)
        data = parse_document(raw_text, doc_type)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/preview/<doc_type>/<int:doc_id>')
def preview_pdf(doc_type, doc_id):
    from flask import send_file
    from io import BytesIO
    from db import fetch_debit_note_by_id, fetch_account_statement_by_id, fetch_renewal_notice_by_id

    if doc_type == 'debit_note':
        doc = fetch_debit_note_by_id(doc_id)
    elif doc_type == 'account_statement':
        doc = fetch_account_statement_by_id(doc_id)
    elif doc_type == 'renewal_notice':
        doc = fetch_renewal_notice_by_id(doc_id)
    else:
        return "Unknown doc type", 400

    if not doc or not doc.get('file_data'):
        return "File not found", 404

    return send_file(
        BytesIO(doc['file_data']),
        download_name=doc['file_name'],
        mimetype='application/pdf',
        as_attachment=False  # open in browser
    )


def open_browser():
    webbrowser.open("http://127.0.0.1:5000/")

if __name__ == '__main__':
    # Open the browser after a short delay so Flask is ready
    threading.Timer(1, open_browser).start()
    app.run(debug=False)
    
