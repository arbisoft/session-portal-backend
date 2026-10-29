from rest_framework.permissions import BasePermission


class IsStaffPermission(BasePermission):
    """ Allow access only to staff users """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_staff)
