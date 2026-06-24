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
이미지가 있는 PDF에서 Read File 결과가 비어 있거나 처리가 오래 걸리면 어떻게 읽어야 해?
```

기대 답변:

이미지 PDF는 `Read File`에서 텍스트가 나오지 않는 경우가 많으므로 `PDF Page Image Extractor`로 필요한 페이지만 PNG로 분리합니다. 생성된 PNG를 `Chat Input`의 Files에 첨부하거나 `Vision Message`를 vision-capable model에 연결해 page summary를 만든 뒤, 그 summary text와 page metadata를 Milvus/RAG에 저장합니다.

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

질문:

```text
route 값이 data_retrieval, document_rag, final_answer일 때 각각 어떤 흐름으로 가야 해?
```

기대 답변:

`data_retrieval`은 API/DB/CSV 같은 정형 데이터 조회 branch로 보내고, `document_rag`는 Milvus 또는 Vector Store 기반 문서 검색 branch로 보냅니다. `final_answer`는 추가 조회 없이 final prompt 또는 질문 보정 답변 branch로 보냅니다. 처음 실습에서는 세 output을 각각 Chat Output에 연결해 `active=true`와 `skipped=true` payload를 먼저 확인합니다.

질문:

```text
MCP로 웹 페이지를 읽고 메일 초안을 만드는 flow는 어떻게 연결해?
```

기대 답변:

외부 web fetch MCP server와 mail MCP server를 `Settings > MCP Servers` 또는 MCP sidebar에서 등록한 뒤, 각각 `MCP Tools` component로 canvas에 추가합니다. 두 `MCP Tools`의 `Toolset` output을 Agent의 `Tools` input에 연결하고, `Chat Input`은 Agent input에, Agent output은 `Chat Output`에 연결합니다. 교육 단계에서는 실제 발송보다 `create_draft` 또는 `preview_email` tool을 사용하고, 사용자가 승인하기 전에는 `send_email`을 호출하지 않습니다. 만든 flow를 외부 client가 쓰게 하려면 Project의 `MCP Server` 화면에서 해당 flow를 tool로 노출하고 이름/설명을 명확히 수정합니다.

질문:

```text
Langflow에서 만든 사내 FAQ flow를 MCP tool로 공개하고 다른 flow에서 쓰려면 어떻게 해?
```

기대 답변:

먼저 Producer flow를 `Chat Input -> Retriever/File Dataset Loader -> Prompt Template -> Language Model -> Chat Output`처럼 만들고 단독 Playground에서 답변을 확인합니다. flow를 MCP tool로 공개하려면 `Chat Output`이 필요합니다. 그 다음 Project의 `MCP Server` tab 또는 `Share -> MCP Server`에서 `Edit Tools`를 열고 해당 flow만 선택한 뒤 tool name을 `company_faq_answer`처럼 명확히 바꿉니다. Consumer flow에서는 Producer project MCP endpoint를 `HTTP/SSE` MCP server로 등록하고, `MCP Tools.Toolset`을 Agent의 `Tools` input에 연결합니다. 이후 사용자 질문이 FAQ/RAG 성격이면 Agent가 `company_faq_answer` tool을 호출해 답변합니다.

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
