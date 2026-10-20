from django.urls import path

from users.v1.views import CurrentUserView, LoginUserView, LoginWithEmailView, UserSearchView

urlpatterns = [
    path('login', LoginUserView.as_view(), name='login_user'),
    path('login/email', LoginWithEmailView.as_view(), name='login_with_email'),
    path('search/', UserSearchView.as_view(), name='user-search'),
    path('me/', CurrentUserView.as_view(), name='current_user'),
]
