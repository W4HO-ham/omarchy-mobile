<!-- SPDX-License-Identifier: MIT -->
# Pixel 9a device policy

Experimental tegu support: the unchanged storage guard's udev policy, USB
networking and the device descriptor. The package does not start firmware,
radio, audio, charging, fingerprint or other unqualified hardware services.
It contains no vendor files or per-phone data.

The CS40L26 feedbackd rule is reused unchanged from the Pixel7 Pro package.
It identifies an already registered force-feedback input and grants desktop
access; it does not load the driver, power hardware or send a vibration.

The LM3644 torch rule grants the existing video group write access only to
`white:torch/brightness` owned by that driver, for the normal quick-settings
`brightnessctl` path. It neither loads a driver nor turns on the light. The
kernel board current cap remains authoritative. On the local d816 kernel,
the owner has confirmed rear-light on/off through the existing tile at the
single tested minimum step; brightness tuning is still separate.

The qualified storage path and remaining standalone-boot limitation are in
`device/tegu/UFS-PLAN.md` and `BOOT-PLAN.md`. The temporary recovery module
is a bring-up tool, not production reboot support. `reboot-to` by itself
does not provide the tested guarded bootloader route on this kernel.

Build with `makepkg`; `test/all` checks the staged storage and USB policy.
The package is self-contained and provides/conflicts with `omamobile-device`.
