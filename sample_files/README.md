# Langflow Q&A 실습용 샘플 파일

이 폴더의 샘플은 단순 업로드 테스트가 아니라, 실제로 질문을 던졌을 때 답변까지 확인할 수 있도록 구성했습니다.

## 먼저 해볼 것

1. `sample_rag_handbook.pdf`를 `Read File`에 업로드합니다.
2. `Read File` 노드의 실행 버튼을 누르고 Inspect Output에서 text/markdown이 나오는지 먼저 확인합니다.
3. 텍스트 PDF에서 내용이 비어 있으면 PDF 뷰어에서 글자가 드래그/복사되는지 먼저 확인합니다. 복사가 안 되면 이미지/스캔 PDF입니다.
4. 이미지/스캔 PDF는 `Read File`에서 계속 재시도하지 말고 `PDF Page Image Extractor`로 필요한 page만 PNG로 분리합니다.
5. 생성된 PNG를 `Chat Input`의 Files에 첨부하거나, `PDF Page Image Extractor.Vision Message`를 vision-capable model에 연결해 page summary를 만듭니다.
6. 그 다음 `Read File -> Split Text -> Embedding -> Milvus` 또는 `page image summary -> Multimodal Milvus Chunk Builder -> Milvus` 적재 flow를 구성합니다.
7. 사용자 질문 flow에서 Chat Input에 아래 질문을 넣고 답변을 확인합니다.

예상 질문:

- `RAG를 왜 문서 적재 flow와 사용자 질문 flow로 나눠야 해?`
- `2페이지 공정 흐름도에서 병목 후보와 조치 우선순위를 요약해줘.`
- `3페이지 defect_rate 차트에서 가장 위험한 lot과 원인은 뭐야?`
- `File Dataset Loader는 Read File 대신 언제 쓰는 컴포넌트야?`
- `Milvus 적재 payload에는 어떤 필드가 들어가야 해?`
- `MCP로 웹 페이지를 읽고 메일 초안을 만드는 flow는 어떻게 연결해?`
- `Langflow에서 만든 사내 FAQ flow를 MCP tool로 공개하고 다른 flow에서 쓰려면 어떻게 해?`

## 파일별 용도

| 파일 | 주 용도 | 연결 위치 |
| --- | --- | --- |
| `sample_rag_handbook.pdf` | PDF 기반 RAG 질문 답변 | `Read File` |
| `sample_visual_process_report.pdf` | 이미지/OCR/vision, 멀티모달 RAG, 문서 추출 실습 | `PDF Page Image Extractor`, `Chat Input.Files`, `Multimodal Milvus Chunk Builder` |
| `visual_process_report_pages_from_pdf/*.png` | PDF에서 렌더링한 page image 직접 첨부 실습 | `Chat Input.Files`, vision-capable `Language Model` |
| `company_faq_rag.json` | JSON FAQ RAG/검색 실습 | `File Dataset Loader` |
| `quality_inspection_metrics.csv` | CSV 분석 질문 실습 | `File Dataset Loader`, `Safe DataFrame Profiler` |
| `support_tickets.jsonl` | JSONL 티켓 검색/필터링 실습 | `File Dataset Loader(parse_mode=jsonl)` |
| `sample_markdown_policy.md` | Markdown 정책 문서 Q&A | `File Dataset Loader(parse_mode=markdown)` |
| `milvus_document_payload.json` | Milvus chunk builder 직접 연결 | `Multimodal Milvus Chunk Builder.document_payload` |
| `run_flow_payload_sample.json` | Run Flow payload bridge 실습 | `Run Flow Payload Adapter.payload` |
| `mcp_web_digest_email_case.json` | MCP fetch + mail draft 활용 사례 실습 | `MCP Tools`, `Agent`, `Chat Output` |
| `mcp_langflow_flow_as_tool_case.json` | Langflow flow를 MCP tool로 공개하고 다른 flow에서 재사용하는 실습 | `MCP Server`, `MCP Tools`, `Agent` |
| `rag_eval_cases.json` | 자동/수동 검증용 질문-기대답변 | 평가 또는 교육 진행표 |
| `sample_questions_and_expected_answers.md` | 복사해서 넣을 질문과 기대 답변 | 교육 진행표 |

## 답변 비교 기준

정답 문장을 완전히 똑같이 말할 필요는 없습니다. 대신 아래 조건을 만족하면 성공으로 봅니다.

- 질문 의도에 맞는 파일 내용을 근거로 답한다.
- 숫자 질문은 주요 수치와 대상 lot/line을 포함한다.
- RAG 질문은 lifecycle, component, Milvus field 같은 핵심 키워드를 포함한다.
- 이미지 PDF 질문은 2페이지 공정 흐름도와 3페이지 차트의 핵심 수치/병목을 포함한다.
- MCP 질문은 외부 MCP server 등록, `MCP Tools.Toolset -> Agent.Tools` 연결, flow를 MCP server로 제공하는 방향을 구분한다.
- 모르는 내용은 파일에 없다고 말하고 임의로 꾸며내지 않는다.
