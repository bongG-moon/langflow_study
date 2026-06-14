from __future__ import annotations

import json
from typing import Any

# Langflow 코드창에 붙여넣을 때 이 import 줄을 포함해야 Component를 인식합니다.
from lfx.custom import Component
from lfx.io import DataInput, Output
from lfx.schema import Data


# 이 node가 열어 줄 branch 이름입니다.
# route 값이 이 목록 밖이면 안전하게 final_answer로 보냅니다.
VALID_ROUTES = {"data_retrieval", "document_rag", "final_answer"}


def _payload_from_value(value: Any) -> dict[str, Any]:
    # RouteGate는 upstream intent parser가 만든 Data/JSON/Message를 모두 받을 수 있게 설계합니다.
    if value is None:
        return {}
    if isinstance(value, dict):
        return value

    # Langflow Data 객체는 `.data`에 구조화 payload를 담습니다.
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        return data

    # Message로 넘어온 JSON 문자열도 route payload로 복원합니다.
    text = getattr(value, "text", None) or getattr(value, "content", None)
    if isinstance(text, str) and text.strip():
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"text": text}
        except Exception:
            # JSON이 아니면 route 정보가 없으므로 text만 보존하고 final_answer로 fallback됩니다.
            return {"text": text}
    return {}


def _normalize_route(value: object) -> str:
    # LLM/intent parser가 route를 항상 정확한 enum으로 내보내지는 않습니다.
    # 흔한 별칭을 사내 표준 route 이름으로 보정합니다.
    route = str(value or "").strip().lower()
    aliases = {
        "retrieval": "data_retrieval",
        "data": "data_retrieval",
        "rag": "document_rag",
        "docs": "document_rag",
        "answer": "final_answer",
        "finish": "final_answer",
    }
    route = aliases.get(route, route)

    # 알 수 없는 route는 외부 조회나 RAG로 보내지 않고 final_answer로 닫습니다.
    # 잘못된 branch 실행을 막는 작은 policy gate 역할도 합니다.
    return route if route in VALID_ROUTES else "final_answer"


class RouteGate(Component):
    display_name = "Route Gate"
    description = "Route a normalized intent payload into retrieval, document RAG, or final answer branches."
    icon = "GitBranch"
    name = "RouteGate"

    # Intent Parser 또는 LLM JSON Caller의 결과를 받는 입력입니다.
    # route 외에도 질문, 필터, 검색 키워드 같은 값을 payload 안에 같이 실을 수 있습니다.
    inputs = [
        DataInput(
            name="intent_payload",
            display_name="Intent Payload",
            input_types=["Data", "JSON"],
            required=True,
        )
    ]

    # group_outputs=True를 쓰면 세 output port가 동시에 노출됩니다.
    # Langflow 라우터 node는 선택형 output보다 "모든 branch를 연결해 두고 active만 보는 방식"이 안정적입니다.
    outputs = [
        Output(
            name="data_retrieval",
            display_name="Data Retrieval",
            method="to_data_retrieval",
            types=["Data"],
            group_outputs=True,
        ),
        Output(
            name="document_rag",
            display_name="Document RAG",
            method="to_document_rag",
            types=["Data"],
            group_outputs=True,
        ),
        Output(
            name="final_answer",
            display_name="Final Answer",
            method="to_final_answer",
            types=["Data"],
            group_outputs=True,
        ),
    ]

    def _route_payload(self, target_route: str) -> Data:
        # 입력 payload를 표준 dict로 맞춘 뒤 route만 추출합니다.
        payload = _payload_from_value(getattr(self, "intent_payload", None))
        selected_route = _normalize_route(payload.get("route"))

        # 각 output method는 자신의 target_route와 selected_route가 같을 때만 active=True가 됩니다.
        active = selected_route == target_route

        # inactive branch는 success=False/skipped=True로 표시해야 downstream이 실수로 처리하지 않습니다.
        # payload는 active branch에만 실어 잘못된 branch가 데이터를 처리하지 않도록 합니다.
        result = {
            "success": active,
            "active": active,
            "skipped": not active,
            "selected_route": selected_route,
            "target_route": target_route,
            "payload": payload if active else {},
            "errors": [],
            "warnings": [] if active else [f"Inactive branch. Selected route is {selected_route}."],
        }

        # 사용자는 Langflow 카드 상태만 보고도 선택된 route를 확인할 수 있습니다.
        self.status = f"Selected route: {selected_route}"
        return Data(data=result)

    def to_data_retrieval(self) -> Data:
        # 데이터 조회 branch: SQL/API/File 조회 등 정형 데이터가 필요한 질문으로 보냅니다.
        return self._route_payload("data_retrieval")

    def to_document_rag(self) -> Data:
        # 문서 RAG branch: 규정/매뉴얼/FAQ 같은 비정형 문서 검색으로 보냅니다.
        return self._route_payload("document_rag")

    def to_final_answer(self) -> Data:
        # 최종 답변 branch: 추가 조회 없이 바로 답하거나, fallback 답변을 만들 때 사용합니다.
        return self._route_payload("final_answer")
