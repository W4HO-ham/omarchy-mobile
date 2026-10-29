<!-- SPDX-License-Identifier: MIT -->
# Pixel 9a sleep: why s2idle drains so much

Status (2026-10-29): s2idle works (RTC and power-key wakes; NFC and Wi-Fi
have their own notes in NOTES and AGENTS), but the drain in sleep is high.
This plan is an audit from the code, stock's device tree and a read-only
snapshot of the palmtop, with candidates ranked by how much they likely
cost, and a measurement runbook. Nothing here has been changed on the
palmtop yet.

Kernel: `7.3.0-rc6-omamobile-tegu-s2mpg15-m1-g991042e2eff3-dirty` (the
integration tree), the palmtop's bring-up DTB.

## What the earlier numbers do and don't say

The 10-28 measurements (434-445 mA as it runs, 374-389 mA with MIF capped
at 421 MHz) were taken with the screen on, so they measure the awake
system, not sleep. They do say that MIF's rate matters. The sleep number
still has to be measured, with the screen off and the cable out (runbook
below).

## Candidates

1. **No cluster or system idle states.** The CPUs have only WFI and the
   per-core `c2` state (PSCI `0x10000`, as in Google's `zumapro-cpu.dtsi`).
   Google adds cluster power-down for all three clusters (`cpd_cl0`-`cpd_cl2`)
   and a system state (`sicd`, idle clock-down), each with a 10 ms target
   residency, through Samsung's own `exynos-cpupm` driver and PMU wakeup
   masks, not through PSCI domain states. Mainline has neither, so in s2idle
   all three clusters stay powered and the SoC's clocks keep running. This is
   likely the largest share. The work is a cluster/SICD path for zumapro
   (PSCI OS-initiated domains if the firmware supports them, otherwise the
   PMU sequence `exynos-cpupm` uses), and it needs its own plan.
2. **GNSS rails always on.** LDO9S-11S (`gnss-core` 1.2 V, `gnss-rf` 1.8 V,
   `gnss-aux` 1.8 V) are `regulator-always-on` in the bring-up DTB, so the
   S5300's GNSS RF and core supplies stay up through sleep, with the modem
   off too. In stock's DT they carry `channel-mux-selection` (subsys GPS):
   the GNSS core switches them itself. Off unless the modem's GNSS runs.
3. **Fingerprint rail always on.** `udfps-3v3` (LDO15S) is also
   `regulator-always-on` in the bring-up DTB. The sensor only needs it while
   an operation runs.
4. **MIF and the interconnect.** The awake numbers moved by about 55 mA with
   MIF capped at 421 MHz. Whether MIF drops in s2idle, and to what, is
   unread.
5. **Smaller and unmeasured:** the eUSB2 repeater rails (`eusb-vdd`,
   `eusb-vdda12`), touch (on for touch wake), the AoC and its sensors (on by
   design), the NFC clock pad (always enabled while NFC is bound), and the
   modem when it has been started (no suspend is allowed then, by the
   inhibitor).

## Runbook (attended for the cable)

**S1. Baseline (risk low).** Screen off, Wi-Fi as it runs, modem not
started, cable out, `tools/power-ab` style detached logging of the fuel
gauge's `current_avg` and `capacity` every 30 s for 30 minutes of
`systemctl suspend` with RTC wakes every 5 minutes. Expect a number in mA.
Stop: the palmtop doesn't come back on the cable within 5 minutes of the
end (power key).

**S2. Rails (risk low).** Same as S1 with the three GNSS rails and
`udfps-3v3` not always-on (a DTB round, through `push`, slot B marked first).
Expect: S1 minus their share.

**S3. Clusters (risk medium-high).** After a cluster/SICD plan exists.

## Not known yet

- The real sleep drain (S1).
- Whether the firmware's PSCI supports OS-initiated cluster states on zumapro.
