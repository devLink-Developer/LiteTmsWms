from django.urls import path

from apps.authentication import api


urlpatterns = [
    path("api/session/", api.session_view, name="auth-session"),
    path("api/login/", api.login_view, name="auth-login"),
    path("api/logout/", api.logout_view, name="auth-logout"),
]
