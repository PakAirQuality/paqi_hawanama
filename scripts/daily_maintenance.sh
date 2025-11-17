#!/bin/bash

# Hawanama Daily Maintenance Script
# Comprehensive system health check and maintenance
# Ensures data integrity and prevents schema drift

set -e  # Exit on any error

# Configuration
PROJECT_DIR="/Users/rehanahmad/Desktop/Geo-analysis/hawanama-main"
LOG_DIR="$PROJECT_DIR/logs"
BACKUP_DIR="$PROJECT_DIR/backups"

# Create directories
mkdir -p "$LOG_DIR"

# Log file
LOG_FILE="$LOG_DIR/daily_maintenance_$(date +%Y%m%d).log"

# Function to log with timestamp
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log "🚀 Starting Daily Maintenance for Hawanama System"
log "=================================================="

# 1. Schema Integrity Check
log "🔍 Step 1: Checking schema integrity..."
if ./scripts/ensure_schema.sh >> "$LOG_FILE" 2>&1; then
    log "✅ Schema integrity: PASSED"
else
    log "❌ Schema integrity: FAILED - Critical issue detected!"
    log "🚨 Manual intervention required - check $LOG_FILE for details"
    exit 1
fi

# 2. Database Backup
log "💾 Step 2: Creating database backup..."
if ./scripts/backup_database.sh >> "$LOG_FILE" 2>&1; then
    log "✅ Database backup: COMPLETED"
    
    # Count backup files
    BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*_backup_*.sql 2>/dev/null | wc -l)
    log "📊 Total backup files: $BACKUP_COUNT"
else
    log "❌ Database backup: FAILED"
    # Don't exit - continue with other maintenance
fi

# 3. System Health Check
log "❤️  Step 3: Checking system health..."

# Check if APScheduler is running
if docker ps | grep -q "hawanama-main-apscheduler-1"; then
    log "✅ APScheduler: Running"
    
    # Check recent logs for errors
    ERROR_COUNT=$(docker logs hawanama-main-apscheduler-1 --since 24h 2>&1 | grep -i error | wc -l)
    if [ "$ERROR_COUNT" -gt 5 ]; then
        log "⚠️  APScheduler: $ERROR_COUNT errors in last 24h (review recommended)"
    else
        log "✅ APScheduler: Low error rate ($ERROR_COUNT errors in 24h)"
    fi
else
    log "❌ APScheduler: NOT RUNNING"
fi

# Check database connectivity
if docker exec hawanama-main-postgres-1 psql -U hawanama -d hawanama -c "SELECT 1;" > /dev/null 2>&1; then
    log "✅ Database: Connected"
else
    log "❌ Database: Connection failed"
fi

# 4. Data Collection Verification
log "📊 Step 4: Verifying data collection..."

# Check station count
STATION_COUNT=$(docker exec hawanama-main-postgres-1 psql -U hawanama -d hawanama -t -c "SELECT COUNT(*) FROM stations;" 2>/dev/null | xargs)
log "🏢 Total stations: $STATION_COUNT"

# Check recent readings
RECENT_READINGS=$(docker exec hawanama-main-postgres-1 psql -U hawanama -d hawanama -t -c "SELECT COUNT(*) FROM readings_minute WHERE ts >= NOW() - INTERVAL '1 hour';" 2>/dev/null | xargs)
log "📈 Recent readings (1h): $RECENT_READINGS"

# Check readings with weather data
WEATHER_READINGS=$(docker exec hawanama-main-postgres-1 psql -U hawanama -d hawanama -t -c "SELECT COUNT(*) FROM readings_minute WHERE pressure IS NOT NULL AND ts >= NOW() - INTERVAL '24 hours';" 2>/dev/null | xargs)
log "🌤️  Weather readings (24h): $WEATHER_READINGS"

# Data collection health assessment
if [ "$RECENT_READINGS" -gt 50 ] && [ "$WEATHER_READINGS" -gt 100 ]; then
    log "✅ Data collection: HEALTHY"
