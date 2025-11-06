"""
Admin Panel Launcher
Runs the FastAPI admin panel on http://localhost:80
"""
import uvicorn
import logging
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    # Get credentials from environment variables
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin")
    
    logger.info("Starting Admin Panel on http://localhost:80")
    logger.info(f"Admin credentials: username='{admin_username}', password='{'*' * len(admin_password)}'")
    logger.info("Access the panel at: http://localhost/login")
    
    uvicorn.run(
        "admin_panel.main:app",
        host="0.0.0.0",
        port=80,
        reload=True,
        log_level="info"
    )
