from django.contrib.auth import get_user_model
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny


from users.v1.utils import get_google_user_info
user_model = get_user_model()

class RegisterUserView(generics.GenericAPIView):
    pass


class LoginUserView(APIView):
    pass


"""  
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
"""


class HelloWorldView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request):
        return Response("Hello World")



