@app.post("/api/download")
async def download_video(req: DownloadRequest):
    file_id = str(uuid.uuid4())[:8]

    try:
        # Common options for all downloads
        common_opts = {
            "quiet": True,
            "no_warnings": True,
            # Add cookies if they exist
            "cookiefile": "cookies.txt" if os.path.exists("cookies.txt") else None,
            # Add user agent to look like a real browser
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            # Add throttling to avoid rate limits
            "sleep_interval": 5,
            "max_sleep_interval": 10,
            # Extract flat playlist (just single video)
            "extract_flat": "in_playlist",
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
            raise HTTPException(status_code=400, detail="YouTube bot protection triggered. Please try a different video or try again in 5 minutes.")
        elif "Private" in msg:
            raise HTTPException(status_code=400, detail="This video is private.")
        else:
            raise HTTPException(status_code=400, detail=f"Download failed: {str(e)[:200]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
