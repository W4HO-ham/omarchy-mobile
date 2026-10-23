<!-- SPDX-License-Identifier: MIT -->
# mesa (Omarchy Mobile build)

Arch Linux's Mesa 26.2.4 package, rebuilt for the Pixel 7 Pro and the
Pixel 6 and 6 Pro, with additional Pixel 9a Mali-G715 support. Mali-G710 (gs201) and Mali-G78 (gs101, with upstream's G68
next to it) are added to Panfrost's model table. Without an entry, Mesa
rejects the GPU (for the G710 even when Panthor is loaded): the Gallium
driver bails out on an unknown model, and PanVK returns
`VK_ERROR_INCOMPATIBLE_DRIVER`. See `device/cheetah/GPU-PLAN.md`, section 4.

| File | What it is |
| --- | --- |
| `PKGBUILD` | Arch's `mesa` PKGBUILD at tag `1-26.2.4-1`, trimmed for this phone (see its header) |
| `0001-panfrost-add-Mali-G710-to-the-model-table.patch` | The G710 entry, in `git format-patch` form |
| `0002-panfrost-don-t-make-image-BOs-private-on-panthor.patch` | Image BOs are always shareable: panthor can't export a BO private to one GPU VM, and GTK 4 exports GL textures made without `PIPE_BIND_SHARED` (GNOME Snapshot crashed after photos with "drmPrimeHandleToFD() failed (err=22)") |
| `0003-panfrost-Advertise-Mali-G68-support.patch` | Upstream's G68 entry (93d2c51f, Markuss Broks), backported to 26.2.4 |
| `0004-panfrost-add-Mali-G78-to-the-model-table.patch` | The G78 entry (Valhall v9), with the G68's tile-buffer sizes and rates and the G78 counter layout. Gallium only: PanVK still refuses the G78 |
| `0005-*` | Upstream G715 model entry, variant 4; the model entry alone is insufficient |
| `0006-*` through `0009-*` | Upstream architecture 11 XML, shared build, Gallium and PanVK support |
| `0010-*` | Upstream CSF NOP payload/type prerequisite |
| `UPSTREAM.md` | Merge request text for upstream Mesa |
| `.SRCINFO` | `makepkg --printsrcinfo` output |

## What differs from Arch Linux ARM's `mesa`

- The patches above.
- `arch=(aarch64)`.
- Only drivers this phone can use:
  - Gallium `panfrost` (which brings `kmsro`), `llvmpipe`, `softpipe` and `zink`.
  - Vulkan `panfrost` (PanVK).
  - The `device-select` and `anti-lag` layers.
- Only three split packages: `mesa`, `vulkan-panfrost` and
  `vulkan-mesa-implicit-layers` (which `vulkan-panfrost` depends on).
- `pkgrel=1.4`. makepkg only accepts `integer[.integer]`, so the Omarchy Mobile
  marker is in Mesa's version string instead: `26.2.4-arch1.1.4.omamobile4`.
  That string shows up in `GL_VERSION` and in the `libgallium-*.so` file name.

The other ALARM split packages (`vulkan-swrast`, `opencl-mesa` and so on)
don't depend on `mesa`'s exact version. They can stay installed at
`1:26.2.4-1`.

## Status

The earlier G715 backport package built natively on ARM64 with verified
source checksums/signature and zero-fuzz patch application. G715 GLES 3.1
offscreen pixel readback and the accelerated Omarchy desktop passed on
the private Pixel 9a kernel. This does not qualify Vulkan conformance,
suspend, DVFS or a public source-built tegu kernel.

This candidate preserves main's existing G68/G78 patches byte-for-byte
and adds the six G715 backports. All ten patches apply with zero fuzz to
the checksummed 26.2.4 source; SHA256 and BLAKE2 checksums, generated metadata
and shell syntax pass. The combined series builds all three packages natively in the ARM64
build container, with the upstream source signature verified. The build
uses a bounded eight-job compiler setting. Existing hardware results used
the earlier G715 package, not this exact combined series; the new packages
have not been installed or runtime-tested on a phone.

The architecture 11 support is backported from upstream Mesa
[MR 41803](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/41803),
with original authorship and review trailers retained. The PanVK backport
adjusts one context-only CSF filename for 26.2.4. The regular G715 model
entry is taken from upstream commit
[73210bf6](https://gitlab.freedesktop.org/mesa/mesa/-/commit/73210bf69dfa4cfb5d5c5b3b7c6c91a05209e2b6).
Keep the original project licenses. Drop backports when a packaged release
contains them; do not mistake a model string for working architecture support.

## Building on the phone

As a normal user in the Arch root, with internet:

```sh
sudo pacman -S --needed base-devel
gpg --recv-keys 57551DE15B968F6341C248F68D8E31AFC32428A6   # Eric Engestrom, signed 26.2.4
cd packages/mesa
makepkg -s                       # pulls the makedepends listed in the PKGBUILD
sudo pacman -U mesa-1:26.2.4-1.4-aarch64.pkg.tar.zst \
  vulkan-panfrost-1:26.2.4-1.4-aarch64.pkg.tar.zst \
  vulkan-mesa-implicit-layers-1:26.2.4-1.4-aarch64.pkg.tar.zst
```

Until Panthor exposes `/dev/dri/renderD128`, nothing changes visibly:
`kmsro` finds no render node and Mesa keeps using `kms_swrast`.

To stop `pacman -Syu` from replacing the build with ALARM's `mesa`, add this
line to `/etc/pacman.conf`:

```
IgnorePkg = mesa vulkan-panfrost vulkan-mesa-implicit-layers
```

Alternatively, publish the build in Omarchy Mobile's own repo listed ahead of
`[extra]`. Rebase on each new ALARM Mesa release:

1. Take the new Arch tag.
2. Re-apply the trimming.
3. Check that the patch still applies.

Drop the G710 and G78 patches once upstream Mesa ships their entries, and
the G68 backport (0003) once a Mesa release carries it.

On the Pixel 6 Pro (raven) the G78 patch runs GLES 3.1 with Hyprland on
top. It needs the kernel's AArch64 page-table quirk for gs101 in
Panfrost, or every fragment job faults.
