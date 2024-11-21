from django.urls import path
from users.v1.views import HelloWorldView, LoginUserView, RegisterUserView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView
)

app_name = 'users'

urlpatterns = [
    path('register/', RegisterUserView.as_view(), name='register_user'),
    path('login/', LoginUserView.as_view(), name='login_user'),
    path('jwt/create/', TokenObtainPairView.as_view(), name='jwt_create'),
    path('jwt/refresh/', TokenRefreshView.as_view(), name='jwt_refresh'),
    path('jwt/verify/', TokenVerifyView.as_view(), name='jwt_verify'),
    path('hello/', HelloWorldView.as_view(), name='hello_world'),
]
