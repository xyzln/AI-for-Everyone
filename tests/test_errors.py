"""Unified error body schema (05-api-contract §3)."""

from aife.errors import AIEError, ErrorBody, ErrorCode, ErrorResponse, http_status_for


def test_body_shape():
    e = AIEError(ErrorCode.MODEL_NOT_FOUND, "missing", details={"model": "m"})
    b = e.to_body()
    assert b.code == "MODEL_NOT_FOUND"
    assert b.message == "missing"
    assert b.details == {"model": "m"}
    assert "trace_id" in b.model_dump()


def test_status_map():
    assert http_status_for(ErrorCode.MODEL_NOT_FOUND) == 404
    assert http_status_for(ErrorCode.OLLAMA_UNAVAILABLE) == 503
    assert http_status_for(ErrorCode.BACKEND_UNHEALTHY) == 503
    assert http_status_for(ErrorCode.VALIDATION) == 400
    assert http_status_for(ErrorCode.PULL_IN_PROGRESS) == 409
    assert http_status_for(ErrorCode.UPSTREAM_TIMEOUT) == 504


def test_response_envelope():
    r = ErrorResponse(error=ErrorBody(code="X", message="y"))
    assert r.model_dump()["error"]["code"] == "X"
