import uvicorn
from ui.dashboard import app, init_dashboard

if __name__ == "__main__":
    init_dashboard({})
    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="info")
