from .models import AuditLog


def record(action: str, entity, *, user=None, order=None, before=None, after=None, note: str = "",
           device=None, request=None) -> AuditLog:
    ip = None
    if request is not None:
        ip = (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip() or None
        if user is None and getattr(request, "user", None) and request.user.is_authenticated:
            user = request.user
    return AuditLog.objects.create(
        action=action,
        entity_type=entity.__class__.__name__ if not isinstance(entity, tuple) else entity[0],
        entity_id=str(entity.pk if not isinstance(entity, tuple) else entity[1]),
        user=user,
        order=order,
        before=before,
        after=after,
        note=note,
        device=device,
        ip=ip,
    )
