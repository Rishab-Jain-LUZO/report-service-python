from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date
from config import settings
from tasks import generic_export_task, celery_app
from celery.result import AsyncResult
from core.registry import CATEGORY_REGISTRY

app = FastAPI(title="Luzo Universal Report Service", version="1.0.0")

# Security header validation
API_KEY_NAME = "X-Report-Service-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def validate_service_token(api_key: str = Security(api_key_header)):
    if not api_key or api_key != settings.api_secret_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing service token"
        )
    return api_key

class ExportRequest(BaseModel):
    category: str
    reports: List[str]
    startDate: Optional[date] = None
    endDate: Optional[date] = None
    email: EmailStr

    model_config = {
        "extra": "allow"
    }

@app.post("/api/v1/export", dependencies=[Depends(validate_service_token)])
async def trigger_universal_export(payload: ExportRequest):
    # Check if category is supported by registry
    if payload.category not in CATEGORY_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category '{payload.category}' is not supported. Supported: {list(CATEGORY_REGISTRY.keys())}"
        )
        
    # Verify that requested reports exist in the selected category registry
    category_reports = CATEGORY_REGISTRY[payload.category]
    for r in payload.reports:
        if r not in category_reports:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Report '{r}' not found under category '{payload.category}'. Supported: {list(category_reports.keys())}"
            )
            
    # Format payload parameters for Celery task
    task_payload = payload.model_dump()
    if payload.startDate:
        task_payload["startDate"] = payload.startDate.isoformat()
    if payload.endDate:
        task_payload["endDate"] = payload.endDate.isoformat()
    
    # Trigger Celery queue task
    task = generic_export_task.delay(task_payload)
    
    return {
        "status": "success",
        "message": f"Export process for '{payload.category}' initiated successfully.",
        "task_id": task.id
    }

@app.get("/api/v1/export/status/{task_id}")
async def get_export_task_status(task_id: str):
    res = AsyncResult(task_id, app=celery_app)
    if res.state == 'PENDING':
        return {
            "status": "pending",
            "progress": 0,
            "message": "Task is waiting in queue."
        }
    elif res.state == 'PROGRESS':
        return {
            "status": "in_progress",
            "progress": res.info.get('progress', 0) if isinstance(res.info, dict) else 0,
            "message": res.info.get('status', '') if isinstance(res.info, dict) else str(res.info)
        }
    elif res.state == 'SUCCESS':
        return {
            "status": "completed",
            "progress": 100,
            "message": "Export completed successfully.",
            "result": res.result
        }
    elif res.state == 'FAILURE':
        return {
            "status": "failed",
            "progress": 0,
            "message": str(res.info)
        }
    else:
        return {
            "status": res.state.lower(),
            "progress": 0,
            "message": str(res.info)
        }
