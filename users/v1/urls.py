from django.urls import path
from users.v1.views import LoginUserView, HelloWorldView

urlpatterns = [
    path('login', LoginUserView.as_view(), name='login_user'),
    path('hello', HelloWorldView.as_view(), name='hello_world'),
]
