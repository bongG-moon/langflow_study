# Langflow Custom Node and AI Agent Flow Developer Guide

이 문서는 Langflow Custom Component를 처음 작성하는 개발자가 실제 AI agent용 node와 flow를 설계, 구현, 검증할 수 있도록 돕는 개발자 육성 자료이다.

목표는 단순히 "Python class 하나를 Langflow 화면에 띄우는 법"을 넘어서, 다음 역량을 갖추는 것이다.

- Langflow custom node의 구조와 실행 흐름을 설명할 수 있다.
- `Data`, `Message`, `DataFrame` 등 출력 타입을 의도에 맞게 선택할 수 있다.
- `FileInput`, `SecretStrInput`, `BoolInput`, `DropdownInput`, `DataFrameInput`, `CodeInput`, `HandleInput` 같은 입력을 flow 편의성과 운영 안전성 관점에서 쓸 수 있다.
- AI agent flow를 state, domain metadata, prompt, LLM call, parser, router, retriever, postprocess, final answer, memory 단계로 나누어 설계할 수 있다.
- 노드가 실패해도 downstream이 읽을 수 있는 payload를 반환하고, Langflow UI에서 디버깅 가능한 상태를 남길 수 있다.
- Langflow canvas에 붙여도 깨지지 않는 standalone component를 작성할 수 있다.

기준 문서는 Langflow 공식 문서의 Custom Components, Components overview, Tool mode, Dynamic Create Data 설명이다. Langflow 버전에 따라 import path나 input class 이름이 조금씩 달라질 수 있다. 공식 문서 기준으로 Langflow 1.7 이후에는 `lfx` import path가 권장되고, 이전 `langflow` import path도 호환된다.

## 1. 개발자가 가져야 할 기본 관점

Langflow에서 하나의 node는 "화면에 보이는 Python class"이다. 하지만 AI agent flow에서 좋은 node는 단순 class가 아니라 작은 계약 단위이다.

좋은 node는 다음 질문에 답할 수 있어야 한다.

| 질문 | 좋은 답 |
| --- | --- |
| 이 node는 무엇을 책임지는가? | 한 문장으로 설명된다. |
| 어떤 input을 받는가? | 입력 이름, 타입, 필수 여부가 명확하다. |
| 어떤 output을 내보내는가? | `Data`, `Message`, `DataFrame` 중 하나로 명확하다. |
| 실패하면 어떻게 되는가? | `success=False`, `errors=[]` 등 downstream이 읽을 수 있는 형태로 반환한다. |
| 다음 node는 무엇을 기대하는가? | payload key가 안정적이고 문서화되어 있다. |
| Langflow UI에서 디버깅할 수 있는가? | `self.status`, `debug`, `warnings`가 적절하다. |

반대로 좋지 않은 node는 다음 특징을 가진다.

- prompt 생성, LLM 호출, JSON parsing, DB 조회, pandas 계산, 최종 답변을 한 파일에 모두 넣는다.
- output method 반환 타입이 `-> Any`라서 포트 타입이 흐려진다.
- `dict`나 `str`를 그대로 반환해서 다음 node 연결이 불안정하다.
- API key, password, token을 일반 텍스트 input이나 debug payload에 노출한다.
- domain-specific rule을 Python 코드에 하드코딩한다.
- 오래 걸리는 외부 호출에 timeout이 없다.
- 큰 row list 전체를 state나 prompt에 계속 싣는다.

이 repo의 `langflow_main/` 원칙도 같다. component 파일은 standalone으로 유지하고, 제조 도메인별 규칙은 가능한 Python 코드가 아니라 domain item, main flow filter, table catalog metadata에 둔다.

## 2. Custom Component의 최소 구조

가장 작은 custom node는 다음 구성으로 만든다.

```text
Python class
  -> Component 상속
  -> display_name, description, icon, name 선언
  -> inputs 리스트 선언
  -> outputs 리스트 선언
  -> Output.method가 가리키는 method 구현
```

예시:

```python
from __future__ import annotations

import json
from typing import Any

from lfx.custom import Component
from lfx.io import DataInput, MessageTextInput, Output
from lfx.schema import Data


def _payload_from_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        return data
    text = getattr(value, "text", None) or getattr(value, "content", None)
    if isinstance(text, str) and text.strip():
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"text": text}
        except Exception:
            return {"text": text}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"text": value}
        except Exception:
            return {"text": value}
    return {}


class ExampleDataNode(Component):
    display_name = "Example Data Node"
    description = "Build a normalized Data payload from text and optional input payload."
    icon = "Box"
    name = "ExampleDataNode"

    inputs = [
        MessageTextInput(
            name="title",
            display_name="Title",
            info="Short label typed by the user.",
            value="hello",
        ),
        DataInput(
            name="payload",
            display_name="Payload",
            info="Payload from another node.",
            input_types=["Data", "JSON"],
            required=False,
        ),
    ]

    outputs = [
        Output(
            name="result",
            display_name="Result",
            method="build_result",
            types=["Data"],
        ),
    ]

    def build_result(self) -> Data:
        title = str(self.title or "").strip()
        payload = _payload_from_value(getattr(self, "payload", None))

        result = {
            "success": True,
            "title": title,
            "payload": payload,
            "errors": [],
            "warnings": [],
        }
        self.status = f"Built payload: {title or 'untitled'}"
        return Data(data=result, text=json.dumps(result, ensure_ascii=False))
```

핵심은 네 가지이다.

- `inputs`에 적은 `name`은 method 안에서 `self.<name>`으로 접근한다.
- `outputs`의 `method` 이름과 실제 method 이름은 정확히 같아야 한다.
- output method에는 `-> Data`, `-> Message`, `-> DataFrame` 같은 return annotation을 명확히 적는다.
- custom node 사이의 구조화된 데이터는 plain `dict`보다 `Data(data=...)`로 넘긴다.

## 3. Import path

Langflow Desktop 1.10.x 기준으로 custom component 코드 맨 위에는 아래 import를 둔다.
코드창에 붙여넣을 때는 이 import 줄부터 class 정의까지 파일 전체를 함께 붙여넣는다.

```python
from lfx.custom import Component
from lfx.io import DataInput, MessageTextInput, Output
from lfx.schema import Data
```

## 4. Class metadata

Component class에는 보통 다음 class-level 속성을 둔다.

```python
class MyNode(Component):
    display_name = "My Node"
    description = "One sentence about what this node does."
    icon = "Box"
    name = "MyNode"
    documentation = "https://docs.example.com/my-node"
```

| 속성 | 의미 | 작성 팁 |
| --- | --- | --- |
| `display_name` | Langflow UI에 보이는 이름 | 사용자가 canvas에서 이해할 수 있는 이름 |
| `description` | node 설명 | Agent tool로 쓸 가능성이 있으면 더 구체적으로 작성 |
| `icon` | UI icon 이름 | Lucide icon 이름을 사용 |
| `name` | 내부 component 이름 | 공백 없이 class명과 비슷하게 |
| `documentation` | 문서 URL | 운영 flow에서는 있으면 좋음 |
| `priority` | component 정렬 우선순위 | custom bundle 관리 시 선택 사용 |

`display_name`은 사람이 보는 이름이고 `name`은 내부 식별자에 가깝다. `name`은 안정적으로 유지하는 것이 좋다. 이름을 자주 바꾸면 Langflow canvas에 남아 있는 기존 node instance와 새 code 사이에서 혼란이 생긴다.

## 5. Input 설계 원칙

Input은 단순히 화면 필드가 아니라 node contract의 절반이다.

좋은 input은 다음 조건을 만족한다.

- `name`이 코드와 payload에서 쓰기 좋은 snake_case이다.
- `display_name`이 화면에서 읽기 쉽다.
- `info`가 "무엇을 넣어야 하는지"를 설명한다.
- 필수값과 운영 옵션을 구분한다.
- API key, password, token은 `SecretStrInput`이나 Langflow variable을 사용한다.
- 복잡한 JSON은 `MultilineInput` 또는 `DataInput`으로 받고, method 내부에서 normalize한다.
- 큰 데이터는 가능하면 `DataFrameInput`, `FileInput`, `data_ref`를 사용하고 LLM prompt에 원문 전체를 넣지 않는다.

### 5.1 자주 쓰는 input class

| Input class | 용도 | 예시 | 주의점 |
| --- | --- | --- | --- |
| `MessageTextInput` / `StrInput` | 짧은 텍스트 | 질문, session id, model name | 긴 JSON/prompt에는 부적합 |
| `MultilineInput` | 긴 텍스트 | prompt, JSON, 정책 문서 | JSON parse helper를 함께 둔다 |
| `DataInput` | 다른 node의 `Data`/`JSON` payload | state, intent, domain payload | `input_types=["Data", "JSON"]` 권장 |
| `DataFrameInput` | 표 형태 데이터 | pandas table, CSV load 결과 | downstream이 Table을 기대할 때 사용 |
| `FileInput` | 파일 업로드/경로 | CSV, JSON, TXT, XLSX | 파일 객체/문자열/list 모두 방어적으로 처리 |
| `SecretStrInput` | 비밀값 | API key, DB password, token | status/debug에 절대 출력하지 않음 |
| `BoolInput` | true/false toggle | include_preview, dry_run, debug_mode | 오래된 환경에서는 문자열도 방어 |
| `IntInput` | 정수 | limit, timeout, max_steps | 범위 clamp 필요 |
| `FloatInput` | 실수 | temperature, threshold | 범위 clamp 필요 |
| `DropdownInput` | 선택지 | provider, parse_mode, auth_type | default 값을 반드시 지정 |
| `CodeInput` | 코드 입력 | pandas code, transform snippet | 실행 node는 반드시 sandbox/allowlist 필요 |
| `HandleInput` / `ModelInput` | 객체 handle 연결 | LLM, embedding, tool | 객체를 `Data` payload에 넣지 않음 |
| `PromptInput` | prompt template | template 기반 prompt | Agent tool mode와 함께 쓸 수 있음 |

Langflow 버전에 따라 class 이름이나 위치가 다를 수 있으므로, 새 input class를 쓰기 전에는 현재 Langflow의 generated example 또는 공식 input definitions를 확인한다.

### 5.2 공통 옵션

| 옵션 | 의미 | 사용 기준 |
| --- | --- | --- |
| `name` | `self.<name>`으로 접근할 내부 이름 | snake_case |
| `display_name` | UI label | 사람이 읽는 짧은 이름 |
| `info` | 도움말 | 운영자가 실수하기 쉬운 값에 작성 |
| `value` | 기본값 | safe default만 넣기 |
| `required` | 필수 입력 여부 | 없으면 실행할 수 없는 값에만 true |
| `advanced` | 고급 영역으로 숨김 | timeout, debug, limit, status filter 등 |
| `input_types` | 연결 가능한 포트 타입 | `DataInput`에서는 `["Data", "JSON"]` 자주 사용 |
| `is_list` | list 입력 여부 | 여러 documents/tools를 받을 때 |
| `tool_mode` | Agent tool argument로 노출 | Agent가 직접 채워야 하는 값에만 |
| `dynamic` | 동적 field 여부 | 조건부 표시 |
| `real_time_refresh` | 변경 즉시 config 갱신 | dropdown이 다른 field를 바꿀 때 |
| `options` | dropdown 선택지 | `DropdownInput`에서 사용 |

좋은 예:

```python
DropdownInput(
    name="parse_mode",
    display_name="Parse Mode",
    info="How to parse the uploaded file.",
    options=["auto", "csv", "json", "jsonl", "text"],
    value="auto",
)
```

좋지 않은 예:

```python
MessageTextInput(name="mode", display_name="Mode")
```

선택지가 고정되어 있다면 `MessageTextInput`보다 `DropdownInput`이 안전하다.

## 6. 편의성과 안전성을 높이는 input 활용

### 6.1 `FileInput`: 파일 기반 dataset loader

파일을 받는 node는 실제 agent 개발에서 자주 필요하다. CSV, JSON, JSONL, TXT, Markdown, Excel을 업로드해서 domain metadata, table catalog, test dataset, prompt context로 넘길 수 있다.

중요한 점은 Langflow 버전이나 실행 방식에 따라 `FileInput` 값이 문자열 경로, path 속성을 가진 객체, list 형태 등으로 들어올 수 있다는 것이다. 따라서 helper를 둔다.

```python
from pathlib import Path
from typing import Any


def _file_paths_from_value(value: Any) -> list[Path]:
    values = value if isinstance(value, list) else [value]
    paths: list[Path] = []
    for item in values:
        if item is None:
            continue
        path_value = (
            getattr(item, "path", None)
            or getattr(item, "file_path", None)
            or getattr(item, "name", None)
            or item
        )
        if isinstance(path_value, str) and path_value.strip():
            paths.append(Path(path_value).expanduser())
    return paths
```

