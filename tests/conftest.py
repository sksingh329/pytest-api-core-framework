"""
conftest.py for the package's own self-tests.
Demonstrates how consuming projects use the framework.
"""
import pytest

# pytester runs throwaway pytest sessions — used to test the HTML reporter end to end.
pytest_plugins = ["pytester"]

# All fixtures (api_config, api_client, …) are auto-registered by
# the pytest-api-core entry-point — no imports needed here.
