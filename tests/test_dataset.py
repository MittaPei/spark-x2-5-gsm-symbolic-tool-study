import hashlib

from spark_math_eval.dataset import (
    EXPECTED_KEY_LIST_SHA256,
    EXPECTED_KEYS,
    sha256_text,
)


def test_frozen_key_list_checksum() -> None:
    rendered = "".join(f"{item_id},{instance}\n" for item_id, instance in EXPECTED_KEYS)
    assert hashlib.sha256(rendered.encode()).hexdigest() == EXPECTED_KEY_LIST_SHA256


def test_sha256_text_is_utf8() -> None:
    assert sha256_text("合肥") == hashlib.sha256("合肥".encode()).hexdigest()
