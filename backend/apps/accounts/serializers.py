from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import PERMISSIONS, Device, Role, RolePermission, User


class UserSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, min_length=4)

    class Meta:
        model = User
        fields = ["id", "username", "full_name", "role", "language", "is_active", "last_login", "date_joined",
                  "permissions", "password"]
        read_only_fields = ["last_login", "date_joined", "permissions"]

    def get_permissions(self, obj):
        return sorted(obj.permission_codes())

    def validate_role(self, value):
        request = self.context.get("request")
        # Only admins can create or promote admins.
        if value == Role.ADMIN and request and request.user.role != Role.ADMIN:
            raise serializers.ValidationError("only_admin_can_grant_admin")
        return value

    def create(self, validated):
        password = validated.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "required"})
        user = User(**validated)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated):
        validated.pop("password", None)  # password changes go through reset_password
        return super().update(instance, validated)


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


class RolePermissionsSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[Role.SUPERVISOR, Role.CHECKER])
    permissions = serializers.ListField(child=serializers.ChoiceField(choices=list(PERMISSIONS)))


def role_permission_matrix() -> dict:
    held: dict[str, list[str]] = {r: [] for r in Role.values}
    for rp in RolePermission.objects.all():
        held[rp.role].append(rp.permission)
    held[Role.ADMIN] = sorted(PERMISSIONS)
    return {"permissions": PERMISSIONS, "roles": {k: sorted(v) for k, v in held.items()}}
