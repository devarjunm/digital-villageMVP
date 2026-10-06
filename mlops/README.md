# mlops

Operational scripts for the model lifecycle. Everything here is safe to run in a
restricted environment: no downloads, no third-party services, no training unless you
explicitly ask for it.

| Script | Purpose | Typical use |
|---|---|---|
| `validate_artifacts.py` | Refuses an artefact that cannot state its provenance, metrics or calibration status | CI, and step 2 of the model release in `docs/deployment.md` §5 |
| `train_all.py` | Trains every component that has a training entrypoint, reports the ones it skipped **and why**, then validates what was produced | Nightly retrain, or a deliberate model release |
| `monitor_models.py` | Model health from the application database: installed vs pinned versions, inference volume, latency, error breakdown, input drift against the artefact's documented envelope | On-call triage, and a scheduled job that posts its output |

## Examples

```bash
# 1. Would this artefact be deployable?
python mlops/validate_artifacts.py
python mlops/validate_artifacts.py crop-recommendation --strict

# 2. What would training do, before doing it?
python mlops/train_all.py --dry-run
python mlops/train_all.py --only crop_recommendation --register

# 3. How are the deployed models behaving?
DATABASE_URL='postgresql+psycopg://dv:dv_password@localhost:5432/digital_village' \
  python mlops/monitor_models.py --days 7
DATABASE_URL='…' python mlops/monitor_models.py --json   # for a scheduler
```

## Rules these scripts enforce

1. **An artefact is a release artefact.** It must carry a model card (task, framework,
   dataset provenance), a metrics file, and an explicit calibration status. The API's
   wording ("relative model score" vs "probability") is derived from that status, so a
   missing field is a correctness problem, not a documentation gap.
2. **A skipped component is announced.** `train_all.py` exits non-zero when a component
   has no training entrypoint, unless `--allow-skips` is passed — so "we only shipped one
   of the four AI capabilities" is always a recorded decision rather than a surprise.
3. **No accuracy is invented.** Offline metrics come from a named evaluation split inside
   the artefact. Production accuracy is never reported from served traffic, because
   served requests have no ground-truth labels.
4. **Drift is reported against the model's own envelope** (the ranges in
   `feature_names.json` that the API already uses to refuse out-of-range input), not
   against an arbitrary threshold chosen to make a dashboard look calm.
5. **Pinning beats "newest on disk".** `ML_*_MODEL_VERSION` is consulted by the registry;
   a pin that is not installed makes the model report as unavailable instead of quietly
   serving a different version. That is the documented rollback lever.

## What is deliberately absent

* No system that trains on user data: dataset export requires recorded consent for the
  `model_training` purpose, and the export tools (`app/users/consent.py`) are the only
  supported path.
* No automatic promotion to production. Registration marks a version as available; moving
  it to `production` is an explicit admin action with an audit record.
* No fake model for capabilities that have no artefact (disease detection today): the API
  returns `model_unavailable` with instructions, and the mobile app shows that message.
