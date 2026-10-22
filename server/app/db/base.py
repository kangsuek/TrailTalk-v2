from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# SQLite batch 마이그레이션이 제약을 이름으로 찾을 수 있도록 이름 규칙을 고정한다.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """모든 모델의 기반 클래스."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
