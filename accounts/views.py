from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError
from .models import User


def register(request):
    """User registration view supporting both students and teachers."""
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        role = request.POST.get('role', 'student')

        # Validation
        if not all([username, email, password, password_confirm]):
            messages.error(request, 'All fields are required.')
            return render(request, 'accounts/register.html')

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

            # Print verification code (MVP placeholder)
            verification_code = f"{user.id:06d}"
            print(f"\n{'='*50}")
            print(f"VERIFICATION CODE for {email}: {verification_code}")
            print(f"{'='*50}\n")

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
