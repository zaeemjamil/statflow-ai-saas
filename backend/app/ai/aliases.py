"""
Column aliases: how original column names stay out of the evidence packet.

Sanitizing a column name does not anonymize it ("Salary_Jane_Doe" is still
"Salary_Jane_Doe" after control characters are stripped), so the packet never
contains an original column name. Every column is referred to by a
deterministic alias - ``Column_001``, ``Column_002`` ... - and the packet is
the only thing that may later leave the application.

The original <-> alias mapping lives ONLY in ``ColumnAliasMap``, which is kept
beside the packet (``EvidenceBuild.aliases``, never inside ``EvidencePacket``),
is never part of its content or fingerprint, and refuses to print or serialize
itself. A later stage uses it locally to turn the AI's ``Column_003`` back into
the real name for display.

Rules:
* Aliases are numbered in dataset column order, then (only if some other
  section mentions a name the profile lacks) in a fixed order of first mention.
* Lookup is by the EXACT original string, not a normalised one, so two names
  that look alike (``café`` spelled two ways, ``Price`` and ``price ``) get two
  different aliases and can never collide.
* If the same exact name occurs twice in the profile, each position still gets
  its own alias. A reference *by name* cannot tell those columns apart, so
  ``is_duplicated`` reports it and the evidence builder does NOT pick one:
  it writes ``AMBIGUOUS_ALIAS`` instead. (``alias_for`` still returns the
  first slot, for local code that knowingly wants "the first column of that
  name".)
"""

from __future__ import annotations

from collections.abc import Sequence

ALIAS_PREFIX = "Column_"
MIN_ALIAS_DIGITS = 3
# Written in the packet where a name-only reference matches several columns.
AMBIGUOUS_ALIAS = "Column_ambiguous"


class ColumnAliasMap:
    """Local-only. Never put this, or anything derived from it that contains
    an original name, into an evidence packet or a log line."""

    __slots__ = ("_first_slot", "_originals", "_slot_counts", "_width")

    def __init__(self, originals: Sequence[str]) -> None:
        self._originals: tuple[str, ...] = tuple(originals)
        self._first_slot: dict[str, int] = {}
        self._slot_counts: dict[str, int] = {}
        for slot, name in enumerate(self._originals):
            self._first_slot.setdefault(name, slot)
            self._slot_counts[name] = self._slot_counts.get(name, 0) + 1
        self._width = max(MIN_ALIAS_DIGITS, len(str(len(self._originals))))

    def __len__(self) -> int:
        return len(self._originals)

    def alias_for_slot(self, slot: int) -> str:
        if not 0 <= slot < len(self._originals):
            raise IndexError(slot)
        return f"{ALIAS_PREFIX}{slot + 1:0{self._width}d}"

    def alias_for(self, original: str) -> str:
        """Alias of an exact original name; ``KeyError`` if it is unknown."""
        return self.alias_for_slot(self._first_slot[original])

    def is_duplicated(self, original: str) -> bool:
        """True when this exact name belongs to more than one column."""
        return self._slot_counts.get(original, 0) > 1

    def duplicated_groups(self) -> list[list[str]]:
        """Aliases of each group of columns sharing one exact name (local
        order of first appearance). The aliases carry no name."""
        groups: dict[str, list[str]] = {}
        for slot, name in enumerate(self._originals):
            if self._slot_counts[name] > 1:
                groups.setdefault(name, []).append(self.alias_for_slot(slot))
        return list(groups.values())

    def has(self, original: str) -> bool:
        return original in self._first_slot

    def original_for(self, alias: str) -> str:
        """The original name behind an alias; ``KeyError`` if there is none."""
        if alias.startswith(ALIAS_PREFIX):
            digits = alias[len(ALIAS_PREFIX) :]
            if digits.isascii() and digits.isdigit():
                slot = int(digits) - 1
                if 0 <= slot < len(self._originals) and self.alias_for_slot(slot) == alias:
                    return self._originals[slot]
        raise KeyError(alias)

    def aliases(self) -> list[str]:
        return [self.alias_for_slot(slot) for slot in range(len(self._originals))]

    # Printing or serializing must not leak names by accident.
    def __repr__(self) -> str:
        return f"<ColumnAliasMap: {len(self)} columns, local only>"

    __str__ = __repr__

    def __reduce__(self) -> str | tuple[object, ...]:
        raise TypeError("ColumnAliasMap is local-only and must not be pickled or serialized.")

    def __copy__(self) -> ColumnAliasMap:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> ColumnAliasMap:
        return self
