# Transcript Amendments and Hotword Annotations

Each transcript turn has a pencil action for users with evaluation-review
permission. Admin/configuration managers also get a tag action to add a term
or annotate a wrong-to-correct spelling from that sentence. Selecting text
before clicking the tag pre-fills the observed word. An empty wrong field adds
only a canonical hotword; it does not create a correction replacement rule.

The PATCH endpoint checks recording/project/user scope, blocks active pipeline
jobs, locks the recording row, and compares expected text to prevent lost
updates. Segment text and the full transcript are changed in the same
transaction. Roles and timings are unchanged. Audit entries retain before and
after text and the actor. Hotword approval requires migration `0022_term_approval`.

Hotwords require TERMS_WRITE, are scoped to the recording's project, and use
the existing term dictionary plus contextual correction settings. New terms,
CSV imports and edits start pending and inactive, with submitter attribution.
Only an admin may approve or reject. Approval publishes correction rules and
activates the term atomically. Existing terms retain their state on migration;
legacy submitters are unknown. Editing an approved term resubmits it and
temporarily deactivates the term. Wrong
spellings are NOT added as ASR adaptation aliases. Existing conflicting
correction mappings return a conflict instead of being silently overwritten.
These changes do not mass-rewrite other recordings. They do not retrain an
ASR model or automatically update the external Dyna agent's own vocabulary.

Manual edit time is exposed independently of ASR completion time. Old
evaluations remain intact; the CRS panel warns if the selected run predates
the amendment. Use reclassify/re-evaluate to regenerate derived results.
Knowledge-card and complaint hints are recomputed from edited segments on
refresh. Reprocessing ASR replaces the transcript, so export manual work first.

The single-call Reprocess menu now supports Dyna Cantonese/Mandarin explicitly.
The per-call provider/model override is saved for pipeline recovery without
changing project defaults. Existing default reprocess behavior remains intact.
