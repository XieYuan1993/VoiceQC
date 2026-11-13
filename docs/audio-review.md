# Optional Audio Review

Audio review is a project-scoped, advisory second opinion after ASR and text
correction. It never replaces transcript text or changes evaluation inputs.

## Deployment

From `infra/migrations`, run `uv run alembic upgrade head` before deploying the API
and workers. Migration `0019_audio_review` adds nullable JSON evidence to
`transcripts`; existing records need no backfill.

In Settings, enable **Audio review** (`asr.audio_review_enabled`). The virtual
default is false, including projects that have no saved setting yet. Turn it off
to stop reviews on future processing runs. Existing evidence remains visible.
Reprocess from STT to review an existing recording; re-evaluation alone does not
review audio. In-flight work may finish using the setting it already read.

The STT worker needs ffmpeg and the existing DashScope credentials/base URL with
access to `qwen3-omni-flash`. Provider/model names are not shown in the review UI.

## Bounds and Evidence

- At most three targets per recording, spaced at least eight seconds apart.
- Targets include number conflicts, identifier contexts, known spelling errors,
  unclear text, and low-confidence ASR segments.
- Target utterances longer than 25 seconds are skipped; context is three seconds
  on either side. Matching isolated speaker audio is preferred; mono audio is a
  fallback.
- Requests have a 20-second network timeout and a 90-second cooperative review
  budget; downloads and clipping also use bounded timeouts. These are not a hard
  process-level deadline.
- Provider failure or unclear audio leaves the transcript unchanged. Errors do
  not fail the recording. Evidence includes original/suggested text, time,
  speaker, agreement/conflict status, and reason.
- All differences require human review. Agreement is corroboration, not proof.
  No acceptance/edit workflow is implemented in this release.

## Smoke Test (2026-11-13)

The same four calls used for the Qwen 3.7/3.8 comparison were tested: S05, H3,
S10 and S13. Input was the saved Qwen 3.7 post-corrected transcript. Target
selection used no reference answers. Each call was limited to three targets.

Ten targets were selected: nine returned, one hit a connection timeout. The
observed additional times were 23.08, 4.54, 5.59 and 5.25 seconds respectively,
excluding production downloads, conversion and queue latency.

After an experimental auto-apply path reduced one call's text similarity,
automatic application was removed. The recorded responses were replayed through
the final advisory-only policy. Mean text similarity stays at 84.26%, mean
bigram F1 at 75.22%, and numeric recall at 39/52 (75%). These are reference-text
comparison metrics, not human-certified accuracy.

Two clear reference-supported numeric suggestions were found: an extra digit in
S05's identity number and the first digit of H3's policy number.
Other suggestions include formatting-only differences, uncertain numbers,
possible omissions, and language rewrites. They are not counted as verified
improvements. This small sample does not establish an overall accuracy gain.
