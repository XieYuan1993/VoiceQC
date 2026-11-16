# Dyna ASR + Flow (optional provider)

The `dyna` provider uploads the original stereo PCM WAV to Dyna, polls the
asynchronous ASR task, then runs the Flow correction in bounded chunks. It
keeps the existing default provider unchanged. Mono and non-WAV originals are
explicitly rejected in this first integration; use the existing provider for
those recordings.

## STT Worker Environment

Configure these on the STT worker (or every worker consuming the STT queue):

```text
DYNA_BASE_URL=https://yz.cybotstar.cn
DYNA_ROBOT_KEY=<agent identifier exactly as provided>
DYNA_ROBOT_TOKEN=<API key>
DYNA_JWT=<JWT without the Bearer prefix>
DYNA_TENANT=brgroup
DYNA_USERNAME=baigong@brgroupp.com
DYNA_ROBOT_ID=202813
DYNA_FLOW_UUID=ef379f02-e0a4-11f1-8b21-a666c97c582e
DYNA_ASR_MODEL=manual_split_16k_yue
```

No account password is used. JWT is currently supplied manually: refresh the
environment and redeploy the STT worker when it expires. Credentials are never
stored in operation names, transcript metadata or the repository. Existing GCS
write access is needed for resumable raw/Flow checkpoints under
`stt-results/<recording-id>/dyna/<task-id>/`.

## Running a Comparison

Deploy API, STT worker and web together; no database migration is needed.
Batch rerun dialogs offer Dyna ASR + Flow Cantonese and Mandarin options.
Choose the appropriate language rather than submitting a mixed-language batch
under one fixed engine. Project settings can optionally select `dyna`, with
`asr.model=manual_split_16k_yue` or `manual_split_16k`; do not change the default
while comparing.

The provider includes its own Flow correction, so it bypasses the existing
Qwen post-correction and audio re-listening stages. CRS evaluation still runs
after transcription for FWD. The original source channel and the project's
`audio.broker_channel` setting determine roles; Flow 1/2 labels are ignored.
Flow line count, timestamps and nonempty text are checked before storing a
transcript. Raw and corrected checkpoints remain available for audit.

ASR operation IDs survive worker restart; completed Flow chunks are reused.
Timeouts/temporary network failures use existing STT retry and 30-minute
timeout logic. Authentication failures fail clearly instead of hanging. A
failure during upload or before an ASR operation ID is committed may repeat
submission on retry; file hashes allow platform upload deduplication.

## Upload Protocol Verification

The supplied HTML omitted part/complete request fields. These were confirmed
against the platform's public `fastUpload` module and validated using a fresh
one-second stereo silence WAV: multipart fields `file_uuid`, `part_number`,
`part_hash` (MD5), and `part_data`; complete takes JSON `{file_uuid}`. Both calls
returned success. The full four-call benchmark separately exercised ASR and
Flow on deduplicated uploaded customer recordings. Neither test establishes
production availability or independent ground-truth transcription accuracy.