파일 node의 권장 output payload:

```json
{
  "success": true,
  "source_name": "uploaded_file",
  "file_name": "sample.csv",
  "file_type": "csv",
  "rows": [],
  "row_count": 123,
  "columns": ["date", "product", "qty"],
  "preview_rows": [],
  "data_ref": {},
  "errors": [],
  "warnings": []
}
```

큰 파일은 `rows` 전체를 계속 들고 다니지 말고, `preview_rows`, `row_count`, `columns`, `data_ref` 중심으로 넘긴다.

### 6.2 `SecretStrInput`: 비밀값과 운영 입력

외부 API, DB, LLM provider를 호출하는 node에는 `SecretStrInput`을 사용한다.

```python
SecretStrInput(
    name="api_key",
    display_name="API Key",
    info="Bearer token for the external service.",
    required=False,
    advanced=True,
)
```

비밀값 사용 규칙:

- `self.status`에 secret을 넣지 않는다.
- output `debug`에 secret을 넣지 않는다.
- exception message에 request header를 그대로 넣지 않는다.
- sample code나 default `value`에 실제 key를 넣지 않는다.
- 가능하면 Langflow variable이나 runtime secret 관리 기능을 사용한다.

환경에 따라 secret 값이 문자열이 아니라 `get_secret_value()`를 가진 객체로 들어올 수 있다. 재사용 helper를 두면 안전하다.

```python
def _secret_to_text(value: object) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter() or "")
    return str(value or "")
```

### 6.3 `BoolInput`: 운영 toggle

`BoolInput`은 flow를 편하게 만드는 데 효과적이다.

추천 사용처:

- `dry_run`: DB write 전 payload만 확인
- `include_preview`: preview rows 포함 여부
- `include_debug`: debug payload 포함 여부
- `strict_mode`: schema 오류 시 실패 처리할지 여부
- `allow_empty_result`: row가 없어도 성공으로 볼지 여부

```python
BoolInput(
    name="include_preview",
    display_name="Include Preview",
    info="Include preview rows in the output payload.",
    value=True,
    advanced=True,
)
```

방어 helper:

```python
def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default
```

### 6.4 `IntInput`과 `FloatInput`: 범위가 있는 설정

숫자 입력은 항상 범위를 제한한다.

```python
def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))
```

예:

- `timeout_seconds`: 1-120
- `preview_limit`: 0-100
- `max_steps`: 1-10
- `temperature`: 0.0-2.0

### 6.5 `DropdownInput`: flow를 안정시키는 선택지

운영자가 값을 직접 타이핑하면 오타가 route bug가 된다. 정해진 mode는 dropdown으로 만든다.

```python
DropdownInput(
    name="auth_type",
    display_name="Auth Type",
    options=["none", "bearer", "api_key_header"],
    value="none",
    real_time_refresh=True,
)
```

`DropdownInput`은 dynamic field와 함께 쓰기 좋다. 예를 들어 `auth_type="none"`이면 secret field를 숨기고, `auth_type="bearer"`이면 보여준다.

### 6.6 `DataFrameInput`과 `DataFrame` output

표 형태의 데이터를 Langflow Table port로 연결하려면 `DataFrameInput`과 `DataFrame` output을 사용한다.

```python
from lfx.io import DataFrameInput, Output
from lfx.schema import Data, DataFrame


outputs = [
    Output(name="table", display_name="Table", method="build_table", types=["DataFrame"]),
]


def build_table(self) -> DataFrame:
    return DataFrame({"product": ["A", "B"], "qty": [10, 20]})
```

사용 기준:

- downstream이 Langflow Table/DataFrame component라면 `DataFrame`.
- custom node 사이에서 schema, errors, metadata도 함께 보내야 한다면 `Data`.
- LLM prompt에 표를 줄 때는 DataFrame 전체보다 preview와 summary를 사용한다.

### 6.7 `CodeInput`: 코드는 입력받되 실행은 제한한다

`CodeInput`은 pandas code, Python snippet, SQL template을 입력받을 때 편리하다. 하지만 code 실행 node는 가장 위험하다.

원칙:

- code를 그대로 `exec`하지 않는다.
- 허용된 globals, timeout, 금지 import, row limit을 둔다.
- 실행 결과와 오류를 payload에 분리한다.
- LLM이 만든 code는 normalizer가 금지 패턴을 검사한 뒤 executor로 넘긴다.

AI agent flow에서는 `LLM -> JSON parser -> plan normalizer -> constrained executor` 구조로 나누는 것이 좋다.

### 6.8 `HandleInput`과 `ModelInput`

`HandleInput`은 model, embedding, retriever, tool 같은 Python 객체를 연결할 때 사용한다. 이 값은 JSON으로 직렬화되는 payload가 아니라 runtime 객체이다.

주의:

- `Data(data=...)` 안에 handle 객체를 넣지 않는다.
- standalone 배포가 중요하면 외부 객체 연결보다 explicit config input이 더 재현 가능하다.
- Agent tool 연결에서는 Langflow의 Tool output과 Agent Tools input 구조를 우선 고려한다.

## 7. Output 설계

Output은 node contract의 나머지 절반이다.

```python
outputs = [
    Output(
        name="result",
        display_name="Result",
        method="build_result",
        types=["Data"],
    ),
]
```

반드시 확인할 것:

- `Output.method`와 method 이름이 일치하는가?
- method return annotation이 명확한가?
- Langflow UI에서 원하는 포트 타입으로 보이는가?
- 여러 output을 동시에 연결해야 하면 `group_outputs=True`가 있는가?

### 7.1 return type 선택

| Return type | 용도 | 연결 대상 |
| --- | --- | --- |
| `Data` | JSON-like 구조화 payload | `DataInput`, JSON/Data port |
| `Message` | chat message, Run Flow text bridge | Chat Output, Message input |
| `DataFrame` | tabular data | `DataFrameInput`, Table port |
| primitive | 단순 값 | 특별한 경우만 |

권장:

```python
def build_payload(self) -> Data:
    return Data(data={"success": True})
```

피하기:

```python
def build_payload(self) -> Any:
    return {"success": True}
```

### 7.2 여러 output과 `group_outputs`

Langflow에서 한 node가 여러 output을 가질 때 기본값은 선택형 output이다. 여러 포트를 동시에 연결해야 하면 각 `Output`에 `group_outputs=True`를 넣는다.

```python
outputs = [
    Output(
        name="data_question",
        display_name="Data Question",
        method="data_question_output",
        group_outputs=True,
        types=["Data"],
    ),
    Output(
        name="finish",
        display_name="Finish",
        method="finish_output",
        group_outputs=True,
        types=["Data"],
    ),
]
```

라우터 node에서는 inactive branch도 명확히 반환한다.

```python
def _branch(self, expected_route: str) -> Data:
    payload = _payload_from_value(self.intent_plan)
    route = str(payload.get("route") or "finish")
    active = route == expected_route
    return Data(data={
        "success": active,
        "active": active,
        "skipped": not active,
        "route": route,
        "payload": payload if active else {},
        "errors": [],
        "warnings": [] if active else [f"Inactive branch. Selected route is {route}."],
    })
```

downstream merger는 `active=True`이고 `skipped=False`인 branch만 선택한다.

## 8. Payload contract

Custom node flow에서 가장 중요한 것은 payload key를 안정적으로 유지하는 것이다.

기본 payload skeleton:

```json
{
  "success": true,
  "node_name": "ExampleNode",
  "result": {},
  "errors": [],
  "warnings": [],
  "debug": {}
}
```

데이터 조회 payload:

```json
{
  "success": true,
  "source_name": "oracle",
  "dataset_key": "production",
  "rows": [],
  "row_count": 100,
  "columns": ["DATE", "PRODUCT", "QTY"],
  "applied_params": {"date": "2026-06-11"},
  "applied_filters": {"product": "A"},
  "preview_rows": [],
  "data_ref": {},
  "errors": [],
  "warnings": []
}
```

Agent state payload:

```json
{
  "agent_state": {
    "session_id": "default",
    "turn_id": 2,
    "chat_history": [],
    "context": {},
    "current_data": null
  }
}
```

LLM result payload:

```json
{
  "success": true,
  "llm_text": "{\"route\":\"data_retrieval\"}",
  "parsed": {},
  "llm_debug": {
    "provider": "openai",
    "model_name": "gpt-4.1-mini",
    "prompt_chars": 1200,
    "ok": true
  },
  "errors": []
}
```

원칙:

- `errors`와 `warnings`는 항상 list로 둔다.
- 사용자가 볼 답변과 개발자가 볼 debug를 분리한다.
- 큰 원본 데이터는 `data_ref`로 빼고 payload에는 preview와 metadata만 둔다.
- 후속 질문에서 재사용할 source는 `current_data` 안에 compact하게 유지한다.
- route 값은 enum처럼 다루고 오타를 normalizer에서 고친다.

## 9. 실행 흐름: output method, `_pre_run_setup`, `ctx`

일반 custom node는 output method만 구현하면 충분하다.

```python
outputs = [Output(name="result", display_name="Result", method="build_result")]

def build_result(self) -> Data:
    return Data(data={})
```

`_pre_run_setup`은 실행 전 초기화가 필요할 때 사용한다.

```python
def _pre_run_setup(self):
    if not hasattr(self, "_initialized"):
        self._initialized = True
        self.ctx["run_count"] = 0
```

`self.ctx`는 같은 component instance 안에서 output method 간 값을 공유할 때 쓴다. 예를 들어 `api_response`와 `api_message` output이 같은 비싼 계산을 공유하도록 cache할 수 있다.

```python
def _payload(self) -> dict:
    cached = getattr(self, "_cached_payload", None)
    if isinstance(cached, dict):
        return cached
    payload = self._build_expensive_payload()
    self._cached_payload = payload
    return payload
```

초보 단계에서는 `run`이나 `_run` override보다 output method 방식이 더 명확하다. 전체 실행 흐름을 직접 제어해야 할 때만 `run`/`_run`을 고려한다.

## 10. Error handling과 status

Langflow UI에서 문제를 빨리 찾으려면 에러를 "숨기지 않고 구조화"해야 한다.

일반적인 변환/조회 node에서는 실패 payload를 반환하는 편이 downstream 처리에 유리하다.

```python
def build_result(self) -> Data:
    try:
        payload = json.loads(str(self.payload_json or "{}"))
    except json.JSONDecodeError as exc:
        message = f"Invalid payload_json: {exc}"
        self.status = message
        return Data(data={
            "success": False,
            "errors": [message],
            "warnings": [],
            "result": {},
        })

    self.status = "Payload parsed"
    return Data(data={"success": True, "result": payload, "errors": []})
```

반대로 필수 configuration이 없어서 node 자체가 실행될 수 없는 경우는 `ValueError`를 raise해도 된다.

```python
if not str(self.api_url or "").strip():
    raise ValueError("API URL is required.")
```

`self.status`는 짧게 유지한다.

좋은 status:

```text
Parsed 5 domain items
Route: data_retrieval
Loaded 120 rows
No data found
API call failed: timeout
```

피할 status:

```text
전체 JSON payload 원문 수천 줄
API key 포함 문자열
traceback 전체
```

## 11. Dynamic field

입력값에 따라 다른 field를 보이거나 숨기려면 `dynamic=True`, `real_time_refresh=True`, `update_build_config`를 사용한다.

예: auth type에 따라 API key field 표시.

```python
from lfx.custom import Component
from lfx.io import DropdownInput, MessageTextInput, SecretStrInput


class ExternalApiConfig(Component):
    inputs = [
        DropdownInput(
            name="auth_type",
            display_name="Auth Type",
            options=["none", "bearer"],
            value="none",
            real_time_refresh=True,
        ),
        SecretStrInput(
            name="api_key",
            display_name="API Key",
            dynamic=True,
            show=False,
            advanced=True,
        ),
        MessageTextInput(
            name="api_url",
            display_name="API URL",
            required=True,
        ),
    ]

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name == "auth_type":
            show_secret = field_value == "bearer"
            build_config["api_key"]["show"] = show_secret
            build_config["api_key"]["required"] = show_secret
        return build_config
```

dynamic field는 편리하지만 너무 많이 쓰면 교육과 운영이 어려워진다. 먼저 고정 input으로 안정화하고, 반복 실수가 보일 때 도입한다.

## 12. Tool Mode와 Agent tool

Langflow Agent가 custom component를 tool로 호출하려면 tool argument가 될 input에 `tool_mode=True`를 붙인다.

```python
MessageTextInput(
    name="dataset_key",
    display_name="Dataset Key",
    info="Dataset key to look up, such as production or target.",
    tool_mode=True,
)
```

