"""Uniform JSON error envelope: {"error": {"code": ..., "message": ...}}."""

from __future__ import annotations

import traceback

from flask import Flask, current_app, jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str):
    return jsonify({"error": {"code": code, "message": message}}), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _api_error(error: ApiError):
        return error_response(error.status, error.code, error.message)

    @app.errorhandler(ValidationError)
    def _validation_error(error: ValidationError):
        first = error.errors()[0]
        field = ".".join(str(p) for p in first["loc"])
        message = f"{field}: {first['msg']}" if field else first["msg"]
        return error_response(400, "invalid_request", message)

    @app.errorhandler(HTTPException)
    def _http_error(error: HTTPException):
        return error_response(
            error.code or 500, (error.name or "error").lower().replace(" ", "_"), error.description
        )

    @app.errorhandler(Exception)
    def _unexpected_error(error: Exception):
        # Anything unhandled (for example a database that was not migrated).
        # Log the details; do not leak them to the client.
        current_app.extensions["kyvon"].error_log.log(
            "Unhandled Error", str(error), traceback.format_exc()
        )
        return error_response(500, "internal_error", "Internal server error.")
