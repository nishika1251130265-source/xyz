import markdown2
from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Load and convert Markdown file
markdown_file = 'CBSE_English_Questions_Organized.md'
with open(markdown_file, 'r', encoding='utf-8') as f:
    markdown_content = f.read()

# Convert Markdown to HTML
html_content = markdown2.markdown(markdown_content)

# Create a Word document
doc = Document()
# Add HTML content as paragraphs
for line in html_content.splitlines():
    doc.add_paragraph(line)

# Save the Word document
docx_filename = 'CBSE_English_Questions_Organized.docx'
doc.save(docx_filename)

# Create a PDF file
pdf_filename = 'CBSE_English_Questions_Organized.pdf'
c = canvas.Canvas(pdf_filename, pagesize=letter)
width, height = letter
c.drawString(100, height - 100, 'CBSE English Questions Organized')
for i, line in enumerate(html_content.splitlines()):
    c.drawString(100, height - 120 - (i * 20), line)

c.save()