Tool Mode 규칙:

- Agent가 직접 채워야 하는 input에만 `tool_mode=True`를 붙인다.
- API key, DB URI, debug toggle, 큰 JSON payload에는 붙이지 않는다.
- `description`, input `info`, output schema가 구체적이어야 Agent가 올바르게 호출한다.
- tool output은 작고 명확해야 한다.
- 여러 tool action이 생기면 action 이름과 설명을 UI에서 검토한다.

간단한 catalog tool 예:

```python
from __future__ import annotations

from lfx.custom import Component
from lfx.io import MessageTextInput, Output
from lfx.schema import Data


DATASET_CATALOG = {
    "production": {
        "display_name": "생산 데이터",
        "required_params": ["date"],
        "columns": ["date", "product", "process", "line", "qty"],
    },
    "target": {
        "display_name": "목표 데이터",
        "required_params": ["date"],
        "columns": ["date", "product", "process", "line", "target_qty"],
    },
}


class DatasetCatalogTool(Component):
    display_name = "Dataset Catalog Tool"
    description = "Return concise dataset metadata by dataset key."
    icon = "Database"
    name = "DatasetCatalogTool"

    inputs = [
        MessageTextInput(
            name="dataset_key",
            display_name="Dataset Key",
            info="Dataset key such as production or target.",
            tool_mode=True,
        ),
    ]

    outputs = [
        Output(name="dataset_info", display_name="Dataset Info", method="lookup_dataset", types=["Data"]),
    ]

    def lookup_dataset(self) -> Data:
        dataset_key = str(self.dataset_key or "").strip()
        dataset = DATASET_CATALOG.get(dataset_key)
        if not dataset:
            return Data(data={
                "success": False,
                "found": False,
                "dataset_key": dataset_key,
                "available_dataset_keys": sorted(DATASET_CATALOG),
                "errors": [f"Unknown dataset_key: {dataset_key}"],
            })
        return Data(data={
            "success": True,
            "found": True,
            "dataset_key": dataset_key,
            "dataset": dataset,
            "errors": [],
        })
```

AI agent 개발에서 모든 것을 Tool Mode로 만들 필요는 없다. 데이터 조회/분석 경로가 명확하고 재현성이 중요하면 고정 DAG flow가 더 좋다. Agent가 어떤 tool을 선택해야 하는지 자유롭게 판단해야 하는 검색/탐색 문제라면 Tool Mode 또는 ReAct 구조가 더 적합하다.

## 13. AI agent flow를 node로 나누는 법

실제 agent flow는 다음 단계로 나누면 관리하기 쉽다.

```text
User Input
  -> State Loader
  -> Domain / Catalog / Filter Loader
  -> Intent Prompt Builder
  -> LLM Caller
  -> Intent Parser
  -> Intent Normalizer
  -> Route Router
  -> Retriever / Tool Caller
  -> Retrieval Merger
  -> Postprocess Router
  -> Direct Result Adapter OR Analysis Prompt Builder
  -> Analysis LLM Caller
  -> Analysis Plan Normalizer
  -> Analysis Executor
  -> Final Answer Prompt Builder
  -> Final Answer LLM Caller
  -> Answer Normalizer
  -> Final Payload Builder
  -> Memory Writer
```

각 node의 책임:

| Node 종류 | 책임 | 하지 말아야 할 일 |
| --- | --- | --- |
| Input/Loader | 원문을 표준 payload로 변환 | LLM 호출 |
| Prompt Builder | LLM에게 보낼 prompt 생성 | provider 호출 |
| LLM Caller | prompt를 모델에 보내고 raw text 반환 | 복잡한 schema 보정 |
| Parser | JSON/text를 dict로 파싱 | domain rule 적용 |
| Normalizer | alias, default, route, schema 보정 | 외부 DB 조회 |
| Router | branch 선택 | payload 대규모 변경 |
| Retriever | 외부 데이터 조회 | 최종 자연어 답변 생성 |
| Merger | 여러 branch/source 결과 병합 | 새 조회 수행 |
| Analysis Executor | 제한된 계산 수행 | 임의 Python 전체 허용 |
| Answer Builder | 사용자용 답변 payload 생성 | secret/debug 노출 |
| Memory Writer | 다음 turn에 필요한 compact state 저장 | 전체 raw rows 무제한 저장 |

이 repo의 main flow도 이 사고방식에 맞춰 state, metadata, intent, retrieval, pandas postprocess, final answer, memory, API response를 분리한다.

## 14. DAG flow와 ReAct flow 선택

두 구조는 목적이 다르다.

| 구조 | 적합한 상황 | 장점 | 위험 |
| --- | --- | --- | --- |
| 고정 DAG | 조회 순서와 검증 기준이 명확한 업무 flow | 재현성, 디버깅, 감사 추적 | tool 선택 자유도가 낮음 |
| Tool Mode Agent | 작은 tool 여러 개 중 agent가 선택 | 구현 빠름, 자연스러운 tool use | 호출이 불안정할 수 있음 |
| ReAct loop | 탐색, 반복 관찰, 여러 tool 조합 필요 | 복잡한 문제 해결 가능 | 무한 반복, 비용, 디버깅 어려움 |

제조 데이터 분석처럼 "질문 -> intent -> source 조회 -> evidence 기반 답변"이 중요한 경우는 고정 DAG를 기본으로 두는 것이 좋다. ReAct는 필요한 범위에만 제한적으로 도입한다.

ReAct를 직접 canvas로 만들 때 최소 안전장치:

- `max_steps`를 둔다.
- 같은 tool과 같은 arguments 반복 호출을 막는다.
- observation은 요약해서 넘긴다.
- tool 실패가 final answer로 새지 않도록 route를 정의한다.
- 마지막 답변은 반드시 evidence payload를 기준으로 만든다.

## 15. Agent 구현용 주요 node catalog

AI agent를 만들 때는 "노드 하나"보다 "역할이 다른 노드들의 조합"이 중요하다. 아래 node들은 대부분의 업무형 agent에서 반복해서 등장한다.

| Node 계열 | 대표 node | 핵심 기능 | 주요 input | 주요 output |
| --- | --- | --- | --- | --- |
| 입력/상태 | User Input Adapter, State Loader, Memory Extractor | 현재 질문과 이전 상태를 표준 state로 변환 | `Message`, previous state, session id | `state_payload` |
| 메타데이터 | Domain Loader, Table Catalog Loader, Filter Loader | 업무 규칙, alias, dataset, metric, filter 정의 로드 | JSON, MongoDB config, file | `domain_payload`, `table_catalog_payload` |
| Prompt | Intent Prompt Builder, Analysis Prompt Builder, Answer Prompt Builder | LLM에게 줄 입력을 목적별로 구성 | state, metadata, evidence | `prompt_payload` |
| LLM 호출 | LLM JSON Caller, LLM Text Caller | provider/model/API key로 LLM 호출 | prompt, model config, secret | `llm_result` |
| 파싱/정규화 | JSON Parser, Intent Normalizer, Analysis Plan Normalizer | LLM output을 안정적인 schema로 변환 | raw LLM text, metadata | `intent_plan`, `analysis_plan` |
| 라우팅 | Request Router, Retrieval Router, Postprocess Router | 다음 branch 결정 | plan, retrieval result | branch outputs |
| 조회 | File Retriever, Excel Dataset Loader, DB Retriever, HTTP API Retriever, Vector Retriever, MCP Gateway Caller | 외부 source에서 evidence 확보 | query/job/source config | `source_result`, `retrieval_payload` |
| 비정형 문서 전처리 | Document Extractor, Multimodal Document To Text | 이미지/PDF/PPT를 text evidence로 변환 | file, instruction, vision model config | `document_text`, `document_summary` |
| 병합 | Source Result Merger, Branch Merger | 여러 source/branch 결과를 하나로 통합 | source results | `retrieval_payload`, `analysis_result` |
| 분석 | Pandas Prompt Builder, Code Plan Normalizer, Pandas Executor | 조회 결과를 계산/집계/비교 | retrieval payload, code plan | `analysis_result` |
| 저장 | Data Store Writer, Data Ref Loader | 큰 데이터 저장과 복원 | rows, `data_ref` | stored payload, restored rows |
| 답변 | Final Answer Builder, API Response Builder | 사용자/웹/API가 읽을 최종 결과 생성 | answer text, analysis result, state | `final_result`, `api_response` |
| 관측/검증 | Debug Payload Builder, Validation Result Builder | 개발자 확인용 상태 정리 | any payload | compact debug/report |

각 node 계열은 기능만 다른 것이 아니라 실패 기준도 다르다.

| Node 계열 | 실패 처리 기준 |
| --- | --- |
| State/Loader | 입력이 비어도 기본 state를 만들 수 있으면 `success=True`, 파싱 실패는 `state_errors`에 기록 |
| Metadata Loader | MongoDB/API 연결 실패는 `success=False`, 단 빈 metadata로 계속 갈지 route를 멈출지 flow 정책으로 결정 |
| Prompt Builder | 필수 payload가 없으면 prompt를 만들지 말고 `errors` 반환 |
| LLM Caller | provider 오류, timeout, 빈 응답을 `llm_debug`와 `errors`에 기록 |
| Parser | raw text와 parse error를 남기고 downstream normalizer가 판단할 수 있게 함 |
| Normalizer | 가능한 default를 채우되, route/evidence를 왜 보정했는지 `normalization_notes`에 기록 |
| Router | inactive branch는 `success=False`, `active=False`, `skipped=True` payload를 반환 |
| Retriever | 외부 source 오류를 전체 agent 오류와 분리해 source별 `error_message`로 기록 |
| Executor | 실행 실패 시 실패한 code/plan과 제한 사유를 debug에 넣되 secret/source credential은 제외 |
| Final Builder | evidence가 부족하면 추측 답변 대신 제한/확인 필요 답변을 생성 |

## 16. 주요 node 구현 패턴

여기서는 실제 agent 구현에 자주 쓰이는 핵심 node를 어떻게 구현해야 하는지 설명한다. 모든 코드를 완성형으로 길게 넣기보다, 개발자가 자기 업무에 맞게 확장할 수 있는 skeleton과 payload contract를 중심으로 본다.

### 16.1 State Loader

State Loader는 현재 질문과 이전 memory를 합쳐 agent가 이번 turn에서 사용할 기준 state를 만든다.

권장 input:

- `chat_input`: 현재 사용자 질문. `MessageTextInput` 또는 `DataInput`.
- `previous_state`: 이전 turn state. `DataInput(input_types=["Data", "JSON"])`.
- `session_id`: 직접 입력하거나 upstream에서 전달.

권장 output:

```json
{
  "agent_state": {
    "session_id": "default",
    "turn_id": 2,
    "chat_history": [],
    "context": {},
    "current_data": null,
    "pending_user_question": "오늘 생산량 알려줘",
    "state_errors": []
  }
}
```

구현 포인트:

- 이전 state가 비어 있어도 기본 state를 만든다.
- `chat_history`, `context`, `current_data` 같은 핵심 key는 항상 유지한다.
- 사용자의 현재 질문은 `pending_user_question`처럼 downstream이 찾기 쉬운 key에 둔다.
- raw memory text 전체를 계속 싣지 말고 필요한 state만 남긴다.

간단 skeleton:

```python
class StateLoader(Component):
    display_name = "State Loader"
    description = "Build canonical agent state from current question and previous state."
    icon = "Memory"
    name = "StateLoader"

    inputs = [
        MessageTextInput(name="chat_input", display_name="Chat Input", required=True),
        DataInput(name="previous_state", display_name="Previous State", input_types=["Data", "JSON"], required=False),
        MessageTextInput(name="session_id", display_name="Session ID", value="default", advanced=True),
    ]

    outputs = [
        Output(name="state_payload", display_name="State Payload", method="build_state", types=["Data"]),
    ]

    def build_state(self) -> Data:
        previous = _payload_from_value(getattr(self, "previous_state", None))
        state = previous.get("agent_state") if isinstance(previous.get("agent_state"), dict) else previous
        if not isinstance(state, dict):
            state = {}

        next_state = {
            "session_id": state.get("session_id") or str(self.session_id or "default"),
            "turn_id": int(state.get("turn_id") or 0) + 1,
            "chat_history": state.get("chat_history") if isinstance(state.get("chat_history"), list) else [],
            "context": state.get("context") if isinstance(state.get("context"), dict) else {},
            "current_data": state.get("current_data"),
            "pending_user_question": str(self.chat_input or "").strip(),
            "state_errors": [],
        }
        self.status = f"Turn {next_state['turn_id']}"
        return Data(data={"agent_state": next_state})
```

### 16.2 Metadata Loader

