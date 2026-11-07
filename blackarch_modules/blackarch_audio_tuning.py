#!/usr/bin/env python3
# blackarch:summary=Manage the speaker tuning for this laptop
# blackarch:args=<on|off|status|match|fronted-sink> [--force]
# blackarch:group=audio
# blackarch:examples=blackarch audio tuning status | blackarch audio tuning on | blackarch audio tuning off
"""blackarch-audio-tuning — manage the speaker tuning for this laptop.

Python port of the bash original. The tuning is hosted by its own PipeWire
client under its own config name, so switching it needs no audio restart — a
restart drops every PulseAudio client's connection, and applications that do not
reconnect (Spotify) then have to be restarted by hand.

A tuning is data, not code: a directory under
$BLACKARCH_PATH/default/audio/tunings declares the DMI string it belongs to and
the sink it expects (tuning.conf), so most tunings need no new script.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

USAGE = "Usage: blackarch-audio-tuning <on|off|status|match|fronted-sink> [--force]"

SINK_NAME = "blackarch_speaker_tuning"
HOST_CONFIG_NAME = "blackarch-speaker-tuning.conf"
UNIT_NAME = "blackarch-speaker-tuning.service"
APP_STREAMS = re.compile(r'^application\.name = "')
PACM_SINK_NAME = re.compile(r"^[ \t]*Name:\s+(\S+)\s*$")


def run_quiet(argv: list[str]) -> str:
    """stdout with trailing whitespace stripped; "" on failure."""
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def paths() -> dict[str, Path]:
    blackarch_path = Path(os.environ.get("BLACKARCH_PATH", ""))
    config_home = Path(os.environ.get("XDG_CONFIG_HOME")
                       or os.path.join(os.environ.get("HOME", ""), ".config"))
    return {
        "tunings_dir": blackarch_path / "default/audio/tunings",
        "host_config": config_home / "pipewire" / HOST_CONFIG_NAME,
        "host_source": blackarch_path / "default/audio/filter-chain-host.conf",
        "fragment": config_home / "pipewire" / f"{HOST_CONFIG_NAME}.d/90-tuning.conf",
        "unit": config_home / "systemd/user" / UNIT_NAME,
        "unit_source": blackarch_path / "default/systemd/user" / UNIT_NAME,
        "stale_daemon": config_home / "pipewire/pipewire.conf.d/90-blackarch-speaker-tuning.conf",
        "stale_wireplumber": config_home / "wireplumber/wireplumber.conf.d/90-blackarch-speaker-tuning.conf",
        "stale_shared": config_home / "pipewire/filter-chain.conf.d/90-blackarch-speaker-tuning.conf",
    }


def dmi_value(name: str) -> str:
    try:
        return Path(f"/sys/class/dmi/id/{name}").read_text(errors="replace").strip()
    except OSError:
        return ""


def sku_matches(wanted: list[str]) -> bool:
    """Exact, case-insensitive match against the DMI product SKU — never a substring."""
    sku = dmi_value("product_sku")
    if not sku:
        return False
    lowered = sku.lower()
    return any(lowered == item.lower() for item in wanted)


def dmi_matches(wanted: list[str]) -> bool:
    for item in wanted:
        if run_quiet(["blackarch-hw-match", item]):
            return True
    return False


def as_list(value) -> list[str]:
    """Bash arrays: an unset variable is empty, a plain string is one entry."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def read_tuning(directory: Path) -> dict:
    """`source tuning.conf` — the file assigns plain shell variables."""
    values: dict[str, object] = {}
    try:
        text = directory.joinpath("tuning.conf").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, raw = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("(") and raw.endswith(")"):
            inner = raw[1:-1].strip()
            items = [item.strip().strip('"').strip("'") for item in inner.split()]
            values[key] = [item for item in items if item]
        else:
            values[key] = raw.strip('"').strip("'")
    return values


def tuning_match(p: dict[str, Path]) -> str:
    """The tuning directory matching this laptop, or "".

    Deliberately does not look at the live audio graph: install hooks run in the
    ISO chroot with no audio server, and a match that depended on a present sink
    would come back empty there.
    """
    try:
        candidates = sorted(p["tunings_dir"].iterdir())
    except OSError:
        return ""

    for directory in candidates:
        if not directory.is_dir() or not (directory / "tuning.conf").is_file():
            continue
        values = read_tuning(directory)

        if values.get("match_command"):
            if run_quiet(as_list(values["match_command"])):
                pass
            else:
                continue
        elif values.get("match_sku"):
            if not sku_matches(as_list(values["match_sku"])):
                continue
        elif values.get("match_dmi"):
            if not dmi_matches(as_list(values["match_dmi"])):
                continue
        else:
            continue

        # Required whichever way the tuning matched: the graph's target sink is
        # substituted from it.
        if not values.get("sink_pattern"):
            continue
        return str(directory)
    return ""


