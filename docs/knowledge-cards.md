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
Settings > Knowledge cards > Import workbook, and upload the scenario XLSX.
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

The recording page shows all matching cards and trigger timestamps. Each
matching segment has a card-code button. Clicking opens a modal containing the
key points, procedure/documents, suggested reply, related products/questions and
source. Playback automatically opens the first unseen card when its trigger
segment is reached; simultaneous cards remain manually available and do not
open a stack of modals. Auto-open can be disabled on the recording page.

Card imports require configuration-write permission. Configuration-read users
can preview cards; transcript-read users can see cards linked to recordings
they are allowed to read. Imports and transcript reads use the existing audit
logging. No new data is sent to external model providers.
