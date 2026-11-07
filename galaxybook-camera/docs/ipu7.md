# IPU7 camera stack — what `--ipu7` does and why the flavour matters

The IPU6 Galaxy Book fix in this script is a *different* stack from the Intel
IPU7 one. They are not interchangeable, and installing the wrong one produces a
camera node with no frames.

## Detect the controller, never the sensor

`ov08x40` (ACPI HID `OVTI08F4`) is used with **both** IPU6 and IPU7, so gating
on the sensor alone installs the IPU7 stack on machines where it cannot work.
That is a real, open upstream bug (omarchy#7697, #14069). This script therefore
gates on the PCI device id first:

| PCI id   | Platform                     | Stack that works                          |
|----------|------------------------------|-------------------------------------------|
| `b05d`   | Panther Lake IPU7.5          | distro package (HAL built for `ipu75xa`)  |
| `645d`   | Lunar Lake IPU7              | kernel module + firmware + HAL            |
| `7d19`   | Arrow Lake IPU7              | distro HAL may not cover it               |
| `a75d`   | Raptor Lake-P IPU6 (this box)| the default IPU6 path in this script      |

`ipu_generation()` reads the bound driver name from `/sys/bus/pci/devices/*/driver`
(authoritative) and only falls back to the loaded module or the raw PCI id when
no driver is bound. `--ipu7` refuses to run when the controller is not IPU7.

## The three flavours

```
sudo blackarch-webcam-setup --ipu7           # distro package (default)
sudo blackarch-webcam-setup --ipu7 dkms      # kernel module only
sudo blackarch-webcam-setup --ipu7 git       # AUR stack
sudo blackarch-webcam-setup --ipu7 status    # report only, install nothing
```

- **distro** — `intel-ipu7-camera` (omarchy repo): kernel module + firmware +
  proprietary HAL + `icamerasrc` + `v4l2-relayd@ipu7`. This is the only flavour
  that actually produces frames end-to-end, because the pipeline is built by the
  HAL. Also enables `intel-ipu7-camera.service` and the relay unit.
- **dkms** — `intel/ipu7-drivers` built against the running kernel
  (`dkms add . && dkms autoinstall ipu7-drivers/0.0.0`). The driver alone creates
  `/dev/media*` nodes but **no usable camera**: IPU7 needs the firmware and HAL
  to build the pipeline. The script says so and stops there.
- **git** — `intel-ipu7-{dkms-git,camera-bin,camera-hal-git}` via paru/yay.

The kernel needs `CONFIG_IPU_BRIDGE` (built-in on this kernel, `=m` here) and
`CONFIG_INTEL_SKL_INT3472` for sensors with discrete power control.

## Why the IPU7 stack fails on IPU6 hardware

The distro package ships one CamHAL plugin, `ipu75xa.so`. On an IPU6 controller
`icamerasrc` asks for the IPU6 plugin and finds none, so `v4l2-relayd@ipu7`
creates its loopback with a black/frozen frame. On IPU6 the working path is the
in-tree `intel_ipu6_isys` driver plus libcamera (`libcamera`, `libcamera-ipa`,
`pipewire-libcamera`) — i.e. the IPU6 half of this script, which is why the
default mode stays IPU6.

## Verify after reboot

```bash
sudo blackarch-webcam-setup --ipu7 status          # controller, module, stack, relay
sudo dmesg | grep -i -E 'ipu7|ipu_bridge|ov08x40'
ls /dev/media*                                     # media graph present
v4l2-ctl --list-devices                            # look for the relay node
```

`--check-only` prints the IPU generation line for every mode, so it is safe to
run on any machine to see which stack applies.