Metadata Loader는 domain rule, table catalog, shared filter 정의를 로드한다. 제조 agent처럼 여러 공정에 재사용해야 하는 flow에서는 업무 규칙을 Python 코드에 넣지 말고 metadata payload로 전달한다.

권장 node 분리:

- `Domain Loader`: 제품/공정/지표/alias/업무 규칙.
- `Table Catalog Loader`: dataset key, source type, columns, query template, required params.
- `Main Flow Filters Loader`: 날짜, 제품, 공정 같은 공통 semantic filter.

권장 output:

```json
{
  "domain_payload": {
    "items": [],
    "alias_index": {},
    "metric_index": {},
    "normalization_rules": []
  },
  "errors": [],
  "warnings": []
}
```

구현 포인트:

- JSON 직접 입력, FileInput, MongoDB loader를 같은 표준 payload로 맞춘다.
- metadata item마다 `key`, `display_name`, `aliases`, `description`, `status` 같은 공통 필드를 둔다.
- loader는 "읽고 표준화"까지만 담당하고, intent 보정은 normalizer가 담당한다.
- connection secret과 base URL은 운영 정책에 맞춰 input으로 열지, 코드 관리할지 명확히 정한다.

### 16.3 Prompt Builder

Prompt Builder는 LLM 호출 node를 단순하게 만들기 위해 prompt 생성 책임을 따로 가진다.

Prompt Builder 종류:

- `Intent Prompt Builder`: 사용자 질문과 metadata를 보고 route/intent JSON을 만들도록 지시.
- `Analysis Prompt Builder`: 조회 결과 preview와 metric 정의를 보고 pandas plan 또는 계산 계획 생성.
- `Final Answer Prompt Builder`: analysis result와 evidence를 보고 사용자 답변 생성.

권장 output:

```json
{
  "prompt": "Return JSON only...",
  "prompt_type": "intent",
  "expected_schema": {"route": "data_retrieval"},
  "source_summary": {
    "domain_items": 12,
    "datasets": 4
  }
}
```

구현 포인트:

- prompt에 모든 raw rows를 넣지 않는다.
- LLM이 반환해야 하는 JSON schema를 명시한다.
- domain/table catalog에서 온 용어와 alias를 compact하게 요약한다.
- prompt text는 `Data.text`에도 넣으면 Langflow UI에서 확인하기 쉽다.

간단 skeleton:

```python
class IntentPromptBuilder(Component):
    display_name = "Intent Prompt Builder"
    icon = "FileText"
    name = "IntentPromptBuilder"

    inputs = [
        DataInput(name="state_payload", display_name="State Payload", input_types=["Data", "JSON"]),
        DataInput(name="domain_payload", display_name="Domain Payload", input_types=["Data", "JSON"]),
        DataInput(name="table_catalog_payload", display_name="Table Catalog Payload", input_types=["Data", "JSON"]),
    ]

    outputs = [
        Output(name="prompt_payload", display_name="Prompt Payload", method="build_prompt", types=["Data"]),
    ]

    def build_prompt(self) -> Data:
        state = _payload_from_value(self.state_payload).get("agent_state", {})
        domain = _payload_from_value(self.domain_payload)
        catalog = _payload_from_value(self.table_catalog_payload)
        question = str(state.get("pending_user_question") or "")

        prompt = f"""
You are routing a data-analysis request.
Return JSON only.

User question:
{question}

Available domain aliases:
{json.dumps(domain.get("alias_index", {}), ensure_ascii=False)[:4000]}

Available datasets:
{json.dumps(catalog.get("datasets", {}), ensure_ascii=False)[:4000]}

Schema:
{{
  "route": "data_retrieval | followup_transform | finish",
  "dataset_hints": [],
  "metric_hints": [],
  "required_params": {{}},
  "filters": {{}},
  "answer_policy": "evidence_only"
}}
""".strip()
        return Data(data={"prompt": prompt, "prompt_type": "intent"}, text=prompt)
```

### 16.4 LLM JSON Caller

LLM Caller는 가능하면 "호출만" 한다. JSON schema 보정, route 보정, domain alias 적용은 parser/normalizer가 맡는다.

권장 input:

- `prompt_payload`: `DataInput`.
- `provider`, `model_name`, `temperature`.
- `api_key`: `SecretStrInput`.
- `timeout_seconds`, `max_retries`.

권장 output:

```json
{
  "success": true,
  "llm_text": "{...}",
  "llm_debug": {
    "provider": "openai",
    "model_name": "gpt-4.1-mini",
    "prompt_chars": 1200,
    "ok": true
  },
  "errors": []
}
```

구현 포인트:

- secret을 status/debug에 넣지 않는다.
- provider 오류와 empty response를 구분한다.
- LLM response parsing은 caller 안에 몰아넣지 않는다.
- 재시도가 필요하면 횟수를 제한한다.

### 16.5 Parser / Normalizer

Parser와 Normalizer는 분리한다.

Parser:

- `llm_text`에서 JSON을 꺼낸다.
- parse 실패를 `parse_errors`에 기록한다.
- raw text를 debug용으로 보존한다.

Normalizer:

- route enum을 표준화한다.
- domain alias를 표준 key로 변환한다.
- table catalog 기준으로 required dataset/job을 만든다.
- 후속 질문이면 이전 state/current_data를 참조해 route를 바꾼다.

권장 output:

```json
{
  "intent_plan": {
    "route": "data_retrieval",
    "retrieval_jobs": [],
    "filters": {},
    "required_params": {},
    "normalization_notes": []
  }
}
```

구현 포인트:

- `single_retrieval`, `multi_retrieval` 같은 LLM 표현은 canvas branch명이 아니라 intent semantic으로만 사용하고, 실제 branch는 `data_retrieval`처럼 통일할 수 있다.
- metadata로 표현 가능한 업무 규칙은 Python if문으로 추가하지 않는다.
- normalizer가 고친 내용은 `normalization_notes`에 남긴다.

### 16.6 Router

Router는 route를 보고 branch output을 만든다. Router가 계산이나 조회까지 해서는 안 된다.

권장 output:

```python
outputs = [
    Output(name="data_retrieval", display_name="Data Retrieval", method="data_retrieval", group_outputs=True, types=["Data"]),
    Output(name="followup_transform", display_name="Follow-up", method="followup_transform", group_outputs=True, types=["Data"]),
    Output(name="finish", display_name="Finish", method="finish", group_outputs=True, types=["Data"]),
]
```

구현 포인트:

- 모든 output이 같은 payload shape을 가진다.
- inactive branch에는 `success=False`, `active=False`, `skipped=True`를 넣는다.
- downstream merger가 active branch만 선택할 수 있게 한다.

### 16.7 Retriever

Retriever는 외부 source에서 evidence를 가져온다. source 종류별로 node를 나누되 output shape은 맞춘다.

대표 retriever:

- `File Dataset Loader`: CSV/JSON/JSONL/TXT/Markdown/Excel.
- `DB Query Retriever`: Oracle, MySQL, Postgres, Datalake.
- `HTTP API Retriever`: REST API, internal service.
- `Vector Search Retriever`: document search/RAG.
- `MCP Gateway Tool Caller`: MCP tool을 HTTP gateway로 감싸 호출.

권장 output:

```json
{
  "success": true,
  "source_name": "oracle",
  "dataset_key": "production",
  "rows": [],
  "row_count": 0,
  "columns": [],
  "applied_params": {},
  "applied_filters": {},
  "source_debug": {},
  "error_message": "",
  "errors": []
}
```

구현 포인트:

- 외부 source별 실패를 전체 agent 실패로 바로 올리지 말고 source result에 기록한다.
- timeout을 반드시 둔다.
- row_count, columns, preview_rows를 항상 계산한다.
- query template은 table catalog/source config에서 받고 Python 코드에 업무별 SQL을 하드코딩하지 않는다.
- API/MCP 응답 원문은 필요할 때만 advanced debug로 포함한다.

### 16.8 Retrieval Merger

여러 retriever 또는 branch 결과를 하나의 `retrieval_payload`로 합친다.

권장 output:

```json
{
  "success": true,
  "source_results": [],
  "rows": [],
  "row_count": 100,
  "columns": [],
  "source_summaries": [],
  "merge_notes": [],
  "errors": []
}
```

구현 포인트:

- source별 `success=False`를 보존한다.
- row schema가 서로 다르면 source별 rows를 분리해 유지한다.
- 단일 table 분석이 가능할 때만 rows를 하나로 flatten한다.
- downstream이 pandas 분석을 해야 하는지 판단할 수 있게 `source_summaries`를 만든다.

### 16.9 Postprocess Router와 Analysis Executor

조회 결과가 바로 답변 가능한지, 추가 계산이 필요한지 나눈다.

Direct answer가 가능한 예:

- row_count가 0인지 여부만 답하면 됨.
- API가 이미 summary/answer를 반환함.
- 단일 값 count/sum이 retriever에서 이미 계산됨.

Post-analysis가 필요한 예:

- group by, ranking, comparison, trend, anomaly.
- 여러 dataset join/merge.
- 후속 질문에서 기존 source data를 재가공.

Pandas Executor 원칙:

- LLM이 만든 code를 바로 실행하지 않고 plan normalizer를 거친다.
- 허용 import, timeout, row limit, output schema를 제한한다.
- 실패한 code와 오류는 debug에 남기되 사용자 답변에는 안전하게 요약한다.

### 16.10 Final Answer Builder, Memory Writer, API Response Builder

Final Answer Builder는 사용자에게 보여줄 답변과 다음 turn state를 만든다.

권장 output:

```json
{
  "final_result": {
    "answer_message": "2026-06-11 A제품 생산량은 100입니다.",
    "analysis_result": {},
    "applied_scope": {},
    "current_data": {},
    "next_state": {},
    "warnings": []
  }
}
```

구현 포인트:

- 답변은 `analysis_result`와 evidence에 근거해야 한다.
- `current_data`에는 후속 질문에 필요한 compact summary와 `data_ref`를 둔다.
- API Response Builder는 웹/API가 읽기 쉬운 compact JSON으로 줄인다.
- memory message는 사람이 읽는 답변과 섞지 말고 marker나 별도 message 구조로 구분한다.

## 17. 현재 repo에서 참고/재사용하기 좋은 구현 노드

이 자료는 새 custom component를 만드는 법만 다루지 않는다. 이미 `langflow_main/`에 구현된 node 중에는 agent 개발자가 그대로 참고하거나, 새 프로젝트에 맞게 복사해서 출발점으로 삼기 좋은 것들이 있다.

단, 이 repo의 component들은 제조 데이터 분석 agent 기준으로 작성되었다. 그대로 복사하기 전에 domain/table catalog key, source config, MongoDB collection, final payload shape이 새 프로젝트와 맞는지 확인해야 한다.

### 17.1 Main Flow에서 우선 읽을 노드

아래 파일들은 `langflow_main/1.main_flow_components/`에 있다.

