#!/usr/bin/env python3
import json, os, re, subprocess, sys, time
from pathlib import Path

HYPR_MONITOR_LUA = Path.home() / ".config" / "hypr" / "blackarch" / "monitor.lua"

mon_name = ""
res_str = ""
scale = "1"

def log_event(orientation, transform):
    print(f"[{time.strftime('%H:%M:%S')}] {orientation:<10} -> Transform: {transform}")

def init_monitor():
    global mon_name, res_str, scale
    try:
        out = subprocess.check_output(["hyprctl","monitors","-j"], text=True, stderr=subprocess.DEVNULL)
        data = json.loads(out)
        focused = [m for m in data if m.get("focused")]
        m = focused[0] if focused else (data[0] if data else {})
        mon_name = m.get("name","")
        w = m.get("width",0); h=m.get("height",0); r=m.get("refreshRate",60); sc=m.get("scale",1)
        res_str = f"{w}x{h}@{r}"
        scale = str(sc)
    except Exception:
        pass

def apply_rotation(transform, orientation_name):
    try:
        gtk = subprocess.check_output(["gsettings","get","org.gnome.desktop.interface","text-scaling-factor"], text=True).strip()
    except Exception:
        gtk = "1.0"
    print(f"After transform {transform}: GTK text-scaling-factor={gtk}, monitor scale={scale}")
    if HYPR_MONITOR_LUA.is_file():
        text = HYPR_MONITOR_LUA.read_text()
        text = re.sub(r'monitor_output = .*', f'monitor_output = "{mon_name}"', text)
        text = re.sub(r'monitor_transform = .*', f'monitor_transform = {transform}', text)
        HYPR_MONITOR_LUA.write_text(text)

def set_touch(state):
    value = 0 if state == "disable" else 1
    toggle_file = Path.home() / ".local/state/blackarch/toggles/hypr/touchscreen-disabled-name"
    if state == "disable":
        toggle_file.parent.mkdir(parents=True, exist_ok=True)
        toggle_file.touch()
    else:
        try: toggle_file.unlink()
        except FileNotFoundError: pass
    if HYPR_MONITOR_LUA.is_file():
        text = HYPR_MONITOR_LUA.read_text()
        text = re.sub(r'local touch_enabled = .*', f'local touch_enabled = {value}', text)
        HYPR_MONITOR_LUA.write_text(text)
    print(f"[{time.strftime('%H:%M:%S')}] Touch -> {state} (touch_enabled={value})")

def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--enable-touch" in argv:
        set_touch("enable"); return 0
    if "--disable-touch" in argv:
        set_touch("disable"); return 0
    init_monitor()
    try:
        gtk = subprocess.check_output(["gsettings","get","org.gnome.desktop.interface","text-scaling-factor"], text=True).strip()
    except Exception:
        gtk = "1.0"
    print(f"GTK text-scaling-factor: {gtk}; monitor scale: {scale}")
    proc = subprocess.Popen(["monitor-sensor"], stdout=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if "Accelerometer orientation changed" in line:
            orient = line.split(":")[-1].strip() if ":" in line else ""
            mapping = {"normal":(0,"Normal"),"left-up":(1,"Left"),"bottom-up":(2,"Bottom"),"right-up":(3,"Right")}
            if orient in mapping:
                t,name = mapping[orient]
                apply_rotation(t,name)
                set_touch("disable" if orient=="normal" else "enable")
    return 0

if __name__ == "__main__":
    sys.exit(main())
