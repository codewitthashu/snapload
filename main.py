from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

class DownloadRequest(BaseModel):
    url: str
    format: str = "mp4"
    quality: str = "best"

@app.post("/api/info")
async def get_info(req: DownloadRequest):
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
            return {
                "title": info.get("title", "Unknown"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", ""),
                "platform": info.get("extractor_key", ""),
            }
    except Exception as e:
        error_msg = str(e)
        if "Sign in to confirm" in error_msg:
            raise HTTPException(status_code=400, detail="YouTube bot protection. Try Instagram Reels instead!")
        raise HTTPException(status_code=400, detail=error_msg[:200])

@app.post("/api/download")
async def download_video(req: DownloadRequest):
    file_id = str(uuid.uuid4())[:8]
    
    try:
        common_opts = {
            "quiet": True,
            "no_warnings": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        if req.format == "mp3":
            ydl_opts = {
                **common_opts,
                "format": "bestaudio/best",
                "outtmpl": str(DOWNLOAD_DIR / f"{file_id}.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
        else:
            quality_map = {
                "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "720": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
                "480": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best",
                "360": "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best",
            }
            ydl_opts = {
                **common_opts,
                "format": quality_map.get(req.quality, quality_map["best"]),
                "outtmpl": str(DOWNLOAD_DIR / f"{file_id}.%(ext)s"),
                "merge_output_format": "mp4",
            }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            title = info.get("title", "video")
        
        files = list(DOWNLOAD_DIR.glob(f"{file_id}.*"))
        if not files:
            raise HTTPException(status_code=500, detail="Download failed")
        
        filename = files[0].name
        ext = files[0].suffix
        
        asyncio.create_task(delete_file_later(files[0], delay=600))
        
        return {
            "success": True,
            "filename": f"{title[:50]}{ext}",
            "download_url": f"/api/file/{filename}",
            "title": title,
        }
        
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "Sign in to confirm" in msg:
            raise HTTPException(status_code=400, detail="YouTube anti-bot protection. Try Instagram Reel instead!")
        elif "Private" in msg:
            raise HTTPException(status_code=400, detail="This video is private")
        else:
            raise HTTPException(status_code=400, detail=f"Download failed: {msg[:150]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

@app.get("/api/file/{filename}")
async def serve_file(filename: str):
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found or expired")
    return FileResponse(path=filepath, filename=filename, media_type="application/octet-stream")

async def delete_file_later(path: Path, delay: int):
    await asyncio.sleep(delay)
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass

@app.get("/privacy")
async def privacy_policy():
    return FileResponse("static/privacy.html")

@app.get("/terms")
async def terms_of_service():
    return FileResponse("static/terms.html")

@app.get("/refund")
async def refund_policy():
    return FileResponse("static/refund.html")

@app.get("/contact")
async def contact_page():
    return FileResponse("static/contact.html")

@app.get("/healthz")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"message": "SnapLoad API is running"}
