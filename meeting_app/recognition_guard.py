"""Conservative detection of long decoding loops, not ordinary repetitions."""
import re

REVIEW_TEXT = "[반복 출력 감지 · 이 구간은 인식 확인이 필요합니다.]"
REVIEW_STATUS = "인식 확인 필요"


def has_repetition_loop(text: str) -> bool:
    tokens = re.findall(r"[^\W_]+", text.casefold())
    for width in range(1, 5):
        minimum = 10 if width == 1 else 6
        for start in range(len(tokens) - width * minimum + 1):
            unit = tokens[start:start + width]
            if all(tokens[start + n * width:start + (n + 1) * width] == unit for n in range(1, minimum)):
                return True
    # Some outputs have no spaces between repeated syllables.
    compact = re.sub(r"[\W_]+", "", text.casefold())
    return any(len(match.group()) >= 16 for match in re.finditer(r"([^\W_]{1,8})\1{9,}", compact))
