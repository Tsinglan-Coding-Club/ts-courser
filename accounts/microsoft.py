import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID

import jwt
import msal
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from jwt import PyJWKClient

from .models import ExternalIdentity, User


class MicrosoftIdentityError(Exception):
    """Raised when Microsoft authenticated a principal we cannot admit."""


@dataclass(frozen=True)
class MicrosoftPrincipal:
    tenant_id: str
    object_id: str
    principal_name: str
    display_name: str


_jwk_clients = {}


def _get_jwk_client():
    jwks_uri = (
        'https://login.microsoftonline.com/'
        f'{settings.MS_ENTRA_TENANT_ID}/discovery/v2.0/keys'
    )
    if jwks_uri not in _jwk_clients:
        _jwk_clients[jwks_uri] = PyJWKClient(
            jwks_uri,
            cache_keys=True,
            lifespan=300,
        )
    return _jwk_clients[jwks_uri]


def build_msal_app():
    if not settings.MS_ENTRA_CLIENT_SECRET:
        raise MicrosoftIdentityError('Microsoft sign-in is not configured.')
    return msal.ConfidentialClientApplication(
        settings.MS_ENTRA_CLIENT_ID,
        authority=settings.MS_ENTRA_AUTHORITY,
        client_credential=settings.MS_ENTRA_CLIENT_SECRET,
        exclude_scopes=['offline_access'],
    )


def verify_id_token(id_token, flow_nonce):
    """Verify the Entra ID token before any decoded claim is trusted."""
    if not id_token or not flow_nonce:
        raise MicrosoftIdentityError('The Microsoft ID token is incomplete.')
    expected_issuer = (
        f'https://login.microsoftonline.com/{settings.MS_ENTRA_TENANT_ID}/v2.0'
    )
    try:
        signing_key = _get_jwk_client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=['RS256'],
            audience=settings.MS_ENTRA_CLIENT_ID,
            issuer=expected_issuer,
            leeway=120,
            options={
                'require': [
                    'aud', 'exp', 'iat', 'iss', 'nbf', 'nonce',
                    'oid', 'sub', 'tid',
                ],
            },
        )
    except Exception as exc:
        raise MicrosoftIdentityError(
            'The Microsoft ID token could not be verified.'
        ) from exc

    expected_nonce = hashlib.sha256(flow_nonce.encode('ascii')).hexdigest()
    if not hmac.compare_digest(str(claims.get('nonce', '')), expected_nonce):
        raise MicrosoftIdentityError('The Microsoft sign-in nonce is invalid.')
    return claims


def validate_claims(claims):
    tenant_id = str(claims.get('tid', '')).lower()
    object_id = str(claims.get('oid', '')).lower()
    audience = claims.get('aud')
    issuer = str(claims.get('iss', '')).lower().rstrip('/')
    principal_name = str(claims.get('preferred_username', '')).strip()
    expected_issuer = (
        f'https://login.microsoftonline.com/{settings.MS_ENTRA_TENANT_ID}/v2.0'
    ).lower()

    if tenant_id != settings.MS_ENTRA_TENANT_ID.lower():
        raise MicrosoftIdentityError('This Microsoft tenant is not allowed.')
    if (
        audience != settings.MS_ENTRA_CLIENT_ID
        and not (
            isinstance(audience, list)
            and settings.MS_ENTRA_CLIENT_ID in audience
        )
    ):
        raise MicrosoftIdentityError('The Microsoft token audience is invalid.')
    if issuer != expected_issuer:
        raise MicrosoftIdentityError('The Microsoft token issuer is invalid.')
    try:
        UUID(object_id)
    except ValueError:
        raise MicrosoftIdentityError('The Microsoft account has no object identifier.')
    # `acct` is an optional ID-token claim configured in Entra. Requiring 0
    # fails closed if the app registration does not emit it and rejects guests.
    if str(claims.get('acct', '')) != '0':
        raise MicrosoftIdentityError('Guest Microsoft accounts are not allowed.')
    if '@' not in principal_name:
        raise MicrosoftIdentityError('The Microsoft account has no school sign-in name.')
    domain = principal_name.rsplit('@', 1)[1].lower()
    if domain != settings.MS_ENTRA_SCHOOL_DOMAIN.lower():
        raise MicrosoftIdentityError('This is not a school Microsoft account.')
    if len(principal_name) > 254:
        raise MicrosoftIdentityError('The Microsoft school sign-in name is too long.')

    return MicrosoftPrincipal(
        tenant_id=tenant_id,
        object_id=object_id,
        principal_name=principal_name,
        display_name=str(claims.get('name', '')).strip()[:200],
    )


def _entra_username(object_id):
    return f'entra_{object_id.replace("-", "").lower()}'


@transaction.atomic
def get_or_create_microsoft_user(principal, requested_role):
    if requested_role is not None and requested_role not in {'student', 'teacher'}:
        raise MicrosoftIdentityError('The requested role is invalid.')

    identity = (
        ExternalIdentity.objects.select_related('user')
        .filter(
            provider=ExternalIdentity.PROVIDER_MICROSOFT,
            tenant_id=principal.tenant_id,
            object_id=principal.object_id,
        )
        .first()
    )
    now = timezone.now()
    if identity:
        user = identity.user
        if requested_role is not None and user.role != requested_role:
            raise MicrosoftIdentityError(
                'This Microsoft account is already registered with another role.'
            )
        if not user.is_active:
            raise MicrosoftIdentityError('This account has been disabled.')
        identity.principal_name = principal.principal_name
        identity.display_name = principal.display_name
        identity.last_authenticated_at = now
        identity.save(update_fields=(
            'principal_name', 'display_name', 'last_authenticated_at',
        ))
        user.email = principal.principal_name
        if principal.display_name:
            user.display_name = principal.display_name[:100]
        user.save(update_fields=('email', 'display_name'))
        return user, False

    if requested_role is None:
        return None, False

    username = _entra_username(principal.object_id)
    if User.objects.filter(username=username).exists():
        raise MicrosoftIdentityError('This Microsoft identity conflicts with an existing account.')

    user = User(
        username=username,
        email=principal.principal_name,
        display_name=principal.display_name[:100],
        role=requested_role,
        is_verified_teacher=False,
        local_login_enabled=False,
    )
    user.set_unusable_password()
    user.save()
    try:
        ExternalIdentity.objects.create(
            user=user,
            provider=ExternalIdentity.PROVIDER_MICROSOFT,
            tenant_id=principal.tenant_id,
            object_id=principal.object_id,
            principal_name=principal.principal_name,
            display_name=principal.display_name,
            last_authenticated_at=now,
        )
    except IntegrityError as exc:
        raise MicrosoftIdentityError(
            'This Microsoft identity is already linked to an account.'
        ) from exc
    return user, True
