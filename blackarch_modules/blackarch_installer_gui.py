#!/usr/bin/env python3
"""BlackArch graphical installer (PySide6)."""

import sys
import socket
import subprocess

sys.path.insert(0, "/opt/blackarch")
sys.path.insert(0, "/opt/blackarch/blackarch_modules")

from blackarch_modules.blackarch_installer_core import list_disks

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QTextEdit, QCheckBox
)


def main(argv=None):
    class InstallerGui(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("BlackArch Installer")
            layout = QVBoxLayout(self)

            self.disk = QComboBox()
            for d in list_disks():
                self.disk.addItem(f"{d['name']}  {d['size']}  {d['model']}", d["name"])
            self.scheme = QComboBox()
            self.scheme.addItems(["recommended", "custom"])
            self.install = QComboBox()
            self.install.addItems(["pacstrap", "clone"])
            self.esp = QLineEdit("1024")
            self.hostname = QLineEdit(socket.gethostname())
            self.bootloader = QComboBox()
            self.bootloader.addItems(["none", "limine", "systemd-boot", "both"])
            self.bootloader.setCurrentIndex(3)
            self.skip_copy_home = QCheckBox("Skip copy home")
            self.skip_copy_home.setChecked(False)
            self.skip_sudoers = QCheckBox("Skip sudoers.d")
            self.skip_sudoers.setChecked(False)
            self.keep_mounted = QCheckBox("Keep mounted")
            self.existing = QCheckBox("Existing install")
            self.no_encrypt = QCheckBox("No encrypt")
            self.skip_pacstrap = QCheckBox("Skip pacstrap")
            self.existing.stateChanged.connect(lambda: self.skip_pacstrap.setChecked(self.existing.isChecked()))
            self.existing.stateChanged.connect(lambda: self.skip_copy_home.setChecked(self.existing.isChecked()))
            self.existing.stateChanged.connect(lambda: self.skip_sudoers.setChecked(self.existing.isChecked()))
            self.skip_network = QCheckBox("Skip network")
            self.skip_timezone = QCheckBox("Skip timezone")
            self.skip_vm = QCheckBox("Skip VM")
            self.cache_dir = QLineEdit("")
            self.efi_part = QLineEdit("")
            self.root_part = QLineEdit("")
            self.luks_part = QLineEdit("")
            self.skip_home_dir = QLineEdit("")
            self.skip_home_ext = QLineEdit("")

            for label, widget in [("Disk", self.disk), ("Scheme", self.scheme),
                                  ("Install mode", self.install), ("ESP size (MiB)", self.esp),
                                  ("Hostname", self.hostname), ("Bootloader", self.bootloader)]:
                row = QHBoxLayout()
                row.addWidget(QLabel(label))
                row.addWidget(widget)
                layout.addLayout(row)

            for cb in (self.existing, self.keep_mounted, self.no_encrypt,
                       self.skip_copy_home, self.skip_network, self.skip_pacstrap,
                       self.skip_sudoers, self.skip_timezone, self.skip_vm):
                layout.addWidget(cb)

            for label, w in [("Cache dir", self.cache_dir), ("EFI part", self.efi_part),
                             ("Root part", self.root_part), ("LUKS part", self.luks_part),
                             ("Skip home dir", self.skip_home_dir), ("Skip home ext", self.skip_home_ext)]:
                row = QHBoxLayout()
                row.addWidget(QLabel(label))
                row.addWidget(w)
                layout.addLayout(row)

            self.log = QTextEdit()
            self.log.setReadOnly(True)
            layout.addWidget(self.log)

            btn = QPushButton("Install")
            btn.clicked.connect(self.run_install)
            layout.addWidget(btn)

        def run_install(self):
            cmd = ["sudo", "blackarch", "installer",
                   "--disk", self.disk.currentData(),
                   "--scheme", self.scheme.currentText(),
                   "--install", self.install.currentText(),
                   "--esp-size", self.esp.text(),
                   "--hostname", self.hostname.text(),
                   "--bootloader", self.bootloader.currentText()]
            if self.skip_copy_home.isChecked():
                cmd.append("--no-copy-home")
            else:
                cmd.append("--copy-home")
            if self.skip_sudoers.isChecked():
                cmd.append("--skip-copy-sudoers")
            if self.keep_mounted.isChecked():
                cmd.append("--keep-mounted")
            if self.existing.isChecked():
                cmd.append("--existing")
            if self.no_encrypt.isChecked():
                cmd.append("--no-encrypt")
            if self.skip_pacstrap.isChecked():
                cmd.append("--skip-pacstrap")
            if self.skip_network.isChecked():
                cmd.append("--skip-network")
            if self.skip_timezone.isChecked():
                cmd.append("--skip-timezone")
            if self.skip_vm.isChecked():
                cmd.append("--skip-vm")
            if self.cache_dir.text().strip():
                cmd += ["--cache-dir", self.cache_dir.text().strip()]
            if self.efi_part.text().strip():
                cmd += ["--efi-part", self.efi_part.text().strip()]
            if self.root_part.text().strip():
                cmd += ["--root-part", self.root_part.text().strip()]
            if self.luks_part.text().strip():
                cmd += ["--luks-part", self.luks_part.text().strip()]
            if self.skip_home_dir.text().strip():
                cmd += ["--skip-home-dir", self.skip_home_dir.text().strip()]
            if self.skip_home_ext.text().strip():
                cmd += ["--skip-home-ext", self.skip_home_ext.text().strip()]
            self.cmd = cmd
            self.close()

    app = QApplication(sys.argv)
    w = InstallerGui()
    w.cmd = None
    w.show()
    app.exec()
    if w.cmd:
        print("Running:", " ".join(w.cmd))
        subprocess.run(w.cmd)
        print("Equivalent command:", " ".join(w.cmd))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
