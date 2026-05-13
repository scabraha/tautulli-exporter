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
    assert cfg.poll_interval == 30
    assert cfg.log_level == "INFO"
    assert cfg.geoip_enabled is True
    assert cfg.geoip_cache_ttl == 3600


def test_from_env_overrides():
    cfg = Config.from_env({
        "TAUTULLI_URL": "http://tautulli:8181",
        "TAUTULLI_API_KEY": "abc123",
        "EXPORTER_PORT": "8080",
        "POLL_INTERVAL": "10",
        "REQUEST_TIMEOUT": "5",
        "LOG_LEVEL": "debug",
        "LOG_FORMAT": "json",
        "GEOIP_ENABLED": "false",
        "GEOIP_CACHE_TTL": "60",
    })
    assert cfg.exporter_port == 8080
    assert cfg.poll_interval == 10
    assert cfg.request_timeout == 5
    assert cfg.log_level == "DEBUG"
    assert cfg.log_format == "json"
    assert cfg.geoip_enabled is False
    assert cfg.geoip_cache_ttl == 60


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
    # Original config unchanged.
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
