import httpx2
import pytest

from magnacoda.ai.client import is_authentication_error
from magnacoda.exceptions import AIAuthenticationError
from magnacoda.orchestrator import _run_ai_step


def _real_auth_error() -> Exception:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(401, request=request)
    import anthropic

    return anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)


def test_is_authentication_error_true_for_a_real_sdk_auth_error():
    assert is_authentication_error(_real_auth_error()) is True


def test_is_authentication_error_false_for_an_unrelated_exception():
    assert is_authentication_error(ValueError("boom")) is False


def test_run_ai_step_translates_auth_error_to_our_own_exception_type():
    def fn():
        raise _real_auth_error()

    with pytest.raises(AIAuthenticationError):
        _run_ai_step(fn)


def test_run_ai_step_passes_through_an_unrelated_exception_unchanged():
    def fn():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        _run_ai_step(fn)


def test_run_ai_step_returns_the_function_result_on_success():
    assert _run_ai_step(lambda: 42) == 42
