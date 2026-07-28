import io
import os

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
            import fitz
            file_bytes = file.read()
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                return "".join(page.get_text() for page in doc)
        except Exception as e:
            raise ValueError(f"Failed to parse PDF document. File may be corrupted or encrypted: {str(e)}")

    elif is_docx:
        try:
            from docx import Document
            file_bytes = file.read()
            with io.BytesIO(file_bytes) as file_stream:
                document = Document(file_stream)
                text = "\n".join([para.text for para in document.paragraphs])
            return text
        except Exception as e:
            raise ValueError(f"Failed to parse DOCX document. File may be corrupted or invalid: {str(e)}")

    else:
        try:
            file_bytes = file.read()
            return file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError("Failed to read file. The document is binary or not valid UTF-8 text.")
        except Exception as e:
            raise ValueError(f"Error reading file content: {str(e)}")

