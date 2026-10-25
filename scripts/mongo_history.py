"""Optional Mongo maintenance. Preview migration by default; never drops SQL data."""
import argparse
import json
from src.storage.mongo import get_store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['install-schema', 'migrate', 'verify'])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    store = get_store()
    if args.operation == 'install-schema':
        if not args.apply:
            print('Preview: install validators and indexes for the designed collections. Pass --apply to execute.')
            return
        store.install_schema()
        print('Schema installed')
        return
    from app.backend.database import SessionLocal
    from src.storage.migration import migrate
    with SessionLocal() as session:
        counts = migrate(session, store=store, apply=args.apply and args.operation == 'migrate')
        if args.operation == 'verify':
            def verify(db):
                return {'reports': db.reports.count_documents({'provenance': 'legacy_unverified'}),
                        'scan_runs': db.scan_runs.count_documents({'coverage_mode': 'legacy_topn_only'}),
                        'scan_results': db.scan_results.count_documents({'quality.legacy_topn_only': True})}
            actual = store.execute(verify, required=True)
            if any(actual[k] != counts[k] for k in actual):
                raise RuntimeError('Migration count mismatch')
            counts['verified'] = True
        print(json.dumps(counts))


if __name__ == '__main__':
    main()
