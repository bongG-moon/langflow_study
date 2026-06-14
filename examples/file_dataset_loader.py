from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

# Langflow 코드창에 붙여넣을 때 이 import 줄을 포함해야 Component를 인식합니다.
from lfx.custom import Component
from lfx.io import BoolInput, DropdownInput, FileInput, IntInput, Output
from lfx.schema import Data


ALLOWED_FILE_TYPES = [
    "csv",
    "json",
    "jsonl",
    "txt",
    "md",
    "markdown",
    "mdx",
    "xlsx",
    "xls",
    "xlsm",
]


def _file_paths_from_value(value: Any) -> list[Path]:
    # FileInput은 단일 파일, 여러 파일, Langflow file object, 문자열 path 등으로 들어올 수 있습니다.
    # 먼저 list처럼 순회할 수 있는 모양으로 맞춥니다.
    values = value if isinstance(value, list) else [value]
    paths: list[Path] = []
    for item in values:
        if item is None:
            continue
        # Langflow 버전/컴포넌트에 따라 파일 경로 속성명이 다를 수 있어 후보를 순서대로 봅니다.
        # 마지막 `or item`은 사용자가 문자열 path를 직접 넣은 경우를 처리합니다.
        path_value = (
            getattr(item, "path", None)
            or getattr(item, "file_path", None)
            or getattr(item, "name", None)
            or item
        )
        if isinstance(path_value, str) and path_value.strip():
            # expanduser는 `~/data.csv` 같은 경로를 Windows/Linux 홈 경로로 확장합니다.
            paths.append(Path(path_value).expanduser())
    return paths


def _as_bool(value: object, default: bool = False) -> bool:
    # BoolInput이 환경에 따라 bool 또는 문자열로 넘어오는 상황을 흡수합니다.
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    # preview_limit 같은 값은 너무 크면 UI와 LLM prompt를 무겁게 만듭니다.
    # 숫자 변환 실패 시 default를 쓰고, 최소/최대 범위로 제한합니다.
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


def _detect_mode(path: Path, selected_mode: str) -> str:
    # auto 모드에서는 확장자를 기준으로 reader를 선택합니다.
    # UI에서 사용자가 직접 고른 모드는 그대로 존중합니다.
    mode = str(selected_mode or "auto").strip().lower()
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


def _json_safe(value: Any) -> Any:
    # Excel cell에는 Timestamp, NaN, numpy type처럼 JSON 직렬화가 애매한 값이 들어올 수 있습니다.
    # Data payload는 downstream에서 JSON처럼 다뤄지는 경우가 많으므로 안전한 값으로 정리합니다.
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


def _read_csv(path: Path) -> list[dict[str, Any]]:
    # utf-8-sig는 Excel에서 만든 CSV의 BOM을 자연스럽게 제거해 줍니다.
    # DictReader를 쓰면 첫 행 header가 각 row의 key가 됩니다.
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> list[dict[str, Any]]:
    # JSON은 list[object] 또는 {"rows": [...]} / {"data": [...]} / {"items": [...]} 형태를 흔히 씁니다.
    # 단일 object JSON도 실습에서 자주 나오므로 row 1개로 감싸 처리합니다.
    # downstream은 row list를 기대하므로 허용되는 모양만 추려냅니다.
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "data", "items"):
            if key in payload:
                rows = payload.get(key)
                if isinstance(rows, list):
                    return [item for item in rows if isinstance(item, dict)]
                if isinstance(rows, dict):
                    return [rows]
                return []
        return [payload]
    return []


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    # JSONL은 한 줄에 JSON object 하나가 있는 로그/이벤트 데이터에 자주 쓰입니다.
    # 빈 줄은 건너뛰고, dict가 아닌 값은 row로 채택하지 않습니다.
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _read_text_lines(path: Path) -> list[dict[str, Any]]:
    # TXT/Markdown은 테이블처럼 columns가 있는 데이터가 아니므로 줄 단위 row로 맞춥니다.
    # 이렇게 해두면 preview_rows와 row_count를 다른 포맷과 같은 방식으로 다룰 수 있습니다.
    text = path.read_text(encoding="utf-8-sig")
    return [{"line_number": index + 1, "text": line} for index, line in enumerate(text.splitlines())]


def _read_excel(path: Path) -> list[dict[str, Any]]:
    # Excel은 pandas/openpyxl이 설치되어 있을 때 가장 안정적으로 읽을 수 있습니다.
    # Langflow Desktop 기본 venv에는 보통 xlsx용 openpyxl이 있지만, 오래된 xls는 xlrd가 필요할 수 있습니다.
    try:
        import pandas as pd
    except Exception as exc:
        raise ValueError("Excel parsing requires pandas and openpyxl in the Langflow environment.") from exc

    try:
        sheets = pd.read_excel(path, sheet_name=None)
    except ImportError as exc:
        raise ValueError("Excel parsing requires an engine such as openpyxl. Use .xlsx or install the required package.") from exc
    except Exception as exc:
        if path.suffix.lower() == ".xls":
            raise ValueError("Old .xls files may require xlrd. Convert to .xlsx if upload succeeds but parsing fails.") from exc
        raise

    rows: list[dict[str, Any]] = []
    for sheet_name, frame in sheets.items():
        # sheet가 여러 개인 파일도 한 output으로 합치고, 원래 sheet 이름은 `_sheet`로 보존합니다.
        for record in frame.to_dict(orient="records"):
            row = {"_sheet": str(sheet_name)}
            row.update({str(key): _json_safe(value) for key, value in record.items()})
            rows.append(row)
    return rows


