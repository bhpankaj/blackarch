#!/usr/bin/env python3
# blackarch:summary=Open the Blackarch theme switcher
"""blackarch-theme-switcher — build the theme preview cache and open the picker.

Python port of the bash original. It refreshes ~/.cache/blackarch/theme-selector
when the fast signature (directory mtimes) or the full signature (preview file
size+mtime) changed, then execs `blackarch-menu-images` over the preview dir.

The second `exec` in the original is unreachable (the first exec never returns)
and is mirrored here as dead code so the port stays diffable against it.
"""

import locale
import os
import subprocess
import sys

locale.setlocale(locale.LC_ALL, "")

PREVIEW_NAMES = [
    "preview.png",
    "preview.jpg",
    "preview.jpeg",
    "preview.webp",
    "preview.gif",
    "preview.bmp",
]
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
PREVIEW_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "gif", "bmp"]


def sort_key(value: str):
    """GNU `sort` orders by locale collation, not byte order."""
    return locale.strxfrm(value)


def mtime(path: str) -> int:
    """stat -Lc '%Y' — mtime in whole seconds, symlinks dereferenced."""
    return int(os.stat(path).st_mtime)


def find_preview(theme_path: str) -> str:
    """find -L <dir> -maxdepth 1 -type f -iname <name> -print -quit, over the
    preview names in order, then the first sorted image in <dir>/backgrounds."""
    try:
        entries = list(os.scandir(theme_path))
    except OSError:
        entries = []
    for name in PREVIEW_NAMES:
        lowered = name.lower()
        for entry in entries:
            if entry.is_file() and entry.name.lower() == lowered:
                return entry.path
    backgrounds = os.path.join(theme_path, "backgrounds")
    if os.path.isdir(backgrounds):
        found = []
        try:
            for entry in os.scandir(backgrounds):
                if entry.is_file() and entry.name.lower().endswith(IMAGE_SUFFIXES):
                    found.append(entry.path)
        except OSError:
            pass
        if found:
            # `| sort | head -n 1`
            return sorted(found, key=sort_key)[0]
    return ""


def add_theme_preview(preview_dir: str, theme_name: str, preview: str) -> None:
    if not preview:
        return
    extension = os.path.splitext(preview)[1].lstrip(".").lower()
    if not extension:
        return
    link = os.path.join(preview_dir, f"{theme_name}.{extension}")
    if os.path.exists(link):
        return
    try:
        os.symlink(preview, link)
    except OSError:
        pass


def theme_children(theme_dir: str):
    """find -L <dir> -mindepth 1 -maxdepth 1 \\( -type d -o -type l \\) -print | sort.

    With -L GNU find dereferences symlinks, so `-type l` matches nothing; the
    net effect is immediate children that resolve to a directory.
    """
    try:
        names = [e.name for e in os.scandir(theme_dir) if e.is_dir()]
    except OSError:
        return []
    return [os.path.join(theme_dir, n) for n in sorted(names, key=sort_key)]


