# 실습: 임베딩 → SQL로 묻기 → 더 복잡한 질의 (1일차 마무리)

**목표**: 글을 숫자로 바꾸는 **임베딩**이 무엇인지 손으로 확인하고, 내 DB(10월 공시 원문)와 공용 상품 DB에 **SQL로 직접** 물은 뒤, 키워드·뜻·상품 조건을 섞은 질의까지 해 봅니다.

| 순서 | 내용 | 시간 |
|---|---|---|
| A | Azure OpenAI 만들고 **벡터화 시작** (약 15분 걸리므로 먼저 시작해 두고 B·C 동안 돌린다) | 8분 |
| B | 임베딩이 무엇인가: TensorFlow Embedding Projector로 보기, 단어 계산, 문장 유사도 | 15분 |
| C | SQL 연습: 내 DB와 공용 상품 DB (6문제) | 15분 |
| D | 더 복잡한 질의: 키워드 vs 뜻, 한국어 질문, 두 DB 잇기 (벡터화가 끝난 뒤) | 15분 |
| E | 1일차 정리 | 5분 |

---

## A. Azure OpenAI 만들고 벡터화 시작

VS Code 터미널 (리소스 그룹 `jpm-course`, 이름은 `jpm-aoai-<이니셜>-<숫자>`):
```bash
az cognitiveservices account create -g jpm-course -n jpm-aoai-<이니셜>-<숫자> -l japaneast \
  --kind OpenAI --sku S0 --custom-domain jpm-aoai-<이니셜>-<숫자> --yes
az cognitiveservices account deployment create -g jpm-course -n jpm-aoai-<이니셜>-<숫자> \
  --deployment-name emb3s --model-name text-embedding-3-small --model-version 1 --model-format OpenAI \
  --sku-name GlobalStandard --sku-capacity 1000
```
`.env`에 `AOAI_ENDPOINT=https://jpm-aoai-<이니셜>-<숫자>.openai.azure.com/` 와 `AOAI_KEY`(포털 → 이 리소스 → **키 및 엔드포인트** → 키 1)를 **직접** 적습니다.

```
uv run jpm_kit/embed.py --try 3
```
청크 3개가 각각 **숫자 1,536개**로 바뀌는 것을 봅니다. 그다음 Claude Code 패널:
```
jpm_kit/embed.py 를 백그라운드로 실행하고, jpm_kit/out/embed_progress.txt 로 진행 상황을 알려줘.
```

---

## B. 임베딩이 무엇인가 (벡터화가 도는 동안)

**한 줄 정의**: 글(단어·문장·문단)을 **숫자 목록(벡터)** 으로 바꾸는 것. 뜻이 비슷한 글은 비슷한 숫자 목록이 되도록 학습되어 있어서, **숫자끼리의 거리로 뜻이 얼마나 가까운지** 잴 수 있습니다.

| 말 | 뜻 |
|---|---|
| 벡터 | 숫자 목록. 단어 벡터는 200개, 오늘 쓰는 문장 임베딩은 1,536개 |
| 차원 | 숫자의 개수. 숫자 하나하나에는 사람이 읽을 뜻이 없다 |
| 코사인 유사도 | 두 벡터의 방향이 얼마나 같은가. 1이면 같은 방향(뜻이 가까움), 0이면 무관 |
| 벡터 검색 | 질문도 같은 모델로 벡터로 바꾼 뒤, 가장 가까운 청크를 찾는 것 |

**⓪ 눈으로 보기: TensorFlow Embedding Projector** (브라우저, 5분)

구글 TensorFlow 팀이 공개한 임베딩 시각화 도구입니다. 위키백과 글로 학습한 단어 1만 개의 벡터(단어마다 숫자 200개)를 3차원으로 눌러 점으로 보여 줍니다.

