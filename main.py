from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI()

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Serve frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")


class DownloadRequest(BaseModel):
    url: str
    format: str  # "mp4" or "mp3"
    quality: str = "best"  # "best", "720", "480", "360"


@app.post("/api/info")
async def get_info(req: DownloadRequest):
    """Get video info before downloading."""
    try:
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
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
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/download")
async def download_video(req: DownloadRequest):
    """Download video/audio and return download link."""
    file_id = str(uuid.uuid4())[:8]

    try:
        if req.format == "mp3":
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": str(DOWNLOAD_DIR / f"{file_id}.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "quiet": True,
                "no_warnings": True,
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
                "format": quality_map.get(req.quality, quality_map["best"]),
                "outtmpl": str(DOWNLOAD_DIR / f"{file_id}.%(ext)s"),
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
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
        if "Private" in msg or "private" in msg:
            raise HTTPException(status_code=400, detail="This video is private.")
        elif "copyright" in msg.lower():
            raise HTTPException(status_code=400, detail="This video is copyright restricted.")
        else:
            raise HTTPException(status_code=400, detail="Could not download. Check the URL and try again.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/file/{filename}")
async def serve_file(filename: str):
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found or expired.")
    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/octet-stream",
    )


async def delete_file_later(path: Path, delay: int):
    await asyncio.sleep(delay)
    try:
        path.unlink()
    except Exception:
        pass
