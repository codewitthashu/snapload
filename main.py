from fastapi import FastAPI, HTTPException, Request, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional
import yt_dlp
import os
import uuid
import asyncio
import sqlite3
import secrets
import hashlib
import time
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime, timedelta
from passlib.context import CryptContext
from collections import defaultdict

# ===== FastAPI App =====
app = FastAPI()

# ===== CORS (for security) =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Security Setup =====
SECRET_KEY = secrets.token_urlsafe(32)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ===== OTP Storage =====
otp_storage = {}

# ===== Email Configuration - REPLACE WITH YOUR DETAILS =====
GMAIL_USER = "codewithashu74@gmail.com"  # ← CHANGE TO YOUR GMAIL
GMAIL_PASSWORD = "cxdd rydr jzrf vwbz"  # ← CHANGE TO YOUR 16-CHAR APP PASSWORD (remove spaces)

# ===== Cost Control System =====
class CostController:
    def __init__(self):
        self.daily_downloads = defaultdict(int)
        self.daily_costs = defaultdict(float)
        self.last_reset = time.time()
    
    def check_limits(self, user_id: str):
        now = time.time()
        if now - self.last_reset > 86400:
            self.daily_downloads.clear()
            self.daily_costs.clear()
            self.last_reset = now
        
        LIMITS = {
            "max_daily_downloads": 5000,
            "max_daily_cost_usd": 10.00,
            "max_downloads_per_user": 100,
        }
        
        total_downloads = sum(self.daily_downloads.values())
        if total_downloads >= LIMITS["max_daily_downloads"]:
            return False, "Daily download limit reached. Try again tomorrow."
        
        if self.daily_costs["total"] >= LIMITS["max_daily_cost_usd"]:
            return False, "System at capacity. Please try again later."
        
        if self.daily_downloads[user_id] >= LIMITS["max_downloads_per_user"]:
            return False, "Daily limit reached. Upgrade for unlimited downloads."
        
        return True, "OK"
    
    def record_download(self, user_id: str, file_size_mb: float = 5):
        self.daily_downloads[user_id] += 1
        bandwidth_cost = (file_size_mb / 1024) * 0.085
        compute_cost = 0.0001
        total_cost = bandwidth_cost + compute_cost
        self.daily_costs["total"] += total_cost
        self.daily_costs[user_id] = self.daily_costs.get(user_id, 0) + total_cost

cost_controller = CostController()

# ===== Database Setup =====
DB_PATH = "snapload.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            credits INTEGER DEFAULT 2,
            total_purchased INTEGER DEFAULT 0,
            total_used INTEGER DEFAULT 0
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            credits INTEGER NOT NULL,
            amount_inr INTEGER,
            payment_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            url TEXT,
            format TEXT,
            quality TEXT,
            file_size_mb REAL,
            downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ===== Helper Functions =====
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(days=30)
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (user_id, session_token, expires_at) VALUES (?, ?, ?)",
        (user_id, token, expires_at)
    )
    conn.commit()
    conn.close()
    return token

