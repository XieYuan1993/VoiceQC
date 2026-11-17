# UI Language

Application-authored UI copy is English: navigation, buttons, form labels,
status labels, alerts, table headings, tooltips and accessibility labels.
Risk-type labels returned by the application are also English.

Business content is not translated for display. Transcripts, knowledge-card
content, FAQs, CRS classifications, hotwords, uploaded names, filenames and
transaction values retain their original language. Detection phrases,
regular expressions and transaction-status values must not be translated.
The English form labels are separate from these values.

Run `pnpm --dir apps/web check:ui-language` to scan authored UI text. The check
allows multilingual literals only inside the specific business vocabulary
declarations listed in `scripts/check-ui-language.cjs`; avoid broad file-level
exceptions. Runtime business content is rendered directly, without a
translation or text-replacement layer.

This UI-only change requires no data migration. The separate hotword approval
feature requires migration `0022_term_approval` before the new API is deployed.
