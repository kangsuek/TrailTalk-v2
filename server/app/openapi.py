"""OpenAPI 스키마를 JSON으로 내보낸다(웹 타입 생성 `npm run gen:api`용).

    uv run python -m app.openapi [출력 파일]

출력 파일을 주지 않으면 표준 출력으로 쓴다. 앱을 띄우지 않고(lifespan 없이) 스키마만 만든다.
"""

import json
import sys
from pathlib import Path

from app.main import create_app


def main() -> None:
    schema = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(schema, encoding="utf-8")
    else:
        sys.stdout.write(schema)


if __name__ == "__main__":
    main()