1. [projector.tensorflow.org](https://projector.tensorflow.org) 를 엽니다. 왼쪽 위 데이터가 **Word2Vec 10K** 인지 확인합니다(기본값).
2. 오른쪽 **Search** 칸에 `bank` → 아래 목록에서 **bank 를 클릭** → 오른쪽에 **Nearest points in the original space**(숫자 200개 공간에서 가장 가까운 단어)와 거리가 나옵니다.
   이 숫자는 **코사인 거리**라 **작을수록 가깝습니다**(① 스크립트가 보여 주는 **유사도**는 클수록 가까움).
3. **Isolate 101 points** 를 눌러 이웃만 남기고, 점 구름을 마우스로 돌려 봅니다. `dollar`, `bond`, `risk` 도 찾아봅니다.
4. 왼쪽 아래 투영 방법을 **PCA → T-SNE** 로 바꿔, 비슷한 단어끼리 무리 짓는 모습을 봅니다.

| 확인 | 내 값 |
|---|---|
| `bank` 의 가장 가까운 단어 5개 | |
| `bank` 이웃 중 금융이 아닌 단어 (어떤 뜻의 bank?) | |
| `bond` 의 가장 가까운 단어 3개 (채권 뜻인가?) | |

> `bank` 이웃에는 banks·monetary·imf 같은 금융 단어 사이에 river·thames·canal(강둑), gaza·west·strip(요르단강 서안 West Bank)이 섞여 나옵니다. 단어 하나에 숫자 묶음이 하나뿐이라 뜻이 섞인 것입니다 → ②에서 문장 임베딩이 이것을 어떻게 푸는지 봅니다.

**① 같은 자료로 계산하기: 단어 계산** (AI 호출 없음, 내 노트북에서 numpy로)

⓪에서 본 **바로 그 Word2Vec 10K 자료**(TensorFlow Embedding Projector 공개 파일, 약 8MB)를 내려받아 직접 계산합니다. 핵심은 아래 몇 줄입니다.
```python
idx = {word: i for i, word in enumerate(words)}          # 단어 → 행 번호
q = V[idx["king"]] - V[idx["man"]] + V[idx["woman"]]     # 벡터 산술
scores = (V @ q) / (np.linalg.norm(V, axis=1) * np.linalg.norm(q))   # 모든 단어와 코사인 유사도
# scores 가 가장 큰 단어 = 답 (식에 쓴 세 단어는 뺀다)
```
```
uv run jpm_kit/emb_1_words.py
```
- 가까운 단어: `dollar → currency, usd, franc …` (⓪의 목록과 비교해 보기)
- **단어 계산**: `king − man + woman = queen`, `paris − france + japan = tokyo` → 관계가 **방향**으로 들어 있다
- **한계**: `bond`의 이웃이 hydrogen, molecule(화학 결합). `bank`는 loan(0.50)보다 river(0.56, 강둑)에 가깝다 → 단어 하나에 숫자 묶음이 하나뿐이라 뜻이 섞인다
- `jpm_kit/out/word_map.png`: 200개 숫자를 2차원으로 눌러 본 지도
- `jpm_kit/out/king_queen.png`: **왕·여왕·남자·여자 그림.** 가로축 = 남자→여자 방향(woman − man), 세로축 = 보통 사람→왕족 방향. man→woman 화살표와 **king→queen 화살표가 같은 쪽(오른쪽)** 을 향합니다. 그래서 king에서 man을 빼고 woman을 더하면 queen 근처에 닿습니다. prince→princess, boy→girl, father→mother도 같은 쪽입니다. 같은 쪽을 향하지 않는 쌍(husband→wife)도 찾아 왜 그럴지 생각해 봅니다.
  > Projector에서 같은 그림을 보려면: 왼쪽 아래 **CUSTOM** → 네 칸 오른쪽의 `.*` 버튼을 눌러 켠 뒤 Left `^man$`, Right `^woman$`, Up `^(king|queen)$`, Down `^(man|woman)$` (강사 시연)
- 직접 해 보기: `uv run jpm_kit/emb_1_words.py --calc tokyo japan france`, `--near loan`

**② 문장을 숫자로** (내 Azure OpenAI, 1원도 안 듦)
```
uv run jpm_kit/emb_2_sentences.py
```

| 확인 | 내 값 |
|---|---|
| 같은 bond: 채권 문장끼리 vs 채권–화학 문장 | / |
| 한국어 질문과 가장 가까운 영어 공시 문장 | |
| 금리만 다른 두 문장(10.75% vs 8.10%)의 유사도 | |

→ **문맥**이 뜻을 정한다(단어 벡터의 한계를 넘음). **언어가 달라도** 뜻이 같으면 가깝다. 대신 **정확한 숫자는 거의 구별하지 못한다** → 그래서 키워드 검색과 합친다.
내 문장으로: `uv run jpm_kit/emb_2_sentences.py "원금 보장" "principal protected" "capital at risk"`

> 벡터화는 계속 돌고 있습니다. C(SQL)를 마칠 무렵 끝납니다. 결과는 D 전에 적습니다.

---

## C. SQL 연습 (벡터화가 도는 동안)

VS Code 왼쪽 **PostgreSQL** → 내 서버 연결 → `postgres` 데이터베이스 → 새 쿼리. 문제마다 SQL을 **직접** 써 봅니다. 막히면 Claude Code 패널에 *"이 질문을 SQL로 어떻게 쓰는지 설명만 해줘"* 라고 묻고, 받은 SQL을 읽고 이해한 뒤 실행합니다.

**내 DB (filings, chunks)**

| # | 질문 | 힌트 | 내 답 |
|---|---|---|---|
| 1 | 10월 공시는 몇 건, 글자 수 합계·평균은? | `count`, `sum`, `avg` | |
| 2 | 가장 짧은 공시 5건의 accession과 앞 200자. 어떤 종류의 공시인가? | `order by chars limit 5`, `left(body, 200)` | |
| 3 | "MerQube" 가 나오는 공시는 몇 건? (같은 공시를 두 번 세지 않게) | `count(distinct accession)`, `body ilike '%merqube%'` | |
| 4 | 키워드 색인으로 `daily deduction` 이 들어간 청크 수. 앞에 `explain analyze` 를 붙여 3번(ilike)과 속도를 비교하면? | `tsv @@ plainto_tsquery('english', 'daily deduction')` | |

**공용 상품 DB (products, 읽기 전용)** — PostgreSQL 확장에 두 번째 연결: 서버 `jpm-shared-d32c.postgres.database.azure.com`, 사용자 `student_ro`, 비밀번호 `20261128`, 데이터베이스 `jpm` (교내 네트워크에서만).

| # | 질문 | 힌트 | 내 답 |
|---|---|---|---|
| 5 | 상품 수, 원금이 확인된 상품 수, 원금 합계 | `count(principal)`은 빈칸을 세지 않는다 | |
| 6 | 조건부 쿠폰 상품의 기초자산 구조(`underlier_structure`)별 평균 연 쿠폰 — **분모(쿠폰이 있는 상품 수)도 함께** | `where product_type = 'contingent_income' and coupon_annual_pct is not null group by …` | |

> 6번에서 "단일 기초자산의 쿠폰이 더 높다"가 나오면, 2일차에 그 이유(기초자산 구성)를 따져 봅니다. 지금은 숫자와 분모만.

---

## D. 더 복잡한 질의 (벡터화가 끝난 뒤)

먼저 벡터화 결과를 적습니다 (`jpm_kit/out/embed_progress.txt` 마지막 줄).

| 벡터화 결과 | 내 값 |
|---|---|
| 청크 수 / 걸린 시간 / 토큰 / 비용 | |
| DB 크기 (전 → 후) | |

**세 가지 검색: 키워드, 벡터, 하이브리드**

| | 키워드 검색 | 벡터 검색 |
|---|---|---|
| 찾는 기준 | 질문과 **같은 단어**가 들어 있는가 (`tsv` 키워드 색인) | 질문과 **뜻**이 가까운가 (`emb` 벡터의 코사인 거리) |
| 잘 찾는 것 | 공시 용어 그대로, 정확한 숫자, 고유명사 | 바꿔 말한 질문, 한국어 질문 |
| 놓치는 것 | 단어가 안 겹치면 못 찾음 (한국어 질문은 결과 없음) | 숫자만 다른 문장을 구별 못 함 (B의 10.75% vs 8.10%: 0.94) |

**하이브리드**는 두 결과를 합칩니다. 키워드 점수와 벡터 거리는 단위가 달라 그대로 더할 수 없으므로 **순위**를 더합니다(순위 융합, RRF).
1. 키워드 상위 50개, 벡터 상위 50개를 뽑는다.
2. 각 목록에서 r위인 문단에 `1 / (60 + r)` 점 (1위 1/61, 2위 1/62 …).
3. 두 목록의 점수를 더해 다시 줄 세운다 → **양쪽에 모두 오른 문단**이 위로 올라온다.

두 방식이 맞히는 질문이 서로 달라서 합치면 대체로 낫습니다(9월 리허설, 영어 질문 20개의 상위 5개 정답률: 키워드 55%, 벡터 70%, 하이브리드 80%). 그러나 **질문마다 늘 이기지는 않습니다**: 한쪽 1위가 엉뚱하면 합친 순위에서도 1위가 될 수 있습니다. 그래서 결과를 원문으로 확인합니다.

**D-1. 같은 질문, 세 가지 검색**
```
uv run jpm_kit/ask.py "6.0% per annum daily deduction"
uv run jpm_kit/ask.py "지수 수준에서 매년 6%를 일별로 차감하는 것의 영향"
uv run jpm_kit/ask.py "지수에서 매일 빠지는 비용은 얼마인가" --sql
```

정답 문단: 지수에서 **연 6.0%를 매일 나누어 차감**한다는 위험 고지 (“6.0% per annum daily deduction”).

| 질문 | 키워드 1위가 맞나 | 벡터 1위가 맞나 | 하이브리드 1위가 맞나 |
|---|---|---|---|
| 공시 표현 그대로 (영어) | | | |
| 한국어, 공시의 개념으로 ("매년 6%를 일별로 차감") | | | |
| 한국어, 막연하게 ("매일 빠지는 비용") | | | |

→ 세 번째 질문이 실패하면, Claude에게 *"이 질문을 영어 공시에서 쓰는 용어로 바꾼 검색어 3개를 만들어줘"* 라고 한 뒤 그 검색어로 다시 찾아봅니다. 벡터 검색도 질문이 막연하면 못 찾습니다.

**D-2. SQL만으로 "이 문단과 비슷한 문단"** (VS Code 쿼리 창: 질문을 벡터로 바꿀 필요 없이 이미 있는 청크의 벡터를 씀)
```sql
-- 먼저 기준 청크 하나를 고른다 (예: D-1에서 찾은 chunk_id)
select c.accession, c.chunk_id, round((1 - (c.emb <=> b.emb))::numeric, 3) as 유사도, left(c.body, 150)
from chunks c, (select emb from chunks where chunk_id = <기준 chunk_id>) b
where c.chunk_id <> <기준 chunk_id>
order by c.emb <=> b.emb
limit 10;
```
→ 같은 위험 고지가 다른 공시에 어떻게 반복되는지, 표현이 조금씩 다른 문단도 같이 나오는지 봅니다.

**D-3. 두 DB 잇기: 상품 조건(공용 DB) + 원문 근거(내 DB)** — Claude Code 패널
```
공용 상품 DB(.env 의 SHARED_…)에서 2026년 10월에 제출된 조건부 쿠폰 상품 중 연 쿠폰이 가장 높은 5개를 고르고
(cusip, accession, 기초자산, 연 쿠폰, 원금 손실 배리어),
내 DB(PG…)에서 그 accession 의 청크만 대상으로 jpm_kit/ask.py 방식의 하이브리드 검색을 해서
"원금 손실 조건" 문단을 하나씩 찾아 표로 보여줘. 쓰는 SQL 을 모두 보여주고, .env 는 열지 마.
```

| 확인 | |
|---|---|
| 상품 표의 배리어 값과 원문 문단의 숫자가 같은가? 다른 상품이 있으면 적기 | |
| 두 DB를 SQL 하나로 join 하지 못한 이유는? Claude는 어떻게 이었나? | |

## E. 1일차 정리 (5줄 메모)

1. 오늘 내 손으로 만든 것: SEC 원문 ___건 → 텍스트 ___건 → 내 DB의 표 ___개 (행 수)
2. 변환기가 바꾸지 **않는** 것 한 가지
3. 키워드 검색이 잘 찾는 질문 / 벡터 검색이 잘 찾는 질문
4. 임베딩이 약한 것 한 가지와 그 이유
5. 2일차에 확인하고 싶은 질문

> Azure 리소스(`jpm-course`)는 지우지 않습니다. 2일차에 그대로 씁니다.
