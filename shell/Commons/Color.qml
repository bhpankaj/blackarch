pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Color surfaces for the shell. Foundational palette (foreground, background,
// accent, urgent) comes from theme/colors.toml. Per-surface roles come from
// theme/shell.toml — generated per theme from default/themed/shell.toml.tpl,
// or shipped directly by a theme to replace the generated file. Surfaces that
// don't appear in shell.toml fall back to the foundational palette.
QtObject {
  id: root

  readonly property string home: Quickshell.env("HOME")
  readonly property string stateHome: home + "/.local/state"
  readonly property string currentThemePath: stateHome + "/blackarch/current/theme"

  property color foreground: "#cacccc"
  property color background: "#101315"
  property color accent: "#cacccc"
  property color urgent: "#a55555"
  property color muted: "#707880"

  // Flat dictionary of "section.key" -> raw string from shell.toml.
  // Reassigning this whole property is what makes surface bindings below
  // re-evaluate when the theme swaps; mutating it in place would not.
  property var shellValues: ({})

  function pick(key, fallback) {
    var v = shellValues[key]
    return (typeof v === "string" && v.length > 0) ? v : fallback
  }

  function pickAlpha(key, fallback) {
    var v = shellValues[key]
    if (typeof v !== "string" || v.length === 0) return fallback
    var n = Number(v)
    if (!isFinite(n)) return fallback
    return clampAlpha(n)
  }

  function firstColorToken(value) {
    var parts = String(value || "").replace(/^\s+|\s+$/g, "").split(/\s+/)
    for (var i = 0; i < parts.length; i++) {
      if (!parts[i].match(/^-?\d+(?:\.\d+)?deg$/)) return parts[i]
    }
    return value
  }

  function flatColor(value, fallback) {
    var seen = Object.create(null)
    var token = firstColorToken(value)
    var role = String(token || "").replace(/^\s+|\s+$/g, "").toLowerCase()
    while (root.shellValues[role] && root.shellValues[role] !== token) {
      if (seen[role]) return fallback
      seen[role] = true
      token = firstColorToken(root.shellValues[role])
      role = String(token || "").replace(/^\s+|\s+$/g, "").toLowerCase()
    }
    if (role === "foreground" || role === "text") return foreground
    if (role === "accent") return accent
    if (role === "urgent") return urgent
    if (role === "muted") return muted
    if (role === "background") return background
    if (role === "transparent") return Qt.rgba(0, 0, 0, 0)

    var color = canonicalColor(token, 1)
    if (typeof color === "string" && color === token && token.charAt(0) !== "#") return fallback
    return color
  }

function clamp(value, min, max) {
  var n = Number(value)
  if (!isFinite(n)) return min
  return Math.max(min, Math.min(max, n))
}

function clampAlpha(value) {
    var n = Number(value)
    if (!isFinite(n)) return 0
    return Math.max(0, Math.min(1, n))
  }

  function alpha(c, opacity) {
    var a = clampAlpha(opacity)
    if (!c) return Qt.rgba(0, 0, 0, a)
    if (typeof c === "string") c = Qt.color(c)
    return Qt.rgba(c.r, c.g, c.b, a)
  }

  // base token is a gradient, color-only consumers use the first stop.
  function composed(colorKey, alphaKey, colorFallback, alphaFallback) {
    return alpha(flatColor(pick(colorKey, colorFallback), colorFallback), pickAlpha(alphaKey, alphaFallback))
  }

  function padHex(value) {
    var n = clamp(Math.round(Number(value)), 0, 255)
    var h = n.toString(16)
    return h.length < 2 ? "0" + h : h
  }

  function qmlHexColor(rgb, alphaByte) {
    var rgbPart = String(rgb || "").replace(/^#/, "")
    var a = clamp(Math.round(Number(alphaByte)), 0, 255)
    if (typeof Qt !== "undefined" && Qt.rgba && rgbPart.length >= 6) {
      return Qt.rgba(
        parseInt(rgbPart.substring(0, 2), 16) / 255,
        parseInt(rgbPart.substring(2, 4), 16) / 255,
        parseInt(rgbPart.substring(4, 6), 16) / 255,
        a / 255
      )
    }
    var aHex = padHex(a)
    return aHex.toLowerCase() === "ff" ? "#" + rgbPart : "#" + rgbPart + aHex
  }

  function canonicalColor(value, alpha) {
    var a = alpha === undefined || alpha === null ? 1 : clampAlpha(alpha)
    var s = String(value || "").replace(/^\s+|\s+$/g, "")
    var m
    m = s.match(/^#([0-9A-Fa-f]{3})$/)
    if (m) {
      var sh = m[1]
      return qmlHexColor(sh.charAt(0)+sh.charAt(0)+sh.charAt(1)+sh.charAt(1)+sh.charAt(2)+sh.charAt(2), a * 255)
    }
    m = s.match(/^#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?$/)
    if (m) {
      var colorAlpha = m[2] ? parseInt(m[2], 16) / 255 : 1
      return qmlHexColor(m[1], colorAlpha * a * 255)
    }
    m = s.match(/^[Rr][Gg][Bb]\(([0-9A-Fa-f]{6})\)$/)
    if (m) return qmlHexColor(m[1], a * 255)
    m = s.match(/^[Rr][Gg][Bb][Aa]\(([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})\)$/)
    if (m) return qmlHexColor(m[1], (parseInt(m[2], 16) / 255) * a * 255)
    m = s.match(/^[Rr][Gg][Bb]\(([0-9]+),([0-9]+),([0-9]+)\)$/)
    if (m) return qmlHexColor(padHex(m[1]) + padHex(m[2]) + padHex(m[3]), a * 255)
    m = s.match(/^[Rr][Gg][Bb][Aa]\(([0-9]+),([0-9]+),([0-9]+),([0-9.]+)\)$/)
    if (m) return qmlHexColor(padHex(m[1]) + padHex(m[2]) + padHex(m[3]), clampAlpha(m[4]) * a * 255)
    m = s.match(/^0x([0-9A-Fa-f]{2})([0-9A-Fa-f]{6})$/)
    if (m) return qmlHexColor(m[2], (parseInt(m[1], 16) / 255) * a * 255)
    return s
  }

  readonly property QtObject bar: QtObject {
    property color background: composed("bar.background", "bar.background-alpha", background, 1.0)
    property color text: pick("bar.text", foreground)
    property color active: pick("bar.active", urgent)
  }
  readonly property QtObject popups: QtObject {
    property color background: composed("popups.background", "popups.background-alpha", background, 1.0)
    property color text: pick("popups.text", foreground)
    property color border: composed("popups.border", "popups.border-alpha", accent, 1.0)
  }
  readonly property QtObject tooltip: QtObject {
    property color background: composed("tooltip.background", "tooltip.background-alpha", background, 1.0)
    property color text: pick("tooltip.text", foreground)
    property color border: composed("tooltip.border", "tooltip.border-alpha", foreground, 1.0)
  }
  readonly property QtObject notifications: QtObject {
    property color background: composed("notifications.background", "notifications.background-alpha", background, 1.0)
    property color text: pick("notifications.text", foreground)
    property color border: composed("notifications.border", "notifications.border-alpha", accent, 1.0)
    property color countdown: pick("notifications.countdown", accent)
  }
  readonly property QtObject menu: QtObject {
    property color background: composed("menu.background", "menu.background-alpha", background, 1.0)
    property color text: pick("menu.text", foreground)
    property color border: composed("menu.border", "menu.border-alpha", foreground, 1.0)
    property color scrim: composed("menu.scrim", "menu.scrim-alpha", background, 0.5)
    property color selectedBackground: composed("menu.selected-background", "menu.selected-background-alpha", foreground, 0.08)
    property color selectedText: pick("menu.selected-text", accent)
    property color selectedBorder: composed("menu.selected-border", "menu.selected-border-alpha", foreground, 0.0)
  }
  // polkit + lock share a single border-alpha across border / border-active /
  // border-error: the three states are mutually exclusive in time, so one
  // companion is enough.
  readonly property QtObject polkit: QtObject {
    property color background: composed("polkit.background", "polkit.background-alpha", background, 1.0)
    property color text: pick("polkit.text", foreground)
    property color textError: pick("polkit.text-error", urgent)
    property color border: composed("polkit.border", "polkit.border-alpha", accent, 1.0)
    property color borderError: composed("polkit.border-error", "polkit.border-alpha", urgent, 1.0)
    property color accent: pick("polkit.accent", accent)
    property color scrim: composed("polkit.scrim", "polkit.scrim-alpha", background, 0.5)
  }
  readonly property QtObject lock: QtObject {
    property color background: composed("lock.background", "lock.background-alpha", background, 0.8)
    property color text: pick("lock.text", foreground)
    property color placeholder: root.shellValues["lock.placeholder"] ? flatColor(root.shellValues["lock.placeholder"], alpha(foreground, 0.66)) : alpha(foreground, 0.66)
    property color textError: pick("lock.text-error", urgent)
    property color border: composed("lock.border", "lock.border-alpha", foreground, 1.0)
    property color borderActive: composed("lock.border-active", "lock.border-alpha", accent, 1.0)
    property color borderError: composed("lock.border-error", "lock.border-alpha", urgent, 1.0)
    property color selection: composed("lock.selection", "lock.selection-alpha", accent, 0.45)
  }
  // The image picker has no card surface or backdrop; per-slice dim
  // overlays / text outlines use the foundational `background` color directly.
  readonly property QtObject imagePicker: QtObject {
    property color scrim: composed("image-picker.scrim", "image-picker.scrim-alpha", background, 0.5)
    property color text: pick("image-picker.text", foreground)
    property color selectedBorder: composed("image-picker.selected-border", "image-picker.selected-border-alpha", accent, 1.0)
    property color unselectedBorder: composed("image-picker.unselected-border", "image-picker.unselected-border-alpha", foreground, 0.28)
  }

  // Default foundational colors (used when colors.toml fails to load or is empty)
  function resetToDefaults() {
    foreground = "#cacccc"
    background = "#101315"
    accent = "#cacccc"
    urgent = "#a55555"
    muted = "#707880"
  }

  function loadColors(raw) {
    resetToDefaults()
  }


  // Last theme-supplied and user-supplied shell.toml dicts, kept separate so
  // either can be reloaded without re-reading the other. `shellValues` is
  // always the merge of theme (base) and user (override) — see mergeShell.
  property var themeShellValues: ({})
  property var userShellValues: ({})

  // Single TOML walker for shell.toml. Both Color (surface roles) and Style
  // (typography, spacing, bar, control states) consume the resulting dict.
  // Accepts quoted strings, bare numeric values, bare width lists, and bare
  // role names; tolerates inline comments. Numbers are kept as strings here —
  // readers coerce when they pull a value.
  function parseShell(raw) {
    var parsed = {}
    var text = String(raw || "")
    if (text) {
      var lines = text.split("\n")
      var section = ""
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i].replace(/^\s+|\s+$/g, "")
        if (!line || line.charAt(0) === "#") continue
        var sectionMatch = line.match(/^\[([A-Za-z0-9_-]+)\]\s*(#.*)?$/)
        if (sectionMatch) { section = sectionMatch[1]; continue }
        var stringKv = line.match(/^([A-Za-z0-9_-]+)\s*=\s*["']([^"']+)["']\s*(#.*)?$/)
        var numKv = line.match(/^([A-Za-z0-9_-]+)\s*=\s*(-?\d+(?:\.\d+)?)\s*(#.*)?$/)
        var widthKv = line.match(/^([A-Za-z0-9_-]+)\s*=\s*(-?\d+(?:\.\d+)?(?:\s+-?\d+(?:\.\d+)?){1,3})\s*(#.*)?$/)
        var bareKv = line.match(/^([A-Za-z0-9_-]+)\s*=\s*([A-Za-z][A-Za-z0-9_-]*)\s*(#.*)?$/)
        var kv = stringKv || numKv || widthKv || bareKv
        if (!kv || !section) continue
        parsed[section + "." + kv[1]] = kv[2]
      }
    }
    return parsed
  }

  // Re-derive `shellValues` from theme base + user override and push it to
  // Style. User keys win, so a machine-level `~/.config/blackarch/shell.toml`
  // survives theme switches (which replace only themeShellValues).
  function mergeShell() {
    var merged = {}
    for (var tk in themeShellValues) merged[tk] = themeShellValues[tk]
    for (var uk in userShellValues) merged[uk] = userShellValues[uk]
    shellValues = merged
    Style.applyShellValues(merged)
  }

  // Default empty shell values - used when shell.toml files fail to load
  function resetShellValues() {
    themeShellValues = {}
    userShellValues = {}
    shellValues = {}
    Style.applyShellValues({})
  }

  function loadShell(raw) {
    // If file failed to load or is empty, reset to empty dict
    if (!raw || String(raw).trim() === "") {
      themeShellValues = {}
    } else {
      themeShellValues = parseShell(raw)
    }
    mergeShell()
  }

  function loadUserShell(raw) {
    // If file failed to load or is empty, reset to empty dict
    if (!raw || String(raw).trim() === "") {
      userShellValues = {}
    } else {
      userShellValues = parseShell(raw)
    }
    mergeShell()
  }

  // Startup load only. Runtime theme switches push the payload explicitly
  // through shell IPC.
  property FileView colorsFile: FileView {
    id: colorsFile
    path: root.currentThemePath + "/colors.toml"
    watchChanges: true
    printErrors: true // <--- Set to true to print read errors to the console
    onLoaded: {
      console.log("colorsFile loaded successfully from: " + path);
      root.loadColors(text());
    }
    onLoadFailed: function(error) {
      console.log("FAILED to load colorsFile at " + path + ". Error: " + error);
      root.loadColors("");
    }
  }

  property FileView shellFile: FileView {
    id: shellFile
    path: root.currentThemePath + "/shell.toml"
    watchChanges: true
    printErrors: true // <--- Set to true to print read errors to the console
    onLoaded: {
      console.log("shellFile loaded successfully from: " + path);
      root.loadShell(text());
    }
    onLoadFailed: function(error) {
      console.log("FAILED to load shellFile at " + path + ". Error: " + error);
      root.loadShell("");
    }
  }  // Machine-level override, layered on top of whatever theme is active. This
  // is where `blackarch display text size` writes `[font] base-size`. Watched so the
  // CLI takes effect live without restarting the shell; absent by default.
  property FileView userShellFile: FileView {
    id: userShellFile
    path: root.home + "/.config/blackarch/shell.toml"
    watchChanges: true
    printErrors: false
    onLoaded: root.loadUserShell(text())
    // Re-read on change (including first creation) before loading — `text()`
    // is stale in the change signal itself, so route both paths through reload
    // → onLoaded to always parse fresh content.
    onFileChanged: root.userShellFileReload.restart()
    onLoadFailed: root.loadUserShell("")
  }
  property Timer userShellFileReload: Timer {
    interval: 150
    repeat: false
    onTriggered: {
      root.loadUserShell(root.userShellFile.text)
    }
  }
}
