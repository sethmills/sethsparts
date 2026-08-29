# Seth's Parts

Self-hosted workshop/home inventory tool (planned domain: sethsparts.com), originally imported from `TOR Inventory.xlsx`. Django + SQLite for now; Docker-ready for later deployment.

## Local dev

```
cd ~/tor-inventory
./venv/bin/python manage.py runserver 8800
```

Or via Claude's preview: `.claude/launch.json` has a `tor-inventory` entry on port 8800.

Admin: http://localhost:8800/admin/

## Re-running the import

The import is a one-time load, not a sync — re-running it against a DB that already has data will create duplicate `Container`s (unique on `number`, so it'll actually raise on the `get_or_create` for anything already present... in practice: wipe `db.sqlite3` and re-migrate before re-importing from a fresh spreadsheet export).

```
./venv/bin/python manage.py import_tor_inventory "/Users/seth/Downloads/TOR Inventory.xlsx"
```

## Status

Phase 1 (data model + import + admin) is done — see `/Users/seth/.claude/plans/luminous-enchanting-kernighan.md` for the full roadmap (barcode scanning, parts enrichment/docs, BOM & build history, reorder dashboard, full export).
