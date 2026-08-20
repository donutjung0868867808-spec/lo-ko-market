"""Role and community-aware permissions shared by Django admin classes."""
import csv
from urllib.parse import quote

from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone


class CsvExportAdminMixin:
    """Export explicitly approved fields from selected admin rows."""

    csv_export_fields = ()
    csv_filename = "export.csv"
    actions = ("export_as_csv",)

    @staticmethod
    def _csv_value(obj, path):
        if "__" not in path:
            display_value = getattr(obj, f"get_{path}_display", None)
            if callable(display_value):
                return str(display_value())
        value = obj
        for part in path.split("__"):
            value = getattr(value, part, "")
            if value is None:
                return ""
        if callable(value):
            value = value()
        if hasattr(value, "tzinfo") and value.tzinfo is not None:
            value = timezone.localtime(value)
        if isinstance(value, bool):
            return "ใช่" if value else "ไม่ใช่"
        return str(value)

    @admin.action(permissions=["view"], description="ดาวน์โหลดรายการที่เลือกเป็นไฟล์ CSV")
    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(self.csv_filename)}"
        )
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow([label for _, label in self.csv_export_fields])
        for obj in queryset.iterator():
            writer.writerow(
                [self._csv_value(obj, field) for field, _ in self.csv_export_fields]
            )
        return response


def staff_community(user):
    if not getattr(user, "is_authenticated", False):
        return None
    profile = getattr(user, "community_staff_profile", None)
    return getattr(profile, "community", None)


class RoleScopedAdminMixin:
    """Grant Django Admin access to system owners only."""

    staff_access = False
    staff_can_add = False
    staff_can_change = False
    staff_can_delete = False
    community_filter = None

    def _is_owner(self, user):
        return bool(getattr(user, "is_authenticated", False) and user.is_owner)

    def _is_scoped_staff(self, user):
        # Community officers use the dedicated staff portal, never Django Admin.
        return False

    def get_staff_scope_filter(self, user, community):
        if not self.community_filter:
            return None
        return {self.community_filter: community}

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self._is_owner(request.user):
            return queryset
        if not self.staff_access or not self._is_scoped_staff(request.user):
            return queryset.none()
        scope = self.get_staff_scope_filter(
            request.user,
            staff_community(request.user),
        )
        if not scope:
            return queryset.none()
        return queryset.filter(**scope).distinct()

    def _object_is_in_scope(self, request, obj):
        if obj is None:
            return True
        return self.get_queryset(request).filter(pk=obj.pk).exists()

    def has_module_permission(self, request):
        return self._is_owner(request.user) or (
            self.staff_access and self._is_scoped_staff(request.user)
        )

    def get_model_perms(self, request):
        if self._is_owner(request.user):
            return {
                "add": self.has_add_permission(request),
                "change": self.has_change_permission(request),
                "delete": self.has_delete_permission(request),
                "view": self.has_view_permission(request),
            }
        if self.staff_access and self._is_scoped_staff(request.user):
            return {
                "add": self.staff_can_add,
                "change": self.staff_can_change,
                "delete": self.staff_can_delete,
                "view": True,
            }
        return {}

    def has_view_permission(self, request, obj=None):
        if self._is_owner(request.user):
            return True
        return bool(
            self.staff_access
            and self._is_scoped_staff(request.user)
            and self._object_is_in_scope(request, obj)
        )

    def has_add_permission(self, request):
        if self._is_owner(request.user):
            return True
        return bool(
            self.staff_access
            and self.staff_can_add
            and self._is_scoped_staff(request.user)
        )

    def has_change_permission(self, request, obj=None):
        if self._is_owner(request.user):
            return True
        return bool(
            self.staff_access
            and self.staff_can_change
            and self._is_scoped_staff(request.user)
            and self._object_is_in_scope(request, obj)
        )

    def has_delete_permission(self, request, obj=None):
        if self._is_owner(request.user):
            return True
        return bool(
            self.staff_access
            and self.staff_can_delete
            and self._is_scoped_staff(request.user)
            and self._object_is_in_scope(request, obj)
        )


class OwnerOnlyAdminMixin(RoleScopedAdminMixin):
    """Expose a model only to system owners and superusers."""