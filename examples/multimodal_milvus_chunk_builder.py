from __future__ import annotations

import hashlib
import json
from typing import Any

# 이 예제는 Milvus에 직접 접속하지 않습니다.
# Langflow의 Milvus component 앞단에서 `ingest_data`로 넘길 record payload를 만드는 adapter입니다.
# DB 접속정보, embedding 모델, vector_dimensions는 Milvus/Embedding component가 담당하게 분리합니다.
# Langflow 코드창에 붙여넣을 때 이 import 줄을 포함해야 Component를 인식합니다.
from lfx.custom import Component
from lfx.io import BoolInput, DataInput, DropdownInput, FloatInput, IntInput, MessageTextInput, Output
from lfx.schema import Data


def _payload_from_value(value: Any) -> dict[str, Any]:
    # Read File, Docling, OCR, Vision LLM 결과는 Data/JSON/Message 등 여러 형태로 들어올 수 있습니다.
    # 먼저 dict payload로 정규화해야 page_summaries/images 같은 필드를 일관되게 읽을 수 있습니다.
    if value is None:
        return {}
    if isinstance(value, dict):
        return value

    # Langflow Data 객체의 구조화 데이터는 `.data`에 들어 있습니다.
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"pages": data}
    if isinstance(data, str) and data.strip():
        return {"extracted_text": data}

    # Message에 JSON 문자열이 담겨 있으면 dict로 복원합니다.
    # 일반 텍스트라면 문서 전체 extracted_text로 간주해 단일 page chunk로 만들 수 있게 합니다.
    text = getattr(value, "text", None) or getattr(value, "content", None)
    if isinstance(value, str):
        text = value
    if isinstance(text, str) and text.strip():
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"items": parsed}
        except Exception:
            return {"extracted_text": text}

    # 알 수 없는 입력 타입은 빈 문서로 처리하고 manifest에서 warning을 보게 합니다.
    return {}


