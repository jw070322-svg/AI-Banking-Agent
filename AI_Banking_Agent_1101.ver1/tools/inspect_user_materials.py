from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from pypdf import PdfReader

source = Path(r'D:\weixin_file\xwechat_files\wxid_n0t7qvlbfnod22_7a73\temp\RWTemp\2026-10\d680665f8d81969b50581d31214ace92')
out = Path(__file__).resolve().parents[1] / 'reports'
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
with ZipFile(next(source.glob('*.docx'))) as z:
    root = ET.fromstring(z.read('word/document.xml'))
    lines = [''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in root.findall('.//w:p', ns)]
(out / 'user_attachment_docx.txt').write_text('\n'.join(line for line in lines if line.strip()), encoding='utf-8')
pdf = PdfReader(next(source.glob('*.pdf')))
(out / 'user_attachment_pdf.txt').write_text('\n\n'.join(f'--- Page {i+1} ---\n{p.extract_text() or ""}' for i,p in enumerate(pdf.pages)), encoding='utf-8')
print(f'docx paragraphs: {len(lines)}; pdf pages: {len(pdf.pages)}')
