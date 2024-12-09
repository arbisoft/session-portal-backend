from django.urls import path
from users.v1.views import HelloWorldView

app_name = 'users'

urlpatterns = [
    path('hello/', HelloWorldView.as_view(), name='hello_world'),
]
