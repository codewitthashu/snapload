# SnapLoad — Free Video Downloader

YouTube + Instagram → MP4 / MP3 downloader. Free hosting on Render.com.

## Files
```
snapload/
├── main.py           ← FastAPI backend
├── static/
│   └── index.html    ← Frontend website
├── requirements.txt
├── render.yaml       ← Render deployment config
└── README.md
```

## Deploy Free on Render.com (5 minutes)

### Step 1 — Put files on GitHub (free)
1. Go to https://github.com and sign up (free)
2. Click "New repository" → name it `snapload` → Create
3. Upload all these files to the repo

### Step 2 — Deploy on Render (free)
1. Go to https://render.com and sign up with GitHub (free)
2. Click "New" → "Web Service"
3. Connect your GitHub repo `snapload`
4. Settings will auto-fill from render.yaml
5. Click "Create Web Service"
6. Wait 2-3 minutes for build to finish
7. Your site is live at: https://snapload.onrender.com

## Run Locally (for testing)
```
pip install -r requirements.txt
uvicorn main:app --reload
```
Open http://localhost:8000

## Free Tier Limits on Render
- Sleeps after 15 min of no traffic (wakes up in ~30 sec)
- 750 hours/month free (enough for 24/7)
- To never sleep: upgrade to $7/month paid plan

## Scale to Big Numbers (still free)
When you get lots of users, move to Railway.app:
1. Go to https://railway.app
2. Deploy same GitHub repo
3. $5 free credit every month
4. Auto-scales with traffic
