# Code Guide

Read the plain-language comments at the start of each section.

| File | Purpose |
|---|---|
| __init__.py | Entry setup, shared runtime, background scheduling, services and cleanup. |
| connection.py | One reconnecting TCP reader and paced command queue; actions are never retried. |
| eiscp.py | Packet encoding and routing through the shared connection. |
| choices.py | Common input/mode/service catalogs and saved visibility preferences. |
| select.py | Confirmed receiver selectors; all options remain available to automations. |
| frontend/choice-card.js | Dashboard dropdowns and checkbox menus; visibility writes only HA options. |
| config_flow.py | Setup, migration settings copy, Configure checkbox lists and custom labels/YAML. |
| receiver_data.py | Metadata decoding, zone commands and mode names. |
| listening_modes.json | Mode codes confirmed on the HT-R997's Network input. |
| button.py | Remote commands, Quick Menu, mode group buttons and Shuffle. |
| media_player.py | Power, source, normalized volume and mode controls for supported zones. |
| number.py | Decimal-minute timer and whole-dB temporary speaker levels. |
| sensor.py | Cached state and query diagnostics; no separate built-in sensor polling. |
| switch.py | Two refresh settings, custom switches and supported channel-mute controls. |
| sync.py | Decode replies/push events, publish changed states and serialize refresh batches. |
| extended.py | Signal-information and signed speaker-level conversion. |

Example: Input Selection maps a label to SLI plus its hexadecimal code. The
shared connection sends it once; SLI push/readback updates the cache, and the
select entity then shows the receiver-confirmed label. A visibility checkbox
instead changes saved options and publishes attributes without sending SLI.
