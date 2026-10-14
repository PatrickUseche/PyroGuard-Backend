import secrets

from django.conf import settings
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAuthenticatedOrIngestAPIKey(BasePermission):
    def has_permission(self, request, _view):
        if request.method in SAFE_METHODS:
            return True

        if request.user and request.user.is_authenticated:
            return True

        expected_key = settings.INGEST_API_KEY
        supplied_key = request.headers.get("X-API-Key", "")
        if not expected_key or not supplied_key:
            return False

        return secrets.compare_digest(
            supplied_key.encode("utf-8"),
            expected_key.encode("utf-8"),
        )
