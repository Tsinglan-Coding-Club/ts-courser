from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from msal.exceptions import MsalError
from requests.exceptions import RequestException

from courses.models import Tag
from ts_courser.utils import ImageUploadValidationError, validate_and_reencode_image

from .forms import FirstLoginCredentialsForm, LocalStudentCreationForm
from .microsoft import (
    MicrosoftIdentityError,
    MicrosoftPrincipal,
    build_msal_app,
    get_or_create_microsoft_user,
    validate_claims,
    verify_id_token,
)
from .models import User
from .services import issue_local_student


PREAUTH_USER_KEY = 'credential_change_user_id'
PREAUTH_HASH_KEY = 'credential_change_password_hash'
PREAUTH_TIME_KEY = 'credential_change_started_at'
PREAUTH_NEXT_KEY = 'credential_change_next'
PENDING_MICROSOFT_PRINCIPAL_KEY = 'pending_microsoft_principal'
PENDING_MICROSOFT_TIME_KEY = 'pending_microsoft_verified_at'
PENDING_MICROSOFT_NEXT_KEY = 'pending_microsoft_next'


def _safe_next(request, candidate=None):
    candidate = candidate or request.GET.get('next') or request.POST.get('next')
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse('courses:course_list')


def _clear_preauth(request):
    for key in (
        PREAUTH_USER_KEY, PREAUTH_HASH_KEY, PREAUTH_TIME_KEY, PREAUTH_NEXT_KEY,
    ):
        request.session.pop(key, None)


