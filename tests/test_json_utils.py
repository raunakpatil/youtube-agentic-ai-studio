import pytest

from agents.json_utils import extract_json


def test_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_strips_markdown_fences_and_chatter():
    raw = 'Sure! ```json\n{"a": {"b": [1, 2]}}\n``` hope that helps {x}'
    assert extract_json(raw) == {"a": {"b": [1, 2]}}


def test_closes_missing_bracket_before_brace():
    # real Pollinations output: the tags array was never closed
    raw = '{"topic": "x", "tags": ["relativity", "science"}'
    assert extract_json(raw) == {"topic": "x", "tags": ["relativity", "science"]}


def test_closes_truncated_output():
    raw = '{"titles": [{"title": "A", "style": "q"}, {"title": "B"'
    assert extract_json(raw) == {"titles": [{"title": "A", "style": "q"}, {"title": "B"}]}


def test_removes_trailing_commas():
    assert extract_json('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3}


def test_keeps_escaped_quotes():
    assert extract_json(r'{"q": "he said \"hi\""}') == {"q": 'he said "hi"'}


def test_raises_without_json():
    with pytest.raises(ValueError):
        extract_json("no json here", "Test")
