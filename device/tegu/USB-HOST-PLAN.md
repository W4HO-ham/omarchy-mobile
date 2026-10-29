<!-- SPDX-License-Identifier: MIT -->
# Pixel 9a USB-C host mode: setup and runbook

Status (2026-10-29): host mode worked end to end on 2026-10-28 (NOTES, "USB-C
host mode through TCPM"). This plan is the setup that run used and the
runbook for the next one, which adds two measurements for
derekross/linux-omarchy-mobile#124: unbinding the charger with a drive
attached, and a reset without shutdown with host mode on. The device tree and
the RT9470 module are on the kernel bring-up branch
derekross/linux-omarchy-mobile#127 (`tegu-usb-host-bringup` at `5dd15e31c`, not
for merge). The two boot helpers are in `device/tegu/usb-host/`.

## What it builds on

| Piece | Where |
| --- | --- |
| Board DT: fuel gauge, TCPC node | derekross/linux-omarchy-mobile#119 |
| `usi10`/`hsi2c10`, its pins, the RT9470 node, the TCPC as dual-role with `vbus-supply`, the graph to dwc3 | #127 (USI10 clocks: #102, merged) |
| RT9470 OTG boost module (`tegu-rt9471-boost`) | #127. JEITA and the watchdog are off only while the boost is enabled |
| MAX77779 charger and its `chgin-otg` regulator | #92, #124 (head `4970bcdc3820`) |
| MAX77779 TCPC in `tcpci_maxim` | #97 (merged) |
| eUSB2 repeater, PHY | #118, the integration tree |
| Kernel the palmtop runs | `7.3.0-rc6-omamobile-tegu-s2mpg15-m1-g991042e2eff3-dirty` (integration tree) |

The palmtop already boots a DTB with this setup (the "gn3" round), so the next
run boots no new DTB and needs no DTB dead-man. The `tegu-dtb-deadman` used
on 10-28 was a one-boot unit: if the gadget wasn't configured 180 s into an
armed boot, it wrote a known-good `vendor_kernel_boot` image (checked against
a stored sha256 first, and read back after) into `vendor_kernel_boot_b` from
the palmtop and rebooted. It is a second path writing slot B next to `bin/omamobile
push`. It stays unarmed, and it won't be used again unless that's agreed first.

**The curated autostart** is the 9a's private bring-up startup
(`/usr/local/lib/omamobile-tegu-curated/<release>/curated-native-start.py`,
with a manifest of sha256 pins). It loads the display, GPU and touch modules
in order, refuses a pinned file that changed, and masks units the bring-up
doesn't run. It doesn't pin or load the USB-C modules: those load through
udev from their DT nodes. Re-pinning (recomputing the manifest's sha256 values
after a deliberate change) only matters when a pinned module changes. This
runbook changes none.

## Runbook (attended, on the charger, W4HO at the palmtop)

