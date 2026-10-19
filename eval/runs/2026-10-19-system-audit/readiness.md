# Readiness

Gate: **NOT READY**

File, dataset-contract, recorded live-eval and submission-reference readiness; not a product/privacy certification

Presence checks confirm files only. Live execution requires explicit provenance-bound evidence.

| Check | State | Scope | Evidence / missing work |
| --- | --- | --- | --- |
| backend | present | presence_only | backend/app/main.py: present; behavior not verified by file presence |
| rag | present | presence_only | rag/retriever.py: present; behavior not verified by file presence |
| frontend | present | presence_only | frontend/package.json: present; behavior not verified by file presence |
| dataset | present | presence_only | data/processed/pois.json: present; behavior not verified by file presence |
| dataset_contract | passed | offline_contract | 14006 POIs; schema checked, sources not independently audited |
| live_evaluation | pending | measured_execution | No --evidence report supplied; offline fixture tests establish QA-tool correctness only |
| submission_documents | present | presence_only | Required preparation documents present; factual review still required |
| submission_artifacts | pending | references_only | No valid docs/submission.json; supply slides_path and demo_url after the working demo exists |

## Not verified

- Privacy: real application logs, storage, consent and coordinate rounding require inspection.
- Frontend UX, map interactions, race conditions and live demo behavior require execution.
- POI source accuracy, pedestrian access and current opening hours require source/human review.
- Faithfulness, explanation quality and RU/KK/EN fluency require calibrated human/judge review.
- A local report is operator-provided evidence; this gate cannot authenticate its author or detect an undisclosed mock server.