| 파일 | Langflow node | 재사용/학습 포인트 |
| --- | --- | --- |
| `00_state_memory_extractor.py` | State Memory Extractor | Message History에서 이전 state를 꺼내는 패턴. memory marker, Message/Data parsing, 빈 memory 처리 방식을 참고한다. |
| `01_state_loader.py` | State Loader | multi-turn agent의 기준 state를 만드는 핵심 예시. `chat_history`, `context`, `current_data`, `pending_user_question` 같은 state key 설계를 읽기 좋다. |
| `02_mongodb_domain_loader.py` | MongoDB Domain Loader | MongoDB에 저장된 domain item을 Langflow payload로 표준화하는 패턴. metadata-driven agent를 만들 때 유용하다. |
| `03_domain_json_loader.py` | Domain JSON Loader | DB 없이 직접 JSON으로 domain metadata를 넣는 개발/테스트용 loader 패턴. |
| `04_table_catalog_loader.py` | Table Catalog Loader | dataset/table catalog JSON을 표준 payload로 만드는 예시. source config, required params, column metadata 구조를 참고한다. |
| `05_mongodb_table_catalog_loader.py` | MongoDB Table Catalog Loader | table catalog를 MongoDB에서 읽는 운영형 loader 패턴. |
| `06_main_flow_filters_loader.py` | Main Flow Filters Loader | 날짜, 제품, 공정처럼 여러 dataset에 공통 적용되는 semantic filter를 metadata로 분리하는 방식. |
| `07_mongodb_main_flow_filters_loader.py` | MongoDB Main Flow Filters Loader | 공통 filter 정의를 MongoDB에서 읽는 운영형 loader 패턴. |
| `08_build_intent_prompt.py` | Build Intent Prompt | state, domain, table catalog, filter metadata를 LLM prompt로 압축하는 prompt builder 예시. |
| `09_llm_json_caller_intent.py` | LLM JSON Caller - Intent | prompt payload를 받아 LLM raw text를 반환하는 caller 패턴. parser/normalizer와 책임을 분리하는 데 참고한다. |
| `10_normalize_intent_plan.py` | Normalize Intent Plan | 이 flow에서 가장 중요한 normalizer 예시. LLM intent를 route, retrieval job, filter, metric contract로 정리한다. |
| `11_intent_route_router.py` | Intent Route Router | `group_outputs=True`를 쓰는 branch router 예시. inactive branch payload 처리도 함께 본다. |
| `12_flow_text_request_builder_data_retrieval.py` | Flow Text Request Builder - Data Retrieval | main flow에서 Run Flow로 compact JSON text를 넘기는 bridge request builder. |
| `13_flow_text_response_adapter_data_retrieval.py` | Flow Text Response Adapter - Data Retrieval | Run Flow output text를 다시 `Data` payload로 복원하는 adapter. |
| `14_mongodb_data_loader_followup.py` | MongoDB Data Loader - Follow-up | `data_ref`로 저장된 이전 row data를 후속 분석용으로 복원하는 패턴. |
| `15_current_data_retriever.py` | Current Data Retriever | state 안의 `current_data`를 후속 질문의 retrieval payload로 바꾸는 패턴. |
| `17_retrieval_payload_merger.py` | Retrieval Payload Merger | data retrieval branch와 follow-up branch를 하나의 retrieval payload로 합치는 branch merger. |
| `18_retrieval_postprocess_router.py` | Retrieval Postprocess Router | 조회 결과를 direct answer와 pandas post-analysis branch로 나누는 router. |
| `20_build_pandas_prompt.py` | Build Pandas Prompt | retrieval payload, domain metric, preview rows를 이용해 분석 code 계획 prompt를 만드는 패턴. |
| `22_normalize_pandas_plan.py` | Normalize Pandas Plan | LLM이 만든 pandas plan/code를 실행 가능한 계약으로 정리하는 normalizer. |
| `23_pandas_analysis_executor.py` | Pandas Analysis Executor | 제한된 pandas 분석 실행 패턴. LLM code 실행을 분리하고 방어해야 하는 이유를 보기 좋다. |
| `24_analysis_result_merger.py` | Analysis Result Merger | early/direct/pandas branch 결과를 final answer 전 하나로 합치는 merger. |
| `25_mongodb_data_store.py` | MongoDB Data Store | 큰 row list를 MongoDB에 저장하고 flow payload에는 compact `data_ref`를 남기는 패턴. |
| `26_build_final_answer_prompt.py` | Build Final Answer Prompt | analysis result를 사용자 답변용 prompt로 만드는 final prompt builder. |
| `28_normalize_answer_text.py` | Normalize Answer Text | final answer LLM output을 안정적인 answer text로 보정하는 node. |
| `29_final_answer_builder.py` | Final Answer Builder | 최종 payload, chat message, next state를 함께 만드는 핵심 node. |
| `30_state_memory_message_builder.py` | State Memory Message Builder | 다음 turn을 위해 compact state snapshot message를 만드는 memory writer. |
| `31_api_response_builder.py` | API Response Builder | 웹/API client가 읽기 쉬운 compact JSON response를 만드는 예시. final output shaping에 유용하다. |

특히 처음 학습할 때는 다음 순서로 읽으면 좋다.

```text
01 State Loader
  -> 08 Build Intent Prompt
  -> 10 Normalize Intent Plan
  -> 11 Intent Route Router
  -> 17 Retrieval Payload Merger
  -> 18 Retrieval Postprocess Router
  -> 23 Pandas Analysis Executor
  -> 29 Final Answer Builder
  -> 30 State Memory Message Builder
  -> 31 API Response Builder
```

이 순서는 "질문이 들어와서 state가 되고, intent가 되고, branch를 타고, retrieval/analysis를 거쳐, 답변과 memory가 되는 흐름"을 가장 빠르게 보여준다.

### 17.2 Data Retrieval Flow에서 참고할 노드

아래 파일들은 `langflow_main/2.data_retrieval_flow_components/`에 있다. main flow와 별도 Run Flow로 연결되는 source 조회 전용 node들이다.

| 파일 | Langflow node | 재사용/학습 포인트 |
| --- | --- | --- |
| `00_flow_text_input_adapter_data_retrieval.py` | Flow Text Input Adapter - Data Retrieval | Run Flow input text를 payload로 복원하는 adapter. subflow를 tool/bridge처럼 쓸 때 참고한다. |
| `01_dummy_data_retriever.py` | Dummy Data Retriever | DB/API 없이 wiring과 regression을 검증하는 deterministic retriever. 새 flow 개발 초기에 아주 유용하다. |
| `02_oracle_query_retriever.py` | Oracle Query Retriever | catalog-driven SQL retrieval 패턴. source config를 보고 query를 실행하고 실패 시 source result로 정리한다. |
| `03_h_api_retriever.py` | H-API Retriever | internal HTTP API retrieval 패턴. request body, timeout, response normalization을 참고한다. |
| `04_datalake_retriever.py` | Datalake Retriever | runtime endpoint discovery가 필요한 복잡한 external source retriever 예시. code-managed config와 input surface 경계를 볼 수 있다. |
| `05_goodocs_retriever.py` | Goodocs Retriever | document/source API retrieval 패턴. row data가 아닌 문서형 evidence를 다룰 때 참고한다. |
| `06_source_retrieval_merger.py` | Source Retrieval Merger | Oracle, H-API, Datalake, Goodocs 결과를 표준 retrieval payload로 합치는 source merger. |
| `07_flow_text_output_builder_data_retrieval.py` | Flow Text Output Builder - Data Retrieval | subflow 결과를 main flow가 읽을 JSON text response로 만드는 output adapter. |

새 source를 붙일 때는 `02/03/04/05` 중 source 성격이 가장 비슷한 node를 참고한다. 예를 들어 REST API면 `03_h_api_retriever.py`, SQL이면 `02_oracle_query_retriever.py`, runtime endpoint 조회가 필요하면 `04_datalake_retriever.py`가 출발점이다.

### 17.3 Authoring Flow에서 참고할 노드

`langflow_main/3.domain_authoring_flow_components/`, `4.table_catalog_authoring_flow_components/`, `5.main_flow_filters_authoring_flow_components/`는 운영자가 prose로 작성한 지식을 MongoDB item으로 정리하기 위한 helper flow이다.

학습 포인트:

- raw text refinement prompt를 별도 template file로 분리하는 방식
- LLM 결과를 authoring result schema로 normalize하는 방식
- review 단계와 save 단계가 분리된 구조
- MongoDB writer가 `dry_run`, `merge/replace` 같은 운영 옵션을 제공하는 방식
- 비개발자가 작성한 설명을 안정적인 domain/table/filter metadata로 바꾸는 흐름

새 agent가 metadata-driven 구조라면 answer flow만 만들지 말고 authoring flow도 함께 설계하는 것이 좋다. 운영자가 metadata를 계속 수정할 수 있어야 Python 코드를 매번 고치지 않아도 된다.

### 17.4 그대로 재사용할지, 패턴만 참고할지 판단하는 기준

| 상황 | 권장 |
| --- | --- |
| 같은 `langflow_main` agent를 유지보수한다 | 기존 node를 직접 수정하고 component detail 문서도 같이 갱신한다. |
| 같은 payload contract를 쓰는 새 제조/데이터 agent를 만든다 | `State Loader`, `Intent Router`, `Retrieval Merger`, `API Response Builder`는 복사 후 이름/metadata만 조정한다. |
| 완전히 다른 업무 agent를 만든다 | 기존 node의 helper 구조, error payload, branch pattern만 참고하고 domain/table key는 새로 설계한다. |
| 새 source retriever를 만든다 | 기존 source retriever 중 가장 가까운 것을 복사해서 output shape만 `source_result` contract에 맞춘다. |
| Tool Mode 기반 간단 agent를 만든다 | 전체 main flow를 복사하지 말고 small tool node와 `Run Flow` tool 연결 패턴만 참고한다. |

기존 node를 복사할 때 반드시 확인할 것:

- `display_name`, `name`, `description`이 새 업무에 맞는가?
- input field 중 secret/config를 운영자가 직접 넣어야 하는지, 코드 관리해야 하는지 결정했는가?
- output payload key를 downstream이 그대로 기대하는가?
- 제조 domain에만 맞는 key나 설명이 남아 있지 않은가?
- `data_ref`, `current_data`, `followup_source_results`가 필요한 flow인가?
- node 파일이 standalone으로 실행될 수 있는가?

### 17.5 현재 구현에는 없지만 추가하면 좋은 공통 노드

현재 repo를 기준으로 보면 Excel 업로드 전용 node와 이미지/PPT/PDF를 LLM으로 설명 텍스트로 바꾸는 multimodal document node는 별도 구현되어 있지 않다. 실제 agent 교육/확장 관점에서는 두 node 모두 넣을 가치가 크다.

#### Excel Dataset Loader

Excel Dataset Loader는 `FileInput`으로 `.xlsx`, `.xls`, `.xlsm` 파일을 받아 sheet별 row data와 metadata를 반환하는 node이다. CSV loader보다 운영자가 쓰기 쉽고, 제조/업무 현장 데이터는 Excel 형태로 전달되는 경우가 많다.

권장 input:

| Input | Type | 설명 |
| --- | --- | --- |
| `excel_file` | `FileInput` | 업로드한 Excel 파일 |
| `sheet_name` | `MessageTextInput` 또는 `DropdownInput` | 읽을 sheet 이름. 비우면 첫 sheet 또는 전체 sheet |
| `read_all_sheets` | `BoolInput` | 모든 sheet를 읽을지 여부 |
| `header_row` | `IntInput` | header row 위치. 기본 0 |
| `preview_limit` | `IntInput` | preview row 개수 |
| `include_rows` | `BoolInput` | 전체 rows를 payload에 포함할지 여부. 큰 파일이면 false 권장 |

권장 output:

```json
{
  "success": true,
  "source_name": "excel_upload",
  "file_name": "sample.xlsx",
  "sheets": [
    {
      "sheet_name": "Sheet1",
      "row_count": 120,
      "columns": ["date", "product", "qty"],
      "preview_rows": [],
      "rows": []
    }
  ],
  "selected_sheet": "Sheet1",
  "rows": [],
  "row_count": 120,
  "columns": ["date", "product", "qty"],
  "errors": [],
  "warnings": []
}
```

구현 포인트:

- `pandas.read_excel()`을 쓰면 구현이 가장 단순하다.
- `.xlsx`를 읽으려면 보통 `openpyxl` dependency가 필요하다. 현재 `requirements.txt`에는 `pandas`만 있고 `openpyxl`은 없으므로 실제 node를 추가할 때 dependency도 같이 추가해야 한다.
- `.xls`까지 지원하려면 환경에 따라 `xlrd`가 필요할 수 있다.
- 큰 Excel 파일은 `rows` 전체를 넘기지 말고 `preview_rows`, `row_count`, `columns`, `data_ref` 중심으로 넘긴다.
- 여러 sheet를 읽을 때는 `source_results`처럼 sheet별 결과를 분리하고, 하나의 sheet만 분석할 때만 top-level `rows`로 올린다.
- 날짜/숫자 타입은 JSON 직렬화 가능한 문자열/숫자로 변환한다.

간단 skeleton:

