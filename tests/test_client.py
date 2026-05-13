import pytest
import responses

from tautulli_exporter.client import TautulliClient, TautulliError


@pytest.fixture
def client() -> TautulliClient:
    return TautulliClient(
        base_url="http://tautulli.test",
        api_key="test-key",
        timeout=5,
    )


def _ok(payload):
    return {"response": {"result": "success", "data": payload}}


def _err(message):
    return {"response": {"result": "error", "message": message}}


@responses.activate
def test_call_sends_apikey_and_cmd(client):
    responses.get("http://tautulli.test/api/v2", json=_ok({"ok": True}))

    body = client.call("get_activity")

    assert body == {"ok": True}
    request = responses.calls[0].request
    assert "apikey=test-key" in request.url
    assert "cmd=get_activity" in request.url


@responses.activate
def test_call_passes_extra_params(client):
    responses.get("http://tautulli.test/api/v2", json=_ok({}))
    client.call("get_geoip_lookup", ip_address="8.8.8.8")
    assert "ip_address=8.8.8.8" in responses.calls[0].request.url


@responses.activate
def test_call_raises_on_api_error(client):
    responses.get("http://tautulli.test/api/v2", json=_err("invalid api key"))
    with pytest.raises(TautulliError, match="invalid api key"):
        client.call("get_activity")


@responses.activate
def test_call_raises_http_error_with_status_and_cmd(client):
    responses.get(
        "http://tautulli.test/api/v2", status=403, body="forbidden"
    )
    import requests
    with pytest.raises(requests.HTTPError) as exc_info:
        client.call("get_activity")
    msg = str(exc_info.value)
    assert "403" in msg
    assert "cmd=get_activity" in msg
    assert "TAUTULLI_API_KEY" in msg


@responses.activate
def test_call_raises_http_error_includes_body(client):
    responses.get(
        "http://tautulli.test/api/v2", status=500, body="db down"
    )
    import requests
    with pytest.raises(requests.HTTPError) as exc_info:
        client.call("get_activity")
    assert "db down" in str(exc_info.value)


# -- get_activity --------------------------------------------------------


@responses.activate
def test_get_activity_returns_dict(client):
    responses.get(
        "http://tautulli.test/api/v2",
        json=_ok({"stream_count": 3, "sessions": [{"user": "alice"}]}),
    )
    activity = client.get_activity()
    assert activity["stream_count"] == 3
    assert activity["sessions"][0]["user"] == "alice"


@responses.activate
def test_get_activity_returns_empty_when_data_missing(client):
    responses.get("http://tautulli.test/api/v2", json=_ok(None))
    assert client.get_activity() == {}


# -- get_libraries / table -----------------------------------------------


@responses.activate
def test_get_libraries_returns_list(client):
    responses.get(
        "http://tautulli.test/api/v2",
        json=_ok([{"section_name": "Movies", "count": 100}]),
    )
    libraries = client.get_libraries()
    assert libraries[0]["section_name"] == "Movies"


@responses.activate
def test_get_libraries_returns_empty_when_data_not_a_list(client):
    responses.get("http://tautulli.test/api/v2", json=_ok({"unexpected": "shape"}))
    assert client.get_libraries() == []


@responses.activate
def test_get_libraries_table_unwraps_data(client):
    responses.get(
        "http://tautulli.test/api/v2",
        json=_ok({"draw": 1, "data": [{"section_name": "Movies", "plays": 7}]}),
    )
    rows = client.get_libraries_table()
    assert rows == [{"section_name": "Movies", "plays": 7}]


@responses.activate
def test_get_libraries_table_handles_missing_data(client):
    responses.get("http://tautulli.test/api/v2", json=_ok({"draw": 1}))
    assert client.get_libraries_table() == []


@responses.activate
def test_get_library_media_info_returns_dict(client):
    responses.get(
        "http://tautulli.test/api/v2",
        json=_ok({"total_file_size": 12345, "data": []}),
    )
    info = client.get_library_media_info(7)
    assert info["total_file_size"] == 12345


# -- get_users / table ---------------------------------------------------


@responses.activate
def test_get_users_returns_list(client):
    responses.get(
        "http://tautulli.test/api/v2",
        json=_ok([{"user_id": 1, "is_active": 1, "is_home_user": 1}]),
    )
    users = client.get_users()
    assert users[0]["user_id"] == 1


@responses.activate
def test_get_users_returns_empty_on_unexpected_shape(client):
    responses.get("http://tautulli.test/api/v2", json=_ok({"oops": True}))
    assert client.get_users() == []


@responses.activate
def test_get_users_table_unwraps_data(client):
    responses.get(
        "http://tautulli.test/api/v2",
        json=_ok({"data": [{"friendly_name": "alice", "plays": 5}]}),
    )
    rows = client.get_users_table()
    assert rows[0]["friendly_name"] == "alice"


# -- server info / status ------------------------------------------------


@responses.activate
def test_get_server_info(client):
    responses.get(
        "http://tautulli.test/api/v2",
        json=_ok({"pms_version": "1.40.0", "pms_name": "media"}),
    )
    info = client.get_server_info()
    assert info["pms_version"] == "1.40.0"
    assert info["pms_name"] == "media"


@responses.activate
def test_get_server_status(client):
    responses.get(
        "http://tautulli.test/api/v2", json=_ok({"connected": True}),
    )
    assert client.get_server_status() == {"connected": True}


@responses.activate
def test_get_pms_update(client):
    responses.get(
        "http://tautulli.test/api/v2",
        json=_ok({"update_available": True, "version": "1.41.0"}),
    )
    info = client.get_pms_update()
    assert info["update_available"] is True
    assert info["version"] == "1.41.0"


# -- geoip ---------------------------------------------------------------


@responses.activate
def test_get_geoip_lookup_returns_dict(client):
    responses.get(
        "http://tautulli.test/api/v2",
        json=_ok({"city": "Seattle", "latitude": 47.6, "longitude": -122.3}),
    )
    geo = client.get_geoip_lookup("8.8.8.8")
    assert geo["city"] == "Seattle"


@responses.activate
def test_get_geoip_lookup_returns_none_on_api_error(client):
    responses.get(
        "http://tautulli.test/api/v2", json=_err("not found")
    )
    assert client.get_geoip_lookup("10.0.0.1") is None


def test_base_url_strips_trailing_slash():
    c = TautulliClient("http://tautulli.test/", "k")
    assert c._base_url == "http://tautulli.test"