def sink_matching(pattern: str) -> str:
    """The sink whose name matches `pattern`, from `pactl list sinks short`."""
    for line in run_quiet(["pactl", "list", "sinks", "short"]).splitlines():
        fields = line.split()
        if len(fields) > 1 and re.search(pattern, fields[1]):
            return fields[1]
    return ""


def tuned_hardware_sink(p: dict[str, Path]) -> str:
    directory = tuning_match(p)
    if not directory:
        return ""
    values = read_tuning(Path(directory))
    pattern = values.get("sink_pattern") or ""
    if not pattern:
        return ""
    return sink_matching(str(pattern))


def tuning_present() -> bool:
    return SINK_NAME in run_quiet(["pactl", "list", "sinks", "short"]).split()


def app_stream_ids() -> list[str]:
    """Sink input ids belonging to real applications (not EasyEffects).

    A filter-chain's own output is also a sink input but carries no
    application.name, and moving it would rewire the tuning itself.
    """
    ids: list[str] = []
    matched: list[str] = []
    for line in run_quiet(["pactl", "list", "sink-inputs"]).splitlines():
        if line.startswith("Sink Input #"):
            ids.append(line.split("#", 1)[1].strip())
        elif APP_STREAMS.match(line):
            app = line.split('"')
            app = app[1] if len(app) > 1 else ""
            if app and app != "EasyEffects" and ids:
                matched.append(ids[-1])

    seen: list[str] = []
    for item in matched:
        if item not in seen:
            seen.append(item)
    return seen


