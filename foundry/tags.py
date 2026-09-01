from __future__ import annotations

CLAIMED = "报表声称"
RECOMPUTED = "我重算"
AGREED = "两者一致"
OUTSIDE = "稿外追问"
NOT_IN_WINDOW = "not-in-this-window"
EXTERNAL = "外部引用"

# The three words that may only ever describe a figure the locked catalog
# produced. A reference the analyst found outside the window carries EXTERNAL
# and its source; letting it borrow one of these would make the brief say a
# number was derived when it was read somewhere.
LOCK_WORDS = frozenset({CLAIMED, RECOMPUTED, AGREED})

# Everything a cited line may never wear. The three above, plus the two marks
# that describe the brief's own structure: a reference is neither a follow-up
# nor a refusal, and a line that called itself one would be read as one.
RESERVED_WORDS = LOCK_WORDS | {OUTSIDE, NOT_IN_WINDOW}
