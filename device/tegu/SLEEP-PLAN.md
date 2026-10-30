<!-- SPDX-License-Identifier: MIT -->
# Pixel 9a sleep: why s2idle drains so much

Status (2026-10-29): s2idle works (RTC and power-key wakes; NFC and Wi-Fi
have their own notes in NOTES and AGENTS), but the drain in sleep is high.
This plan gathers what's measured, an audit from stock's device tree and
a read-only snapshot of the palmtop, the candidates ranked, and a
measurement runbook.

Kernel: `7.3.0-rc6-omamobile-tegu-s2mpg15-m1-g991042e2eff3-dirty` (the
integration tree), the palmtop's bring-up DTB. The code the runbook boots
is on the bring-up branch `tegu-sleep-bringup` of the kernel fork (not for
merge):

- the MIF module, `tegu-mif-sleep`:
  <https://github.com/W4HO-ham/linux-omarchy-mobile/commit/adbca4c88a21c32ed2fdf3454dc048a50bccd8dd>;
- the bring-up DT as it runs (the dtsi included at the end of
  `zumapro-tegu.dts` in the integration tree):
  <https://github.com/W4HO-ham/linux-omarchy-mobile/commit/af56e6307ddd4d332dec252917add74645101225>;
- S2's change, the four rails no longer always-on:
  <https://github.com/W4HO-ham/linux-omarchy-mobile/commit/054ee78086fbce5881f82eafc65bd19301853ef4>.

## What's measured

