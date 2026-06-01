"""
Settings for pytest-api-core-framework's own integration tests.
Consumer projects should create their own settings.py with their own environments.
"""
from __future__ import annotations

import os

from pytest_api_core.config.base_settings import BaseSettings


class DevSettings(BaseSettings):
    base_url = "https://jsonplaceholder.typicode.com"
    timeout = 30
    verify_ssl = True
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


class StagingSettings(DevSettings):
    base_url = os.environ.get("API_BASE_URL", "https://jsonplaceholder.typicode.com")
    timeout = 60


ENVIRONMENTS = {
    "dev": DevSettings,
    "staging": StagingSettings,
}
