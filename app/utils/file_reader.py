import io

def read_file(file):
    if file.content_type == "application/pdf":
        import fitz
        file_bytes = file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    elif file.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        from docx import Document
        file_bytes = file.read()
        with io.BytesIO(file_bytes) as file_stream:
            document = Document(file_stream)
            text = "\n".join([para.text for para in document.paragraphs])
        return text
    else:
        return file.read().decode('utf-8')