class FileDatasetLoader(Component):
    display_name = "File Dataset Loader"
    description = "Load CSV, JSON, JSONL, TXT, Markdown, or Excel files into a normalized dataset payload."
    icon = "FileSpreadsheet"
    name = "FileDatasetLoader"

    # FileInput은 사용자가 업로드한 파일을 Langflow file object로 전달합니다.
    # file_types를 비워두면 Langflow UI가 "Allowed types:"를 빈 목록으로 보고 업로드를 막을 수 있습니다.
    # 그래서 교육/운영에서 받을 확장자를 명시적으로 선언합니다.
    inputs = [
        FileInput(
            name="dataset_file",
            display_name="Dataset File",
            info="CSV, JSON, JSONL, TXT, Markdown, or Excel file uploaded by the user.",
            file_types=ALLOWED_FILE_TYPES,
            required=True,
        ),
        DropdownInput(
            name="parse_mode",
            display_name="Parse Mode",
            options=["auto", "csv", "json", "jsonl", "text", "markdown", "excel"],
            value="auto",
            # parse_mode를 두면 자동 판별이 틀렸을 때 교육생이 직접 모드를 고정할 수 있습니다.
        ),
        IntInput(
            name="preview_limit",
            display_name="Preview Limit",
            info="Number of rows to include in preview_rows.",
            value=20,
            # advanced 옵션은 운영자가 튜닝할 값이라 기본 화면에서는 숨깁니다.
            advanced=True,
        ),
        BoolInput(
            name="include_full_rows",
            display_name="Include Full Rows",
            info="Use only for small files. Large flows should pass data_ref instead.",
            value=False,
            # 전체 row를 LLM에 넘기는 것은 비용/보안 리스크가 있으므로 고급 옵션으로 둡니다.
            advanced=True,
        ),
    ]

    # 이 예제는 table 자체가 아니라 "검색/분석용 payload"를 반환하므로 Data output으로 둡니다.
    outputs = [
        Output(
            name="dataset",
            display_name="Dataset",
            method="load_dataset",
            types=["Data"],
        )
    ]

    def load_dataset(self) -> Data:
        # Langflow FileInput에서 실제 파일 경로를 뽑습니다.
        # 여러 파일이 들어와도 이 예제는 첫 번째 파일만 처리하도록 단순화했습니다.
        paths = _file_paths_from_value(getattr(self, "dataset_file", None))
        if not paths:
            message = "No dataset file was provided."
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message], "warnings": []})

        path = paths[0]
        mode = _detect_mode(path, str(getattr(self, "parse_mode", "auto") or "auto"))

        try:
            # 모드별 reader를 분리해 두면 포맷별 예외 처리와 확장을 나중에 추가하기 쉽습니다.
            if mode == "csv":
                rows = _read_csv(path)
            elif mode == "json":
                rows = _read_json(path)
            elif mode == "jsonl":
                rows = _read_jsonl(path)
            elif mode in {"text", "markdown"}:
                rows = _read_text_lines(path)
            elif mode == "excel":
                rows = _read_excel(path)
            else:
                raise ValueError(f"Unsupported parse mode: {mode}")
        except Exception as exc:
            # custom node는 예외를 그대로 터뜨리기보다 errors payload로 반환하는 편이 flow 디버깅에 좋습니다.
            message = f"Failed to read {path.name}: {exc}"
            self.status = message
            return Data(data={"success": False, "rows": [], "errors": [message], "warnings": []})

        # preview는 UI/LLM에 보여줄 작은 샘플입니다. 전체 rows와 분리해 관리합니다.
        preview_limit = _clamp_int(getattr(self, "preview_limit", 20), 20, 0, 100)

        # 모든 row의 key를 합쳐 columns를 만들면 JSON row마다 컬럼이 조금 달라도 안전합니다.
        columns = sorted({key for row in rows for key in row})

        # downstream component가 공통으로 기대할 수 있는 dataset contract입니다.
        result: dict[str, Any] = {
            "success": True,
            "source_name": "uploaded_file",
            "file_name": path.name,
            "file_type": mode,
            "row_count": len(rows),
            "columns": columns,
            "preview_rows": rows[:preview_limit],
            "errors": [],
            "warnings": [],
        }

        if _as_bool(getattr(self, "include_full_rows", False), default=False):
            # 아주 작은 파일 실습에서는 전체 rows를 넘겨도 됩니다.
            result["rows"] = rows
        else:
            # 운영에서는 전체 데이터를 prompt/state에 싣지 않고 data_ref 저장소를 쓰는 쪽이 안전합니다.
            result["rows"] = []
            result["warnings"].append("Full rows omitted. Persist the dataset and pass data_ref for large flows.")

        # 카드 상태에는 사람이 빠르게 이해할 수 있는 짧은 문장을 둡니다.
        self.status = f"Loaded {len(rows)} rows from {path.name}"
        return Data(data=result)
