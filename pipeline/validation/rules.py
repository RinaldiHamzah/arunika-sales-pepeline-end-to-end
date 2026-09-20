"""Deterministic data-quality primitives; no locale-dependent guessing."""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation

MISSING = {"", "null", "none", "nan", "n/a", "na"}


def clean_text(value):
    if value is None:
        return None
    value = " ".join(unicodedata.normalize("NFKC", str(value)).split())
    return None if value.casefold() in MISSING else value


def match_key(value):
    """Match case/separators, but preserve digits, units, shades, and SPF '+' signs."""
    value = clean_text(value) or ""
    return re.sub(r"[\s_\-]+", "", value.casefold())


def number(value, integer=False):
    value = clean_text(value)
    if value is None:
        return None, "MISSING_REQUIRED"
    try:
        result = Decimal(value)
        if not result.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        return None, "INVALID_NUMBER"
    if result <= 0:
        return None, "NON_POSITIVE"
    if integer:
        if result != result.to_integral_value() or result > 2147483647:
            return None, "INVALID_INTEGER"
        return int(result), None
    if result > Decimal("999999999999.99") or result != result.quantize(Decimal(".01")):
        return None, "INVALID_MONEY_PRECISION_OR_RANGE"
    return result.quantize(Decimal(".01")), None


def parse_date(value, source):
    value = clean_text(value)
    if value is None:
        return None, "MISSING_REQUIRED"
    months = {
        m: i + 1
        for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])
    }
    try:
        if source == "website":
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(value, fmt), None
                except ValueError:
                    pass
            m = re.fullmatch(r"([A-Za-z]{3}) (\d{1,2}), (\d{4})", value)
            if m:
                return datetime(int(m[3]), months[m[1].lower()], int(m[2])), None
        if source == "offline":
            m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", value)
            if m:
                return datetime(int(m[3]), months[m[2].lower()], int(m[1])), None
        formats = ["%Y-%m-%d"]
        if source in {"shopee", "tokopedia"}:
            formats.append("%d/%m/%Y")
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt), None
            except ValueError:
                pass
    except (ValueError, KeyError):
        pass
    return None, "INVALID_DATE"
