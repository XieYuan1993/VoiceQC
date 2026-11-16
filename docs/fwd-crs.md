# FWD CRS Classification

The existing evaluation queue now supports a CRS-only mode for the
`fwd-insurance-demo` project, or an explicit `crs_classification` project module.
Other projects retain their existing quality/trade workflow.

This mode analyses the full transcript in one structured LLM call and returns
multiple distinct enquiries. It does not score criteria, extract trades or
call embeddings/KB retrieval. Token budgets, retry/timeouts, run history and
usage accounting reuse the existing evaluation pipeline.

The bundled catalogue comes from the supplied workbook's `CRS与知识卡片` sheet:
29 enquiry examples reduced to 20 unique category/event/content combinations,
plus 11 Reason values. It is a demo subset, NOT the full enterprise CRS taxonomy.
The model selects a catalogue ID; server code resolves the canonical labels.
Unknown classifications, uncertain Reasons and unverifiable quotations are
marked for review rather than inventing business codes.

Results are stored under `Evaluation.extracted_call_fields.crs` with a catalogue
snapshot in `fields_snapshot`. No schema migration is needed. Past evaluations
are preserved. The recording detail page shows CRS results below Transcript,
with enquiry, category, event detail, content detail, Reason, rationale and
evidence. Historical CRS runs can be selected; old QA runs are not relabelled.

Deploy API, worker and web together. New FWD batches run transcription followed
by CRS classification. The pipeline also permits CRS on previously
transcription-only FWD batches. Existing transcripts can use the recording's
CRS `重新分類` button or the existing scoped bulk re-evaluate action without
rerunning ASR. No existing data is automatically reprocessed by deployment.

The current configured LLM provider/model is reused; no new credentials or
environment variables are required. This change does not add a production CRS
integration or submit records to FWD's downstream systems.
