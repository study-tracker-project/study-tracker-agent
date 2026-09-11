# 빌드 전에 이 파일을 oauth_secret.py 로 복사하고 실제 값을 채운 뒤 pyinstaller를 실행하세요.
# oauth_secret.py는 .gitignore에 등록되어 있어 절대 커밋되지 않습니다.
# 값은 study-tracker-backend/web에서 쓴 것과 같은 Google OAuth "데스크톱 앱" 클라이언트입니다.

GOOGLE_OAUTH_CLIENT_ID = "여기에 클라이언트 ID"
GOOGLE_OAUTH_CLIENT_SECRET = "여기에 클라이언트 시크릿"
