# -*- coding: utf-8 -*-
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(__file__).resolve().parents[1] / "sample_files"
PAGE_W = 1240
PAGE_H = 1754


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("C:/Windows/Fonts/malgunbd.ttf"),
        Path("C:/Windows/Fonts/NotoSansCJK-Regular.ttc"),
    ]
    if "bold" in name.lower():
        candidates.insert(0, Path("C:/Windows/Fonts/malgunbd.ttf"))
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT = load_font("regular", 34)
SMALL = load_font("regular", 26)
TINY = load_font("regular", 22)
BOLD = load_font("bold", 44)
MEDIUM_BOLD = load_font("bold", 32)


def base_page(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (PAGE_W, PAGE_H), "#ffffff")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, PAGE_W, 140], fill="#17202c")
    draw.text((70, 38), title, font=BOLD, fill="#ffffff")
    draw.text((72, 96), subtitle, font=SMALL, fill="#c5d0df")
    draw.line([70, 165, PAGE_W - 70, 165], fill="#d9e0e8", width=3)
    return img, draw


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: str = "#17202c",
    max_chars: int = 34,
    line_gap: int = 12,
) -> int:
    x, y = xy
    for para in text.split("\n"):
        line = ""
        for char in para:
            line += char
            if len(line) >= max_chars:
                draw.text((x, y), line, font=font, fill=fill)
                y += font.size + line_gap
                line = ""
        if line:
            draw.text((x, y), line, font=font, fill=fill)
            y += font.size + line_gap
        y += line_gap
    return y


def page_summary() -> Image.Image:
    img, draw = base_page("C라인 품질 개선 리포트", "이미지 기반 PDF/OCR/Vision 실습용 샘플")
    draw.text((80, 220), "문서 요약", font=MEDIUM_BOLD, fill="#0f766e")
    body = (
        "이 문서는 Langflow 멀티모달 RAG 실습을 위해 만든 샘플입니다.\n"
        "목표는 PDF에서 텍스트와 이미지 기반 정보를 함께 추출하고,\n"
        "Milvus에 저장한 뒤 질문에 답하는 것입니다.\n\n"
        "핵심 수치:\n"
        "- 대상 라인: C라인\n"
        "- 가장 높은 defect_rate: LOT-C-2409, 0.0323\n"
        "- 주요 원인: 금형 냉각 편차\n"
        "- 권장 조치: 냉각수 유량 점검 후 금형 조건 재승인"
    )
    draw_wrapped(draw, (90, 285), body, FONT, max_chars=100)
    draw.rounded_rectangle([90, 980, 1150, 1220], radius=18, outline="#c7d2df", width=3, fill="#f8fbff")
    draw.text((125, 1030), "실습 질문 예시", font=MEDIUM_BOLD, fill="#17202c")
    draw_wrapped(draw, (125, 1090), "이 문서에서 가장 위험한 lot과 원인, 권장 조치를 요약해줘.", SMALL, max_chars=39)
    return img


