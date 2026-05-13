import pytest

from tautulli_exporter.config import Config, ConfigError


def test_from_env_minimal():
    cfg = Config.from_env({
        "TAUTULLI_URL": "http://tautulli:8181/",
        "TAUTULLI_API_KEY": "abc123",
    })
    assert cfg.tautulli_url == "http://tautulli:8181"  # trailing slash stripped
    assert cfg.api_key == "abc123"
    assert cfg.exporter_port == 9487
    assert cfg.activity_poll_interval == 10
    assert cfg.inventory_poll_interval == 300
    assert cfg.meta_poll_interval == 1800
    assert cfg.log_level == "INFO"
    assert cfg.geoip_enabled is True
    assert cfg.geoip_cache_ttl == 3600
    assert cfg.library_size_enabled is False


def test_from_env_overrides():
    cfg = Config.from_env({
        "TAUTULLI_URL": "http://tautulli:8181",
        "TAUTULLI_API_KEY": "abc123",
        "EXPORTER_PORT": "8080",
        "ACTIVITY_POLL_INTERVAL": "5",
        "INVENTORY_POLL_INTERVAL": "120",
        "META_POLL_INTERVAL": "900",
        "REQUEST_TIMEOUT": "5",
        "LOG_LEVEL": "debug",
        "LOG_FORMAT": "json",
        "GEOIP_ENABLED": "false",
        "GEOIP_CACHE_TTL": "60",
        "LIBRARY_SIZE_ENABLED": "true",
    })
    assert cfg.exporter_port == 8080
    assert cfg.activity_poll_interval == 5
    assert cfg.inventory_poll_interval == 120
    assert cfg.meta_poll_interval == 900
    assert cfg.request_timeout == 5
    assert cfg.log_level == "DEBUG"
    assert cfg.log_format == "json"
    assert cfg.geoip_enabled is False
    assert cfg.geoip_cache_ttl == 60
    assert cfg.library_size_enabled is True


def test_log_format_default_is_text():
    cfg = Config.from_env({
        "TAUTULLI_URL": "http://tautulli:8181",
        "TAUTULLI_API_KEY": "abc123",
    })
    assert cfg.log_format == "text"


def test_invalid_log_format_raises():
    with pytest.raises(ConfigError, match="LOG_FORMAT"):
        Config.from_env({
            "TAUTULLI_URL": "http://x",
            "TAUTULLI_API_KEY": "k",
            "LOG_FORMAT": "yaml",
        })


def test_sanitized_redacts_api_key():
    cfg = Config.from_env({
        "TAUTULLI_URL": "http://tautulli",
        "TAUTULLI_API_KEY": "super-secret-key",
    })
    s = cfg.sanitized()
    assert s["api_key"] == "***"
    assert s["tautulli_url"] == "http://tautulli"
    assert cfg.api_key == "super-secret-key"


def test_invalid_bool_raises():
    with pytest.raises(ConfigError, match="GEOIP_ENABLED"):
        Config.from_env({
            "TAUTULLI_URL": "http://tautulli",
            "TAUTULLI_API_KEY": "k",
            "GEOIP_ENABLED": "maybe",
        })


def test_missing_url_raises():
    with pytest.raises(ConfigError, match="TAUTULLI_URL"):
        Config.from_env({"TAUTULLI_API_KEY": "x"})


def test_missing_api_key_raises():
    with pytest.raises(ConfigError, match="TAUTULLI_API_KEY"):
        Config.from_env({"TAUTULLI_URL": "http://x"})


def test_invalid_int_raises():
    with pytest.raises(ConfigError, match="EXPORTER_PORT"):
        Config.from_env({
            "TAUTULLI_URL": "http://tautulli",
            "TAUTULLI_API_KEY": "k",
            "EXPORTER_PORT": "not-a-number",
        })


def test_blank_int_uses_default():
    cfg = Config.from_env({
        "TAUTULLI_URL": "http://tautulli",
        "TAUTULLI_API_KEY": "k",
        "EXPORTER_PORT": "",
    })
    assert cfg.exporter_port == 9487


def test_zero_interval_rejected():
    """Zero would mean 'poll every iteration'; almost always a misconfig."""
    with pytest.raises(ConfigError, match="ACTIVITY_POLL_INTERVAL"):
        Config.from_env({
            "TAUTULLI_URL": "http://x",
            "TAUTULLI_API_KEY": "k",
            "ACTIVITY_POLL_INTERVAL": "0",
        })


def test_negative_interval_rejected():
    with pytest.raises(ConfigError, match="INVENTORY_POLL_INTERVAL"):
        Config.from_env({
            "TAUTULLI_URL": "http://x",
            "TAUTULLI_API_KEY": "k",
            "INVENTORY_POLL_INTERVAL": "-1",
        })


def test_legacy_poll_interval_rejected_with_helpful_message():
    """POLL_INTERVAL was removed in the tiered-polling refactor."""
    with pytest.raises(ConfigError, match="POLL_INTERVAL.*ACTIVITY_POLL_INTERVAL"):
        Config.from_env({
            "TAUTULLI_URL": "http://x",
            "TAUTULLI_API_KEY": "k",
            "POLL_INTERVAL": "30",
        })
