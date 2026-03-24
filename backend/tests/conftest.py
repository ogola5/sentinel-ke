"""
Pytest configuration for Sentinel-KE backend tests.

Marks and fixtures used across the test suite.

Integration tests (require live DB / Kafka):
    @pytest.mark.integration
Slow tests (> 5s):
    @pytest.mark.slow

CI runs with -m 'not integration and not slow' so only fast unit tests execute.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires live DB/Kafka or external runtime state")
    config.addinivalue_line("markers", "slow: execution expected to take more than a few seconds")


def pytest_collection_modifyitems(items):
    """Auto-mark any test that imports DB/Kafka infra as integration."""
    db_indicators = {"SessionLocal", "create_engine", "KafkaConsumer", "DATABASE_URL"}
    for item in items:
        module = item.module
        source = getattr(module, "__file__", "") or ""
        # Mark real_data_pipeline tests as integration (they hit live APIs)
        if "real_data_pipeline" in source:
            item.add_marker(pytest.mark.integration)
