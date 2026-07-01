"""Long-form source upload and short variant generation API."""
import os
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile

from app.config import get_settings
from app.models.schemas import VariantGenerationResponse, VariantUploadResponse, VariantUrlRequest
from app.services import entitlements, variants
from app.tenant import owner_from_user

router = APIRouter()


@router.post("/upload", response_model=VariantUploadResponse)
async def upload_source_video(request: Request, file: UploadFile = File(...)):
    entitlements.require_feature(
        request,
        "variant",
        rights_required=True,
        metadata={"kind": "source_upload", "filename": file.filename or ""},
    )
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix and suffix not in variants.SAFE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload a video file")

    upload_id = variants.new_upload_id()
    path = variants.upload_path(upload_id, file.filename)
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    written = 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds {get_settings().max_upload_mb} MB limit",
                    )
                out.write(chunk)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    finally:
        await file.close()
    variants.register_source(upload_id, os.path.basename(path), path=path)
    return {"upload_id": upload_id, "filename": os.path.basename(path)}


@router.post("/from-url", response_model=VariantUploadResponse)
async def create_source_from_url(req: VariantUrlRequest, request: Request):
    entitlements.require_feature(
        request,
        "download",
        rights_required=True,
        metadata={"kind": "variant_source_url", "url": req.url},
    )
    try:
        source = await variants.create_source_from_url(req.url)
        return {"upload_id": source["upload_id"], "filename": source["filename"]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/from-url/start")
async def start_source_download(req: VariantUrlRequest, background_tasks: BackgroundTasks, request: Request):
    entitlements.require_feature(
        request,
        "download",
        rights_required=True,
        metadata={"kind": "variant_source_url", "url": req.url, "background": True},
    )
    try:
        source = variants.start_source_download(req.url)
        background_tasks.add_task(
            variants.download_source_job,
            source["upload_id"],
            source["url"],
            owner_from_user(getattr(request.state, "user", None)),
        )
        return source
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{upload_id}/source-status")
async def get_source_download_status(upload_id: str, request: Request):
    try:
        return variants.get_source_status(upload_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{upload_id}/generate", response_model=VariantGenerationResponse)
async def generate_source_variants(upload_id: str, request: Request):
    entitlements.require_feature(
        request,
        "variant",
        quantity=10,
        rights_required=True,
        metadata={"upload_id": upload_id, "requested_variants": 10},
    )
    try:
        return await variants.generate_variants(upload_id, count=10)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