def _as_list(value: Any) -> list[Any]:
    # page_summaries/images가 단일 dict로 오더라도 아래 로직은 list를 기대합니다.
    # None -> [], 단일 값 -> [value]로 맞춰 반복문을 단순하게 합니다.
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_bool(value: object, default: bool = False) -> bool:
    # BoolInput 값은 Langflow 실행 경로에 따라 bool, "true", "false" 문자열로 들어올 수 있습니다.
    # bool("false")는 True가 되므로 반드시 명시 변환합니다.
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _clamp_float(value: object, default: float, minimum: float, maximum: float) -> float:
    # UI에서 들어온 숫자 옵션은 실행 직전에 다시 범위를 제한합니다.
    # FloatInput 기본값이 있어도 flow import/API 호출 과정에서 문자열로 들어올 수 있습니다.
    try:
        number = float(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    # flow import/API 실행에서는 IntInput 값이 문자열이나 잘못된 값으로 들어올 수 있습니다.
    # 실행 시점에 다시 보정해야 chunking 중 ValueError로 flow가 끊기지 않습니다.
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


def _page_number(item: Any, default: int) -> int:
    # PDF는 page, PPT는 slide라는 이름을 쓰는 경우가 많습니다.
    # 둘 다 page number로 정규화하여 metadata filter를 단순하게 만듭니다.
    if isinstance(item, dict):
        for key in ("page", "page_number", "slide", "slide_number"):
            if key in item:
                try:
                    return int(item[key])
                except Exception:
                    # 값이 숫자로 변환되지 않으면 enumerate index를 fallback으로 씁니다.
                    return default
    return default


def _item_text(item: Any, *keys: str) -> str:
    # parser/vision provider마다 text 필드명이 다를 수 있습니다.
    # 후보 key를 순서대로 보며 처음 발견한 문자열을 사용합니다.
    if isinstance(item, dict):
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(item, str):
        # 테스트나 간단한 flow에서는 page item이 문자열 자체일 수도 있습니다.
        return item.strip()
    return ""


def _split_text(text: str, chunk_chars: int, overlap_chars: int) -> list[str]:
    # embedding 전 chunk를 만들기 전에 공백을 정리합니다.
    # PDF/PPT 추출 텍스트는 줄바꿈과 공백이 불규칙한 경우가 많습니다.
    text = " ".join(str(text or "").split())
    if not text:
        return []

    # 너무 작은 chunk는 검색 recall이 나빠질 수 있어 최소 400자로 제한합니다.
    chunk_chars = max(400, int(chunk_chars or 1200))

    # overlap은 이전 chunk와 다음 chunk의 문맥 연결을 돕지만, 너무 크면 중복 저장이 늘어납니다.
    # 최대 chunk의 절반까지만 허용합니다.
    overlap_chars = max(0, min(int(overlap_chars or 0), chunk_chars // 2))

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        # 다음 chunk는 overlap만큼 뒤로 당겨 시작합니다.
        start = max(0, end - overlap_chars)
    return chunks


def _stable_id(*parts: object) -> str:
    # 같은 문서를 같은 방식으로 chunking하면 같은 id가 나오도록 hash를 씁니다.
    # 재색인 시 중복 관리나 upsert 전략을 세우기 쉬워집니다.
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class MultimodalMilvusChunkBuilder(Component):
    display_name = "Multimodal Milvus Chunk Builder"
    description = "Build Milvus ingest_data records from PDF/PPT text extraction and vision summaries."
    icon = "DatabaseZap"
    name = "MultimodalMilvusChunkBuilder"

    # 입력 payload는 다음과 같은 형태를 기대합니다.
    # {
    #   "file_name": "report.pdf",
    #   "page_summaries": [{"page": 1, "text": "..."}],
    #   "image_summaries": [{"page": 1, "summary": "chart shows ..."}]
    # }
    # Read File/Docling/OCR/Vision LLM 결과를 중간 normalizer로 이 형태에 맞추면 됩니다.
    inputs = [
        DataInput(
            name="document_payload",
            display_name="Document Payload",
            info="Data from Read File, Docling, OCR, or a multimodal document normalizer.",
            # Data/JSON port 모두 허용해 Parser 결과와 custom normalizer 결과를 쉽게 연결합니다.
            input_types=["Data", "JSON"],
            required=True,
        ),
        DropdownInput(
            name="parse_mode",
            display_name="Parse Mode",
            info="Choose whether to build text-only, OCR-oriented, or multimodal chunks.",
            options=["text_only", "ocr", "multimodal"],
            value="multimodal",
            # parse_mode가 바뀌면 vision 설정 field를 즉시 보이거나 숨기기 위해 사용합니다.
            real_time_refresh=True,
        ),
        MessageTextInput(
            name="document_id",
            display_name="Document ID",
            info="Stable document ID. If empty, the file name is used.",
            value="",
            # 문서 id는 운영자가 고정하고 싶을 때만 쓰는 값이라 advanced로 둡니다.
            advanced=True,
        ),
        IntInput(
            name="max_pages",
            display_name="Max Pages",
            info="Maximum pages/slides to process in one ingestion run.",
            value=300,
            # 대량 문서를 한 번에 처리하면 비용/시간이 커지므로 운영 튜닝값으로 둡니다.
            advanced=True,
        ),
        IntInput(
            name="chunk_chars",
            display_name="Chunk Chars",
            value=1200,
            # embedding chunk 크기는 검색 품질에 영향을 주는 튜닝 값입니다.
            advanced=True,
        ),
        IntInput(
            name="overlap_chars",
            display_name="Overlap Chars",
            value=120,
            # PDF/PPT 문맥이 chunk 경계에서 끊기는 것을 줄이기 위한 overlap입니다.
            advanced=True,
        ),
        BoolInput(
            name="include_visual_summaries",
            display_name="Include Visual Summaries",
            value=True,
            # 비용이 큰 vision summary를 실험적으로 끄고 text-only 색인을 비교할 수 있습니다.
            real_time_refresh=True,
            advanced=True,
        ),
        DropdownInput(
            name="vision_model_profile",
            display_name="Vision Model Profile",
            info="Only used when visual summaries are included.",
            options=["fast", "balanced", "accurate"],
            value="balanced",
            # parse_mode/include_visual_summaries 값에 따라 update_build_config에서 노출을 제어합니다.
            dynamic=True,
            show=True,
            advanced=True,
        ),
        FloatInput(
            name="min_visual_confidence",
            display_name="Min Visual Confidence",
            info="Drop image summaries below this confidence/score when the upstream payload provides one.",
            value=0.0,
            dynamic=True,
            show=True,
            advanced=True,
        ),
    ]

    # Milvus Ingest Payload는 Milvus component의 `ingest_data`에 연결할 본 출력입니다.
    # Manifest는 운영자가 색인 결과를 확인하는 검수용 출력입니다.
    outputs = [
        Output(
            name="milvus_ingest_payload",
            display_name="Milvus Ingest Payload",
            method="build_ingest_payload",
            types=["Data"],
            group_outputs=True,
        ),
        Output(
            name="manifest",
            display_name="Ingestion Manifest",
            method="build_manifest",
            types=["Data"],
            group_outputs=True,
        ),
    ]

    def update_build_config(self, build_config: dict[str, Any], field_value: Any, field_name: str | None = None) -> dict[str, Any]:
        # parse_mode 또는 include_visual_summaries가 바뀌면 vision 관련 옵션 표시 여부를 즉시 갱신합니다.
        # 교육 포털의 "운영 설정 Input" 예시가 실제 component 코드에서도 어떻게 쓰이는지 보여주는 부분입니다.
        if field_name in {"parse_mode", "include_visual_summaries"}:
            current_mode = build_config.get("parse_mode", {}).get("value", "multimodal")
            current_include = build_config.get("include_visual_summaries", {}).get("value", True)

            # 방금 변경된 field_value가 최신 값이므로 build_config의 기존 값보다 우선합니다.
            if field_name == "parse_mode":
                current_mode = field_value
            if field_name == "include_visual_summaries":
                current_include = field_value

            show_vision_options = current_mode == "multimodal" and _as_bool(current_include, default=True)
            for option_name in ("vision_model_profile", "min_visual_confidence"):
                build_config[option_name]["show"] = show_vision_options
                build_config[option_name]["required"] = False

        return build_config

    def _build_records(self) -> list[dict[str, Any]]:
        # 입력 문서를 dict로 정규화하고 기본 metadata 값을 확정합니다.
        payload = _payload_from_value(getattr(self, "document_payload", None))
        file_name = str(payload.get("file_name") or payload.get("source_name") or "document")
        file_type = str(payload.get("file_type") or "").lstrip(".") or file_name.rsplit(".", 1)[-1]

        # document_id가 없으면 파일명을 씁니다. 운영에서는 버전/문서번호를 포함한 id를 권장합니다.
        document_id = str(getattr(self, "document_id", "") or "").strip() or file_name

        # chunk/overlap 값은 UI에서 들어오므로 int로 확정합니다.
        parse_mode = str(getattr(self, "parse_mode", "multimodal") or "multimodal")
        max_pages = _clamp_int(getattr(self, "max_pages", 300), 300, 1, 2000)
        chunk_chars = _clamp_int(getattr(self, "chunk_chars", 1200), 1200, 400, 8000)
        overlap_chars = _clamp_int(getattr(self, "overlap_chars", 120), 120, 0, chunk_chars // 2)
        include_visuals = _as_bool(getattr(self, "include_visual_summaries", True), default=True) and parse_mode == "multimodal"
        vision_model_profile = str(getattr(self, "vision_model_profile", "balanced") or "balanced")
        min_visual_confidence = _clamp_float(getattr(self, "min_visual_confidence", 0.0), 0.0, 0.0, 1.0)

        # page_summaries/pages는 텍스트 추출 결과, image_summaries/images는 vision/OCR 결과로 봅니다.
        page_items = _as_list(
            payload.get("page_summaries")
            or payload.get("pages")
            or payload.get("documents")
            or payload.get("chunks")
        )
        image_items = _as_list(payload.get("image_summaries") or payload.get("images"))

        if not page_items:
            # 기본 Read File/Parser/custom loader마다 원문 텍스트 필드명이 조금씩 다를 수 있습니다.
            # 페이지 구조가 없으면 가장 흔한 텍스트 필드를 찾아 단일 page로 감쌉니다.
            fallback_text = _item_text(payload, "extracted_text", "text", "raw_content", "content", "markdown", "page_content")
            if fallback_text:
                page_items = [{"page": 1, "text": fallback_text}]

        # max_pages는 대량 PDF/PPT를 교육/운영 flow에서 실수로 전부 처리하지 않게 막는 안전장치입니다.
        page_items = [item for index, item in enumerate(page_items, start=1) if _page_number(item, index) <= max_pages]
        image_items = [item for index, item in enumerate(image_items, start=1) if _page_number(item, index) <= max_pages]

        # vision summary는 page 번호 기준으로 묶어 두었다가 해당 page text와 합칩니다.
        visuals_by_page: dict[int, list[str]] = {}
        if include_visuals:
            for index, item in enumerate(image_items, start=1):
                page = _page_number(item, index)

                # upstream vision node가 confidence/score를 주면 낮은 품질의 이미지 설명은 제외합니다.
                if isinstance(item, dict):
                    raw_confidence = item.get("confidence", item.get("score", 1.0))
                    confidence = _clamp_float(raw_confidence, 1.0, 0.0, 1.0)
                    if confidence < min_visual_confidence:
                        continue

                visual_text = _item_text(item, "summary", "description", "caption", "text")
                if visual_text:
                    visuals_by_page.setdefault(page, []).append(visual_text)

        records: list[dict[str, Any]] = []
        for index, item in enumerate(page_items, start=1):
            # PDF page와 PPT slide를 모두 page metadata로 통일합니다.
            page = _page_number(item, index)

            # text/markdown/summary 등 가능한 텍스트 필드를 순서대로 채택합니다.
            page_text = _item_text(item, "text", "content", "markdown", "summary")

            # 같은 page에 여러 image/chart summary가 있으면 줄바꿈으로 합칩니다.
            visual_text = "\n".join(visuals_by_page.get(page, []))

            sections = []
            if page_text:
                # tag를 붙여 저장하면 검색된 chunk를 prompt에 넣을 때 근거 종류가 분명해집니다.
                sections.append("[PAGE_TEXT]\n" + page_text)
            if visual_text:
                # 이미지 자체가 아니라 LLM이 이해한 설명을 embedding 대상으로 저장합니다.
                sections.append("[VISUAL_SUMMARY]\n" + visual_text)

            combined = "\n\n".join(sections)
            for chunk_index, chunk in enumerate(_split_text(combined, chunk_chars, overlap_chars), start=1):
                # chunk 앞부분까지 id 재료에 넣어 같은 page가 여러 chunk로 나뉘어도 id가 구분됩니다.
                record_id = _stable_id(document_id, page, chunk_index, chunk[:160])

                # metadata는 Milvus search_filter와 답변 citation에 쓰입니다.
                # 특히 page/source_locator는 사용자에게 출처를 보여줄 때 필수입니다.
                metadata = {
                    "document_id": document_id,
                    "source_file": file_name,
                    "file_type": file_type,
                    "page": page,
                    "chunk_index": chunk_index,
                    "content_type": "text_plus_vision" if visual_text else "text",
                    "modalities": ["text", "vision"] if visual_text else ["text"],
                    "parse_mode": parse_mode,
                    "vision_model_profile": vision_model_profile if visual_text else None,
                    "source_locator": f"page:{page}",
                }
                records.append(
                    {
                        # id는 vector store upsert/중복관리용 안정 키입니다.
                        "id": record_id,

                        # Langflow/Milvus/LangChain component는 text 또는 page_content를 기대할 수 있어 둘 다 넣습니다.
                        "text": chunk,
                        "page_content": chunk,
                        "metadata": metadata,
                    }
                )

        return records

    def build_ingest_payload(self) -> Data:
        # Milvus component의 `ingest_data` 입력에 연결할 수 있는 본 payload를 만듭니다.
        records = self._build_records()
        self.status = f"Prepared {len(records)} Milvus records"
        return Data(
            data={
                "success": bool(records),
                # Langflow Milvus component의 ingest_data input에 연결할 핵심 필드입니다.
                "ingest_data": records,
                "record_count": len(records),
                "warnings": [] if records else ["No text or visual summaries were found."],
            }
        )

    def build_manifest(self) -> Data:
        # 운영자는 manifest를 Inspect Output으로 보고 어떤 page/modalities가 색인됐는지 확인합니다.
        records = self._build_records()
        pages = sorted({record["metadata"]["page"] for record in records})
        return Data(
            data={
                "success": bool(records),
                "record_count": len(records),
                "pages": pages,
                "settings": {
                    "parse_mode": str(getattr(self, "parse_mode", "multimodal") or "multimodal"),
                    "max_pages": _clamp_int(getattr(self, "max_pages", 300), 300, 1, 2000),
                    "include_visual_summaries": _as_bool(getattr(self, "include_visual_summaries", True), default=True),
                    "vision_model_profile": str(getattr(self, "vision_model_profile", "balanced") or "balanced"),
                    "min_visual_confidence": _clamp_float(getattr(self, "min_visual_confidence", 0.0), 0.0, 0.0, 1.0),
                },
                # text-only 색인인지, vision summary까지 포함됐는지 빠르게 확인하는 필드입니다.
                "modalities": sorted({mode for record in records for mode in record["metadata"]["modalities"]}),
                # sample_record는 실제 Milvus에 들어갈 record 모양을 교육생이 바로 볼 수 있게 합니다.
                "sample_record": records[0] if records else None,
            }
        )
