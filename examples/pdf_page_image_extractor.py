from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

# Langflow 코드창에 붙여넣을 때 이 import 줄을 포함해야 Component를 인식합니다.
from lfx.custom import Component
from lfx.io import BoolInput, FileInput, FloatInput, IntInput, MessageTextInput, Output
from lfx.schema import Data
from lfx.schema.message import Message


def _file_paths_from_value(value: Any) -> list[Path]:
    # FileInput은 Langflow 버전에 따라 문자열 path, file object, list 등으로 넘어올 수 있습니다.
    # 모든 경우를 Path list로 정규화해 두면 아래 렌더링 로직이 단순해집니다.
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


def _parse_page_range(page_range: str, total_pages: int, max_pages: int) -> list[int]:
    # 사용자는 "1-3,5"처럼 사람이 읽는 1-base 페이지 번호를 입력합니다.
    # 내부 렌더링은 0-base index를 쓰므로 마지막에 1을 빼서 변환합니다.
    text = str(page_range or "").strip()
    if not text:
        selected = list(range(1, min(total_pages, max_pages) + 1))
    else:
        selected: list[int] = []
        for part in re.split(r"[, ]+", text):
            if not part:
                continue
            if "-" in part:
                start_text, end_text = part.split("-", 1)
                start = int(start_text)
                end = int(end_text)
                selected.extend(range(start, end + 1))
            else:
                selected.append(int(part))

    # 범위를 벗어난 값과 중복을 제거합니다.
    cleaned: list[int] = []
    for page_no in selected:
        if 1 <= page_no <= total_pages and page_no not in cleaned:
            cleaned.append(page_no)
        if len(cleaned) >= max_pages:
            break
    return [page_no - 1 for page_no in cleaned]


def _safe_stem(path: Path) -> str:
    # 파일명은 output directory 이름으로 쓰이므로 영문/숫자/일부 기호만 남깁니다.
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem).strip("._")
    return stem or "pdf"


class PdfPageImageExtractor(Component):
    display_name = "PDF Page Image Extractor"
    description = "Render selected PDF pages to PNG files and return a multimodal Message for vision-capable models."
    icon = "FileImage"
    name = "PdfPageImageExtractor"

    inputs = [
        FileInput(
            name="pdf_file",
            display_name="PDF File",
            info="Image-based or scanned PDF file. This component renders pages to PNG instead of running OCR.",
            file_types=["pdf"],
            required=True,
        ),
        MessageTextInput(
            name="instruction",
            display_name="Vision Instruction",
            info="Question or extraction instruction sent with the rendered page images.",
            value=(
                "첨부된 PDF 페이지 이미지를 보고 핵심 내용, 표/차트 수치, 병목 후보, "
                "권장 조치를 페이지 번호와 함께 한국어로 요약하세요."
            ),
        ),
        MessageTextInput(
            name="page_range",
            display_name="Page Range",
            info="1-based pages to render. Examples: 1, 1-3, 2,4. Empty means first N pages.",
            value="1-3",
        ),
        IntInput(
            name="max_pages",
            display_name="Max Pages",
            info="Hard limit to avoid sending too many page images to a vision model.",
            value=3,
        ),
        FloatInput(
            name="render_scale",
            display_name="Render Scale",
            info="Higher values make clearer images but larger files. 1.5-2.0 is usually enough for training.",
            value=1.7,
            advanced=True,
        ),
        BoolInput(
            name="include_manifest_in_message",
            display_name="Include Manifest In Message",
            info="Append page image paths to the message text for debugging.",
            value=True,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            name="vision_message",
            display_name="Vision Message",
            method="build_vision_message",
            types=["Message"],
            group_outputs=True,
        ),
        Output(
            name="manifest",
            display_name="Page Manifest",
            method="build_manifest",
            types=["Data"],
            group_outputs=True,
        ),
    ]

    def _render_pages(self) -> dict[str, Any]:
        # 여러 output이 같은 실행에서 호출될 수 있으므로 한 번 렌더링한 결과를 캐시합니다.
        cached = getattr(self, "_last_manifest", None)
        if isinstance(cached, dict):
            return cached

        paths = _file_paths_from_value(getattr(self, "pdf_file", None))
        if not paths:
            raise ValueError("No PDF file was provided.")

        pdf_path = paths[0]
        max_pages = max(1, min(int(getattr(self, "max_pages", 3) or 3), 20))
        scale = float(getattr(self, "render_scale", 1.7) or 1.7)
        scale = max(0.8, min(scale, 3.0))

        document = pdfium.PdfDocument(str(pdf_path))
        total_pages = len(document)
        page_indexes = _parse_page_range(str(getattr(self, "page_range", "") or ""), total_pages, max_pages)
        if not page_indexes:
            raise ValueError("No valid pages were selected.")

        output_root = Path(tempfile.gettempdir()) / "langflow_pdf_page_images" / _safe_stem(pdf_path)
        output_root.mkdir(parents=True, exist_ok=True)

        pages: list[dict[str, Any]] = []
        for page_index in page_indexes:
            # pypdfium2는 PDF page를 bitmap으로 빠르게 렌더링합니다.
            # OCR은 하지 않기 때문에 Langflow job queue를 오래 붙잡지 않습니다.
            page = document[page_index]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()

            page_no = page_index + 1
            image_path = output_root / f"{_safe_stem(pdf_path)}_page_{page_no:03d}.png"
            image.save(image_path, format="PNG", optimize=True)

            pages.append(
                {
                    "page": page_no,
                    "image_path": str(image_path),
                    "width": image.width,
                    "height": image.height,
                    "render_scale": scale,
                }
            )

        manifest = {
            "success": True,
            "source_file": str(pdf_path),
            "total_pages": total_pages,
            "rendered_pages": pages,
            "page_count": len(pages),
            "recommended_next_step": (
                "Connect Vision Message to a vision-capable Language Model, "
                "or inspect Page Manifest and upload selected PNG pages through Chat Input Files."
            ),
        }
        self._last_manifest = manifest
        self.status = f"Rendered {len(pages)} page image(s) from {pdf_path.name}"
        return manifest

    def build_vision_message(self) -> Message:
        # Message.files에 PNG path를 넣으면 Langflow가 image content로 변환합니다.
        # 단, 실제 모델이 vision input을 지원해야 합니다.
        manifest = self._render_pages()
        files = [page["image_path"] for page in manifest["rendered_pages"]]

        instruction = str(getattr(self, "instruction", "") or "").strip()
        page_lines = "\n".join(
            f"- page {page['page']}: {page['image_path']}" for page in manifest["rendered_pages"]
        )
        text = instruction
        if bool(getattr(self, "include_manifest_in_message", True)):
            text = f"{instruction}\n\n[렌더링된 페이지 이미지]\n{page_lines}"

        return Message(text=text, files=files)

    def build_manifest(self) -> Data:
        # Milvus chunk builder나 검수용 Chat Output에는 이 manifest를 연결합니다.
        return Data(data=self._render_pages())
