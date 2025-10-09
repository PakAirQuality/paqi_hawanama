#!/bin/bash

# Hawanama Schema Enforcement Script
# Ensures critical schema elements are present
# Prevents schema reversion and data loss

set -e  # Exit on any error

# Configuration
PROJECT_DIR="/Users/rehanahmad/Desktop/Geo-analysis/hawanama-main"
CONTAINER_NAME="hawanama-main-postgres-1"
DB_USER="hawanama"
DB_NAME="hawanama"
MIGRATION_FILE="infra/migrations/001_apscheduler_schema.sql"

echo "🛡️  Hawanama Schema Protection System"
echo "====================================="
echo "Ensuring critical schema elements are present..."
echo ""

# Check if container is running
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "❌ Error: PostgreSQL container '$CONTAINER_NAME' is not running"
    echo "   Please start the container with: docker-compose up -d postgres"
    exit 1
fi

# Function to check schema elements
check_schema_element() {
    local element_name="$1"
    local check_sql="$2"
    local description="$3"
    
    if docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -t -c "$check_sql" | grep -q "t"; then
        echo "✅ $element_name: Present"
        return 0
    else
        echo "❌ $element_name: MISSING"
        echo "   $description"
        return 1
    fi
}

echo "🔍 Checking current schema state..."
echo ""

# Initialize status tracking
missing_elements=0

# Check 1: discovery_progress table
if ! check_schema_element \
    "discovery_progress table" \
    "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'discovery_progress');" \
    "Required for APScheduler station discovery operations"; then
    ((missing_elements++))
fi

# Check 2: Weather columns in readings_minute
weather_count=$(docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -t -c "
    SELECT COUNT(*) FROM information_schema.columns 
    WHERE table_name = 'readings_minute' 
    AND column_name IN ('pressure', 'wind_speed', 'wind_direction', 'weather_icon', 'heat_index');
" | xargs)

if [ "$weather_count" -eq 5 ]; then
    echo "✅ Weather columns (readings_minute): Present (5/5)"
else
    echo "❌ Weather columns (readings_minute): MISSING ($weather_count/5)"
    echo "   Required for complete meteorological data storage"
    ((missing_elements++))
fi

# Check 3: Weather columns in readings_hour
weather_count_hour=$(docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -t -c "
    SELECT COUNT(*) FROM information_schema.columns 
    WHERE table_name = 'readings_hour' 
    AND column_name IN ('pressure', 'wind_speed', 'wind_direction', 'weather_icon', 'heat_index');
" | xargs)

if [ "$weather_count_hour" -eq 5 ]; then
    echo "✅ Weather columns (readings_hour): Present (5/5)"
else
    echo "❌ Weather columns (readings_hour): MISSING ($weather_count_hour/5)"
    echo "   Required for complete meteorological data storage"
    ((missing_elements++))
fi

# Check 4: Station unique constraint
if ! check_schema_element \
    "Station unique constraint" \
    "SELECT EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'stations_source_external_unique');" \
    "Required to prevent duplicate station creation"; then
    ((missing_elements++))
fi

echo ""

# Report status
if [ "$missing_elements" -eq 0 ]; then
    echo "🎉 Schema integrity verified - all critical elements present!"
    echo ""
    echo "✅ System status: Ready for operation"
    echo "✅ APScheduler: Can safely run station discovery"
    echo "✅ Data collection: Weather data will be stored correctly"
    echo "✅ Station management: No duplicate creation risk"
    echo ""
    exit 0
else
    echo "⚠️  Schema integrity compromised - $missing_elements critical element(s) missing!"
    echo ""
    echo "🚨 IMPACT:"
    echo "   - APScheduler station discovery may fail"
    echo "   - Weather data collection will be incomplete"
    echo "   - Risk of duplicate station creation"
    echo "   - Potential system instability"
    echo ""
    
    # Offer to fix the schema
    read -p "🔧 Would you like to automatically fix the schema? [Y/n]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        echo ""
        echo "🔧 Applying schema migration to fix missing elements..."
        
        # Apply the migration
        if [ -f "$PROJECT_DIR/$MIGRATION_FILE" ]; then
            docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" < "$PROJECT_DIR/$MIGRATION_FILE"
            
            if [ $? -eq 0 ]; then
                echo ""
                echo "✅ Schema migration applied successfully!"
                echo ""
                echo "🔄 Re-checking schema integrity..."
                echo ""
                
                # Re-run this script to verify the fix
                exec "$0"
            else
                echo ""
                echo "❌ Schema migration failed!"
                echo "   Please check the migration file and database logs"
                exit 1
            fi
        else
            echo "❌ Migration file not found: $MIGRATION_FILE"
            echo "   Please ensure you're running this script from the project root"
            exit 1
        fi
    else
        echo ""
        echo "⚠️  Schema issues not resolved - system may not function correctly"
        echo ""
        echo "📝 Manual fix options:"
        echo "   1. Run migration manually:"
        echo "      docker exec -i $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME < $MIGRATION_FILE"
        echo ""
        echo "   2. Restore from backup:"
        echo "      ./scripts/restore_database.sh"
        echo ""
        exit 1
    fi
fi