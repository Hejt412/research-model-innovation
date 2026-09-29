"""Synthetic byte artifacts only: no model, checkpoint loader or training."""
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
from run_records import capture


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_ledger(root, rows):
    root.mkdir(parents=True, exist_ok=True)
    rows = [{**r, 'run_id': r.get('run_id', str(r['experiment_id']) + '-seed-' + str(r['seed']))} for r in rows]
    groups = defaultdict(list)
    for row in rows:
        groups[row['run_id']].append(row)
    runs = []
    for i, (rid, values) in enumerate(groups.items()):
        directory = root / str(i)
        directory.mkdir(exist_ok=True)
        checkpoint, log = directory/'checkpoint.bin', directory/'training.txt'
        checkpoint.write_bytes(('Synthetic bytes; not model weights: ' + rid).encode())
        log.write_text('Synthetic completed run: ' + rid, encoding='utf-8')
        results, receipt_path = directory/'results.csv', directory/'evaluation.json'
        write_csv(results, values)
        run = {'run_id': rid, 'experiment_id': values[0]['experiment_id'], 'seed': int(values[0]['seed']),
               'manifest_sha256': values[0]['manifest_sha256']}
        receipt = {**run, 'kind': 'evaluation_receipt', 'schema_version': 1}
        for kind, path in (('checkpoint', checkpoint), ('training_log', log), ('results', results)):
            receipt[kind + '_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            run[kind + '_path'] = str(path.resolve())
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        run['evaluation_log_path'] = str(receipt_path.resolve())
        runs.append(run)
    spec = root/'spec.json'
    spec.write_text(json.dumps({'kind': 'run_spec', 'schema_version': 1, 'runs': runs}), encoding='utf-8')
    ledger = root/'ledger.json'
    ledger.write_text(json.dumps(capture(spec)), encoding='utf-8')
    return rows, ledger