def page_process() -> Image.Image:
    img, draw = base_page("C라인 공정 흐름도", "Page 2 - 공정 병목과 재작업 루프")
    draw.text((80, 220), "공정 단계", font=MEDIUM_BOLD, fill="#0f766e")
    steps = [
        ("입고 검사", "평균 8분"),
        ("성형", "평균 19분"),
        ("냉각", "평균 31분"),
        ("검사 대기", "평균 42분"),
        ("재작업", "불량 lot 재투입"),
        ("출하 승인", "최종 확인"),
    ]
    positions = [(90, 330), (470, 330), (850, 330), (850, 590), (470, 590), (90, 590)]
    box_w = 300
    box_h = 130
    for (name, desc), (x, y) in zip(steps, positions):
        fill = "#fff0d5" if name == "검사 대기" else "#f8fbff"
        outline = "#b45309" if name == "검사 대기" else "#c7d2df"
        draw.rounded_rectangle([x, y, x + box_w, y + box_h], radius=14, fill=fill, outline=outline, width=4)
        draw.text((x + 24, y + 24), name, font=MEDIUM_BOLD, fill="#17202c")
        draw.text((x + 24, y + 76), desc, font=SMALL, fill="#5a6675")

    for (x1, y1), (x2, y2) in zip(positions[:3], positions[1:4]):
        draw.line([x1 + box_w, y1 + 65, x2, y2 + 65], fill="#5a6675", width=5)
        draw.polygon([(x2 - 12, y2 + 53), (x2, y2 + 65), (x2 - 12, y2 + 77)], fill="#5a6675")

    for (x1, y1), (x2, y2) in zip(positions[3:5], positions[4:6]):
        draw.line([x1, y1 + 65, x2 + box_w, y2 + 65], fill="#5a6675", width=5)
        draw.polygon([(x2 + box_w + 12, y2 + 53), (x2 + box_w, y2 + 65), (x2 + box_w + 12, y2 + 77)], fill="#5a6675")

    draw.arc([430, 470, 930, 760], start=205, end=350, fill="#be123c", width=5)
    draw.polygon([(910, 545), (932, 540), (920, 562)], fill="#be123c")

    draw.text((90, 860), "시각적 해석 포인트", font=MEDIUM_BOLD, fill="#0f766e")
    points = (
        "- 검사 대기 단계가 평균 42분으로 가장 길어 병목 후보입니다.\n"
        "- 재작업은 냉각 단계로 되돌아가는 루프를 만들며 처리 시간을 늘립니다.\n"
        "- LOT-C-2409는 냉각수 유량 점검과 금형 조건 재승인이 우선입니다."
    )
    draw_wrapped(draw, (90, 930), points, FONT, max_chars=33)
    return img


def page_chart() -> Image.Image:
    img, draw = base_page("LOT별 defect_rate 차트", "Page 3 - 품질 위험 우선순위")
    draw.text((80, 220), "Defect rate", font=MEDIUM_BOLD, fill="#0f766e")
    data = [
        ("LOT-C-2405", 0.0142),
        ("LOT-C-2406", 0.0281),
        ("LOT-C-2407", 0.0198),
        ("LOT-C-2408", 0.0287),
        ("LOT-C-2409", 0.0323),
    ]
    chart_y = 360
    bar_h = 82
    max_v = 0.035
    for i, (lot, value) in enumerate(data):
        y = chart_y + i * 145
        draw.text((90, y + 18), lot, font=SMALL, fill="#17202c")
        draw.rectangle([310, y, 1040, y + bar_h], outline="#d9e0e8", width=2, fill="#f8fbff")
        width = int((value / max_v) * 700)
        color = "#be123c" if lot == "LOT-C-2409" else ("#b45309" if value > 0.028 else "#0f766e")
        draw.rectangle([310, y, 310 + width, y + bar_h], fill=color)
        draw.text((1060, y + 18), f"{value:.4f}", font=SMALL, fill=color)

    draw.rounded_rectangle([90, 1135, 1150, 1425], radius=18, outline="#c7d2df", width=3, fill="#f8fbff")
    draw.text((125, 1185), "차트 해석", font=MEDIUM_BOLD, fill="#17202c")
    draw_wrapped(
        draw,
        (125, 1245),
        "LOT-C-2409가 0.0323으로 가장 높습니다.\n"
        "LOT-C-2408과 LOT-C-2406도 0.028 이상이므로\n"
        "C라인 냉각/지그/금형 조건을 함께 점검해야 합니다.",
        SMALL,
        max_chars=100,
        line_gap=10,
    )
    return img


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    pages = [page_summary(), page_process(), page_chart()]
    pages[0].save(OUT_DIR / "sample_visual_process_report_page1.png")
    pages[1].save(OUT_DIR / "sample_visual_process_report_page2.png")
    pages[2].save(OUT_DIR / "sample_visual_process_report_page3.png")
    pages[0].save(
        OUT_DIR / "sample_visual_process_report.pdf",
        save_all=True,
        append_images=pages[1:],
        resolution=150.0,
    )
    print(OUT_DIR / "sample_visual_process_report.pdf")


if __name__ == "__main__":
    main()
