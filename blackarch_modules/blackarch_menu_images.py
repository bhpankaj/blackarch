#!/usr/bin/env python3
# blackarch:summary=Open a generic image selector menu
# blackarch:args=[--selected <image>] [--print-name] [--show-labels] [--filterable] [--lazy-thumbnails] [--preload] [--cache-only] <image-dir>...
"""blackarch-menu-images — open a generic image selector menu.

Python port of the bash original. Enumerates image files from the given
directories, generates vips thumbnails into a content-addressed cache, then
summons the shell's image-selector target with base64-encoded rows (image rows
can contain tabs and newlines, which do not survive positional IPC arguments).
"""

import base64
import fcntl
import hashlib
import locale
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
THUMBNAIL_SIZE = "1536x864"
THUMBNAIL_TIMEOUT = 30
LOCK_TIMEOUT = 30
LOCK_REAP_SECONDS = 120


def sort_key(value: str) -> str:
    """GNU `sort` collates with the locale, not by byte value."""
    locale.setlocale(locale.LC_ALL, "")
    return locale.strxfrm(value)


def mtime(path: Path) -> int:
    """`stat -Lc '%Y'` — mtime in whole seconds, symlinks dereferenced."""
    return int(os.stat(path).st_mtime)


def size_mtime(path: Path) -> str:
    """`stat -Lc '%s:%Y'`."""
    info = os.stat(path)
    return f"{info.st_size}:{int(info.st_mtime)}"


def usage() -> None:
    print(
        "Usage: blackarch-menu-images [--selected <image>] [--print-name] "
        "[--show-labels] [--filterable] [--lazy-thumbnails] [--preload] "
        "[--cache-only] <image-dir>...",
        file=sys.stderr,
    )


def parse_args(argv: list[str]) -> tuple[dict, list[str]]:
    """Return (flags, image_dirs). `--selected` is the only valued flag."""
    flags = {
        "selected": "",
        "print_name": False,
        "show_labels": False,
        "filterable": False,
        "lazy_thumbnails": False,
        "prepare_only": False,
        "preload": False,
        "cache_only": False,
    }
    image_dirs: list[str] = []
    index = 0

    while index < len(argv):
        flag = argv[index]
        if flag == "--selected":
            if index + 1 >= len(argv):
                usage()
                raise SystemExit(1)
            flags["selected"] = argv[index + 1]
            index += 2
        elif flag == "--print-name":
            flags["print_name"] = True
            index += 1
        elif flag == "--show-labels":
            flags["show_labels"] = True
            index += 1
        elif flag == "--filterable":
            flags["filterable"] = True
            index += 1
        elif flag == "--lazy-thumbnails":
            flags["lazy_thumbnails"] = True
            index += 1
        elif flag == "--prepare-only":
            flags["prepare_only"] = True
            index += 1
        elif flag == "--preload":
            flags["preload"] = True
            index += 1
        elif flag == "--cache-only":
            flags["cache_only"] = True
            index += 1
        elif flag in ("--help", "-h"):
            usage()
            raise SystemExit(0)
        else:
            image_dirs.append(flag)
            index += 1

    return flags, image_dirs


def image_files(directory: Path) -> list[str]:
    """`find -L <dir> -depth 1 -type f <image suffixes> | sort -z`.

    `-L` dereferences symlinks, so a symlinked image counts as a file. Bash's
    `sort` collates by locale.
    """
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return []

    found = []
    for entry in entries:
        try:
            if not entry.is_file():
                continue
        except OSError:
            continue
        if entry.name.lower().endswith(IMAGE_SUFFIXES):
            found.append(entry.path)
    return sorted(found, key=sort_key)


