from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from users.forms import CustomUserCreationForm

User = get_user_model()


class CustomUserAdmin(UserAdmin):
    """ Custom Admin for User Model"""
    add_form = CustomUserCreationForm
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "first_name", "last_name", "password1", "password2"),
        }),
    )
    search_fields = ['first_name', 'last_name', 'email']


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
