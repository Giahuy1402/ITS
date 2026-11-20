"""Start TrafficVision locally: python run.py [--port 8000] [--reload]."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    gpu_python = Path(__file__).resolve().parent / ".venv-gpu" / "Scripts" / "python.exe"
    marker = gpu_python.parent.parent / "gpu-ready"
    if marker.exists() and Path(sys.prefix).resolve() != gpu_python.parent.parent.resolve() and not os.environ.get("ITS_USE_CPU"):
        raise SystemExit(subprocess.call([str(gpu_python), str(Path(__file__).resolve()), *sys.argv[1:]]))
    import uvicorn
    parser = argparse.ArgumentParser(description="ITS TrafficVision AI")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Reload Python changes during development")
    args = parser.parse_args()
    print(f"TrafficVision AI: http://127.0.0.1:{args.port}")
    print("Nhan Ctrl+C de dung server.")
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port, reload=args.reload)
