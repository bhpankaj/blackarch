---
name: logging-mechanism
description: Structured logging (file + console + JSON) for blackarch execute and blackarch installer.
---

Module: `/opt/blackarch/bin/blackarch_logging.py`

Usage:
```python
from blackarch_logging import get_logger
logger = get_logger("commander")
logger.info("message", extra={"command": "hyprlock"})
```

Environment variables:
- `BLACKARCH_LOG_FILE` — default `/var/log/blackarch/commander.log`
- `BLACKARCH_LOG_FORMAT` — `json` (default) or `text`
- `BLACKARCH_LOG_LEVEL` — `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, `CRITICAL`
- `BLACKARCH_LOG_STDOUT` — `1` to also print colored output to console

Features:
- File handler creates parent directory automatically (`os.makedirs(..., exist_ok=True)`)
- Console handler uses `ColoredTextFormatter` (ANSI colors per level)
- JSON formatter includes `timestamp`, `level`, `logger`, `message`, `module`, `line`, and optional `command` (via `extra={"command": ...}`)
- Integrated into `blackarch execute` (decorator `@log_all` applied to dispatcher functions; `logger.info()` calls present) and `blackarch installer` (decorator `@log_all` applied to setup/install functions). The decorator wraps any `def` with automatic logging (`logger.info(f"dispatcher: {func.__name__} called", extra={"command": func.__name__})`). The module also supports direct import (`from blackarch_logging import get_logger`).

Pitfall: The module creates directories and writes to `/var/log/blackarch/` automatically. If the user manually creates the directory but the file remains empty, verify the script calls `logger.info()` (not just imports the module).
