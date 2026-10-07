import argparse
import os
import uvicorn
from fox_coding_agent.src import Config
from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="FoxCode local HTTP/SSE server")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    model = args.model or os.getenv("FOX_MODEL")
    config = Config.from_env(cwd=args.cwd, model=model, base_url=args.base_url) if model else None
    uvicorn.run(create_app(config), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
