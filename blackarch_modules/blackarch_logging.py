#!/usr/bin/env python3
# blackarch:summary=Structured logging (file + console + JSON) for blackarch execute and blackarch installer
"""blackarch_logging — structured logging module for commander and installer.

Usage (imported):
    from blackarch_modules.blackarch_logging import setup_logging, get_logger
    logger = get_logger("commander")
    logger.info("message", extra={"command": "hyprlock"})

Environment variables:
    BLACKARCH_LOG_FILE    default /var/log/blackarch/commander.log
    BLACKARCH_LOG_FORMAT  default json  (options: text, json)
    BLACKARCH_LOG_LEVEL   default INFO (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    BLACKARCH_LOG_STDOUT  1 to also print to console
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_FILE = os.environ.get("BLACKARCH_LOG_FILE", "/var/log/blackarch/commander.log")
LOG_FORMAT = os.environ.get("BLACKARCH_LOG_FORMAT", "json")
LOG_LEVEL = os.environ.get("BLACKARCH_LOG_LEVEL", "INFO")
LOG_STDOUT = os.environ.get("BLACKARCH_LOG_STDOUT") == "1"


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": _timestamp(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if getattr(record, "command", None):
            data["command"] = record.command
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


class ColoredTextFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        msg = super().format(record)
        return f"{color}[{record.levelname}] {msg}{self.RESET}"


def setup_logging(name: str = "blackarch") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    logger.handlers.clear()

    # File handler
    if LOG_FILE:
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
            file_handler.setFormatter(JSONFormatter() if LOG_FORMAT == "json" else logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(file_handler)
        except OSError as exc:
            print(f"[blackarch_logging] Warning: cannot write to {LOG_FILE}: {exc}", file=sys.stderr)

    # Console handler
    if LOG_STDOUT:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(ColoredTextFormatter())
        logger.addHandler(console_handler)

    return logger


def get_logger(name: str = "blackarch") -> logging.Logger:
    return setup_logging(name)
