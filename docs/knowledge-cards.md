# Transcript Knowledge Cards

Migration `0020_knowledge_cards` creates a project-scoped knowledge-card table
and imports the bundled 19 FWD demo cards (92 triggers) into the existing
`fwd-insurance-demo` project. It does not import cards into other projects or
create a missing project. The snapshot was extracted from the supplied workbook's
`知识卡片清单` sheet; trailing instructions and scenario hints are excluded.

All card content is labelled as unverified FWD demo material, as stated in the
source workbook. Cards do not affect evaluation, ASR correction or transaction
reconciliation and are separate from the retrieval/embedding knowledge base.

## Deployment and Import

Deploy API and web together after applying migrations from `infra/migrations`
with `uv run alembic upgrade head`. The existing worker migration startup can
apply this migration. No worker environment variables or model calls are needed.

For updates or projects created after the migration, select the project, open
Knowledge > Import Excel, and upload the scenario XLSX.
Import replaces matching card codes within that project and preserves other
cards. It is atomic and repeatable; duplicate codes or malformed cards reject
the import. It does not delete cards omitted from a workbook.

A CLI alternative is available from the repository root:

```powershell
uv run python scripts/seed_fwd_knowledge_cards.py --slug fwd-insurance-demo --workbook "C:\path\to\FWD_Demo_经典场景清单.xlsx"
```

This command requires DATABASE_URL for the intended database. Add `--dry-run`
to inspect counts without connecting. No audio re-upload or ASR rerun is needed.

## Matching and Display

The transcript API scans each timed segment against current active cards in
the recording's project. One matching trigger is sufficient. Matching supports
Traditional/Simplified Chinese, case folding and common spacing differences;
ASCII words and numeric triggers use boundaries to avoid substring collisions.
This is keyword assistance, not semantic confirmation that a rule applies.
Phrases split across separate transcript segments are not combined.

Matching happens when the completed transcript is read, so imported or updated
cards also work for old recordings after refreshing the page. This application
uses batch ASR; this is not a live microphone/streaming transcription feature.

The recording page shows inline assistance beneath each matching transcript
turn: card title and a short suggested-reply preview. Clicking opens the full
card; linked FAQ questions open their full answer in the same dialog, with a
back action to return to the card. There is no aggregate list above the
transcript and no automatic modal interruption during playback.

The recorded incremental replay checkbox starts the audio timeline at zero and
reveals timed segments and their assistance as playback reaches them. Future
segments, raw text and audio-review summaries are not shown in this mode. It is
a recorded demo, not a new streaming ASR integration. Full transcript remains
the default view.

## FAQ Library and Editing

Migration `0021_knowledge_faqs` adds project-scoped FAQs and seeds the 43 supplied
FWD demo questions into the existing `fwd-insurance-demo` project. Apply
`uv run alembic upgrade head` from `infra/migrations` before using this update.
No new environment variables are needed. Existing recordings need only refresh,
not ASR or evaluation reruns.

The Knowledge navigation page provides cards and FAQ tabs, search, creation,
editing and activation checkboxes. Card editing includes trigger words,
suggested replies and related FAQ selection. Existing codes cannot be renamed
because they are reference keys; deactivate unwanted entries instead. Changes
and FAQ lookups are scoped to the active project. Transcript readers can open
linked active FAQs; editing requires configuration-write permission.

Workbook import and the CLI now also upsert the optional `常见问题库` sheet.
An existing project created after migration can use the same import action.
Import replaces fields and reactivates matching codes; omitted entries remain
unchanged. A subsequent import can overwrite manual edits for the same codes.
FAQ data keeps the workbook's unverified-demo notice.

Card imports require configuration-write permission. Configuration-read users
can preview cards; transcript-read users can see cards linked to recordings
they are allowed to read. Imports and transcript reads use the existing audit
logging. No new data is sent to external model providers.
