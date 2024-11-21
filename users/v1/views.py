from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
# from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import authenticate
from rest_framework.permissions import AllowAny
from rest_framework.authtoken.models import Token
from users.serializers import  UserSerializer, RegisterUserSerializer, LoginUserSerializer
from users.models import User

# from users.v1.utils import get_google_user_info
# user_model = get_user_model()

class RegisterUserView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterUserSerializer


@method_decorator(csrf_exempt, name='dispatch')
class LoginUserView(APIView):
    serializer_class = LoginUserSerializer
    permission_classes = [AllowAny]

    def post(self, request: Request, *args, **kwargs):
        email = request.data.get('email')
        password = request.data.get('password')
        user = authenticate(username=email, password=password)  # Use `username` for Django's default User model
        if not user:
            return Response({'detail': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)
        user_serializer = UserSerializer(user)

        return Response({
            'token': str(refresh.access_token),
            'user': user_serializer.data
        }, status=status.HTTP_200_OK)



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