```python
class ExcelDatasetLoader(Component):
    display_name = "Excel Dataset Loader"
    description = "Load Excel sheets into normalized row payloads."
    icon = "Sheet"
    name = "ExcelDatasetLoader"

    inputs = [
        FileInput(name="excel_file", display_name="Excel File", required=True),
        MessageTextInput(name="sheet_name", display_name="Sheet Name", value="", required=False),
        BoolInput(name="read_all_sheets", display_name="Read All Sheets", value=False, advanced=True),
        IntInput(name="header_row", display_name="Header Row", value=0, advanced=True),
        IntInput(name="preview_limit", display_name="Preview Limit", value=20, advanced=True),
        BoolInput(name="include_rows", display_name="Include Rows", value=True, advanced=True),
    ]

    outputs = [
        Output(name="dataset_payload", display_name="Dataset Payload", method="build_dataset", types=["Data"]),
    ]

    def build_dataset(self) -> Data:
        path = _file_paths_from_value(getattr(self, "excel_file", None))[0]
        sheet_name = str(getattr(self, "sheet_name", "") or "").strip() or 0
        read_all = _as_bool(getattr(self, "read_all_sheets", False))
        header_row = _clamp_int(getattr(self, "header_row", 0), 0, 0, 50)
        preview_limit = _clamp_int(getattr(self, "preview_limit", 20), 20, 0, 100)
        include_rows = _as_bool(getattr(self, "include_rows", True), True)

        try:
            import pandas as pd
            loaded = pd.read_excel(path, sheet_name=None if read_all else sheet_name, header=header_row)
        except ImportError as exc:
            message = f"Excel dependency is missing: {exc}. Install openpyxl for .xlsx files."
            return Data(data={"success": False, "errors": [message], "rows": []})
        except Exception as exc:
            message = f"Failed to read Excel file: {exc}"
            return Data(data={"success": False, "errors": [message], "rows": []})

        frames = loaded if isinstance(loaded, dict) else {str(sheet_name): loaded}
        sheets = []
        for name, frame in frames.items():
            rows = frame.where(frame.notna(), None).to_dict(orient="records")
            columns = [str(column) for column in frame.columns]
            sheets.append({
                "sheet_name": str(name),
                "row_count": len(rows),
                "columns": columns,
                "preview_rows": rows[:preview_limit],
                "rows": rows if include_rows else [],
            })

        first = sheets[0] if sheets else {"rows": [], "columns": [], "row_count": 0, "sheet_name": ""}
        return Data(data={
            "success": True,
            "source_name": "excel_upload",
            "file_name": path.name,
            "sheets": sheets,
            "selected_sheet": first["sheet_name"],
            "rows": first["rows"],
            "row_count": first["row_count"],
            "columns": first["columns"],
            "errors": [],
            "warnings": [],
        })
```

#### Multimodal Document to Text Node

이 node는 이미지, PDF, PPT/PPTX 같은 비정형 파일을 입력받아 LLM이 읽을 수 있는 텍스트 설명 payload로 바꾸는 역할을 한다.

중요한 점은 현재 repo의 `LLM JSON Caller`는 prompt 문자열만 `llm.invoke(prompt)`로 보내는 구조라는 것이다. 따라서 현재 형태 그대로는 이미지 분석 node로 쓰기 어렵다. 이미지/PDF/PPT 내용을 분석하려면 아래 두 방식 중 하나를 선택해야 한다.

| 방식 | 설명 | 기존 LLM JSON Caller 사용 가능 여부 |
| --- | --- | --- |
| 텍스트 추출 후 LLM | PDF text, PPT text box, OCR 결과를 먼저 텍스트로 추출한 뒤 prompt로 전달 | 가능 |
| Vision/multimodal LLM 직접 호출 | 이미지 bytes/base64 또는 file part를 model에 함께 전달 | 현재 caller로는 부족. 별도 `Multimodal LLM Caller` 필요 |

권장 분리:

```text
FileInput
  -> Document Extractor
  -> Text Chunk / Summary Prompt Builder
  -> LLM JSON Caller
  -> Document Summary Normalizer
```

이미지나 스캔 PDF처럼 텍스트 추출이 안 되는 파일은:

```text
FileInput
  -> Multimodal Prompt Builder
  -> Multimodal LLM Caller
  -> Vision Summary Normalizer
```

권장 input:

| Input | Type | 설명 |
| --- | --- | --- |
| `document_file` | `FileInput` | 이미지, PDF, PPT/PPTX |
| `analysis_instruction` | `MultilineInput` | 무엇을 설명할지 지시. 예: 핵심 내용, 표, 리스크, 액션 아이템 |
| `extract_mode` | `DropdownInput` | `auto`, `text_only`, `vision`, `ocr_first` |
| `max_pages` | `IntInput` | PDF/PPT 최대 처리 page/slide |
| `include_page_details` | `BoolInput` | page별 설명 포함 여부 |
| `llm_api_key` | `SecretStrInput` | vision LLM을 직접 호출할 때만 |
| `model_name` | `MessageTextInput` | vision-capable model |

권장 output:

```json
{
  "success": true,
  "source_name": "document_upload",
  "file_name": "report.pdf",
  "file_type": "pdf",
  "extracted_text": "...",
  "document_summary": "...",
  "page_summaries": [
    {"page": 1, "text": "...", "summary": "..."}
  ],
  "tables": [],
  "images": [],
  "errors": [],
  "warnings": []
}
```

구현 포인트:

- PDF가 text PDF라면 `pypdf`, `pdfplumber`, `PyMuPDF` 같은 라이브러리로 text를 먼저 추출하는 편이 비용이 낮다.
- scanned PDF나 이미지 기반 slide는 OCR 또는 vision model이 필요하다.
- PPT/PPTX는 `python-pptx`로 slide text를 먼저 추출할 수 있다. slide를 이미지로 렌더링해 vision model에 보내는 방식은 환경 의존성이 더 크다.
- 이미지 파일은 `Pillow`로 크기/포맷을 확인하고, 너무 큰 이미지는 resize하거나 page limit을 둔다.
- 문서 전체를 한 번에 LLM에 넣지 말고 page/slide별 summary를 만든 뒤 최종 summary로 합치는 map-reduce 구조가 안정적이다.
- 개인/민감 정보가 있을 수 있으므로 원본 파일 bytes를 debug payload에 넣지 않는다.

멀티모달 caller skeleton은 provider별 SDK 차이가 커서 일반 LLM caller와 분리하는 것이 안전하다.

```python
class MultimodalDocumentToText(Component):
    display_name = "Multimodal Document To Text"
    description = "Convert images, PDFs, or PPT files into text descriptions using extraction or a vision-capable LLM."
    icon = "ScanText"
    name = "MultimodalDocumentToText"

    inputs = [
        FileInput(name="document_file", display_name="Document File", required=True),
        DropdownInput(name="extract_mode", display_name="Extract Mode", options=["auto", "text_only", "vision"], value="auto"),
        MultilineInput(name="analysis_instruction", display_name="Analysis Instruction", value="Summarize the document faithfully."),
        IntInput(name="max_pages", display_name="Max Pages", value=10, advanced=True),
        BoolInput(name="include_page_details", display_name="Include Page Details", value=True, advanced=True),
        SecretStrInput(name="llm_api_key", display_name="LLM API Key", required=False, advanced=True),
        MessageTextInput(name="model_name", display_name="Vision Model Name", value="", advanced=True),
    ]

    outputs = [
        Output(name="document_text", display_name="Document Text", method="build_document_text", types=["Data"]),
    ]

    def build_document_text(self) -> Data:
        path = _file_paths_from_value(getattr(self, "document_file", None))[0]
        suffix = path.suffix.lower()
        mode = str(getattr(self, "extract_mode", "auto") or "auto")

        if mode in {"auto", "text_only"} and suffix in {".pdf", ".pptx"}:
            extracted = _extract_text_without_llm(path)
            if extracted.get("text") or mode == "text_only":
                return Data(data={
                    "success": bool(extracted.get("text")),
                    "source_name": "document_upload",
                    "file_name": path.name,
                    "file_type": suffix.lstrip("."),
                    "extracted_text": extracted.get("text", ""),
                    "page_summaries": extracted.get("pages", []),
                    "errors": extracted.get("errors", []),
                    "warnings": extracted.get("warnings", []),
                })

        # Vision mode needs a provider-specific implementation.
        # The current text-only LLM JSON Caller is not enough because it does not send file/image parts.
        vision_result = _call_vision_model(path, getattr(self, "analysis_instruction", ""), getattr(self, "llm_api_key", ""), getattr(self, "model_name", ""))
        return Data(data=vision_result)
```

이 node를 실제 구현하려면 helper를 provider와 dependency에 맞게 채워야 한다.

- `_extract_text_without_llm`: PDF/PPT text extraction.
- `_call_vision_model`: OpenAI, Gemini, Azure, local VLM 등 실제 vision-capable model 호출.
- `_file_to_parts`: image bytes/base64 또는 provider-specific file part 생성.
- `_page_limit`: PDF/PPT page 수 제한.

## 18. 전체 Agent Flow 구현 예시 3개

아래 예시는 실제 개발자가 "어떤 node들을 어떤 순서로 만들고 연결할지"를 잡기 위한 flow blueprint이다.

### 18.1 Flow A: 제조 데이터 조회/분석 DAG agent

목표:

- 사용자가 자연어로 제조 데이터를 묻는다.
- agent가 필요한 dataset과 filter를 결정한다.
- source에서 데이터를 조회한다.
- 필요한 경우 pandas 분석을 수행한다.
- evidence 기반 최종 답변과 다음 turn state를 만든다.

권장 canvas:

```text
Chat Input
  -> State Loader

Message History
  -> State Memory Extractor
  -> State Loader.previous_state

MongoDB Domain Loader OR Domain JSON Loader
MongoDB Table Catalog Loader OR Table Catalog Loader
MongoDB Main Flow Filters Loader OR Main Flow Filters Loader

State Loader + Domain + Table Catalog + Main Filters
  -> Intent Prompt Builder
  -> LLM JSON Caller - Intent
  -> Intent JSON Parser
  -> Intent Normalizer
  -> Intent Route Router

Intent Route Router.data_retrieval
  -> Data Retrieval Request Builder
  -> Run Flow - Data Retrieval
  -> Data Retrieval Response Adapter
  -> Retrieval Merger

Optional uploaded Excel path:
Excel Dataset Loader
  -> Retrieval Merger

Intent Route Router.followup_transform
  -> Data Ref Loader
  -> Current Data Retriever
  -> Retrieval Merger

Intent Route Router.finish
  -> Early Result Adapter
  -> Analysis Result Merger

Retrieval Merger
  -> Postprocess Router

Postprocess Router.direct_response
  -> Direct Result Adapter
  -> Analysis Result Merger

Postprocess Router.post_analysis
  -> Pandas Prompt Builder
  -> LLM JSON Caller - Pandas
  -> Pandas Plan Parser
  -> Pandas Plan Normalizer
  -> Pandas Analysis Executor
  -> Analysis Result Merger

Analysis Result Merger
  -> Data Store Writer
  -> Final Answer Prompt Builder
  -> LLM JSON Caller - Answer
  -> Answer JSON Parser
  -> Answer Text Normalizer
  -> Final Answer Builder
  -> State Memory Message Builder
  -> Message History Store

Final Answer Builder
  -> API Response Builder
  -> Chat Output / Run API response
```

핵심 payload 흐름:

| 단계 | payload |
| --- | --- |
| State Loader | `agent_state.pending_user_question`, `current_data` |
| Metadata Loader | `domain_payload`, `table_catalog_payload`, `main_flow_filters_payload` |
| Intent Normalizer | `intent_plan.route`, `retrieval_jobs`, `filters`, `required_params` |
| Retrieval Flow | `source_results`, `rows`, `row_count`, `columns`, `applied_filters` |
| Postprocess | `analysis_result`, `pandas_execution_status`, `answer_fit` |
| Final | `answer_message`, `current_data`, `next_state`, `data_ref` |

언제 이 flow를 선택하는가:

- 데이터 정확도와 재현성이 중요하다.
- route와 evidence를 canvas에서 눈으로 추적해야 한다.
- 후속 질문에서 이전 source data를 재사용해야 한다.
- 여러 공정/업무로 확장해야 하므로 metadata-driven 구조가 필요하다.

### 18.2 Flow B: 문서 RAG + 업무 도구 agent

목표:

- 사용자가 정책, 매뉴얼, 업무 절차를 묻는다.
- agent가 문서 검색과 필요 시 업무 API/tool을 함께 사용한다.
- 답변에는 근거 문서와 tool result를 분리해서 표시한다.

권장 canvas:

```text
Chat Input
  -> State Loader
  -> Query Rewrite Prompt Builder
  -> LLM JSON Caller - Query Rewrite
  -> Query Parser

Optional uploaded document path:
PDF / PPT / Image Input
  -> Multimodal Document To Text
  -> Evidence Merger

Query Parser.search_query
  -> Vector Search Retriever
  -> Document Result Normalizer

Query Parser.tool_intent
  -> Tool Selection Router

Tool Selection Router.api_lookup
  -> External API Retriever

Tool Selection Router.mcp_tool
  -> MCP Gateway Tool Caller

Document Result Normalizer + API Retriever + MCP Gateway Tool Caller
  -> Evidence Merger
  -> Answer Prompt Builder
  -> LLM JSON Caller - Answer
  -> Citation/Answer Normalizer
  -> Final Answer Builder
  -> Memory Writer
```

주요 node:

| Node | 구현 방식 |
| --- | --- |
| Query Rewrite Prompt Builder | 질문을 검색 query, tool intent, answer mode로 분리하는 JSON prompt 생성 |
| Vector Search Retriever | query와 top_k를 받아 documents/snippets 반환 |
| Document Result Normalizer | 문서 title, url, snippet, score를 표준화 |
| Tool Selection Router | LLM이 고른 tool intent를 branch로 나눔 |
| MCP Gateway Tool Caller | MCP server를 직접 품지 않고 HTTP gateway로 호출 |
| Evidence Merger | documents와 tool_results를 분리해서 final prompt에 전달 |
| Citation/Answer Normalizer | 답변, 근거 문서 id, tool 사용 내역을 schema로 정리 |