class ThumbnailCache:
    """Content-addressed thumbnail cache with a signature-validated row cache."""

    def __init__(self, cache_dir: Path, index_file: Path, image_dirs: list[str]) -> None:
        self.cache_dir = cache_dir
        self.index_file = index_file
        self.image_dirs = image_dirs
        self.rows_cacheable = True
        self.pending: list[tuple[str, str]] = []

    def fast_signature(self) -> str:
        """Directory mtimes only — cheap enough to check every invocation."""
        lines = ["v2"]
        for directory in self.image_dirs:
            path = Path(directory)
            if path.is_dir():
                lines.append(f"{directory}:{mtime(path)}")
        return "\n".join(lines) + "\n"

    def full_signature(self, files: list[str]) -> str:
        """Directory mtimes plus every image's size:mtime."""
        lines = ["v3"]
        for directory in self.image_dirs:
            path = Path(directory)
            if path.is_dir():
                lines.append(f"{directory}:{mtime(path)}")
        for image in files:
            try:
                lines.append(f"{image}:{size_mtime(Path(image))}")
            except OSError:
                continue
        return "\n".join(lines) + "\n"

    def hash_for(self, image: str, signature: str) -> str:
        """The cached hash for (image, signature), or a fresh one, recorded."""
        try:
            for line in self.index_file.read_text(errors="replace").splitlines():
                path, sig, digest = line.split("\t")
                if path == image and sig == signature:
                    return digest
        except OSError:
            pass

        digest = hashlib.md5(f"{image}\t{signature}".encode("utf-8")).hexdigest()
        try:
            with open(self.index_file, "a", encoding="utf-8") as handle:
                handle.write(f"{image}\t{signature}\t{digest}\n")
        except OSError:
            pass
        return digest

    def generate(self, image: str, thumbnail: str) -> bool:
        """Run vipsthumbnail for one image, under a lock, single-threaded.

        A killed generator leaves its partial `<thumbnail>.<pid>.jpg` behind;
        only the lock holder writes those, so any found now are stale.
        """
        lock = f"{thumbnail}.lock"
        # Older releases used directories as locks; only reap aged ones, so a
        # legacy generator still running through an upgrade keeps its lock.
        if os.path.isdir(lock):
            try:
                age = int(time.time()) - int(os.stat(lock).st_mtime)
            except OSError:
                age = 0
            if age > LOCK_REAP_SECONDS:
                try:
                    os.rmdir(lock)
                except OSError:
                    pass

        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_WRONLY, 0o644)
        except OSError:
            return False

        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False

            for stale in Path(thumbnail).parent.glob(f"{Path(thumbnail).name}.*.jpg"):
                try:
                    stale.unlink()
                except OSError:
                    pass

            if os.path.exists(thumbnail):
                return True

            # Close the lock fd for vips: an orphaned or hung vips must not keep
            # holding the lock after this process is killed.
            tmp = f"{thumbnail}.{os.getpid()}.jpg"
            env = dict(os.environ, VIPS_CONCURRENCY="1")
            try:
                # Close the lock fd for vips: an orphaned or hung vips must not
                # keep holding the lock after this process is killed.
                with open(os.devnull, "wb") as devnull:
                    os.close(lock_fd)
                    lock_fd = -1
                    proc = subprocess.run(
                        ["vipsthumbnail", image, "--size", THUMBNAIL_SIZE,
                         "--smartcrop=centre", "--path", f"{tmp}[Q=82,strip]"],
                        env=env, stdout=devnull, stderr=devnull, check=False,
                    )
            except OSError:
                # vips may be absent; a missing generator must not take the
                # picker down with it (`xargs … || true` in the original).
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                return False
            if proc.returncode == 0 and os.path.exists(tmp):
                os.replace(tmp, thumbnail)
                return True
            try:
                os.unlink(tmp)
            except OSError:
                pass
            try:
                os.unlink(thumbnail)
            except OSError:
                pass
            return False
        finally:
            if lock_fd >= 0:
                os.close(lock_fd)

    def thumbnail_for(self, image: str) -> str:
        """The thumbnail path for `image`, queueing one for generation if absent."""
        try:
            signature = size_mtime(Path(image))
        except OSError:
            return ""

        digest = self.hash_for(image, signature)
        thumbnail = str(self.cache_dir / f"{digest}.jpg")

        if not os.path.exists(thumbnail):
            if self.flags_lazy and not self.flags_cache_only:
                self.rows_cacheable = False
                if not self.flags_prepare_only:
                    self.pending.append((image, thumbnail))
                return image
            self.pending.append((image, thumbnail))

        return thumbnail

    # Flags the caller sets before use; kept as attributes so thumbnail_for can
    # read them without threading four booleans through.
    flags_lazy = False
    flags_cache_only = False
    flags_prepare_only = False

    def drain_pending(self) -> None:
        """Generate every queued thumbnail. Each vips run is single-threaded."""
        if not self.pending:
            return
        for image, thumbnail in self.pending:
            self.generate(image, thumbnail)
        self.pending = []


def publish(cache: ThumbnailCache, cache_key: str, rows: str, fast: str, full: str) -> None:
    """Write the row cache under a lock and via renames.

    Rows go first so a kill between renames leaves signatures that are either
    older (a harmless miss) or describe the same directory state.
    """
    lock_path = Path(f"{cache.cache_dir / cache_key}.rows.lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
    except OSError:
        return

    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return

        if not cache.rows_cacheable:
            for name in ("rows", "signature", "fast-signature"):
                try:
                    os.unlink(cache.cache_dir / f"{cache_key}.{name}")
                except OSError:
                    pass
            return

        for name, content in (
            ("rows", rows),
            ("signature", full),
            ("fast-signature", fast),
        ):
            target = cache.cache_dir / f"{cache_key}.{name}"
            tmp = cache.cache_dir / f"{cache_key}.{name}.{os.getpid()}.tmp"
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, target)
    finally:
        os.close(lock_fd)


