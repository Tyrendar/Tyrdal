from rest_framework.permissions import BasePermission


def require(*codes: str) -> type[BasePermission]:
    """DRF permission class requiring the user to hold *all* given permission codes."""

    class _Require(BasePermission):
        message = "permission_denied"

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            held = user.permission_codes()
            return all(c in held for c in codes)

    _Require.__name__ = "Require_" + "_".join(c.replace(".", "_") for c in codes)
    return _Require
