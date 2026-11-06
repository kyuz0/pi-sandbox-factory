Document tools are installed in every profile, under /opt/document-tools/lib.
Use python or python3; system Python can import
these libraries directly. For another virtual environment, create it with
python3 -m venv --system-site-packages /opt/my-tools/.venv to inherit them.

- PDF: pypdf (including AES encryption), PyPDF2 (legacy compatibility),
  pymupdf/fitz, pdfplumber, pdfminer.six, pikepdf, reportlab, pdf2image, camelot.
  Import fitz from PyMuPDF; do not install the unrelated package named fitz.
- Word: python-docx (import docx), docxtpl, docx2txt, mammoth.
- Excel: openpyxl, xlsxwriter, pandas, xlrd/xlwt for .xls, pyxlsb,
  python_calamine for spreadsheet reading.
- PowerPoint: python-pptx (import pptx) for .pptx.
- Other formats: odfpy, striprtf, extract_msg, msoffcrypto, olefile,
  BeautifulSoup, lxml, markdown, markdownify, pypandoc, python-magic, Pillow.
- Commands: LibreOffice (soffice) for legacy .doc/.xls/.ppt conversion and
  Office-to-PDF rendering; pandoc; Poppler (pdftotext, pdfinfo, pdftoppm);
  Tesseract with English OCR data and the pytesseract Python interface.

For LibreOffice conversion use a separate temporary user profile per process:
soffice -env:UserInstallation=file:///tmp/unique-office-profile --headless
--convert-to pdf --outdir /tmp/output input.docx
Use temporary files for conversion and retain the original. OCR handles scanned
pages; PDF text extractors alone cannot recover text from image-only scans.
Package downloads happen at image build time; runtime network allowlists still apply.