def get_user_by_session(session_token: str) -> Optional[dict]:
    conn = get_db()
    session = conn.execute(
        "SELECT user_id, expires_at FROM sessions WHERE session_token = ?",
        (session_token,)
    ).fetchone()
    if session and datetime.fromisoformat(session["expires_at"]) > datetime.now():
        user = conn.execute(
            "SELECT id, email, full_name, credits FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()
        conn.close()
        return dict(user)
    conn.close()
    return None

def get_device_fingerprint(request: Request) -> str:
    data = f"{request.headers.get('user-agent', '')}{request.client.host}"
    data += request.headers.get('accept-language', '')
    data += request.headers.get('sec-ch-ua', '')
    return hashlib.md5(data.encode()).hexdigest()

def send_email_otp(to_email: str, otp: str):
    """Send OTP via Gmail SMTP"""
    try:
        # Clean the app password (remove spaces if any)
        password_clean = GMAIL_PASSWORD.replace(" ", "")
        
        subject = "🔐 SnapLoad - Your Login OTP"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 500px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                <h2 style="color: #667eea;">Welcome to SnapLoad! 🎉</h2>
                <p>Your One-Time Password (OTP) is:</p>
                <div style="font-size: 32px; font-weight: bold; color: #764ba2; padding: 15px; background: #f0f0f0; border-radius: 8px; text-align: center;">
                    {otp}
                </div>
                <p>This OTP is valid for <strong>10 minutes</strong>.</p>
                <p>If you didn't request this, please ignore this email.</p>
                <hr>
                <p style="font-size: 12px; color: #888;">SnapLoad - Download Instagram Reels & YouTube Videos</p>
            </div>
        </body>
        </html>
        """
        
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, password_clean)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ OTP email sent to {to_email}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        print(f"📧 OTP for {to_email} (check console): {otp}")
        return False

# ===== Pydantic Models =====
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class DownloadRequest(BaseModel):
    url: str
    format: str = "mp4"
    quality: str = "best"

class PurchaseRequest(BaseModel):
    credits: int
    payment_id: str
    gateway: str = "razorpay"

class OTPRequest(BaseModel):
    email: EmailStr

class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str

# ============================================================
# ========== OTP ENDPOINTS (Passwordless Login) ==========
# ============================================================

@app.post("/api/send-otp")
async def send_otp(req: OTPRequest):
    """Send OTP to user's email"""
    try:
        otp = str(random.randint(100000, 999999))
        
        otp_storage[req.email] = {
            "otp": otp,
            "expires_at": datetime.now() + timedelta(minutes=10)
        }
        
        send_email_otp(req.email, otp)
        
        return {
            "success": True,
            "message": "OTP sent to your email"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send OTP: {str(e)}")

@app.post("/api/verify-otp")
async def verify_otp(req: OTPVerifyRequest):
    """Verify OTP and login/register user"""
    stored = otp_storage.get(req.email)
    if not stored:
        raise HTTPException(status_code=400, detail="OTP expired or not requested")
    
    if stored["otp"] != req.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    if datetime.now() > stored["expires_at"]:
        del otp_storage[req.email]
        raise HTTPException(status_code=400, detail="OTP expired")
    
    del otp_storage[req.email]
    
    conn = get_db()
    user = conn.execute(
        "SELECT id, email, full_name, credits FROM users WHERE email = ?",
        (req.email,)
    ).fetchone()
    
    if not user:
        random_password = secrets.token_urlsafe(16)
        password_hash = hash_password(random_password)
        conn.execute(
            "INSERT INTO users (email, password_hash, credits) VALUES (?, ?, 2)",
            (req.email, password_hash)
        )
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        credits = 2
        is_new_user = True
    else:
        user_id = user["id"]
        credits = user["credits"]
        is_new_user = False
    
    session_token = create_session(user_id)
    conn.commit()
    conn.close()
    
    response = JSONResponse({
        "success": True,
        "session_token": session_token,
        "credits": credits,
        "is_new_user": is_new_user,
        "user": {"email": req.email}
    })
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        max_age=2592000,
        path="/"
    )
    
    return response

# ============================================================
# ========== AUTH ENDPOINTS ==========
# ============================================================

@app.post("/api/signup")
async def signup(req: SignupRequest, request: Request):
    device_id = get_device_fingerprint(request)
    conn = get_db()
    existing_device = conn.execute("SELECT user_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
    if existing_device:
        conn.close()
        raise HTTPException(status_code=400, detail="Only one account per device allowed")
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (req.email,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash = hash_password(req.password)
    conn.execute("INSERT INTO users (email, password_hash, full_name, credits) VALUES (?, ?, ?, 2)", (req.email, password_hash, req.full_name))
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO devices (device_id, user_id) VALUES (?, ?)", (device_id, user_id))
    session_token = create_session(user_id)
    conn.commit()
    conn.close()
    return {
        "success": True,
        "message": "Account created! You have 2 free credits.",
        "session_token": session_token,
        "user": {"email": req.email, "full_name": req.full_name},
        "credits": 2
    }

@app.post("/api/login")
async def login(req: LoginRequest):
    conn = get_db()
    user = conn.execute("SELECT id, email, full_name, password_hash, credits FROM users WHERE email = ?", (req.email,)).fetchone()
    if not user or not verify_password(req.password, user["password_hash"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    session_token = create_session(user["id"])
    conn.close()
    response = JSONResponse({
        "success": True,
        "user": {"email": user["email"], "full_name": user["full_name"]},
        "credits": user["credits"]
    })
    response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=2592000)
    return response

@app.post("/api/logout")
async def logout(request: Request):
    session_token = request.cookies.get("session_token")
    if session_token:
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
        conn.commit()
        conn.close()
    response = JSONResponse({"success": True})
    response.delete_cookie("session_token")
    return response

@app.get("/api/me")
async def get_me(request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not logged in")
    user = get_user_by_session(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return {
        "user": {"id": user["id"], "email": user["email"], "full_name": user["full_name"]},
        "credits": user["credits"]
    }

# ============================================================
# ========== PAYMENT & PRICING ENDPOINTS ==========
# ============================================================

@app.get("/api/pricing")
async def get_pricing():
    return {
        "free_credits": 2,
        "packages": [
            {"credits": 20, "price_inr": 49, "price_usd": 2, "id": "starter"},
            {"credits": 60, "price_inr": 149, "price_usd": 5, "id": "popular"},
            {"credits": 150, "price_inr": 299, "price_usd": 10, "id": "pro"},
            {"credits": 400, "price_inr": 599, "price_usd": 20, "id": "ultra"}
        ]
    }

@app.post("/api/purchase")
async def purchase_credits(purchase: PurchaseRequest, request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Please login to purchase")
    user = get_user_by_session(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    valid_amounts = [20, 60, 150, 400]
    if purchase.credits not in valid_amounts:
        raise HTTPException(status_code=400, detail="Invalid credit amount")
    prices = {20: 49, 60: 149, 150: 299, 400: 599}
    amount_inr = prices[purchase.credits]
    conn = get_db()
    conn.execute("INSERT INTO transactions (user_id, credits, amount_inr, payment_id, status) VALUES (?, ?, ?, ?, 'completed')", (user["id"], purchase.credits, amount_inr, purchase.payment_id))
    conn.execute("UPDATE users SET credits = credits + ?, total_purchased = total_purchased + ? WHERE id = ?", (purchase.credits, purchase.credits, user["id"]))
    conn.commit()
    updated = conn.execute("SELECT credits FROM users WHERE id = ?", (user["id"],)).fetchone()
    conn.close()
    return {
        "success": True,
        "credits_added": purchase.credits,
        "total_credits": updated["credits"],
        "message": f"Added {purchase.credits} credits!"
    }

# ============================================================
# ========== POLICY PAGES ==========
# ============================================================

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

# ============================================================
# ========== RAZORPAY WEBHOOK ==========
# ============================================================

@app.post("/api/razorpay-webhook")
async def razorpay_webhook(request: Request):
    try:
        body = await request.json()
        event = body.get("event")
        
        if event == "payment.captured":
            payment = body["payload"]["payment"]["entity"]
            payment_id = payment["id"]
            amount = payment["amount"] / 100
            email = payment.get("email", "")
            
            credit_map = {49: 20, 149: 60, 299: 150, 599: 400}
            credits = credit_map.get(amount, 0)
            
            if credits and email:
                conn = get_db()
                user = conn.execute("SELECT id, credits FROM users WHERE email = ?", (email,)).fetchone()
                if user:
                    new_credits = user["credits"] + credits
                    conn.execute("UPDATE users SET credits = ?, total_purchased = total_purchased + ? WHERE id = ?", (new_credits, credits, user["id"]))
                    conn.execute("INSERT INTO transactions (user_id, credits, amount_inr, payment_id, status) VALUES (?, ?, ?, ?, 'completed')", (user["id"], credits, amount, payment_id))
                    conn.commit()
                    print(f"✅ Added {credits} credits to {email}")
                conn.close()
        
        return {"status": "ok"}
    except Exception as e:
        print(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}

# ============================================================
# ========== DOWNLOAD ENDPOINTS ==========
# ============================================================

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
            raise HTTPException(status_code=400, detail="YouTube bot protection. Try Instagram Reels instead (works perfectly!)")
        raise HTTPException(status_code=400, detail=error_msg[:200])

@app.post("/api/download")
async def download_video(req: DownloadRequest, request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Please login to download")
    user = get_user_by_session(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    if user["credits"] <= 0:
        raise HTTPException(status_code=402, detail="Insufficient credits. Purchase more credits to continue downloading.")
    user_id_str = str(user["id"])
    allowed, message = cost_controller.check_limits(user_id_str)
    if not allowed:
        raise HTTPException(status_code=429, detail=message)
    
    file_id = str(uuid.uuid4())[:8]
    DOWNLOAD_DIR = Path("downloads")
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    
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
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
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
        file_size_mb = files[0].stat().st_size / (1024 * 1024)
        
        conn = get_db()
        conn.execute("UPDATE users SET credits = credits - 1, total_used = total_used + 1 WHERE id = ?", (user["id"],))
        conn.execute("INSERT INTO downloads (user_id, url, format, quality, file_size_mb) VALUES (?, ?, ?, ?, ?)", (user["id"], req.url, req.format, req.quality, file_size_mb))
        conn.commit()
        updated = conn.execute("SELECT credits FROM users WHERE id = ?", (user["id"],)).fetchone()
        conn.close()
        
        cost_controller.record_download(user_id_str, file_size_mb)
        asyncio.create_task(delete_file_later(files[0], delay=600))
        
        return {
            "success": True,
            "filename": f"{title[:50]}{files[0].suffix}",
            "download_url": f"/api/file/{filename}",
            "title": title,
            "credits_remaining": updated["credits"],
            "message": f"Download complete! You have {updated['credits']} credits left."
        }
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "Sign in to confirm" in msg:
            raise HTTPException(status_code=400, detail="YouTube anti-bot protection. Try Instagram Reel instead (works perfectly!)")
        elif "Private" in msg:
            raise HTTPException(status_code=400, detail="This video is private")
        else:
            raise HTTPException(status_code=400, detail=f"Download failed: {msg[:150]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

@app.get("/api/file/{filename}")
async def serve_file(filename: str):
    filepath = Path("downloads") / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found or expired")
    return FileResponse(path=filepath, filename=filename, media_type="application/octet-stream")

@app.get("/api/admin/stats")
async def get_admin_stats(admin_key: str = ""):
    ADMIN_SECRET = "snapload_admin_2024"
    if admin_key != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_downloads = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    total_revenue = conn.execute("SELECT SUM(amount_inr) FROM transactions WHERE status='completed'").fetchone()[0]
    active_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE expires_at > datetime('now')").fetchone()[0]
    total_credits_issued = conn.execute("SELECT SUM(total_purchased) + (COUNT(*) * 2) FROM users").fetchone()[0]
    total_credits_used = conn.execute("SELECT SUM(total_used) FROM users").fetchone()[0]
    conn.close()
    return {
        "total_users": total_users,
        "total_downloads": total_downloads,
        "total_revenue_inr": total_revenue or 0,
        "active_sessions": active_sessions,
        "total_credits_issued": total_credits_issued or 0,
        "total_credits_used": total_credits_used or 0,
        "credit_usage_rate": round((total_credits_used or 0) / (total_credits_issued or 1) * 100, 2)
    }

async def delete_file_later(path: Path, delay: int):
    await asyncio.sleep(delay)
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass

# ============================================================
# ========== HEALTH CHECK & STATIC FILES ==========
# ============================================================

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
