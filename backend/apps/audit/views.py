from django.utils.dateparse import parse_date
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from apps.accounts.permissions import require

from .models import AuditLog


class AuditLogView(ListAPIView):
    permission_classes = [require("audit.view")]

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user", "order")
        p = self.request.query_params
        if p.get("user"):
            qs = qs.filter(user_id=p["user"])
        if p.get("action"):
            qs = qs.filter(action__startswith=p["action"])
        if p.get("from") and parse_date(p["from"]):
            qs = qs.filter(at__date__gte=parse_date(p["from"]))
        if p.get("to") and parse_date(p["to"]):
            qs = qs.filter(at__date__lte=parse_date(p["to"]))
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([
            {"id": a.pk, "at": a.at, "user": a.user.display_name if a.user else None, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "order_id": a.order_id,
             "order_reference": a.order.reference_id if a.order else None, "before": a.before, "after": a.after,
             "note": a.note, "ip": a.ip}
            for a in page
        ])
