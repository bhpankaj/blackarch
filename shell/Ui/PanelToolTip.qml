import QtQuick
import QtQuick.Controls
import qs.Commons

// Styled wrapper around Qt Quick Controls ToolTip. Drop-in: declare inside
// the hovered item and bind `visible` to the hover state, e.g.
//   PanelToolTip {
//     visible: mouse.containsMouse
//     text: "Forget network"
//   }
//
// Defaults pull from [tooltip] in shell.toml via Color.tooltip.*. Override
// the panel* properties per-instance only when you need a tooltip that
// intentionally diverges from the theme.
//
// Property names are prefixed `panel*` to avoid clashing with ToolTip's
// built-in `background`/`font` properties.
ToolTip {
  id: root

  property color panelForeground: (typeof Color !== "undefined" && Color.tooltip && Color.tooltip.text !== undefined) ? Color.tooltip.text : "#ffffff"
  property color panelBackground: (typeof Color !== "undefined" && Color.tooltip && Color.tooltip.background !== undefined) ? Color.tooltip.background : "#0a0a0a"
  property color panelBorder: (typeof Color !== "undefined" && Color.tooltip && Color.tooltip.border !== undefined) ? Color.tooltip.border : "#333333"
  property string fontFamily: (typeof Style !== "undefined" && Style.font) ? Style.font.family : "sans-serif"
  property real fontSize: (typeof Style !== "undefined" && Style.font) ? Style.font.bodySmall : 12

  readonly property var panelBorderSpec: Border.localOrSurfaceSpec("tooltip", "border", panelBorder, panelBorder, (typeof Style !== "undefined") ? Style.normalBorderWidth : 1)

  delay: 400
  padding: 0

  background: BorderSurface {
    color: root.panelBackground
    borderSpec: root.panelBorderSpec
    radius: (typeof Style !== "undefined") ? Style.cornerRadius : 4
  }

  contentItem: Text {
    textFormat: Text.PlainText
    text: root.text
    color: root.panelForeground
    font.family: root.fontFamily
    font.pixelSize: root.fontSize
    leftPadding: Border.left(root.panelBorderSpec) + ((typeof Style !== "undefined" && Style.spacing) ? Style.spacing.controlPaddingX : 4)
    rightPadding: Border.right(root.panelBorderSpec) + ((typeof Style !== "undefined" && Style.spacing) ? Style.spacing.controlPaddingX : 4)
    topPadding: Border.top(root.panelBorderSpec) + ((typeof Style !== "undefined" && Style.spacing) ? Style.spacing.controlPaddingY : 4)
    bottomPadding: Border.bottom(root.panelBorderSpec) + ((typeof Style !== "undefined" && Style.spacing) ? Style.spacing.controlPaddingY : 4)
  }
}
