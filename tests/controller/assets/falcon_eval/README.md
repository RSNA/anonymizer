# FALCON evaluation dataset layout

Place labeled CT series under first-level folders named by ground truth, for example:

```text
falcon_eval_data/
  CT_HEAD_WITH_CONTRAST/
    <study_uid>/
      <series_uid>/*.dcm
  CT_HEAD_WITHOUT_CONTRAST/
    <study_uid>/
      <series_uid_A>/*.dcm
      <series_uid_B>/*.dcm
```

Run:

```bash
poetry run python -m anonymizer.controller.ai.falcon.eval_accuracy \
  --data-dir /path/to/falcon_eval_data
```

Results CSV defaults to `falcon_eval_results.csv` inside the data directory. Use `--output` to choose another path.

See `src/anonymizer/controller/falcon/docs/FALCON_Evaluation.md` for naming rules and metrics.