def main() -> int:
    preload = len(sys.argv) > 1 and sys.argv[1] == "--preload"

    home = os.environ.get("HOME", "")
    user_themes = os.path.join(home, ".config/blackarch/themes")
    blackarch_themes = os.path.join(os.environ.get("BLACKARCH_PATH", ""), "themes")
    cache_path = os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache"),
        "blackarch",
        "theme-selector",
    )
    preview_dir = os.path.join(cache_path, "previews")
    signature_file = os.path.join(cache_path, "signature")
    fast_signature_file = os.path.join(cache_path, "fast-signature")

    os.makedirs(preview_dir, exist_ok=True)

    # fast_signature = "v1" + "<dir>:<mtime>" lines for both roots and children
    fast_lines = ["v1"]
    for theme_dir in (user_themes, blackarch_themes):
        if os.path.isdir(theme_dir):
            fast_lines.append(f"{theme_dir}:{mtime(theme_dir)}")
            for child in theme_children(theme_dir):
                fast_lines.append(f"{child}:{mtime(child)}")
    fast_signature = "\n".join(fast_lines) + "\n"

    def fast_signature_current() -> bool:
        try:
            with open(fast_signature_file, encoding="utf-8", errors="replace") as fh:
                return fh.read() == fast_signature
        except OSError:
            return False

    theme_signature = ""
    if not fast_signature_current():
        lines = []
        for theme_dir in (user_themes, blackarch_themes):
            if os.path.isdir(theme_dir):
                lines.append(f"{theme_dir}:{mtime(theme_dir)}")
                for child in theme_children(theme_dir):
                    preview = find_preview(child)
                    lines.append(f"{child}:{mtime(child)}")
                    if preview:
                        st = os.stat(preview)
                        lines.append(f"{preview}:{st.st_size}:{int(st.st_mtime)}")
        theme_signature = "\n".join(lines) + "\n"

    if not fast_signature_current():
        # Invalidate the preview cache and rebuild it from the theme dirs.
        import shutil

        shutil.rmtree(preview_dir, ignore_errors=True)
        os.makedirs(preview_dir, exist_ok=True)

        for theme_path in theme_children(user_themes):
            theme_name = os.path.basename(theme_path)
            preview = find_preview(theme_path)
            if not preview:
                preview = find_preview(os.path.join(blackarch_themes, theme_name))
            add_theme_preview(preview_dir, theme_name, preview)

        for theme_path in theme_children(blackarch_themes):
            theme_name = os.path.basename(theme_path)
            add_theme_preview(preview_dir, theme_name, find_preview(theme_path))

        with open(signature_file, "w", encoding="utf-8") as fh:
            fh.write(theme_signature)
        with open(fast_signature_file, "w", encoding="utf-8") as fh:
            fh.write(fast_signature)

    try:
        with open(
            os.path.join(home, ".local/state/blackarch/current/theme.name"),
            encoding="utf-8",
            errors="replace",
        ) as fh:
            current_theme = fh.read().rstrip("\n")
    except OSError:
        current_theme = ""

    selected_preview = ""
    for extension in PREVIEW_EXTENSIONS:
        candidate = os.path.join(preview_dir, f"{current_theme}.{extension}")
        if os.path.exists(candidate):
            selected_preview = candidate
            break

    menu_args = [
        "blackarch-menu-images",
        "--print-name",
        "--show-labels",
        "--filterable",
        "--lazy-thumbnails",
        "--selected",
        selected_preview,
    ]
    if preload:
        menu_args.append("--preload")
    menu_args.append(preview_dir)

    try:
        proc = subprocess.run(
            menu_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        print(f"exec: {menu_args[0]}: not found", file=sys.stderr)
        return 127

    if proc.returncode == 0:
        selection = proc.stdout.decode("utf-8", "replace").strip()
        if selection:
            theme_name = selection
            if theme_name:
                state_path = os.path.join(home, ".local/state/blackarch/current/theme.name")
                try:
                    os.makedirs(os.path.dirname(state_path), exist_ok=True)
                    with open(state_path, "w", encoding="utf-8") as fh:
                        fh.write(theme_name + "\n")
                except OSError:
                    pass
            # Resolve selected theme directory and link it to current/theme
            theme_dir = None
            for root in (user_themes, blackarch_themes):
                candidate = os.path.join(root, theme_name)
                if os.path.isdir(candidate):
                    theme_dir = candidate
                    break
            if theme_dir:
                current_theme_dir = os.path.join(home, ".local/state/blackarch/current/theme")
                try:
                    if os.path.islink(current_theme_dir):
                        os.unlink(current_theme_dir)
                    elif os.path.isdir(current_theme_dir):
                        import shutil
                        shutil.rmtree(current_theme_dir)
                    os.symlink(theme_dir, current_theme_dir)
                except OSError:
                    pass
            # Auto-load first wallpaper of the new theme
            backgrounds_dir = os.path.join(theme_dir, "backgrounds") if theme_dir else ""
            first_bg = ""
            if os.path.isdir(backgrounds_dir):
                images = sorted(
                    (os.path.join(backgrounds_dir, n) for n in os.listdir(backgrounds_dir)
                     if n.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"))),
                    key=sort_key,
                )
                if images:
                    first_bg = images[0]
            if first_bg:
                subprocess.run(
                    ["blackarch-theme-bg-set", first_bg],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            # Apply colors via matugen (uses current background by default)
            subprocess.run(
                ["blackarch-matugen-apply"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    else:
        return proc.returncode

    return 0


if __name__ == "__main__":
    sys.exit(main())
