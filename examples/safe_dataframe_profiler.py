from __future__ import annotations

from typing import Any

# DataFrameInput/DataFrame은 Langflow 내부 Table 포트와 연결되는 핵심 타입입니다.
# Langflow 코드창에 붙여넣을 때 이 import 줄을 포함해야 Component를 인식합니다.
from lfx.custom import Component
from lfx.io import DataFrameInput, IntInput, Output
from lfx.schema import Data, DataFrame


def _to_records(value: Any) -> list[dict[str, Any]]:
    # DataFrame이 비어 있거나 upstream 연결이 없으면 빈 row list로 처리합니다.
    if value is None:
        return []

    # pandas DataFrame 또는 Langflow DataFrame wrapper는 `to_dict(orient="records")`를 지원할 수 있습니다.
    # 이 경로가 가장 표준적인 table -> list[dict] 변환입니다.
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            records = to_dict(orient="records")
            if isinstance(records, list):
                # dict row만 유지하면 downstream에서 key 접근이 안전합니다.
                return [row for row in records if isinstance(row, dict)]
        except TypeError:
            # 일부 wrapper는 orient 인자를 받지 않을 수 있어 다음 fallback으로 넘어갑니다.
            pass

    # Langflow DataFrame/Data 객체가 `.data`에 list row를 담는 경우를 처리합니다.
    data = getattr(value, "data", None)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    # 테스트나 간단한 custom node 연결에서는 list[dict]가 직접 들어올 수도 있습니다.
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]

    # 알 수 없는 table 형태는 예외를 내지 않고 빈 list로 둡니다.
    return []


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    # preview row 수는 LLM prompt 크기와 직접 연결되므로 최대치를 제한합니다.
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


class SafeDataFrameProfiler(Component):
    display_name = "Safe DataFrame Profiler"
    description = "Summarize table shape and emit a stable preview without sending the full table to an LLM."
    icon = "TableProperties"
    name = "SafeDataFrameProfiler"

    # DataFrameInput은 CSV/SQL/Table Operations 같은 component의 Table/DataFrame output에 연결합니다.
    # 전체 table을 LLM에 보내지 않고 profile과 preview를 나누어 만드는 것이 목적입니다.
    inputs = [
        DataFrameInput(
            name="table",
            display_name="Table",
            info="DataFrame output from an upstream table-producing node.",
            required=True,
        ),
        IntInput(
            name="preview_limit",
            display_name="Preview Limit",
            value=20,
            # 운영자가 조정할 수 있는 값이지만 기본 교육 화면에서는 숨겨도 됩니다.
            advanced=True,
        ),
    ]

    # profile은 JSON-like Data, preview는 다시 DataFrame으로 내보냅니다.
    # 이렇게 하면 한쪽은 LLM/Prompt용, 다른 한쪽은 Table viewer/후속 table 작업용으로 쓸 수 있습니다.
    outputs = [
        Output(name="profile", display_name="Profile", method="build_profile", types=["Data"]),
        Output(name="preview", display_name="Preview Table", method="build_preview", types=["DataFrame"]),
    ]

    def _records(self) -> list[dict[str, Any]]:
        # 여러 method에서 같은 table 변환 로직을 쓰도록 한 곳으로 모읍니다.
        return _to_records(getattr(self, "table", None))

    def build_profile(self) -> Data:
        # rows는 전체 데이터를 내부에서만 읽고, 반환 payload에는 preview만 넣습니다.
        rows = self._records()

        # row마다 key가 조금 달라도 전체 column 후보를 모두 수집합니다.
        columns = sorted({key for row in rows for key in row})

        # preview_limit은 0~100 사이로 제한하여 큰 테이블이 prompt로 새는 것을 방지합니다.
        preview_limit = _clamp_int(getattr(self, "preview_limit", 20), 20, 0, 100)

        # LLM이나 answer builder가 읽기 좋은 작은 profile contract입니다.
        result = {
            "success": True,
            "row_count": len(rows),
            "columns": columns,
            "preview_rows": rows[:preview_limit],
            "errors": [],
            "warnings": [],
        }

        # status에는 테이블 크기만 간단히 남겨 UI에서 즉시 확인할 수 있게 합니다.
        self.status = f"Profiled {len(rows)} rows"
        return Data(data=result)

    def build_preview(self) -> DataFrame:
        # 사람이 Inspect Output에서 볼 수 있는 작은 DataFrame preview입니다.
        # profile과 별도 output으로 두면 표 형태 UI를 그대로 활용할 수 있습니다.
        rows = self._records()
        preview_limit = _clamp_int(getattr(self, "preview_limit", 20), 20, 0, 100)
        return DataFrame(rows[:preview_limit])