def move_apps_to(target: str) -> None:
    for identifier in app_stream_ids():
        subprocess.run(["pactl", "move-sink-input", identifier, target],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def tuning_downstream_sink() -> str:
    return run_quiet(["blackarch-audio-output-sink", SINK_NAME])


def easyeffects_running() -> bool:
    if "easyeffects_sink" in run_quiet(["pactl", "list", "sinks", "short"]).split():
        return True
    if run_quiet(["pgrep", "-u", str(os.getuid()), "-x", "easyeffects"]):
        return True
    return run_quiet(["systemctl", "--user", "is-active", "--quiet",
                      "easyeffects.service"]) == ""


def drop_stale_daemon_config(p: dict[str, Path]) -> None:
    """Unloading a daemon-loaded drop-in is the one case needing an audio restart."""
    if not (p["stale_daemon"].exists() or p["stale_wireplumber"].exists()):
        return
    for path in (p["stale_daemon"], p["stale_wireplumber"]):
        try:
            path.unlink()
        except OSError:
            pass
    subprocess.run(["blackarch-restart-audio"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=False)
    for _ in range(40):
        if run_quiet(["pactl", "info"]):
            return
        time.sleep(0.25)


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "status"
    force = len(argv) > 1 and argv[1] == "--force"
    p = paths()

    if action == "match":
        print(tuning_match(p))
        return 0

    if action == "fronted-sink":
        # "is a tuning in place", not "where should volume go" — the latter is
        # blackarch-audio-output-sink.
        if not tuning_present():
            return 1
        print(tuned_hardware_sink(p))
        return 0

    if action == "status":
        if p["fragment"].is_file():
            print(f"Installed:    yes ({p['fragment']})")
        else:
            print("Installed:    no")
        # Both is-active and is-enabled print their answer *and* exit non-zero
        # when negative, so a "|| echo" fallback would print it twice. An empty
        # systemctl answer is a missing unit — "not-found", not "disabled".
        state = run_quiet(["systemctl", "--user", "is-active", UNIT_NAME]) or "inactive"
        if p["unit"].is_file():
            enabled = (run_quiet(["systemctl", "--user", "is-enabled", UNIT_NAME])
                       or "disabled")
        else:
            enabled = "not-found"
        print(f"Host service: {state} ({enabled})")
        print(f"Tuning sink:  {'present' if tuning_present() else 'absent'}")
        print(f"Default sink: {run_quiet(['pactl', 'get-default-sink'])}")
        directory = tuning_match(p)
        if directory:
            description = read_tuning(Path(directory)).get("description") or "?"
            print(f"Matches:      {description} ({Path(directory).name})")
        else:
            print("Matches:      nothing ships for this laptop")
        return 0

    if action == "off":
        installed_any = any(
            path.is_file() for path in
            (p["fragment"], p["unit"], p["stale_daemon"], p["stale_wireplumber"], p["stale_shared"])
        )
        if not installed_any:
            print("No speaker tuning installed.")
            return 0

        speakers = tuned_hardware_sink(p)

        subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        for path in (p["fragment"], p["host_config"], p["unit"], p["stale_shared"]):
            try:
                path.unlink()
            except OSError:
                pass
        try:
            p["host_config"].parent.rmdir()
        except OSError:
            pass
        subprocess.run(["systemctl", "--user", "daemon-reload"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        drop_stale_daemon_config(p)

        for _ in range(20):
            if not tuning_present():
                break
            time.sleep(0.25)

        if speakers:
            subprocess.run(["pactl", "set-default-sink", speakers],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            move_apps_to(speakers)
        print("Speaker tuning removed.")
        return 0

    if action == "on":
        if not p["tunings_dir"].is_dir():
            print(f"No tunings shipped at {p['tunings_dir']}", file=sys.stderr)
            return 1

        selected = tuning_match(p)
        if not selected:
            print("No speaker tuning matches this laptop.")
            return 0

        values = read_tuning(Path(selected))
        description = str(values.get("description") or "")
        pattern = str(values.get("sink_pattern") or "")

        speaker_sink = ""
        for _ in range(20):
            speaker_sink = sink_matching(pattern)
            if speaker_sink:
                break
            time.sleep(0.5)
        if not speaker_sink:
            print(f"A tuning applies to this laptop but no sink matching {pattern}",
                  file=sys.stderr)
            print("is present, so there is no audio server yet. Re-run after login:",
                  file=sys.stderr)
            print("  blackarch audio tuning on", file=sys.stderr)
            return 1

        if easyeffects_running():
            print("EasyEffects is running. It moves any stream that follows the default "
                  "sink to its", file=sys.stderr)
            print("own sink, so a tuning installed now would be bypassed.", file=sys.stderr)
            print("", file=sys.stderr)
            print("Stop it first:  systemctl --user disable --now easyeffects.service",
                  file=sys.stderr)
            return 1

        # Every tuning ends in a limiter, which is an LV2 plugin.
        if not Path("/usr/lib/lv2/lsp-plugins.lv2/limiter_stereo.ttl").is_file():
            print("lsp-plugins-lv2 is required for the tuning limiter.", file=sys.stderr)
            return 1

        rendered = p["host_config"].parent / f"90-tuning.{os.getpid()}.conf"
        rendered.write_text(
            Path(selected, "filter-chain.conf").read_text(encoding="utf-8",
                                                          errors="replace").replace(
                "@SPEAKER_SINK@", speaker_sink),
            encoding="utf-8")

        current = (
            p["fragment"].is_file()
            and rendered.read_text(encoding="utf-8")
                == p["fragment"].read_text(encoding="utf-8")
            and p["host_config"].is_file()
            and p["host_source"].read_text(encoding="utf-8", errors="replace")
                == p["host_config"].read_text(encoding="utf-8", errors="replace")
            and p["unit"].is_file()
            and p["unit_source"].read_text(encoding="utf-8", errors="replace")
                == p["unit"].read_text(encoding="utf-8", errors="replace")
            and run_quiet(["systemctl", "--user", "is-active", "--quiet", UNIT_NAME]) == ""
            and run_quiet(["systemctl", "--user", "is-enabled", "--quiet", UNIT_NAME]) == ""
            and tuning_downstream_sink() == speaker_sink
        )

        if not force and current:
            try:
                rendered.unlink()
            except OSError:
                pass
            print(f"Speaker tuning already current: {description}")
            return 0

        drop_stale_daemon_config(p)

        try:
            p["stale_shared"].unlink()
        except OSError:
            pass
        for source, target in ((p["host_source"], p["host_config"]),
                               (rendered, p["fragment"]),
                               (p["unit_source"], p["unit"])):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            os.chmod(target, 0o644)

        subprocess.run(["systemctl", "--user", "daemon-reload"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        subprocess.run(["systemctl", "--user", "enable", UNIT_NAME],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        subprocess.run(["systemctl", "--user", "restart", UNIT_NAME],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print(f"Installed speaker tuning: {description}")

        for _ in range(40):
            if tuning_present():
                break
            time.sleep(0.25)
        if not tuning_present():
            subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            for path in (p["fragment"], p["host_config"], p["unit"]):
                try:
                    path.unlink()
                except OSError:
                    pass
            subprocess.run(["systemctl", "--user", "daemon-reload"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            print("Tuning sink never appeared, so it was removed. Audio is untouched.",
                  file=sys.stderr)
            print(f"Check: systemctl --user status {UNIT_NAME}", file=sys.stderr)
            return 1

        downstream = ""
        for _ in range(20):
            downstream = tuning_downstream_sink()
            if downstream == speaker_sink:
                break
            time.sleep(0.25)
        if downstream != speaker_sink:
            subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            for path in (p["fragment"], p["host_config"], p["unit"]):
                try:
                    path.unlink()
                except OSError:
                    pass
            subprocess.run(["systemctl", "--user", "daemon-reload"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            print(f"The tuning output linked to {downstream or 'nothing'} instead of",
                  file=sys.stderr)
            print(f"{speaker_sink}, so it was removed rather than left tuning the wrong",
                  file=sys.stderr)
            print("device. Audio is untouched.", file=sys.stderr)
            return 1

        subprocess.run(["pactl", "set-default-sink", SINK_NAME],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        move_apps_to(SINK_NAME)
        print("Speakers now play through the tuning.")
        return 0

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
