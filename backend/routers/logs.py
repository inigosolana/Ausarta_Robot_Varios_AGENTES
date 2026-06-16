import os
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fpdf import FPDF

from services.auth import CurrentUser, get_current_user, require_superadmin
from services.supabase_service import supabase

router = APIRouter(tags=["logs"])


def _pdf_text(value: object) -> str:
    text = str(value or "")
    return text.encode("latin-1", "replace").decode("latin-1")


@router.get("/api/logs/sip")
async def get_sip_logs(
    lines: int = 100,
    current_user: CurrentUser = Depends(require_superadmin),
):
    try:
        log_path = "api.log"
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.readlines()
                return {"logs": [l.strip() for l in content[-lines:]]}
        return {"logs": ["No hay logs acumulados en api.log."]}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/calls/{encuesta_id}/transcript.pdf")
async def download_transcript_pdf(
    encuesta_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    res = (
        supabase.table("encuestas")
        .select("id, empresa_id, fecha, telefono, transcripcion, transcription, datos_extra")
        .eq("id", encuesta_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")

    row = res.data[0]
    empresa_id = row.get("empresa_id")
    if current_user.role != "superadmin" and current_user.empresa_id != empresa_id:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    empresa_res = (
        supabase.table("empresas")
        .select("nombre")
        .eq("id", empresa_id)
        .limit(1)
        .execute()
    )
    empresa_nombre = (
        empresa_res.data[0].get("nombre")
        if empresa_res.data
        else f"Empresa {empresa_id}"
    )

    transcript = row.get("transcripcion") or row.get("transcription") or ""
    datos_extra = row.get("datos_extra") or {}
    if not isinstance(datos_extra, dict):
        datos_extra = {}

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _pdf_text(empresa_nombre), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, _pdf_text(f"Fecha: {row.get('fecha') or ''}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, _pdf_text(f"Numero llamado: {row.get('telefono') or ''}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Transcript", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)

    transcript_lines = str(transcript).splitlines() or [str(transcript)]
    for line in transcript_lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        pdf.multi_cell(0, 6, _pdf_text(cleaned))

    if datos_extra:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Datos extra", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for key, value in datos_extra.items():
            pdf.multi_cell(0, 6, _pdf_text(f"{key}: {value}"))

    pdf_bytes = pdf.output(dest="S")
    if isinstance(pdf_bytes, str):
        pdf_bytes = pdf_bytes.encode("latin-1")
    buffer = BytesIO(bytes(pdf_bytes))
    filename = f"transcript_{encuesta_id}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename=\"{filename}\"'},
    )
