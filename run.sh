#!/usr/bin/with-contenv bashio

# Configure logging
export LOG_LEVEL="$(bashio::config 'log_level' || echo 'info')"
export DIRECT_ACCESS_MODE="$(bashio::config 'direct_access_mode' || echo 'disabled')"
export ENABLE_DISABLED_ENTITIES="$(bashio::config 'enable_disabled_entities' || echo 'false')"
export ENABLE_Z2M_BRIDGE="$(bashio::config 'enable_z2m_bridge' || echo 'true')"
export Z2M_BASE_TOPIC="$(bashio::config 'z2m_base_topic' || echo 'zigbee2mqtt')"

bashio::log.info "Starting Entity Manager..."

# Set environment variables
export HA_URL="http://supervisor/core"
export HA_TOKEN="${SUPERVISOR_TOKEN}"

bashio::log.info "Environment setup complete"
bashio::log.info "HA_URL: ${HA_URL}"
bashio::log.info "LOG_LEVEL: ${LOG_LEVEL}"
bashio::log.info "DIRECT_ACCESS_MODE: ${DIRECT_ACCESS_MODE}"
bashio::log.info "ENABLE_DISABLED_ENTITIES: ${ENABLE_DISABLED_ENTITIES}"

# Check if web_ui.py exists
if [ -f /app/web_ui.py ]; then
    bashio::log.info "Found web_ui.py at /app/web_ui.py"
else
    bashio::log.error "web_ui.py not found at /app/web_ui.py!"
    ls -la /app/
fi

# Replace the shell with Python so SIGTERM reaches the server and its exit code
# reaches Supervisor. Piping through a logging loop previously hid both.
bashio::log.info "Starting Flask application..."
cd /app
exec python3 -u web_ui.py