The figures are from the 2026-10-27 and 10-28 NOTES entries
(<https://github.com/derekross/omarchy-mobile/pull/100>).

- **s2idle with the cable out: about 300 mA** (302 mA over two 30-minute
  sleeps on 2026-10-29, S1 below; the 140 mA read on 2026-10-27 didn't
  hold up and is retired there).
- **MIF in sleep** (cable in, buck off, Bluetooth blocked, 600 s RTC-woken
  freezes): 371-373 mA at MIF 2028 MHz, 314 mA at 421 MHz, so lowering MIF
  for sleep saves about 57 mA. With the cable in, the USB link keeps the
  SoC busy, so this can't reproduce the cable-out figure. A PM-notifier
  module (`tegu-mif-sleep`: 421 MHz at suspend-prepare, the old rate after
  resume; the commit above) is the policy to measure with the cable out.
- **Cluster power-down was tried** (2026-10-28) through the hint Google's
  `exynos-cpupm` writes on each idle entry (`CPU_INFORM`, PMU 0x860 + 4 x
  cpu; 1 = C2, 2 = cluster power-down). The C2 hint was stable but saved
  nothing measurable. Cluster power-down on all three clusters stopped
  ACPM's DVFS channel within a second, then I2C and UFS stalled and the
  watchdog reset the palmtop (Google never powers down cluster 0:
  `cpd_cl0` has no `entry-allowed`). Clusters 1 and 2 alone were stable,
  but no saving was measurable, screen on or off. Dropped.
  For the record, what wrote the hints: a bring-up kernel module,
  `tegu-cpuinform` (a `cpu_pm` notifier, out of tree, on the laptop only;
  it was dropped with the result and isn't published), writing each
  core's `CPU_INFORM` word with the PMU register-write SMC (function
  0x82000504, the call the kernel's `gs101-pmu` regmap write uses) from
  the notifier, not through the `exynos-pmu` regmap and not from
  userspace. If SICD ever becomes a step, its PMU sequence goes through the
  kernel's `exynos-pmu` regmap.

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

### Stock's consumers of the four rails (checked 2026-10-29)

Before S2 turns LDO9S, LDO10S, LDO11S and LDO15S off, the question was
whether anything else on stock draws from them. Checked in stock's base
DT (the DTB in stock's `vendor_kernel_boot`, decompiled) and in all ten
board overlays of stock's `dtbo`: none of the four nodes carries a
`phandle`, so no node names any of them as a supply (a consumer would
force one; LDO12S, `L12S_CAMIO`, has one, from the cameras), and no
overlay fixup names them either. The three GNSS rails are `subsys-name
"GPS"` with `channel-mux-selection` 0x29-0x2b, so stock's GNSS core
switches them through the PMIC's channel mux; LDO15S is `L15S_SPARE`,
`regulator-always-on` on stock, subsys Spare, with no consumer in the DT
(the fingerprint sensor node has no supply; FINGERPRINT-PLAN). So the
four feed GNSS and the fingerprint sensor only, by stock's DT.

A phandle finds every DT supply reference, but the regulator core also
looks a supply up by `regulator-name` when a driver asks for one the DT
doesn't give it, so stock's kernel source was grepped for the four names
too (`L15S_SPARE`, `L9S_GNSS_CORE`, `L10S_GNSS_RF`, `L11S_GNSS_AUX`, and
`S2MPG15_LDO9`-`11`/`15`): `devices/google/tegu`, `devices/google/zuma*`
and `google-modules`. They appear only in device tree sources
(`zumapro-pmic.dtsi`, `zuma-pmic.dtsi`, the GNSS board dtsi files, and
tegu's udfps dtsi, which makes LDO15S always-on at 3.3 V) and in the
S2MPG15 register header. No vendor module asks for any of them by name:
the GNSS module uses no regulator at all, and the fingerprint tree's
`regulator_get` by name is in the FPC driver, not tegu's Goodix one. The
gap is closed.

## Runbook (attended for the cable)

Preconditions for the whole runbook:

- **Slot B.** Stop if slot B isn't marked successful; this runbook doesn't
  mark it (on the 9a marking is a `devinfo` write, under the rules being
  settled on <https://github.com/derekross/omarchy-mobile/pull/125>). An unmarked
  B burns an ABL retry on every boot, and a cycle that resets the palmtop
  counts as one.
- **NFC.** S1 and S2 run `systemctl suspend` cycles, and on the 9a a
  suspend with neard polling reset the palmtop (2026-10-27; AGENTS,
  "Suspend and modem"). Before the first cycle: the stop-poll sleep hook
  (`omamobile-tegu-nfc` on the palmtop, not in the repository yet) is
  installed and its unit active, or polling is stopped by hand. Either
  way, read neard's `Polling` property before each run (a neard restart
  starts polling again):

  ```sh
  tools/phone-ssh 'busctl get-property org.neard /org/neard/nfc0 org.neard.Adapter Polling'
  ```

  It must read `b false`. The
  palmtop's current kernel carries the nxp-nci change of
  <https://github.com/derekross/linux-omarchy-mobile/pull/131> (its
  `core.c` is in the running tree, blob 77fc35b61da5), which turns the
  ST54L's NFC mode on after init; it doesn't lift the rule. NFC still
  loses its NCI state across s2idle
  (<https://github.com/derekross/omarchy-mobile/issues/132>,
  <https://github.com/derekross/omarchy-mobile/pull/137>), so NFC must not
  poll through these cycles.
- **If a cycle doesn't come back** (no wake within 5 minutes, no answer on
  the cable): Power held about 30 s, then Power. Then, before anything
  else, read `/sys/fs/pstore` (systemd-pstore moves it to
  `/var/lib/systemd/pstore` at boot) and quote the end of the console log
  in this plan.

**S1. Baseline, then MIF (risk low; attended for the cable).** Screen off,
Wi-Fi as it runs, modem not started, cable out. The run is `tools/power-ab`
with the systemd suspend mode of
<https://github.com/derekross/omarchy-mobile/pull/157>, so S1 waits for
#157 to merge:

```sh
tools/phone-ssh 'power-ab --detach --unplug 180 --phase 1800 --rounds 2 --suspend systemd s2idle'
```

`--suspend systemd` arms the RTC with `rtcwake -m no` and runs `systemctl
suspend`, so the NFC sleep hook runs (a freeze written to
`/sys/power/state` would skip it). On the 9a always pass it: `power-ab`'s
default, `--suspend rtcwake`, is a direct freeze, the path that fails to
wake (the S1 result below), and a detached cable-out run is the worst place
for one. Phase A is awake with the screen off,
phase B is the 30-minute sleep, two rounds. The 9a's gauge has no
`charge_counter`, so the figure is the `charge_now` column of the CSV
(column 7, `charge_now_uah`): the gauge's model-corrected remaining
charge, coarser than a coulomb counter, hence the long phases. Repeat with
`tegu-mif-sleep` loaded (the module commit above, built against the running
kernel). Expect about 300 mA, then less. Stop: the palmtop doesn't come
back on the cable within 5 minutes of the end (power key). Rollback:
`rmmod tegu-mif-sleep` (the module changes nothing while awake: it sets the
rate at suspend-prepare and puts the old one back at resume), or a reboot.

**S1 result (2026-10-29, `7.3.0-rc6-omamobile-tegu-s2mpg15-m1-g991042e2eff3-dirty`,
device-tegu 0.2.0).** The baseline ran as written (cable out, screen off,
Wi-Fi kept, modem not started, two 30-minute `systemctl suspend` rounds
through `power-ab --suspend systemd`), then the pieces were pulled apart
with the cable in.

- **Cable out: 311 mA awake with the screen off, 302 mA asleep** (phase A
  3434 samples of `current_now`; phase B 302.5 mAh of `charge_now` over
  3604 s, two rounds, both woken by the RTC through the PMIC, `success` 2).
  Sleep saves nothing over the awake screen-off state. The 140 mA of
  2026-10-27 is the outlier: a cable-out A/B on 2026-10-28
  (`logs/tegu-morning-20261028/sleep-ab-20261028b.log`) already read 434
  and 445 mA asleep as-is and 374 and 389 mA with MIF at 421 MHz.
- **The CPUs do sleep.** A 60 s `systemctl suspend` with the cable in ran
  with `Timekeeping suspended for 60.059 seconds` and each cluster's deep
  state entered once in s2idle (`cpuidle/state1/s2idle/usage` +1 per CPU),
  so no interrupt keeps the cores up. What stays on is everything below
  them: MIF and the buses at full rate, and the always-on rails. Google's
  kernel has a system idle state (SICD) for this; ours has none.
- **The radios cost nothing at idle** (cable in, buck off through
  `CHG_CNFG_00` 0x00 under a dead-man restore, screen off, 45 s means of
  `current_now`): baseline 351 mA, Bluetooth off 355, NFC driver unbound
  356, Wi-Fi link down 360. All within noise.
- **MIF at 421 MHz in sleep saves about 60-75 mA.** Cable in, buck off,
  240 s `systemctl suspend` sleeps measured by the gauge's coulomb counter
  (`QH`, register 0x4d of the fuel gauge at 0x36 on bus 24; 2.5 mAh per
  count, checked against 60 s of `current_now`): as-is 12 counts, 446 mA;
  with `tegu-mif-sleep.ko` 10 counts, 371 mA (one count is 37 mA at this
  length). This matches the 2026-10-28 figure (57 mA). The module loads,
  unloads and wakes cleanly; the palmtop now loads it at boot from a hand
  unit, `/etc/systemd/system/tegu-mif-sleep.service`
  (`insmod /var/lib/omamobile-tegu/tegu-mif-sleep.ko`, the module built
  from `adbca4c88a21` above against this release), until the policy is in
  the kernel or the device package. Rollback: `systemctl disable --now
  tegu-mif-sleep; rmmod tegu_mif_sleep` (nothing changes while awake), and
  the module must be rebuilt for every kernel push. Cable-in figures sit about
  140 mA above cable-out ones (the USB link keeps the SoC busy).
- **Sleeps that never wake, three so far, and no single cause.** Not
  woken by the RTC alarm, nor by the power key, and reset by hand with
  Power + Volume Up: a direct `rtcwake -m freeze` of 10 min on 2026-10-28
  (MIF as it was, after two 421 MHz sleeps that woke); a direct freeze of
  240 s on the night of 2026-10-29 (NFC blocked, polling already stopped);
  and on 2026-10-30 a `systemctl suspend` of 30 min, cable out, through
  `power-ab --suspend systemd` with `tegu-mif-sleep` loaded (the A phase
  ran at about 300 mA, the B freeze was logged, nothing after; the owner's
  65-minute timer ran out with the palmtop dark). Woke: 35 short systemd
  cycles on 2026-10-27, two 30-minute and four 240 s systemd sleeps on
  2026-10-29 (one of the four with the module), two 10-minute direct
  freezes with the module on 2026-10-28. So neither the entry method nor
  the module alone explains it. Until it is understood: every sleep test
  is attended, the cable-out run's sleep phase is kept to what the owner
  can watch, `power-ab` still runs with `--suspend systemd` (the sleep
  hooks run that way), and the hand unit that loaded `tegu-mif-sleep` at
  boot is disabled (2026-10-30). Nothing in pstore for any of the three: a
  held power key is a pin reset, and the console log doesn't survive it;
  the cable-out S1 figure with the module is therefore still missing.
  Next on this: a way to see the hung state (the RTC alarm registers and
  the wake sources after a forced reset are gone; a kmsg stream to the
  laptop needs the cable, so a cable-in 30-minute systemd sleep with the
  module, logged, is the next cheap test).
- A later note on the method: `power-ab`'s CSV columns are
  `voltage_uv,current_ua,current_avg_ua,charge_counter_uah,charge_now_uah`;
  the gauge's `current_avg` is a long filter and says little about a
  30-minute window, so read `charge_now` (or `QH`) across the sleep.

**S1 method, cable in (the steps the measurements above used; S2 reuses
them).** Each goes into the runbook before it runs; the charger write ran
tonight before it was written here, which is not the order the plan asks
for.

```sh
# 1. Buck off: the palmtop runs on its battery with USB data up (risk low; charger in, battery above 30 %).
#    First the dead-man that puts the buck back. For awake measurements a monotonic timer is enough:
tools/phone-ssh 'systemd-run --unit=x-buck-restore --on-active=600 /usr/bin/i2cset -f -y 24 0x69 0xbc 0x05'
#    For sleeps, monotonic timers don't run in suspend, so use the wall clock, and have the script restore on EXIT too:
tools/phone-ssh 'systemd-run --unit=x-buck-cal --on-calendar="$(date -d "+25 min" "+%Y-%m-%d %H:%M:%S")" /usr/bin/i2cset -f -y 24 0x69 0xbc 0x05'
tools/phone-ssh 'i2cset -f -y 24 0x69 0xbc 0x00; sleep 3; i2cget -f -y 24 0x69 0xbc; cat /sys/class/power_supply/max77779-battery/current_now'
#    Expect: 0x00, current_now negative (discharging, about -350 mA screen off). Stop: current_now stays positive
#    (the buck is still on: don't measure), or the dead-man refuses to arm. Rollback: the write of 0x05 below.
# 2. Measure. Awake: 45 s means of current_now. Asleep: the gauge's coulomb counter across the sleep,
tools/phone-ssh 'i2cget -f -y 24 0x36 0x4d w'     # QH, 2.5 mAh per count; mA = counts * 2.5 * 3600 / seconds
#    (checked 2026-10-29: 3 counts in 60 s at a 357 mA mean of current_now; one count is 37 mA over 240 s).
#    The sleep itself: rtcwake -m no -s 240; systemctl suspend. Never rtcwake -m freeze (the result above).
# 3. Buck back on, then the read-back:
tools/phone-ssh 'i2cset -f -y 24 0x69 0xbc 0x05; systemctl stop x-buck-restore.timer x-buck-cal.timer 2>/dev/null; sleep 3; i2cget -f -y 24 0x69 0xbc; cat /sys/class/power_supply/max77779-battery/status'
#    Expect: 0x05 and current_now positive again (status reads Unknown on this driver). Stop: 0x05 doesn't read
#    back: write it again; if it still doesn't, replug the charger (the chip's power-on default is 0x05).
```

Next: S2 (the four rails), and a cable-out `power-ab` run with the module
loaded to put a cable-out number on the MIF saving.

**S2. Rails (risk low).** As S1 with the three GNSS rails and `udfps-3v3`
not always-on: the running DTB with `regulator-always-on` removed from
LDO9S-11S and LDO15S, nothing else (the S2 commit above). Not in or around
a G3 (GNSS) session: GNSS is off for this boot.

S2 turns LDO15S off on purpose, for this one boot, although
FINGERPRINT-PLAN's Risks table says our S2MPG15 description must not
switch it off as unused: the sensor is unpowered for the boot, and that
is the point of the measurement. FINGERPRINT-PLAN's Risks table names this exception. Steps:

1. **Before (read-only).** On the running DTB, 60 s or more after boot,
   save `/sys/kernel/debug/regulator/regulator_summary` to
   `logs/tegu-sleep-s2/summary-before.txt`.
2. **The image.** Build the images from the S2 commit. `bin/omamobile
   push` writes every image in `BOOT_IMAGES`; check first that only
   `vendor_kernel_boot.img` differs from the running set (sha256 of each
   image against the running kit), so the push changes the DTB and
   nothing else. Stop if any other image differs.
3. **Push and boot.** Precondition, before the push: the fingerprint
   stack stays stopped in that boot. `omamobile-fp.service` and anything
   that starts the trusted app or `storageproxyd` (the `omamobile-fp-stage`
   transient unit, `omamobile-fp-chroot start …` by hand, fprintd) are
   disabled or masked before the push and put back after the rollback.
   An enrolled template lives in Trusty, and nothing in Trusty should
   meet a sensor with no power. Check
   after the boot: `systemctl list-units 'omamobile-fp*'` empty, no
   `storageproxyd` process. Don't start the modem in this boot: the
   S5300's GNSS supplies are off. Nothing on the palmtop starts the modem
   at boot (it is started by hand with `omamobile-tegu-modem-up`,
   MODEM-PLAN), so there is nothing to mask; just don't run it.
4. **After (read-only).** 60 s or more after boot, save the summary again
   and diff it against the before file. Expect: LDO9S, LDO10S, LDO11S and
   LDO15S read disabled, and nothing else changed. All four are off at
   hand-off and without `regulator-always-on` nothing turns them on, so
   they read disabled whether or not the regulator core's 30 s unused-rail
   cleanup has run (which matters if the S2MPG15 regulators ever register
   after it). Stop if anything other than those four changed: push the
   running DTB's image back before any suspend.
5. **Measure.** S1's cycles. Expect S1 minus the four rails' share.

Rollback: push the running DTB's image back (the before/after check of
step 2 in reverse).

## Not known yet

- What the GNSS and fingerprint rails cost in sleep (S2).
- What MIF in sleep saves with the cable out (S1).
