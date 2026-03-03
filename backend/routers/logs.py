from fastapi import APIRouter
import os

router = APIRouter(prefix="/api/logs", tags=["logs"])

@router.get("/sip")
async def get_sip_logs(lines: int = 100):
    try:
        log_path = "api.log"
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.readlines()
                return {"logs": [l.strip() for l in content[-lines:]]}
        return {"logs": ["No hay logs acumulados en api.log."]}
    except Exception as e:
        return {"error": str(e)}
