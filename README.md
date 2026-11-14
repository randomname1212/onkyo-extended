# Onkyo Extended

Home Assistant custom integration for controlling Onkyo receivers over local-network eISCP. Version **0.2.0**.

> **Partially tested on one Onkyo HT-R997 only.** This is an experimental release, not a claim of complete receiver or feature compatibility. Other receiver models have not been tested.

## Receiver and firmware compatibility

The HT-R997 used during development reported firmware **1142-1020-3070-0011-0000**. Onkyo's published firmware bulletin lists the main version as **1142-1020-3070-0011**, dated **1 April 2024**.

The following receivers appear in the same Onkyo firmware update bulletin and **might be compatible** with this integration. Shared firmware is a reason to investigate compatibility, not proof: input codes, zones, volume ranges, network services and listening modes may differ.

| Receiver | Integration testing |
| --- | --- |
| HT-R997 | Partially tested |
| TX-NR575 | Not tested; potential compatibility only |
| TX-NR676 / TX-NR676E | Not tested; potential compatibility only |
| TX-NR777 | Not tested; potential compatibility only |
| TX-RZ620 | Not tested; potential compatibility only |
| TX-RZ720 | Not tested; potential compatibility only |
| TX-RZ820 | Not tested; potential compatibility only |

Sources: [Onkyo HT-R997 support](https://onkyo.com/ht-r997) and [official firmware bulletin](https://assets.onkyo-av.com/product-firmware/Firmware_Update_TX-NR575_676_777_RZ620_RZ720_RZ820_HTR997_04-01-2024_2024-04-05-013015_ggcv.pdf?v=1712280616). This repository does not distribute receiver firmware.

## Features

- Main Zone and capability-dependent secondary-zone media players, with power, input and supported volume/mute controls.
- Network Services, Input Selection and Listening Modes dropdowns.
- Configure lists and an optional dashboard card for choosing which menu options to show. Hidden options remain available to scripts and scenes.
- Quick Menu, directional/menu controls, Movie/TV, Music, Game and Shuffle buttons.
- Temporary centre and subwoofer level controls, signal information and query diagnostics.
- A persistent local TCP connection with paced commands and push state updates.
- Optional fallback polling with a decimal-minute timer: `0.5` means 30 seconds; `0` disables it.
- Custom eISCP commands and configurable mappings.

Features depend on receiver capabilities and the active source. Selecting a network service opens that service; it does not itself start a song or provide a Spotify playback backend.

## Install manually

1. Back up your Home Assistant configuration.
2. Download this repository or its version 0.2.0 archive.
3. Copy `custom_components/onkyo_extended` into `/config/custom_components/onkyo_extended` on Home Assistant. Do not nest the folder twice.
4. Disable any other integration controlling the same receiver while evaluating this one, to avoid competing connections.
5. Restart Home Assistant.
6. Open **Settings → Devices & services → Add integration → Onkyo Extended**. Enter the receiver's address and TCP port (normally `60128`). Manual IP entry can be used when discovery does not cross a VM/network boundary.

Development used Home Assistant Core 2026.11.1; earlier versions have not been verified. This is a custom integration and is not part of Home Assistant Core.

### Upgrading from onkyo_extended_functions

The folder and integration domain changed to `onkyo_extended` in 0.2.0. Back up the old integration and dashboard, disable the old entry, install the new folder, restart and add Onkyo Extended. Setup can copy settings from a disabled same-host custom Onkyo entry. Entity IDs may change: update scripts, scenes, automations and dashboard references before removing the old entry. Keep your dashboard; replace its entity references. Do not run both custom entries against the same receiver.

## Optional dashboard menus

Add `/onkyo_extended/choice-card.js?v=020-domain` as a **JavaScript module** in dashboard resources. See [the example card](examples/dashboard-card.yaml), replacing its placeholder entity IDs with those from your installation.

The three **Show…** checkbox lists are also available in the integration's Configure options. Visibility preferences filter the custom dashboard menus, not native select options, so hidden choices remain usable in scripts and scenes.

For automation, use `select.select_option` on the relevant select entity. Combine this with `media_player.volume_set` for a zone; its `volume_level` is normalized from `0` to `1`.

## Testing status and known limitations

- **Only partially tested on the HT-R997. No other receiver has been tested.**
- Installation, entity registration and dashboard rendering were observed. Twenty-three listening-mode codes were accepted on the HT-R997's Network input. Acceptance on that input does not verify every audio format or speaker layout.
- Version 0.2.0 did not receive a complete control regression test. Quick Menu, listening-mode category buttons, Shuffle and all visibility/scene combinations still require broader runtime verification.
- The default mappings are based on the HT-R997. Ignored commands may require a different input signal or may be unsupported on a particular model.
- Native Spotify Connect could select the receiver and display artwork during troubleshooting but did not start audio playback. Other network services worked; the owner reported Spotify playback through Chromecast working. The underlying Spotify Connect cause remains unresolved. No Spotify script or guaranteed Chromecast playback solution is included.
- A successful command, reported playback state or artwork display is not proof of audible playback.

No additional receiver commands were sent while preparing this repository. Please include receiver model, firmware, Home Assistant version, input/audio format and relevant redacted logs when reporting a problem.

## Code and acknowledgements

See [the code guide](custom_components/onkyo_extended/CODE_GUIDE.md) and [integration notes](custom_components/onkyo_extended/README.md).

Protocol references include [miracle2k/onkyo-eiscp](https://github.com/miracle2k/onkyo-eiscp) and [arturpragacz/aioonkyo](https://github.com/arturpragacz/aioonkyo). The integration uses its bundled TCP implementation, rather than requiring those command-line packages at runtime. Icon attribution is retained in [brand/LICENSE.txt](custom_components/onkyo_extended/brand/LICENSE.txt).
