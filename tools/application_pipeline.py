#!/usr/bin/env python3
"""Bounded /apply stage reads, evidence validation, builds and archive plans."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import job_state
import verify_pdf

STAGES = {'input': 0, 'evaluate': 1, 'draft': 2, 'review': 3,
          'revise': 4, 'verify': 5, 'record': 6}
CONTRACT = '.claude/skills/job-application-assistant/references/apply-workflow.md'
PROFILE = '.claude/skills/job-application-assistant/01-candidate-profile.md'


class PipelineError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise PipelineError('path must stay inside the repository')
    return path


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.apply-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def stage_text(root, name):
    body = inside(root, CONTRACT).read_text(encoding='utf-8')
    number = STAGES[name]
    match = re.search(rf'^## Step {number}:.*?(?=^## Step [0-6]:|\Z)', body, re.M | re.S)
    if not match:
        raise PipelineError('stage missing from canonical workflow')
    return match.group().strip()


def template_text(root, engine):
    body = inside(root, '.claude/skills/job-application-assistant/05-cv-templates.md').read_text(encoding='utf-8')
    if engine != 'reportlab':
        return body
    initial = body.split('## Template:')[0]
    tailoring = body.split('## Section-by-Section Tailoring', 1)[1].split('### LaTeX Special Characters', 1)[0]
    page_rules = body.split('## Page Budget', 1)[1]
    return initial + '\n## Section-by-Section Tailoring' + tailoring + '\n## Page Budget' + page_rules


def unique_ids(rows, label):
    if not isinstance(rows, list):
        raise PipelineError(f'{label} must be a list')
    ids = [r.get('id') for r in rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise PipelineError(f'{label} needs unique nonempty IDs')
    return set(ids)


def validate_state(root, state):
    if state.get('schema') != 'application_state_v1':
        raise PipelineError('unsupported state schema')
    for key in ['run_id', 'job', 'profile_sha256', 'evidence', 'requirements', 'claims',
                'evaluation', 'unresolved_flags', 'artifacts', 'authorization']:
        if key not in state:
            raise PipelineError(f'missing state field: {key}')
    if not isinstance(state['unresolved_flags'], list):
        raise PipelineError('unresolved_flags must be a list')
    if state['authorization'] not in ['evaluate-only', 'prepare']:
        raise PipelineError('state must not imply submission authorization')
    job = state['job']
    for key in ['company', 'role', 'snapshot_path', 'snapshot_sha256', 'snapshot_fetched_at']:
        if not job.get(key):
            raise PipelineError(f'missing job field: {key}')
    snapshot = inside(root, job['snapshot_path'])
    if sha(snapshot) != job['snapshot_sha256']:
        raise PipelineError('posting snapshot changed')
    fetched = datetime.fromisoformat(job['snapshot_fetched_at'].replace('Z', '+00:00'))
    if fetched.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - fetched).total_seconds() <= 86400:
        raise PipelineError('snapshot must be timezone-aware and at most 24 hours old')
    if job.get('input_kind') != 'pasted':
        availability = job.get('availability', {})
        if not job.get('authoritative_url') or availability.get('status') != 'open' or availability.get('url') != job['authoritative_url']:
            raise PipelineError('same-URL live-open proof required')
        checked = datetime.fromisoformat(availability.get('checked_at', '').replace('Z', '+00:00'))
        if checked.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 7200:
            raise PipelineError('refresh the live-open proof; it is older than two hours')
    profile = inside(root, PROFILE)
    if sha(profile) != state['profile_sha256']:
        raise PipelineError('canonical profile changed; revalidate selected evidence')
    profile_text = profile.read_text(encoding='utf-8')
    evidence_ids = unique_ids(state['evidence'], 'evidence')
    for evidence in state['evidence']:
        if not evidence.get('section') or not evidence.get('excerpt') or evidence['excerpt'] not in profile_text:
            raise PipelineError('candidate evidence must quote the current canonical profile')
    unique_ids(state['requirements'], 'requirements')
    posting_text = snapshot.read_text(encoding='utf-8')
    for requirement in state['requirements']:
        if requirement.get('priority') not in ['required', 'preferred', 'logistics']:
            raise PipelineError('invalid requirement priority')
        if not requirement.get('text') or requirement.get('coverage') not in ['supported', 'adjacent', 'gap']:
            raise PipelineError('requirement needs text and explicit coverage')
        if requirement['text'] not in posting_text:
            raise PipelineError('requirements must quote the verified posting')
        if not isinstance(requirement.get('terms', []), list) or any(not isinstance(t, str) or not t.strip() for t in requirement.get('terms', [])):
            raise PipelineError('keyword terms must be nonempty strings')
        refs = requirement.get('evidence_ids', [])
        if not set(refs) <= evidence_ids or (requirement['coverage'] != 'gap' and not refs):
            raise PipelineError('supported requirements need canonical evidence IDs')
    unique_ids(state['claims'], 'claims')
    for claim in state['claims']:
        refs = claim.get('evidence_ids', [])
        if not claim.get('text') or not refs or not set(refs) <= evidence_ids:
            raise PipelineError('each candidate claim needs evidence IDs')
    evaluation = state['evaluation']
    if evaluation.get('confidence') not in ['HIGH', 'MEDIUM', 'LOW'] or not evaluation.get('rationale') or not isinstance(evaluation.get('components'), dict):
        raise PipelineError('evaluation needs confidence, rationale and component scores')
    if not isinstance(evaluation.get('score'), (float, int)) or not 0 <= evaluation['score'] <= 100:
        raise PipelineError('score must be 0-100')
    for gate in ['eligibility', 'target_scope', 'location', 'language']:
        if evaluation.get('gates', {}).get(gate) not in ['PASS', 'FLAG', 'FAIL']:
            raise PipelineError(f'missing/invalid gate: {gate}')
    if not evaluation.get('rubric_sha256') or sha(inside(root, '.claude/skills/job-application-assistant/04-job-evaluation.md')) != evaluation['rubric_sha256']:
        raise PipelineError('evaluation rubric changed')
    unique_ids(state['artifacts'], 'artifacts')
    artifact_paths = []
    for artifact in state['artifacts']:
        if artifact['id'] not in ['cv', 'cover']:
            raise PipelineError('only CV and optional cover artifacts belong to this build state')
        for field in ['source', 'pdf', 'contract', 'receipt']:
            artifact_paths.append(inside(root, artifact[field]))
        for field in ['contract', 'receipt']:
            if not inside(root, artifact[field]).is_relative_to(inside(root, 'tmp')):
                raise PipelineError('contracts and receipts must stay in private tmp storage')
        folder = 'cv' if artifact['id'] == 'cv' else 'cover_letters'
        for field in ['source', 'pdf']:
            if not inside(root, artifact[field]).is_relative_to(inside(root, folder)):
                raise PipelineError('role artifacts must stay in their role-output directory')
            if inside(root, artifact[field]).stem in ['main_example', 'cover_example', 'build_default_resume']:
                raise PipelineError('never compile over a baseline/example artifact')
    if len(set(artifact_paths)) != len(artifact_paths):
        raise PipelineError('artifact source/output/contract/receipt paths must be distinct')
    if not isinstance(state.get('cover_required'), bool):
        raise PipelineError('cover_required must be a boolean')
    return {'valid': True, 'run_id': state['run_id'], 'evidence_count': len(evidence_ids),
            'requirements': len(state['requirements']), 'claims': len(state['claims']),
            'state_sha256': digest(state), 'semantic_review_required': True}


def preparation_allowed(state):
    if state['authorization'] != 'prepare':
        raise PipelineError('evaluate-only must remain read-only')
    if 'FAIL' in state['evaluation']['gates'].values():
        raise PipelineError('hard gate failure prevents preparation')
    if (state['unresolved_flags'] or 'FLAG' in state['evaluation']['gates'].values()
            or state['evaluation']['score'] < 60) and not state.get('user_decision'):
        raise PipelineError('material flags/low score need the recorded user decision')


def state_fingerprint(state):
    return digest({k: state[k] for k in ['job', 'profile_sha256', 'requirements', 'claims',
                                       'evidence', 'evaluation', 'unresolved_flags']})


def resolve_template(root, source, engine, candidates, pages=1):
    source_path = inside(root, source)
    if not source_path.is_file() or pages < 1:
        raise PipelineError('template source and positive page limit are required')
    executable = None
    if engine == 'reportlab':
        for candidate in dict.fromkeys([*candidates, sys.executable]):
            try:
                result = subprocess.run([candidate, '-c', 'import reportlab; import sys; print(sys.executable)'],
                                        capture_output=True, text=True, timeout=15)
                if result.returncode == 0:
                    executable = result.stdout.strip()
                    break
            except (OSError, subprocess.TimeoutExpired):
                pass
        args = ['{source}', '--output', '{pdf}']
    else:
        executable = shutil.which(engine)
        args = (['compile', '{source}', '{pdf}'] if engine == 'typst' else
                ['-interaction=nonstopmode', '-halt-on-error', '-output-directory={pdf_dir}', '{source}'])
    if not executable:
        raise PipelineError(f'{engine} unavailable; resolve a verified runtime, not a guessed fallback')
    return {'schema': 'application_template_v1', 'engine': engine,
            'executable': executable, 'args': args, 'pages': pages,
            'source': source, 'renderer': shutil.which('pdftoppm'),
            'working_directory': str(source_path.parent.relative_to(Path(root).resolve()))}


def receipt_inputs(root, state, artifact):
    return {'source_sha256': sha(inside(root, artifact['source'])),
            'pdf_sha256': sha(inside(root, artifact['pdf'])),
            'contract_sha256': sha(inside(root, artifact['contract'])),
            'artifact_checks_sha256': digest(artifact),
            'evidence_sha256': state_fingerprint(state),
            'verifier_sha256': sha(Path(verify_pdf.__file__)),
            'pipeline_sha256': sha(Path(__file__))}


def receipt_valid(root, state, artifact, receipt):
    try:
        return receipt.get('schema') == 'application_verification_v1' and receipt['inputs'] == receipt_inputs(root, state, artifact)
    except (KeyError, OSError):
        return False


def build_check(root, state, artifact_id, force=False):
    validate_state(root, state)
    preparation_allowed(state)
    artifact = next((a for a in state['artifacts'] if a['id'] == artifact_id), None)
    if not artifact or (artifact_id == 'cover' and not state['cover_required']):
        raise PipelineError('artifact was not requested')
    receipt_path = inside(root, artifact['receipt'])
    if receipt_path.exists() and not force:
        old = read_json(receipt_path)
        if receipt_valid(root, state, artifact, old):
            return {'cache_hit': True, 'receipt': artifact['receipt'], 'mechanical_pass': old['mechanical_pass'],
                    'checks': old['owner_checks'], 'images': old['images']}
    contract = read_json(inside(root, artifact['contract']))
    if contract.get('schema') != 'application_template_v1' or contract.get('source') != artifact['source']:
        raise PipelineError('template contract belongs to a different source')
    source, pdf = inside(root, artifact['source']), inside(root, artifact['pdf'])
    if source == pdf or pdf.suffix.lower() != '.pdf':
        raise PipelineError('source and PDF must be distinct')
    if contract['engine'] in ['lualatex', 'xelatex'] and pdf.stem != source.stem:
        raise PipelineError('LaTeX output must share its source stem')
    pdf.parent.mkdir(parents=True, exist_ok=True)
    values = {'source': str(source), 'pdf': str(pdf), 'pdf_dir': str(pdf.parent)}
    argv = [contract['executable'], *[a.format(**values) for a in contract['args']]]
    log_path = receipt_path.with_suffix('.build.log')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # A failed build must never be mistaken for a previously successful PDF.
    if pdf.exists():
        pdf.unlink()
    with log_path.open('w', encoding='utf-8') as log:
        try:
            result = subprocess.run(argv, cwd=inside(root, contract['working_directory']),
                                    stdout=log, stderr=subprocess.STDOUT, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PipelineError(f'build failed; log: {log_path}; {exc}') from exc
    if result.returncode or not pdf.exists():
        detail = log_path.read_text(encoding='utf-8', errors='replace')[-1600:]
        raise PipelineError(f'build failed; log: {log_path}; {detail}')
    text_path = receipt_path.with_suffix('.txt')
    extractor, text, pages = verify_pdf.verify_pdf(pdf, contract['pages'], dump_text=text_path)
    required_text = artifact.get('required_text', [])
    anomalies = verify_pdf.text_checks(text, required_text)
    keywords = verify_pdf.keyword_matches(text, state['requirements']) if artifact_id == 'cv' else []
    images = []
    renderer = contract.get('renderer')
    if renderer:
        prefix = receipt_path.with_suffix('')
        try:
            rendered = subprocess.run([renderer, '-png', '-r', '120', str(pdf), str(prefix)],
                                      capture_output=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PipelineError(f'rendering failed: {exc}') from exc
        if rendered.returncode:
            raise PipelineError('rendering failed; inspect PDF with a supported visual tool')
        images = [str(p.relative_to(Path(root).resolve())) for p in sorted(prefix.parent.glob(prefix.name + '-*.png'))]
    receipt = {'schema': 'application_verification_v1', 'inputs': receipt_inputs(root, state, artifact),
               'extractor': extractor, 'pages': pages, 'text_path': str(text_path.relative_to(Path(root).resolve())),
               'anomalies': anomalies, 'keywords': keywords, 'images': images,
               'mechanical_pass': not anomalies, 'owner_checks': {}, 'compile_argv': argv}
    save_json(receipt_path, receipt)
    return {'cache_hit': False, 'receipt': artifact['receipt'], 'pages': pages, 'extractor': extractor,
            'mechanical_pass': not anomalies, 'anomalies': anomalies, 'keywords': keywords,
            'images': images, 'owner_checks_required': ['visual', 'factual', 'source'] + (['semantic_ats'] if artifact_id == 'cv' else [])}


def attest(root, state, artifact_id, checks, note):
    validate_state(root, state)
    preparation_allowed(state)
    artifact = next(a for a in state['artifacts'] if a['id'] == artifact_id)
    path = inside(root, artifact['receipt'])
    receipt = read_json(path)
    if not receipt_valid(root, state, artifact, receipt) or not receipt['mechanical_pass']:
        raise PipelineError('stale or failed verification; rebuild/review the current artifact')
    if not note.strip() or not set(checks) <= {'visual', 'factual', 'source', 'semantic_ats'}:
        raise PipelineError('owner checks require a concrete review note')
    for check in checks:
        receipt['owner_checks'][check] = {'passed': True, 'note': note, 'at': datetime.now(timezone.utc).isoformat()}
    save_json(path, receipt)
    return {'receipt': artifact['receipt'], 'recorded_owner_checks': checks,
            'note': 'Records the owner review; does not perform visual or semantic review.'}


def archive(root, state, tracker_path, write=False, expected_plan=None):
    validate_state(root, state)
    preparation_allowed(state)
    expected = {'cv', 'cover'} if state['cover_required'] else {'cv'}
    if {a['id'] for a in state['artifacts']} != expected:
        raise PipelineError('missing requested artifact or unexpected cover')
    review = state.get('review', {})
    if review.get('mode') not in ['SELF_REVIEW', 'INDEPENDENT'] or not review.get('model') or not review.get('effort'):
        raise PipelineError('actual review provenance required')
    prepared = {}
    for a in state['artifacts']:
        receipt = read_json(inside(root, a['receipt']))
        if not receipt_valid(root, state, a, receipt) or not receipt['mechanical_pass']:
            raise PipelineError('artifact verification is stale or failed')
        required_checks = ['visual', 'factual', 'source'] + (['semantic_ats'] if a['id'] == 'cv' else [])
        if not all(receipt.get('owner_checks', {}).get(c, {}).get('passed') is True
                   for c in required_checks):
            raise PipelineError('owner visual/factual/source/semantic checks are incomplete')
        prepared[a['id']] = {'path': a['pdf'], 'sha256': sha(inside(root, a['pdf'])),
                             'source': a['source'], 'source_sha256': sha(inside(root, a['source']))}
    tracker = job_state.load_tracker(inside(root, tracker_path))
    matches = [r for r in tracker.rows if r.get('application_id') == state.get('application_id')]
    if len(matches) != 1:
        raise PipelineError('application identity missing or ambiguous in tracker')
    row = matches[0]
    if (row['company'].casefold() != state['job']['company'].casefold()
            or row['role'].casefold() != state['job']['role'].casefold() or row['status'] != 'drafted'):
        raise PipelineError('tracker identity/status does not match this draft')
    if float(row['fit_rating']) != state['evaluation']['score']:
        raise PipelineError('tracker score differs from the final evaluation')
    for kind, column in [('cv', 'cv_file'), ('cover', 'cover_letter_file')]:
        if kind in prepared and inside(root, row[column]) != inside(root, prepared[kind]['path']):
            raise PipelineError('tracker artifact path differs from verified artifact')
    target = inside(root, row['archive_path'])
    allowed = inside(root, 'documents/applications')
    if not target.is_relative_to(allowed) or target == allowed:
        raise PipelineError('invalid archive directory')
    posting = target / 'job_posting.md'
    manifest_path = target / 'application_manifest.json'
    if posting.exists() and sha(posting) != state['job']['snapshot_sha256']:
        raise PipelineError('existing archive posting has a different hash')
    old = read_json(manifest_path) if manifest_path.exists() else {}
    if old and (old.get('application_id') != state['application_id'] or old.get('submitted_artifacts')):
        raise PipelineError('archive identity or submitted history must be reconciled')
    manifest = {**old, 'application_id': state['application_id'], 'requisition_id': state['job'].get('requisition_id', ''),
                'authoritative_url': state['job'].get('authoritative_url', ''),
                'discovery_url': state['job'].get('discovery_url', ''),
                'posting_sha256': state['job']['snapshot_sha256'],
                'apply_score': state['evaluation']['score'], 'evaluation': state['evaluation'],
                'rank_score': state['job'].get('rank_score'), 'unresolved_flags': state['unresolved_flags'],
                'review': review, 'prepared_artifacts': prepared, 'submitted_artifacts': {}}
    plan = {'application_id': state['application_id'], 'archive_path': row['archive_path'],
            'posting_sha256': state['job']['snapshot_sha256'], 'manifest_sha256': digest(manifest),
            'posting_action': 'preserve' if posting.exists() else 'copy', 'written': write}
    plan['plan_sha256'] = digest({k: v for k, v in plan.items() if k != 'written'})
    if write:
        if expected_plan != plan['plan_sha256']:
            raise PipelineError('archive plan changed or was not reviewed; repeat dry run')
        target.mkdir(parents=True, exist_ok=True)
        if not posting.exists():
            data = inside(root, state['job']['snapshot_path']).read_bytes()
            # Exclusive creation preserves a concurrent archive instead of overwriting it.
            with posting.open('xb') as f:
                f.write(data)
        if sha(posting) != state['job']['snapshot_sha256']:
            raise PipelineError('archived snapshot hash mismatch')
        save_json(manifest_path, manifest)
        if read_json(manifest_path) != manifest:
            raise PipelineError('manifest verification failed')
    return plan


def company_cache(path, now=None, expected_company=None):
    if not Path(path).exists():
        return {'hit': False, 'reason': 'missing'}
    try:
        data = read_json(path)
        fetched = datetime.strptime(data['fetched_date'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        age = ((now or datetime.now(timezone.utc)) - fetched).total_seconds() / 86400
        if expected_company and data.get('company', '').casefold() != expected_company.casefold():
            return {'hit': False, 'reason': 'company_mismatch'}
        if not 0 <= age <= 30:
            return {'hit': False, 'reason': 'stale_or_future'}
        if not isinstance(data['sources'], dict):
            raise ValueError('invalid sources')
        return {'hit': True, 'company': data['company'], 'age_days': round(age, 2),
                'source_urls': {k: v.get('url') for k, v in data['sources'].items()},
                'notes_path': str(path), 'final_claim_verification_required': True}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {'hit': False, 'reason': 'invalid'}


def usage_summary(trace, turn, events_path=None, run_id=None):
    from scrape_pipeline import usage_report
    markers = []
    if events_path:
        with Path(events_path).open(encoding='utf-8') as f:
            markers = [json.loads(line) for line in f if line.strip()]
        markers = [m for m in markers if run_id is None or m['run_id'] == run_id]
    stages, efforts, compactions = {}, {}, set()
    current_effort = 'unknown'
    with Path(trace).open(encoding='utf-8') as f:
        for line in f:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            data = event.get('payload', {})
            if event.get('type') == 'turn_context':
                current_effort = data.get('effort', data.get('reasoning_effort', 'unknown'))
            if event.get('type') == 'compacted' and data.get('compaction_response_id'):
                compactions.add(data['compaction_response_id'])
            if event.get('type') == 'token_usage_record':
                rid = data.get('response_id')
                efforts[rid] = current_effort
                explicit = [m for m in markers if m.get('response_id') == rid]
                prior = [m for m in markers if m['at'] <= event.get('timestamp', '')]
                selected = explicit or sorted(prior, key=lambda m: m['at'])
                if selected:
                    stages[rid] = selected[-1]['stage']
    result = usage_report(trace, turn, stages)
    for call in result['calls']:
        call['effort'] = efforts.get(call['response_id'], 'unknown')
        call['compaction'] = call['response_id'] in compactions
    result['stage_attribution'] = 'Explicit response ID when available; otherwise preceding checkpoint timestamp (approximate).'
    result['billing'] = 'No subscription allowance or dollar conversion is inferred.'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('stage'); p.add_argument('name', choices=STAGES)
    p = sub.add_parser('template'); p.add_argument('--engine', choices=['reportlab', 'lualatex', 'xelatex', 'typst'], required=True)
    p = sub.add_parser('state-check'); p.add_argument('--state', required=True)
    p = sub.add_parser('checkpoint'); p.add_argument('--state', required=True); p.add_argument('--stage', choices=STAGES, required=True)
    p.add_argument('--events', required=True); p.add_argument('--model', default='unknown'); p.add_argument('--effort', default='unknown')
    p.add_argument('--response-id'); p.add_argument('--retry-reason'); p.add_argument('--cache-status')
    p = sub.add_parser('resolve-template'); p.add_argument('--source', required=True)
    p.add_argument('--engine', choices=['reportlab', 'lualatex', 'xelatex', 'typst'], required=True)
    p.add_argument('--python', action='append', default=[]); p.add_argument('--pages', type=int, default=1); p.add_argument('--output', required=True)
    p = sub.add_parser('build-check'); p.add_argument('--state', required=True); p.add_argument('--artifact', choices=['cv', 'cover'], required=True); p.add_argument('--force', action='store_true')
    p = sub.add_parser('attest'); p.add_argument('--state', required=True); p.add_argument('--artifact', choices=['cv', 'cover'], required=True)
    p.add_argument('--check', action='append', required=True); p.add_argument('--note', required=True)
    p = sub.add_parser('archive'); p.add_argument('--state', required=True); p.add_argument('--tracker', default='job_search_tracker.csv'); p.add_argument('--write', action='store_true'); p.add_argument('--expected-plan')
    p = sub.add_parser('company-cache'); p.add_argument('--path', required=True); p.add_argument('--company', required=True)
    p = sub.add_parser('usage-report'); p.add_argument('--trace', type=Path, required=True); p.add_argument('--turn', required=True)
    p.add_argument('--events', type=Path); p.add_argument('--run-id'); p.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'stage':
            print(stage_text(args.root, args.name)); return 0
        if args.command == 'template':
            print(template_text(args.root, args.engine)); return 0
        if args.command == 'usage-report':
            report = usage_summary(args.trace, args.turn, args.events, args.run_id)
            save_json(inside(args.root, args.output), report)
            result = {k: v for k, v in report.items() if k != 'calls'}
        elif args.command == 'company-cache':
            result = company_cache(inside(args.root, args.path), expected_company=args.company)
        elif args.command == 'resolve-template':
            result = resolve_template(args.root, args.source, args.engine, args.python, args.pages)
            save_json(inside(args.root, args.output), result)
        else:
            state = read_json(inside(args.root, args.state))
            if args.command == 'state-check':
                result = validate_state(args.root, state)
            elif args.command == 'build-check':
                result = build_check(args.root, state, args.artifact, args.force)
            elif args.command == 'attest':
                result = attest(args.root, state, args.artifact, args.check, args.note)
            elif args.command == 'archive':
                result = archive(args.root, state, args.tracker, args.write, args.expected_plan)
            elif args.command == 'checkpoint':
                validate_state(args.root, state); preparation_allowed(state)
                result = {'at': datetime.now(timezone.utc).isoformat(), 'run_id': state['run_id'],
                          'stage': args.stage, 'state_sha256': digest(state), 'model': args.model,
                          'effort': args.effort, 'response_id': args.response_id,
                          'retry_reason': args.retry_reason, 'cache_status': args.cache_status}
                path = inside(args.root, args.events); path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(result) + '\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PipelineError, verify_pdf.VerificationError, job_state.JobStateError, OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
