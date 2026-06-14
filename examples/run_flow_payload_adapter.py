from __future__ import annotations

import json
from typing import Any

# Run Flow 경계에서 자주 쓰는 `Message` 타입까지 import합니다.
# Langflow 코드창에 붙여넣을 때 이 import 줄을 포함해야 Component를 인식합니다.
from lfx.custom import Component
from lfx.io import DataInput, DropdownInput, IntInput, MessageTextInput, Output
from lfx.schema import Data
from lfx.schema.message import Message


def _payload_from_value(value: Any) -> dict[str, Any]:
    # 상위 flow에서 넘어오는 값은 Data, JSON dict, Message, JSON 문자열 등 다양합니다.
    # Run Flow로 보내기 전 dict 형태로 한 번 정규화합니다.
    if value is None:
        return {}
    if isinstance(value, dict):
        return value

    # Langflow Data output의 표준 구조화 payload 경로입니다.
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        return data

    # Message output이나 text input으로 넘어온 JSON 문자열을 복원합니다.
    # JSON이 아니면 일반 text payload로 감싸서 잃지 않습니다.
    text = getattr(value, "text", None) or getattr(value, "content", None)
    if isinstance(value, str):
        text = value
    if isinstance(text, str) and text.strip():
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"items": parsed}
        except Exception:
            return {"text": text}

    # 알 수 없는 타입은 실패시키지 않고 빈 payload로 처리합니다.
    return {}


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    # Run Flow가 text/message 경계만 받을 때 큰 JSON을 그대로 넘기면 느리고 불안정합니다.
    # max_chars로 잘라서 subflow 입력을 예측 가능한 크기로 유지합니다.
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n...[truncated]", True


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    # flow import/API 실행에서는 IntInput 값이 문자열로 들어올 수 있습니다.
    # 변환 실패 시 기본값을 쓰고, 너무 큰 payload가 Run Flow 경계로 넘어가지 않게 제한합니다.
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


class RunFlowPayloadAdapter(Component):
    display_name = "Run Flow Payload Adapter"
    description = "Serialize a structured Data payload into a Message that can be passed through a Run Flow text/message boundary."
    icon = "Workflow"
    name = "RunFlowPayloadAdapter"

    # 이 adapter는 "상위 flow의 구조화 payload"를 "하위 Run Flow가 받을 수 있는 Message"로 바꿉니다.
    # request_text는 Agent가 tool argument로 직접 채울 수 있는 짧은 지시문입니다.
    inputs = [
        MessageTextInput(
            name="request_text",
            display_name="Request Text",
            info="Short user request or subflow instruction. This is safe to expose in Tool Mode.",
            value="",
            # Agent가 Run Flow tool을 호출할 때 이 필드만 직접 채우도록 열어 둡니다.
            tool_mode=True,
        ),
        DataInput(
            name="payload",
            display_name="Payload",
            info="Structured payload from an upstream node. It will be serialized for the Run Flow boundary.",
            # Data와 JSON을 모두 허용해 Parser/Normalizer 결과를 쉽게 붙일 수 있게 합니다.
            input_types=["Data", "JSON"],
            required=False,
        ),
        DropdownInput(
            name="bridge_mode",
            display_name="Bridge Mode",
            options=["json_with_request", "json_only", "text_only"],
            value="json_with_request",
            # subflow가 기대하는 입력 모양에 따라 직렬화 방식을 바꿀 수 있습니다.
            advanced=True,
        ),
        IntInput(
            name="max_chars",
            display_name="Max Chars",
            info="Prevent very large payloads from being pushed into a text/message-only subflow.",
            value=12000,
            # 운영에서는 payload 크기 제한이 중요하므로 조정 가능하되 기본 화면에서는 숨깁니다.
            advanced=True,
        ),
    ]

    # Message는 Run Flow/Chat Output 쪽으로 연결하고, Debug Payload는 Inspect Output이나 로그 확인용입니다.
    # group_outputs=True를 두면 두 port를 동시에 연결할 수 있습니다.
    outputs = [
        Output(
            name="message",
            display_name="Run Flow Message",
            method="build_message",
            types=["Message"],
            group_outputs=True,
        ),
        Output(
            name="debug_payload",
            display_name="Debug Payload",
            method="build_debug_payload",
            types=["Data"],
            group_outputs=True,
        ),
    ]

    def _envelope(self) -> dict[str, Any]:
        # request_text와 payload를 하나의 명시적 계약으로 묶습니다.
        # contract 버전은 하위 flow가 입력 schema 변경을 감지하는 데 도움 됩니다.
        request_text = str(getattr(self, "request_text", "") or "").strip()
        payload = _payload_from_value(getattr(self, "payload", None))
        return {
            "request_text": request_text,
            "payload": payload,
            "contract": "run_flow_message_bridge.v1",
        }

    def _message_text(self) -> str:
        # bridge_mode는 하위 flow가 받을 수 있는 입력 타입에 맞춰 선택합니다.
        mode = str(getattr(self, "bridge_mode", "json_with_request") or "json_with_request")
        envelope = self._envelope()

        if mode == "text_only":
            # 아주 단순한 subflow는 자연어 지시문만 기대할 수 있습니다.
            text = envelope["request_text"] or str(envelope["payload"].get("text", ""))
        elif mode == "json_only":
            # payload만 필요한 subflow라면 wrapper 없이 JSON body만 넘깁니다.
            text = json.dumps(envelope["payload"], ensure_ascii=False, default=str)
        else:
            # 기본값은 request_text, payload, contract를 모두 담는 가장 명시적인 형식입니다.
            text = json.dumps(envelope, ensure_ascii=False, default=str)

        # max_chars는 하위 flow 입력 크기를 보호하는 guard입니다.
        max_chars = _clamp_int(getattr(self, "max_chars", 12000), 12000, 0, 200000)
        text, truncated = _truncate(text, max_chars)

        # debug_payload에서 같은 실행의 truncate 여부를 보여주기 위해 임시 상태로 보관합니다.
        self._last_truncated = truncated
        return text

    def build_message(self) -> Message:
        # Run Flow의 text/message input에 직접 연결할 최종 출력입니다.
        text = self._message_text()
        self.status = f"Run Flow message prepared ({len(text)} chars)"
        return Message(text=text)

    def build_debug_payload(self) -> Data:
        # 디버그 출력은 message 전체 대신 preview와 key 목록만 제공합니다.
        # 민감하거나 큰 payload가 Inspect Output에 과도하게 노출되는 것을 줄입니다.
        envelope = self._envelope()
        text = self._message_text()
        return Data(
            data={
                "success": True,
                "contract": envelope["contract"],
                "message_preview": text[:800],
                "message_chars": len(text),
                "truncated": bool(getattr(self, "_last_truncated", False)),
                "payload_keys": sorted(envelope["payload"].keys()),
            }
        )
