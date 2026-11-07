#!/usr/bin/env python3
# blackarch:summary=Measure live disk read and write speed
# blackarch:args=[target-dir]
"""blackarch-disk-speedtest — measure live disk read and write speed.

Python port of the bash `blackarch-disk-speedtest`. Both phases stream to
stdout one line per second ("disk <model>", then "read <MB/s>" / "write <MB/s>");
each phase's final line is its steady-state average, which the panel dials
settle on. Scratch files live in /dev/shm and in the target directory and are
removed on exit, including on SIGTERM/SIGINT.
"""

import os
import random
import signal
import string
import subprocess
import sys
import time

PHASE_SECONDS = 8
PARALLEL = 4
CHUNK_MB = 4
FILE_MB = 256

CHUNK_FILE = ""
TEST_FILES = []
WORKER_PIDS = []


def out(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def err(line):
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def format_rate(value):
    value = float(value)
    if value <= 0:
        return "0.0"
    if value < 10:
        return f"{value:.1f}"
    return f"{value:.0f}"


def mktemp(path):
    # tempfile.mkstemp does not seed its names from a template, so the
    # XXXXXX marker is replaced the way mktemp(1) does it.
    for _ in range(64):
        suffix = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(6))
        candidate = path.replace("XXXXXX", suffix)
        try:
            fd = os.open(candidate, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        return candidate
    raise OSError("mktemp: no unique name left")


def remove_scratch():
    for path in [CHUNK_FILE] + list(TEST_FILES):
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def stop_workers():
    for pid in list(WORKER_PIDS):
        subprocess.run(["pkill", "-TERM", "-P", str(pid)], capture_output=True)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for pid in list(WORKER_PIDS):
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
    del WORKER_PIDS[:]


def cleanup():
    # Unlink before stopping the workers, so even a cleanup cut short by an
    # impatient SIGKILL has already taken the names off the filesystem. A live
    # write worker's next dd pass recreates its file by name, so sweep again
    # once they are gone.
    remove_scratch()
    stop_workers()
    remove_scratch()


def alive_workers():
    count = 0
    for pid in WORKER_PIDS:
        try:
            os.kill(pid, 0)
            count += 1
        except OSError:
            pass
    return count


def device_sectors(dev, direction):
    with open(f"/sys/class/block/{dev}/stat") as handle:
        stats = handle.read().split()
    return int(stats[2] if direction == "read" else stats[6])


def dd(args, follow=False):
    """Run dd(1). A live worker keeps going only while dd succeeds, which is
    what `|| return` in the shell loop does; with follow=True every failure is
    mirrored to stderr so the measurement's failure is not swallowed the way
    the shell's 2>/dev/null swallows a worker's."""
    proc = subprocess.run(["dd"] + args, capture_output=True)
    if proc.returncode != 0 and follow:
        err(proc.stderr.decode("utf-8", "replace"))
    return proc.returncode


def _parent_dev(partition):
    # A partition's sysfs entry lives one level below its whole disk, so the
    # realpath's parent names it. `ls` prints the same bare name.
    return os.path.basename(os.path.dirname(os.path.realpath(f"/sys/class/block/{partition}")))


def main(argv):
    global CHUNK_FILE

    if argv and not os.path.isdir(argv[0]):
        err("Usage: blackarch-disk-speedtest [target-dir]")
        return 2

    if argv:
        target_dir = argv[0]
    else:
        target_dir = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                                  "blackarch")

    os.makedirs(target_dir, exist_ok=True)

    CHUNK_FILE = mktemp("/dev/shm/blackarch-disk-speedtest-XXXXXX.src")
    for _ in range(PARALLEL):
        path = mktemp(os.path.join(target_dir, "disk-speedtest-XXXXXX.dat"))
        subprocess.run(["chattr", "+C", path], capture_output=True)
        TEST_FILES.append(path)

    def _cleanup(_signum, _frame):
        cleanup()
        os._exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    # Resolve the block device backing the target directory, so throughput can
    # be sampled from its kernel I/O counters the same way the network speed
    # test samples the interface counters.
    source_dev = subprocess.run(["findmnt", "-no", "SOURCE", "--target", target_dir],
                                capture_output=True, text=True).stdout.strip()
    source_dev = source_dev.split("[")[0]  # strip btrfs subvolume suffix

    if not source_dev.startswith("/dev/"):
        err(f"Cannot find a disk behind {target_dir}")
        return 1

    dev = os.path.basename(os.path.realpath(source_dev))

    if not os.access(f"/sys/class/block/{dev}/stat", os.R_OK):
        err(f"No I/O statistics for {dev}")
        return 1

    available_mb = subprocess.run(["df", "--output=avail", "-m", target_dir],
                                  capture_output=True, text=True).stdout.split("\n")[-2].replace(" ", "")
    if int(available_mb) < PARALLEL * FILE_MB * 2:
        err(f"Need at least {PARALLEL * FILE_MB * 2}MB free on {target_dir}")
        return 1

    # Name the physical disk under test, walking dm-crypt/LVM layers and the
    # partition table up to the whole device that carries the hardware model.
    disk = dev
    while True:
        try:
            slaves = os.listdir(f"/sys/class/block/{disk}/slaves")
        except OSError:
            slaves = []
        if not slaves:
            break
        disk = slaves[0]
    if os.path.exists(f"/sys/class/block/{disk}/partition"):
        disk = _parent_dev(disk)
    model = subprocess.run(["lsblk", "-dno", "MODEL", f"/dev/{disk}"],
                           capture_output=True, text=True).stdout.strip()
    out(f"disk {model or disk}")

    # The stress data must be incompressible so nothing between the write call
    # and the flash can shrink it. Staging a urandom chunk in RAM also keeps the
    # source out of the measurement -- reading tmpfs is a memcpy.
    dd([f"if=/dev/urandom", f"of={CHUNK_FILE}", f"bs={CHUNK_MB}M",
        f"count={FILE_MB // CHUNK_MB}", "status=none"])

    def write_worker(file):
        while True:
            try:
                os.kill(os.getppid(), 0)
            except OSError:
                return
            if dd([f"if={CHUNK_FILE}", f"of={file}", f"bs={CHUNK_MB}M",
                   "oflag=direct", "conv=notrunc", "status=none"], follow=True) != 0:
                return

    def read_worker(file):
        while True:
            try:
                os.kill(os.getppid(), 0)
            except OSError:
                return
            if dd([f"if={file}", "of=/dev/null", f"bs={CHUNK_MB}M",
                   "iflag=direct", "status=none"], follow=True) != 0:
                return

    def run_phase(phase):
        worker = read_worker if phase == "read" else write_worker

        for file in TEST_FILES:
            WORKER_PIDS.append(subprocess.Popen(
                [sys.executable, __file__, "--worker", phase, file, CHUNK_FILE],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid)

        before = device_sectors(dev, phase)
        deadline = int(time.monotonic()) + PHASE_SECONDS
        samples = 0
        after = before
        baseline_sectors = before
        baseline_time = time.time()
        end_time = baseline_time

        while int(time.monotonic()) < deadline and alive_workers() > 0:
            time.sleep(1)
            after = device_sectors(dev, phase)
            end_time = time.time()
            if after < before:
                rate = 0
            else:
                rate = (after - before) * 512 / 1000000
            out(f"{phase} {format_rate(rate)}")
            samples += 1
            # The first second is warm-up -- governor ramp, crypt workers
            # spinning up -- so the steady-state average starts after it.
            if samples == 1:
                baseline_sectors = after
                baseline_time = end_time
            before = after

        # The workers only stop on their own when dd fails (quota, I/O error,
        # full disk), so any worker gone before the deadline is a failed
        # measurement, not a finished one.
        alive = alive_workers()
        stop_workers()
        if alive < PARALLEL:
            err(f"Disk {phase} test failed before finishing")
            return False

        # The figure the dial settles on is the steady-state mean over the
        # whole phase, not whatever rate the final second happened to catch.
        if samples > 1:
            secs = end_time - baseline_time
            if secs <= 0 or after < baseline_sectors:
                rate = 0
            else:
                rate = (after - baseline_sectors) * 512 / 1000000 / secs
            out(f"{phase} {format_rate(rate)}")
        return True

    # The read phase runs first, so its data must be staged before any
    # measuring starts. Direct I/O leaves nothing in the page cache to serve
    # reads from.
    stage_failed = 0
    stage_pids = []
    for file in TEST_FILES:
        stage_pids.append(subprocess.Popen(
            [sys.executable, __file__, "--worker", "stage", file, CHUNK_FILE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid)
    for pid in stage_pids:
        if os.waitpid(pid, 0)[1] != 0:
            stage_failed = 1
    del WORKER_PIDS[:]

    if stage_failed or os.path.getsize(TEST_FILES[0]) == 0:
        err(f"Direct disk I/O is not available on {target_dir}")
        return 1

    if not run_phase("read"):
        return 1
    if not run_phase("write"):
        return 1
    return 0


def worker_main(phase, file, chunk_file):
    """Child process running one measurement pass loop."""
    if phase == "stage":
        return dd([f"if={chunk_file}", f"of={file}", f"bs={CHUNK_MB}M",
                   "oflag=direct", "conv=notrunc", "status=none"])
    while True:
        try:
            os.kill(os.getppid(), 0)
        except OSError:
            return 0
        if phase == "write":
            rc = dd([f"if={chunk_file}", f"of={file}", f"bs={CHUNK_MB}M",
                     "oflag=direct", "conv=notrunc", "status=none"], follow=True)
        else:
            rc = dd([f"if={file}", "of=/dev/null", f"bs={CHUNK_MB}M",
                     "iflag=direct", "status=none"], follow=True)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--worker":
        sys.exit(worker_main(sys.argv[2], sys.argv[3], sys.argv[4]))
    rc = main(sys.argv[1:])
    cleanup()
    sys.exit(rc)
