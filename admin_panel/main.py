
from fastapi import FastAPI, Request, Form, status, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import os
from dotenv import load_dotenv
from config import Config

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="Admin Panel Dashboard")

# CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session middleware for authentication
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("ADMIN_SECRET_KEY", "supersecret"))

# Static files (css, js, images)
app.mount("/static", StaticFiles(directory="admin_panel/static"), name="static")

# Templates (Jinja2)
templates = Jinja2Templates(directory="admin_panel/templates")

def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        return None
    return user

@app.get("/")
def root(request: Request):
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    # Get credentials from environment or use defaults
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin")
    
    if username == admin_username and password == admin_password:
        request.session["user"] = username
        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("overview.html", {"request": request, "user": user, "active_page": "overview"})

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("users.html", {"request": request, "user": user, "active_page": "users"})

@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("channels.html", {"request": request, "user": user, "active_page": "channels"})

@app.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("subscriptions.html", {"request": request, "user": user, "active_page": "subscriptions"})

@app.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("trades.html", {"request": request, "user": user, "active_page": "trades"})

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("overview.html", {"request": request, "user": user, "active_page": "analytics"})

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse(url="/login")
    return response

@app.get("/test-new-features")
async def test_features(request: Request):
    """Test route to verify new features are loaded"""
    return JSONResponse({
        "message": "New features API is working!",
        "features": [
            "Analytics Overview",
            "System Health",
            "Active Trades Monitor",
            "Risk Overview"
        ],
        "timestamp": "2025-10-08",
        "version": "2.0"
    })

# API endpoints for dynamic dashboard content
@app.get("/api/bot_status")
async def api_bot_status(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"status": "Unauthorized"}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        # Get statistics
        stats = {
            "total_users": db.get_all_users_count(),
            "total_subscriptions": db.get_total_subscriptions_count(),
            "total_channels": db.get_all_channels_count(),
            "recent_trades": db.get_recent_trades_count(days=7),
            "active_trades": db.get_active_trades_count(),
            "status": "Running",
            "uptime": "N/A"  # TODO: Calculate actual uptime
        }
        return stats
    except Exception as e:
        return {"status": "Error", "error": str(e)}

# 🆕 NEW: Analytics API
@app.get("/api/analytics/overview")
async def api_analytics_overview(request: Request, user: str = Depends(get_current_user)):
    """Get comprehensive analytics overview"""
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    from database.db_manager import DatabaseManager
    from utils.trade_analytics import TradeAnalytics
    
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    analytics = TradeAnalytics(db)
    
    try:
        # Get metrics for different periods
        metrics_7d = analytics.calculate_metrics(days=7)
        metrics_30d = analytics.calculate_metrics(days=30)
        
        # Get performance by symbol
        symbol_performance = analytics.get_performance_by_symbol(days=30)
        
        return {
            "last_7_days": metrics_7d,
            "last_30_days": metrics_30d,
            "by_symbol": symbol_performance
        }
    except Exception as e:
        return {"error": str(e)}

