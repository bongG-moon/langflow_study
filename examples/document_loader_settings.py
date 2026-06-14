from __future__ import annotations

from typing import Any

# 이 파일은 "운영 설정 Input을 잘 쓰는 법"을 그대로 실습할 수 있는 최소 예제입니다.
# 실제 문서를 읽지는 않고, downstream 문서 처리 flow가 사용할 설정 payload만 만듭니다.
# Langflow 코드창에 붙여넣을 때 이 import 줄을 포함해야 Component를 인식합니다.
from lfx.custom import Component
from lfx.io import BoolInput, DropdownInput, FloatInput, IntInput, Output
from lfx.schema import Data


def _as_bool(value: object, default: bool = False) -> bool:
    # BoolInput 값은 UI에서는 bool처럼 보이지만 API/저장된 flow를 거치면 문자열일 수 있습니다.
    # bool("false")는 True가 되므로 문자열 후보를 명시적으로 처리합니다.
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    # IntInput 기본값이 있어도 사용자가 UI/API에서 범위 밖 값을 넣을 수 있습니다.
    # 실행 직전에 한 번 더 제한해야 downstream 처리량과 비용을 예측할 수 있습니다.
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


def _clamp_float(value: object, default: float, minimum: float, maximum: float) -> float:
    # FloatInput은 threshold, confidence, temperature처럼 범위가 중요한 값에 씁니다.
    # 여기서는 0.0~1.0 사이 값만 허용합니다.
    try:
        number = float(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


class DocumentLoaderSettings(Component):
    display_name = "Document Loader Settings"
    description = "Build a safe runtime settings payload for PDF/PPT ingestion flows."
    icon = "Settings2"
    name = "DocumentLoaderSettings"

    inputs = [
        BoolInput(
            name="use_vision_summary",
            display_name="Use Vision Summary",
            info="이미지, 차트, 도면 설명을 vision LLM으로 생성할지 결정합니다.",
            value=False,
            # 값이 바뀌는 즉시 update_build_config가 실행되어 관련 field 표시를 바꿉니다.
            real_time_refresh=True,
        ),
        DropdownInput(
            name="parse_mode",
            display_name="Parse Mode",
            info="문서를 어떤 방식으로 해석할지 선택합니다.",
            options=["text_only", "ocr", "multimodal"],
            value="text_only",
            # multimodal 선택 시 vision 설정이 바로 나타나도록 합니다.
            real_time_refresh=True,
        ),
        IntInput(
            name="max_pages",
            display_name="Max Pages",
            info="한 번에 처리할 최대 페이지/슬라이드 수입니다.",
            value=30,
            # 자주 바꾸지 않는 운영 튜닝값은 기본 화면보다 advanced 영역에 둡니다.
            advanced=True,
        ),
        FloatInput(
            name="similarity_threshold",
            display_name="Similarity Threshold",
            info="검색 결과를 근거로 인정할 최소 유사도입니다.",
            value=0.72,
            advanced=True,
        ),
        DropdownInput(
            name="vision_model_profile",
            display_name="Vision Model Profile",
            info="vision summary를 사용할 때만 필요한 모델 프로필입니다.",
            options=["fast", "balanced", "accurate"],
            value="balanced",
            # 처음에는 숨겨두고, update_build_config에서 필요한 경우에만 보이게 합니다.
            dynamic=True,
            show=False,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            name="settings",
            display_name="Settings",
            method="build_settings",
            types=["Data"],
        )
    ]

    def update_build_config(self, build_config: dict[str, Any], field_value: Any, field_name: str | None = None) -> dict[str, Any]:
        # 이 hook은 real_time_refresh=True인 입력값이 바뀔 때 Langflow UI가 호출합니다.
        # 여기서는 parse_mode/use_vision_summary에 따라 vision_model_profile 표시 여부를 결정합니다.
        if field_name in {"use_vision_summary", "parse_mode"}:
            current_mode = build_config.get("parse_mode", {}).get("value", "text_only")
            current_use_vision = build_config.get("use_vision_summary", {}).get("value", False)

            # 방금 바뀐 field_value가 가장 최신 값이므로 build_config보다 우선합니다.
            if field_name == "parse_mode":
                current_mode = field_value
            if field_name == "use_vision_summary":
                current_use_vision = field_value

            show_vision_profile = current_mode == "multimodal" or _as_bool(current_use_vision, default=False)
            build_config["vision_model_profile"]["show"] = show_vision_profile
            build_config["vision_model_profile"]["required"] = show_vision_profile

            # multimodal이 필요할 때는 선택지를 OCR/multimodal 중심으로 줄여 실수를 줄입니다.
            if show_vision_profile:
                build_config["parse_mode"]["options"] = ["ocr", "multimodal"]
            else:
                build_config["parse_mode"]["options"] = ["text_only", "ocr", "multimodal"]

        return build_config

    def build_settings(self) -> Data:
        # UI에서 들어온 값은 실행 직전에 다시 표준 타입과 허용 범위로 보정합니다.
        parse_mode = str(getattr(self, "parse_mode", "text_only") or "text_only")
        use_vision = _as_bool(getattr(self, "use_vision_summary", False), default=False)
        max_pages = _clamp_int(getattr(self, "max_pages", 30), 30, 1, 300)
        threshold = _clamp_float(getattr(self, "similarity_threshold", 0.72), 0.72, 0.0, 1.0)

        # downstream flow가 그대로 읽을 수 있도록 설정 payload 계약을 명확히 둡니다.
        result = {
            "success": True,
            "parse_mode": parse_mode,
            "use_vision_summary": use_vision,
            "vision_model_profile": self.vision_model_profile if use_vision or parse_mode == "multimodal" else None,
            "max_pages": max_pages,
            "similarity_threshold": threshold,
            "errors": [],
        }

        # status는 UI 카드에 보이는 짧은 실행 결과입니다. secret이나 긴 payload를 넣지 않습니다.
        self.status = f"mode={parse_mode}, pages={max_pages}, threshold={threshold}"
        return Data(data=result)
