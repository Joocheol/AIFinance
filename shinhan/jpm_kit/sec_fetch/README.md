# 부록 — SEC에서 공시 원문을 직접 받기

SEC EDGAR는 누구나 받을 수 있지만, 자동 요청에는 규칙이 있습니다 (SEC "Accessing EDGAR Data").

1. **User-Agent에 연락처**: `회사 또는 이름 이메일` 형식. 연락처 없는 요청은 403으로 막힙니다.
   스크립트는 연락처를 코드에 쓰지 말고 환경변수 `SEC_USER_AGENT` 에서 읽습니다.
2. **초당 10건 이하**: 수업에서는 1건마다 1초 이상 쉽니다.
3. **403·429가 오면 즉시 중단**: 다시 두드리면 IP가 한동안 막힙니다. 강의실은 공인 IP 하나를 함께 쓰므로 한 사람의 실수가 모두를 막습니다.
4. **받은 시점과 SHA-256 해시를 함께 기록**: SEC는 HTML 끝에 봇 차단용 한 줄(`<script src="/random…">`)을 붙이고, 이 줄이 바뀌면 같은 공시라도 해시가 달라집니다.
   같은 날 받은 파일은 누구나 같은 해시, 10월에 받은 파일과는 다른 해시가 나옵니다. 그 한 줄을 지우고 비교하면 본문은 같습니다.

## 실행 (Desktop 터미널에서 직접)
- Windows: `powershell -ExecutionPolicy Bypass -File .\sec_fetch.ps1 <URL>`
  (Windows 기본 실행 정책은 Restricted라 그냥 실행하면 막힙니다. 이 명령은 그 파일 한 번만 허용합니다.)
- Mac: `sh sec_fetch.sh <URL>`
- 실행 전 터미널에서 연락처를 설정합니다. Windows `$env:SEC_USER_AGENT = "이름 이메일"`, Mac `export SEC_USER_AGENT="이름 이메일"`

## 예시 URL
`https://www.sec.gov/Archives/edgar/data/19617/000121390025125177/ea0270850-01_424b2.htm`
