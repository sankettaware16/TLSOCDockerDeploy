# elasticsearch/

Retention, index templates and the storage report for the TLSOC stack.

| File | Purpose |
|---|---|
| `setup_storage.py` | Creates/updates the ILM retention policies and index templates from `.env`. Idempotent. `--dry-run`, `--reassign`, `--no-existing`, `--confirm-shrink` |
| `retention_report.py` | Measures GB per day per source and says whether the configured retention fits the disk |
| `soc-index-template.json` | Field types for every field the TLSOC Engine can emit. A **bundled copy** of the engine's generated template, used when no engine is installed locally |

Full guide: [docs/retention-and-storage.md](../docs/retention-and-storage.md).

## Where the field types come from

`setup_storage.py` looks for the engine's template in this order and uses the
first it finds:

1. `--engine-template PATH`
2. `$ENGINE_DIR/elasticsearch/soc-index-template.json` (`ENGINE_DIR` defaults to
   `/etc/foss-soc-engine`, where the engine installs itself)
3. the bundled `soc-index-template.json` in this directory

So a host that runs the engine always gets exactly the field types of the rules
it runs. The bundled copy exists for stacks installed before the engine.

## Refreshing the bundled copy

The template is **generated** in the
[engine repository](https://github.com/sankettaware16/foss-soc-engine)
(`elasticsearch/generate_template.py`); do not edit this copy by hand. After the
engine's rules change, copy the regenerated file over it:

```bash
cp ../foss-soc-engine/elasticsearch/soc-index-template.json elasticsearch/
```

and run `./elasticsearch/setup_storage.py` so the component template is updated.
