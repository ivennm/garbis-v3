"""Run the server:  .venv/bin/python -m garbis_server"""
import logging

import uvicorn

from . import config


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    uvicorn.run("garbis_server.main:app", host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
