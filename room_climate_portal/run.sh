#!/usr/bin/with-contenv bashio
# SUPERVISOR_TOKEN is provided by the Supervisor (homeassistant_api: true).
bashio::log.info "Starting Room Climate Portal"
cd /app
exec python3 -m portal
