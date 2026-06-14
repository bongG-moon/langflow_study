# 샘플 질문과 기대 답변

아래 질문을 Langflow Playground의 Chat Input에 넣고 답변을 비교합니다.

## PDF RAG

파일: `sample_rag_handbook.pdf`

질문:

```text
RAG를 왜 문서 적재 flow와 사용자 질문 flow로 나눠야 해?
```

기대 답변:

문서 적재 flow는 upload, parse, chunk, embedding, Milvus upsert를 담당하고, 사용자 질문 flow는 Chat Input, query embedding, Milvus search, prompt, answer를 담당합니다. 분리하면 재색인과 사용자 응답을 따로 배포, 테스트, 모니터링할 수 있습니다.

## 이미지 기반 PDF / 멀티모달 실습

파일: `sample_visual_process_report.pdf`

질문:

```text
이미지가 있는 PDF에서 Read File OCR이 너무 오래 걸리거나 Job queue 오류가 나면 어떻게 읽어야 해?
```

기대 답변:

이미지 PDF는 PDF 전체를 `Read File + easyocr`로 오래 돌리기보다 `PDF Page Image Extractor`로 필요한 페이지만 PNG로 분리합니다. 생성된 PNG를 `Chat Input`의 Files에 첨부하거나 `Vision Message`를 vision-capable model에 연결해 page summary를 만든 뒤, 그 summary text와 page metadata를 Milvus/RAG에 저장합니다.

질문:

```text
2페이지 공정 흐름도에서 병목 후보와 조치 우선순위를 요약해줘.
```

기대 답변:

2페이지 공정 흐름도에서는 `검사 대기`가 평균 42분으로 가장 길어 병목 후보입니다. 재작업은 냉각 단계로 되돌아가는 루프를 만들며 처리 시간을 늘립니다. 우선 조치는 LOT-C-2409 중심으로 냉각수 유량 점검과 금형 조건 재승인입니다.

질문:

```text
3페이지 defect_rate 차트에서 가장 위험한 lot과 원인은 뭐야?
```

기대 답변:

3페이지 차트에서 `LOT-C-2409`가 `defect_rate=0.0323`으로 가장 위험합니다. 문서의 원인 설명은 `금형 냉각 편차`이며, LOT-C-2408과 LOT-C-2406도 0.028 이상이라 C라인 냉각/지그/금형 조건을 함께 점검해야 합니다.

## JSON FAQ

파일: `company_faq_rag.json`

질문:

```text
File Dataset Loader는 Read File 대신 언제 써?
```

기대 답변:

Read File은 PDF/DOCX/PPTX 같은 문서 추출용이고, File Dataset Loader는 CSV/JSON/JSONL/Markdown/Excel 데이터셋을 `row_count`, `columns`, `preview_rows`, `rows`, `warnings`가 있는 표준 Data payload로 정규화할 때 씁니다.

질문:

```text
Route Gate에서 선택되지 않은 branch는 어떻게 처리해야 해?
```

기대 답변:

선택되지 않은 branch는 `success=false`, `active=false`, `skipped=true`로 반환하고, downstream은 `active=true`이며 `skipped=false`인 branch만 처리해야 합니다.

## CSV 분석

파일: `quality_inspection_metrics.csv`

질문:

```text
defect_rate가 가장 높은 lot과 원인, 조치가 뭐야?
```

기대 답변:

`LOT-C-2409`가 `defect_rate=0.0323`으로 가장 높습니다. 원인은 `금형 냉각 편차`이고, 권장 조치는 `냉각수 유량 점검 후 금형 조건 재승인`입니다.

질문:

```text
라인별 평균 defect_rate를 비교하면 어디가 가장 위험해?
```

기대 답변:

C라인이 평균 defect_rate 약 `0.0272`로 가장 높습니다. A라인은 약 `0.0170`, B라인은 약 `0.0081`, D라인은 `0.0056` 수준입니다.

## JSONL 티켓

파일: `support_tickets.jsonl`

질문:

```text
현재 open 상태의 high priority 티켓은 무엇이고 해결 방향은 뭐야?
```

기대 답변:

open 상태의 high priority 티켓은 `TCK-2001`입니다. Milvus 적재 flow의 `ingest_data`는 생성되지만 runtime flow 검색 결과가 비어 있는 문제이며, `collection_name`과 embedding model 차원을 적재/runtime flow에서 동일하게 맞춰야 합니다.

## Milvus Payload

파일: `milvus_document_payload.json`

질문:

```text
Milvus record metadata에는 어떤 값들이 들어가야 해?
```

기대 답변:

metadata에는 `document_id`, `source_file`, `page`, `chunk_index`, `content_type`, `modalities`, `parse_mode`, `source_locator` 같은 값이 들어가야 합니다.
