#!/bin/bash

APP_NAME="core"

# Create main test directory
mkdir -p $APP_NAME/tests/{integration,functional,performance}

# Create test files
touch $APP_NAME/tests/__init__.py
touch $APP_NAME/tests/test_{models,views,forms,urls,api,utils}.py

# Create integration test files
touch $APP_NAME/tests/integration/__init__.py
touch $APP_NAME/tests/integration/test_{view_model_integration,api_database_integration}.py

# Create functional test file
touch $APP_NAME/tests/functional/__init__.py
touch $APP_NAME/tests/functional/test_user_workflow.py

# Create performance test file
touch $APP_NAME/tests/performance/__init__.py
touch $APP_NAME/tests/performance/test_query_performance.py

# Create factories file
touch $APP_NAME/factories.py

# Create fixtures directory and file
mkdir -p $APP_NAME/fixtures
touch $APP_NAME/fixtures/test_data.json

echo "Test directory structure created successfully!"
