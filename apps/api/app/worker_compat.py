"""
Compatibility layer for worker modules in API container.
This module provides the import paths that worker tasks expect.
"""

# Re-export worker config and services with the paths worker tasks expect
import sys
import os
from pathlib import Path

# Add the app directory to Python path so worker modules can find dependencies
app_dir = Path(__file__).parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

# Create module aliases that worker tasks expect
try:
    # Worker tasks expect 'config.settings' but it's at 'app.worker_config.settings'
    import app.worker_config.settings as config_settings_module
    sys.modules['config'] = sys.modules.get('config', type(sys)('config'))
    sys.modules['config'].settings = config_settings_module.settings
    sys.modules['config.settings'] = config_settings_module
    
    # Worker tasks expect 'services.iqair_client' - import from the new location
    import app.services.ingestion.iqair_service as iqair_client_module
    sys.modules['services'] = sys.modules.get('services', type(sys)('services'))
    sys.modules['services'].iqair_client = iqair_client_module
    sys.modules['services.iqair_client'] = iqair_client_module
    
    # Worker tasks expect 'services.database' - use worker_services version
    import app.worker_services.database as database_module
    sys.modules['services'].database = database_module
    sys.modules['services.database'] = database_module
    
    # Add manifest_utils to the module path
    import app.manifest_utils as manifest_utils_module
    sys.modules['manifest_utils'] = manifest_utils_module
    
    print("Worker compatibility imports configured successfully")
    
except ImportError as e:
    print(f"Warning: Could not set up worker compatibility imports: {e}")
    import traceback
    print(f"Traceback: {traceback.format_exc()}")