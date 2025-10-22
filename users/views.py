#pylint:disable=all
from django.views import View
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import CustomUser as User
from django.contrib.auth import authenticate, login, logout


class SignupView(View):
    """View for user registration."""

    def get(self, request):
        # Redirect to dashboard if already logged in
        next_url = request.GET.get("next", "")
        if request.user.is_authenticated:
            return redirect("dashboard")
        return render(
            request, "users/signup.html", {"next": next_url}
        )  # Render template with empty form

    def post(self, request):
        # Get form data
        username = request.POST.get("username")
        email = request.POST.get("email")
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        password1 = request.POST.get("password1")
        password2 = request.POST.get("password2")
        next_url = request.POST.get("next") or request.GET.get("next")

        # Validation
        if not username or not email or not password1 or not password2:
            messages.error(request, "All fields are required.")
            return render(request, "signup.html", {"next": next_url})

        if len(password1) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, "signup.html", {"next": next_url})

        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return render(request, "signup.html", {"next": next_url})

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username is already taken.")
            return render(request, "signup.html", {"next": next_url})

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email is already registered.")
            return render(request, "users/signup.html", {"next": next_url})

        # Create user
        user = User.objects.create_user(
            username=username, email=email, password=password1, first_name=first_name, last_name=last_name
        )
        login(request, user)  # Auto login after signup
        messages.success(request, "Signup successful!")
        if next_url and next_url not in ["/login/", "/signup/"]:
            return redirect(next_url)
        return redirect("dashboard")


class LoginView(View):
    """View for user login."""

    def get(self, request):
        # Redirect to dashboard if already logged in
        # In GET method - pass next to template
        next_url = request.GET.get("next", "")
        if request.user.is_authenticated:
            if next_url and next_url != "/login/":  # Avoid redirect loops
                return redirect(next_url)
            return redirect("dashboard")
        return render(
            request, "users/login.html", {"next": next_url}
        )  # Render the login page

    def post(self, request):
        # Get form data
        email = request.POST.get("email")
        password = request.POST.get("password")
        next_url = request.POST.get("next") or request.GET.get("next")

        # Validate input fields
        if not email or not password:
            messages.error(request, "All fields are required.")
            return render(request, "login.html")

        # Authenticate user
        user = authenticate(request, email=email, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, "Login successful!")
            if next_url and next_url != "/login/":  # Avoid redirect loops
                return redirect(next_url)
            return redirect("dashboard")  # Redirect to dashboard
        else:
            messages.error(request, "Invalid username or password.")
            return render(request, "users/login.html")
        
class LogoutView(View):
    """View for handling user logout."""

    def post(self, request):
        logout(request)  # Logs out the user
        return redirect("login")  # Redirect to login page