from __future__ import annotations

from typing import Any

# 이 파일은 "운영 설정 Input을 잘 쓰는 법"을 실습하는 예시입니다.
# 실제 PDF/PPT를 읽는 node가 아니라, 뒤쪽 문서 처리 flow가 사용할 설정 payload만 만듭니다.
# Langflow 코드창에 붙여넣을 때는 아래 import 줄부터 class 끝까지 함께 붙여넣습니다.
from lfx.custom import Component
from lfx.io import BoolInput, DropdownInput, FloatInput, IntInput, Output
from lfx.schema import Data


class DocumentLoaderSettings(Component):
    display_name = "Document Loader Settings"
    description = "Build a small settings payload for document flows."
    icon = "Settings2"
    name = "DocumentLoaderSettings"

    inputs = [
        DropdownInput(
            name="parse_mode",
            display_name="Parse Mode",
            info="문서를 읽는 방식을 고릅니다. multimodal이면 vision 설정이 추가로 필요합니다.",
            options=["text_only", "ocr", "multimodal"],
            value="text_only",
            # real_time_refresh=True는 "이 값이 바뀌면 설정 화면을 다시 계산해 달라"는 표시입니다.
            # 그래서 parse_mode가 바뀌면 Langflow UI가 아래 update_build_config hook을 호출합니다.
            real_time_refresh=True,
        ),
        BoolInput(
            name="include_debug",
            display_name="Include Debug",
            info="결과 payload에 설정 원문을 함께 넣을지 결정합니다.",
            value=False,
            # 운영 중 자주 켜는 값이 아니므로 기본 화면보다 advanced 영역에 둡니다.
            advanced=True,
        ),
        IntInput(
            name="max_pages",
            display_name="Max Pages",
            info="한 번에 처리할 최대 페이지 수입니다.",
            value=30,
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
            info="parse_mode가 multimodal일 때만 필요한 설정입니다.",
            options=["fast", "balanced", "accurate"],
            value="balanced",
            # 처음에는 숨겨두고 parse_mode가 multimodal일 때만 화면에 보이게 합니다.
            dynamic=True,
            show=False,
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
        # real_time_refresh=True가 붙은 parse_mode가 바뀔 때 이 hook이 호출됩니다.
        # 여기서는 multimodal을 선택한 경우에만 vision_model_profile field를 보여줍니다.
        if field_name == "parse_mode":
            needs_vision = field_value == "multimodal"
            build_config["vision_model_profile"]["show"] = needs_vision
            build_config["vision_model_profile"]["required"] = needs_vision
        return build_config

    def build_settings(self) -> Data:
        # UI 입력값은 기본값이 있어도 API 실행이나 flow import를 거치며 이상한 값이 될 수 있습니다.
        # 그래서 실행 직전에 숫자 범위만 짧게 보정합니다.
        try:
            max_pages = int(self.max_pages or 30)
        except Exception:
            max_pages = 30
        max_pages = max(1, min(max_pages, 300))

        try:
            threshold = float(self.similarity_threshold or 0.72)
        except Exception:
            threshold = 0.72
        threshold = max(0.0, min(threshold, 1.0))

        result = {
            "success": True,
            "parse_mode": self.parse_mode,
            "max_pages": max_pages,
            "similarity_threshold": threshold,
            "vision_model_profile": self.vision_model_profile if self.parse_mode == "multimodal" else None,
            "errors": [],
        }
        if self.include_debug is True:
            result["debug"] = {"selected_parse_mode": self.parse_mode}

        # status는 Langflow node 카드에 보이는 짧은 실행 상태입니다.
        self.status = f"mode={self.parse_mode}, pages={max_pages}, threshold={threshold}"
        return Data(data=result)