권장 evidence payload:

```json
{
  "evidence": {
    "documents": [
      {"doc_id": "policy-1", "title": "휴가 정책", "url": "...", "snippet": "..."}
    ],
    "tool_results": [
      {"tool_name": "employee_lookup", "success": true, "summary": "..."}
    ]
  }
}
```

언제 이 flow를 선택하는가:

- 답변 근거가 문서와 tool result 양쪽에서 온다.
- Agent가 임의로 tool을 반복 호출하기보다 검색, tool, 답변 단계를 통제하고 싶다.
- citation/근거 표시가 중요하다.

### 18.3 Flow C: Tool Mode 기반 경량 action agent

목표:

- 여러 small tool을 Agent component에 연결한다.
- Agent가 사용자 질문을 보고 필요한 tool을 선택한다.
- 각 tool은 독립 custom component로 구현한다.

권장 canvas:

```text
Chat Input
  -> Agent
  -> Chat Output

Dataset Catalog Tool.tool
  -> Agent.tools

File Dataset Summary Tool.tool
  -> Agent.tools

External API Lookup Tool.tool
  -> Agent.tools

Run Flow - Data Retrieval.tool
  -> Agent.tools
```

Tool node 예:

| Tool | `tool_mode=True` input | output |
| --- | --- | --- |
| Dataset Catalog Tool | `dataset_key` | dataset metadata |
| File Dataset Summary Tool | `question`, `file_id` | file summary/statistics |
| External API Lookup Tool | `lookup_key` | normalized API result |
| Domain Alias Tool | `term` | matched domain item/aliases |
| Run Flow Data Retrieval Tool | flow input text | retrieval answer |

Tool Mode 설계 기준:

- tool 설명은 "언제 쓰는지, 어떤 input이 필요한지, 무엇을 반환하는지"를 포함한다.
- Agent가 직접 채우는 argument에만 `tool_mode=True`를 붙인다.
- secret, endpoint, timeout, debug flag는 일반 input/advanced input으로 두고 tool argument로 열지 않는다.
- tool output은 작게 유지한다.
- tool이 큰 데이터를 만들면 `data_ref` 또는 summary만 반환한다.

언제 이 flow를 선택하는가:

- PoC나 내부 도구처럼 빠르게 만들고 검증해야 한다.
- tool 수가 적고, 잘못된 tool 호출의 위험이 낮다.
- Agent의 자연스러운 tool 선택을 활용하고 싶다.

주의:

- 데이터 정확도와 audit trail이 중요하면 Flow A 같은 고정 DAG가 더 적합하다.
- 같은 tool 반복 호출, 비용 증가, 불안정한 reasoning을 막기 위해 Agent 설정에서 max iterations를 제한한다.
- 운영 flow에서는 tool 결과를 최종 답변 전에 normalizer/evidence merger로 한 번 정리하는 구조를 고려한다.

## 19. 실전 예시: File dataset loader

아래 node는 `FileInput`, `DropdownInput`, `BoolInput`, `IntInput`을 함께 사용하는 예시이다. CSV, JSON, JSONL, TXT, Markdown, Excel 파일을 읽고, downstream이 쓰기 쉬운 `Data` payload로 변환한다.

기본 `Read File`은 PDF/DOCX/PPTX처럼 문서를 읽어 텍스트나 markdown으로 넘기는 범용 노드에 가깝다. `File Dataset Loader`는 그 대체품이라기보다, 사내 데이터셋을 `row_count`, `columns`, `preview_rows`, `warnings`, `rows` 같은 동일한 계약으로 맞춰 downstream component가 같은 방식으로 읽게 만드는 adapter 예시이다.

```python
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from lfx.custom import Component
from lfx.io import BoolInput, DropdownInput, FileInput, IntInput, Output
from lfx.schema import Data


ALLOWED_FILE_TYPES = ["csv", "json", "jsonl", "txt", "md", "markdown", "mdx", "xlsx", "xls", "xlsm"]


def _file_paths_from_value(value: Any) -> list[Path]:
    values = value if isinstance(value, list) else [value]
    paths: list[Path] = []
    for item in values:
        if item is None:
            continue
        path_value = (
            getattr(item, "path", None)
            or getattr(item, "file_path", None)
            or getattr(item, "name", None)
            or item
        )
        if isinstance(path_value, str) and path_value.strip():
            paths.append(Path(path_value).expanduser())
    return paths


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def _detect_mode(path: Path, selected_mode: str) -> str:
    mode = str(selected_mode or "auto").lower()
    if mode != "auto":
        return mode
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"md", "markdown", "mdx"}:
        return "markdown"
    if suffix in {"xlsx", "xls", "xlsm"}:
        return "excel"
    if suffix in {"csv", "json", "jsonl"}:
        return suffix
    return "text"


def _read_rows(path: Path, mode: str) -> tuple[list[dict[str, Any]], str]:
    if mode == "csv":
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = [dict(row) for row in csv.DictReader(file)]
        return rows, ""

    if mode == "json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)], ""
        if isinstance(payload, dict):
            for key in ("rows", "data", "items"):
                if key in payload:
                    rows = payload.get(key)
                    if isinstance(rows, list):
                        return [row for row in rows if isinstance(row, dict)], ""
                    if isinstance(rows, dict):
                        return [rows], ""
                    return [], ""
            return [payload], ""
        return [], ""

    if mode == "jsonl":
        rows = []
        with path.open("r", encoding="utf-8-sig") as file:
            for line in file:
                text = line.strip()
                if not text:
                    continue
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    rows.append(parsed)
        return rows, ""

    if mode == "excel":
        import pandas as pd

        sheets = pd.read_excel(path, sheet_name=None)
        rows = []
        for sheet_name, frame in sheets.items():
            for record in frame.to_dict(orient="records"):
                row = {"_sheet": str(sheet_name)}
                row.update({str(key): _json_safe(value) for key, value in record.items()})
                rows.append(row)
        return rows, ""

    text = path.read_text(encoding="utf-8-sig")
    rows = [{"line_number": index + 1, "text": line} for index, line in enumerate(text.splitlines())]
    return rows, text


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(str(key))
    return columns


class FileDatasetLoader(Component):
    display_name = "File Dataset Loader"
    description = "Load CSV, JSON, JSONL, TXT, Markdown, or Excel files into a normalized Data payload."
    icon = "FileText"
    name = "FileDatasetLoader"

    inputs = [
        FileInput(
            name="dataset_file",
            display_name="Dataset File",
            info="CSV, JSON, JSONL, TXT, Markdown, or Excel file.",
            file_types=ALLOWED_FILE_TYPES,
            required=True,
        ),
        DropdownInput(
            name="parse_mode",
            display_name="Parse Mode",
            options=["auto", "csv", "json", "jsonl", "text", "markdown", "excel"],
            value="auto",
        ),
        BoolInput(
            name="include_preview",
            display_name="Include Preview",
            value=True,
            advanced=True,
        ),
        IntInput(
            name="preview_limit",
            display_name="Preview Limit",
            value=20,
            advanced=True,
        ),
    ]

    outputs = [
        Output(name="dataset", display_name="Dataset", method="build_dataset", types=["Data"]),
    ]

    def build_dataset(self) -> Data:
        paths = _file_paths_from_value(getattr(self, "dataset_file", None))
        if not paths:
            message = "No file was provided."
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message]})

        path = paths[0]
        if not path.exists():
            message = f"File not found: {path}"
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message]})

        mode = _detect_mode(path, str(self.parse_mode or "auto"))
        preview_limit = _clamp_int(self.preview_limit, default=20, minimum=0, maximum=100)
        include_preview = _as_bool(self.include_preview, default=True)

        try:
            rows, text = _read_rows(path, mode)
        except Exception as exc:
            message = f"Failed to read file: {exc}"
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message]})

        result = {
            "success": True,
            "source_name": "uploaded_file",
            "file_name": path.name,
            "file_type": mode,
            "rows": rows,
            "row_count": len(rows),
            "columns": _columns(rows),
            "preview_rows": rows[:preview_limit] if include_preview else [],
            "text": text,
            "text_chars": len(text),
            "errors": [],
            "warnings": [],
        }
        self.status = f"Loaded {len(rows)} rows from {path.name}" if rows else f"Loaded text from {path.name}"
        return Data(data=result)
```

운영 단계에서는 큰 파일을 바로 `rows`에 담기보다 storage writer node를 붙여 `data_ref`를 만들고, downstream에는 preview와 ref만 넘긴다.

## 20. 실전 예시: Secret + Bool + Dropdown 외부 API retriever

아래 node는 외부 HTTP API 호출 node의 기본 골격이다.

```python
from __future__ import annotations

import json
from typing import Any

import requests

from lfx.custom import Component
from lfx.io import BoolInput, DropdownInput, IntInput, MessageTextInput, MultilineInput, Output, SecretStrInput
from lfx.schema import Data


def _secret_to_text(value: object) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter() or "")
    return str(value or "")


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


class ExternalApiRetriever(Component):
    display_name = "External API Retriever"
    description = "Call an external API and return a normalized retrieval payload."
    icon = "Cloud"
    name = "ExternalApiRetriever"

    inputs = [
        MessageTextInput(name="api_url", display_name="API URL", required=True),
        DropdownInput(
            name="method",
            display_name="Method",
            options=["GET", "POST"],
            value="GET",
        ),
        DropdownInput(
            name="auth_type",
            display_name="Auth Type",
            options=["none", "bearer"],
            value="none",
            real_time_refresh=True,
            advanced=True,
        ),
        SecretStrInput(
            name="api_key",
            display_name="API Key",
            required=False,
            dynamic=True,
            show=False,
            advanced=True,
        ),
        MultilineInput(name="params_json", display_name="Params JSON", value="{}", advanced=True),
        IntInput(name="timeout_seconds", display_name="Timeout Seconds", value=30, advanced=True),
        BoolInput(name="include_raw_response", display_name="Include Raw Response", value=False, advanced=True),
    ]

    outputs = [
        Output(name="retrieval_payload", display_name="Retrieval Payload", method="call_api", types=["Data"]),
    ]

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name == "auth_type":
            show_secret = field_value == "bearer"
            build_config["api_key"]["show"] = show_secret
            build_config["api_key"]["required"] = show_secret
        return build_config

    def call_api(self) -> Data:
        api_url = str(self.api_url or "").strip()
        if not api_url:
            raise ValueError("API URL is required.")

        try:
            params = json.loads(str(self.params_json or "{}"))
            if not isinstance(params, dict):
                raise ValueError("Params JSON must be an object.")
        except Exception as exc:
            message = f"Invalid params_json: {exc}"
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message]})

        headers = {}
        if str(self.auth_type or "none") == "bearer":
            api_key = _secret_to_text(getattr(self, "api_key", None)).strip()
            if not api_key:
                message = "API key is required for bearer auth."
                self.status = message
                return Data(data={"success": False, "rows": [], "errors": [message]})
            headers["Authorization"] = f"Bearer {api_key}"

        timeout = _clamp_int(getattr(self, "timeout_seconds", 30), 30, 1, 120)
        method = str(self.method or "GET").upper()

        try:
            if method == "POST":
                response = requests.post(api_url, headers=headers, json=params, timeout=timeout)
            else:
                response = requests.get(api_url, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            try:
                payload = response.json() if response.content else {}
            except ValueError:
                payload = {"text": response.text.strip()} if response.text.strip() else {}
        except Exception as exc:
            message = f"API request failed: {exc}"
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message]})

        rows: list[Any]
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = None
            for key in ("rows", "data", "items", "result", "results", "records"):
                if key in payload:
                    rows = payload.get(key)
                    break
            if rows is None:
                rows = [payload] if payload else []
            elif isinstance(rows, dict):
                rows = [rows]
            elif not isinstance(rows, list):
                rows = [{"value": rows}]
        else:
            rows = []

        row_dicts = [row for row in rows if isinstance(row, dict)]
        result = {
            "success": True,
            "source_name": "external_api",
            "status_code": response.status_code,
            "rows": row_dicts,
            "row_count": len(row_dicts),
            "columns": sorted({key for row in row_dicts for key in row}),
            "applied_params": params,
            "errors": [],
            "warnings": [],
        }
        if _as_bool(getattr(self, "include_raw_response", False), default=False):
            result["raw_response"] = payload

        self.status = f"Loaded {len(row_dicts)} rows"
        return Data(data=result)
```

