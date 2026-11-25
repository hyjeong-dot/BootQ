"""FastAPI 조립 (02_BACKEND.md 1장). #13에서는 Compose의 API 컨테이너가 뜨는지만 확인하는 빈 앱이다.
엔드포인트(글 등록·SSE·피드백·어휘 재로드)는 #14에서 routers/로 추가한다. 기동 확인은 /docs."""
from fastapi import FastAPI

app = FastAPI(title='BootQ', summary='커뮤니티 고민 글 → 직무 부트캠프 추천')
