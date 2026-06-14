from __future__ import annotations

import json
from typing import Any

import requests

# Langflow 코드창에 붙여넣을 때 이 import 줄을 포함해야 Component를 인식합니다.
from lfx.custom import Component
from lfx.io import BoolInput, DropdownInput, IntInput, MessageTextInput, MultilineInput, Output, SecretStrInput
from lfx.schema import Data


def _secret_to_text(value: object) -> str:
    # SecretStrInput 값은 Pydantic SecretStr처럼 `get_secret_value()`를 가질 수 있습니다.
    # 단순 문자열로 들어오는 경우까지 함께 처리해 bearer token 문자열로 변환합니다.
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter() or "")
    return str(value or "")


def _as_bool(value: object, default: bool = False) -> bool:
    # BoolInput 값은 실행 경로에 따라 bool 또는 문자열이 될 수 있어 명시 변환합니다.
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    # 외부 API 호출 timeout은 너무 작아도 실패하고 너무 커도 flow를 오래 붙잡습니다.
    # 교육 예제에서는 1~120초 범위로 제한합니다.
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


class InternalApiRetriever(Component):
    display_name = "Internal API Retriever"
    description = "Call an internal API with optional bearer auth and return a normalized retrieval payload."
    icon = "Cloud"
    name = "InternalApiRetriever"

    # 이 node는 사내 REST API를 RAG/Agent flow의 "검색 도구"처럼 쓰기 위한 예제입니다.
    # API URL과 method는 기본 입력, 인증/timeout/raw response는 고급 옵션으로 둡니다.
    inputs = [
        MessageTextInput(name="api_url", display_name="API URL", required=True),
        DropdownInput(name="method", display_name="Method", options=["GET", "POST"], value="GET"),
        DropdownInput(
            name="auth_type",
            display_name="Auth Type",
            options=["none", "bearer"],
            value="none",
            # auth_type을 바꾸면 api_key 필드 표시 여부가 즉시 바뀌어야 하므로 real_time_refresh를 켭니다.
            real_time_refresh=True,
            advanced=True,
        ),
        SecretStrInput(
            name="api_key",
            display_name="API Key",
            required=False,
            # update_build_config에서 auth_type에 따라 required/show를 동적으로 바꿉니다.
            dynamic=True,
            show=False,
            advanced=True,
        ),
        # GET이면 query parameter, POST면 JSON body로 사용합니다.
        # 문자열로 받아 JSON object인지 직접 검증합니다.
        MultilineInput(name="params_json", display_name="Params JSON", value="{}", advanced=True),
        IntInput(name="timeout_seconds", display_name="Timeout Seconds", value=30, advanced=True),
        # raw response는 디버깅에는 좋지만 민감정보/대용량 문제가 있어 기본값은 False입니다.
        BoolInput(name="include_raw_response", display_name="Include Raw Response", value=False, advanced=True),
    ]

    # API 결과를 표준 retrieval payload로 반환하면 Agent, Data Q&A, Report flow에서 재사용하기 쉽습니다.
    outputs = [
        Output(
            name="retrieval_payload",
            display_name="Retrieval Payload",
            method="call_api",
            types=["Data"],
        )
    ]

    def update_build_config(self, build_config: dict[str, Any], field_value: Any, field_name: str | None = None):
        # Langflow가 입력 UI를 다시 그릴 때 호출되는 hook입니다.
        # bearer 인증을 선택한 경우에만 API Key 입력을 보이게 하여 화면을 단순하게 유지합니다.
        if field_name == "auth_type":
            show_secret = field_value == "bearer"
            build_config["api_key"]["show"] = show_secret
            build_config["api_key"]["required"] = show_secret
        return build_config

    def call_api(self) -> Data:
        # 외부 호출 전 필수값을 먼저 검증합니다. URL이 없으면 requests까지 가지 않습니다.
        api_url = str(getattr(self, "api_url", "") or "").strip()
        if not api_url:
            message = "API URL is required."
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message], "warnings": []})

        try:
            # params_json은 사용자가 UI에서 문자열로 입력하므로 JSON object인지 확인합니다.
            # list/string을 허용하면 API 호출 의미가 모호해져 object만 허용합니다.
            params = json.loads(str(getattr(self, "params_json", "{}") or "{}"))
            if not isinstance(params, dict):
                raise ValueError("Params JSON must be an object.")
        except Exception as exc:
            message = f"Invalid params_json: {exc}"
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message], "warnings": []})

        headers: dict[str, str] = {}
        if str(getattr(self, "auth_type", "none") or "none") == "bearer":
            # secret은 output/status/debug에 절대 넣지 않고 Authorization header에만 사용합니다.
            api_key = _secret_to_text(getattr(self, "api_key", None)).strip()
            if not api_key:
                message = "API key is required for bearer auth."
                self.status = message
                return Data(data={"success": False, "rows": [], "errors": [message], "warnings": []})
            headers["Authorization"] = f"Bearer {api_key}"

        # timeout과 method를 UI 값에서 안전하게 확정합니다.
        timeout = _clamp_int(getattr(self, "timeout_seconds", 30), 30, 1, 120)
        method = str(getattr(self, "method", "GET") or "GET").upper()

        try:
            # GET은 params, POST는 json body로 보냅니다. 이 규칙을 고정하면 로그와 재현이 쉬워집니다.
            if method == "POST":
                response = requests.post(api_url, headers=headers, json=params, timeout=timeout)
            else:
                response = requests.get(api_url, headers=headers, params=params, timeout=timeout)
            # 4xx/5xx를 errors payload로 보내기 위해 여기서 예외로 바꿉니다.
            response.raise_for_status()
            try:
                payload = response.json() if response.content else {}
            except ValueError:
                # 일부 사내 API는 JSON이 아니라 plain text를 반환합니다.
                # 이 경우도 실패로 보지 않고 text row 1개로 정규화합니다.
                payload = {"text": response.text.strip()} if response.text.strip() else {}
        except Exception as exc:
            message = f"API request failed: {exc}"
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message], "warnings": []})

        # 많은 사내 API는 list 자체 또는 rows/data/items/result/results/records 같은 wrapper를 반환합니다.
        # 단일 object 응답도 row 1개로 감싸 downstream이 같은 방식으로 읽게 합니다.
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

        # downstream 분석 component는 dict row만 처리하기 쉽기 때문에 dict가 아닌 항목은 제외합니다.
        row_dicts = [row for row in rows if isinstance(row, dict)]

        # retrieval payload는 row_count/columns/applied_params를 함께 담아 답변 근거로 쓸 수 있게 합니다.
        result: dict[str, Any] = {
            "success": True,
            "source_name": "internal_api",
            "status_code": response.status_code,
            "rows": row_dicts,
            "row_count": len(row_dicts),
            "columns": sorted({key for row in row_dicts for key in row}),
            "applied_params": params,
            "errors": [],
            "warnings": [],
        }

        if _as_bool(getattr(self, "include_raw_response", False), default=False):
            # raw_response는 장애 분석용입니다. 운영에서는 기본 비활성화하고 필요할 때만 켭니다.
            result["raw_response"] = payload

        # Langflow UI 카드에서 호출 결과 규모를 빠르게 볼 수 있게 합니다.
        self.status = f"Loaded {len(row_dicts)} API rows"
        return Data(data=result)
