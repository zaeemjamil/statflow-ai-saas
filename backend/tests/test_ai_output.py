"""Phase 9 Stage 2: model output is untrusted. Parsing, sanitizing and the
alias round trip."""

from __future__ import annotations

import json

import pytest

from app.ai.aliases import ColumnAliasMap
from app.ai.output import (
    DUPLICATE_COLUMN,
    ITEM_MAX,
    SUMMARY_MAX,
    UNKNOWN_COLUMN,
    InvalidAIOutput,
    parse_provider_output,
    translate_aliases,
)

KNOWN = frozenset({"Column_001", "Column_002", "Column_003"})


def _parse(payload: object) -> object:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return parse_provider_output(raw, KNOWN)


def test_a_well_formed_reply_is_accepted() -> None:
    out = parse_provider_output(
        json.dumps(
            {
                "summary": "Column_001 and Column_002 are associated.",
                "key_findings": ["a", "b"],
                "limitations": ["Association only."],
            }
        ),
        KNOWN,
    )
    assert out.summary.startswith("Column_001")
    assert out.key_findings == ["a", "b"] and out.next_steps == [] and out.data_quality == []


def test_code_fences_around_json_are_tolerated() -> None:
    raw = '```json\n{"summary": "ok"}\n```'
    assert parse_provider_output(raw, KNOWN).summary == "ok"


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not json", "[1, 2]", '"just a string"', "{}", '{"summary": 5}', '{"summary": ""}'],
)
def test_unusable_replies_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidAIOutput):
        parse_provider_output(raw, KNOWN)


def test_a_non_list_field_is_rejected() -> None:
    with pytest.raises(InvalidAIOutput):
        parse_provider_output('{"summary": "x", "key_findings": "oops"}', KNOWN)


def test_an_oversized_reply_is_rejected() -> None:
    with pytest.raises(InvalidAIOutput):
        parse_provider_output('{"summary": "' + "a" * 30_000 + '"}', KNOWN)


def test_lengths_and_counts_are_bounded_not_trusted() -> None:
    out = parse_provider_output(
        json.dumps(
            {
                "summary": "s" * 5000,
                "key_findings": ["k" * 600] * 20,
                "next_steps": ["n"] * 20,
                "unexpected_key": "ignored",
            }
        ),
        KNOWN,
    )
    assert len(out.summary) <= SUMMARY_MAX
    assert len(out.key_findings) == 6 and all(len(x) <= ITEM_MAX for x in out.key_findings)
    assert len(out.next_steps) == 4
    assert not hasattr(out, "unexpected_key")


def test_control_bidi_characters_and_links_are_removed() -> None:
    nasty = "Hi\x00 there\u202e evil\u200b see https://evil.example/x?a=1 and www.evil.test now"
    out = parse_provider_output(json.dumps({"summary": nasty}), KNOWN)
    assert "\x00" not in out.summary and "\u202e" not in out.summary and "\u200b" not in out.summary
    assert "evil.example" not in out.summary and "evil.test" not in out.summary
    assert "[link removed]" in out.summary


def test_invented_aliases_never_survive() -> None:
    out = parse_provider_output(
        json.dumps({"summary": "Column_001 vs Column_999 and Column_ambiguous and Column_1234"}),
        KNOWN,
    )
    assert "Column_001" in out.summary and "Column_ambiguous" in out.summary
    assert "Column_999" not in out.summary and "Column_1234" not in out.summary
    assert out.summary.count(UNKNOWN_COLUMN) == 2


def test_translation_restores_real_names_for_display_only() -> None:
    aliases = ColumnAliasMap(["revenue", "ad spend", "region"])
    text = translate_aliases("Column_002 drives Column_001; ignore Column_009.", aliases)
    assert text == f"“ad spend” drives “revenue”; ignore {UNKNOWN_COLUMN}."


def test_translation_never_names_a_duplicated_column() -> None:
    aliases = ColumnAliasMap(["same", "same", "other"])
    text = translate_aliases("Column_001, Column_002 and Column_003", aliases)
    assert text.count(DUPLICATE_COLUMN) == 2 and "“other”" in text and "same" not in text


def test_hostile_original_names_are_sanitized_when_displayed() -> None:
    name = "bad\u202e\x00name https://evil.example " + "z" * 200
    text = translate_aliases("See Column_001.", ColumnAliasMap([name]))
    assert "\u202e" not in text and "\x00" not in text and "evil.example" not in text
    assert len(text) < 140
