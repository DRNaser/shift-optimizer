
import os
import sys
import threading
import logging
from datetime import datetime
import uvicorn
import webview
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

# =============================================================================
# LOGGING SETUP - File-based logging for debugging
# =============================================================================

# Create logs directory
if getattr(sys, 'frozen', False):
    log_dir = Path(sys.executable).parent / "logs"
else:
    log_dir = Path(__file__).parent.parent / "logs"

log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"solver_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Configure ROOT logger to capture ALL logs from all modules
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# File handler - captures everything
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))

root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Create app logger
logger = logging.getLogger("ShiftOptimizer")
logger.info(f"=== SHIFT OPTIMIZER STARTED ===")
logger.info(f"Log file: {log_file}")

# Fix for PyInstaller where temp folder is used
if getattr(sys, 'frozen', False):
    base_dir = Path(sys._MEIPASS)
    logger.info(f"Running from PyInstaller bundle: {base_dir}")
else:
    base_dir = Path(__file__).parent.parent
    logger.info(f"Running from source: {base_dir}")

# Import the existing router
# We need to add src to path if running from source
if not getattr(sys, 'frozen', False):
    sys.path.append(str(base_dir / "backend_py"))


from src.api.forecast_router import router as forecast_router

def create_app():
    app = FastAPI(title="Shift Optimizer Desktop")
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request, call_next):
        logger.info(f">>> REQUEST: {request.method} {request.url.path}")
        try:
            response = await call_next(request)
            logger.info(f"<<< RESPONSE: {response.status_code} for {request.url.path}")
            return response
        except Exception as e:
            logger.error(f"!!! ERROR in {request.url.path}: {e}")
            raise
    
    # API Router - NO prefix here because forecast_router already has /api/v1
    app.include_router(forecast_router)
    
    # Static Files (Frontend)
    # In PyInstaller, we will bundle 'frontend_next/out' to 'site'
    if getattr(sys, 'frozen', False):
        static_dir = base_dir / "site"
    else:
        static_dir = base_dir / "frontend_next" / "out"
        
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        logger.warning(f"Frontend build not found at {static_dir}")
        
    return app

def start_server():
    app = create_app()
    logger.info("Starting uvicorn server on http://127.0.0.1:8000")
    # Port 8000 is hardcoded in the frontend currently
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    import time
    
    # Start API in thread
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    
    # Wait for server to start
    time.sleep(1)
    
    # Create window
    window = webview.create_window(
        "Shift Optimizer", 
        "http://127.0.0.1:8000",
        width=1280,
        height=800,
        resizable=True
    )
    
    # Start UI (blocking) - debug=True enables right-click > Inspect
    webview.start(debug=True)
    
    # When window closes, exit
    os._exit(0)

