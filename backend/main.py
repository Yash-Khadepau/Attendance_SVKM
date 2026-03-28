import io

from fastapi import FastAPI, File, HTTPException, UploadFile
import pdfplumber

from backend.parser import (
    structure_rows,
    aggregate_attendance,
    compute_bunk_buffer,
)

app = FastAPI()


def extract_text_from_pdf(file) -> list[str]:
    lines: list[str] = []

    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                lines.extend(line.strip() for line in page_text.splitlines() if line.strip())

    return lines


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

    try:
        content = await file.read()
        pdf_stream = io.BytesIO(content)
        lines = extract_text_from_pdf(pdf_stream)
        rows = structure_rows(lines)
        stats = aggregate_attendance(rows)
        final = compute_bunk_buffer(stats)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to process PDF: {exc}") from exc

    return final
