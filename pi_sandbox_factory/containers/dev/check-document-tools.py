"""Exercise document readers, writers, conversion, and OCR on harmless fixtures."""
import importlib
from pathlib import Path
import subprocess
import tempfile

for name in (
    'pypdf', 'PyPDF2', 'pymupdf', 'fitz', 'pdfplumber', 'pdfminer.high_level',
    'pikepdf', 'reportlab', 'pdf2image', 'pytesseract', 'camelot', 'docx',
    'docxtpl', 'docx2txt', 'mammoth', 'openpyxl', 'xlsxwriter', 'xlrd', 'xlwt',
    'pyxlsb', 'python_calamine', 'pandas', 'pptx', 'odf', 'striprtf.striprtf',
    'bs4', 'lxml', 'PIL', 'markdown', 'markdownify', 'pypandoc', 'msoffcrypto',
    'olefile', 'extract_msg', 'magic', 'tabulate',
):
    importlib.import_module(name)
subprocess.run(['python3', '-m', 'pip', 'check'], check=True)

with tempfile.TemporaryDirectory(prefix='document-check-') as temp:
    root = Path(temp)
    marker = 'DOCUMENT TOOLKIT CHECK'
    from reportlab.pdfgen import canvas
    pdf = root / 'sample.pdf'
    page = canvas.Canvas(str(pdf))
    page.setFont('Helvetica', 24)
    page.drawString(40, 750, marker)
    page.save()
    from pypdf import PdfReader, PdfWriter
    from PyPDF2 import PdfReader as LegacyReader
    import pymupdf
    import pdfplumber
    import pikepdf
    from pdfminer.high_level import extract_text
    assert marker in PdfReader(pdf).pages[0].extract_text()
    assert marker in LegacyReader(pdf).pages[0].extract_text()
    assert marker in extract_text(str(pdf))
    with pymupdf.open(pdf) as document:
        assert marker in document[0].get_text()
    with pdfplumber.open(pdf) as document:
        assert marker in document.pages[0].extract_text()
    with pikepdf.open(pdf) as document:
        assert len(document.pages) == 1
    writer = PdfWriter(clone_from=pdf)
    writer.encrypt('fixture-only', algorithm='AES-256')
    writer.write(root / 'encrypted.pdf')
    assert marker in PdfReader(root / 'encrypted.pdf', password='fixture-only').pages[0].extract_text()
    assert marker in subprocess.check_output(['pdftotext', str(pdf), '-'], text=True)
    from pdf2image import convert_from_path
    import pytesseract
    rendered = convert_from_path(pdf, dpi=150, first_page=1, last_page=1)
    assert marker in pytesseract.image_to_string(rendered[0], config='--psm 6')
    print('PASS PDF creation, six readers, AES encryption, Poppler rendering, and English OCR', flush=True)

    from docx import Document
    import docx2txt
    import mammoth
    from docxtpl import DocxTemplate
    word = root / 'word.docx'
    document = Document()
    document.add_paragraph('{{ message }}')
    document.save(word)
    template = DocxTemplate(word)
    template.render({'message': marker})
    template.save(word)
    assert marker in Document(word).paragraphs[0].text
    assert marker in docx2txt.process(word)
    with word.open('rb') as stream:
        assert marker in mammoth.extract_raw_text(stream).value

    import pandas as pd
    import openpyxl
    import xlrd
    import xlwt
    from python_calamine import CalamineWorkbook
    sheet = root / 'sheet.xlsx'
    with pd.ExcelWriter(sheet, engine='xlsxwriter') as excel:
        pd.DataFrame({'message': [marker], 'value': [42]}).to_excel(excel, index=False)
        excel.sheets['Sheet1'].set_column('A:A', 40)
    assert openpyxl.load_workbook(sheet).active['A2'].value == marker
    assert pd.read_excel(sheet).iloc[0]['value'] == 42
    with CalamineWorkbook.from_path(str(sheet)) as book:
        assert book.get_sheet_by_index(0).to_python()[1][0] == marker
    old = xlwt.Workbook()
    old.add_sheet('Data').write(0, 0, marker)
    old.save(str(root / 'legacy.xls'))
    assert xlrd.open_workbook(root / 'legacy.xls').sheet_by_index(0).cell_value(0, 0) == marker

    from pptx import Presentation
    slides = root / 'slides.pptx'
    deck = Presentation()
    deck.slides.add_slide(deck.slide_layouts[0]).shapes.title.text = marker
    deck.save(slides)
    assert Presentation(slides).slides[0].shapes.title.text == marker
    print('PASS DOCX templates/extraction, XLSX/XLS round trips, and PPTX round trip', flush=True)

    output = root / 'converted'
    output.mkdir()
    def office(extension, inputs, destination):
        subprocess.run(['soffice', '-env:UserInstallation=' + (root / 'office-profile').as_uri(),
                        '--headless', '--convert-to', extension, '--outdir', str(destination),
                        *map(str, inputs)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=120)
        for source in inputs:
            assert (destination / (source.stem + '.' + extension)).is_file(), source

    office('pdf', [word, sheet, slides], output)
    for source in (word, sheet, slides):
        text = ' '.join(' '.join(p.extract_text() for p in PdfReader(output / (source.stem + '.pdf')).pages).split())
        assert marker in text, (source.name, text)
    office('doc', [word], output)
    office('ppt', [slides], output)
    roundtrip = root / 'roundtrip'
    roundtrip.mkdir()
    office('docx', [output / 'word.doc'], roundtrip)
    office('pptx', [output / 'slides.ppt'], roundtrip)
    assert marker in Document(roundtrip / 'word.docx').paragraphs[0].text
    assert Presentation(roundtrip / 'slides.pptx').slides[0].shapes.title.text == marker
    import pypandoc
    assert marker in pypandoc.convert_text(marker, 'html', format='md')
    from striprtf.striprtf import rtf_to_text
    assert marker in rtf_to_text('{\\rtf1 ' + marker + '}')
    print('PASS Office-to-PDF rendering, legacy DOC/PPT conversion, Pandoc, and RTF', flush=True)
