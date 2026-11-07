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


def require_any(*codes: str) -> type[BasePermission]:
    """DRF permission class requiring *at least one* of the given permission codes."""

    class _RequireAny(BasePermission):
        message = "permission_denied"

        def has_permission(self, request, view):
            user = request.user
            if not (user and user.is_authenticated):
                return False
            return bool(user.permission_codes() & set(codes))

    _RequireAny.__name__ = "RequireAny_" + "_".join(c.replace(".", "_") for c in codes)
    return _RequireAny
