#!/usr/bin/env python3
"""Publish the camera relay loopback as an RTSP stream.

The Windows VM (dockurr/windows under QEMU) has no virtual-webcam device, and
the built-in sensor is MIPI rather than USB, so the camera reaches it as a
network stream. This publishes the relay's v4l2loopback node (default
/dev/video0, label "Camera Relay") as RTSP; Windows consumes it through a
virtual webcam (OBS Studio + Virtual Camera, an IP-camera app, ...).

Usage:
  blackarch camera stream [options]
"""

from __future__ import annotations

import argparse
import sys

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import GLib, Gst, GstRtspServer  # noqa: E402

# The relay loopback is natively 1920x1080 YUYV; the source caps must match
# the device, and videoscale brings it down to the requested size.
SOURCE_WIDTH = 1920
SOURCE_HEIGHT = 1080


def build_launch(device: str, width: int, height: int, bitrate: int,
                 fps: int) -> str:
    return (
        f"( v4l2src device={device} "
        f"! video/x-raw,format=YUY2,width={SOURCE_WIDTH},height={SOURCE_HEIGHT},"
        f"framerate={fps}/1 "
        f"! videoconvert ! videoscale ! video/x-raw,width={width},height={height} "
        f"! videoconvert ! x264enc tune=zerolatency speed-preset=ultrafast "
        f"bitrate={bitrate} ! rtph264pay name=pay0 pt=96 )"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="blackarch camera stream",
        description="Publish the camera relay loopback as an RTSP stream.",
    )
    parser.add_argument("--device", default="/dev/video0",
                        help="v4l2loopback node (default: /dev/video0)")
    parser.add_argument("--port", default="8554",
                        help="RTSP port (default: 8554)")
    parser.add_argument("--path", default="/camera",
                        help="RTSP mount path (default: /camera)")
    parser.add_argument("--width", type=int, default=1280,
                        help="stream width (default: 1280)")
    parser.add_argument("--height", type=int, default=720,
                        help="stream height (default: 720)")
    parser.add_argument("--bitrate", type=int, default=3000,
                        help="H.264 bitrate in kbit/s (default: 3000)")
    parser.add_argument("--fps", type=int, default=30,
                        help="framerate (default: 30)")
    args = parser.parse_args(argv)

    Gst.init(None)

    server = GstRtspServer.RTSPServer()
    server.set_property("service", args.port)

    factory = GstRtspServer.RTSPMediaFactory()
    factory.set_launch(build_launch(
        args.device, args.width, args.height, args.bitrate, args.fps
    ))
    factory.set_shared(True)

    server.get_mount_points().add_factory(args.path, factory)
    server.attach(None)

    print(f"RTSP stream: rtsp://0.0.0.0:{args.port}{args.path}", flush=True)
    print(f"source: {args.device} ({args.width}x{args.height} @ {args.fps}fps, "
          f"{args.bitrate} kbit/s)", flush=True)
    print("Windows VM URL: rtsp://172.18.0.1:{}{}".format(
        args.port, args.path), flush=True)
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
