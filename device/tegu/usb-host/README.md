# USB-C host mode on the Pixel 9a: the bring-up setup

These are the parts of the 2026-10-28 host-mode run (NOTES, "USB-C host mode through TCPM") that aren't in a public tree yet. They're published so the run can be reproduced. They are bring-up files, not proposals for the kernel: the RT9470 boost will go upstream in whatever shape derekross/linux-omarchy-mobile#124 settles on (mainline `rt9471` with an optional interrupt, or an OTG-only driver).

| File | What |
| --- | --- |
| `usb-host.dtsi` | The DT fragment ("ot2"): the RT9470's OTG boost on `hsi2c10`, the MAX77779 charger's `chgin-otg` regulator over it, the TCPC as a dual-role port that prefers sink with that regulator as `vbus-supply`, and the graph from the connector to dwc3's role switch. The source PDO is stock's (fixed 5 V, 900 mA). |
| `tegu-rt9471-boost.c`, `Makefile` | The RT9470 as an OTG boost only: a regulator on `OTG_EN` (FUNCTION 0x02 bit 1). At probe it turns off JEITA (0x0C bit 7) and the I2C watchdog (TOP 0x01 bits 1:0). With either one on, VBUS collapsed under the boost. |

## What it builds on

- The kernel the palmtop ran: `7.3.0-rc6-omamobile-tegu-s2mpg15-m1-g991042e2eff3-dirty`, the integration tree. It carries the MAX77779 TCPC in `tcpci_maxim` (kernel #97, merged), the board's TCPC and fuel gauge nodes (kernel #119), the eUSB2 repeater (kernel #118) and the MAX77779 charger (kernel #92).
- The charger's `chgin-otg` regulator, kernel #124. The run used a superset of that driver (blob `1c71542965b0`), whose OTG code matches #124's head before the review changes (`f70a184098c3`).
- The `tcpci_maxim` module on the palmtop also had three bring-up parameters (`src_cmd`, `keep_sink`, `no_autodischarge`). All three were off by default and off in the run, so its behaviour was #97's.

## Runbook

Attended only: the drive swap takes out the laptop, which is the only link. Every step that can lose USB has a timer armed first.

1. **Build** (laptop or build machine): `make -C <kernel out> M=$PWD ARCH=arm64 LLVM=1 W=1 modules` builds `tegu-rt9471-boost.ko`. Add `usb-host.dtsi` to the board DTB after `zumapro-tegu.dts`'s own nodes.
   *Expect:* a clean build and a DTB that passes `dtc` with no new warnings. *Risk:* none.
2. **Install the module** under `/usr/lib/modules/$(uname -r)/updates/otg/`, run `depmod -a`, and re-pin the curated autostart manifest if it pins that directory.
   *Expect:* `modinfo tegu-rt9471-boost` resolves. *Risk:* none (nothing loads yet).
3. **Boot the DTB** with `bin/omamobile push` only, never a `flash`, with slot B already marked successful, and with the one-boot DTB dead-man armed (`tegu-dtb-deadman`: the good DTB comes back if the boot loses USB).
   *Expect:* `regulator.*` entries named `otg-boost` and `chgin-otg`, both `disabled`; the port is a sink, and the laptop charges the palmtop and reaches it over SSH.
   *Stop if:* SSH doesn't come back within 2 minutes (the dead-man restores the DTB).
   *Rollback:* push the previous DTB. *Risk:* medium (a boot).
4. **Arm the swap timer**, then swap the cable for the drive:
   `systemd-run --unit=x-deadman --on-active=300 systemctl reboot`
   *Expect:* the port becomes a source, `otg-boost` and `chgin-otg` read `enabled`, VBUS holds near 5.2 V, and the drive enumerates (`lsblk` shows it on `usb`).
   *Stop if:* the drive doesn't enumerate within a minute: plug the laptop back in.
5. **Back to the laptop**, then over a fresh login (`tools/phone-ssh --fresh`) `systemctl stop x-deadman.timer`.
   *Expect:* the port is a sink again, `CHG_CNFG_00` reads 0x05, and the palmtop charges.
   *Rollback for 4 and 5:* the timer reboots the palmtop 5 minutes after it was armed, and the boot comes back as a sink.

In the 10-28 run the swaps were attended (W4HO at the palmtop). The protection then was each sampling script's own dead-man rather than this timer: with no USB gadget configured 6 to 8 minutes after the cable came out, it unloaded `tcpci_maxim` and set the role switch back to device. The laptop came back as a sink every time, so it never fired.

## Not known yet

- **What a warm reboot with host mode on leaves behind.** With the RT9470's watchdog off, nothing turns its boost off after a crash. The OTG bit and `ICSTAT` before any driver loads haven't been read after a warm reboot with the drive attached, so whether VBUS stays out across one is unknown.
- **Why JEITA tripped.** JEITA reading "hot" is an inference: the RT9470's TS pin may have no thermistor on it. It isn't confirmed. Google's tegu tree leaves `en-jeita` commented out.
- **Whether the RT9470 charges under our kernel.** Its CE comes from the MAX77779's sGPIO 7, which hasn't been read. On the charger with the battery full (2026-10-28 evening), `FUNCTION` read 0x41 (`CHG_EN` set) and `ICSTAT` 0xf1 (IC state 1, VBUS ready, not charging). With JEITA off, the RT9470 has no temperature cut-off of its own, which matters only if it charges.
