"""Access to application services from request handlers."""

from __future__ import annotations

from flask import current_app, request
from pydantic import BaseModel

from kyvon.api.errors import ApiError


def services():
    return current_app.extensions["kyvon"]


def parse_json[T: BaseModel](model: type[T]) -> T:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_request", "Request body must be a JSON object.")
    return model.model_validate(data)
