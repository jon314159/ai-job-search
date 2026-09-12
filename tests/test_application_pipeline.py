import copy
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import application_pipeline as pipeline
import verify_pdf


class ApplicationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write(pipeline.PROFILE, '## Experience\nUsed Excel in a coursework reporting project.\n')
        self.write('.claude/skills/job-application-assistant/04-job-evaluation.md', 'rubric v1')
        self.write('postings/job.md', 'Requires Excel.\r\nFull time.\r\n')
        self.write('cv/main_test.py', 'source v1')
        self.write('cv/main_test.pdf', 'pdf v1')
        self.write('tmp/cv-contract.json', json.dumps({'schema': 'application_template_v1', 'engine': 'reportlab',
                   'executable': sys.executable, 'args': ['{source}', '--output', '{pdf}'], 'source': 'cv/main_test.py',
                   'working_directory': 'cv', 'pages': 1, 'renderer': None}))
        now = datetime.now(timezone.utc).isoformat()
        self.state = {'schema': 'application_state_v1', 'run_id': 'fixture', 'authorization': 'prepare',
            'cover_required': False, 'application_id': 'test_123',
            'job': {'company': 'Test', 'role': 'Analyst', 'snapshot_path': 'postings/job.md',
                    'snapshot_sha256': pipeline.sha(self.root/'postings/job.md'), 'snapshot_fetched_at': now,
                    'authoritative_url': 'https://example.test/123',
                    'availability': {'status': 'open', 'url': 'https://example.test/123', 'checked_at': now}},
            'profile_sha256': pipeline.sha(self.root/pipeline.PROFILE),
            'evidence': [{'id': 'e1', 'section': 'Experience', 'excerpt': 'Used Excel in a coursework reporting project.'}],
            'requirements': [{'id': 'r1', 'text': 'Requires Excel.', 'priority': 'required', 'terms': ['Excel'],
                              'coverage': 'supported', 'evidence_ids': ['e1']}],
            'claims': [{'id': 'c1', 'text': 'Excel coursework reporting project', 'evidence_ids': ['e1']}],
            'evaluation': {'score': 75, 'confidence': 'HIGH', 'rationale': 'Fixture fit', 'components': {'technical': 75}, 'rubric_sha256': pipeline.sha(self.root/'.claude/skills/job-application-assistant/04-job-evaluation.md'),
                           'gates': {g: 'PASS' for g in ['eligibility', 'target_scope', 'location', 'language']}},
            'unresolved_flags': [], 'review': {'mode': 'SELF_REVIEW', 'model': 'fixture-model', 'effort': 'high'},
            'artifacts': [{'id': 'cv', 'source': 'cv/main_test.py', 'pdf': 'cv/main_test.pdf',
                           'contract': 'tmp/cv-contract.json', 'receipt': 'tmp/cv-receipt.json', 'required_text': ['candidate@example.test']} ]}

    def write(self, path, text):
        target = self.root/path; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode('utf-8'))

    def make_receipt(self):
        artifact = self.state['artifacts'][0]
        receipt = {'schema': 'application_verification_v1', 'inputs': pipeline.receipt_inputs(self.root, self.state, artifact),
                   'mechanical_pass': True, 'owner_checks': {}, 'images': []}
        pipeline.save_json(self.root/artifact['receipt'], receipt)
        return receipt

    def tracker(self, status='drafted'):
        with (self.root/'tracker.csv').open('w', newline='', encoding='utf-8') as f:
            fields = ['date','company','sector','role','role_type','channel','status','contact_person','fit_rating','notes','cv_file','cover_letter_file','source','deadline','application_id','archive_path']
            writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
            writer.writerow({'date':'2026-09-08','company':'Test','role':'Analyst','status':status,'fit_rating':'75',
                             'cv_file':'cv/main_test.pdf','application_id':'test_123','archive_path':'documents/applications/test_123'})

    def verified(self):
        self.make_receipt()
        pipeline.attest(self.root, self.state, 'cv', ['visual','factual','source','semantic_ats'], 'Fixture review evidence')
        self.tracker()

    def test_state_roundtrip_preserves_evidence_requirements_and_flags(self):
        self.state['unresolved_flags'] = ['location unresolved']
        restored = json.loads(json.dumps(self.state))
        self.assertEqual(restored, self.state)
        self.assertTrue(pipeline.validate_state(self.root, restored)['valid'])
        with self.assertRaises(pipeline.PipelineError): pipeline.preparation_allowed(restored)

    def test_rejects_profile_snapshot_rubric_changes(self):
        for file in [pipeline.PROFILE, 'postings/job.md', '.claude/skills/job-application-assistant/04-job-evaluation.md']:
            path = self.root/file; original=path.read_bytes(); path.write_bytes(original+b'changed')
            with self.assertRaises(pipeline.PipelineError): pipeline.validate_state(self.root, self.state)
            path.write_bytes(original)

    def test_rejects_missing_claim_evidence_and_invented_requirement(self):
        for field,value in [('claims',[{'id':'c1','text':'Invented','evidence_ids':['missing']}]),
                            ('requirements',[{'id':'r1','text':'SQL required','priority':'required','coverage':'gap'}])]:
            state=copy.deepcopy(self.state);state[field]=value
            with self.assertRaises(pipeline.PipelineError):pipeline.validate_state(self.root,state)

    def test_stale_and_mismatched_live_proof(self):
        for value in ['https://wrong.test', None]:
            state=copy.deepcopy(self.state);state['job']['availability']['url']=value
            with self.assertRaises(pipeline.PipelineError):pipeline.validate_state(self.root,state)
        self.state['job']['availability']['checked_at']=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        with self.assertRaises(pipeline.PipelineError):pipeline.validate_state(self.root,self.state)

    def test_pasted_posting_needs_no_invented_url(self):
        self.state['job']['input_kind']='pasted';self.state['job'].pop('authoritative_url');self.state['job'].pop('availability')
        self.assertTrue(pipeline.validate_state(self.root,self.state)['valid'])

    def test_path_escape_and_baseline_protection(self):
        with self.assertRaises(pipeline.PipelineError):pipeline.inside(self.root,'../outside')
        self.state['artifacts'][0]['source']='documents/cv/baseline.py'
        with self.assertRaises(pipeline.PipelineError):pipeline.validate_state(self.root,self.state)

    def test_hard_fail_and_evaluate_only_cannot_write(self):
        self.state['evaluation']['gates']['eligibility']='FAIL';self.state['user_decision']='proceed'
        with self.assertRaises(pipeline.PipelineError):pipeline.build_check(self.root,self.state,'cv')
        self.state['evaluation']['gates']['eligibility']='PASS';self.state['authorization']='evaluate-only'
        with self.assertRaises(pipeline.PipelineError):pipeline.build_check(self.root,self.state,'cv')
        self.assertFalse((self.root/'tmp/cv-receipt.json').exists())

    def test_cache_hit_does_not_build_or_claim_visual_review(self):
        self.make_receipt()
        with patch.object(pipeline.subprocess,'run',side_effect=AssertionError('unexpected compile')):
            result=pipeline.build_check(self.root,self.state,'cv')
        self.assertTrue(result['cache_hit']);self.assertEqual(result['checks'],{})

    def test_receipt_invalidated_by_each_input(self):
        receipt=self.make_receipt();artifact=self.state['artifacts'][0]
        for key in ['source','pdf','contract']:
            path=self.root/artifact[key];data=path.read_bytes();path.write_bytes(data+b'changed')
            self.assertFalse(pipeline.receipt_valid(self.root,self.state,artifact,receipt));path.write_bytes(data)
        self.state['claims'][0]['text']='Different claim'
        self.assertFalse(pipeline.receipt_valid(self.root,self.state,artifact,receipt))

    def test_new_contact_or_date_expectation_invalidates_receipt(self):
        receipt=self.make_receipt();artifact=self.state['artifacts'][0]
        artifact['required_text'].append('2024-2026')
        self.assertFalse(pipeline.receipt_valid(self.root,self.state,artifact,receipt))

    def test_receipt_cannot_overwrite_source(self):
        self.state['artifacts'][0]['receipt']='cv/main_test.py'
        with self.assertRaises(pipeline.PipelineError):pipeline.validate_state(self.root,self.state)

    def test_archive_requires_real_owner_checks_and_dry_run(self):
        self.make_receipt();self.tracker()
        with self.assertRaises(pipeline.PipelineError):pipeline.archive(self.root,self.state,'tracker.csv')
        self.verified()
        with self.assertRaises(pipeline.PipelineError):pipeline.archive(self.root,self.state,'tracker.csv',True)
        self.assertFalse((self.root/'documents/applications/test_123').exists())

    def test_archive_copies_exact_bytes_preserves_tracker_and_reuses_identity(self):
        self.verified();tracker=(self.root/'tracker.csv').read_bytes()
        plan=pipeline.archive(self.root,self.state,'tracker.csv')
        pipeline.archive(self.root,self.state,'tracker.csv',True,plan['plan_sha256'])
        target=self.root/'documents/applications/test_123'
        self.assertEqual((target/'job_posting.md').read_bytes(),(self.root/'postings/job.md').read_bytes())
        self.assertEqual((self.root/'tracker.csv').read_bytes(),tracker)
        manifest=pipeline.read_json(target/'application_manifest.json')
        self.assertEqual(manifest['submitted_artifacts'],{})
        self.assertEqual(pipeline.archive(self.root,self.state,'tracker.csv')['posting_action'],'preserve')

    def test_archive_rejects_changed_plan_and_submitted_history(self):
        self.verified();plan=pipeline.archive(self.root,self.state,'tracker.csv')
        self.state['review']['effort']='medium'
        with self.assertRaises(pipeline.PipelineError):pipeline.archive(self.root,self.state,'tracker.csv',True,plan['plan_sha256'])
        self.tracker('applied')
        with self.assertRaises(pipeline.PipelineError):pipeline.archive(self.root,self.state,'tracker.csv')

    def test_existing_posting_conflict_is_not_overwritten(self):
        self.verified();self.write('documents/applications/test_123/job_posting.md','old posting')
        with self.assertRaises(pipeline.PipelineError):pipeline.archive(self.root,self.state,'tracker.csv')
        self.assertEqual((self.root/'documents/applications/test_123/job_posting.md').read_text(),'old posting')

    def test_optional_cover_not_built(self):
        with self.assertRaises(pipeline.PipelineError):pipeline.build_check(self.root,self.state,'cover')
        self.state['cover_required']=True;self.verified()
        with self.assertRaises(pipeline.PipelineError):pipeline.archive(self.root,self.state,'tracker.csv')

    def test_requested_cover_does_not_require_cv_only_ats_attestation(self):
        self.state['cover_required']=True
        cover={'id':'cover','source':'cover_letters/cover_test.py','pdf':'cover_letters/cover_test.pdf',
               'contract':'tmp/cover-contract.json','receipt':'tmp/cover-receipt.json'}
        self.state['artifacts'].append(cover)
        self.write(cover['source'],'cover source');self.write(cover['pdf'],'cover pdf');self.write(cover['contract'],'{}')
        self.verified()
        with (self.root/'tracker.csv').open(newline='',encoding='utf-8') as f:
            reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
        rows[0]['cover_letter_file']=cover['pdf']
        with (self.root/'tracker.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        pipeline.save_json(self.root/cover['receipt'],{'schema':'application_verification_v1',
            'inputs':pipeline.receipt_inputs(self.root,self.state,cover),'mechanical_pass':True,'owner_checks':{},'images':[]})
        pipeline.attest(self.root,self.state,'cover',['visual','factual','source'],'Cover reviewed; ATS keyword screening is CV-only')
        self.assertFalse(pipeline.archive(self.root,self.state,'tracker.csv')['written'])

    def test_company_cache_ttl_identity_and_readonly(self):
        cache=self.root/'cache.json';now=datetime(2026,9,8,tzinfo=timezone.utc)
        pipeline.save_json(cache,{'company':'Test','fetched_date':'2026-09-01','sources':{'website':{'url':'https://example.test','notes':'long notes'}}})
        before=cache.read_bytes();result=pipeline.company_cache(cache,now,'Test')
        self.assertTrue(result['hit']);self.assertNotIn('long notes',str(result));self.assertEqual(before,cache.read_bytes())
        self.assertFalse(pipeline.company_cache(cache,now,'Wrong')['hit'])
        self.assertFalse(pipeline.company_cache(cache,now+timedelta(days=35),'Test')['hit'])

    def test_keyword_matching_respects_boundaries_and_keeps_gaps_for_owner(self):
        requirement={'id':'r1','priority':'required','terms':['SQL'],'coverage':'gap'}
        self.assertEqual(verify_pdf.keyword_matches('NoSQL',[requirement])[0]['status'],'needs_owner_review')
        self.assertEqual(verify_pdf.keyword_matches('SQL, Excel',[requirement])[0]['status'],'literal')
        self.assertTrue(verify_pdf.text_checks('broken (cid:123) text',['email']))

    def test_stage_dispatcher_preserves_all_required_steps_without_loading_them(self):
        root=Path(__file__).resolve().parent.parent
        command=(root/'.claude/commands/apply.md').read_text(encoding='utf-8')
        self.assertLess(len(command),6500)
        for name,number in pipeline.STAGES.items():
            body=pipeline.stage_text(root,name)
            self.assertTrue(body.startswith(f'## Step {number}:'))
            self.assertNotIn(f'## Step {number+1}:',body)
        self.assertIn('compile',pipeline.stage_text(root,'verify').lower())
        self.assertIn('Record a Verified Submission',pipeline.stage_text(root,'record'))

    def test_usage_dedup_includes_compaction_and_actual_effort(self):
        trace=self.root/'trace.jsonl'
        records=[{'type':'turn_context','payload':{'model':'actual','effort':'high'}},
                 {'type':'token_usage_record','timestamp':'2026-09-08T01:00:00Z','payload':{'turn_id':'turn','response_id':'r1','usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':10,'reasoning_output_tokens':4,'total_tokens':110}}}]
        records.append(records[-1]);records.append({'type':'compacted','payload':{'compaction_response_id':'r1'}})
        trace.write_text('\n'.join(map(json.dumps,records)),encoding='utf-8')
        result=pipeline.usage_summary(trace,'turn')
        self.assertEqual(result['response_count'],1);self.assertEqual(result['totals']['total_tokens'],110)
        self.assertEqual(result['calls'][0]['effort'],'high');self.assertTrue(result['calls'][0]['compaction'])

    def real_source(self, pages=1):
        self.write('cv/main_test.py', f'''import sys
from reportlab.pdfgen.canvas import Canvas
c=Canvas(sys.argv[sys.argv.index('--output')+1])
for i in range({pages}):
    c.drawString(50,750,'candidate@example.test - Excel coursework reporting project')
    c.showPage()
c.save()
''')
        contract=pipeline.resolve_template(self.root,'cv/main_test.py','reportlab',[sys.executable])
        contract['renderer']=None
        pipeline.save_json(self.root/'tmp/cv-contract.json',contract)

    def test_actual_pdf_cold_build_warm_reuse_and_source_invalidation(self):
        self.real_source()
        cold=pipeline.build_check(self.root,self.state,'cv')
        self.assertFalse(cold['cache_hit']);self.assertEqual(cold['pages'],1);self.assertTrue(cold['mechanical_pass'])
        self.assertEqual(cold['keywords'][0]['status'],'literal')
        self.assertTrue(pipeline.build_check(self.root,self.state,'cv')['cache_hit'])
        with (self.root/'cv/main_test.py').open('a') as f:f.write('\n# changed\n')
        self.assertFalse(pipeline.build_check(self.root,self.state,'cv')['cache_hit'])

    def test_actual_two_page_failure_does_not_reuse_old_receipt(self):
        self.real_source();pipeline.build_check(self.root,self.state,'cv')
        self.real_source(2)
        with self.assertRaises(verify_pdf.VerificationError):pipeline.build_check(self.root,self.state,'cv')
        artifact=self.state['artifacts'][0]
        self.assertFalse(pipeline.receipt_valid(self.root,self.state,artifact,pipeline.read_json(self.root/artifact['receipt'])))

    def test_actual_compile_failure_does_not_preserve_stale_pdf(self):
        self.real_source();pipeline.build_check(self.root,self.state,'cv')
        self.write('cv/main_test.py','raise RuntimeError("seeded failure")')
        with self.assertRaisesRegex(pipeline.PipelineError,'seeded failure'):
            pipeline.build_check(self.root,self.state,'cv')
        self.assertFalse((self.root/'cv/main_test.pdf').exists())


if __name__ == '__main__':
    unittest.main()
