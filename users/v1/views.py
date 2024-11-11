from django.contrib.auth import get_user_model
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken

from users.v1.utils import get_google_user_info

user_model = get_user_model()

class LoginUserView(APIView):

    permission_classes = []

    def post(self, request):
        token = request.POST.get('token')
        user_info = get_google_user_info(token)
        user = user_model.objects.filter(email=user_info['email']).first()
        if not user:
            raise ValidationError
        refresh = RefreshToken.for_user(user)

        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        })


class HelloWorldView(APIView):

    def get(self, request):
        return Response("Hello World")
