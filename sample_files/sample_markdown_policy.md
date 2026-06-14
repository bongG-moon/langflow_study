# Agent Builder 교육 정책 샘플

## Custom component 작성 기준

사내 공통 custom component는 교육생이 복사해서 Langflow 코드창에 붙여 넣을 수 있어야 한다.

- 파일 하나만으로 동작한다.
- sibling module import에 의존하지 않는다.
- 실패 시 `success=false`, `errors`를 반환한다.
- 긴 원문이나 secret은 `status`, `debug`, `output`에 노출하지 않는다.

## RAG 운영 기준

RAG는 한 장의 flow가 아니라 두 lifecycle로 설명한다.

1. 문서 적재 lifecycle
   - `Read File`
   - parser 또는 OCR
   - chunk
   - embedding
   - Milvus upsert

2. 사용자 질문 lifecycle
   - `Chat Input`
   - query embedding
   - Milvus search
   - prompt 구성
   - `Chat Output`

## 초보자 질문 예시

질문: `RAG 적재 flow와 사용자 질문 flow는 각각 무엇을 담당해?`

기대 답변: `적재 flow는 문서를 읽고 chunk/embedding/Milvus 저장을 담당하고, 사용자 질문 flow는 질문을 받아 검색과 답변 생성을 담당한다.`

질문: `custom component가 실패했을 때 어떻게 반환해야 해?`

기대 답변: `예외만 던지지 말고 success=false와 errors 배열을 포함한 Data payload를 반환해야 한다.`
