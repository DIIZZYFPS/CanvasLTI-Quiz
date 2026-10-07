import io
import os
from .docx_reader import extract_docx_paragraphs
from .text_utils import join_docx_paragraphs

def read_file(file):
    if not file or not getattr(file, 'filename', None):
        raise ValueError("No file provided.")

    filename = file.filename.lower()
    ext = os.path.splitext(filename)[1]
    content_type = getattr(file, 'content_type', '') or ''

    is_pdf = content_type == "application/pdf" or ext == ".pdf"
    is_docx = (
        content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or ext == ".docx"
    )
    is_text = (
        content_type.startswith("text/")
        or ext in {".txt", ".md", ".text"}
    )

    if not (is_pdf or is_docx or is_text):
        if ext in {".doc", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar", ".png", ".jpg", ".jpeg"}:
            raise ValueError(f"Unsupported file format '{ext}'. Please convert to .txt, .pdf, or .docx before uploading.")
        elif ext:
            raise ValueError(f"Unsupported file type '{ext}'. Supported formats: .pdf, .docx, .txt, .md")
        else:
            raise ValueError("Unsupported file type. Supported formats: .pdf, .docx, .txt, .md")

    if is_pdf:
        try:
            import pymupdf  # `fitz` is the deprecated alias and warns on import
            file_bytes = file.read()
            with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
                return "".join(page.get_text() for page in doc)
        except Exception as e:
            raise ValueError(f"Failed to parse PDF document. File may be corrupted or encrypted: {str(e)}")

    elif is_docx:
        try:
            from docx import Document
            file_bytes = file.read()
            with io.BytesIO(file_bytes) as file_stream:
                document = Document(file_stream)
                # Rebuilds auto-numbered list labels and includes table text; plain
                # `para.text` has neither (see docx_reader).
                paragraphs = extract_docx_paragraphs(document)
            return join_docx_paragraphs(paragraphs)
        except Exception as e:
            raise ValueError(f"Failed to parse DOCX document. File may be corrupted or invalid: {str(e)}")

    else:
        try:
            file_bytes = file.read()
            # utf-8-sig: Windows Notepad's "UTF-8" option prepends a byte-order mark, which as plain
            # utf-8 stays in the text as an invisible character and defeats the first question's
            # prefix match ("Essay:", "SA:", "1.") and leaks into its text.
            return file_bytes.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError("Failed to read file. The document is binary or not valid UTF-8 text.")
        except Exception as e:
            raise ValueError(f"Error reading file content: {str(e)}")

