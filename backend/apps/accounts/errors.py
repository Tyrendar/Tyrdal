"""Uniform API error shape: {"code": "...", "detail": "...", "data": {...}}.

`code` is a stable machine key the web panel and PDA translate into Persian or
English; `detail` is an English fallback for logs and developers.
"""
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "domain_error"

    def __init__(self, code: str, detail: str = "", data: dict | None = None, http_status: int | None = None):
        super().__init__(detail or code, code)
        self.error_code = code
        self.data = data or {}
        if http_status:
            self.status_code = http_status


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, DomainError):
        response.data = {"code": exc.error_code, "detail": str(exc.detail), "data": exc.data}
    elif isinstance(response.data, dict) and "detail" in response.data and len(response.data) == 1:
        code = getattr(response.data["detail"], "code", "error")
        response.data = {"code": code, "detail": str(response.data["detail"]), "data": {}}
    else:
        response.data = {"code": "validation_error", "detail": "Invalid input", "data": response.data}
    return response
