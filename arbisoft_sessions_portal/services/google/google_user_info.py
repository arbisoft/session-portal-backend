import requests

class GoogleUserInfoService:

    auth_token = None
    OAUTH_USERINFO_API_URL = "https://www.googleapis.com/oauth2/v1/userinfo"

    def __init__(self, auth_token):
        self.auth_token = auth_token

    def _get_request_headers(self):
        return {
            'Authorization': 'Bearer ' + self.auth_token
        }

    def get_user_info(self):
        try:
            response = requests.get(self.OAUTH_USERINFO_API_URL, headers=self._get_request_headers())
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            return None
