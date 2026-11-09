import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

PopupWindow {
    id: root
    width: 360
    height: 520
    color: "transparent"

    property var menuData: []

    // Run the Python script at runtime to read multiple menu files and output JSON
    Process {
        id: menuLoader
        // Pass multiple menu files as arguments to your parser script
        command: ["python3", "/opt/blackarch/bin/blackarch-xdg-menu-parser", 
                  "/etc/xdg/menus/red-applications.menu", 
                  "/etc/xdg/menus/blue-applications.menu", 
                  "/etc/xdg/menus/mitre-applications.menu", 
                  "/etc/xdg/menus/xfce-applications.menu", 
                  "/etc/xdg/menus/arch-applications.menu"]
        
        running: true
        stdout: SplitParser {
            onRead: data => {
                try {
                    root.menuData = JSON.parse(data)
                } catch (e) {
                    console.log("Failed to parse menu JSON: " + e)
                }
            }
        }
    }

    // Process launcher for executing selected app commands
    Process {
        id: launcher
    }

    Rectangle {
        anchors.fill: parent
        color: "#1e1e2e"
        radius: 12
        border.color: "#313244"
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8

            // Search Bar
            TextField {
                id: searchInput
                Layout.fillWidth: true
                placeholderText: "Search applications..."
                color: "#cdd6f4"
                background: Rectangle {
                    color: "#11111b"
                    radius: 6
                    border.color: searchInput.activeFocus ? "#89b4fa" : "#45475a"
                }
            }

            // Categorized Application ListView
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                ListView {
                    model: root.menuData
                    spacing: 6

                    delegate: ColumnLayout {
                        width: ListView.view.width
                        spacing: 2

                        // Category Header
                        Rectangle {
                            Layout.fillWidth: true
                            height: 28
                            color: "#313244"
                            radius: 4

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.leftMargin: 8
                                text: modelData.category
                                color: "#89b4fa"
                                font.bold: true
                                font.pixelSize: 13
                            }
                        }

                        // Category Items
                        Repeater {
                            model: modelData.items

                            delegate: Rectangle {
                                id: itemRect
                                readonly property bool matchesSearch: searchInput.text === "" || modelData.name.toLowerCase().includes(searchInput.text.toLowerCase())
                                
                                Layout.fillWidth: true
                                height: matchesSearch ? 30 : 0
                                visible: matchesSearch
                                color: itemMouse.containsMouse ? "#45475a" : "transparent"
                                radius: 4

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.left: parent.left
                                    anchors.leftMargin: 16
                                    text: modelData.name
                                    color: "#cdd6f4"
                                    font.pixelSize: 12
                                }

                                MouseArea {
                                    id: itemMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    onClicked: {
                                        launcher.command = ["sh", "-c", modelData.exec]
                                        launcher.running = true
                                        root.visible = false
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