def main(argv: list[str]) -> int:
    flags, image_dirs = parse_args(argv)
    if not image_dirs:
        usage()
        return 1

    home = os.environ.get("HOME", "")
    cache_dir = Path(os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")) / "blackarch/image-selector"
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_file = cache_dir / "index.tsv"

    cache = ThumbnailCache(cache_dir, index_file, image_dirs)
    cache.flags_lazy = flags["lazy_thumbnails"]
    cache.flags_cache_only = flags["cache_only"]
    cache.flags_prepare_only = flags["prepare_only"]

    dirs_env = "\n".join(image_dirs)
    cache_key = hashlib.md5(dirs_env.encode("utf-8")).hexdigest()

    rows_file = cache_dir / f"{cache_key}.rows"
    signature_file = cache_dir / f"{cache_key}.signature"
    fast_signature_file = cache_dir / f"{cache_key}.fast-signature"

    fast = cache.fast_signature()
    rows = ""
    rows_cache_hit = False

    try:
        hit = (fast_signature_file.read_text(errors="replace") == fast
               and rows_file.is_file())
    except OSError:
        hit = False

    if hit:
        try:
            rows = rows_file.read_text(errors="replace")
        except OSError:
            rows = ""
        rows_cache_hit = True

    image_files_list: list[str] = []
    if not rows_cache_hit:
        for directory in image_dirs:
            image_files_list.extend(image_files(Path(directory)))
        full = cache.full_signature(image_files_list)

        try:
            signature_hit = signature_file.read_text(errors="replace") == full
        except OSError:
            signature_hit = False

        if signature_hit:
            rows = rows_file.read_text(errors="replace")
            fast_signature_file.write_text(fast, encoding="utf-8")
        else:
            lines = []
            for image in image_files_list:
                thumbnail = cache.thumbnail_for(image)
                if not thumbnail:
                    continue
                if flags["lazy_thumbnails"] and not flags["cache_only"] and thumbnail == image:
                    cache.rows_cacheable = False
                lines.append(f"{image}\t{thumbnail}")

            cache.drain_pending()

            if cache.pending:
                # A thumbnail that failed to materialise must not be offered.
                kept = []
                for line in lines:
                    image, thumbnail = line.split("\t", 1)
                    if not os.path.exists(thumbnail):
                        cache.rows_cacheable = False
                        continue
                    kept.append(line)
                lines = kept
                cache.pending = []

            rows = "\n".join(lines)
            if rows:
                rows += "\n"
            publish(cache, cache_key, rows, fast, full)

    if flags["cache_only"] or flags["prepare_only"]:
        return 0

    selection_file = tempfile.mkstemp(prefix="blackarch-menu-images-")[1]
    done_file = tempfile.mkstemp(prefix="blackarch-menu-images-done-")[1]
    os.unlink(done_file)

    try:
        rows_b64 = base64.b64encode(rows.encode("utf-8")).decode("ascii")

        # The currently selected image, resolved through the same symlink
        # identity the menu will use when it highlights a row.
        selected = flags["selected"]
        selected_list_image = ""
        if selected:
            current_image = os.path.realpath(selected) if os.path.exists(selected) else ""
            for directory in image_dirs:
                path = Path(directory)
                if not path.is_dir():
                    continue
                if os.path.isfile(selected) and os.path.dirname(selected) == directory:
                    selected_list_image = selected
                    break
                for image in image_files(path):
                    if os.path.realpath(image) == current_image:
                        selected_list_image = image
                        break
                if selected_list_image:
                    break

        if flags["preload"]:
            subprocess.run(
                ["blackarch-shell", "image-selector", "preload", rows_b64,
                 selected_list_image, str(flags["show_labels"]), str(flags["filterable"])],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            return 0

        with open(os.devnull, "wb") as devnull:
            proc = subprocess.run(
                ["blackarch-shell", "image-selector", "open", "",
                 rows_b64, selected_list_image, selection_file, done_file,
                 str(flags["show_labels"]), str(flags["filterable"])],
                stdout=subprocess.PIPE, stderr=devnull, check=False,
            )
        if proc.returncode != 0:
            print("Image selector failed to accept request", file=sys.stderr)
            return 1
        if proc.stdout.decode("utf-8", "replace").strip() != "ok":
            print("Image selector failed to accept request", file=sys.stderr)
            return 1

        while not os.path.exists(done_file):
            time.sleep(0.01)

        if os.path.getsize(selection_file) > 0:
            selection = open(selection_file, encoding="utf-8", errors="replace").read()
            if flags["print_name"]:
                name = os.path.basename(selection)
                print(os.path.splitext(name)[0])
            else:
                sys.stdout.write(selection)
        return 0
    finally:
        for path in (selection_file, done_file):
            try:
                os.unlink(path)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
