from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

User = get_user_model()


class CustomUserCreationForm(forms.ModelForm):
    """ Custom user creation form with an optional password """
    password1 = forms.CharField(
        label="Password", widget=forms.PasswordInput, required=False
    )
    password2 = forms.CharField(
        label="Confirm Password", widget=forms.PasswordInput, required=False
    )

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name")

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password1 != password2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password1")

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        if commit:
            user.save()
        return user


class CustomUserAdmin(UserAdmin):
    """ Custom Admin for User Model"""
    add_form = CustomUserCreationForm
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "first_name", "last_name", "password1", "password2"),
        }),
    )


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
