import pytest

from app.sut_auth import SUTAuthError, project_headers


def test_public_project_ignores_old_global_credentials(monkeypatch):
    monkeypatch.setenv("SUT_HEADERS_JSON", '{"Authorization":"Bearer global-secret"}')
    assert project_headers(None) == {}


def test_only_explicit_project_variable_is_read(monkeypatch):
    monkeypatch.setenv("SUT_HEADERS_JSON", '{"Authorization":"Bearer global-secret"}')
    monkeypatch.setenv("SUT_A_HEADERS", '{"Authorization":"Bearer secret-a"}')
    monkeypatch.setenv("SUT_B_HEADERS", '{"X-Api-Key":"secret-b"}')
    assert project_headers("SUT_A_HEADERS") == {"Authorization": "Bearer secret-a"}
    assert project_headers("SUT_B_HEADERS") == {"X-Api-Key": "secret-b"}
    assert project_headers(None) == {}


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "sensitive-invalid-json",
        "null",
        "[]",
        '"sensitive"',
        '{"Authorization":123}',
        '{"Authorization":null}',
        '{"Authorization":true}',
        '{"Bad Header":"sensitive"}',
        '{"Authorization":"sensitive\\r\\nX-Test: injected"}',
    ],
)
def test_invalid_or_missing_project_headers_fail_without_exposing_values(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("SUT_PRIVATE_HEADERS", raising=False)
    else:
        monkeypatch.setenv("SUT_PRIVATE_HEADERS", raw)
    with pytest.raises(SUTAuthError) as error:
        project_headers("SUT_PRIVATE_HEADERS")
    assert "SUT_PRIVATE_HEADERS" in str(error.value)
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("name", ["", "GEMINI_API_KEY", "SUT_bad", "SUT_HEADERS\n", 42])
def test_invalid_variable_names_fail_closed(name):
    with pytest.raises(SUTAuthError):
        project_headers(name)
