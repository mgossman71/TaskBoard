from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict

T = TypeVar("T")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_line(v: str) -> str:
    v = unicodedata.normalize("NFC", v)
    v = _CONTROL.sub("", v).replace("\r", "").replace("\n", " ").replace("\t", " ")
    v = " ".join(v.split())
    if not v:
        raise ValueError("must not be blank")
    return v


def _clean_text(v: str) -> str:
    v = unicodedata.normalize("NFC", v)
    return _CONTROL.sub("", v).replace("\r\n", "\n").strip()


# Single-line, trimmed, non-blank, control-character free text
CleanStr = Annotated[str, AfterValidator(_clean_line)]
# Multi-line text (descriptions, comments) with control characters removed
CleanText = Annotated[str, AfterValidator(_clean_text)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    total: int | None = None
