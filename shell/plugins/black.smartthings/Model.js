// Parsing helpers for `smartthings devices --status -j` and for the curated
// device list in Blackarch's `additional-menu.jsonc`.
//
// The status response is one array entry per device; each device carries a
// `components` array whose `main` component holds the capabilities. A device
// counts as a switch only when `main` exposes the `switch` capability.
//
// The widget's device list is driven by the menu file rather than by the raw
// status dump: every `smartthings.<uuid>` key there is a device the user
// curated for the Blackarch menu, and that same set is what belongs in the
// widget. Its labels and ordering are used, so the two surfaces agree.

var MAIN_COMPONENT = "main"
var MENU_DEVICE_PREFIX = "smartthings."

function mainComponent(device) {
  if (!device || !device.components) return null
  for (var i = 0; i < device.components.length; i++) {
    if (device.components[i] && device.components[i].id === MAIN_COMPONENT)
      return device.components[i]
  }
  return null
}

function capability(device, capabilityId) {
  var main = mainComponent(device)
  if (!main || !main.capabilities) return null
  for (var i = 0; i < main.capabilities.length; i++) {
    if (main.capabilities[i] && main.capabilities[i].id === capabilityId)
      return main.capabilities[i]
  }
  return null
}

function hasCapability(device, capabilityId) {
  return capability(device, capabilityId) !== null
}

// Status objects are shaped { status: { <attr>: { value: ... } } }.
function attributeValue(device, capabilityId, attribute) {
  var cap = capability(device, capabilityId)
  if (!cap || !cap.status) return null
  var attr = cap.status[attribute]
  if (!attr) return null
  return attr.value
}

function switchState(device) {
  return attributeValue(device, "switch", "switch")
}

// Dimmer level 0-100, or null when the device has no switchLevel capability.
function dimmerLevel(device) {
  var level = attributeValue(device, "switchLevel", "level")
  if (level === null || level === undefined || level === "") return null
  var numeric = Number(level)
  return isNaN(numeric) ? null : numeric
}

// ---- additional-menu.jsonc -------------------------------------------

// The file is JSON-with-comments. Strip line/block comments and trailing
// commas before handing it to JSON.parse, mirroring the shell's own tolerance
// so a hand-edited file does not silently yield an empty device list.
function stripJsonc(raw) {
  var text = String(raw || "")
  var out = ""
  var inString = false
  var inLine = false
  var inBlock = false
  var i = 0
  while (i < text.length) {
    var c = text.charAt(i)
    var n = text.charAt(i + 1)
    if (inLine) {
      if (c === "\n") { inLine = false; out += c }
      i++
      continue
    }
    if (inBlock) {
      if (c === "*" && n === "/") { inBlock = false; i += 2; continue }
      i++
      continue
    }
    if (inString) {
      out += c
      if (c === "\\") { out += n; i += 2; continue }
      if (c === '"') inString = false
      i++
      continue
    }
    if (c === '"') { inString = true; out += c; i++; continue }
    if (c === "/" && n === "/") { inLine = true; i += 2; continue }
    if (c === "/" && n === "*") { inBlock = true; i += 2; continue }
    out += c
    i++
  }
  return out.replace(/,(\s*[}\]])/g, "$1")
}

// Every `smartthings.<uuid>` entry, in file order.
// Returns { order: [deviceId...], labels: { deviceId: label } }.
function parseMenuDevices(raw) {
  var order = []
  var labels = {}
  if (!raw) return { order: order, labels: labels }
  var parsed = null
  try {
    parsed = JSON.parse(stripJsonc(raw))
  } catch (e) {
    return { order: order, labels: labels }
  }
  if (!parsed || typeof parsed !== "object") return { order: order, labels: labels }
  for (var key in parsed) {
    if (key.indexOf(MENU_DEVICE_PREFIX) !== 0) continue
    var id = key.substring(MENU_DEVICE_PREFIX.length)
    if (!id) continue
    var entry = parsed[key]
    order.push(id)
    labels[id] = entry && entry.label ? String(entry.label) : ""
  }
  return { order: order, labels: labels }
}

// ---- device list -----------------------------------------------------

function compareNames(a, b) {
  var an = String(a.name || "").toLowerCase()
  var bn = String(b.name || "").toLowerCase()
  if (an < bn) return -1
  if (an > bn) return 1
  return 0
}

// Switch-capable devices, restricted to the curated menu set when one is
// given. Menu order and menu labels win, so the widget and the Blackarch menu
// list the same devices under the same names.
function switchDevices(payload, menu) {
  var order = menu && menu.order ? menu.order : null
  var labels = menu && menu.labels ? menu.labels : null
  var rank = {}
  if (order) for (var r = 0; r < order.length; r++) rank[order[r]] = r

  var out = []
  if (!payload || !payload.length) return out
  for (var i = 0; i < payload.length; i++) {
    var device = payload[i]
    if (!device || !device.deviceId) continue
    if (!hasCapability(device, "switch")) continue
    var id = device.deviceId
    if (order && rank[id] === undefined) continue
    var curatedLabel = labels ? labels[id] : undefined
    var state = switchState(device)
    out.push({
      id: id,
      name: curatedLabel || String(device.label || device.name || "Unnamed"),
      state: state === null || state === undefined ? "unknown" : String(state),
      level: dimmerLevel(device),
      type: String(device.type || ""),
      curated: curatedLabel !== undefined
    })
  }

  out.sort(function(a, b) {
    if (order) {
      var ar = rank[a.id]
      var br = rank[b.id]
      if (ar !== br) return ar - br
    }
    return compareNames(a, b)
  })
  return out
}

function parse(payload, menu) {
  try {
    return switchDevices(payload, menu)
  } catch (e) {
    return []
  }
}

// Devices reported `on` — drives the bar indicator count.
function countOn(devices) {
  var n = 0
  for (var i = 0; i < devices.length; i++)
    if (devices[i].state === "on") n++
  return n
}

// Case-insensitive substring filter over device names.
function filterDevices(devices, query) {
  var q = String(query || "").trim().toLowerCase()
  if (q === "") return devices
  var out = []
  for (var i = 0; i < devices.length; i++) {
    if (devices[i].name.toLowerCase().indexOf(q) !== -1) out.push(devices[i])
  }
  return out
}
