# Shared option names and defaults live here so the UI and scheduler agree.
CONF_EXTENDED_REFRESH = "include_extended_information"

DOMAIN = "onkyo_extended"
PLATFORMS = ["select", "button", "switch", "sensor", "number", "media_player"]
CONF_HOST = "host"
CONF_PORT = "port"
CONF_DELAY = "service_delay"
CONF_VERIFY = "verify_service"
CONF_CUSTOM_YAML = "custom_commands_yaml"
CONF_SHOW_HIDDEN = "show_hidden_services"
CONF_VISIBLE_SERVICES = "visible_network_services"
CONF_SYNC_INTERVAL = "sync_interval"  # seconds, legacy v0.1.3 option
CONF_UPDATE_AFTER_INPUT = "update_values_after_input"
CONF_UPDATE_PERIOD_MINUTES = "update_values_periodic_timer"
DEFAULT_PORT = 60128
DEFAULT_DELAY = 2.0
DEFAULT_UPDATE_PERIOD_MINUTES = 1
QUERY_GAP_SECONDS = 10

# Main-zone selector IDs reported by this HT-R997 via NRIQSTN.
# The receiver also reports 80 (Source), but only for Zone 2.
INPUT_BY_ID = {
    "10": "Blu-ray/DVD", "01": "Cable/Satellite", "02": "Game",
    "11": "Streaming Box", "05": "PC", "03": "AUX",
    "25": "AM", "24": "FM", "23": "CD", "12": "TV",
    "22": "Phono", "2B": "Network", "2E": "Bluetooth",
}

SERVICES = {
    "TuneIn": "NSV0E0", "Pandora": "NSV040", "Spotify": "NSV0A0",
    "Deezer": "NSV120", "TIDAL": "NSV1B0", "Amazon Music": "NSV1C0",
    "FlareConnect": "NSV430", "Chromecast built-in": "NSV400",
    "DTS Play-Fi": "NSV420", "AirPlay": "NSV180",
    "Music Server": "NSV000", "Play Queue": "NSV1D0", "USB": "NSVF00",
}
HIDDEN_BY_DEFAULT = {
    "Pandora", "Deezer", "TIDAL", "Amazon Music", "FlareConnect", "DTS Play-Fi"
}