def login_view(request):
    """Local username/password login for administrator-issued accounts."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None and user.local_login_enabled:
            next_url = _safe_next(request)
            if user.must_change_credentials:
                if (
                    not user.initial_password_expires_at
                    or user.initial_password_expires_at <= timezone.now()
                ):
                    messages.error(
                        request,
                        'The initial password has expired. Ask an administrator for a new one.',
                    )
                    return render(request, 'accounts/login.html')
                logout(request)
                request.session.cycle_key()
                request.session[PREAUTH_USER_KEY] = user.pk
                request.session[PREAUTH_HASH_KEY] = user.password
                request.session[PREAUTH_TIME_KEY] = timezone.now().isoformat()
                request.session[PREAUTH_NEXT_KEY] = next_url
                return redirect('accounts:first_login_credentials')
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'accounts/login.html')


@require_POST
def logout_view(request):
    """User logout view."""
    logout(request)
    _clear_preauth(request)
    _clear_pending_microsoft_identity(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('accounts:login')


@require_POST
def microsoft_login(request):
    if not settings.MS_ENTRA_ENABLED:
        messages.error(request, 'Microsoft sign-in is not configured on this server.')
        return redirect('accounts:login')

    _clear_pending_microsoft_identity(request)
    try:
        flow = build_msal_app().initiate_auth_code_flow(
            scopes=[],
            redirect_uri=settings.MS_ENTRA_REDIRECT_URI,
            prompt='select_account',
        )
    except (MicrosoftIdentityError, MsalError, RequestException, RuntimeError, ValueError):
        messages.error(request, 'Microsoft sign-in could not be started.')
        return redirect('accounts:login')
    if 'auth_uri' not in flow:
        messages.error(request, 'Microsoft sign-in could not be started.')
        return redirect('accounts:login')

    request.session['microsoft_auth_flow'] = flow
    request.session['microsoft_next'] = _safe_next(request)
    return redirect(flow['auth_uri'])


def microsoft_callback(request):
    flow = request.session.pop('microsoft_auth_flow', None)
    next_url = request.session.pop('microsoft_next', None)
    if not flow:
        return render(
            request,
            'accounts/microsoft_error.html',
            {'message': 'This sign-in request is missing or has already been used.'},
            status=400,
        )

    try:
        result = build_msal_app().acquire_token_by_auth_code_flow(
            flow,
            request.GET.dict(),
        )
    except (MicrosoftIdentityError, MsalError, RequestException, RuntimeError, ValueError):
        result = {}
    id_token = result.get('id_token') if isinstance(result, dict) else None
    if not id_token:
        return render(
            request,
            'accounts/microsoft_error.html',
            {'message': 'Microsoft sign-in was cancelled or could not be verified.'},
            status=403,
        )

    try:
        claims = verify_id_token(id_token, flow.get('nonce'))
        principal = validate_claims(claims)
        user, _created = get_or_create_microsoft_user(principal, None)
    except MicrosoftIdentityError as exc:
        return render(
            request,
            'accounts/microsoft_error.html',
            {'message': str(exc)},
            status=403,
        )

    if user is None:
        request.session[PENDING_MICROSOFT_PRINCIPAL_KEY] = {
            'tenant_id': principal.tenant_id,
            'object_id': principal.object_id,
            'principal_name': principal.principal_name,
            'display_name': principal.display_name,
        }
        request.session[PENDING_MICROSOFT_TIME_KEY] = timezone.now().isoformat()
        request.session[PENDING_MICROSOFT_NEXT_KEY] = next_url
        return redirect('accounts:microsoft_role_selection')

    _clear_pending_microsoft_identity(request)
    login(request, user, backend='accounts.backends.EntraSessionBackend')
    if user.role == 'teacher' and not user.is_verified_teacher:
        return redirect('accounts:teacher_pending')
    return redirect(next_url if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ) else reverse('courses:course_list'))


def microsoft_role_selection(request):
    principal_data = request.session.get(PENDING_MICROSOFT_PRINCIPAL_KEY)
    verified_at_value = request.session.get(PENDING_MICROSOFT_TIME_KEY)
    if not principal_data or not verified_at_value:
        messages.error(request, 'Sign in with your school Microsoft account first.')
        return redirect('accounts:login')
    try:
        verified_at = timezone.datetime.fromisoformat(verified_at_value)
        principal = MicrosoftPrincipal(**principal_data)
    except (TypeError, ValueError):
        verified_at = None
    if not verified_at or timezone.now() - verified_at > timedelta(minutes=10):
        _clear_pending_microsoft_identity(request)
        messages.error(request, 'Your verified Microsoft session has expired. Sign in again.')
        return redirect('accounts:login')

    if request.method == 'POST':
        requested_role = request.POST.get('role')
        if requested_role not in {'student', 'teacher'}:
            messages.error(request, 'Choose either the Student or Teacher role.')
        else:
            next_url = request.session.get(PENDING_MICROSOFT_NEXT_KEY)
            try:
                try:
                    user, _created = get_or_create_microsoft_user(
                        principal,
                        requested_role,
                    )
                except IntegrityError:
                    user, _created = get_or_create_microsoft_user(
                        principal,
                        requested_role,
                    )
            except IntegrityError:
                return render(
                    request,
                    'accounts/microsoft_error.html',
                    {'message': 'This Microsoft account could not be registered. Please try again.'},
                    status=409,
                )
            except MicrosoftIdentityError as exc:
                return render(
                    request,
                    'accounts/microsoft_error.html',
                    {'message': str(exc)},
                    status=403,
                )

            _clear_pending_microsoft_identity(request)
            login(request, user, backend='accounts.backends.EntraSessionBackend')
            if user.role == 'teacher' and not user.is_verified_teacher:
                return redirect('accounts:teacher_pending')
            return redirect(next_url if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ) else reverse('courses:course_list'))

    return render(
        request,
        'accounts/microsoft_role_selection.html',
        {'principal': principal},
    )


def _clear_pending_microsoft_identity(request):
    for key in (
        PENDING_MICROSOFT_PRINCIPAL_KEY,
        PENDING_MICROSOFT_TIME_KEY,
        PENDING_MICROSOFT_NEXT_KEY,
    ):
        request.session.pop(key, None)


@login_required
def teacher_pending(request):
    if request.user.role != 'teacher' or request.user.is_verified_teacher:
        return redirect('courses:course_list')
    return render(request, 'accounts/teacher_pending.html')


def first_login_credentials(request):
    user_id = request.session.get(PREAUTH_USER_KEY)
    password_hash = request.session.get(PREAUTH_HASH_KEY)
    started_at = request.session.get(PREAUTH_TIME_KEY)
    if not all((user_id, password_hash, started_at)):
        messages.error(request, 'Sign in with the issued account before changing it.')
        return redirect('accounts:login')
    try:
        started = timezone.datetime.fromisoformat(started_at)
        user = User.objects.get(pk=user_id, is_active=True)
    except (ValueError, TypeError, User.DoesNotExist):
        _clear_preauth(request)
        return redirect('accounts:login')
    if (
        timezone.now() - started > timedelta(minutes=10)
        or not user.local_login_enabled
        or not user.must_change_credentials
        or not constant_time_compare(user.password, password_hash)
        or not user.initial_password_expires_at
        or user.initial_password_expires_at <= timezone.now()
    ):
        _clear_preauth(request)
        messages.error(request, 'This credential-change session is no longer valid.')
        return redirect('accounts:login')

    form = FirstLoginCredentialsForm(request.POST or None, user=user)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                locked_user = User.objects.select_for_update().get(pk=user.pk)
                if (
                    not locked_user.is_active
                    or not locked_user.local_login_enabled
                    or not locked_user.must_change_credentials
                    or timezone.now() - started > timedelta(minutes=10)
                    or not locked_user.initial_password_expires_at
                    or locked_user.initial_password_expires_at <= timezone.now()
                    or not constant_time_compare(locked_user.password, password_hash)
                ):
                    _clear_preauth(request)
                    messages.error(request, 'This credential-change session is no longer valid.')
                    return redirect('accounts:login')
                locked_user.username = form.cleaned_data['username']
                locked_user.set_password(form.cleaned_data['password1'])
                locked_user.must_change_credentials = False
                locked_user.initial_password_expires_at = None
                locked_user.password_changed_at = timezone.now()
                locked_user.save(update_fields=(
                    'username', 'password', 'must_change_credentials',
                    'initial_password_expires_at', 'password_changed_at',
                ))
        except IntegrityError:
            form.add_error('username', 'This username is already in use.')
            return render(
                request,
                'accounts/first_login_credentials.html',
                {'form': form},
                status=409,
            )
        next_url = request.session.get(PREAUTH_NEXT_KEY)
        _clear_preauth(request)
        login(request, locked_user, backend='accounts.backends.LocalAccountBackend')
        messages.success(request, 'Your username and password have been updated.')
        return redirect(next_url if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ) else reverse('courses:course_list'))

    return render(request, 'accounts/first_login_credentials.html', {'form': form})


def _admin_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_admin:
            return JsonResponse({'success': False, 'error': 'Administrator required.'}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapped


@_admin_required
def account_management(request):
    pending_teachers = User.objects.filter(
        role='teacher', is_verified_teacher=False, is_active=True,
    ).select_related('external_identity').order_by('created_at')
    return render(
        request,
        'accounts/account_management.html',
        {'pending_teachers': pending_teachers},
    )


@_admin_required
def create_local_student(request):
    form = LocalStudentCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user, initial_password = issue_local_student(
            creator=request.user,
            **form.cleaned_data,
        )
        response = render(
            request,
            'accounts/local_account_created.html',
            {'created_user': user, 'initial_password': initial_password},
        )
        response['Cache-Control'] = 'no-store'
        return response
    return render(request, 'accounts/create_local_student.html', {'form': form})


@_admin_required
@require_POST
def approve_teacher(request, user_id):
    teacher = get_object_or_404(User, pk=user_id, role='teacher', is_active=True)
    if not teacher.is_verified_teacher:
        teacher.is_verified_teacher = True
        teacher.teacher_reviewed_at = timezone.now()
        teacher.teacher_reviewed_by = request.user
        teacher.save(update_fields=(
            'is_verified_teacher', 'teacher_reviewed_at', 'teacher_reviewed_by',
        ))
    messages.success(request, f'{teacher.get_display_name} has been approved as a teacher.')
    return redirect('accounts:account_management')


@login_required
def profile_view(request, username=None):
    """View user profile."""
    if username:
        profile_user = get_object_or_404(User, username=username)
    else:
        profile_user = request.user

    # Check if viewing own profile
    is_own_profile = (request.user == profile_user)

    # Get favorite tags
    favorite_tags = profile_user.favorite_tags.all()

    # Get enrolled courses count (if student)
    enrolled_count = 0
    if profile_user.is_student:
        enrolled_count = profile_user.enrolled_courses.count()

    # Get created courses count (if teacher)
    created_count = 0
    if profile_user.is_teacher:
        created_count = profile_user.created_courses.filter(is_published=True).count()

    context = {
        'profile_user': profile_user,
        'is_own_profile': is_own_profile,
        'favorite_tags': favorite_tags,
        'enrolled_count': enrolled_count,
        'created_count': created_count,
    }

    return render(request, 'accounts/profile.html', context)


@login_required
def profile_edit(request):
    """Edit user profile."""
    if request.method == 'POST':
        user = request.user

        # Update basic info
        user.display_name = request.POST.get('display_name', '').strip()
        user.bio = request.POST.get('bio', '').strip()

        # Handle avatar upload using a decoded, sanitized raster image.
        if 'avatar' in request.FILES:
            avatar_file = request.FILES['avatar']
            try:
                avatar_file = validate_and_reencode_image(avatar_file)
            except ImageUploadValidationError as exc:
                messages.error(request, str(exc))
                return redirect('accounts:profile_edit')

            # Delete old avatar if exists
            if user.avatar:
                user.delete_old_avatar()

            # Save new avatar
            user.avatar = avatar_file

        user.save()
        messages.success(request, 'Profile updated successfully!')
        return redirect('accounts:profile')

    # GET request - show edit form
    all_tags = Tag.objects.all().order_by('category', 'name')
    user_favorite_tag_ids = list(request.user.favorite_tags.values_list('id', flat=True))

    context = {
        'all_tags': all_tags,
        'user_favorite_tag_ids': user_favorite_tag_ids,
    }

    return render(request, 'accounts/profile_edit.html', context)


@login_required
@require_POST
def update_favorite_tags(request):
    """AJAX endpoint to update user's favorite tags."""
    try:
        tag_ids = request.POST.getlist('tag_ids[]')

        # Clear existing favorite tags
        request.user.favorite_tags.clear()

        # Add selected tags
        if tag_ids:
            tags = Tag.objects.filter(id__in=tag_ids)
            request.user.favorite_tags.set(tags)

        return JsonResponse({
            'success': True,
            'message': 'Favorite tags updated successfully!'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)
