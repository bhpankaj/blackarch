import QtQuick
import qs.Ui

BarWidget {
  id: root
  moduleName: "blackarch.menu"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\ue900"
    fontFamily: "blackarch"
    horizontalMargin: 7.5
    onPressed: function(button) {
      if (!root.bar) return
      if (button === Qt.RightButton) root.bar.run("blackarch execute gui kitty")
      else root.bar.run("blackarch-shell shell toggle blackarch.menu '{\"menu\":\"root\"}'")
    }
  }
}
