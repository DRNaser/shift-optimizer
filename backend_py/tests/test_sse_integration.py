import pytest
from fastapi.testclient import TestClient
from src.main import app
import time
import threading
from src.api.run_manager import run_manager, RunContext, RunStatus
from datetime import datetime

client = TestClient(app)

def test_sse_endpoint_structure():
    """Test that the SSE endpoint exists and returns event-stream media type."""
    # Create a dummy run
    run_id = "test_sse_run"
    ctx = RunContext(
        run_id=run_id,
        status=RunStatus.RUNNING,
        created_at=datetime.now(),
        input_summary={},
        config=None,
        time_budget=60.0
    )
    run_manager.runs[run_id] = ctx
    
    # Connect to SSE
    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

def test_sse_receives_events():
    """Test that events emitted by the backend are received by the SSE stream."""
    run_id = "test_sse_flow"
    ctx = RunContext(
        run_id=run_id,
        status=RunStatus.RUNNING,
        created_at=datetime.now(),
        input_summary={},
        config=None,
        time_budget=60.0
    )
    run_manager.runs[run_id] = ctx
    
    # Define a generator to simulate the stream reading
    def read_stream():
        with client.stream("GET", f"/api/v1/runs/{run_id}/events") as response:
            for line in response.iter_lines():
                if line:
                    yield line

    # Generate events in a separate thread so we can read them
    def generate_events():
        time.sleep(0.5)
        ctx.emit_progress("test_event", "Hello World", metrics={"foo": "bar"})
        time.sleep(0.5)
        ctx.status = RunStatus.COMPLETED # Close stream
    
    t = threading.Thread(target=generate_events)
    t.start()
    
    # Read stream
    events_received = []
    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as response:
        start = time.time()
        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("data:"):
                    events_received.append(decoded)
            
            if len(events_received) >= 1 or time.time() - start > 2.0:
                break
                
    t.join()
    
    assert len(events_received) > 0
    assert "Hello World" in events_received[0]
