from django.contrib.auth.backends import ModelBackend


class LocalAccountBackend(ModelBackend):
    """Authenticate passwords only for accounts explicitly issued locally."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(
            request,
            username=username,
            password=password,
            **kwargs,
        )
        if user is None or not user.local_login_enabled:
            return None
        return user


class EntraSessionBackend(ModelBackend):
    """Session loader for users already verified by the Entra callback."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        return None
