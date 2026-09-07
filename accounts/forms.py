from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import User


class FirstLoginCredentialsForm(forms.Form):
    username = forms.CharField(max_length=150, label='New username')
    password1 = forms.CharField(
        label='New password',
        strip=False,
        widget=forms.PasswordInput,
    )
    password2 = forms.CharField(
        label='Confirm new password',
        strip=False,
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        username_field = User._meta.get_field('username')
        for validator in username_field.validators:
            validator(username)
        if username == self.user.username:
            raise ValidationError('Please choose a new username.')
        if User.objects.exclude(pk=self.user.pk).filter(username__iexact=username).exists():
            raise ValidationError('This username is already in use.')
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        username = cleaned_data.get('username')
        if not password1 or not password2:
            return cleaned_data
        if password1 != password2:
            self.add_error('password2', 'The two passwords do not match.')
            return cleaned_data
        if self.user.check_password(password1):
            self.add_error('password1', 'The new password must differ from the initial password.')
            return cleaned_data

        old_username = self.user.username
        try:
            if username:
                self.user.username = username
            password_validation.validate_password(password1, self.user)
        except ValidationError as exc:
            self.add_error('password1', exc)
        finally:
            self.user.username = old_username
        return cleaned_data


class LocalStudentCreationForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        required=False,
        label='Temporary username (optional)',
        help_text='Leave blank to generate one automatically.',
    )
    display_name = forms.CharField(max_length=100, label='Student name')
    email = forms.EmailField(required=False, label='Contact email (optional)')

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if not username:
            return username
        username_field = User._meta.get_field('username')
        for validator in username_field.validators:
            validator(username)
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is already in use.')
        return username


class AdminLocalUserCreationForm(UserCreationForm):
    """Django-admin form for explicitly issued local student/admin accounts."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'role')

    def clean_role(self):
        role = self.cleaned_data['role']
        if role not in {'student', 'admin'}:
            raise ValidationError('Local teacher accounts are not supported; use Microsoft sign-in.')
        return role

    def save(self, commit=True):
        user = super().save(commit=False)
        user.local_login_enabled = True
        user.must_change_credentials = True
        user.initial_password_expires_at = timezone.now() + timedelta(
            days=settings.LOCAL_INITIAL_PASSWORD_TTL_DAYS,
        )
        user.is_verified_teacher = False
        user.is_staff = user.role == 'admin'
        if commit:
            user.save()
        return user
