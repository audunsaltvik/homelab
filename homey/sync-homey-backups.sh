#!/bin/bash
set -euo pipefail

# Configuration
SYNOLOGY_USER="rsync-backup"
SYNOLOGY_HOST="nas"
SYNOLOGY_PORT="2222"
SYNOLOGY_PATH="/volume1/backups/homey"
LOCAL_PATH="/var/backups/homey"
SSH_KEY="/root/.ssh/synology_backup"
LOG_TAG="homey-backup-sync"

# Function to log to journald
log_info() {
    echo "$1"
    logger -t "${LOG_TAG}" -p user.info "$1"
}

log_error() {
    echo "$1" >&2
    logger -t "${LOG_TAG}" -p user.err "$1"
}

# Check if local backup directory exists and has files
if [ ! -d "${LOCAL_PATH}" ]; then
    log_error "ERROR: Local backup directory ${LOCAL_PATH} does not exist"
    exit 1
fi

BACKUP_COUNT=$(find "${LOCAL_PATH}" -name "homey-backup-*.tar.gz" | wc -l)
if [ "${BACKUP_COUNT}" -eq 0 ]; then
    log_error "ERROR: No backup files found in ${LOCAL_PATH}"
    exit 1
fi

log_info "Starting sync of ${BACKUP_COUNT} backup(s) to Synology"

# Create remote directory if it doesn't exist
ssh -i "${SSH_KEY}" -p ${SYNOLOGY_PORT} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
    "${SYNOLOGY_USER}@${SYNOLOGY_HOST}" "mkdir -p ${SYNOLOGY_PATH}" 2>/dev/null || {
    log_error "ERROR: Failed to create remote directory or connect to Synology"
    exit 1
}

# Perform rsync
RSYNC_OUTPUT=$(rsync -avz --delete \
    -e "ssh -i ${SSH_KEY} -p ${SYNOLOGY_PORT} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=30" \
    "${LOCAL_PATH}/" \
    "${SYNOLOGY_USER}@${SYNOLOGY_HOST}:${SYNOLOGY_PATH}/" 2>&1)

RSYNC_EXIT=$?

if [ ${RSYNC_EXIT} -eq 0 ]; then
    # Get total size of synced backups
    TOTAL_SIZE=$(du -sh "${LOCAL_PATH}" | cut -f1)
    LATEST_BACKUP=$(ls -t "${LOCAL_PATH}"/homey-backup-*.tar.gz 2>/dev/null | head -1 | xargs basename 2>/dev/null || echo "unknown")
    
    log_info "SUCCESS: Synced ${BACKUP_COUNT} backup(s) (${TOTAL_SIZE}) to ${SYNOLOGY_HOST}. Latest: ${LATEST_BACKUP}"
    exit 0
else
    log_error "ERROR: Rsync failed with exit code ${RSYNC_EXIT}"
    log_error "Rsync output: ${RSYNC_OUTPUT}"
    exit 1
fi