elif [ "$RECENT_READINGS" -gt 10 ]; then
    log "⚠️  Data collection: DEGRADED (low volume)"
else
    log "❌ Data collection: CRITICAL (very low/no data)"
fi

# 5. Disk Space Check
log "💾 Step 5: Checking disk space..."

# Check available disk space (warning if < 10GB)
AVAILABLE_GB=$(df -BG "$PROJECT_DIR" | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$AVAILABLE_GB" -gt 10 ]; then
    log "✅ Disk space: ${AVAILABLE_GB}GB available"
else
    log "⚠️  Disk space: LOW (${AVAILABLE_GB}GB available)"
fi

# Check backup directory size
BACKUP_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1 || echo "0")
log "📦 Backup directory size: $BACKUP_SIZE"

# 6. Performance Metrics
log "⚡ Step 6: Performance metrics..."

# Database size
DB_SIZE=$(docker exec hawanama-main-postgres-1 psql -U hawanama -d hawanama -t -c "SELECT pg_size_pretty(pg_database_size('hawanama'));" 2>/dev/null | xargs)
log "🗄️  Database size: $DB_SIZE"

# Largest tables
log "📋 Largest tables:"
docker exec hawanama-main-postgres-1 psql -U hawanama -d hawanama -t -c "
SELECT 
    schemaname||'.'||tablename as table,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC 
LIMIT 5;
" 2>/dev/null | while IFS='|' read -r table size; do
    log "   $(echo $table | xargs): $(echo $size | xargs)"
done

# 7. Generate Summary Report
log "📋 Step 7: Generating summary report..."

# Overall health score calculation
HEALTH_CHECKS=0
PASSED_CHECKS=0

# Schema integrity (mandatory)
HEALTH_CHECKS=$((HEALTH_CHECKS + 1))
if grep -q "Schema integrity: PASSED" "$LOG_FILE"; then
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
fi

# APScheduler status
HEALTH_CHECKS=$((HEALTH_CHECKS + 1))
if grep -q "APScheduler: Running" "$LOG_FILE"; then
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
fi

# Database connection
HEALTH_CHECKS=$((HEALTH_CHECKS + 1))
if grep -q "Database: Connected" "$LOG_FILE"; then
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
fi

# Data collection health
HEALTH_CHECKS=$((HEALTH_CHECKS + 1))
if grep -q "Data collection: HEALTHY" "$LOG_FILE"; then
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
elif grep -q "Data collection: DEGRADED" "$LOG_FILE"; then
    PASSED_CHECKS=$((PASSED_CHECKS + 1))  # Degraded still counts as partial pass
fi

HEALTH_PERCENTAGE=$(( (PASSED_CHECKS * 100) / HEALTH_CHECKS ))

log ""
log "🎯 MAINTENANCE SUMMARY"
log "====================="
log "Overall health: $HEALTH_PERCENTAGE% ($PASSED_CHECKS/$HEALTH_CHECKS checks passed)"
log "Stations: $STATION_COUNT"
log "Recent readings: $RECENT_READINGS/hour"
log "Database size: $DB_SIZE"
log "Available disk: ${AVAILABLE_GB}GB"
log "Backup files: $BACKUP_COUNT"

if [ "$HEALTH_PERCENTAGE" -ge 75 ]; then
    log "✅ System status: HEALTHY"
elif [ "$HEALTH_PERCENTAGE" -ge 50 ]; then
    log "⚠️  System status: DEGRADED (monitoring recommended)"
else
    log "❌ System status: CRITICAL (immediate attention required)"
fi

log ""
log "🏁 Daily maintenance completed at $(date)"
log "📁 Full log available at: $LOG_FILE"
log "=================================================="

# Exit with appropriate code
if [ "$HEALTH_PERCENTAGE" -ge 50 ]; then
    exit 0  # Success
else
    exit 1  # Critical issues found
fi