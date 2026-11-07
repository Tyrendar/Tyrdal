from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.audit.services import record

from .errors import DomainError
from .models import AppRole, Role, RolePermission, User, users_with_role_perm
from .permissions import require, require_any
from .serializers import (
    AppRoleSerializer, LoginSerializer, ResetPasswordSerializer, RolePermissionsSerializer, UserSerializer, role_permission_matrix,
)


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        lang = request.data.get("language")
        if lang in ("fa", "en"):
            request.user.language = lang
            request.user.save(update_fields=["language"])
        return Response(UserSerializer(request.user).data)


class UserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                  mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """No delete: users are deactivated so their history stays attributable."""

    serializer_class = UserSerializer
    permission_classes = [require("users.manage")]

    def get_queryset(self):
        qs = User.objects.prefetch_related("roles")
        p = self.request.query_params
        if p.get("role"):
            qs = qs.filter(roles__code=p["role"]).distinct()
        if p.get("active") in ("true", "false"):
            qs = qs.filter(is_active=p["active"] == "true")
        if p.get("q"):
            qs = qs.filter(Q(username__icontains=p["q"]) | Q(full_name__icontains=p["q"]))
        return qs

    def perform_create(self, serializer):
        user = serializer.save()
        record("user.created", user, request=self.request, after={"username": user.username, "roles": user.role_codes()})

    def perform_update(self, serializer):
        before = {"roles": serializer.instance.role_codes(), "is_active": serializer.instance.is_active,
                  "full_name": serializer.instance.full_name}
        if serializer.instance.pk == self.request.user.pk and serializer.validated_data.get("is_active") is False:
            raise DomainError("cannot_deactivate_self")
        if serializer.instance.is_admin and not self.request.user.is_admin:
            raise DomainError("only_admin_can_edit_admin", http_status=403)
        if (serializer.instance.pk == self.request.user.pk and "roles" in serializer.validated_data
                and Role.ADMIN in before["roles"] and all(r.code != Role.ADMIN for r in serializer.validated_data["roles"])):
            raise DomainError("cannot_remove_own_admin")
        user = serializer.save()
        record("user.updated", user, request=self.request, before=before,
               after={"roles": user.role_codes(), "is_active": user.is_active, "full_name": user.full_name})

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        if user.is_admin and not request.user.is_admin:
            raise DomainError("only_admin_can_edit_admin", http_status=403)
        s = ResetPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user.set_password(s.validated_data["password"])
        user.save(update_fields=["password"])
        record("user.password_reset", user, request=request)
        return Response({"ok": True})

    @action(detail=False, methods=["get"])
    def activity(self, request):
        """Per-user activity today: last login, scans, orders completed."""
        start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        qs = self.get_queryset().annotate(
            scans_today=Count("check_events", filter=Q(check_events__kind="scan", check_events__client_at__gte=start)),
        )
        return Response([
            {"id": u.pk, "username": u.username, "full_name": u.full_name, "roles": [r.code for r in u.roles.all()], "is_active": u.is_active,
             "last_login": u.last_login, "scans_today": u.scans_today}
            for u in qs
        ])


class CheckersView(APIView):
    """Active checkers with their current workload, for the assignment picker."""

    permission_classes = [require("orders.view")]

    def get(self, request):
        qs = users_with_role_perm("checking.perform").annotate(
            active_orders=Count("assignments", filter=Q(assignments__revoked_at__isnull=True,
                                                        assignments__order__status__in=("assigned", "in_progress"))),
        ).order_by("full_name", "username")
        return Response([{"id": u.pk, "username": u.username, "name": u.display_name, "active_orders": u.active_orders}
                         for u in qs])


class RolePermissionView(APIView):
    def get_permissions(self):
        return [require("permissions.manage")()] if self.request.method != "GET" else [require("users.manage")()]

    def get(self, request):
        return Response(role_permission_matrix())

    @transaction.atomic
    def put(self, request):
        s = RolePermissionsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        role, perms = s.validated_data["role"].code, set(s.validated_data["permissions"])
        before = sorted(RolePermission.objects.filter(role=role).values_list("permission", flat=True))
        RolePermission.objects.filter(role=role).delete()
        RolePermission.objects.bulk_create(RolePermission(role=role, permission=p) for p in sorted(perms))
        record("permissions.changed", ("Role", role), request=request, before=before, after=sorted(perms))
        return Response(role_permission_matrix())


class AppRoleViewSet(viewsets.ModelViewSet):
    """Roles: list (for the user form and the permissions page), create, rename, delete.

    Built-in roles cannot be deleted; a role still held by users cannot be deleted.
    Permissions of a role are set through role-permissions/.
    """

    serializer_class = AppRoleSerializer
    pagination_class = None

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [require_any("users.manage", "permissions.manage")()]
        return [require("permissions.manage")()]

    def get_queryset(self):
        return AppRole.objects.annotate(n_users=Count("users", filter=Q(users__is_active=True)))

    def perform_create(self, serializer):
        from django.utils.text import slugify

        base = slugify(serializer.validated_data.get("name_en") or "") or "role"
        code, n = base[:30], 1
        while AppRole.objects.filter(code=code).exists():
            n += 1
            code = f"{base[:30]}-{n}"
        role = serializer.save(code=code, is_system=False)
        record("role.created", role, request=self.request, after={"code": role.code, "name_fa": role.name_fa, "name_en": role.name_en})

    def perform_update(self, serializer):
        before = {"name_fa": serializer.instance.name_fa, "name_en": serializer.instance.name_en}
        role = serializer.save()
        record("role.updated", role, request=self.request, before=before, after={"name_fa": role.name_fa, "name_en": role.name_en})

    def perform_destroy(self, instance):
        if instance.is_system:
            raise DomainError("role_is_builtin", "Built-in roles cannot be deleted")
        n = instance.users.count()
        if n:
            raise DomainError("role_in_use", f"{n} users still have this role", data={"users": n})
        RolePermission.objects.filter(role=instance.code).delete()
        record("role.deleted", instance, request=self.request, before={"code": instance.code, "name_fa": instance.name_fa})
        instance.delete()
