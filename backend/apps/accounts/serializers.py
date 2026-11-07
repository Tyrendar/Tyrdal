from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import PERMISSIONS, AppRole, Device, Role, RolePermission, User


class UserSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    roles = serializers.SlugRelatedField(many=True, slug_field="code", queryset=AppRole.objects.all(), required=False)
    # Kept for PDA app versions that read a single role: the first role, if any.
    role = serializers.SerializerMethodField()
    role_names = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, min_length=4)

    class Meta:
        model = User
        fields = ["id", "username", "full_name", "roles", "role", "role_names", "capacity_boxes", "language", "is_active", "last_login", "date_joined",
                  "permissions", "password"]
        read_only_fields = ["last_login", "date_joined", "permissions"]

    def get_permissions(self, obj):
        return sorted(obj.permission_codes())

    def get_role_names(self, obj):
        return [{"code": r.code, "name_fa": r.name_fa, "name_en": r.name_en} for r in obj.roles.all()] if obj.pk else []

    def get_role(self, obj):
        codes = obj.role_codes()
        return codes[0] if codes else ""

    def validate_roles(self, value):
        request = self.context.get("request")
        # Only admins can grant the admin role.
        if any(r.code == Role.ADMIN for r in value) and request and not request.user.is_admin:
            raise serializers.ValidationError("only_admin_can_grant_admin")
        return value

    def create(self, validated):
        password = validated.pop("password", None)
        roles = validated.pop("roles", [])
        if not password:
            raise serializers.ValidationError({"password": "required"})
        user = User(**validated)
        user.set_password(password)
        user.save()
        user.roles.set(roles)
        return user

    def update(self, instance, validated):
        validated.pop("password", None)  # password changes go through reset_password
        roles = validated.pop("roles", None)
        user = super().update(instance, validated)
        if roles is not None:
            user.roles.set(roles)
        return user


class ResetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(min_length=4)


class LoginSerializer(TokenObtainPairSerializer):
    device_serial = serializers.CharField(required=False, allow_blank=True)
    device_model = serializers.CharField(required=False, allow_blank=True)
    app_version = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        serial = (attrs.get("device_serial") or "").strip()
        if serial:
            device, _ = Device.objects.get_or_create(serial=serial)
            device.model = attrs.get("device_model") or device.model
            device.app_version = attrs.get("app_version") or device.app_version
            device.last_seen_at = timezone.now()
            device.last_user = user
            device.save()
            data["device_id"] = device.pk
        data["user"] = UserSerializer(user).data
        return data


class AppRoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    users = serializers.IntegerField(source="n_users", read_only=True, default=0)

    class Meta:
        model = AppRole
        fields = ["id", "code", "name_fa", "name_en", "is_system", "permissions", "users"]
        read_only_fields = ["code", "is_system"]

    def get_permissions(self, obj):
        if obj.code == Role.ADMIN:
            return sorted(PERMISSIONS)
        return sorted(RolePermission.objects.filter(role=obj.code).values_list("permission", flat=True))

    def validate_name_fa(self, v):
        v = " ".join(v.split())
        if not v:
            raise serializers.ValidationError("required")
        return v


class RolePermissionsSerializer(serializers.Serializer):
    role = serializers.SlugRelatedField(slug_field="code", queryset=AppRole.objects.exclude(code=Role.ADMIN))
    permissions = serializers.ListField(child=serializers.ChoiceField(choices=list(PERMISSIONS)))


def role_permission_matrix() -> dict:
    held: dict[str, list[str]] = {r.code: [] for r in AppRole.objects.all()}
    for rp in RolePermission.objects.all():
        if rp.role in held:
            held[rp.role].append(rp.permission)
    held[Role.ADMIN] = sorted(PERMISSIONS)
    return {"permissions": PERMISSIONS, "roles": {k: sorted(v) for k, v in held.items()}}
