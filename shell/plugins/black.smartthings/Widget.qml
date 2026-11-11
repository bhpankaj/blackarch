import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// SmartThings switch + dimmer widget.
//
// Polls `smartthings devices --status -j` on an interval, renders a bar icon
// whose count reflects how many switches are on, and opens a keyboard-driven
// popup listing every device with its live state and dimmer level. Toggling
// and level changes go out through `smartthings devices:commands`.
//
// The CLI is a compiled Go binary and takes ~1.3s for a full status dump, so
// the poll runs in the background and the popup never blocks on it: the last
// good snapshot stays rendered while a refresh is in flight.
BarWidget {
  id: root
  moduleName: "blackarch.smartthings"

  // ---- State ------------------------------------------------------------

  property var devices: []
  property bool loading: false
  property string lastError: ""
  property bool cursorActive: false
  property int selectedIndex: 0
  property string filterText: ""

  // Curated device set, read from Blackarch's additional-menu.jsonc.
  // { order: [deviceId...], labels: { deviceId: label } }. Empty until the
  // file loads; an empty set means "no restriction" so the widget still works
  // if the file is missing.
  property var menuDevices: ({ order: [], labels: {} })
  // Last raw status payload, kept so a menu edit can re-filter immediately.
  property string lastPayload: ""

  readonly property int refreshSeconds: Math.max(5, parseInt(setting("refreshIntervalSec", 30), 10) || 30)
  readonly property bool showLevels: setting("showLevels", true) !== false
  readonly property bool curated: menuDevices && menuDevices.order && menuDevices.order.length > 0
  readonly property int onCount: Model.countOn(devices)
  readonly property var visibleDevices: Model.filterDevices(devices, filterText)
  readonly property bool anyDimmer: {
    for (var i = 0; i < devices.length; i++)
      if (devices[i].level !== null) return true
    return false
  }

  function refresh() {
    if (statusProc.running) return
    loading = true
    statusProc.running = true
  }

  // Re-parse the last status payload against the current menu set, so a menu
  // edit takes effect without waiting for the next poll.
  function reparse() {
    if (lastPayload !== "") applyStatus(lastPayload)
  }

  function applyStatus(raw) {
    var parsed = null
    try {
      parsed = JSON.parse(raw)
    } catch (e) {
      lastError = "Could not parse device status"
      return
    }
    devices = Model.parse(parsed, menuDevices)
    lastError = ""
    // Keep the cursor inside the list as the set or filter narrows it.
    if (selectedIndex >= visibleDevices.length)
      selectedIndex = Math.max(0, visibleDevices.length - 1)
  }

  // ---- Command queue ----------------------------------------------------
  //
  // `smartthings devices:commands` BLOCKS FOREVER when its stdin is an open
  // pipe that never closes — and Quickshell gives every child exactly that
  // (`stdinEnabled: false` does NOT change it in 0.3.1; the child still gets
  // a pipe). The CLI then epolls fd 0 and never returns.
  //
  // Because a single `Process` runs one command at a time, the first hang
  // silently swallowed every later click and slider change. So:
  //
  //   1. every command runs through `bash -c '… </dev/null'`, which gives the
  //      CLI a closed stdin so it exits normally;
  //   2. an explicit queue + watchdog means even a genuinely wedged command
  //      cannot block the UI for the rest of the session.

  property var commandQueue: []
  property var activeCommand: null
  property int commandWatchdogMs: 15000

  function shellQuote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'"
  }

  function sendCommand(deviceId, command) {
    commandQueue = commandQueue.concat([{ id: deviceId, cmd: command }])
    pumpCommands()
  }

  function pumpCommands() {
    if (commandProc.running) return
    if (commandQueue.length === 0) { activeCommand = null; return }
    var next = commandQueue[0]
    commandQueue = commandQueue.slice(1)
    activeCommand = next
    // The `</dev/null` is load-bearing — see the note above.
    commandProc.command = ["bash", "-c",
      "smartthings devices:commands " + shellQuote(next.id) + " " + shellQuote(next.cmd)
      + " </dev/null"]
    commandProc.running = true
    commandWatchdog.restart()
  }

  function commandFinished(ok, detail) {
    commandWatchdog.stop()
    if (!ok) lastError = detail
    activeCommand = null
    settleTimer.restart()
    // Let the next queued command go once the settle read has been issued.
    Qt.callLater(pumpCommands)
  }

  function toggleDevice(device) {
    if (!device) return
    sendCommand(device.id, "switch:" + (device.state === "on" ? "off" : "on"))
  }

  function setLevel(device, level) {
    if (!device) return
    var clamped = Math.max(0, Math.min(100, Math.round(level)))
    sendCommand(device.id, "switchLevel:setLevel(" + clamped + ")")
  }

  // Look a device up by id — used by the id-addressed IPC controls.
  function deviceById(deviceId) {
    var want = String(deviceId || "")
    for (var i = 0; i < devices.length; i++)
      if (devices[i].id === want) return devices[i]
    return null
  }

  // The row under the keyboard cursor, or null.
  function cursorDevice() {
    var list = visibleDevices
    if (!cursorActive || selectedIndex < 0 || selectedIndex >= list.length) return null
    return list[selectedIndex]
  }

  // Map an x offset within a slider to a 0-100 level, mirroring the geometry
  // PanelSlider uses internally (its knob is clamped to the track, so the
  // usable range is the track width inset by half a knob on each side).
  function levelFromX(x, sliderWidth) {
    var knob = Math.max(14, Math.round(Style.spacing.controlHeight * 0.38))
    var track = Math.max(1, sliderWidth - knob)
    var clamped = Math.max(0, Math.min(track, x - knob / 2))
    return Math.round((clamped / track) * 100)
  }

  function moveCursor(delta) {
    var list = visibleDevices
    if (!list.length) { selectedIndex = 0; return }
    if (!cursorActive) {
      cursorActive = true
      selectedIndex = 0
      return
    }
    selectedIndex = Math.max(0, Math.min(list.length - 1, selectedIndex + delta))
  }

  function activateCursor() {
    var device = cursorDevice()
    if (device) toggleDevice(device)
  }

  // +/- adjust the cursor row's dimmer level by 5.
  function nudgeLevel(delta) {
    var device = cursorDevice()
    if (!device || device.level === null) return
    setLevel(device, device.level + delta)
  }

  // ---- Bar button -------------------------------------------------------

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // Solid bulb when anything is on, hollow when everything is off.
    text: root.onCount > 0 ? "\uF0EB" : "\uF0EC"
    active: root.onCount > 0
    slotSize: Style.bar.statusSlot
    tooltipText: root.lastError !== ""
      ? "SmartThings — " + root.lastError
      : (root.devices.length === 0
          ? "SmartThings — loading"
          : "SmartThings — " + root.onCount + " of " + root.devices.length + " on")

    onPressed: function(b) {
      if (b === Qt.RightButton) root.refresh()
      else root.toggle()
    }
  }

  // Small count badge, hidden when nothing is on.
  Text {
    visible: root.onCount > 0
    anchors.left: parent.right
    anchors.leftMargin: Style.space(-4)
    anchors.top: parent.top
    anchors.topMargin: Style.space(1)
    text: root.onCount
    color: root.bar ? root.bar.urgent : Color.urgent
    font.family: root.bar ? root.bar.fontFamily : Style.font.family
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  // ---- Data plumbing ----------------------------------------------------

  // Path to the curated device list. Defaults to Blackarch's own per-source
  // menu file so the widget tracks whatever `blackarch shell generate` writes;
  // the `menuFile` setting can point it somewhere else (e.g. a personal list
  // that does not touch the shared menu).
  readonly property string menuPath: {
    var override = setting("menuFile", "")
    if (override !== "" && override !== null && override !== undefined)
      return String(override)
    return (Quickshell.env("BLACKARCH_PATH") || "/opt/blackarch")
           + "/default/blackarch/menus/smartthings.jsonc"
  }

  // Curated device list. watchChanges makes an edit (by
  // blackarch-launch-hackingTools or by hand) take effect live.
  FileView {
    id: menuFile
    path: root.menuPath
    watchChanges: true
    printErrors: false
    onLoaded: {
      root.menuDevices = Model.parseMenuDevices(text())
      root.reparse()
    }
    onLoadFailed: {
      root.menuDevices = ({ order: [], labels: {} })
      root.reparse()
    }
    onFileChanged: reload()
  }

  Timer {
    id: refreshTimer
    interval: root.refreshSeconds * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Process {
    id: statusProc
    // Same `</dev/null` reason as commandProc — this CLI blocks on a pipe stdin.
    command: ["bash", "-c", "smartthings devices --status -j -c switch </dev/null"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        if (raw === "") { root.lastError = "No response from smartthings"; return }
        root.lastPayload = raw
        root.applyStatus(raw)
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var err = String(text || "").trim()
        if (err !== "" && root.devices.length === 0) root.lastError = err.split("\n")[0]
      }
    }
    onExited: function(exitCode) {
      root.loading = false
      if (exitCode !== 0 && root.lastError === "") root.lastError = "smartthings exited " + exitCode
    }
  }

  Process {
    id: commandProc
    // Closed stdin is load-bearing: the CLI hangs forever on an open pipe.
    stdinEnabled: false
    stdout: StdioCollector { id: commandOut; waitForEnd: true }
    stderr: StdioCollector { id: commandErr; waitForEnd: true }
    onExited: function(exitCode) {
      var err = String(commandErr.text || "").trim()
      var out = String(commandOut.text || "").trim()
      if (exitCode === 0) root.commandFinished(true, "")
      else root.commandFinished(false, "Command failed: " + (err || out || ("exit " + exitCode)))
    }
  }

  // If a command neither exits nor errors, give up on it and move on rather
  // than wedging the queue for the rest of the session.
  Timer {
    id: commandWatchdog
    interval: root.commandWatchdogMs
    onTriggered: {
      if (!commandProc.running) return
      commandProc.running = false
      root.commandFinished(false, "Command timed out after " + Math.round(root.commandWatchdogMs / 1000) + "s")
    }
  }

  // Give the hub a moment to register the change before re-reading.
  Timer {
    id: settleTimer
    interval: 900
    onTriggered: root.refresh()
  }

  // ---- Popup ------------------------------------------------------------

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: filterField.activeFocus
      onMoveRequested: function(dx, dy) { root.moveCursor(dy !== 0 ? dy : dx) }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      // +/- (and =/_) adjust the dimmer on the cursor row.
      onTextKey: function(t) {
        if (t === "+" || t === "=") root.nudgeLevel(5)
        else if (t === "-" || t === "_") root.nudgeLevel(-5)
      }

      Flickable {
        id: scroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: panelColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: panelColumn
          width: scroll.width
          spacing: Style.space(6)

          // ---- Header
          Row {
            width: parent.width
            spacing: Style.space(8)

            Text {
              text: "SMARTTHINGS"
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1
              anchors.verticalCenter: parent.verticalCenter
            }

            Item { width: Math.max(0, parent.width - 260); height: 1 }

            Text {
              text: root.onCount + "/" + root.devices.length + " on"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
              anchors.verticalCenter: parent.verticalCenter
            }

            // Reminder that the list is the curated menu set, not every
            // switch in the account.
            Text {
              visible: root.curated
              text: "menu"
              color: Qt.darker(root.bar.foreground, 1.6)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.letterSpacing: 1
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              visible: root.loading
              text: "\uF021"
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.bodySmall
              anchors.verticalCenter: parent.verticalCenter

              RotationAnimator on rotation {
                running: root.loading
                from: 0; to: 360
                duration: 800
                loops: Animation.Infinite
              }
            }

            Rectangle {
              width: Style.space(18)
              height: Style.space(18)
              radius: Math.min(4, Style.cornerRadius)
              color: refreshArea.containsMouse ? Style.hoverFillFor(root.bar.foreground, Color.accent) : "#44ff88"
              anchors.verticalCenter: parent.verticalCenter

              Text {
                anchors.centerIn: parent
                text: "\uF01E"
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
              }

              MouseArea {
                id: refreshArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.refresh()
              }
            }
          }

          Rectangle {
            width: parent.width
            height: Style.spacing.hairline
            color: root.bar.foreground
            opacity: 0.12
          }

          // ---- Filter field
          TextField {
            id: filterField
            width: parent.width
            placeholderText: "Filter devices"
            foreground: root.bar.foreground
            font.family: root.bar.fontFamily
            onTextChanged: {
              root.filterText = text
              root.selectedIndex = 0
            }
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Escape) {
                text = ""
                root.filterText = ""
                keyCatcher.forceActiveFocus()
                event.accepted = true
              } else if (event.key === Qt.Key_Down) {
                root.cursorActive = true
                keyCatcher.forceActiveFocus()
                event.accepted = true
              }
            }
          }

          // ---- Error / empty states
          Text {
            visible: root.lastError !== ""
            width: parent.width
            text: root.lastError
            color: root.bar ? root.bar.urgent : Color.urgent
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          Text {
            visible: !root.loading && root.lastError === "" && root.visibleDevices.length === 0
            width: parent.width
            text: root.devices.length === 0 ? "No devices reported." : "No device matches the filter."
            color: Qt.darker(root.bar.foreground, 1.5)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            font.italic: true
          }

          // ---- Device rows
          Repeater {
            model: root.visibleDevices

            // Self-sizing row. Every child is declared before the MouseAreas
            // so nothing sizes itself from a sibling that already depends on
            // it — a Row's implicit size counts non-visible children too, so
            // a full-size MouseArea inside it collapses the whole row.
            Item {
              required property var modelData
              required property int index

              readonly property bool selected: root.cursorActive && index === root.selectedIndex
              readonly property bool isOn: modelData.state === "on"
              readonly property bool hasLevel: root.showLevels && modelData.level !== null

              width: panelColumn.width
              height: body.height + Style.space(8)

              Rectangle {
                anchors.fill: parent
                radius: Style.cornerRadius
                color: selected || nameArea.containsMouse || bodyHover.hovered
                  ? Style.hoverFillFor(root.bar.foreground, Color.accent)
                  : "transparent"
              }

              HoverHandler {
                id: bodyHover
                onHoveredChanged: if (hovered) {
                  root.cursorActive = true
                  root.selectedIndex = index
                }
              }

              Column {
                id: body
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(8)
                anchors.rightMargin: Style.space(8)
                spacing: Style.space(4)

                // ---- name row: dot · name · state · level · power button
                Item {
                  id: nameLine
                  width: parent.width
                  implicitHeight: Math.max(nameText.implicitHeight, Style.space(22))

                  Rectangle {
                    id: stateDot
                    width: Style.space(8)
                    height: Style.space(8)
                    radius: width / 2
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    color: isOn ? (root.bar ? root.bar.urgent : Color.urgent)
                                : Qt.darker(root.bar.foreground, 1.8)
                  }

                  // ---- Power toggle. Explicit affordance: the whole name
                  // strip also toggles, but this makes the action visible.
                  Rectangle {
                    id: powerButton
                    width: Style.space(22)
                    height: Style.space(22)
                    radius: Math.min(4, Style.cornerRadius)
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    color: powerArea.containsMouse
                      ? Style.hoverFillFor(root.bar.foreground, Color.accent)
                      : "transparent"

                    Text {
                      anchors.centerIn: parent
                      text: isOn ? "\uF011" : "\uF011"   // nf-fa-power_off
                      color: isOn ? (root.bar ? root.bar.urgent : Color.urgent)
                                  : Qt.darker(root.bar.foreground, 1.3)
                      font.family: root.bar.fontFamily
                      font.pixelSize: Style.font.body
                    }

                    MouseArea {
                      id: powerArea
                      anchors.fill: parent
                      hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: root.toggleDevice(modelData)
                    }
                  }

                  Text {
                    id: levelText
                    visible: hasLevel
                    text: modelData.level !== null ? modelData.level + "%" : ""
                    color: Qt.darker(root.bar.foreground, 1.4)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    width: Style.space(34)
                    horizontalAlignment: Text.AlignRight
                    anchors.right: powerButton.left
                    anchors.rightMargin: Style.space(4)
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Text {
                    id: stateText
                    text: isOn ? "ON" : (modelData.state === "unknown" ? "—" : "OFF")
                    color: isOn ? (root.bar ? root.bar.urgent : Color.urgent)
                                : Qt.darker(root.bar.foreground, 1.5)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.caption
                    font.letterSpacing: 1
                    width: Style.space(30)
                    horizontalAlignment: Text.AlignRight
                    anchors.right: levelText.visible ? levelText.left : powerButton.left
                    anchors.rightMargin: levelText.visible ? Style.space(6) : Style.space(4)
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Text {
                    id: nameText
                    text: modelData.name
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.body
                    elide: Text.ElideRight
                    anchors.left: stateDot.right
                    anchors.leftMargin: Style.space(8)
                    anchors.right: stateText.left
                    anchors.rightMargin: Style.space(6)
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  // Whole-strip click target (behind the power button, which
                  // is declared above it and so takes precedence).
                  MouseArea {
                    id: nameArea
                    width: parent.width - powerButton.width - Style.space(4)
                    height: parent.height
                    x: 0
                    y: 0
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.toggleDevice(modelData)
                  }
                }

                // Dimmer slider. Click the track (or drag) to set a level.
                //
                // PanelSlider's own MouseArea handles the wheel and fires
                // `released` on every notch, so scrolling anywhere over the
                // popup would silently change the level. It is a packaged
                // shared component (audio/monitor use it too), so instead of
                // editing it we render it inert and drive it from our own
                // handlers: a TapHandler for clicks, a DragHandler for drags,
                // and a WheelHandler that accepts the event so it cannot
                // scroll the device list underneath.
                PanelSlider {
                  id: levelSlider
                  visible: hasLevel
                  width: parent.width
                  bar: root.bar
                  minimum: 0
                  maximum: 100
                  step: 1
                  integer: true
                  tickCount: 0
                  enabled: false
                  value: modelData.level !== null ? modelData.level : 0
                }

                // Wheel over a slider is swallowed — never changes the level,
                // never scrolls the list behind it.
                WheelHandler {
                  enabled: hasLevel
                  acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                  onWheel: function(event) { event.accepted = true }
                }

                TapHandler {
                  enabled: hasLevel
                  acceptedButtons: Qt.LeftButton
                  onTapped: function(event) {
                    root.setLevel(modelData, levelFromX(event.position.x, levelSlider.width))
                  }
                }

                DragHandler {
                  id: levelDrag
                  enabled: hasLevel
                  acceptedButtons: Qt.LeftButton
                  target: null
                  onCentroidChanged: {
                    if (active) root.setLevel(modelData, levelFromX(centroid.position.x, levelSlider.width))
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  // ---- Lifecycle --------------------------------------------------------

  readonly property bool opened: panel.open

  function open() {
    root.refresh()
    panel.open = true
  }

  function close() {
    root.cursorActive = false
    panel.open = false
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root, direction)
    return false
  }

  IpcHandler {
    target: "blackarch.smartthings"

    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.refresh() }

    // ---- control by device id (scripting) ----
    function setSwitch(deviceId: string, state: string): string {
      var want = String(state).toLowerCase()
      if (want !== "on" && want !== "off") return "state must be 'on' or 'off'"
      var device = root.deviceById(deviceId)
      if (!device) return "unknown device: " + deviceId
      root.sendCommand(device.id, "switch:" + want)
      return "ok"
    }

    function toggleDeviceById(deviceId: string): string {
      var device = root.deviceById(deviceId)
      if (!device) return "unknown device: " + deviceId
      root.toggleDevice(device)
      return "ok"
    }

    function setLevelById(deviceId: string, level: string): string {
      var device = root.deviceById(deviceId)
      if (!device) return "unknown device: " + deviceId
      if (device.level === null) return "device has no switchLevel: " + device.name
      var n = Number(level)
      if (isNaN(n)) return "level must be a number 0-100"
      root.setLevel(device, n)
      return "ok"
    }

    // JSON summary, for scripts and for verifying the curated list is wired.
    function status(): string {
      var rows = []
      for (var i = 0; i < root.devices.length; i++) {
        var d = root.devices[i]
        rows.push({ id: d.id, name: d.name, state: d.state, level: d.level, curated: d.curated })
      }
      return JSON.stringify({
        menuPath: root.menuPath,
        curated: root.curated,
        menuCount: root.menuDevices.order.length,
        deviceCount: root.devices.length,
        onCount: root.onCount,
        error: root.lastError,
        devices: rows
      })
    }
  }

  Component.onCompleted: root.refresh()
}
