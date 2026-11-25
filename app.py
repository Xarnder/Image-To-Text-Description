import argparse
from collections import OrderedDict
from contextlib import asynccontextmanager
import csv
from functools import lru_cache
import io
import json
import os
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field

from jobs import JobManager
from storage import CHARACTER_REFERENCE_GUIDANCE, Store, prepare_settings, scan_folder


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder: str
    recursive: bool = True
    preset: str = "pose"
    prompt: str = Field(min_length=1, max_length=32000)
    system_prompt: str = Field(default="", max_length=16000)
    model_path: str
    max_tokens: int = Field(default=384, ge=1, le=32768)
    output_label: str = "pose"
    output_directory: str = ""
    write_txt: bool = True
    character_reference: bool = False
    gender_neutral: bool = False
    force: bool = False
    keep_loaded: bool = False


class ScanRequest(BaseModel):
    folder: str
    recursive: bool = True


@lru_cache(maxsize=192)
def thumbnail(path, modified, edge):
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
        image.thumbnail((edge, edge))
        image = Image.alpha_composite(Image.new("RGBA", image.size, "white"), image).convert("RGB")
        handle = io.BytesIO()
        image.save(handle, format="JPEG", quality=85)
    return handle.getvalue()


def create_app(config=None, data_directory=None, engine=None):
    config = config or json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    presets = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    store = Store(Path(data_directory or ROOT / "data") / "batches.sqlite3")
    manager = JobManager(store, config["runtime_directory"], engine=engine)
    session = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    cookie_name = "caption_studio_" + str(config["port"])
    scans = OrderedDict()
    scan_lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(application):
        manager.start()
        yield
        manager.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.manager = manager
    app.state.shutdown = None

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        try:
            host = urlsplit("http://" + request.headers.get("host", "")).hostname
        except ValueError:
            host = None
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return JSONResponse({"detail": "This app accepts local connections only."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin requests are not allowed."}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            if request.cookies.get(cookie_name) != session:
                return JSONResponse({"detail": "Reload the app to reconnect."}, status_code=401)
            if request.method not in {"GET", "HEAD"} and request.headers.get("x-csrf-token") != csrf:
                return JSONResponse({"detail": "Missing local session token. Reload the app."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'")
        if request.url.path.startswith("/api/") and "/thumbnail" not in request.url.path:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid_value(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.get("/")
    def index():
        response = FileResponse(ROOT / "dist" / "index.html", headers={"Cache-Control": "no-store"})
        response.set_cookie(cookie_name, session, httponly=True, samesite="strict")
        return response

    @app.get("/api/health")
    def health():
        return {"app": "local-image-captioner", "version": "1.0", "status": "ready"}

    @app.get("/api/bootstrap")
    def bootstrap():
        return {"config": config, "presets": presets, "csrf": csrf,
                "character_reference_guidance": CHARACTER_REFERENCE_GUIDANCE,
                "jobs": store.jobs(), "worker": manager.state()}

    @app.get("/api/state")
    def state():
        return {"jobs": store.jobs(), "worker": manager.state()}

    @app.get("/api/folders")
    def folders(path: str = ""):
        if not path:
            if os.name == "nt":
                import ctypes
                mask = ctypes.windll.kernel32.GetLogicalDrives()
                drives = [chr(65 + i) + ":\\" for i in range(26) if mask & (1 << i)]
            else:
                drives = [str(Path.home()), "/"]
            return {"path": "", "parent": None, "folders": [{"name": p, "path": p} for p in drives]}
        folder = Path(path).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("That folder does not exist.")
        try:
            children = sorted((p for p in folder.iterdir() if p.is_dir() and not p.is_symlink()),
                              key=lambda p: p.name.casefold())
        except OSError as error:
            raise ValueError("This folder cannot be opened: " + str(error)) from error
        return {"path": str(folder), "parent": str(folder.parent) if folder.parent != folder else "",
                "folders": [{"name": p.name, "path": str(p)} for p in children]}

    @app.post("/api/scan")
    def scan(payload: ScanRequest):
        folder, files, warnings = scan_folder(payload.folder, payload.recursive)
        scan_id = uuid.uuid4().hex
        with scan_lock:
            scans[scan_id] = {"folder": folder, "files": files}
            while len(scans) > 8:
                scans.popitem(last=False)
        return {"id": scan_id, "folder": folder, "total": len(files), "warnings": warnings}

    def get_scan(scan_id):
        with scan_lock:
            if scan_id not in scans:
                raise HTTPException(404, "This preview expired. Scan the folder again.")
            return scans[scan_id]

    @app.get("/api/scans/{scan_id}/items")
    def scan_items(scan_id: str, offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100)):
        scan = get_scan(scan_id)
        return {"total": len(scan["files"]), "items": [
            {**item, "id": offset + i, "status": "ready", "caption": "",
             "thumbnail": f"/api/scans/{scan_id}/{offset+i}/thumbnail"}
            for i, item in enumerate(scan["files"][offset:offset+limit])]}

    def image_response(path, root, edge):
        path = Path(path).resolve()
        if not path.is_relative_to(Path(root).resolve()):
            raise HTTPException(403, "The image is outside the selected folder.")
        try:
            data = thumbnail(str(path), path.stat().st_mtime_ns, edge)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            raise HTTPException(400, "Image preview unavailable: " + str(error)) from error
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})

    @app.get("/api/scans/{scan_id}/{item_index}/thumbnail")
    def scan_thumbnail(scan_id: str, item_index: int):
        scan = get_scan(scan_id)
        if not 0 <= item_index < len(scan["files"]):
            raise HTTPException(404, "Image not found.")
        return image_response(scan["files"][item_index]["path"], scan["folder"], 420)

    @app.post("/api/jobs")
    def create_job(payload: BatchRequest):
        settings = prepare_settings(payload.model_dump(), presets)
        folder, files, warnings = scan_folder(settings["folder"], settings["recursive"])
        if not files:
            raise ValueError("No supported images were found in this folder.")
        settings["folder"] = folder
        settings["scan_warnings"] = warnings
        job_id = store.create(settings, files)
        manager.wake.set()
        return store.job(job_id)

    def get_job(job_id):
        job = store.job(job_id)
        if job is None:
            raise HTTPException(404, "Batch not found.")
        return job

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return get_job(job_id)

    @app.get("/api/jobs/{job_id}/items")
    def items(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100)):
        job = get_job(job_id)
        return {"total": job["total"], "items": [
            {**item, "thumbnail": f"/api/items/{item['id']}/thumbnail"}
            for item in store.items(job_id, offset, limit)]}

    @app.post("/api/jobs/{job_id}/{action}")
    def job_action(job_id: str, action: str):
        get_job(job_id)
        manager.action(job_id, action)
        return store.job(job_id)

    @app.get("/api/items/{item_id}")
    def item(item_id: int):
        result = store.item(item_id)
        if result is None:
            raise HTTPException(404, "Image not found.")
        return result

    @app.get("/api/items/{item_id}/thumbnail")
    def item_thumbnail(item_id: int):
        result = item(item_id)
        return image_response(result["path"], get_job(result["job_id"])["settings"]["folder"], 420)

    @app.get("/api/items/{item_id}/image")
    def item_image(item_id: int):
        result = item(item_id)
        return image_response(result["path"], get_job(result["job_id"])["settings"]["folder"], 1600)

    @app.get("/api/jobs/{job_id}/export")
    def export(job_id: str, format: str = "json"):
        job = get_job(job_id)
        results = store.items(job_id, 0, job["total"])
        if format == "json":
            content = json.dumps({"batch": job, "images": results}, ensure_ascii=False, indent=2)
            media = "application/json"
        elif format == "csv":
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow(["image", "status", "description", "error", "json_file", "text_file"])
            for result in results:
                values = [result[k] for k in ("relative", "status", "caption", "error", "output_json", "output_txt")]
                writer.writerow(["'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v for v in values])
            content = "\ufeff" + buffer.getvalue()
            media = "text/csv"
        else:
            raise HTTPException(400, "Choose JSON or CSV.")
        return Response(content, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="captions-{job_id[:8]}.{format}"'})

    @app.post("/api/model/unload")
    def unload():
        if manager.state()["active_job"]:
            raise HTTPException(409, "Pause the active batch and wait for its current image to finish first.")
        manager.release_requested.set()
        manager.wake.set()
        return {"status": "releasing"}

    @app.post("/api/shutdown")
    def shutdown():
        if manager.state()["active_job"]:
            raise HTTPException(409, "Pause or cancel the active batch before stopping the app.")
        if app.state.shutdown:
            threading.Timer(0.3, app.state.shutdown).start()
        return {"status": "stopping"}

    app.mount("/assets", StaticFiles(directory=ROOT / "dist", check_dir=False), name="assets")
    return app


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if args.port:
        config["port"] = args.port
    application = create_app(config=config)
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=config["port"], log_level="info"))
    application.state.shutdown = lambda: setattr(server, "should_exit", True)
    server.run()
