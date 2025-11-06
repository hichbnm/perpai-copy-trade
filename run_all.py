"""
Unified Launcher for Discord Trading Bot and Admin Panel
Runs both services concurrently
"""
import asyncio
import subprocess
import sys
import logging
import signal
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ServiceManager:
    def __init__(self):
        self.processes = []
        
    def start_admin_panel(self):
        """Start the FastAPI admin panel"""
        logger.info("Starting Admin Panel on http://localhost:80")
        process = subprocess.Popen(
            [sys.executable, "run_admin_panel.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self.processes.append(("Admin Panel", process))
        return process
    
    def start_discord_bot(self):
        """Start the Discord bot"""
        logger.info("Starting Discord Bot")
        process = subprocess.Popen(
            [sys.executable, "main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self.processes.append(("Discord Bot", process))
        return process
    
    def monitor_processes(self):
        """Monitor all running processes"""
        try:
            while True:
                for name, process in self.processes:
                    # Check if process is still running
                    if process.poll() is not None:
                        logger.error(f"{name} has stopped unexpectedly!")
                        return_code = process.returncode
                        stdout, stderr = process.communicate()
                        logger.error(f"{name} return code: {return_code}")
                        if stderr:
                            logger.error(f"{name} stderr: {stderr}")
                        self.shutdown()
                        sys.exit(1)
                
                asyncio.run(asyncio.sleep(5))
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            self.shutdown()
    
    def shutdown(self):
        """Gracefully shutdown all processes"""
        logger.info("Shutting down all services...")
        for name, process in self.processes:
            if process.poll() is None:
                logger.info(f"Stopping {name}...")
                process.terminate()
                try:
                    process.wait(timeout=10)
                    logger.info(f"{name} stopped successfully")
                except subprocess.TimeoutExpired:
                    logger.warning(f"{name} did not stop gracefully, forcing shutdown")
                    process.kill()
        logger.info("All services stopped")

def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("Discord Trading Bot - Unified Launcher")
    logger.info("=" * 60)
    
    # Check if .env file exists
    if not Path(".env").exists():
        logger.warning("⚠️  .env file not found! Create one with your DISCORD_TOKEN")
        logger.info("Example .env file:")
        logger.info("DISCORD_TOKEN=your_discord_token_here")
        logger.info("ADMIN_SECRET_KEY=your_secret_key_here")
    
    manager = ServiceManager()
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info("\nReceived interrupt signal")
        manager.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start services
        logger.info("\n🚀 Starting services...")
        logger.info("-" * 60)
        
        admin_panel = manager.start_admin_panel()
        logger.info("✅ Admin Panel started")
        logger.info("   Access at: http://localhost:8000/login")
        logger.info("   Default credentials: admin/admin")
        
        logger.info("-" * 60)
        
        discord_bot = manager.start_discord_bot()
        logger.info("✅ Discord Bot started")
        
        logger.info("-" * 60)
        logger.info("\n✨ All services are running!")
        logger.info("Press CTRL+C to stop all services\n")
        logger.info("=" * 60)
        
        # Monitor processes
        manager.monitor_processes()
        
    except Exception as e:
        logger.error(f"Error starting services: {e}")
        manager.shutdown()
        sys.exit(1)

if __name__ == "__main__":
    main()
