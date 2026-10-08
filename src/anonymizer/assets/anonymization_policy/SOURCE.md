# Anonymization policy assets

| File | Role |
| --- | --- |
| `clinical_text_keep_tags.txt` | Public tags flipped from `@remove`/`@empty` → keep for Clinical |
| `tcia_private_tag_kb.csv` | TCIA-style private tag dispositions (`k` keep, `d` remove, `h` `@uid`, `o`/`oi` date operand) |

Replace the sample CSV with the vendor TCIA private-tag knowledge base when available, then re-run:

```bash
uv run python src/anonymizer/assets/scripts/compile_clinical_script.py
```

Use `--check` in CI to ensure the committed `clinical-anonymizer.script` matches compiler output.
