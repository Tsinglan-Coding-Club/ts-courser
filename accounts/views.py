from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError
from django.http import JsonResponse
from django.core.files.storage import default_storage
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import timedelta
from .models import User
from courses.models import Tag
import os
import random
import string


def generate_verification_code():
    """Generate a 6-digit verification code."""
    return ''.join(random.choices(string.digits, k=6))


@require_POST
def send_verification_code(request):
    """Send verification code to email (MVP: print to console)."""
    email = request.POST.get('email')

    if not email:
        return JsonResponse({'success': False, 'error': 'Email is required'})

    # Check if email already exists
    if User.objects.filter(email=email).exists():
        return JsonResponse({'success': False, 'error': 'Email already registered'})

    # Generate verification code
    code = generate_verification_code()

    # Store code in session (temporary storage for MVP)
    request.session['verification_code'] = code
    request.session['verification_email'] = email
    request.session['code_sent_at'] = timezone.now().isoformat()

    # MVP: Print to console (replace with email sending in production)
    print(f"\n{'='*50}")
    print(f"VERIFICATION CODE for {email}: {code}")
    print(f"Code expires in 10 minutes")
    print(f"{'='*50}\n")

    return JsonResponse({
        'success': True,
        'message': 'Verification code sent! (Check console in MVP mode)'
    })


def register(request):
    """User registration view with email verification code."""
    if request.method == 'POST':
        # Get form data
        email = request.POST.get('email')
        verification_code = request.POST.get('verification_code')
        username = request.POST.get('username')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        role = request.POST.get('role', 'student')

        # Validation
        if not all([email, verification_code, username, password, password_confirm]):
            messages.error(request, 'All fields are required.')
            return render(request, 'accounts/register.html')

        # Verify email matches session
        session_email = request.session.get('verification_email')
        if not session_email or session_email != email:
            messages.error(request, 'Email verification required. Please request a new code.')
            return render(request, 'accounts/register.html')

        # Verify code matches and hasn't expired
        session_code = request.session.get('verification_code')
        code_sent_at = request.session.get('code_sent_at')

        if not session_code or session_code != verification_code:
            messages.error(request, 'Invalid verification code.')
            return render(request, 'accounts/register.html')

        # Check code expiration (10 minutes)
        if code_sent_at:
            sent_time = timezone.datetime.fromisoformat(code_sent_at)
            if timezone.now() - sent_time > timedelta(minutes=10):
                messages.error(request, 'Verification code expired. Please request a new one.')
                # Clear session
                request.session.pop('verification_code', None)
                request.session.pop('verification_email', None)
                request.session.pop('code_sent_at', None)
                return render(request, 'accounts/register.html')

        # Validate passwords
        if password != password_confirm:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'accounts/register.html')

        try:
            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                role=role
            )
            user.is_email_verified = True
            user.save()

            # Clear session
            request.session.pop('verification_code', None)
            request.session.pop('verification_email', None)
            request.session.pop('code_sent_at', None)

            if role == 'teacher':
                messages.success(
                    request,
                    'Teacher account created! Please wait for admin verification.'
                )
            else:
                messages.success(request, 'Account created successfully!')

            # Auto-login after registration
            login(request, user)
            return redirect('courses:course_list')

        except IntegrityError:
            messages.error(request, 'Username or email already exists.')
            return render(request, 'accounts/register.html')

    return render(request, 'accounts/register.html')


def login_view(request):
    """User login view."""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')

            # Redirect based on role
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('courses:course_list')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'accounts/login.html')


@login_required
def logout_view(request):
    """User logout view."""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('accounts:login')


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

        # Handle avatar upload
        if 'avatar' in request.FILES:
            avatar_file = request.FILES['avatar']

            # Validate file size (2MB max)
            if avatar_file.size > 2 * 1024 * 1024:
                messages.error(request, 'Avatar file size must be less than 2MB.')
                return redirect('accounts:profile_edit')

            # Validate file type
            allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
            if avatar_file.content_type not in allowed_types:
                messages.error(request, 'Avatar must be a valid image file (JPEG, PNG, GIF, or WebP).')
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
