import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageFilter
import numpy as np
import easyocr

_reader = None


def get_reader():
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(
            ['en'],
            gpu=False  # deterministic
        )
    return _reader


def preprocess_image(img: Image.Image) -> Image.Image:
    """
    Fax-safe preprocessing:
    - grayscale
    - autocontrast
    - denoise
    - mild sharpen
    """
    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img, cutoff=2)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    img = img.filter(ImageFilter.SHARPEN)
    return img


def ocr_pdf_to_text(pdf_bytes: str) -> str:
    """
    Convert PDF → OCR text using high DPI render.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    ocr = get_reader()
    full_text = ""

    for page in doc:
        zoom = 300 / 72  # 300 DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = Image.frombytes(
            "RGB",
            [pix.width, pix.height],
            pix.samples
        )

        img = preprocess_image(img)

        result = ocr.readtext(
            np.array(img),
            detail=0,
            paragraph=True,
            contrast_ths=0.1,
            adjust_contrast=0.5
        )

        if result:
            full_text += "\n".join(result) + "\n"

    return full_text


def local_ocr_pdf_to_text(pdf_path: str) -> str:
    """
    Convert PDF → OCR text using high DPI render.
    """
    doc = fitz.open(pdf_path)
    ocr = get_reader()
    full_text = ""

    for page in doc:
        zoom = 300 / 72  # 300 DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = Image.frombytes(
            "RGB",
            [pix.width, pix.height],
            pix.samples
        )

        img = preprocess_image(img)

        result = ocr.readtext(
            np.array(img),
            detail=0,
            paragraph=True,
            contrast_ths=0.1,
            adjust_contrast=0.5
        )

        if result:
            full_text += "\n".join(result) + "\n"

    return full_text
