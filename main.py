from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

# Create FastAPI app FIRST
app = FastAPI()

# Create downloads directory
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Mount static files (if static folder exists)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    """Serve the frontend"""
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"message": "SnapLoad API is running"}

@app.get("/healthz")
async def health_check():
    """Health check endpoint for Render"""
    return {"status": "ok"}

class DownloadRequest(BaseModel):
    url: str
    format: str  # "mp4" or "mp3"
    quality: str = "best"

@app.post("/api/info")
async def get_info(req: DownloadRequest):
    """Get video info without downloading"""
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            # Add cookies if available
            "cookiefile": "cookies.txt" if os.path.exists("cookies.txt") else None,
            # Mimic a real browser
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
            raise HTTPException(status_code=400, detail="YouTube bot protection. Try again in 5 minutes or use Instagram/Vimeo instead.")
        raise HTTPException(status_code=400, detail=error_msg[:200])

@app.post("/api/download")
async def download_video(req: DownloadRequest):
    """Download video and return file link"""
    file_id = str(uuid.uuid4())[:8]

    try:
        # Common options for all downloads
        common_opts = {
            "quiet": True,
            "no_warnings": True,
            "cookiefile": "cookies.txt" if os.path.exists("cookies.txt") else None,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "sleep_interval": 3,  # Be nice to YouTube
            "max_sleep_interval": 5,
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
            # Video quality mapping
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

        # Find the downloaded file
        files = list(DOWNLOAD_DIR.glob(f"{file_id}.*"))
        if not files:
            raise HTTPException(status_code=500, detail="Download failed")

        filename = files[0].name
        ext = files[0].suffix

        # Schedule file deletion after 10 minutes
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
            raise HTTPException(status_code=400, detail="YouTube anti-bot protection. Please try an Instagram Reel instead (works perfectly!)")
        elif "Private" in msg:
            raise HTTPException(status_code=400, detail="This video is private")
        elif "copyright" in msg.lower():
            raise HTTPException(status_code=400, detail="This video is copyright restricted")
        else:
            raise HTTPException(status_code=400, detail=f"Download failed: {msg[:150]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

@app.get("/api/file/{filename}")
async def serve_file(filename: str):
    """Serve the downloaded file"""
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found or expired")
    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/octet-stream",
    )

async def delete_file_later(path: Path, delay: int):
    """Delete file after delay seconds"""
    await asyncio.sleep(delay)
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass
