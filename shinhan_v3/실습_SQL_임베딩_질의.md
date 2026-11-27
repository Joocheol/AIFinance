# 실습: 임베딩 → SQL로 묻기 → 더 복잡한 질의 (1일차 마무리)

**목표**: 글을 숫자로 바꾸는 **임베딩**이 무엇인지 손으로 확인하고, JPMorgan 상품 담당자가 되어 상품 라인업을 **SQL로** 분석한 뒤, **벡터로만** 할 수 있는 분석(특이 상품 찾기, 새 상품과 닮은 상품 찾기)을 해 봅니다.

| 순서 | 내용 | 시간 |
|---|---|---|
| A | Azure OpenAI 만들고 **벡터화 시작** (약 19분 걸리므로 먼저 시작해 두고 B·C 동안 돌린다) | 8분 |
| B | 임베딩이 무엇인가: TensorFlow Embedding Projector로 보기, 단어 계산, 문장 유사도 | 15분 |
| C | 상품군 분석: JPMorgan 상품 담당자로서 "무엇을 얼마나 팔았나" (SQL, 벡터 불필요) | 12분 |
| D | 벡터로만 할 수 있는 분석: 키워드 vs 뜻(3분), 특이 상품 찾기, 새 상품 설계안과 닮은 상품 찾기 | 18분 |
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
> **`InsufficientQuota` 오류가 나면**: 무료 계정은 Azure OpenAI를 **하나만** 가질 수 있고, 지운 계정도 48시간 동안 "삭제 대기"로 남아 그 자리를 차지합니다(예: 연습으로 만들었다 지운 계정). 휴지통을 확인하고 완전히 지운 뒤 위 명령을 다시 실행합니다.
> ```bash
> az cognitiveservices account list-deleted -o table
> az cognitiveservices account purge -l japaneast -g <그 계정의 리소스 그룹> -n <그 계정 이름>
> ```

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
- 직접 해 보기 (두 명령을 **따로** 실행. 한 줄에 같이 쓰면 `--near`만 실행됩니다):
  ```
  uv run jpm_kit/emb_1_words.py --calc tokyo japan france
  uv run jpm_kit/emb_1_words.py --near loan
  ```
  `--calc A B C` = A − B + C에 가장 가까운 단어 (tokyo − japan + france → paris). `--near 단어` = 그 단어와 가장 가까운 단어 6개 (loan → loans, debts, payments …). 다른 영어 단어로도 해 봅니다.

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

## C. 상품군 분석: 우리는 무엇을 얼마나 팔았나 (벡터화가 도는 동안)

**역할**: 여러분은 JPMorgan 구조화상품 담당자입니다. 공용 상품 DB(products, 2026년 1~10월 8,868개)로 우리 상품 라인업을 봅니다. 상품군 이름을 이미 알고 있으므로 **벡터가 필요 없습니다. SQL이면 됩니다.**

**공용 상품 DB 연결** — PostgreSQL 확장에 두 번째 연결: 서버 `jpm-shared-d32c.postgres.database.azure.com`, 사용자 `student_ro`, 비밀번호 `20261128`, 데이터베이스 `jpm` (교내 네트워크에서만).

**C-1. 내 손으로 SQL 두 개** (VS Code 쿼리 창, 5분)

| # | 질문 | 힌트 | 내 답 |
|---|---|---|---|
| 1 | 상품군(`product_type`)별 상품 수와 비중 | `count(*)`, `round(100.0 * count(*) / sum(count(*)) over (), 1)`, `group by 1 order by 2 desc` | |
| 2 | 조건부 쿠폰 상품의 기초자산 구조(`underlier_structure`)별 평균 연 쿠폰 — **분모(쿠폰이 있는 상품 수)도 함께** | `where product_type = 'contingent_income' and coupon_annual_pct is not null group by …` | |

막히면 Claude Code 패널에 *"이 질문을 SQL로 어떻게 쓰는지 설명만 해줘"* 라고 묻고, 받은 SQL을 읽고 이해한 뒤 실행합니다.

**C-2. Claude에게 상품군 지도 맡기기** (Claude Code 패널, 약 4분)
```
너는 JPMorgan 구조화상품 담당자다. 공용 상품 DB(products, 2026년 1~10월)로 "우리가 무엇을 얼마나 팔았나" 상품군 지도를 만들어줘.
1. 상품군(product_type)별 상품 수·비중·평균 만기·평균 연 쿠폰·발행가 대비 추정가치 차이(price_value_gap_pct) 평균·원금 합계. 평균마다 분모(값이 있는 상품 수)도.
2. 월별 상품 수와 상위 4개 상품군의 월별 추이.
3. 가장 많이 쓰인 기초자산(tickers) 10개.
4. 이 숫자로 말할 수 있는 것 3가지와, 이 데이터로는 말할 수 없는 것 2가지.
DB 연결은 jpm_kit/kit_db.py 의 connect("SHARED"). 짧은 코드는 jpm_kit/out/ 에 파일로 만들어 uv run 으로 실행하고, 쓴 SQL 을 모두 보여줘. .env 는 열지 마.
```

| 확인 | |
|---|---|
| Claude의 상품군별 상품 수가 내 C-1의 1번과 같은가 | |
| 평균 쿠폰·숨은 비용(gap)의 **분모**가 상품 수와 다른 상품군은? 왜 다른가 | |
| Claude가 꼽은 "이 데이터로는 말할 수 없는 것" 하나 | |

---

## D. 벡터로만 할 수 있는 분석 (벡터화가 끝난 뒤)

먼저 벡터화 결과를 적습니다 (`jpm_kit/out/embed_progress.txt` 마지막 줄).

| 벡터화 결과 | 내 값 |
|---|---|
| 청크 수 / 걸린 시간 / 토큰 / 비용 | |
| DB 크기 (전 → 후) | |

| | 키워드 검색 | 벡터 검색 |
|---|---|---|
| 찾는 기준 | 질문과 **같은 단어**가 들어 있는가 (`tsv` 키워드 색인) | 질문과 **뜻**이 가까운가 (`emb` 벡터의 코사인 거리) |
| 잘 찾는 것 | 공시 용어 그대로, 정확한 숫자, 고유명사 | 바꿔 말한 질문 (공시와 다른 말로 물어도) |
| 놓치는 것 | 질문의 단어가 한 문단에 모두 있어야 찾음 | 숫자만 다른 문장을 구별 못 함 (B의 10.75% vs 8.10%), 한국어로 막연히 물으면 자주 실패 |

**하이브리드**(`ask.py`의 세 번째 결과)는 두 결과의 **순위**를 합칩니다(RRF: 각 목록에서 r위면 `1 / (60 + r)` 점). 양쪽에 모두 오른 문단이 위로 올라오지만, 늘 이기지는 않습니다.

**D-1. 같은 뜻, 다른 말: ask.py로 3분**
```
uv run jpm_kit/ask.py "Can the bank end the investment early?" -k 3
uv run jpm_kit/ask.py "6.0% per annum daily deduction" -k 3
```

| 질문 | 키워드 1위 | 벡터 1위 |
|---|---|---|
| 고객의 말 (공시에 없는 표현) | | |
| 공시 표현 그대로 | | |

→ 첫 질문에서 키워드가 아무것도 못 찾는 이유: 키워드 검색은 질문의 **모든 단어**가 한 문단에 있어야 합니다(`'bank' & 'end' & 'invest' & 'earli'`). 벡터는 "Early redemption risk" 문단을 찾습니다. **벡터가 값을 하는 때는 묻는 말과 공시의 말이 다를 때**입니다. 아래 두 분석이 바로 그런 경우입니다: 무엇을 찾을지 **이름을 모르는** 분석.

**공시 한 건 = 벡터 하나**: 키트의 `jpm_kit/similar.py`는 공시마다 공통 문구가 아닌 청크 벡터의 **평균**을 내어 공시 1,859건을 벡터 1,859개로 만들고(처음 한 번 약 30초), 공시끼리 또는 새 설명과 코사인 유사도로 비교합니다.

