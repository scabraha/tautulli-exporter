from unittest.mock import MagicMock

import pytest

from tautulli_exporter.geoip import GeoIPLookup, _has_coords, _is_local


@pytest.fixture
def fake_client():
    return MagicMock()


def test_lookup_returns_record(fake_client):
    fake_client.get_geoip_lookup.return_value = {
        "city": "Seattle", "latitude": 47.6, "longitude": -122.3,
    }
    geo = GeoIPLookup(fake_client)
    assert geo.lookup("8.8.8.8")["city"] == "Seattle"


def test_lookup_caches_result(fake_client):
    fake_client.get_geoip_lookup.return_value = {
        "city": "Seattle", "latitude": 47.6, "longitude": -122.3,
    }
    geo = GeoIPLookup(fake_client, ttl_seconds=3600)
    geo.lookup("8.8.8.8")
    geo.lookup("8.8.8.8")
    assert fake_client.get_geoip_lookup.call_count == 1


def test_lookup_caches_misses_too(fake_client):
    """Misses are cached so we don't hammer Tautulli with hopeless lookups."""
    fake_client.get_geoip_lookup.return_value = None
    geo = GeoIPLookup(fake_client)
    assert geo.lookup("8.8.8.8") is None
    assert geo.lookup("8.8.8.8") is None
    assert fake_client.get_geoip_lookup.call_count == 1


def test_lookup_skips_empty_ip(fake_client):
    geo = GeoIPLookup(fake_client)
    assert geo.lookup("") is None
    fake_client.get_geoip_lookup.assert_not_called()


@pytest.mark.parametrize("ip", [
    "10.0.0.1", "172.16.0.1", "192.168.1.1", "127.0.0.1",
    "169.254.1.1", "::1", "fc00::1", "fe80::1",
])
def test_lookup_skips_local_ips(fake_client, ip):
    geo = GeoIPLookup(fake_client)
    assert geo.lookup(ip) is None
    fake_client.get_geoip_lookup.assert_not_called()


def test_lookup_treats_zero_coords_as_miss(fake_client):
    """Tautulli sometimes returns success+zero coords for unresolvable IPs."""
    fake_client.get_geoip_lookup.return_value = {
        "city": "", "latitude": 0, "longitude": 0,
    }
    geo = GeoIPLookup(fake_client)
    assert geo.lookup("8.8.8.8") is None


def test_lookup_treats_missing_coords_as_miss(fake_client):
    fake_client.get_geoip_lookup.return_value = {"city": "Nowhere"}
    geo = GeoIPLookup(fake_client)
    assert geo.lookup("8.8.8.8") is None


@pytest.mark.parametrize("ip,expected", [
    ("10.0.0.1", True),
    ("192.168.1.10", True),
    ("127.0.0.1", True),
    ("169.254.1.1", True),
    ("::1", True),
    ("8.8.8.8", False),
    ("not-an-ip", False),
])
def test_is_local(ip, expected):
    assert _is_local(ip) is expected


def test_has_coords():
    assert _has_coords({"latitude": 47.6, "longitude": -122.3}) is True
    assert _has_coords({"latitude": 0, "longitude": 0}) is False
    assert _has_coords({"latitude": "0", "longitude": "0"}) is False
    assert _has_coords({"latitude": None, "longitude": -122.3}) is False
    assert _has_coords({}) is False
