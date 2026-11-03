<!-- SPDX-License-Identifier: MIT -->
# mmsd-tng

An opt-in, per-user MMS daemon using ModemManager's D-Bus API. It never
starts the modem or sitd. This package alone does not enable picture
messages in Messages: omatel-agent and omamessages need their T3 changes
in their own repositories. See `docs/TELEPHONY-APPS-PLAN.md` section 1.7b.

The AUR has `mmsd-tng-git`, advertising 2.5.0.r0.g6529119-1 in its cached
package metadata while building upstream HEAD. Neither Arch's exact-name
search nor Arch Linux ARM's aarch64 core/extra indexes contained mmsd-tng
when checked on 2026-11-03. This recipe uses upstream's stable 2.6.4 tag
and the AUR runtime dependency set, with a checked source checksum and a
single Meson build directory. Modern libphonenumber headers additionally
need explicit protobuf and Abseil linkage.

Sources: [AUR recipe](https://aur.archlinux.org/cgit/aur.git/tree/PKGBUILD?h=mmsd-tng-git),
[upstream 2.6.4](https://gitlab.com/kop316/mmsd/-/tree/2.6.4),
[Arch Linux ARM package indexes](https://de3.mirror.archlinuxarm.org/aarch64/extra/).
Upstream is GPL-2.0; its LGPL components retain their notices. Patches use
the corresponding upstream file's license.

The patches apply the configured own number when MM's OwnNumbers array is
empty, including E.164 parsing without an IMSI-derived region; close HTTP sockets on interface-binding failure; prefer a dedicated
MMS bearer when its APN matches the internet APN; and link the dependencies
required by current libphonenumber. With a dedicated profile present,
there is no fallback to the internet bearer while MMS is disconnected.

Owner configuration, before the first start (private files, mode 0600):

* `/etc/omamobile/modem-sit.conf`: `[mms] apn = <APN>`, `ip_type = ipv4`.
  This enables only the profile. It does not connect on boot.
* Copy `/usr/share/mmsd-tng/mms.example` to
  `~/.mms/modemmanager/mms` and replace `<MMSC>`, `<APN>` and `<OWN_NUMBER>`.
  Keep `ForceCAres=true` so DNS uses the MMS bearer. Set the MMS proxy to
  the carrier's `host:port`, or `NULL` when no proxy is required.

Use the same session user as omatel-agent. Prepare the configured MMS
bearer through MM's `Bearer.Connect` before starting `mmsd-tng.service`.
Upstream discovers connected bearers; it does not connect one itself.
After preparing a bearer while the daemon is running, call
`org.ofono.mms.ModemManager.ProcessMessageQueue` on session-bus object
`/org/ofono/mms`. The agent integration must manage this lifecycle.

No unit is enabled or D-Bus activated by this package. No carrier settings
are shipped. Do not enable upstream debug logging on the phone: it can
print numbers, message URLs, settings and message content. Never publish
its journal, settings, message store, WAP bytes or attachments.

The first host route supports IPv4 (including an IPv4v6 PDP with IPv4
address and DNS). It configures only rmnet2, table 625 and an output-device
rule at priority 1625; normal Wi-Fi/internet routes and DNS are untouched.
IPv6-only MMS, MTU selection, modem suspend and carrier acceptance need
attended qualification. Do not restart sitd on the running 9a CP to apply
configuration: use a separately approved fresh-boot session.