**D-2. 우리가 판 상품 중 특이한 것이 있나** (약 5분)

먼저 직접 실행해 봅니다.
```
uv run jpm_kit/similar.py --outliers 5
```
그다음 Claude Code 패널에서:
```
너는 JPMorgan 구조화상품 담당자다. 10월에 우리가 낸 공시 중 특이한 상품이 있는지 보려고 한다.
1. uv run jpm_kit/similar.py --outliers 5 를 실행하고 결과를 표로 보여줘.
2. 그 5건이 어떤 상품인지 uv run jpm_kit/ask.py "<검색어>" --accession <번호> 로 원문을 찾아 확인하고, 왜 특이한지 한 줄씩 써줘.
   문서 양식(판매 채널)이 달라서인지, 상품 구조가 달라서인지 구분하고, 근거 [accession #chunk_id] 를 붙여.
.env 는 열지 마.
```

| 확인 | |
|---|---|
| 가장 닮은 다른 공시와 0.99 이상으로 닮은 공시 비율 → 무슨 뜻인가 | |
| 특이 5건 중 **상품 구조**가 특이한 것 / **문서 양식(판매 채널)** 이 달라서인 것 | / |
| 특이 5건 중 공용 상품 표에 없거나 분류 미확정인 것은 몇 건? 왜 그럴까 | |

**D-3. 새 상품을 설계했다: 기존 상품 중 무엇과 닮았나** (약 5분, Claude Code 패널)
```
너는 JPMorgan 구조화상품 담당자다. 새 상품을 설계했다:
"금과 비트코인 ETF를 같은 비중으로 담은 바스켓에 연동, 만기 5년, 원금 100% 보장, 바스켓 상승분의 80% 참여, 수익 상한 40%, 이자 없음."
1. 이 설명을 공시에서 쓰는 영어 문장 3~4개로 바꿔 보여줘.
2. 비교 기준으로 평범한 상품 설명(Nasdaq-100·Russell 2000 worst-of 자동조기상환 조건부 쿠폰)도 영어로 하나 써서,
   uv run jpm_kit/similar.py --text "<새 상품>" --text "<평범한 상품>" 을 실행해.
3. 새 상품과 가장 비슷한 공시 3건이 무엇 때문에 닮았고 무엇이 다른지 ask.py --accession 으로 원문을 확인해 표로. 특히 "원금 100% 보장"이 닮은 이유에 들어 있는지 봐.
4. 이 새 상품은 기존 상품의 변형인가, 새로운 구조인가? 근거와 함께 3줄로.
.env 는 열지 마.
```

| 확인 | |
|---|---|
| 새 상품 / 평범한 상품의 1위 유사도 | / |
| 새 상품과 가장 닮은 공시가 닮은 이유 (무엇이 같은가) | |
| "원금 100% 보장"이 닮은 이유에 들어갔나? 들어가지 않았다면 그것이 벡터에 대해 말해 주는 것은 | |

> 한국어 설명을 그대로 `--text`에 넣으면 영어 공시와 잘 비교되지 않습니다(리허설: 유사도 0.35). 그래서 Claude에게 먼저 영어 공시 문장으로 바꾸게 합니다.

## E. 1일차 정리 (5줄 메모)

1. 오늘 내 손으로 만든 것: SEC 원문 ___건 → 텍스트 ___건 → 내 DB의 표 ___개 (행 수)
2. 변환기가 바꾸지 **않는** 것 한 가지
3. 키워드 검색이 잘 찾는 질문 / 벡터 검색이 잘 찾는 질문
4. 벡터가 놓친 것 한 가지와 그 이유 (예: D-3의 원금 보장, B의 숫자)
5. 2일차에 확인하고 싶은 질문

> Azure 리소스(`jpm-course`)는 지우지 않습니다. 2일차에 그대로 씁니다.
