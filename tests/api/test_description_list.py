"""Regression: behaviour-row descriptions must reach the UI as a LIST.

`behaviorDescription` is one entry per call, but an entry can be a plain string. The old
`value or []` passed a non-empty string through unchanged, so the UI ran `.map()` on a string
and the whole document view died with "data.descriptionList.map is not a function"
(<BehaviorTableView>). Reported from the office run on the Math component.
"""
import pytest

from api.services.doc_render import _as_description_list

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value, expected", [
    # the crash case: a single string becomes a one-item list, not a sequence of characters
    ("Sends the request downstream.", ["Sends the request downstream."]),
    (["a", "b"], ["a", "b"]),                 # already a list
    (("a", "b"), ["a", "b"]),                 # tuple
    ([], []),
    (None, []),
    ("", []),                                  # empty/blank string -> no rows
    ("   ", []),
    (42, []),                                  # anything else is not renderable
    ({"a": 1}, []),
    (["a", None, "b"], ["a", "b"]),           # drop holes the engine may leave
])
def test_coerced_to_list(value, expected):
    out = _as_description_list(value)
    assert isinstance(out, list)
    assert out == expected


def test_string_is_not_exploded_into_characters():
    """The specific failure mode: iterating a string yields chars, which would render one row
    per letter even where it didn't crash."""
    assert _as_description_list("abc") == ["abc"]
