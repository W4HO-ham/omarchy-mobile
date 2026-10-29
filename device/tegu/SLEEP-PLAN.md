<!-- SPDX-License-Identifier: MIT -->
# Pixel 9a sleep: why s2idle drains so much

Status (2026-10-29): s2idle works (RTC and power-key wakes; NFC and Wi-Fi
have their own notes in NOTES and AGENTS), but the drain in sleep is high.
This plan gathers what's measured, an audit from stock's device tree and
a read-only snapshot of the palmtop, the candidates ranked, and a
measurement runbook.

Kernel: `7.3.0-rc6-omamobile-tegu-s2mpg15-m1-g991042e2eff3-dirty` (the
integration tree), the palmtop's bring-up DTB.

## What's measured

- **s2idle with the cable out: about 140 mA** (59 minutes, 2026-10-27).
- **MIF in sleep** (cable in, buck off, Bluetooth blocked, 600 s RTC-woken
  freezes): 371-373 mA at MIF 2028 MHz, 314 mA at 421 MHz, so lowering MIF
  for sleep saves about 57 mA. With the cable in, the USB link keeps the
  SoC busy, so this can't reproduce the cable-out figure. A PM-notifier
  module (`tegu-mif-sleep`: 421 MHz at suspend-prepare, the old rate after
  resume) is the policy to measure with the cable out.
- **Cluster power-down was tried** (2026-10-28) through the hint Google's
  `exynos-cpupm` writes on each idle entry (`CPU_INFORM`, PMU 0x860 + 4 x
  cpu; 1 = C2, 2 = cluster power-down). The C2 hint was stable but saved
  nothing measurable. Cluster power-down on all three clusters stopped
  ACPM's DVFS channel within a second, then I2C and UFS stalled and the
  watchdog reset the palmtop (Google never powers down cluster 0:
  `cpd_cl0` has no `entry-allowed`). Clusters 1 and 2 alone were stable,
  but no saving was measurable, screen on or off. Dropped.

## Candidates

1. **MIF in sleep: about 57 mA**, measured with the cable in. Next is the
   cable-out measurement with `tegu-mif-sleep`.
2. **GNSS rails always on.** LDO9S-11S (`gnss-core` 1.2 V, `gnss-rf` 1.8 V,
   `gnss-aux` 1.8 V) are `regulator-always-on` in the bring-up DTB, so the
   S5300's GNSS supplies stay up through sleep, with the modem off too. In
   stock's DT they carry `channel-mux-selection` (subsys GPS): the GNSS
   core switches them itself. Off unless the modem's GNSS runs.
3. **Fingerprint rail always on.** `udfps-3v3` (LDO15S) is also
   `regulator-always-on` in the bring-up DTB. The sensor only needs it
   while an operation runs.
4. **The system idle state (SICD).** Google's `cpupm` has a system state
   (`sicd`, idle clock-down, 10 ms target residency) beside the cluster
   ones. It hasn't been tried, and it would need the same PMU sequence.
   Given the cluster results, it's lower than 1-3.
5. **Smaller and unmeasured:** the eUSB2 repeater rails (`eusb-vdd`,
   `eusb-vdda12`), touch (on for touch wake), the AoC and its sensors (on
   by design), the NFC clock pad (always enabled while NFC is bound), and
   the modem when it has been started (no suspend is allowed then, by the
   inhibitor).

The CPUs' own idle state works: cpu0's `c2` was entered about a million
times by 2026-10-29, with 1304 rejected (EINVAL); cpu4 1148 of 46339, cpu7
576 of 33173. The firmware's PSCI is v1.1 with no OS-initiated mode.

## Runbook (attended for the cable)

**S1. Baseline, then MIF (risk low; attended for the cable).** Screen off,
Wi-Fi as it runs, modem not started, cable out, detached logging of the fuel
gauge's charge counter and `capacity` every 30 s across 30 minutes of
`systemctl suspend` with RTC wakes every 5 minutes. Repeat with
`tegu-mif-sleep` loaded. Expect about 140 mA, then less. Stop: the palmtop
doesn't come back on the cable within 5 minutes of the end (power key).

**S2. Rails (risk low).** As S1 with the three GNSS rails and `udfps-3v3`
not always-on (a DTB round through `push`, with slot B marked first).
Expect: S1 minus their share.

## Not known yet

- What the GNSS and fingerprint rails cost in sleep (S2).
- What MIF in sleep saves with the cable out (S1).
