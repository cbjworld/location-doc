# 위치도 및 현장사진 자동생성 (Vercel 웹 버전)

## 배포 순서
1. 이 폴더를 GitHub 저장소에 올립니다.
2. https://vercel.com → Add New → Project → 저장소 Import (Framework: Other, 설정 변경 없음).
3. Settings → Environment Variables 에 추가:
   - `KAKAO_JS_KEY` : 카카오 JavaScript 키
   - `KAKAO_REST_KEY` : 카카오 REST API 키
4. Deploy. 완료되면 `https://프로젝트명.vercel.app` 주소가 생깁니다.
5. 카카오디벨로퍼스 → 앱 → 플랫폼 키 → JavaScript 키 → **JavaScript SDK 도메인**에
   `https://프로젝트명.vercel.app` 을 등록합니다. (커스텀 도메인을 쓰면 그것도 등록)
   REST 키의 "호출 허용 IP"는 비워두세요(Vercel은 IP가 고정이 아닙니다).
6. 환경변수를 바꾼 뒤에는 Redeploy 해야 반영됩니다.

CLI로 배포하려면: `npm i -g vercel && vercel --prod`

## 주의
- 접근 제한이 없습니다. 주소를 아는 누구나 사용할 수 있고 카카오 REST 호출 한도(무료 일일 쿼터)를 소진할 수 있습니다. 필요하면 나중에 비밀번호/사내 SSO를 붙이세요.
- 업로드한 사진과 지도 이미지가 외부 클라우드(Vercel 서버)를 거쳐 처리됩니다(저장은 하지 않음). 민감한 현장 사진·공공 자료라면 보안 정책을 먼저 확인하세요.
- Vercel 요청/응답 한도 4.5MB: 사진은 브라우저에서 1200px로 줄여 보내고, hwpx 안 이미지는 900px 폭으로 저장합니다.
- Hobby 플랜은 상업적 용도 불가 약관이 있습니다. 업무용이면 Pro 플랜을 확인하세요.

## 구조
- `api/index.py` : Flask 앱(/, /geocode, /generate)
- `hwpx_generator.py`, `template/` : hwpx 조립
- `templates/index.html` : 화면
- `vercel.json` : 모든 경로를 Flask로 연결, template 폴더 포함
