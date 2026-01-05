"""
SOLVEREIGN API Runner
=====================

Starts the FastAPI server with proper event loop configuration for Windows.
"""

import asyncio
import platform
import selectors

if __name__ == "__main__":
    import uvicorn
    from api.config import settings

    # Windows-specific: use SelectorEventLoop for psycopg async compatibility
    if platform.system() == "Windows":
        print("[INFO] Using SelectorEventLoop for Windows psycopg compatibility")

        # Create selector-based event loop
        selector = selectors.SelectSelector()
        loop = asyncio.SelectorEventLoop(selector)

        # Run uvicorn with the selector loop
        config = uvicorn.Config(
            "api.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.reload,
            workers=settings.workers,
            log_level=settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        loop.run_until_complete(server.serve())
    else:
        # On Linux/macOS, use standard uvicorn.run
        uvicorn.run(
            "api.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.reload,
            workers=settings.workers,
            log_level=settings.log_level.lower(),
        )
