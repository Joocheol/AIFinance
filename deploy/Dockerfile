# 신한은행 수업용 원격 MCP 서버 이미지
#   빌드: GitHub Actions (.github/workflows/course-image.yml) — DB 파일은 릴리스 자산에서 받는다
#   실행: 포트 8000, 엔드포인트 /mcp, 상태 확인 /healthz
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    FASTEMBED_CACHE_PATH=/app/models \
    PORT=8000 \
    MAX_ROWS=50 \
    RATE_LIMIT_PER_MIN=120

WORKDIR /app

# 서버에 필요한 패키지만 (노트북·Jupyter 제외). DB 파일 형식 때문에 duckdb 버전은 로컬과 같게 고정
RUN pip install --no-cache-dir \
    "duckdb==2.0.0" "fastembed==0.9.1" "mcp==2.3.0" "uvicorn==0.54.0" "starlette==1.10.0" \
    "pandas==3.1.1" "numpy==2.5.4" "pydantic==2.14.3" "tabulate==0.10.0" \
    "python-dotenv==1.2.4" "requests==2.34.2" "beautifulsoup4==4.15.0" "lxml==6.1.3" "tqdm==4.70.1"

# DuckDB 전문 검색 확장과 임베딩 모델을 이미지에 미리 넣는다 (실행 시 다운로드·지연 없음)
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL fts')"
COPY src/aifinance ./src/aifinance
RUN python -c "from aifinance.rag import embed; embed(['warm up'], 'minishlab/potion-retrieval-32M')"

ARG DB_URL
ADD ${DB_URL} /app/data/shinhan_jpm.duckdb

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["python", "-m", "aifinance.course_server"]