이 패턴에서 중요한 것은 secret을 출력하지 않는 것, timeout을 두는 것, 실패도 같은 payload shape으로 반환하는 것이다.

## 21. Parser와 Normalizer는 분리한다

LLM에게 JSON을 요청해도 실제 응답은 코드블록, 설명 문장, trailing comma, 빈 응답 등이 섞일 수 있다.

Parser node의 책임:

- raw text에서 JSON 후보를 찾는다.
- JSON parse 오류를 명확히 반환한다.
- parse된 dict/list를 `intent_raw`, `analysis_raw` 등으로 넘긴다.

Normalizer node의 책임:

- schema default를 채운다.
- alias를 표준 key로 바꾼다.
- route enum을 보정한다.
- domain/table catalog metadata와 맞춘다.
- downstream이 기대하는 payload key를 만든다.

Parser 예:

```python
def _strip_code_fence(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return value


def _parse_json_object(text: str) -> dict:
    cleaned = _strip_code_fence(text)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {"items": parsed}
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(cleaned[start:end + 1])
            return parsed if isinstance(parsed, dict) else {"items": parsed}
        raise
```

Normalizer 예:

```python
VALID_ROUTES = {"data_retrieval", "followup_transform", "finish"}


def _normalize_route(value: object) -> str:
    route = str(value or "").strip().lower()
    aliases = {
        "retrieval": "data_retrieval",
        "single_retrieval": "data_retrieval",
        "multi_retrieval": "data_retrieval",
        "followup": "followup_transform",
        "done": "finish",
    }
    route = aliases.get(route, route)
    return route if route in VALID_ROUTES else "finish"
```

## 22. 대용량 데이터와 `data_ref`

AI agent flow에서 큰 데이터를 계속 payload에 싣는 것은 금방 문제가 된다.

문제:

- LLM prompt가 커진다.
- UI가 느려진다.
- memory state가 비대해진다.
- API response가 불필요하게 커진다.

권장 구조:

```text
Retriever
  -> rows, row_count, columns, preview_rows
  -> Large Data Store Writer
  -> data_ref 생성
  -> downstream에는 data_ref + preview + summary 전달
```

payload 예:

```json
{
  "row_count": 12000,
  "columns": ["date", "product", "qty"],
  "preview_rows": [
    {"date": "2026-06-11", "product": "A", "qty": 10}
  ],
  "data_ref": {
    "ref_id": "analysis-results-abc123",
    "collection_name": "analysis_results",
    "row_count": 12000
  }
}
```

후속 질문에서는 최종 표시 데이터만 보지 말고, 원본 조회 source의 `data_ref`도 보존한다. 그래야 "그중에서 A제품만 다시 봐줘" 같은 질문에 원본 범위를 복원할 수 있다.

## 23. Memory state 설계

state에는 "다음 turn에 필요한 최소 정보"만 넣는다.

좋은 state:

```json
{
  "session_id": "default",
  "turn_id": 3,
  "chat_history": [],
  "context": {
    "last_intent": {"route": "data_retrieval", "dataset_hints": ["production"]}
  },
  "current_data": {
    "summary": "120 rows for production on 2026-06-11",
    "row_count": 120,
    "columns": ["date", "product", "qty"],
    "data_ref": {"ref_id": "final-ref", "row_count": 120},
    "followup_source_results": [
      {"dataset_key": "production", "data_ref": {"ref_id": "source-ref", "row_count": 5000}}
    ]
  }
}
```

나쁜 state:

```json
{
  "current_data": {
    "all_rows": [{ "...": "..." }, { "...": "..." }]
  }
}
```

state loader와 memory writer는 agent 품질을 크게 좌우한다. 질문이 틀렸을 때 LLM prompt만 보지 말고 state가 어떤 context를 들고 있는지 먼저 확인한다.

## 24. Standalone component 원칙

이 repo의 numbered Langflow component는 standalone을 목표로 한다.

권장:

```text
one_component.py
  -> imports from standard library / installed packages / lfx
  -> helper functions included in file
  -> Component class included in file
```

피하기:

```python
from langflow_main.services.domain import normalize_domain
from manufacturing_agent.runtime import run_query
```

이유:

- Langflow UI에 code를 붙여 넣거나 custom components path에 복사했을 때 sibling repo module이 없을 수 있다.
- 새 개발자가 node 하나만 봐도 동작을 이해할 수 있어야 한다.
- 배포 환경마다 Python path가 다르면 import bug가 생긴다.

반복 helper가 많아져도 초반에는 명시적으로 유지한다. 공통 패키지화는 배포 구조가 정해지고 테스트가 충분할 때만 한다.

## 25. Custom components path와 배포

Langflow가 custom component를 찾으려면 보통 category folder와 `__init__.py`가 필요하다.

예:

```text
custom_components/
  manufacturing/
    __init__.py
    file_dataset_loader.py
    external_api_retriever.py
```

`LANGFLOW_COMPONENTS_PATH`를 쓰는 경우:

```powershell
$env:LANGFLOW_COMPONENTS_PATH="C:\path\to\custom_components"
langflow run --port 7860
```

체크할 점:

- component file이 Langflow가 scan하는 경로에 있는가?
- category folder에 `__init__.py`가 있는가?
- 너무 깊은 하위 폴더에 있지 않은가?
- component code를 바꾼 뒤 Langflow reload 또는 restart를 했는가?
- 기존 canvas node가 cache된 code를 들고 있지 않은가?
- 바뀐 node는 삭제 후 새로 추가해 보았는가?

## 26. 검증 방법

문서와 code를 나누어 검증한다.

### 26.1 Python compile

```powershell
python -m compileall -q langflow_main tests
```

### 26.2 component import smoke test

```python
from pathlib import Path
import importlib.util
import sys

roots = [
    Path("langflow_main/1.main_flow_components"),
    Path("langflow_main/2.data_retrieval_flow_components"),
]

for root in roots:
    for path in sorted(root.glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)
        print(f"OK {path}")
```

### 26.3 repo test

```powershell
python -m pytest tests -q
```

### 26.4 whitespace check

```powershell
git diff --check
```

### 26.5 Langflow UI check

- node가 원하는 category와 이름으로 보이는가?
- input field가 main/advanced 영역에 의도대로 보이는가?
- secret field가 일반 텍스트처럼 노출되지 않는가?
- output port 개수와 타입 색상이 의도와 맞는가?
- 여러 output이 동시에 보여야 할 때 `group_outputs=True`가 적용되었는가?
- downstream node와 실제 연결되는가?
- 실행 후 `self.status`가 짧고 유용한가?
- output payload가 downstream에서 읽히는가?
- 큰 데이터가 prompt/state/API response로 과도하게 복사되지 않는가?

## 27. 개발자 훈련 로드맵

### Level 1. Single transform node

목표:

- `MessageTextInput`, `DataInput`, `Output`, `Data` 사용
- `_payload_from_value` helper 작성
- `self.status` 작성

실습:

- 입력 텍스트를 normalize해서 `Data(data={"text": ...})`로 반환한다.
- 잘못된 JSON을 넣으면 `success=False`, `errors`를 반환한다.

### Level 2. Parser / Normalizer node

목표:

- LLM raw text에서 JSON 파싱
- route enum 보정
- default field 채우기

실습:

- `{"route":"single_retrieval"}`을 `{"route":"data_retrieval"}`로 normalize한다.
- 코드블록 안의 JSON도 파싱한다.

### Level 3. File/API retriever node

목표:

- `FileInput`, `SecretStrInput`, `BoolInput`, `DropdownInput`, `IntInput` 사용
- timeout, preview, secret masking
- 표준 retrieval payload 작성

실습:

- CSV 파일을 읽어 row_count, columns, preview_rows를 반환한다.
- API key가 없을 때 secret을 노출하지 않는 오류 payload를 반환한다.

### Level 4. Router and merger

목표:

- `group_outputs=True`
- inactive branch payload
- merger가 active branch만 선택

실습:

- route 값에 따라 `data_retrieval`, `followup_transform`, `finish` output을 만든다.
- 잘못된 route는 `finish`로 보정한다.

### Level 5. Agent memory

목표:

- compact state 작성
- `current_data`, `data_ref`, `followup_source_results` 구조 이해
- 후속 질문 context 보존

실습:

- final result에서 다음 turn state를 만든다.
- 큰 rows 대신 data_ref와 preview만 남긴다.

### Level 6. Tool Mode / ReAct

목표:

- `tool_mode=True`
- Agent가 읽을 수 있는 tool description 작성
- tool output을 작게 유지

실습:

- dataset catalog lookup tool을 만든다.
- Agent가 tool argument로 채워야 하는 input과 운영자가 설정해야 하는 input을 분리한다.

### Level 7. Production hardening

목표:

- compile/import/test 자동화
- Langflow UI cache/reload 이슈 대응
- observability payload 설계
- domain rule을 metadata로 이동

실습:

- node별 component detail 문서를 작성한다.
- validation question set으로 regression을 돌린다.

## 28. 실수 체크리스트

연결이 안 될 때:

1. output method return annotation이 `-> Data`, `-> Message`, `-> DataFrame`인가?
2. `Output.method`와 실제 method 이름이 같은가?
3. `DataInput(input_types=["Data", "JSON"])`처럼 input port가 받을 타입을 열어두었는가?
4. 여러 output을 동시에 써야 하는데 `group_outputs=True`가 빠지지 않았는가?
5. 기존 canvas node가 cache된 code를 들고 있지는 않은가?
6. node를 삭제 후 새로 추가했는가?
7. plain `dict`를 반환하고 있지 않은가?
8. input field가 `advanced=True`나 `show=False`로 숨겨져 있지 않은가?

실행이 실패할 때:

1. 필수 input이 비어 있지 않은가?
2. JSON input에 코드블록 fence가 포함되어 있지 않은가?
3. 외부 API/DB timeout이 설정되어 있는가?
4. secret이 잘못되었을 때 오류가 masking되는가?
5. row가 없을 때 success/failure 기준이 명확한가?
6. downstream이 기대하는 key가 빠지지 않았는가?
7. route enum 오타가 normalizer에서 보정되는가?

Agent 답변이 틀릴 때:

1. state loader가 이전 context를 잘못 들고 있지 않은가?
2. domain/table catalog/main filter metadata가 최신인가?
3. prompt builder가 필요한 metadata를 빠뜨리지 않았는가?
4. LLM caller는 raw text만 반환하고 parser/normalizer가 보정하는가?
5. retriever 결과의 `applied_params`, `applied_filters`가 실제 질문과 맞는가?
6. pandas executor가 final display 데이터가 아니라 원본 source data를 사용해야 하는 상황은 아닌가?
7. final answer prompt가 evidence 없는 내용을 만들도록 열려 있지 않은가?

## 29. 새 node를 만들 때의 기본 템플릿

```python
from __future__ import annotations

import json
from typing import Any

from lfx.custom import Component
from lfx.io import BoolInput, DataInput, MessageTextInput, Output
from lfx.schema import Data


def _payload_from_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        return data
    text = getattr(value, "text", None) or getattr(value, "content", None)
    if isinstance(text, str) and text.strip():
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"text": text}
        except Exception:
            return {"text": text}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"text": value}
        except Exception:
            return {"text": value}
    return {}


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


class MyCustomNode(Component):
    display_name = "My Custom Node"
    description = "Explain this node in one sentence."
    icon = "Box"
    name = "MyCustomNode"

    inputs = [
        MessageTextInput(
            name="user_text",
            display_name="User Text",
            value="",
        ),
        DataInput(
            name="input_payload",
            display_name="Input Payload",
            input_types=["Data", "JSON"],
            required=False,
        ),
        BoolInput(
            name="include_debug",
            display_name="Include Debug",
            value=False,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            name="output_payload",
            display_name="Output Payload",
            method="build_output",
            types=["Data"],
        ),
    ]

    def build_output(self) -> Data:
        payload = _payload_from_value(getattr(self, "input_payload", None))
        result = {
            "success": True,
            "user_text": str(self.user_text or "").strip(),
            "input_payload": payload,
            "errors": [],
            "warnings": [],
        }
        if _as_bool(getattr(self, "include_debug", False)):
            result["debug"] = {
                "input_keys": sorted(payload.keys()),
            }
        self.status = "Output payload built"
        return Data(data=result, text=json.dumps(result, ensure_ascii=False, default=str))
```

## 30. 공식 참고 문서

- [Create custom Python components](https://docs.langflow.org/components-custom-components)
- [Components overview](https://docs.langflow.org/concepts-components)
- [Configure tools for agents](https://docs.langflow.org/agents-tools)
- [Dynamic Create Data](https://docs.langflow.org/dynamic-create-data)
