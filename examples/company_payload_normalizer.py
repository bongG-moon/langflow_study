from __future__ import annotations

import json
from typing import Any

# Langflow 코드창에 붙여넣을 때 이 import 줄을 포함해야 Component를 인식합니다.
from lfx.custom import Component
from lfx.io import BoolInput, DataInput, MessageTextInput, Output
from lfx.schema import Data


def _payload_from_value(value: Any) -> dict[str, Any]:
    # upstream component가 비어 있으면 표준 payload도 빈 dict로 시작합니다.
    # None을 그대로 흘리면 이후 `payload.get(...)` 같은 코드에서 실패할 수 있습니다.
    if value is None:
        return {}

    # 이미 dict라면 가장 이상적인 상태입니다. 불필요하게 복사하지 않고 그대로 씁니다.
    if isinstance(value, dict):
        return value

    # Langflow의 `Data` 객체는 보통 `.data` 속성에 JSON-like payload를 담습니다.
    # custom node 사이의 구조화 데이터 연결은 이 경로로 들어오는 경우가 많습니다.
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        return data

    # Message 또는 문자열 입력은 `.text`, `.content`, raw str 형태로 올 수 있습니다.
    # JSON 문자열이면 dict로 복원하고, 일반 문장이면 `text` 필드에 보존합니다.
    text = getattr(value, "text", None) or getattr(value, "content", None)
    if not text and isinstance(value, str):
        text = value
    if isinstance(text, str) and text.strip():
        try:
            parsed = json.loads(text)
            # list JSON도 버리지 않고 `items`로 감싸 downstream에서 읽을 수 있게 합니다.
            return parsed if isinstance(parsed, dict) else {"items": parsed}
        except Exception:
            # JSON이 아닌 일반 자연어 입력은 실패가 아니라 정상 text payload입니다.
            return {"text": text}

    # 모르는 타입은 예외를 내기보다 빈 payload로 정규화합니다.
    # 교육용 adapter node는 "흐름을 끊지 않는 것"이 중요합니다.
    return {}


def _as_bool(value: object, default: bool = False) -> bool:
    # Langflow UI 값은 bool 그대로 오기도 하고 "true"/"false" 문자열로 오기도 합니다.
    # 운영 환경 차이를 줄이기 위해 명시적으로 변환합니다.
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


class CompanyPayloadNormalizer(Component):
    display_name = "Company Payload Normalizer"
    description = "Normalize text and optional Data input into the company standard payload contract."
    icon = "Braces"
    name = "CompanyPayloadNormalizer"

    # inputs는 UI의 입력 필드이면서 동시에 연결 가능한 input port를 정의합니다.
    # MessageTextInput은 Agent Tool Mode에서 agent가 직접 채우기 좋은 짧은 텍스트용입니다.
    inputs = [
        MessageTextInput(
            name="request_text",
            display_name="Request Text",
            info="Natural-language request or short label to preserve in the payload.",
            value="",
            # tool_mode=True는 Agent가 이 값을 tool argument로 채울 수 있게 합니다.
            # API key나 대용량 payload에는 붙이지 않는 것이 안전합니다.
            tool_mode=True,
        ),
        DataInput(
            name="input_payload",
            display_name="Input Payload",
            info="Optional Data or JSON payload from an upstream node.",
            # Data와 JSON port를 모두 허용해서 Parser/Type Convert 결과를 쉽게 연결합니다.
            input_types=["Data", "JSON"],
            required=False,
            # advanced=True는 초보자가 처음 볼 때 화면을 단순하게 유지하는 용도입니다.
            advanced=True,
        ),
        BoolInput(
            name="include_debug",
            display_name="Include Debug",
            info="Include non-sensitive normalization details.",
            value=False,
            advanced=True,
        ),
    ]

    # Output의 method 이름은 실제 클래스 메서드명과 반드시 일치해야 합니다.
    # types=["Data"]로 지정하면 downstream DataInput/JSON 계열 port에 연결하기 쉽습니다.
    outputs = [
        Output(
            name="payload",
            display_name="Payload",
            method="build_payload",
            types=["Data"],
        )
    ]

    def build_payload(self) -> Data:
        # UI 입력값은 비어 있거나 None일 수 있으므로 문자열로 안전하게 정리합니다.
        request_text = str(getattr(self, "request_text", "") or "").strip()

        # upstream 값은 dict/Data/Message/JSON 문자열 등 다양한 형태일 수 있어 helper로 통일합니다.
        upstream = _payload_from_value(getattr(self, "input_payload", None))

        # 사내 표준 payload의 최소 필드를 먼저 고정합니다.
        # success/errors/warnings를 항상 넣으면 downstream component가 조건문을 단순하게 쓸 수 있습니다.
        result: dict[str, Any] = {
            "success": True,
            "request_text": request_text,
            "input_payload": upstream,
            "errors": [],
            "warnings": [],
        }

        if _as_bool(getattr(self, "include_debug", False)):
            # debug에는 민감한 원문 값 대신 구조 정보만 넣습니다.
            # 운영 로그에 남아도 부담이 적은 key 목록과 입력 존재 여부 정도가 적당합니다.
            result["debug"] = {
                "input_keys": sorted(upstream.keys()),
                "has_request_text": bool(request_text),
            }

        # self.status는 Langflow component 카드에 보이는 짧은 실행 상태입니다.
        self.status = "Payload normalized"

        # Data.data는 구조화 payload, Data.text는 Message/Chat Output으로 볼 때 유용한 문자열 표현입니다.
        # ensure_ascii=False를 써야 한국어가 \uXXXX로 깨져 보이지 않습니다.
        return Data(data=result, text=json.dumps(result, ensure_ascii=False, default=str))
