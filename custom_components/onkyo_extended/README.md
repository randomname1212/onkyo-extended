# Onkyo Extended 0.2.0

The integration domain and installation folder are now `onkyo_extended`.
Friendly names use Title Case; entity unique IDs use lowercase tokens.
The receiver media player is named Main Zone; secondary players are Zone 2 etc.

## Menus and visibility

Network Services, Input Selection and Listening Modes are real select entities.
Configure → Show Options contains three multiple-choice dropdowns: Show Network
Services, Show Input Selection and Show Listening Modes. These preferences also
appear as expandable checkbox menus in the packaged dashboard card.

Visibility changes only the dashboard menus. Native entity option lists remain
complete so scripts and scenes can always select a hidden option. Visibility
does not disable a receiver feature or change the current selection.
The old per-service visibility switches are removed, reducing device entities.

Register `/onkyo_extended/choice-card.js?v=020-domain` as a JavaScript module in
Dashboard Resources. Add a `custom:onkyo-choice-card` with `entities` entries
containing `entity` (select entity ID) and `name` (the menu's friendly label).

## Remote buttons

Quick Menu sends OSDQUICK. Movie/TV, Music and Game send LMDMOVIE, LMDMUSIC and
LMDGAME, cycling the receiver's listening-mode groups just like the remote.
Shuffle sends NTCRANDOM; support depends on the active network/USB service.
The buttons do not start tracks or change receiver calibration.

## Listening modes

The default table contains modes accepted by the HT-R997 during the requested
Network-input check on 14 November 2026. Names come from IFA responses; THX
variants distinguish their Dolby/DTS upmixer. The check restored the original
mode and mute state. Some additional formats require a compatible input signal;
a command ignored during this check is not proof of incompatibility with every
possible source. Receiver Controls → Listening Modes JSON can add such modes.

## Scripts and scenes

Use `select.select_option` for Network Services, Input Selection or Listening
Modes, including options hidden on the dashboard. Combine this with
`media_player.volume_set` for Main Zone (volume_level from 0 to 1). A scene can
store select states and the media-player volume together. Hidden options remain
in native select attributes specifically to preserve scene restoration.

## Migration

Back up the previous integration and dashboard. Disable the previous custom
integration, install this folder under `/config/custom_components/`, and restart
Home Assistant. Add Onkyo Extended with the same receiver address. The setup flow
copies options/custom YAML from a disabled same-host custom Onkyo entry if it is
still present. Keep the standard Onkyo integration disabled to avoid competing
connections. After the dashboard references have been updated, the previous
custom entry/folder can be retired. Never run both custom entries together.
The dashboard itself is retained; its entity references need the new IDs.

One persistent connection paces commands at least one second apart. Periodic
fallback refreshes preserve ten-second query gaps and never overlap. Timer 0.5
is 30 seconds; 0 disables fallback polling. Startup retries missed essential
queries once, never actions. Push replies update states directly.

No general control retest was performed for this update, at the owner's request.
The new buttons and checkbox menus require normal runtime verification later.
