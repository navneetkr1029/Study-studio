"""FastAPI application: file extraction + streaming generation."""
import json
from typing import List, Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import extractors, llm, pipeline
from .config import settings

app = FastAPI(title="Study Studio API", version="1.0.0")

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    # No max_length on purpose: the pipeline handles text of any size.
    text: str = ""
    mode: Literal["summary", "qa", "flashcards", "custom"] = "summary"
    prompt: str = ""
    level: str = Field(default="high school", max_length=60)
    count: Optional[int] = Field(default=None, ge=1, le=100)


@app.get("/")
async def root():
    return {"name": "Study Studio API", "docs": "/docs", "health": "/api/health"}


@app.get("/api/health")
async def health():
    return await llm.health()


@app.post("/api/extract")
async def extract_files(files: List[UploadFile] = File(...)):
    """Read text out of one or more uploaded files (PDF, TXT, MD, CSV, images)."""
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    results = []
    for f in files:
        name = f.filename or "file"
        data = await f.read()
        if len(data) > max_bytes:
            results.append({"name": name, "error": f"File is larger than {settings.max_upload_mb:g} MB."})
            continue
        try:
            text = await extractors.extract(name, data, f.content_type or "")
            results.append({"name": name, "text": text, "chars": len(text)})
        except (extractors.ExtractError, llm.LLMError) as exc:
            results.append({"name": name, "error": str(exc)})
        except Exception:  # never leak internals
            results.append({"name": name, "error": "Something went wrong while reading this file."})
    return {"files": results}


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """Stream newline-delimited JSON events: {"type": "progress"|"result"|"error", ...}."""
    if req.mode == "custom":
        if not req.prompt.strip():
            raise HTTPException(status_code=422, detail="Please type what you would like to generate.")
    elif not req.text.strip():
        raise HTTPException(status_code=422, detail="Please add some study content first.")

    async def events():
        try:
            async for ev in pipeline.run(req.text, req.mode, req.level, req.count, req.prompt):
                yield json.dumps(ev) + "\n"
        except llm.LLMError as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
        except Exception:
            yield json.dumps({"type": "error", "message": "Something went wrong while generating. Please try again."}) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
