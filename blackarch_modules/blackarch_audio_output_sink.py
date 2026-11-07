#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# blackarch:summary=Print the sink whose volume and mute a given output really uses
# blackarch:args=[sink-name]
# blackarch:group=audio
# blackarch:examples=blackarch audio output sink | blackarch audio output sink blackarch_speaker_tuning
"""blackarch-audio-output-sink: port of the bash helper.

    Print the sink whose volume and mute a given output really uses

    Args: [sink-name]
    Examples: blackarch audio output sink | blackarch audio output sink blackarch_speaker_tuning
    Group: audio
"""

import os
import re
import subprocess
import sys

# A DSP sink -- a speaker tuning filter-chain, or EasyEffects -- can be the
# selected output without being where loudness lives. Changing its volume alters
# the level going *into* the processing: the display moves while the speakers do
# not, and on a chain with a compressor or limiter the tone changes too. Resolve
# through it to the physical sink it feeds.
#
# With no argument this resolves the current default output, so when headphones or
# HDMI are selected it returns those, not the speakers a tuning happens to front.
# Callers that need to describe some *other* output -- an output switcher naming
# the next one in the rotation -- pass that sink explicitly.


def pactl(*args):
    """pactl output as text, or None when the call fails / the server is gone."""
    try:
        p = subprocess.run(
            ["pactl", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    if p.returncode != 0:
        return None
    return p.stdout.decode("utf-8", "replace")


def sink_input_target(sink):
    """The sink a stream carrying `sink`'s own node name feeds, else "".

    A DSP sink feeds its physical output through a stream of its own; follow that
    stream down to the sink underneath. Mirrors the awk walk over `pactl list
    sink-inputs`: `Sink Input #` starts a record, a `Sink:` line names the
    current target, and a `node.name = "..."` line carrying the DSP sink's name
    as a prefix of the stream identifies that stream.
    """
    text = pactl("list", "sink-inputs")
    if text is None:
        return ""
    target = ""
    for line in text.split("\n"):
        if line.startswith("Sink Input #"):
            target = ""
        elif re.match(r"^[ \t]*Sink:", line):
            parts = line.split()
            target = parts[1] if len(parts) > 1 else ""
        elif "node.name = " in line:
            name = line.split("node.name = \"", 1)[1]
            name = re.sub('"$', "", name)
            if name.startswith(sink) and target != "":
                return target
        elif 'application.name = "EasyEffects"' in line:
            if sink == "easyeffects_sink" and target != "":
                return target
    return ""


def sink_short_name(sink_id):
    """The `Name` field of the sink whose short-list id is `sink_id`, else ""."""
    text = pactl("list", "sinks", "short")
    if text is None:
        return ""
    for line in text.split("\n"):
        parts = line.split()
        if len(parts) > 1 and parts[0] == sink_id:
            return parts[1]
    return ""


def main(argv):
    if len(argv) > 1 and argv[1] != "":
        sink = argv[1]
    else:
        default = pactl("get-default-sink")
        sink = default.strip() if default is not None else ""

    if sink == "" or sink.startswith("alsa_output."):
        print(sink)
        return 0

    downstream = sink_input_target(sink)
    if downstream:
        name = sink_short_name(downstream)
        if name:
            print(name)
            return 0

    # Nothing resolvable downstream -- the DSP sink may simply be idle and
    # unlinked. Fall back to the sink itself so callers still have something to
    # act on.
    print(sink)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
