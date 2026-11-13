# Scoped Greeting-Term Recovery

Text post-correction can recover an approved greeting term from an otherwise
rejected model response. This avoids rejecting a brand correction just because
the ASR brand spelling contains a spurious digit.

The exception requires all of the following:

- The turn belongs to the agent (`broker`).
- It contains a self-introduction and an explicit service greeting.
- A configured opening-greeting replacement targets an active glossary term.
- The source spelling matches at the beginning of the turn (allowing a short
  greeting), within the first 18 characters.
- The model proposes that approved term in its opening and retains a service
  greeting.

Only the exact term span is replaced. Every other character, including all
account, policy, date and amount values, remains unchanged. Unknown company
spellings, customer speech, and brand mentions elsewhere do not qualify.

Two narrowly scoped FWD numeric-looking spellings are recognized only when the
FWD glossary and opening-greeting rules are present: `5萬份保險` and its simplified
equivalent. The output phrase must also be in the active glossary. This is a
domain-specific spelling rule, not an exception for arbitrary numeric edits.

There is no extra model request. Existing safe model responses retain their
previous behavior. Audio-review suggestions remain advisory and are not
automatically fed into this recovery path.

## Validation (2026-11-13)

The S05, H3, S10 and S13 calls were run with Qwen 3.7 Max. Each model reply was
captured once and replayed through the old and new policies, keeping model
variation out of the comparison. No eligible greeting span was present in the
rejected replies: both policies scored 84.56% average text similarity, 75.77%
average bigram F1 and 39/52 numeric recall. No accuracy gain is claimed for these
four calls. Absolute values differ from earlier runs because model outputs vary.

A separate regression replay used the saved real S14 audio-model suggestion.
The old policy rejected the entire proposal because its brand correction
removed a digit. The new policy recovered only the brand span, leaving the
agent name, remaining wording, speaker and timestamp untouched. This checks
the recovery policy, not live model recall or general accuracy. S14 was not
included in the four-call score.

A local key-field verification worksheet contains 37 entries from the four
reference transcripts. Every entry is marked pending human audio review; the
reference is not assumed to be authoritative, and no names or numbers are
declared human-confirmed by this automated test.