Forced restart if the palmtop hangs, also in a shutdown under the swap timer:
hold Power about 30 s until it is off, then press Power. Stop the run if slot
B isn't marked successful: this runbook doesn't mark it (marking is a separate
`devinfo` operation under the rules settled on #125), and nothing here
writes a boot partition.

**H1. Precondition (read-only; risk none).** `tools/phone-ssh 'uname -r;
cat /proc/device-tree/__symbols__/otg_boost; for r in /sys/class/regulator/*;
do grep -H . $r/name; done | grep -E "otg-boost|chgin-otg"'`.
Expect: the release above, the `otg_boost` symbol, and both regulators.
Stop: either regulator missing (an older DTB).

**H2. Modules for the run (risk low).** Blacklist the boost module, so its
node can't load it before the early read: `echo "blacklist tegu_rt9471_boost"
> /etc/modprobe.d/omamobile-tegu-otg-bringup.conf`. Install the boost module
from #127 (`597a2251…`) and the charger built from #124's head `4970bcdc3820`
(`e5a4c78e…`), both staged in `/var/lib/omamobile-tegu/usb-host/`, over
`/usr/lib/modules/$(uname -r)/updates/otg/`, keeping the old files as
`*.before-h2`, then `depmod -a`. These live under one release's `updates/`,
so after every `push` of a new kernel they must be rebuilt and reinstalled.
Rollback: put the `*.before-h2` files back and run `depmod -a`.

**H3. Boot with the boost module held back (risk low).** Reboot, with kmsg
streamed to the laptop. Expect: the gadget comes up as before (it ran before
the TCPC node existed), the charger waits for `otg-boost-supply`, and the
TCPC waits for the charger. Stop: no SSH 3 minutes after the reboot (forced
restart, then H2's rollback). Then load the boost module by hand (`modprobe
tegu_rt9471_boost`) with kmsg streamed. Expect: `otg-boost` and `chgin-otg`
registered and disabled, and the TCPC probes as a sink with the laptop
attached.

**H4. Unbind the charger with the drive attached (#124; risk medium).**
Arm the swap timer first: `systemd-run --unit=x-deadman --on-active=300
systemctl reboot`. Swap the laptop for the drive. Expect host mode as on
10-28 (the drive enumerates). Then, from a script started before the swap,
unbind `max77779-charger` 20 s after the drive enumerates and log kmsg,
VBUS (TCPC 0x70/0x71) and `CHG_CNFG_00` (0xbc). Expect a clean kmsg, VBUS
at 0 and `CHG_CNFG_00` reading 0x05. Laptop back in. Over a fresh login
(`tools/phone-ssh --fresh`), stop the timer: `systemctl stop x-deadman.timer`.
Stop: the laptop doesn't come back as a sink before the timer fires.

**H5. Reset without shutdown with host mode on (#124, #127; risk
medium-high).** Arm the early read for the next boot (`mkdir -p
/var/lib/omamobile-tegu/rt9470-early-read; touch
/var/lib/omamobile-tegu/rt9470-early-read/armed`; the script and unit are in
`device/tegu/usb-host/`). With the boost module blacklisted from H2, the read
runs before any RT9470 driver. Arm the swap timer, swap to the drive, and
from a script started before the swap, `echo b > /proc/sysrq-trigger` 20 s
after the drive enumerates. `systemctl reboot` would run the charger's
`.shutdown`, which turns the boost off, so it can't show what a crash leaves.
Then, with an inline USB-C meter between the palmtop and the drive:
- Expect: VBUS falls to 0 within the reboot.
- **Stop if VBUS is still up two minutes after the reset.** Don't plug the
  laptop in (two sources on VBUS). Unplug the drive and report it.
- Otherwise put the laptop back in. The log `/var/log/omamobile/rt9470-early-read.log`
  has the OTG bit (FUNCTION 0x02 bit 1) and ICSTAT before any driver, and
  again at 60 s. If the boost had survived, a read at 60 s also shows
  whether the regulator core's unused-regulator cleanup turned it off (only
  if the module had loaded by then, which H2's blacklist prevents; a second
  run without the blacklist would show it).

**H6. Afterwards (risk low).** Remove `omamobile-tegu-otg-bringup.conf`, run
`depmod -a`, and reboot. The modules stay as installed in H2, unless H2's
rollback is wanted.

## Not known yet

- What a reset without shutdown leaves with host mode on (H5).
- Why JEITA tripped. "Read hot" is an inference: the TS pin may have no
  thermistor on it.
- Whether the RT9470 charges under our kernel. Its CE comes from the
  MAX77779's sGPIO 7, which hasn't been read. On the charger with the
  battery full, FUNCTION read 0x41 (`CHG_EN` set) and ICSTAT 0xf1 (VBUS
  ready, not charging). Since #127 turns JEITA off only while the boost is
  on, this matters only in host mode.
- Where stock's source PDO (5 V, 900 mA in the run) comes from. It isn't
  traced to a stock file yet.
