#!/usr/bin/env python3
# kbd-backlight-monitor.py — Auto keyboard backlight for Samsung Galaxy Book
# ON on any key press, OFF after 45s (or args[1]) of inactivity
# Uses only Python stdlib; requires root for /dev/input/event* and /sys/class/leds/*
import sys, os, time, select

# Discover keyboard LED at runtime — never hardcode (matches user standing convention)
led_dir = None
for entry in os.listdir("/sys/class/leds"):
    if "kbd" in entry.lower():
        candidate = f"/sys/class/leds/{entry}"
        if os.path.isfile(f"{candidate}/brightness"):
            led_dir = entry
            break
if led_dir is None:
    print("No keyboard backlight LED found under /sys/class/leds/*kbd*", file=sys.stderr)
    sys.exit(1)

led_path = f"/sys/class/leds/{led_dir}/brightness"
max_path = f"/sys/class/leds/{led_dir}/max_brightness"
with open(max_path, "r") as f:
    max_b = int(f.read().strip())
idle = int(sys.argv[1]) if len(sys.argv) > 1 else 45

events = []
for entry in os.listdir("/dev/input"):
    if entry.startswith("event"):
        try:
            events.append(open(f"/dev/input/{entry}", "rb"))
        except Exception:
            pass

def set_on(on):
    try:
        with open(led_path, "w") as f:
            f.write(str(max_b if on else 0))
    except Exception:
        pass

set_on(True)
last = time.time()
is_on = True
while True:
    r, _, _ = select.select(events, [], [], 1.0)
    if r:
        for fdev in r:
            try:
                data = fdev.read(24)
                if data:
                    last = time.time()
                    if not is_on:
                        set_on(True)
                        is_on = True
            except Exception:
                pass
    if is_on and (time.time() - last) > idle:
        set_on(False)
        is_on = False
