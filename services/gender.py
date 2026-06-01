from __future__ import annotations


def parse_gender(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper().replace("Ё", "Е")
    if not s:
        return None
    if s in ("М", "M", "MALE", "МУЖ", "МУЖЧИНА", "MAN"):
        return "male"
    if s in ("Ж", "F", "FEMALE", "ЖЕН", "ЖЕНЩИНА", "WOMAN"):
        return "female"
    return None


def gender_label(code: str | None) -> str:
    if code == "male":
        return "Мужчина"
    if code == "female":
        return "Женщина"
    return "—"