# 🆕 NEW: Live Trades Monitor
@app.get("/api/trades/active")
async def api_active_trades(request: Request, user: str = Depends(get_current_user)):
    """Get all active trades with real-time status"""
    if not user:
        return JSONResponse({"trades": []}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        active_trades = db.get_active_trades_detailed()
        return {"trades": active_trades, "count": len(active_trades)}
    except Exception as e:
        return {"trades": [], "error": str(e)}

# 🆕 NEW: System Health Metrics
@app.get("/api/system/health")
async def api_system_health(request: Request, user: str = Depends(get_current_user)):
    """Get system health metrics"""
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    import psutil
    import sys
    from datetime import datetime
    
    try:
        # CPU and Memory
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        # Disk usage
        disk = psutil.disk_usage('/')
        
        # Python version
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        
        return {
            "cpu_usage": round(cpu_percent, 2),
            "memory_usage": round(memory.percent, 2),
            "memory_total": round(memory.total / (1024**3), 2),  # GB
            "memory_available": round(memory.available / (1024**3), 2),  # GB
            "disk_usage": round(disk.percent, 2),
            "disk_total": round(disk.total / (1024**3), 2),  # GB
            "disk_free": round(disk.free / (1024**3), 2),  # GB
            "python_version": python_version,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}

# 🆕 NEW: User Activity Log
@app.get("/api/users/{user_id}/activity")
async def api_user_activity(user_id: str, request: Request, user: str = Depends(get_current_user)):
    """Get user activity history"""
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        trades = db.get_user_trades_detailed(user_id, limit=50)
        subscriptions = db.get_user_subscriptions(user_id)
        
        return {
            "user_id": user_id,
            "trades": trades,
            "subscriptions": subscriptions,
            "total_trades": len(trades)
        }
    except Exception as e:
        return {"error": str(e)}

# 🆕 NEW: Risk Management Dashboard
@app.get("/api/risk/overview")
async def api_risk_overview(request: Request, user: str = Depends(get_current_user)):
    """Get risk management overview"""
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        # Get all active trades
        active_trades = db.get_active_trades_detailed()
        
        # Calculate risk metrics
        total_positions = len(active_trades)
        total_exposure = sum(float(t.get('position_size', 0)) for t in active_trades)
        
        # Group by user
        user_exposure = {}
        for trade in active_trades:
            uid = trade['user_id']
            user_exposure[uid] = user_exposure.get(uid, 0) + float(trade.get('position_size', 0))
        
        # Group by symbol
        symbol_exposure = {}
        for trade in active_trades:
            sym = trade['symbol']
            symbol_exposure[sym] = symbol_exposure.get(sym, 0) + float(trade.get('position_size', 0))
        
        return {
            "total_active_positions": total_positions,
            "total_exposure": round(total_exposure, 2),
            "by_user": user_exposure,
            "by_symbol": symbol_exposure,
            "max_user_exposure": max(user_exposure.values()) if user_exposure else 0,
            "max_symbol_exposure": max(symbol_exposure.values()) if symbol_exposure else 0
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/users")
async def api_users(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"users": []}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        users = db.get_all_users_with_details()
        return {"users": users}
    except Exception as e:
        return {"users": [], "error": str(e)}

@app.post("/api/users/ban-all")
async def ban_all_users(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        # Get all users
        users = db.get_all_users_with_details()
        
        banned_count = 0
        for user_data in users:
            user_id = user_data.get('user_id')
            if user_id:
                db.ban_user(user_id)
                banned_count += 1
        
        return {"success": True, "banned_count": banned_count, "message": f"Banned {banned_count} users"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/users/unban-all")
async def unban_all_users(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        # Get all users
        users = db.get_all_users_with_details()
        
        unbanned_count = 0
        for user_data in users:
            user_id = user_data.get('user_id')
            if user_id:
                db.unban_user(user_id)
                unbanned_count += 1
        
        return {"success": True, "unbanned_count": unbanned_count, "message": f"Unbanned {unbanned_count} users"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/subscriptions")
async def api_subscriptions(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"subscriptions": []}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        subscriptions = db.get_all_subscriptions_with_details()
        return {"subscriptions": subscriptions}
    except Exception as e:
        return {"subscriptions": [], "error": str(e)}

@app.get("/api/channels")
async def api_channels(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"channels": []}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        channels = db.get_all_channels()
        return {"channels": channels}
    except Exception as e:
        return {"channels": [], "error": str(e)}

@app.get("/api/channels/{channel_id}/subscribers")
async def get_channel_subscribers(channel_id: str, request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"subscribers": []}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        subscribers = db.get_channel_subscribers(channel_id)
        return {"subscribers": subscribers}
    except Exception as e:
        return {"subscribers": [], "error": str(e)}

@app.put("/api/channels/{channel_id}")
async def update_channel(channel_id: str, request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        body = await request.json()
        channel_name = body.get('channel_name')
        is_signal_channel = body.get('is_signal_channel', True)
        
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        success = db.update_channel(channel_id, channel_name, is_signal_channel)
        
        if success:
            return {"success": True, "message": "Channel updated successfully"}
        else:
            return {"success": False, "error": "Failed to update channel"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/channels/{channel_id}")
async def delete_channel(channel_id: str, request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        success = db.delete_channel(channel_id)
        
        if success:
            return {"success": True, "message": "Channel deleted successfully"}
        else:
            return {"success": False, "error": "Failed to delete channel"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/channels/{channel_id}/ban-all")
async def ban_all_subscribers(channel_id: str, request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        # Get all subscribers for this channel
        subscribers = db.get_channel_subscribers(channel_id)
        
        banned_count = 0
        for sub in subscribers:
            user_id = sub.get('user_id')
            if user_id:
                db.ban_user(user_id)
                banned_count += 1
        
        return {"success": True, "banned_count": banned_count, "message": f"Banned {banned_count} users"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/channels/{channel_id}/unban-all")
async def unban_all_subscribers(channel_id: str, request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        # Get all subscribers for this channel
        subscribers = db.get_channel_subscribers(channel_id)
        
        unbanned_count = 0
        for sub in subscribers:
            user_id = sub.get('user_id')
            if user_id:
                db.unban_user(user_id)
                unbanned_count += 1
        
        return {"success": True, "unbanned_count": unbanned_count, "message": f"Unbanned {unbanned_count} users"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/trades")
async def api_trades(request: Request, user: str = Depends(get_current_user), limit: int = 50):
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        trades = db.get_recent_trades(limit=limit)
        total_count = db.get_total_trades_count()
        
        print(f"API: Returning {len(trades)} trades out of {total_count} total")
        
        return {
            "trades": trades,
            "total_count": total_count,
            "count": len(trades)
        }
    except Exception as e:
        print(f"API Error: {e}")
        return JSONResponse({"trades": [], "error": str(e), "total_count": 0, "count": 0}, status_code=500)

# User API Key Management Endpoints
@app.get("/api/users/{user_id}/api-keys")
async def get_user_api_keys(user_id: str, request: Request, user: str = Depends(get_current_user)):
    if not user:
        return JSONResponse({"api_keys": []}, status_code=401)
    
    from database.db_manager import DatabaseManager
    db = DatabaseManager(database_url=Config.DATABASE_URL)
    
    try:
        api_keys = db.get_user_all_api_keys(user_id)
        return {"api_keys": api_keys}
    except Exception as e:
        return {"api_keys": [], "error": str(e)}

@app.put("/api/users/{user_id}/api-keys/{exchange}")
async def update_user_api_key(
    user_id: str,
    exchange: str,
    request: Request,
    user: str = Depends(get_current_user)
):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        body = await request.json()
        api_key = body.get('api_key')
        api_secret = body.get('api_secret', '')
        testnet = body.get('testnet', False)
        
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        # Update the API key
        success = db.add_api_key(
            user_id=user_id,
            exchange=exchange,
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet,
            private_key=api_secret  # For Hyperliquid
        )
        
        if success:
            return {"success": True, "message": "API key updated successfully"}
        else:
            return {"success": False, "error": "Failed to update API key"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/users/{user_id}/api-keys/{exchange}")
async def delete_user_api_key(
    user_id: str,
    exchange: str,
    request: Request,
    user: str = Depends(get_current_user)
):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        success = db.delete_api_key(user_id, exchange)
        
        if success:
            return {"success": True, "message": "API key deleted successfully"}
        else:
            return {"success": False, "error": "Failed to delete API key"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/users/{user_id}/ban")
async def ban_user(
    user_id: str,
    request: Request,
    user: str = Depends(get_current_user)
):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        success = db.ban_user(user_id)
        
        if success:
            return {"success": True, "message": "User banned successfully"}
        else:
            return {"success": False, "error": "Failed to ban user"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/users/{user_id}/unban")
async def unban_user(
    user_id: str,
    request: Request,
    user: str = Depends(get_current_user)
):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        success = db.unban_user(user_id)
        
        if success:
            return {"success": True, "message": "User unbanned successfully"}
        else:
            return {"success": False, "error": "Failed to unban user"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.put("/api/subscriptions/{subscription_id}")
async def update_subscription(
    subscription_id: int,
    request: Request,
    user: str = Depends(get_current_user)
):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        body = await request.json()
        position_mode = body.get('position_mode')
        position_size = body.get('position_size')
        max_risk = body.get('max_risk')
        
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        success = db.update_subscription(
            subscription_id,
            position_mode=position_mode,
            position_size=position_size,
            max_risk=max_risk
        )
        
        if success:
            return {"success": True, "message": "Subscription updated successfully"}
        else:
            return {"success": False, "error": "Failed to update subscription"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/subscriptions/{user_id}/{channel_id}")
async def delete_subscription(
    user_id: str,
    channel_id: str,
    request: Request,
    user: str = Depends(get_current_user)
):
    if not user:
        return JSONResponse({"success": False, "error": "Unauthorized"}, status_code=401)
    
    try:
        from database.db_manager import DatabaseManager
        db = DatabaseManager(database_url=Config.DATABASE_URL)
        
        db.remove_channel_subscription(user_id, channel_id)
        
        return {"success": True, "message": "Subscription deleted successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}
