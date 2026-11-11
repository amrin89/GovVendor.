"""Request/database checks. Run: python -m unittest discover -s tests -v"""
import sqlite3
import csv
import re
import tempfile
import unittest
from datetime import date
from unittest.mock import patch
from contextlib import contextmanager
from io import BytesIO, StringIO
from html import unescape
from pathlib import Path

from werkzeug.security import check_password_hash

from app import MAX_PDF_BYTES, REVIEW_CHECKS, create_app

SAMPLE = (Path(__file__).resolve().parents[1] / 'sample-documents' / 'sample-trade-licence.pdf').read_bytes()
PROFILE = (Path(__file__).resolve().parents[1] / 'sample-documents' / 'sample-company-profile.pdf').read_bytes()


class GovVendorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / 'test.db')
        self.config = {'TESTING': True, 'DATABASE': self.database, 'SECRET_KEY': 'test-only-key'}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.values = {'company_name': 'Demo Supplies LLC', 'category': 'Office supplies',
                       'trade_reference': 'DEMO-LIC-104', 'licence_expiry': '2027-12-31',
                       'contact_name': 'Demo Applicant', 'contact_email': 'supplier@example.com'}

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def post(self, path, data=None, client=None):
        client = client or self.client
        with client.session_transaction() as session:
            token = session.setdefault('csrf', 'test-csrf')
        return client.post(path, data={'csrf': token, **(data or {})})

    def register(self, email='applicant@example.com', client=None):
        return self.post('/register', {'name': 'Demo Applicant', 'email': email,
                                      'password': 'fictional-password-123'}, client)

    def draft(self):
        with self.db() as db:
            return db.execute('SELECT * FROM applications ORDER BY id DESC LIMIT 1').fetchone()

    def test_home_and_account_pages_render(self):
        for path in ['/', '/register', '/login', '/static/style.css']:
            with self.subTest(path=path), self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)

    def test_registration_hashes_password_and_ignores_forged_role(self):
        response = self.post('/register', {'name': 'Demo Applicant', 'email': 'USER@EXAMPLE.COM',
                                          'password': 'fictional-password-123', 'role': 'administrator'})
        self.assertEqual(response.status_code, 303)
        with self.db() as db:
            user = db.execute('SELECT * FROM users').fetchone()
            self.assertEqual(user['email'], 'user@example.com')
            self.assertEqual(user['role'], 'applicant')
            self.assertNotEqual(user['password_hash'], 'fictional-password-123')
            self.assertTrue(check_password_hash(user['password_hash'], 'fictional-password-123'))
        self.assertEqual(self.client.get('/dashboard').status_code, 200)

    def test_invalid_account_and_duplicate_email(self):
        self.assertEqual(self.post('/register', {'name': 'X', 'email': 'bad', 'password': 'short'}).status_code, 400)
        self.register()
        self.assertEqual(self.register().status_code, 409)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)

    def test_sign_in_and_sign_out(self):
        self.register()
        self.assertEqual(self.post('/logout').status_code, 303)
        self.assertEqual(self.client.get('/dashboard').status_code, 302)
        self.assertEqual(self.post('/login', {'email': 'applicant@example.com', 'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.post('/login', {'email': 'applicant@example.com', 'password': 'fictional-password-123'}).status_code, 303)

    def test_authentication_and_csrf_are_required(self):
        self.assertEqual(self.client.get('/applications/new').status_code, 302)
        self.register()
        self.assertEqual(self.client.post('/applications/new', data=self.values).status_code, 400)
        self.assertIsNone(self.draft())

    def test_draft_saved_with_reference_and_server_controlled_status(self):
        self.register()
        response = self.post('/applications/new', {**self.values, 'status': 'Approved'})
        self.assertEqual(response.status_code, 303)
        draft = self.draft()
        self.assertRegex(draft['reference'], r'^GV-[A-F0-9]{12}$')
        self.assertEqual(draft['status'], 'Draft')
        self.assertEqual(draft['company_name'], self.values['company_name'])
        self.assertEqual(self.client.get(response.location).status_code, 200)
        self.assertIn(draft['reference'].encode(), self.client.get('/dashboard').data)

    def test_errors_retain_values_and_do_not_save_invalid_records(self):
        self.register()
        for field, invalid in [('category', 'not-a-category'), ('licence_expiry', 'not-a-date'),
                               ('contact_email', 'invalid'), ('company_name', 'X')]:
            with self.subTest(field=field):
                response = self.post('/applications/new', {**self.values, field: invalid})
                self.assertEqual(response.status_code, 400)
                self.assertIn(b'aria-invalid="true"', response.data)
                self.assertIsNone(self.draft())

    def test_edit_preserves_reference_and_records_activity(self):
        self.register()
        self.post('/applications/new', self.values)
        reference = self.draft()['reference']
        self.assertEqual(self.client.get(f'/applications/{reference}/edit').status_code, 200)
        response = self.post(f'/applications/{reference}/edit', {**self.values, 'company_name': 'Updated Demo Company'})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.draft()['reference'], reference)
        self.assertEqual(self.draft()['company_name'], 'Updated Demo Company')
        self.client.get(response.location)
        self.client.get(response.location)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM applications').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_events').fetchone()[0], 2)

    def test_other_applicant_cannot_read_or_edit_records(self):
        self.register()
        self.post('/applications/new', self.values)
        reference = self.draft()['reference']
        other = self.app.test_client()
        self.register('other@example.com', other)
        self.assertNotIn(reference.encode(), other.get('/dashboard').data)
        self.assertEqual(other.get(f'/applications/{reference}').status_code, 404)
        self.assertEqual(other.get(f'/applications/{reference}/edit').status_code, 404)
        self.assertEqual(self.post(f'/applications/{reference}/edit', self.values, other).status_code, 404)

    def test_saved_data_survives_a_new_app_instance(self):
        self.register()
        self.post('/applications/new', self.values)
        reference = self.draft()['reference']
        app = create_app(self.config)
        client = app.test_client()
        self.post('/login', {'email': 'applicant@example.com', 'password': 'fictional-password-123'}, client)
        self.assertIn(reference.encode(), client.get('/dashboard').data)

    def test_user_text_is_escaped_and_sql_values_are_bound(self):
        self.register()
        text = "Demo ' <script>alert(1)</script> LLC"
        response = self.post('/applications/new', {**self.values, 'company_name': text})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.draft()['company_name'], text)
        page = self.client.get(response.location).data
        self.assertIn(b'&lt;script&gt;', page)
        self.assertNotIn(b'<script>alert(1)</script>', page)

    def test_expiry_warning_and_404_page(self):
        self.register()
        response = self.post('/applications/new', {**self.values, 'licence_expiry': '2000-01-01'})
        self.assertEqual(response.status_code, 303)
        self.assertIn(b'expiry is in the past', self.client.get(response.location).data)
        self.assertEqual(self.client.get('/missing-page').status_code, 404)

    def make_draft(self, **overrides):
        self.register()
        result = self.post('/applications/new', {**self.values, **overrides})
        self.assertEqual(result.status_code, 303)
        return result.location

    def attach(self, path, kind='licence', content=SAMPLE, filename='sample.pdf', client=None):
        return self.post(f'{path}/documents/{kind}', {'document': (BytesIO(content), filename)}, client)

    def test_uploaded_document_downloads_as_attachment_and_can_be_replaced(self):
        path = self.make_draft()
        self.assertEqual(self.attach(path, filename='../../sample.pdf').status_code, 303)
        self.assertIn(b'1 of 2 attached', self.client.get(path).data)
        download = self.client.get(path + '/documents/licence')
        self.assertEqual(download.data, SAMPLE)
        self.assertIn('attachment; filename=sample.pdf', download.headers['Content-Disposition'])
        self.assertEqual(self.attach(path, filename='replacement.pdf').status_code, 303)
        self.assertIn('replacement.pdf', self.client.get(path + '/documents/licence').headers['Content-Disposition'])
        self.assertIn(b'1 of 2 attached', self.client.get(path).data)

    def test_bad_and_large_uploads_are_not_saved(self):
        path = self.make_draft()
        self.assertEqual(self.attach(path, content=b'<html>not a PDF</html>').status_code, 303)
        self.assertEqual(self.attach(path, filename='sample.txt').status_code, 303)
        oversized = b'%PDF-' + b'x' * MAX_PDF_BYTES + b'%%EOF'
        self.assertEqual(self.attach(path, content=oversized).status_code, 303)
        self.assertIn(b'0 of 2 attached', self.client.get(path).data)
        self.assertEqual(self.client.get(path + '/documents/licence').status_code, 404)

    def test_submission_requires_both_pdfs_and_locks_draft(self):
        path = self.make_draft()
        self.attach(path)
        self.assertEqual(self.post(path + '/submit').status_code, 303)
        self.assertEqual(self.draft()['status'], 'Draft')
        self.attach(path, 'profile')
        self.assertEqual(self.post(path + '/submit').status_code, 303)
        self.assertEqual(self.draft()['status'], 'Submitted')
        detail = self.client.get(path).data
        self.assertIn(b'Application submitted for demo review', detail)
        self.assertIn(b'2 of 2 attached', detail)
        self.assertNotIn(b'Edit draft', detail)
        self.assertEqual(self.post(path + '/edit', self.values).status_code, 400)
        self.assertEqual(self.attach(path).status_code, 400)
        self.assertEqual(self.post(path + '/submit').status_code, 400)
        client = create_app(self.config).test_client()
        self.post('/login', {'email': 'applicant@example.com', 'password': 'fictional-password-123'}, client)
        self.assertIn(b'Submitted', client.get(path).data)
        self.assertEqual(client.get(path + '/documents/licence').data, SAMPLE)

    def test_expired_licence_blocks_submission_even_with_documents(self):
        path = self.make_draft(licence_expiry='2000-01-01')
        self.attach(path)
        self.attach(path, 'profile')
        self.assertEqual(self.post(path + '/submit').status_code, 303)
        self.assertEqual(self.draft()['status'], 'Draft')

    def test_document_access_and_submission_require_application_owner(self):
        path = self.make_draft()
        self.attach(path)
        other = self.app.test_client()
        self.register('other@example.com', other)
        self.assertEqual(other.get(path + '/documents/licence').status_code, 404)
        self.assertEqual(self.attach(path, client=other).status_code, 404)
        self.assertEqual(self.post(path + '/submit', client=other).status_code, 404)
        self.assertEqual(self.draft()['status'], 'Draft')

    def reviewer(self, email='reviewer@example.com'):
        password = 'reviewer-test-password'
        result = self.app.test_cli_runner().invoke(args=['create-reviewer', '--email', email],
                                                   input=f'{password}\n{password}\n')
        self.assertEqual(result.exit_code, 0, result.output)
        client = self.app.test_client()
        sign_in = self.post('/login', {'email': email, 'password': password}, client)
        self.assertEqual(sign_in.location, '/review')
        return client

    def review_revision(self, client, case):
        page = client.get(case)
        self.assertEqual(page.status_code, 200)
        match = re.search(rb'name="revision" value="(\d+)"', page.data)
        self.assertIsNotNone(match)
        return match[1].decode()

    def save_checklist(self, reviewer, case, checks=None):
        return self.post(case + '/checklist', {'revision': self.review_revision(reviewer, case),
                         'checks': list(REVIEW_CHECKS) if checks is None else checks}, reviewer)

    def test_review_corrections_resubmission_and_approval(self):
        path = self.make_draft()
        case = path.replace('/applications/', '/review/')
        self.attach(path, filename='sample-trade-licence.pdf')
        self.attach(path, 'profile', filename='sample-trade-licence.pdf')
        reviewer = self.reviewer()
        self.assertEqual(reviewer.get(case).status_code, 404)
        self.assertEqual(reviewer.get(case + '/documents/licence').status_code, 404)
        self.post(path + '/submit')
        self.assertIn(b'Demo Supplies LLC', reviewer.get('/review').data)
        self.assertEqual(reviewer.get(case + '/documents/licence').data, SAMPLE)
        self.assertEqual(self.client.get(case).status_code, 403)
        self.assertEqual(self.client.get(case + '/documents/licence').status_code, 403)
        self.assertEqual(reviewer.get('/applications/new').status_code, 403)
        revision = self.review_revision(reviewer, case)
        self.assertEqual(self.post(case, {'revision': revision, 'action': 'approve'}, reviewer).status_code, 400)
        self.assertEqual(self.post(case, {'revision': revision, 'action': 'start'}, reviewer).status_code, 303)
        self.assertEqual(self.draft()['status'], 'Under review')
        other_reviewer = self.reviewer('other-reviewer@example.com')
        self.assertNotIn(b'Demo Supplies LLC', other_reviewer.get('/review').data)
        self.assertEqual(other_reviewer.get(case).status_code, 404)
        self.assertEqual(other_reviewer.get(case + '/documents/licence').status_code, 404)
        self.assertEqual(self.post(case, {'revision': revision, 'action': 'approve'}, reviewer).status_code, 409)
        revision = self.review_revision(reviewer, case)
        self.assertEqual(reviewer.post(case, data={'revision': revision, 'action': 'approve'}).status_code, 400)
        self.assertEqual(self.post(case, {'revision': revision, 'action': 'approve'}, self.client).status_code, 403)
        self.post(case, {'revision': revision, 'action': 'request-changes'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Under review')
        note = 'Please replace the company profile <PDF>.'
        self.post(case, {'revision': revision, 'action': 'request-changes', 'note': note}, reviewer)
        self.assertEqual(self.draft()['status'], 'Changes requested')
        detail = self.client.get(path).data
        self.assertIn(b'Please replace the company profile &lt;PDF&gt;.', detail)
        self.assertIn(b'Replace PDF', detail)
        self.assertEqual(self.post(path + '/edit', {**self.values, 'contact_name': 'Corrected Name'}).status_code, 303)
        self.attach(path, 'profile', PROFILE, 'sample-company-profile.pdf')
        self.post(path + '/submit')
        self.assertEqual(self.draft()['status'], 'Submitted')
        self.assertTrue(path.endswith(self.draft()['reference']))
        self.assertIn(b'Corrected Name', reviewer.get(case).data)
        self.assertEqual(reviewer.get(case + '/documents/profile').data, PROFILE)
        self.assertEqual(other_reviewer.get(case).status_code, 404)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.save_checklist(reviewer, case)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Approved')
        self.assertEqual(self.attach(path).status_code, 400)
        self.assertIn(b'Application resubmitted for demo review', self.client.get(path).data)
        self.assertIn(b'Reviewer decision: Approved', self.client.get(path).data)

    def test_rejection_requires_reason_and_is_final(self):
        path = self.make_draft()
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        reviewer = self.reviewer()
        case = path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        revision = self.review_revision(reviewer, case)
        self.post(case, {'revision': revision, 'action': 'reject', 'note': ' '}, reviewer)
        self.assertEqual(self.draft()['status'], 'Under review')
        self.post(case, {'revision': revision, 'action': 'reject', 'note': 'The demo licence cannot be verified.'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Rejected')
        self.assertIn(b'The demo licence cannot be verified.', self.client.get(path).data)
        self.assertEqual(self.post(path + '/submit').status_code, 400)

    def test_reviewer_creation_cannot_promote_existing_applicant(self):
        self.register('reviewer@example.com')
        result = self.app.test_cli_runner().invoke(args=['create-reviewer'])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('already has an account', result.output)
        self.assertEqual(self.client.get('/review').status_code, 403)

    def test_dashboard_counts_and_combined_filters_are_owner_scoped(self):
        self.register()
        draft_path = self.post('/applications/new', self.values).location
        approved_path = self.post('/applications/new', {**self.values, 'company_name': 'Cedar Pixel Demo LLC'}).location
        with self.db() as db:
            db.execute("UPDATE applications SET status='Approved' WHERE reference=?", (approved_path.rsplit('/', 1)[1],))
        other = self.app.test_client()
        self.register('other@example.com', other)
        self.post('/applications/new', {**self.values, 'company_name': 'Hidden Other Company'}, other)
        page = self.client.get('/dashboard').data
        self.assertIn(b'data-total="all">2<', page)
        self.assertIn(b'data-total="Draft">1<', page)
        self.assertIn(b'data-total="Approved">1<', page)
        self.assertNotIn(b'Hidden Other Company', page)
        filtered = self.client.get('/dashboard', query_string={'q': 'cEdAr', 'status': 'Approved'}).data
        self.assertIn(b'Cedar Pixel Demo LLC', filtered)
        self.assertNotIn(b'Demo Supplies LLC', filtered)
        self.assertIn(b'data-total="all">2<', filtered)
        reference = draft_path.rsplit('/', 1)[1]
        searched = self.client.get('/dashboard', query_string={'q': reference.lower()}).data
        self.assertIn(reference.encode(), searched)
        self.assertNotIn(b'Cedar Pixel Demo LLC', searched)
        self.assertIn(b'No matching applications', self.client.get('/dashboard?q=Hidden').data)

    def test_search_characters_are_literal_and_invalid_filters_fail(self):
        self.register()
        self.post('/applications/new', {**self.values, 'company_name': 'Demo 50%_ Supplies'})
        self.post('/applications/new', {**self.values, 'company_name': 'Demo 500 Supplies'})
        filtered = self.client.get('/dashboard', query_string={'q': '%_'}).data
        self.assertIn(b'Demo 50%_ Supplies', filtered)
        self.assertNotIn(b'Demo 500 Supplies', filtered)
        for query in ["' OR 1=1 --", '<script>alert(1)</script>']:
            page = self.client.get('/dashboard', query_string={'q': query}).data
            self.assertIn(b'No matching applications', page)
            self.assertNotIn(b'<script>alert(1)</script>', page)
        self.assertEqual(self.client.get('/dashboard?status=Unknown').status_code, 400)
        self.assertEqual(self.client.get('/dashboard', query_string={'q': 'x' * 121}).status_code, 400)

    def test_review_filters_and_totals_exclude_other_assigned_cases_and_private_drafts(self):
        path = self.make_draft()
        case = path.replace('/applications/', '/review/')
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        # This private draft must not contribute to any reviewer totals.
        self.post('/applications/new', {**self.values, 'company_name': 'Private Draft Company'})
        reviewer = self.reviewer()
        other_reviewer = self.reviewer('second-reviewer@example.com')
        self.assertIn(b'data-total="all">1<', reviewer.get('/review').data)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        own = reviewer.get('/review', query_string={'status': 'Under review', 'q': 'demo supplies'}).data
        self.assertIn(b'Demo Supplies LLC', own)
        self.assertIn(b'data-total="Under review">1<', own)
        self.assertNotIn(b'Private Draft Company', own)
        self.assertIn(b'No matching applications', reviewer.get('/review?status=Approved').data)
        other = other_reviewer.get('/review', query_string={'q': path.rsplit('/', 1)[1]}).data
        self.assertIn(b'data-total="all">0<', other)
        self.assertNotIn(b'Demo Supplies LLC', other)
        self.assertEqual(reviewer.get('/review?status=Draft').status_code, 400)

    def test_summary_is_only_for_approved_owner_and_assigned_reviewer(self):
        path = self.make_draft()
        summary = path + '/summary'
        self.assertEqual(self.client.get(summary).status_code, 400)
        self.assertNotIn(b'Open demo approval summary', self.client.get(path).data)
        self.attach(path, filename='sample-trade-licence.pdf')
        self.attach(path, 'profile', PROFILE, 'sample-company-profile.pdf')
        self.post(path + '/submit')
        reviewer = self.reviewer()
        case = path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.save_checklist(reviewer, case)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve',
                         'note': 'Reviewed <sample> files.'}, reviewer)
        for client, url in [(self.client, summary), (reviewer, case + '/summary')]:
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            for content in [b'Demo approval summary', b'Demo Supplies LLC',
                            b'sample-company-profile.pdf', b'Not a government registration',
                            b'Reviewed &lt;sample&gt; files.', b'Ctrl + P']:
                self.assertIn(content, response.data)
        self.assertIn(b'Open demo approval summary', self.client.get(path).data)
        outsider = self.app.test_client()
        self.register('other@example.com', outsider)
        self.assertEqual(outsider.get(summary).status_code, 404)
        self.assertEqual(outsider.get(case + '/summary').status_code, 403)
        another_reviewer = self.reviewer('second@example.com')
        self.assertEqual(another_reviewer.get(case + '/summary').status_code, 404)
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get(summary).status_code, 302)

    def approved_case(self):
        path = self.make_draft()
        self.attach(path, filename='sample-trade-licence.pdf')
        self.attach(path, 'profile', PROFILE, 'sample-company-profile.pdf')
        self.post(path + '/submit')
        reviewer = self.reviewer()
        case = path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.save_checklist(reviewer, case)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Approved')
        return path, reviewer

    def test_renewal_copies_fields_preserves_original_and_prevents_duplicate_drafts(self):
        path, _ = self.approved_case()
        previous = dict(self.draft())
        with self.db() as db:
            events = db.execute('SELECT * FROM application_events WHERE application_id=?', (previous['id'],)).fetchall()
        response = self.post(path + '/renew')
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith('/edit'))
        renewal = self.draft()
        self.assertNotEqual(previous['reference'], renewal['reference'])
        self.assertEqual(renewal['status'], 'Draft')
        for field in self.values:
            self.assertEqual(renewal[field], previous[field])
        self.assertIn(previous['reference'].encode(), self.client.get(response.location).data)
        renewal_path = response.location.removesuffix('/edit')
        self.assertIn(b'0 of 2 attached', self.client.get(renewal_path).data)
        again = self.post(path + '/renew')
        self.assertEqual(again.location, renewal_path)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_renewals').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM applications').fetchone()[0], 2)
            self.assertEqual(dict(db.execute('SELECT * FROM applications WHERE id=?', (previous['id'],)).fetchone()), previous)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_events WHERE application_id=?', (previous['id'],)).fetchone()[0], len(events))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_documents WHERE application_id=?', (previous['id'],)).fetchone()[0], 2)
        self.assertIn(b'Open existing renewal', self.client.get(path).data)
        self.assertIn(b'Renewal of', self.client.get('/dashboard').data)

    def test_renewal_start_requires_owner_role_approval_and_csrf(self):
        path = self.make_draft()
        self.assertEqual(self.post(path + '/renew').status_code, 400)
        with self.db() as db:
            db.execute("UPDATE applications SET status='Approved'")
        self.assertEqual(self.client.post(path + '/renew').status_code, 400)
        other = self.app.test_client()
        self.register('someone@example.com', other)
        self.assertEqual(self.post(path + '/renew', client=other).status_code, 404)
        reviewer = self.reviewer()
        self.assertEqual(self.post(path + '/renew', client=reviewer).status_code, 403)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_renewals').fetchone()[0], 0)

    def test_renewal_requires_later_expiry_and_both_documents_and_can_be_reviewed(self):
        path, reviewer = self.approved_case()
        renewal_edit = self.post(path + '/renew').location
        renewal_path = renewal_edit.removesuffix('/edit')
        self.assertEqual(self.post(renewal_edit, self.values).status_code, 400)
        self.attach(renewal_path, filename='sample-trade-licence.pdf')
        self.attach(renewal_path, 'profile', PROFILE, 'sample-company-profile.pdf')
        self.post(renewal_path + '/submit')
        self.assertEqual(self.draft()['status'], 'Draft')
        self.assertIn(b'later than', self.client.get(renewal_path).data)
        corrected = {**self.values, 'licence_expiry': '2028-12-31'}
        self.assertEqual(self.post(renewal_edit, corrected).status_code, 303)
        self.assertEqual(self.post(renewal_path + '/submit').status_code, 303)
        self.assertEqual(self.draft()['status'], 'Submitted')
        case = renewal_path.replace('/applications/', '/review/')
        self.assertIn(b'Renewal of', reviewer.get('/review').data)
        self.assertIn(b'2027-12-31', reviewer.get(case).data)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'request-changes',
                         'note': 'Update the demo contact name.'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Changes requested')
        self.assertEqual(self.post(renewal_edit, {**corrected, 'contact_name': 'Renewal Contact'}).status_code, 303)
        self.post(renewal_path + '/submit')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.save_checklist(reviewer, case)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Approved')
        self.assertIn(b'Open approved renewal', self.client.get(path).data)
        summary = self.client.get(renewal_path + '/summary').data
        self.assertIn(path.rsplit('/', 1)[1].encode(), summary)
        self.assertIn(b'2028-12-31', summary)
        self.assertIn(b'2027-12-31', self.client.get(path + '/summary').data)

    def test_renewal_missing_documents_and_rejection_retry(self):
        path, reviewer = self.approved_case()
        renewal_edit = self.post(path + '/renew').location
        renewal_path = renewal_edit.removesuffix('/edit')
        self.post(renewal_edit, {**self.values, 'licence_expiry': '2028-12-31'})
        self.post(renewal_path + '/submit')
        self.assertEqual(self.draft()['status'], 'Draft')
        self.attach(renewal_path)
        self.post(renewal_path + '/submit')
        self.assertEqual(self.draft()['status'], 'Draft')
        self.attach(renewal_path, 'profile', PROFILE)
        self.post(renewal_path + '/submit')
        case = renewal_path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'reject',
                         'note': 'Demo information is incomplete.'}, reviewer)
        retry = self.post(path + '/renew')
        self.assertEqual(retry.status_code, 303)
        self.assertNotEqual(retry.location, renewal_edit)
        self.assertEqual(self.draft()['status'], 'Draft')
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_renewals').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT status FROM applications WHERE reference=?',
                                       (renewal_path.rsplit('/', 1)[1],)).fetchone()[0], 'Rejected')

    def test_expiry_reminders_boundaries_privacy_and_latest_approved_version(self):
        path, _ = self.approved_case()
        for today, text in [(date(2027, 12, 1), b'Expires in 30 day(s)'),
                            (date(2027, 12, 31), b'Expires today'),
                            (date(2028, 1, 1), b'Expired 1 day(s) ago')]:
            with self.subTest(today=today), patch('app.local_today', return_value=today):
                self.assertIn(text, self.client.get('/dashboard').data)
        with patch('app.local_today', return_value=date(2027, 11, 30)):
            self.assertNotIn(b'Sample licence reminders', self.client.get('/dashboard').data)
        outsider = self.app.test_client()
        self.register('outsider@example.com', outsider)
        with patch('app.local_today', return_value=date(2028, 1, 1)):
            self.assertNotIn(b'Sample licence reminders', outsider.get('/dashboard').data)
            renewed = self.post(path + '/renew').location.removesuffix('/edit')
            self.assertIn(b'Renewal status: Draft', self.client.get('/dashboard').data)
            with self.db() as db:
                db.execute("UPDATE applications SET status='Approved',licence_expiry='2028-12-31' WHERE reference=?",
                           (renewed.rsplit('/', 1)[1],))
            self.assertNotIn(b'Sample licence reminders', self.client.get('/dashboard').data)
            self.assertEqual(self.client.get(path + '/summary').status_code, 200)

    def read_csv(self, client, filters=None):
        response = client.get('/reports.csv', query_string=filters or {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertIn('attachment; filename=govvendor-applications-', response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        return list(csv.DictReader(StringIO(response.data.decode('utf-8-sig'))))

    def test_report_dates_are_inclusive_and_export_matches_combined_filters(self):
        self.register()
        refs = []
        for name in ['Boundary Start LLC', 'Boundary End LLC', 'Next Day LLC']:
            refs.append(self.post('/applications/new', {**self.values, 'company_name': name}).location.rsplit('/', 1)[1])
        with self.db() as db:
            for ref, created in zip(refs, ['2026-01-31T00:00:00+04:00', '2026-01-31T23:59:59+04:00', '2026-02-01T00:00:00+04:00']):
                db.execute("UPDATE applications SET status='Submitted',created_at=? WHERE reference=?", (created, ref))
        filters = {'from_date': '2026-01-31', 'to_date': '2026-01-31', 'q': 'boundary', 'status': 'Submitted'}
        report = self.client.get('/reports', query_string=filters)
        self.assertEqual(report.status_code, 200)
        self.assertIn(b'data-report-total="all">2<', report.data)
        self.assertIn(b'Boundary Start LLC', report.data)
        self.assertIn(b'Boundary End LLC', report.data)
        self.assertNotIn(b'Next Day LLC', report.data)
        exported = self.read_csv(self.client, filters)
        self.assertEqual({row['Application reference'] for row in exported}, set(refs[:2]))
        self.assertTrue(all(row['Current status'] == 'Submitted' for row in exported))
        one_sided = self.read_csv(self.client, {'from_date': '2026-02-01'})
        self.assertEqual([row['Application reference'] for row in one_sided], [refs[2]])
        self.assertEqual(self.read_csv(self.client, {'q': 'No Such Company'}), [])

    def test_reports_and_csv_exclude_other_applicant_records(self):
        path = self.make_draft()
        own_ref = path.rsplit('/', 1)[1]
        other = self.app.test_client()
        self.register('other@example.com', other)
        other_path = self.post('/applications/new', {**self.values, 'company_name': 'Hidden Export Company'}, other).location
        other_ref = other_path.rsplit('/', 1)[1]
        page = self.client.get('/reports').data
        self.assertIn(b'data-report-total="all">1<', page)
        self.assertNotIn(other_ref.encode(), page)
        self.assertEqual([row['Application reference'] for row in self.read_csv(self.client)], [own_ref])
        self.assertEqual(self.read_csv(self.client, {'q': other_ref}), [])
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/reports').status_code, 302)
        self.assertEqual(anonymous.get('/reports.csv').status_code, 302)

    def test_reviewer_reports_match_review_queue_permissions(self):
        path, reviewer = self.approved_case()
        ref = path.rsplit('/', 1)[1]
        self.post('/applications/new', {**self.values, 'company_name': 'Private Report Draft'})
        other_reviewer = self.reviewer('other-report-reviewer@example.com')
        self.assertEqual([row['Application reference'] for row in self.read_csv(reviewer)], [ref])
        self.assertEqual(self.read_csv(other_reviewer), [])
        page = reviewer.get('/reports').data
        self.assertNotIn(b'Private Report Draft', page)
        self.assertIn(b'data-report-total="approved">1<', page)
        self.assertEqual(reviewer.get('/reports?status=Draft').status_code, 400)
        self.assertEqual(reviewer.get('/reports.csv?status=Draft').status_code, 400)

    def test_csv_roundtrip_unicode_quotes_and_formula_like_company_names(self):
        self.register()
        names = ['=1+1 Demo LLC', '+Demo Supplier', '-Demo Supplier', '@Demo Supplier',
                 'Demo, "Quoted"\nشركة']
        for name in names:
            self.post('/applications/new', {**self.values, 'company_name': name})
        exported = self.read_csv(self.client)
        values = {row['Company'] for row in exported}
        self.assertEqual(values, {"'" + name if name[0] in '=+-@' else name for name in names})
        self.assertTrue(self.client.get('/reports.csv').data.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(len(exported), len(names))
        self.assertEqual(set(exported[0]), {'Application reference', 'Record type', 'Previous approval reference',
            'Company', 'Category', 'Current status', 'Sample licence reference', 'Sample licence expiry',
            'Contact name', 'Contact email', 'Created (Dubai time)', 'Last updated (Dubai time)'})
        page = self.client.get('/reports', query_string={'q': '<script>alert(1)</script>'}).data
        self.assertNotIn(b'<script>alert(1)</script>', page)
        self.assertIn(b'No applications match', page)

    def test_renewal_type_and_previous_reference_are_in_report_and_export(self):
        path, _ = self.approved_case()
        renewal = self.post(path + '/renew').location.removesuffix('/edit')
        rows = self.read_csv(self.client)
        by_ref = {row['Application reference']: row for row in rows}
        self.assertEqual(by_ref[renewal.rsplit('/', 1)[1]]['Record type'], 'Renewal')
        self.assertEqual(by_ref[renewal.rsplit('/', 1)[1]]['Previous approval reference'], path.rsplit('/', 1)[1])
        self.assertEqual(by_ref[path.rsplit('/', 1)[1]]['Record type'], 'New registration')
        page = self.client.get('/reports').data
        self.assertIn(b'data-report-total="renewals">1<', page)
        self.assertIn(b'data-report-total="registrations">1<', page)
        self.assertIn(b'data-report-total="all">2<', page)

    def test_report_rejects_invalid_filter_values_for_page_and_export(self):
        self.register()
        invalid = [{'from_date': 'not-a-date'}, {'to_date': '2026-02-30'},
                   {'from_date': '2026-02-01', 'to_date': '2026-01-31'},
                   {'status': 'Unknown'}, {'q': 'x' * 121}]
        for route in ('/reports', '/reports.csv'):
            for filters in invalid:
                with self.subTest(route=route, filters=filters):
                    self.assertEqual(self.client.get(route, query_string=filters).status_code, 400)

    def administrator(self, email='admin@example.com'):
        password = 'administrator-demo-password'
        result = self.app.test_cli_runner().invoke(args=['create-administrator', '--email', email],
                                                   input=f'{password}\n{password}\n')
        self.assertEqual(result.exit_code, 0, result.output)
        client = self.app.test_client()
        login = self.post('/login', {'email': email, 'password': password}, client)
        self.assertEqual(login.location, '/admin')
        return client

    def admin_revision(self, client, reference):
        page = client.get('/admin/applications/' + reference)
        self.assertEqual(page.status_code, 200)
        return re.search(rb'name="revision" value="(\d+)"', page.data)[1].decode()

    def test_admin_setup_redirects_and_cannot_promote_existing_accounts(self):
        self.register('admin@example.com')
        failed = self.app.test_cli_runner().invoke(args=['create-administrator'])
        self.assertNotEqual(failed.exit_code, 0)
        with self.db() as db:
            self.assertEqual(db.execute("SELECT role FROM users WHERE email='admin@example.com'").fetchone()[0], 'applicant')
        admin = self.administrator('other-admin@example.com')
        self.assertEqual(admin.get('/dashboard').location, '/admin')
        self.assertEqual(admin.get('/applications/new').status_code, 403)
        self.assertIn(b'Open administration', admin.get('/').data)

    def test_admin_creates_reviewer_with_fixed_role_hash_and_unchanged_session(self):
        admin = self.administrator()
        account = {'name': 'Reviewer Two', 'email': 'REVIEWER2@EXAMPLE.COM', 'password': 'second-review-password',
                   'role': 'administrator'}
        response = self.post('/admin/reviewers', account, admin)
        self.assertEqual(response.status_code, 303)
        with self.db() as db:
            user = db.execute("SELECT * FROM users WHERE email='reviewer2@example.com'").fetchone()
            self.assertEqual(user['role'], 'officer')
            self.assertTrue(check_password_hash(user['password_hash'], account['password']))
        self.assertEqual(self.post('/admin/reviewers', account, admin).status_code, 409)
        self.assertEqual(self.post('/admin/reviewers', {**account, 'password': 'short'}, admin).status_code, 400)
        self.assertEqual(admin.get('/admin').status_code, 200)
        client = self.app.test_client()
        self.assertEqual(self.post('/login', {'email': 'reviewer2@example.com', 'password': account['password']}, client).location, '/review')

    def test_admin_reassignment_revokes_previous_reviewer_and_records_history(self):
        path = self.make_draft()
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        ref = path.rsplit('/', 1)[1]
        case = path.replace('/applications/', '/review/')
        first = self.reviewer()
        second = self.reviewer('second-reviewer@example.com')
        admin = self.administrator()
        with self.db() as db:
            first_id = db.execute("SELECT id FROM users WHERE email='reviewer@example.com'").fetchone()[0]
            second_id = db.execute("SELECT id FROM users WHERE email='second-reviewer@example.com'").fetchone()[0]
        assign_path = f'/admin/applications/{ref}/assign'
        result = self.post(assign_path, {'revision': self.admin_revision(admin, ref), 'reviewer_id': first_id}, admin)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(self.draft()['status'], 'Submitted')
        self.assertEqual(second.get(case).status_code, 404)
        self.assertIn(b'Start review</button>', first.get(case).data)
        self.post(case, {'revision': self.review_revision(first, case), 'action': 'start'}, first)
        stale_review_revision = self.review_revision(first, case)
        admin_revision = self.admin_revision(admin, ref)
        self.post(assign_path, {'revision': admin_revision, 'reviewer_id': second_id}, admin)
        self.assertEqual(self.draft()['status'], 'Under review')
        self.post(assign_path, {'revision': admin_revision, 'reviewer_id': second_id,
                                'note': 'Reassign for the demo shift.'}, admin)
        self.assertEqual(self.draft()['status'], 'Submitted')
        self.assertEqual(first.get(case).status_code, 404)
        self.assertEqual(first.get(case + '/documents/licence').status_code, 404)
        self.assertEqual(self.post(case, {'revision': stale_review_revision, 'action': 'approve'}, first).status_code, 404)
        self.assertEqual(second.get(case).status_code, 200)
        self.assertEqual(second.get(case + '/documents/licence').data, SAMPLE)
        self.assertIn(b'Reassign for the demo shift.', self.client.get(path).data)
        # Reusing an earlier admin form must not overwrite this assignment.
        self.assertEqual(self.post(assign_path, {'revision': admin_revision, 'reviewer_id': first_id,
                                                'note': 'Stale admin action'}, admin).status_code, 409)
        self.post(case, {'revision': self.review_revision(second, case), 'action': 'start'}, second)
        self.save_checklist(second, case)
        self.post(case, {'revision': self.review_revision(second, case), 'action': 'approve'}, second)
        self.assertEqual(self.draft()['status'], 'Approved')
        self.assertEqual(first.get(case + '/summary').status_code, 404)
        self.assertEqual(admin.get(f'/admin/applications/{ref}/summary').status_code, 200)
        with self.db() as db:
            latest = db.execute('SELECT MAX(id) FROM application_events').fetchone()[0]
        self.assertEqual(self.post(assign_path, {'revision': latest, 'reviewer_id': first_id}, admin).status_code, 400)

    def test_admin_actions_require_role_csrf_and_valid_reviewer(self):
        path = self.make_draft()
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        ref = path.rsplit('/', 1)[1]
        admin = self.administrator()
        reviewer = self.reviewer()
        for client in (self.client, reviewer):
            self.assertEqual(client.get('/admin').status_code, 403)
            self.assertEqual(client.get('/admin/reviewers').status_code, 403)
            self.assertEqual(client.get(f'/admin/applications/{ref}').status_code, 403)
            self.assertEqual(self.post(f'/admin/applications/{ref}/assign', client=client).status_code, 403)
            self.assertEqual(self.post('/admin/reviewers', client=client).status_code, 403)
        self.assertEqual(self.app.test_client().get('/admin').status_code, 302)
        assign = f'/admin/applications/{ref}/assign'
        revision = self.admin_revision(admin, ref)
        self.assertEqual(admin.post(assign, data={'revision': revision}).status_code, 400)
        with self.db() as db:
            applicant_id = db.execute("SELECT id FROM users WHERE role='applicant'").fetchone()[0]
        self.assertEqual(self.post(assign, {'revision': revision, 'reviewer_id': applicant_id}, admin).status_code, 400)
        self.assertEqual(self.post(assign, {'revision': revision, 'reviewer_id': 'invalid'}, admin).status_code, 400)

    def test_admin_scope_includes_submitted_records_and_excludes_private_drafts(self):
        path, _ = self.approved_case()
        draft = self.post('/applications/new', {**self.values, 'company_name': 'Private Admin Draft'}).location
        private_ref = draft.rsplit('/', 1)[1]
        admin = self.administrator()
        page = admin.get('/admin').data
        self.assertIn(b'data-total="all">1<', page)
        self.assertNotIn(b'Private Admin Draft', page)
        for suffix in ('', '/documents/licence', '/summary'):
            self.assertEqual(admin.get(f'/admin/applications/{private_ref}{suffix}').status_code, 404)
        self.assertEqual(admin.get('/admin?status=Draft').status_code, 400)
        self.assertEqual(admin.get('/reports?status=Draft').status_code, 400)
        self.assertEqual([row['Application reference'] for row in self.read_csv(admin)], [path.rsplit('/', 1)[1]])
        self.assertNotIn(b'Private Admin Draft', admin.get('/reports').data)

    def inbox_rows(self, client):
        with client.session_transaction() as session:
            user_id = session['user_id']
        with self.db() as db:
            return db.execute('''SELECT n.*,e.description FROM notifications n
                JOIN application_events e ON e.id=n.event_id WHERE n.user_id=? ORDER BY n.id DESC''', (user_id,)).fetchall()

    def test_submission_notifies_staff_without_notifying_private_drafts_or_other_applicants(self):
        path = self.make_draft()
        reviewer = self.reviewer()
        admin = self.administrator()
        outsider = self.app.test_client()
        self.register('notification-outsider@example.com', outsider)
        self.assertEqual(self.inbox_rows(reviewer), [])
        self.assertIn(b'No notifications yet', reviewer.get('/notifications').data)
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        self.assertEqual(len(self.inbox_rows(reviewer)), 1)
        self.assertEqual(len(self.inbox_rows(admin)), 1)
        self.assertEqual(self.inbox_rows(self.client), [])
        self.assertEqual(self.inbox_rows(outsider), [])
        self.assertIn(b'Application submitted for demo review', reviewer.get('/notifications').data)
        self.assertIn(b'1 unread', reviewer.get('/review').data)
        self.assertEqual(self.post(path + '/submit').status_code, 400)
        self.assertEqual(len(self.inbox_rows(reviewer)), 1)

    def test_owner_review_notifications_read_controls_are_private_and_keep_read_timestamp(self):
        path = self.make_draft()
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        reviewer = self.reviewer()
        case = path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'request-changes',
                         'note': 'Please correct the sample name.'}, reviewer)
        rows = self.inbox_rows(self.client)
        self.assertEqual(len(rows), 2)
        self.assertIn(b'Changes requested', self.client.get('/notifications').data)
        notification_id = rows[0]['id']
        other = self.app.test_client()
        self.register('not-my-notification@example.com', other)
        self.assertEqual(self.post(f'/notifications/{notification_id}/read', client=other).status_code, 404)
        self.assertEqual(self.post(f'/notifications/{notification_id}/open', client=other).status_code, 404)
        self.assertEqual(self.client.post(f'/notifications/{notification_id}/read').status_code, 400)
        self.post(f'/notifications/{notification_id}/read', {'view': 'unread'})
        first_read = self.inbox_rows(self.client)[0]['read_at']
        with patch('app.now', return_value='2099-01-01T12:00:00+04:00'):
            self.post(f'/notifications/{notification_id}/read')
        self.assertEqual(self.inbox_rows(self.client)[0]['read_at'], first_read)
        self.assertEqual(sum(row['read_at'] is None for row in self.inbox_rows(self.client)), 1)
        self.post('/notifications/read-all')
        self.assertTrue(all(row['read_at'] for row in self.inbox_rows(self.client)))
        self.assertIn(b'You are caught up', self.client.get('/notifications?view=unread').data)
        self.assertEqual(self.inbox_rows(other), [])

    def test_notification_open_uses_current_permissions_after_reassignment(self):
        path = self.make_draft()
        first = self.reviewer()
        second = self.reviewer('inbox-second@example.com')
        admin = self.administrator()
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        old_notice = self.inbox_rows(first)[0]['id']
        admin_notice = self.inbox_rows(admin)[0]['id']
        self.assertEqual(self.post(f'/notifications/{admin_notice}/open', client=admin).location,
                         '/admin/applications/' + path.rsplit('/', 1)[1])
        ref = path.rsplit('/', 1)[1]
        with self.db() as db:
            second_id = db.execute("SELECT id FROM users WHERE email='inbox-second@example.com'").fetchone()[0]
        self.post(f'/admin/applications/{ref}/assign',
                  {'revision': self.admin_revision(admin, ref), 'reviewer_id': second_id}, admin)
        self.assertIn(b'no longer available', first.get('/notifications').data)
        self.assertEqual(self.post(f'/notifications/{old_notice}/open', client=first).location, '/notifications')
        self.assertEqual(first.get(path.replace('/applications/', '/review/')).status_code, 404)
        assigned_notice = self.inbox_rows(second)[0]['id']
        self.assertEqual(self.post(f'/notifications/{assigned_notice}/open', client=second).location,
                         path.replace('/applications/', '/review/'))
        owner_notice = self.inbox_rows(self.client)[0]['id']
        self.assertEqual(self.post(f'/notifications/{owner_notice}/open').location, path)

    def test_resubmission_notifies_assigned_reviewer_and_administrators(self):
        path = self.make_draft()
        reviewer = self.reviewer()
        other_reviewer = self.reviewer('other-inbox-reviewer@example.com')
        admin = self.administrator()
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        case = path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'request-changes',
                         'note': 'Check the demo contact.'}, reviewer)
        for client in (reviewer, other_reviewer, admin, self.client):
            self.post('/notifications/read-all', client=client)
        self.post(path + '/submit')
        self.assertEqual(sum(row['read_at'] is None for row in self.inbox_rows(reviewer)), 1)
        self.assertEqual(sum(row['read_at'] is None for row in self.inbox_rows(admin)), 1)
        self.assertEqual(sum(row['read_at'] is None for row in self.inbox_rows(other_reviewer)), 0)
        self.assertEqual(sum(row['read_at'] is None for row in self.inbox_rows(self.client)), 0)
        self.assertIn('resubmitted', self.inbox_rows(reviewer)[0]['description'])

    def test_inbox_pagination_invalid_inputs_and_restart(self):
        path = self.make_draft()
        with self.db() as db:
            application = db.execute('SELECT id,user_id FROM applications').fetchone()
            for i in range(30):
                event = db.execute('INSERT INTO application_events(application_id,actor_id,description,created_at) VALUES (?,?,?,?)',
                                   (application['id'], application['user_id'], f'Demo inbox item {i:02d}', '2026-11-04T12:00:00+04:00'))
                db.execute('INSERT INTO notifications(user_id,event_id) VALUES (?,?)', (application['user_id'], event.lastrowid))
        page = self.client.get('/notifications').data
        self.assertIn(b'Demo inbox item 29', page)
        self.assertNotIn(b'Demo inbox item 04', page)
        self.assertIn(b'Page 1 of 2', page)
        page2 = self.client.get('/notifications?page=2').data
        self.assertIn(b'Demo inbox item 04', page2)
        self.assertIn(b'Demo inbox item 00', page2)
        for query in ('page=0', 'page=abc', 'view=unknown'):
            self.assertEqual(self.client.get('/notifications?' + query).status_code, 400)
        self.assertEqual(self.client.get('/notifications?page=9999999999999999999999999').status_code, 404)
        self.assertEqual(self.post('/notifications/9999999999999999999999999999/read').status_code, 404)
        self.assertEqual(self.client.get('/notifications/read-all').status_code, 405)
        self.assertEqual(self.app.test_client().get('/notifications').status_code, 302)
        restarted = create_app(self.config).test_client()
        self.post('/login', {'email': 'applicant@example.com', 'password': 'fictional-password-123'}, restarted)
        self.assertIn(b'Demo inbox item 29', restarted.get('/notifications').data)
        self.post('/notifications/read-all', client=restarted)
        self.assertTrue(all(row['read_at'] for row in self.inbox_rows(restarted)))

    def test_document_replacement_keeps_earlier_bytes_names_and_current_version(self):
        path = self.make_draft()
        self.attach(path, filename='first.pdf')
        self.attach(path, content=PROFILE, filename='second.pdf')
        ref = path.rsplit('/', 1)[1]
        history = f'/documents/{ref}/licence/history'
        page = self.client.get(history)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Version 1', page.data)
        self.assertIn(b'Version 2', page.data)
        self.assertIn(b'first.pdf', page.data)
        self.assertIn(b'second.pdf', page.data)
        self.assertIn(b'Version 2', self.client.get(path).data)
        self.assertEqual(self.client.get(f'/documents/{ref}/licence/versions/1').data, SAMPLE)
        latest = self.client.get(f'/documents/{ref}/licence/versions/2')
        self.assertEqual(latest.data, PROFILE)
        self.assertIn('attachment; filename=second-v2.pdf', latest.headers['Content-Disposition'])
        self.assertEqual(latest.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get(path + '/documents/licence').data, PROFILE)
        self.assertIn(b'attached (version 2)', self.client.get(path).data)
        app = create_app(self.config)
        client = app.test_client()
        self.post('/login', {'email': 'applicant@example.com', 'password': 'fictional-password-123'}, client)
        self.assertEqual(client.get(f'/documents/{ref}/licence/versions/1').data, SAMPLE)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM document_versions').fetchone()[0], 2)

    def test_invalid_or_locked_uploads_do_not_create_versions(self):
        path = self.make_draft()
        self.attach(path, content=b'Not a PDF')
        ref = path.rsplit('/', 1)[1]
        self.assertEqual(self.client.get(f'/documents/{ref}/licence/history').status_code, 404)
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        self.assertEqual(self.attach(path).status_code, 400)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM document_versions').fetchone()[0], 2)
        for route in (f'/documents/{ref}/unknown/history', f'/documents/{ref}/licence/versions/0',
                      f'/documents/{ref}/licence/versions/99999999999999999999999999999'):
            self.assertEqual(self.client.get(route).status_code, 404)

    def test_version_access_matches_current_roles_and_reassignment(self):
        path = self.make_draft()
        self.attach(path)
        self.attach(path, content=PROFILE)
        self.attach(path, 'profile', PROFILE)
        ref = path.rsplit('/', 1)[1]
        history = f'/documents/{ref}/licence/history'
        download = f'/documents/{ref}/licence/versions/1'
        first = self.reviewer()
        second = self.reviewer('history-second@example.com')
        admin = self.administrator()
        outsider = self.app.test_client()
        self.register('history-outsider@example.com', outsider)
        for client in (first, second, admin, outsider):
            self.assertEqual(client.get(history).status_code, 404)
            self.assertEqual(client.get(download).status_code, 404)
        self.assertEqual(self.app.test_client().get(download).status_code, 302)
        self.post(path + '/submit')
        for client in (first, second, admin):
            self.assertEqual(client.get(history).status_code, 200)
            self.assertEqual(client.get(download).data, SAMPLE)
        self.assertEqual(outsider.get(download).status_code, 404)
        case = path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(first, case), 'action': 'start'}, first)
        self.assertEqual(second.get(download).status_code, 404)
        with self.db() as db:
            second_id = db.execute("SELECT id FROM users WHERE email='history-second@example.com'").fetchone()[0]
        self.post(f'/admin/applications/{ref}/assign', {'revision': self.admin_revision(admin, ref),
                  'reviewer_id': second_id, 'note': 'History demo reassignment'}, admin)
        self.assertEqual(first.get(history).status_code, 404)
        self.assertEqual(first.get(download).status_code, 404)
        self.assertEqual(second.get(download).data, SAMPLE)
        self.assertEqual(admin.get(download).data, SAMPLE)

    def test_upgrade_seed_is_idempotent_and_renewal_documents_have_separate_histories(self):
        path, _ = self.approved_case()
        # Simulate pre-feature saved documents: reopening seeds one current version each.
        with self.db() as db:
            db.execute('DELETE FROM document_versions')
        create_app(self.config)
        create_app(self.config)
        with self.db() as db:
            versions = db.execute('SELECT * FROM document_versions ORDER BY kind').fetchall()
            self.assertEqual(len(versions), 2)
            self.assertTrue(all(row['version'] == 1 for row in versions))
        renewal = self.post(path + '/renew').location.removesuffix('/edit')
        self.attach(renewal, filename='renewal.pdf')
        renewal_ref = renewal.rsplit('/', 1)[1]
        parent_ref = path.rsplit('/', 1)[1]
        self.assertIn(b'1 saved version(s)', self.client.get(f'/documents/{renewal_ref}/licence/history').data)
        self.assertEqual(self.client.get(f'/documents/{parent_ref}/licence/versions/1').data, SAMPLE)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM document_versions').fetchone()[0], 3)


    def review_case(self):
        path = self.make_draft()
        self.attach(path, filename='sample-trade-licence.pdf')
        self.attach(path, 'profile', PROFILE, 'sample-company-profile.pdf')
        self.post(path + '/submit')
        reviewer = self.reviewer()
        case = path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        return path, case, reviewer

    def test_checklist_partial_progress_persists_and_forged_approval_is_blocked(self):
        path, case, reviewer = self.review_case()
        partial = ['company_details', 'licence_expiry']
        with self.db() as db:
            notices_before = db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0]
        self.assertEqual(self.save_checklist(reviewer, case, partial).status_code, 303)
        page = reviewer.get(case).data
        self.assertIn(b'data-review-count="2"', page)
        self.assertIn(b'value="approve" disabled', page)
        self.assertIn(b'name="checks" value="company_details" checked', page)
        revision = self.review_revision(reviewer, case)
        self.post(case, {'revision': revision, 'action': 'approve', 'checks': list(REVIEW_CHECKS)}, reviewer)
        self.assertEqual(self.draft()['status'], 'Under review')
        self.assertIn(b'before approving', reviewer.get(case).data)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], notices_before)
        reopened = create_app(self.config).test_client()
        self.post('/login', {'email': 'reviewer@example.com', 'password': 'reviewer-test-password'}, reopened)
        self.assertIn(b'data-review-count="2"', reopened.get(case).data)
        self.save_checklist(reopened, case)
        self.assertNotIn(b'value="approve" disabled', reopened.get(case).data)
        self.post(case, {'revision': self.review_revision(reopened, case), 'action': 'approve'}, reopened)
        self.assertEqual(self.draft()['status'], 'Approved')
        self.assertIn(b'Reviewer saved checklist (4 of 4)', self.client.get(path).data)
        with self.db() as db:
            final = dict(db.execute('SELECT * FROM review_checklists').fetchone())
            latest = db.execute('SELECT MAX(id) FROM application_events').fetchone()[0]
        self.assertEqual(self.post(case + '/checklist', {'revision': latest, 'checks': []}, reopened).status_code, 400)
        with self.db() as db:
            self.assertEqual(dict(db.execute('SELECT * FROM review_checklists').fetchone()), final)

    def test_checklist_noop_uncheck_and_stale_forms_cannot_overwrite_progress(self):
        _, case, reviewer = self.review_case()
        stale_revision = self.review_revision(reviewer, case)
        self.save_checklist(reviewer, case)
        saved_revision = self.review_revision(reviewer, case)
        self.save_checklist(reviewer, case)
        self.assertEqual(self.review_revision(reviewer, case), saved_revision)
        self.assertEqual(self.post(case + '/checklist', {'revision': stale_revision, 'checks': []}, reviewer).status_code, 409)
        self.assertEqual(self.post(case, {'revision': stale_revision, 'action': 'approve'}, reviewer).status_code, 409)
        self.assertIn(b'data-review-count="4"', reviewer.get(case).data)
        self.save_checklist(reviewer, case, [])
        self.assertIn(b'data-review-count="0"', reviewer.get(case).data)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Under review')
        with self.db() as db:
            descriptions = [row[0] for row in db.execute("SELECT description FROM application_events WHERE description LIKE 'Reviewer saved checklist%' ORDER BY id")]
        self.assertEqual(len(descriptions), 2)
        self.assertIn('(4 of 4)', descriptions[0])
        self.assertIn('(0 of 4): None', descriptions[1])

    def test_resubmission_clears_checklist_but_retains_prior_checks_in_activity(self):
        path, case, reviewer = self.review_case()
        self.save_checklist(reviewer, case)
        old_revision = self.review_revision(reviewer, case)
        self.post(case, {'revision': old_revision, 'action': 'request-changes', 'note': 'Replace the sample profile.'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Changes requested')
        with self.db() as db:
            last = db.execute('SELECT MAX(id) FROM application_events').fetchone()[0]
        self.assertEqual(self.post(case + '/checklist', {'revision': last, 'checks': []}, reviewer).status_code, 400)
        self.attach(path, 'profile', SAMPLE, 'corrected-profile.pdf')
        self.post(path + '/edit', {**self.values, 'contact_name': 'Corrected Demo Contact'})
        self.post(path + '/submit')
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_checklists').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT MAX(version) FROM document_versions WHERE kind='profile'").fetchone()[0], 2)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.assertIn(b'data-review-count="0"', reviewer.get(case).data)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Under review')
        self.assertIn(b'Reviewer saved checklist (4 of 4)', self.client.get(path).data)
        self.save_checklist(reviewer, case)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Approved')

    def test_reassignment_clears_checklist_and_same_reviewer_assignment_preserves_it(self):
        path, case, reviewer = self.review_case()
        self.save_checklist(reviewer, case)
        admin = self.administrator()
        ref = path.rsplit('/', 1)[1]
        assign = f'/admin/applications/{ref}/assign'
        with self.db() as db:
            first_id = db.execute("SELECT id FROM users WHERE email='reviewer@example.com'").fetchone()[0]
        self.post(assign, {'revision': self.admin_revision(admin, ref), 'reviewer_id': first_id}, admin)
        self.assertIn(b'data-review-count="4"', reviewer.get(case).data)
        second = self.reviewer('second-checklist@example.com')
        with self.db() as db:
            second_id = db.execute("SELECT id FROM users WHERE email='second-checklist@example.com'").fetchone()[0]
        self.post(assign, {'revision': self.admin_revision(admin, ref), 'reviewer_id': second_id,
                          'note': 'New demo review shift.'}, admin)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_checklists').fetchone()[0], 0)
            latest = db.execute('SELECT MAX(id) FROM application_events').fetchone()[0]
        self.assertEqual(self.post(case + '/checklist', {'revision': latest, 'checks': list(REVIEW_CHECKS)}, reviewer).status_code, 404)
        self.post(case, {'revision': self.review_revision(second, case), 'action': 'start'}, second)
        self.assertIn(b'data-review-count="0"', second.get(case).data)
        self.save_checklist(second, case)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT reviewer_id FROM review_checklists').fetchone()[0], second_id)

    def test_checklist_roles_csrf_stage_and_input_validation(self):
        path = self.make_draft()
        reviewer = self.reviewer()
        case = path.replace('/applications/', '/review/')
        self.assertEqual(self.post(case + '/checklist', {'checks': []}, reviewer).status_code, 404)
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        revision = self.review_revision(reviewer, case)
        self.assertEqual(self.post(case + '/checklist', {'revision': revision}, reviewer).status_code, 400)
        self.post(case, {'revision': revision, 'action': 'start'}, reviewer)
        revision = self.review_revision(reviewer, case)
        other = self.reviewer('outsider-check@example.com')
        admin = self.administrator()
        for client, status in [(self.client, 403), (admin, 403), (other, 404)]:
            self.assertEqual(self.post(case + '/checklist', {'revision': revision}, client).status_code, status)
        self.assertEqual(self.app.test_client().post(case + '/checklist').status_code, 400)
        self.assertEqual(reviewer.post(case + '/checklist', data={'revision': revision}).status_code, 400)
        for invalid in [['fake'], ['company_details', 'company_details']]:
            self.assertEqual(self.save_checklist(reviewer, case, invalid).status_code, 400)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_checklists').fetchone()[0], 0)
        self.assertEqual(self.review_revision(reviewer, case), revision)
        # A return or rejection does not need a completed checklist.
        self.post(case, {'revision': revision, 'action': 'reject', 'note': 'Demo details do not match.'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Rejected')

    def test_checklist_cannot_override_expiry_or_missing_documents(self):
        path, case, reviewer = self.review_case()
        self.save_checklist(reviewer, case)
        with patch('app.local_today', return_value=date(2028, 1, 1)):
            self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Under review')
        # Simulate incomplete imported data: tick boxes alone do not create a PDF.
        with self.db() as db:
            db.execute("DELETE FROM document_versions WHERE kind='profile'")
            db.execute("DELETE FROM application_documents WHERE kind='profile'")
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Under review')


    def message_fields(self, client, path, body='Please check the fictional company profile.'):
        page = client.get(path + '/messages')
        self.assertEqual(page.status_code, 200)
        token = re.search(rb'name="message_token" value="([a-f0-9]+)"', page.data)
        reviewer_id = re.search(rb'name="reviewer_id" value="(\d+)"', page.data)
        self.assertIsNotNone(token)
        self.assertIsNotNone(reviewer_id)
        return {'body': body, 'message_token': token[1].decode(), 'reviewer_id': reviewer_id[1].decode()}

    def test_application_messages_roundtrip_roles_escaping_notifications_and_restart(self):
        path, case, reviewer = self.review_case()
        self.save_checklist(reviewer, case, ['company_details'])
        admin = self.administrator()
        with self.db() as db:
            old_status = db.execute('SELECT status FROM applications').fetchone()[0]
            checklist = dict(db.execute('SELECT * FROM review_checklists').fetchone())
            notices = db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0]
        body = 'Question <script>alert(1)</script> & company details?\nSecond line: مرحبا'
        fields = self.message_fields(self.client, path, body)
        response = self.post(path + '/messages', {**fields, 'author_role': 'officer', 'author_id': '999'}, self.client)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, path + '/messages#conversation-end')
        response = reviewer.get(path + '/messages')
        self.assertIn(b'Question &lt;script&gt;', response.data)
        self.assertNotIn(b'<script>alert(1)</script>', response.data)
        self.assertIn('مرحبا'.encode(), response.data)
        self.assertIn(b'>Applicant</span>', response.data)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with self.db() as db:
            message = db.execute('SELECT * FROM application_messages').fetchone()
            owner = db.execute("SELECT id FROM users WHERE role='applicant'").fetchone()[0]
            reviewer_id = db.execute("SELECT id FROM users WHERE role='officer'").fetchone()[0]
            self.assertEqual(message['author_id'], owner)
            self.assertEqual(message['author_role'], 'applicant')
            recipients = [row[0] for row in db.execute('SELECT user_id FROM notifications WHERE event_id=?', (message['event_id'],))]
            self.assertEqual(recipients, [reviewer_id])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], notices + 1)
            notification_id = db.execute('SELECT id FROM notifications WHERE event_id=?', (message['event_id'],)).fetchone()[0]
            self.assertEqual(dict(db.execute('SELECT * FROM review_checklists').fetchone()), checklist)
        inbox = reviewer.get('/notifications').data
        self.assertIn(b'Open messages', inbox)
        self.assertNotIn(b'Question &lt;script&gt;', inbox)  # Message body is not copied into inbox/history.
        self.assertEqual(self.post(f'/notifications/{notification_id}/open', client=reviewer).location, path + '/messages')
        reply = self.message_fields(reviewer, path, 'The sample profile is readable. Thank you.')
        self.assertEqual(self.post(path + '/messages', reply, reviewer).status_code, 303)
        with self.db() as db:
            message = db.execute('SELECT * FROM application_messages ORDER BY id DESC LIMIT 1').fetchone()
            self.assertEqual([row[0] for row in db.execute('SELECT user_id FROM notifications WHERE event_id=?', (message['event_id'],))], [owner])
            self.assertEqual(db.execute('SELECT status FROM applications').fetchone()[0], old_status)
        self.assertIn(b'The sample profile is readable.', admin.get(path + '/messages').data)
        self.assertNotIn(b'Send message</button>', admin.get(path + '/messages').data)
        reopened = create_app(self.config).test_client()
        self.post('/login', {'email': 'applicant@example.com', 'password': 'fictional-password-123'}, reopened)
        page = reopened.get(path + '/messages').data
        self.assertIn(b'Question &lt;script&gt;', page)
        self.assertIn(b'The sample profile is readable.', page)
        self.assertIn(b'2 message(s)', page)

    def test_message_retries_are_idempotent_and_token_reuse_cannot_change_body(self):
        path, _, reviewer = self.review_case()
        fields = self.message_fields(self.client, path, 'One saved demo question.')
        self.assertEqual(self.post(path + '/messages', fields).status_code, 303)
        with self.db() as db:
            before = tuple(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                           for table in ('application_messages', 'application_events', 'notifications'))
        self.assertEqual(self.post(path + '/messages', fields).status_code, 303)
        self.assertEqual(self.post(path + '/messages', {**fields, 'body': 'Changed duplicate'}).status_code, 409)
        # The same token on a second application does not cross-link the thread.
        second_path = self.post('/applications/new', self.values).location
        self.attach(second_path)
        self.attach(second_path, 'profile', PROFILE)
        self.post(second_path + '/submit')
        second_case = second_path.replace('/applications/', '/review/')
        self.post(second_case, {'revision': self.review_revision(reviewer, second_case), 'action': 'start'}, reviewer)
        self.assertEqual(self.post(second_path + '/messages', fields).status_code, 409)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_messages').fetchone()[0], before[0])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM application_events WHERE description LIKE '%sent an application message'").fetchone()[0], 1)
            event_id = db.execute('SELECT event_id FROM application_messages').fetchone()[0]
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications WHERE event_id=?', (event_id,)).fetchone()[0], 1)

    def test_messages_require_owner_assignment_role_and_csrf(self):
        path, _, reviewer = self.review_case()
        fields = self.message_fields(self.client, path)
        outsider = self.app.test_client()
        self.register('other-messages@example.com', outsider)
        other_reviewer = self.reviewer('unassigned-messages@example.com')
        admin = self.administrator()
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get(path + '/messages').status_code, 302)
        self.assertEqual(self.post(path + '/messages', fields, anonymous).status_code, 302)
        for client in (outsider, other_reviewer):
            self.assertEqual(client.get(path + '/messages').status_code, 404)
            self.assertEqual(self.post(path + '/messages', fields, client).status_code, 404)
        self.assertEqual(self.post(path + '/messages', fields, admin).status_code, 403)
        self.assertEqual(self.client.post(path + '/messages', data=fields).status_code, 400)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_messages').fetchone()[0], 0)
        self.assertEqual(self.post(path + '/messages', fields).status_code, 303)
        self.assertIn(b'Please check', reviewer.get(path + '/messages').data)

    def test_messages_unavailable_for_drafts_and_wait_for_assignment(self):
        path = self.make_draft()
        reviewer = self.reviewer()
        admin = self.administrator()
        data = {'body': 'Hello', 'message_token': 'a' * 32, 'reviewer_id': '1'}
        for client in (self.client, reviewer, admin):
            self.assertEqual(client.get(path + '/messages').status_code, 404)
            self.assertEqual(self.post(path + '/messages', data, client).status_code, 404)
        self.assertNotIn(b'Messages', self.client.get(path).data)
        self.attach(path)
        self.attach(path, 'profile', PROFILE)
        self.post(path + '/submit')
        for client in (self.client, reviewer):
            page = client.get(path + '/messages')
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Messages become available', page.data)
            self.assertNotIn(b'Send message</button>', page.data)
            self.assertEqual(self.post(path + '/messages', data, client).status_code, 400)
        case = path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.assertEqual(self.post(path + '/messages', self.message_fields(self.client, path)).status_code, 303)

    def test_message_validation_keeps_text_and_never_partially_writes(self):
        path, _, _ = self.review_case()
        fields = self.message_fields(self.client, path)
        with self.db() as db:
            before = tuple(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                           for table in ('application_messages', 'application_events', 'notifications'))
        for body in (' ', 'x' * 1501, 'ab\x00cd'):
            response = self.post(path + '/messages', {**fields, 'body': body})
            self.assertEqual(response.status_code, 400)
            self.assertIn(b'aria-invalid="true"', response.data)
        invalid = {**fields, 'body': 'My <question> is still here.', 'message_token': 'invalid'}
        response = self.post(path + '/messages', invalid)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'My &lt;question&gt; is still here.', response.data)
        with self.db() as db:
            after = tuple(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                          for table in ('application_messages', 'application_events', 'notifications'))
        self.assertEqual(before, after)
        # The exact upper bound remains valid.
        self.assertEqual(self.post(path + '/messages', {**fields, 'body': 'x' * 1500}).status_code, 303)

    def test_message_reassignment_preserves_thread_revokes_access_and_blocks_stale_recipient(self):
        path, _, first = self.review_case()
        self.post(path + '/messages', self.message_fields(first, path, 'Earlier reviewer question.'), first)
        stale = self.message_fields(self.client, path, 'Answer after a reviewer change.')
        admin = self.administrator()
        second = self.reviewer('message-second@example.com')
        ref = path.rsplit('/', 1)[1]
        with self.db() as db:
            second_id = db.execute("SELECT id FROM users WHERE email='message-second@example.com'").fetchone()[0]
        self.post(f'/admin/applications/{ref}/assign', {'revision': self.admin_revision(admin, ref),
                  'reviewer_id': second_id, 'note': 'New demo reviewer.'}, admin)
        self.assertEqual(first.get(path + '/messages').status_code, 404)
        self.assertEqual(self.post(path + '/messages', stale, first).status_code, 404)
        response = self.post(path + '/messages', stale)
        self.assertEqual(response.status_code, 409)
        self.assertIn(b'Answer after a reviewer change.', response.data)
        self.assertIn(b'The reviewer assignment changed.', response.data)
        self.assertIn(b'Earlier reviewer question.', second.get(path + '/messages').data)
        fields = self.message_fields(self.client, path, stale['body'])
        self.assertEqual(fields['reviewer_id'], str(second_id))
        self.post(path + '/messages', fields)
        with self.db() as db:
            last = db.execute('SELECT event_id FROM application_messages ORDER BY id DESC LIMIT 1').fetchone()[0]
            self.assertEqual([row[0] for row in db.execute('SELECT user_id FROM notifications WHERE event_id=?', (last,))], [second_id])
        self.assertIn(b'Answer after', admin.get(path + '/messages').data)

    def test_message_notifications_lose_links_for_reassigned_reviewer(self):
        path, _, first = self.review_case()
        self.post(path + '/messages', self.message_fields(self.client, path, 'Question for the original reviewer.'))
        with self.db() as db:
            event_id = db.execute('SELECT event_id FROM application_messages').fetchone()[0]
            notice_id = db.execute('SELECT id FROM notifications WHERE event_id=?', (event_id,)).fetchone()[0]
        admin = self.administrator()
        second = self.reviewer('notification-message-second@example.com')
        with self.db() as db:
            second_id = db.execute("SELECT id FROM users WHERE email='notification-message-second@example.com'").fetchone()[0]
        ref = path.rsplit('/', 1)[1]
        self.post(f'/admin/applications/{ref}/assign', {'revision': self.admin_revision(admin, ref),
                  'reviewer_id': second_id, 'note': 'Switch reviewer for message test.'}, admin)
        page = first.get('/notifications').data
        self.assertNotIn(f'/notifications/{notice_id}/open'.encode(), page)
        self.assertEqual(self.post(f'/notifications/{notice_id}/open', client=first).location, '/notifications')
        self.assertEqual(first.get(path + '/messages').status_code, 404)

    def test_messages_after_corrections_remain_readable_and_final_decisions_lock_new_sends(self):
        path, case, reviewer = self.review_case()
        self.post(path + '/messages', self.message_fields(self.client, path, 'Before corrections.'))
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'request-changes', 'note': 'Correct the contact.'}, reviewer)
        self.post(path + '/messages', self.message_fields(self.client, path, 'I am making corrections.'))
        self.post(path + '/edit', {**self.values, 'contact_name': 'Corrected Demo Contact'})
        self.post(path + '/submit')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.save_checklist(reviewer, case)
        pending = self.message_fields(self.client, path, 'A message from an old open form.')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        self.assertEqual(self.draft()['status'], 'Approved')
        self.assertEqual(self.post(path + '/messages', pending).status_code, 400)
        for client in (self.client, reviewer):
            page = client.get(path + '/messages').data
            self.assertIn(b'Before corrections.', page)
            self.assertIn(b'I am making corrections.', page)
            self.assertNotIn(b'Send message</button>', page)
        # A renewal is a separate conversation, and its private Draft has no messages page.
        renewal = self.post(path + '/renew').location.removesuffix('/edit')
        self.assertEqual(self.client.get(renewal + '/messages').status_code, 404)
        self.assertIn(b'2 message(s)', self.client.get(path + '/messages').data)

    def test_message_pagination_is_case_scoped_and_validated(self):
        path, _, _ = self.review_case()
        for number in range(21):
            fields = self.message_fields(self.client, path, f'Demo message {number:02d}')
            self.assertEqual(self.post(path + '/messages', fields).status_code, 303)
        latest = self.client.get(path + '/messages').data
        self.assertIn(b'Demo message 20', latest)
        self.assertNotIn(b'Demo message 00', latest)
        self.assertIn(b'Page 2 of 2', latest)
        older = self.client.get(path + '/messages?page=1').data
        self.assertIn(b'Demo message 00', older)
        self.assertIn(b'Demo message 19', older)
        self.assertNotIn(b'Demo message 20', older)
        for page in ('0', '-1', 'abc'):
            self.assertEqual(self.client.get(path + '/messages?page=' + page).status_code, 400)
        self.assertEqual(self.client.get(path + '/messages?page=3').status_code, 404)
        self.assertEqual(self.client.get(path + '/messages?page=' + '9'*100).status_code, 404)


    def save_plan(self, admin, path, priority='Normal', target_date=''):
        reference = path.rsplit('/', 1)[1]
        return self.post(f'/admin/applications/{reference}/plan',
                         {'revision': self.admin_revision(admin, reference),
                          'priority': priority, 'target_date': target_date}, admin)

    def plan_fixture(self, name, status, reviewer_id, priority='Normal', target_date=None):
        # Deterministic list fixtures; workflow mutations themselves use the real routes.
        with self.db() as db:
            base = db.execute('SELECT * FROM applications ORDER BY id LIMIT 1').fetchone()
            number = db.execute('SELECT MAX(id)+1 FROM applications').fetchone()[0]
            reference = f'GV-{number:012X}'
            values = (reference, base['user_id'], name, base['category'], base['trade_reference'],
                      base['licence_expiry'], base['contact_name'], base['contact_email'], status,
                      base['created_at'], base['updated_at'])
            result = db.execute("""INSERT INTO applications(reference,user_id,company_name,category,trade_reference,
                licence_expiry,contact_name,contact_email,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""", values)
            application_id = result.lastrowid
            db.execute('INSERT INTO application_events(application_id,actor_id,description,created_at) VALUES (?,?,?,?)',
                       (application_id, base['user_id'], 'Registration draft created', base['created_at']))
            if reviewer_id is not None:
                db.execute('INSERT INTO application_reviews(application_id,reviewer_id) VALUES (?,?)',
                           (application_id, reviewer_id))
            if priority != 'Normal' or target_date:
                admin_id = db.execute("SELECT id FROM users WHERE role='administrator'").fetchone()[0]
                db.execute('INSERT INTO review_plans VALUES (?,?,?,?,?)',
                           (application_id, priority, target_date, admin_id, base['updated_at']))
        return '/applications/' + reference

    def test_review_plan_saves_preserves_application_and_notifies_current_parties(self):
        path, case, reviewer = self.review_case()
        admin = self.administrator()
        self.save_checklist(reviewer, case, ['company_details'])
        with self.db() as db:
            before = dict(db.execute('SELECT * FROM applications').fetchone())
            checklist = dict(db.execute('SELECT * FROM review_checklists').fetchone())
            docs = db.execute('SELECT * FROM document_versions ORDER BY kind').fetchall()
            admin_id = db.execute("SELECT id FROM users WHERE role='administrator'").fetchone()[0]
            owner_id = before['user_id']
            reviewer_id = db.execute("SELECT id FROM users WHERE role='officer'").fetchone()[0]
        with patch('app.local_today', return_value=date(2026, 11, 4)):
            self.assertEqual(self.save_plan(admin, path, 'Urgent', '2026-11-04').status_code, 303)
            page = reviewer.get(case).data
            self.assertIn(b'priority-urgent', page)
            self.assertIn(b'timing-today">Due today', page)
            self.assertNotIn(b'Save review plan', page)
            self.assertIn(b'priority-urgent', self.client.get(path).data)
            self.assertNotIn(b'Save review plan', self.client.get(path).data)
            self.assertIn(b'data-review-total="today">1<', reviewer.get('/review').data)
        with self.db() as db:
            plan = db.execute('SELECT * FROM review_plans').fetchone()
            self.assertEqual(plan['priority'], 'Urgent')
            self.assertEqual(plan['target_date'], '2026-11-04')
            self.assertEqual(plan['updated_by'], admin_id)
            after = dict(db.execute('SELECT * FROM applications').fetchone())
            self.assertEqual({key:value for key,value in before.items() if key != 'updated_at'},
                             {key:value for key,value in after.items() if key != 'updated_at'})
            self.assertEqual(dict(db.execute('SELECT * FROM review_checklists').fetchone()), checklist)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM document_versions ORDER BY kind')], [tuple(row) for row in docs])
            event = db.execute('SELECT id,description FROM application_events ORDER BY id DESC LIMIT 1').fetchone()
            self.assertIn('Normal / no target date → Urgent / 2026-11-04', event['description'])
            self.assertEqual({row[0] for row in db.execute('SELECT user_id FROM notifications WHERE event_id=?', (event['id'],))}, {owner_id, reviewer_id})
        self.assertIn(b'Administrator updated review plan', self.client.get('/notifications').data)
        self.assertIn(b'Administrator updated review plan', reviewer.get('/notifications').data)
        reopened = create_app(self.config).test_client()
        self.post('/login', {'email': 'applicant@example.com', 'password': 'fictional-password-123'}, reopened)
        self.assertIn(b'priority-urgent', reopened.get(path).data)
        self.assertIn(b'2026-11-04', reopened.get(path).data)

    def test_review_plan_noop_and_clear_date_do_not_create_duplicate_activity(self):
        path, _, _ = self.review_case()
        admin = self.administrator()
        with self.db() as db:
            counts = tuple(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                           for table in ('review_plans', 'application_events', 'notifications'))
        self.save_plan(admin, path)
        with self.db() as db:
            self.assertEqual(tuple(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                                   for table in ('review_plans', 'application_events', 'notifications')), counts)
        self.save_plan(admin, path, 'High', '2026-11-03')
        with self.db() as db:
            changed = tuple(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                            for table in ('review_plans', 'application_events', 'notifications'))
        self.save_plan(admin, path, 'High', '2026-11-03')
        with self.db() as db:
            self.assertEqual(tuple(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                                   for table in ('review_plans', 'application_events', 'notifications')), changed)
        self.save_plan(admin, path, 'Normal', '')
        with self.db() as db:
            plan = db.execute('SELECT * FROM review_plans').fetchone()
            self.assertEqual(plan['priority'], 'Normal')
            self.assertIsNone(plan['target_date'])
        self.assertIn(b'High / 2026-11-03', self.client.get(path).data)
        self.assertIn(b'Normal / no target date', self.client.get(path).data)

    def test_review_plan_date_boundaries_waiting_and_completed_cases(self):
        path, _, reviewer = self.review_case()
        admin = self.administrator()
        with self.db() as db:
            reviewer_id = db.execute("SELECT id FROM users WHERE role='officer'").fetchone()[0]
        future = self.plan_fixture('Future Due Demo LLC', 'Submitted', reviewer_id, 'High', '2026-11-05')
        waiting = self.plan_fixture('Waiting Demo LLC', 'Changes requested', reviewer_id, 'Urgent', '2026-11-01')
        completed = self.plan_fixture('Completed Demo LLC', 'Approved', reviewer_id, 'Urgent', '2026-11-01')
        with patch('app.local_today', return_value=date(2026, 11, 4)):
            self.save_plan(admin, path, 'High', '2026-11-03')
            page = reviewer.get('/review').data
            self.assertIn(b'data-review-total="overdue">1<', page)
            self.assertIn(b'data-review-total="today">0<', page)
            self.assertIn(b'Overdue by 1 day(s)', self.client.get(path).data)
            self.assertIn(b'Due in 1 day(s)', self.client.get(future).data)
            self.assertIn(b'timing-waiting">Waiting for applicant', self.client.get(waiting).data)
            self.assertIn(b'timing-completed">Completed', self.client.get(completed).data)
            self.save_plan(admin, path, 'High', '2026-11-04')
            self.assertIn(b'data-review-total="today">1<', reviewer.get('/review').data)
        # Date-dependent labels update on request, without generating another notification.
        with self.db() as db:
            notice_count = db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0]
        with patch('app.local_today', return_value=date(2026, 11, 5)):
            self.assertIn(b'Overdue by 1 day(s)', self.client.get(path).data)
            self.assertIn(b'data-review-total="today">1<', reviewer.get('/review').data)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], notice_count)

    def test_staff_review_plan_filters_counts_and_default_priority_respect_scope(self):
        path, _, reviewer = self.review_case()
        admin = self.administrator()
        self.reviewer('planning-other@example.com')
        with self.db() as db:
            own_id = db.execute("SELECT id FROM users WHERE email='reviewer@example.com'").fetchone()[0]
            other_id = db.execute("SELECT id FROM users WHERE email='planning-other@example.com'").fetchone()[0]
        needle = self.plan_fixture('Needle Urgent Demo LLC', 'Submitted', own_id, 'Urgent', '2026-11-03')
        self.plan_fixture('Other Assigned Secret LLC', 'Under review', other_id, 'Urgent', '2026-11-03')
        private = self.plan_fixture('Private Draft Secret LLC', 'Draft', own_id, 'Urgent', '2026-11-03')
        self.plan_fixture('Unassigned Late Demo LLC', 'Submitted', None, 'High', '2026-11-03')
        self.plan_fixture('Today Demo LLC', 'Under review', own_id, 'Normal', '2026-11-04')
        self.plan_fixture('Waiting Past Demo LLC', 'Changes requested', own_id, 'Urgent', '2026-11-03')
        self.plan_fixture('Approved Past Demo LLC', 'Approved', own_id, 'Urgent', '2026-11-03')
        default = self.plan_fixture('Default Normal Demo LLC', 'Submitted', None)
        with patch('app.local_today', return_value=date(2026, 11, 4)):
            page = reviewer.get('/review').data
            self.assertIn(b'data-review-total="overdue">2<', page)
            self.assertIn(b'data-review-total="today">1<', page)
            self.assertNotIn(b'Other Assigned Secret LLC', page)
            self.assertNotIn(b'Private Draft Secret LLC', page)
            self.assertEqual(reviewer.get(private.replace('/applications/', '/review/')).status_code, 404)
            self.assertNotIn(b'Private Draft Secret LLC', reviewer.get('/reports').data)
            self.assertNotIn(b'Private Draft Secret LLC', reviewer.get('/reports.csv').data)
            filtered = reviewer.get('/review', query_string={'priority': 'Urgent', 'review_due': 'overdue',
                                                             'status': 'Submitted', 'q': 'nEeDlE'}).data
            self.assertIn(b'Needle Urgent Demo LLC', filtered)
            self.assertNotIn(b'Unassigned Late Demo LLC', filtered)
            self.assertIn(b'data-review-total="overdue">2<', filtered)
            self.assertIn(b'data-review-total="overdue">3<', admin.get('/admin').data)
            for query in ('priority=Normal&review_due=no-target', 'review_due=no-target'):
                data = reviewer.get('/review?' + query).data
                self.assertIn(b'Default Normal Demo LLC', data)
                self.assertNotIn(b'Approved Past Demo LLC', data)
                self.assertNotIn(b'Waiting Past Demo LLC', data)
            self.assertNotIn(b'Needle Urgent Demo LLC', reviewer.get('/review?status=Approved&review_due=overdue').data)
        for client, endpoint in ((reviewer, '/review'), (admin, '/admin')):
            self.assertEqual(client.get(endpoint + '?priority=Critical').status_code, 400)
            self.assertEqual(client.get(endpoint + '?review_due=invalid').status_code, 400)
        self.assertNotIn(b'data-review-total=', self.client.get('/dashboard').data)
        self.assertEqual(self.client.get('/dashboard?priority=Urgent').status_code, 400)
        self.assertEqual(self.client.get('/dashboard?review_due=overdue').status_code, 400)

    def test_staff_queue_orders_active_priority_then_target_date_without_changing_owner_order(self):
        path, _, reviewer = self.review_case()
        self.administrator()
        with self.db() as db:
            own_id = db.execute("SELECT id FROM users WHERE role='officer'").fetchone()[0]
        self.plan_fixture('Urgent Later Sort LLC', 'Submitted', own_id, 'Urgent', '2026-11-10')
        self.plan_fixture('Urgent Earlier Sort LLC', 'Under review', own_id, 'Urgent', '2026-11-06')
        self.plan_fixture('Urgent Undated Sort LLC', 'Submitted', own_id, 'Urgent')
        self.plan_fixture('High Sort LLC', 'Submitted', own_id, 'High', '2026-11-01')
        self.plan_fixture('Normal Sort LLC', 'Submitted', own_id, 'Normal', '2026-10-01')
        self.plan_fixture('Waiting Urgent Sort LLC', 'Changes requested', own_id, 'Urgent', '2026-09-01')
        last = self.plan_fixture('Completed Urgent Sort LLC', 'Approved', own_id, 'Urgent', '2026-08-01')
        data = reviewer.get('/review').data
        names = ['Urgent Earlier Sort LLC', 'Urgent Later Sort LLC', 'Urgent Undated Sort LLC',
                 'High Sort LLC', 'Normal Sort LLC', 'Waiting Urgent Sort LLC', 'Completed Urgent Sort LLC']
        positions = [data.index(name.encode()) for name in names]
        self.assertEqual(positions, sorted(positions))
        owner_data = self.client.get('/dashboard').data
        self.assertLess(owner_data.index(b'Completed Urgent Sort LLC'), owner_data.index(b'Urgent Earlier Sort LLC'))

    def test_review_plan_permissions_csrf_validation_and_stale_forms(self):
        path, case, reviewer = self.review_case()
        admin = self.administrator()
        reference = path.rsplit('/', 1)[1]
        target = f'/admin/applications/{reference}/plan'
        revision = self.admin_revision(admin, reference)
        fields = {'revision': revision, 'priority': 'Urgent', 'target_date': '2026-11-04'}
        for client in (self.client, reviewer):
            self.assertEqual(self.post(target, fields, client).status_code, 403)
        self.assertEqual(admin.post(target, data=fields).status_code, 400)
        self.assertEqual(self.post(target, fields, self.app.test_client()).status_code, 302)
        for priority, due in [('Critical', ''), ('High', '2026-02-30'), ('High', 'not-a-date'),
                              ('High', '20261104'), ('High', '2026-W45-3')]:
            self.assertEqual(self.post(target, {**fields, 'priority': priority, 'target_date': due}, admin).status_code, 400)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_plans').fetchone()[0], 0)
        old_review_revision = self.review_revision(reviewer, case)
        self.post(path + '/messages', self.message_fields(self.client, path, 'Planning test question.'))
        self.assertEqual(self.post(target, fields, admin).status_code, 409)
        self.save_plan(admin, path, 'Urgent', '2026-11-04')
        self.assertEqual(self.post(case + '/checklist', {'revision': old_review_revision, 'checks': []}, reviewer).status_code, 409)
        # The administration route never opens an applicant's private draft.
        draft = self.post('/applications/new', self.values).location
        draft_reference = draft.rsplit('/', 1)[1]
        self.assertEqual(self.post(f'/admin/applications/{draft_reference}/plan', fields, admin).status_code, 404)

    def test_review_plan_survives_corrections_reassignment_and_finishes_without_renewal_inheritance(self):
        path, case, reviewer = self.review_case()
        admin = self.administrator()
        self.save_plan(admin, path, 'Urgent', '2026-11-03')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'request-changes', 'note': 'Correct the sample contact.'}, reviewer)
        with patch('app.local_today', return_value=date(2026, 11, 4)):
            self.assertIn(b'data-review-total="overdue">0<', reviewer.get('/review').data)
            self.assertIn(b'timing-waiting">Waiting for applicant', self.client.get(path).data)
        self.save_plan(admin, path, 'High', '2026-11-06')
        self.post(path + '/edit', {**self.values, 'contact_name': 'Corrected Demo Contact'})
        self.post(path + '/submit')
        with self.db() as db:
            plan_before = dict(db.execute('SELECT * FROM review_plans').fetchone())
        second = self.reviewer('planning-reassignment@example.com')
        with self.db() as db:
            second_id = db.execute("SELECT id FROM users WHERE email='planning-reassignment@example.com'").fetchone()[0]
        reference = path.rsplit('/', 1)[1]
        self.post(f'/admin/applications/{reference}/assign', {'revision': self.admin_revision(admin, reference),
                  'reviewer_id': second_id, 'note': 'Keep the case target for the new reviewer.'}, admin)
        with self.db() as db:
            self.assertEqual(dict(db.execute('SELECT * FROM review_plans').fetchone()), plan_before)
        self.assertEqual(reviewer.get(case).status_code, 404)
        self.assertIn(b'priority-high', second.get(case).data)
        self.post(case, {'revision': self.review_revision(second, case), 'action': 'start'}, second)
        self.save_checklist(second, case)
        self.post(case, {'revision': self.review_revision(second, case), 'action': 'approve'}, second)
        self.assertEqual(self.draft()['status'], 'Approved')
        self.assertIn(b'timing-completed">Completed', self.client.get(path).data)
        with self.db() as db:
            latest = db.execute('SELECT MAX(id) FROM application_events WHERE application_id=?', (self.draft()['id'],)).fetchone()[0]
        self.assertEqual(self.post(f'/admin/applications/{reference}/plan', {'revision': latest, 'priority': 'Urgent', 'target_date': ''}, admin).status_code, 400)
        renewal = self.post(path + '/renew').location.removesuffix('/edit')
        with self.db() as db:
            renewal_id = db.execute('SELECT id FROM applications WHERE reference=?', (renewal.rsplit('/', 1)[1],)).fetchone()[0]
            self.assertIsNone(db.execute('SELECT * FROM review_plans WHERE application_id=?', (renewal_id,)).fetchone())
            self.assertEqual(dict(db.execute('SELECT * FROM review_plans').fetchone()), plan_before)


    def test_supplier_directory_is_admin_only_and_excludes_non_approvals(self):
        path = self.make_draft()
        reviewer = self.reviewer()
        admin = self.administrator()
        directory = '/admin/suppliers'
        for client in (self.client, reviewer):
            self.assertEqual(client.get(directory).status_code, 403)
            self.assertNotIn(b'href="/admin/suppliers"', client.get('/').data)
        self.assertEqual(self.app.test_client().get(directory).location, '/login')
        self.assertIn(b'No approved suppliers yet.', admin.get(directory).data)
        for status in ('Submitted', 'Under review', 'Changes requested', 'Rejected'):
            self.plan_fixture(status + ' Supplier LLC', status, None)
        active = self.plan_fixture('Approved Supplier LLC', 'Approved', None)
        with self.db() as db:
            revision = db.execute('SELECT COUNT(*) FROM application_events').fetchone()[0]
        data = admin.get(directory).data
        self.assertIn(b'data-licence-total="all">1<', data)
        self.assertIn(b'Approved Supplier LLC', data)
        self.assertIn(('/admin' + active).encode(), data)
        self.assertNotIn(b'supplier@example.com', data)
        for status in ('Submitted', 'Under review', 'Changes requested', 'Rejected'):
            self.assertNotIn((status + ' Supplier LLC').encode(), data)
        self.assertNotIn(path.split('/')[-1].encode(), data)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM application_events').fetchone()[0], revision)

    def test_supplier_directory_expiry_boundaries_and_combined_literal_filters(self):
        self.make_draft()
        admin = self.administrator()
        dates = {'Expired Example LLC': '2026-11-10', 'Due Today LLC': '2026-11-11',
                 'Élan 100%_ Demo LLC': '2026-12-11', 'Valid Example LLC': '2026-12-12',
                 'Élan 100X Demo LLC': '2026-12-11'}
        for name, expiry in dates.items():
            path = self.plan_fixture(name, 'Approved', None)
            with self.db() as db:
                db.execute('UPDATE applications SET licence_expiry=?,category=? WHERE reference=?',
                           (expiry, 'IT services' if name.startswith('Élan') else 'Office supplies', path.split('/')[-1]))
        directory = '/admin/suppliers'
        with patch('app.local_today', return_value=date(2026, 11, 11)):
            full = admin.get(directory).data
            self.assertIn(b'data-licence-total="expired">1<', full)
            self.assertIn(b'data-licence-total="expiring">3<', full)
            self.assertIn(b'data-licence-total="valid">1<', full)
            self.assertIn(b'Expires today', full)
            filtered = admin.get(directory, query_string={'q': 'élan 100%_', 'category': 'IT services',
                                                           'licence': 'expiring'}).data
            self.assertIn('Élan 100%_ Demo LLC'.encode(), filtered)
            self.assertNotIn('Élan 100X Demo LLC'.encode(), filtered)
            self.assertIn(b'1 of 5 shown', filtered)
            self.assertIn(b'data-licence-total="expiring">3<', filtered)
            empty = admin.get(directory, query_string={'category': 'IT services', 'licence': 'valid'}).data
            self.assertIn(b'No suppliers match.', empty)
            for query in ({'category': 'unlisted'}, {'licence': 'unlisted'}, {'q': 'x' * 121}):
                self.assertEqual(admin.get(directory, query_string=query).status_code, 400)

    def test_supplier_directory_replaces_approval_only_after_renewal_is_approved(self):
        path, reviewer = self.approved_case()
        admin = self.administrator()
        directory = '/admin/suppliers'
        original = path.split('/')[-1].encode()

        def check_listing(present, absent):
            page = admin.get(directory).data
            self.assertIn(b'data-licence-total="all">1<', page)
            self.assertIn(present, page)
            self.assertNotIn(absent, page)

        def start_renewal(parent, expiry):
            edit = self.post(parent + '/renew').location
            renewal = edit.removesuffix('/edit')
            self.post(edit, {**self.values, 'licence_expiry': expiry})
            self.attach(renewal)
            self.attach(renewal, 'profile', PROFILE, 'sample-company-profile.pdf')
            self.post(renewal + '/submit')
            case = renewal.replace('/applications/', '/review/')
            self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
            return renewal, case, renewal.split('/')[-1].encode()

        first, case, rejected = start_renewal(path, '2028-12-31')
        check_listing(original, rejected)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'reject',
                         'note': 'Fictional renewal declined.'}, reviewer)
        check_listing(original, rejected)
        latest, case, approved = start_renewal(path, '2029-12-31')
        check_listing(original, approved)
        self.save_checklist(reviewer, case)
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'approve'}, reviewer)
        check_listing(approved, original)
        self.assertEqual(admin.get('/admin' + path + '/summary').status_code, 200)
        self.assertIn(approved, admin.get(directory, query_string={'q': approved.decode().lower()}).data)
        self.assertIn(b'No suppliers match.', admin.get(directory, query_string={'q': original.decode()}).data)

    def test_workload_is_admin_only_and_includes_idle_reviewers(self):
        self.make_draft()
        reviewer = self.reviewer()
        admin = self.administrator()
        route = '/admin/workload'
        self.assertEqual(self.app.test_client().get(route).location, '/login')
        for client in (self.client, reviewer):
            self.assertEqual(client.get(route).status_code, 403)
            self.assertNotIn(b'href="/admin/workload"', client.get('/').data)
        data = admin.get(route).data
        self.assertIn(b'data-workload-total="open">0<', data)
        self.assertIn(b'data-workload-total="unassigned">0<', data)
        self.assertIn(b'data-workload-row="unassigned"', data)
        self.assertIn(b'reviewer@example.com', data)
        self.assertEqual(data.count(b'data-count="open">0<'), 2)

    def test_workload_counts_and_drilldowns_match_active_cases_and_dates(self):
        self.make_draft()
        self.reviewer()
        self.reviewer('reviewer2@example.com')
        admin = self.administrator()
        with self.db() as db:
            first, second = [row[0] for row in db.execute("SELECT id FROM users WHERE role='officer' ORDER BY id")]
            admin_id = db.execute("SELECT id FROM users WHERE role='administrator'").fetchone()[0]
        fixtures = [
            ('First Submitted Demo', 'Submitted', first, 'Urgent', '2026-11-10'),
            ('First Reviewing Demo', 'Under review', first, 'Normal', '2026-11-11'),
            ('First Waiting Demo', 'Changes requested', first, 'Normal', '2026-11-09'),
            ('First Approved Demo', 'Approved', first, 'Normal', '2026-11-10'),
            ('First Rejected Demo', 'Rejected', first, 'Normal', '2026-11-11'),
            ('Second Future Demo', 'Under review', second, 'Normal', '2026-11-12'),
            ('Second Undated Demo', 'Submitted', second, 'Normal', None),
            ('Unassigned Late Demo', 'Submitted', None, 'Normal', '2026-11-10'),
            ('Unassigned Today Demo', 'Submitted', None, 'Normal', '2026-11-11'),
        ]
        for values in fixtures:
            self.plan_fixture(*values)
        with self.db() as db:
            before = list(db.iterdump())
        with patch('app.local_today', return_value=date(2026, 11, 11)):
            page = admin.get('/admin/workload').data
            for key, expected in (('open', 7), ('unassigned', 2), ('overdue', 2), ('today', 2)):
                self.assertIn(f'data-workload-total="{key}">{expected}<'.encode(), page)
            row = re.search(fr'data-workload-row="{first}">(.*?)</tr>'.encode(), page, re.S)[1]
            for key, expected in (('open', 3), ('submitted', 1), ('reviewing', 1), ('waiting', 1), ('overdue', 1), ('today', 1)):
                self.assertIn(f'data-count="{key}">{expected}<'.encode(), row)
            open_cases = admin.get('/admin', query_string={'reviewer': first, 'status': 'Open'}).data
            for label in ('First Submitted Demo', 'First Reviewing Demo', 'First Waiting Demo'):
                self.assertIn(label.encode(), open_cases)
            for label in ('First Approved Demo', 'First Rejected Demo', 'Second Future Demo', 'Unassigned Late Demo'):
                self.assertNotIn(label.encode(), open_cases)
            self.assertIn(b'3 of 5 shown', open_cases)
            self.assertIn(f'/admin?review_due=overdue&amp;reviewer={first}'.encode(), open_cases)
            overdue = admin.get('/admin', query_string={'reviewer': first, 'review_due': 'overdue',
                                                       'priority': 'Urgent', 'q': 'Submitted'}).data
            self.assertIn(b'First Submitted Demo', overdue)
            self.assertNotIn(b'First Waiting Demo', overdue)
            self.assertNotIn(b'Unassigned Late Demo', overdue)
            unassigned = admin.get('/admin', query_string={'reviewer': 'unassigned', 'review_due': 'today'}).data
            self.assertIn(b'Unassigned Today Demo', unassigned)
            self.assertNotIn(b'Unassigned Late Demo', unassigned)
            self.assertNotIn(b'First Reviewing Demo', unassigned)
        for selection in ('missing', str(admin_id), '9999999999999999999999999'):
            self.assertEqual(admin.get('/admin', query_string={'reviewer': selection}).status_code, 400)
        with self.db() as db:
            self.assertEqual(list(db.iterdump()), before)

    def test_workload_updates_after_reassignment_and_approval(self):
        path, case, _ = self.review_case()
        second_reviewer = self.reviewer('reviewer2@example.com')
        admin = self.administrator()
        ref = path.split('/')[-1]
        with self.db() as db:
            first, second = [row[0] for row in db.execute("SELECT id FROM users WHERE role='officer' ORDER BY id")]

        def open_count(reviewer_id):
            page = admin.get('/admin/workload').data
            row = re.search(fr'data-workload-row="{reviewer_id}">(.*?)</tr>'.encode(), page, re.S)[1]
            return int(re.search(rb'data-count="open">(\d+)<', row)[1])

        self.assertEqual((open_count(first), open_count(second)), (1, 0))
        result = self.post('/admin' + path + '/assign', {'reviewer_id': second, 'note': 'Balance the demo queue.',
                                                        'revision': self.admin_revision(admin, ref)}, admin)
        self.assertEqual(result.status_code, 303)
        self.assertEqual((open_count(first), open_count(second)), (0, 1))
        self.post(case, {'revision': self.review_revision(second_reviewer, case), 'action': 'start'}, second_reviewer)
        self.save_checklist(second_reviewer, case)
        self.post(case, {'revision': self.review_revision(second_reviewer, case), 'action': 'approve'}, second_reviewer)
        self.assertEqual(self.draft()['status'], 'Approved')
        self.assertEqual(open_count(second), 0)
        self.assertIn(ref.encode(), admin.get('/admin/suppliers').data)

    def test_activity_is_admin_only_and_private_drafts_stay_hidden(self):
        path = self.make_draft(company_name='Demo Activity Supplier')
        private = self.plan_fixture('Never Submitted Demo', 'Draft', None)
        reviewer = self.reviewer()
        admin = self.administrator()
        route = '/admin/activity'
        self.assertEqual(self.app.test_client().get(route).location, '/login')
        for client in (self.client, reviewer):
            self.assertEqual(client.get(route).status_code, 403)
            self.assertNotIn(b'href="/admin/activity"', client.get('/').data)
        self.assertIn(b'No activity found.', admin.get(route).data)
        self.attach(path)
        self.attach(path, 'profile', PROFILE, 'sample-company-profile.pdf')
        self.post(path + '/submit')
        case = path.replace('/applications/', '/review/')
        self.post(case, {'revision': self.review_revision(reviewer, case), 'action': 'start'}, reviewer)
        self.save_plan(admin, path, 'High')
        with self.db() as db:
            before = list(db.iterdump())
        data = admin.get(route).data
        self.assertIn(b'Application submitted for demo review', data)
        self.assertIn(b'Administrator updated review plan', data)
        self.assertIn(b'admin@example.com', data)
        self.assertIn(b'reviewer@example.com', data)
        self.assertIn(('href="/admin' + path + '"').encode(), data)
        self.assertNotIn(b'Never Submitted Demo', data)
        self.assertNotIn(private.split('/')[-1].encode(), data)
        self.assertNotIn(b'applicant@example.com', data)
        self.assertIn(b'No activity found.', admin.get(route, query_string={'q': 'applicant@example.com'}).data)
        with self.db() as db:
            self.assertEqual(list(db.iterdump()), before)

    def test_activity_filters_use_inclusive_dubai_dates_and_escape_recorded_text(self):
        path = self.make_draft()
        self.reviewer()
        admin = self.administrator()
        with self.db() as db:
            db.execute("UPDATE applications SET status='Submitted' WHERE reference=?", (path.split('/')[-1],))
            item = db.execute('SELECT id,user_id FROM applications').fetchone()
            reviewer = db.execute("SELECT id FROM users WHERE role='officer'").fetchone()[0]
            db.executemany('INSERT INTO application_events(application_id,actor_id,description,created_at) VALUES (?,?,?,?)', [
                (item['id'], reviewer, 'Previous day 100%_', '2026-11-10T23:59:59+04:00'),
                (item['id'], reviewer, 'Start 100%_ <b>demo</b>', '2026-11-11T00:00:00+04:00'),
                (item['id'], reviewer, 'End 100%_', '2026-11-11T23:59:59+04:00'),
                (item['id'], item['user_id'], 'Wrong actor 100%_', '2026-11-11T12:00:00+04:00'),
                (item['id'], reviewer, 'Similar plain text 100XX', '2026-11-11T12:00:00+04:00'),
                (item['id'], reviewer, 'Next day 100%_', '2026-11-12T00:00:00+04:00'),
            ])
        route = '/admin/activity'
        filters = {'role': 'officer', 'from_date': '2026-11-11', 'to_date': '2026-11-11', 'q': '100%_'}
        data = admin.get(route, query_string=filters).data
        self.assertIn(b'Start 100%_ &lt;b&gt;demo&lt;/b&gt;', data)
        self.assertIn(b'End 100%_', data)
        self.assertLess(data.index(b'End 100%_'), data.index(b'Start 100%_'))
        for label in (b'Previous day', b'Wrong actor', b'Similar plain text', b'Next day', b'<b>demo</b>'):
            self.assertNotIn(label, data)
        filters['q'] = 'REVIEWER@EXAMPLE.COM'
        data = admin.get(route, query_string=filters).data
        self.assertIn(b'Similar plain text 100XX', data)
        self.assertNotIn(b'Wrong actor', data)
        for invalid in ({'role': 'other'}, {'q': 'x' * 121}, {'from_date': '2026-99-01'},
                        {'from_date': '2026-11-12', 'to_date': '2026-11-11'}, {'page': 'word'}, {'page': 0}):
            self.assertEqual(admin.get(route, query_string=invalid).status_code, 400)

    def test_activity_pages_are_stable_and_links_keep_the_filters(self):
        path = self.make_draft()
        self.reviewer()
        admin = self.administrator()
        with self.db() as db:
            db.execute("UPDATE applications SET status='Submitted' WHERE reference=?", (path.split('/')[-1],))
            app_id = db.execute('SELECT id FROM applications').fetchone()[0]
            reviewer = db.execute("SELECT id FROM users WHERE role='officer'").fetchone()[0]
            db.executemany('INSERT INTO application_events(application_id,actor_id,description,created_at) VALUES (?,?,?,?)',
                           [(app_id, reviewer, f'Timeline demo {i:02}', '2026-11-11T12:00:00+04:00') for i in range(1, 28)])
        filters = {'q': 'Timeline demo', 'role': 'officer', 'from_date': '2026-11-11', 'to_date': '2026-11-11'}
        route = '/admin/activity'
        page = admin.get(route, query_string=filters)
        self.assertEqual(page.status_code, 200)
        expected = [f'{i:02}'.encode() for i in range(27, 0, -1)]
        self.assertEqual(re.findall(rb'Timeline demo (\d\d)', page.data), expected[:25])
        next_link = re.search(r'href="([^"]+)"[^>]*>Next', page.get_data(as_text=True))[1]
        next_page = admin.get(unescape(next_link))
        self.assertEqual(next_page.status_code, 200)
        self.assertIn(b'Page 2 of 2', next_page.data)
        self.assertIn(b'role=officer', next_page.data)
        self.assertIn(b'from_date=2026-11-11', next_page.data)
        self.assertEqual(re.findall(rb'Timeline demo (\d\d)', next_page.data), expected[25:])
        self.assertEqual(admin.get(route, query_string={**filters, 'page': 3}).status_code, 404)


    def test_renewal_comparison_shows_saved_changes_without_altering_records(self):
        original, _ = self.approved_case()
        ref = original.split('/')[-1]
        self.assertEqual(self.client.get(original + '/renewal-comparison').status_code, 404)
        self.assertNotIn(b'Compare renewal details', self.client.get(original).data)
        edit = self.post(original + '/renew').location
        renewal = edit.removesuffix('/edit')
        route = renewal + '/renewal-comparison'
        first = self.client.get(route)
        self.assertEqual(first.status_code, 200)
        self.assertIn(b'0 of 4 fields changed', first.data)
        self.assertIn(b'Choose a sample licence expiry later than 2027-12-31', first.data)
        self.assertIn(b'Compare renewal details', self.client.get(renewal).data)
        result = self.post(edit, {**self.values, 'company_name': 'Demo Supplies <b>Renewed</b>',
                                  'category': 'IT services', 'licence_expiry': '2028-12-31'})
        self.assertEqual(result.status_code, 303)
        with self.db() as db:
            before = list(db.iterdump())
        page = self.client.get(route).data
        self.assertIn(b'3 of 4 fields changed', page)
        for text in (b'Demo Supplies LLC', b'Demo Supplies &lt;b&gt;Renewed&lt;/b&gt;', b'Office supplies',
                     b'IT services', b'2027-12-31', b'2028-12-31', b'Unchanged', ref.encode()):
            self.assertIn(text, page)
        self.assertNotIn(b'<b>Renewed</b>', page)
        self.assertNotIn(b'Choose a sample licence expiry later than', page)
        self.assertNotIn(b'supplier@example.com', page)
        with self.db() as db:
            self.assertEqual(list(db.iterdump()), before)
            self.assertEqual(db.execute('SELECT company_name FROM applications WHERE reference=?', (ref,)).fetchone()[0],
                             self.values['company_name'])

    def test_renewal_comparison_respects_current_case_access_and_prior_privacy(self):
        original, previous_reviewer = self.approved_case()
        admin = self.administrator()
        new_reviewer = self.reviewer('renewal-reviewer@example.com')
        other_owner = self.app.test_client()
        self.register('other-owner@example.com', other_owner)
        edit = self.post(original + '/renew').location
        renewal = edit.removesuffix('/edit')
        route = renewal + '/renewal-comparison'
        self.assertEqual(self.app.test_client().get(route).location, '/login')
        for client in (admin, new_reviewer, other_owner):
            self.assertEqual(client.get(route).status_code, 404)
        self.post(edit, {**self.values, 'licence_expiry': '2028-12-31'})
        self.attach(renewal)
        self.attach(renewal, 'profile', PROFILE, 'sample-company-profile.pdf')
        self.post(renewal + '/submit')
        with self.db() as db:
            reviewer_id = db.execute("SELECT id FROM users WHERE email='renewal-reviewer@example.com'").fetchone()[0]
        ref = renewal.split('/')[-1]
        assignment = self.post('/admin' + renewal + '/assign', {'reviewer_id': reviewer_id,
                                'revision': self.admin_revision(admin, ref)}, admin)
        self.assertEqual(assignment.status_code, 303)
        case = renewal.replace('/applications/', '/review/')
        for client, back in ((new_reviewer, case), (admin, '/admin' + renewal), (self.client, renewal)):
            data = client.get(route)
            self.assertEqual(data.status_code, 200)
            self.assertIn(('href="' + back + '"').encode(), data.data)
            self.assertIn(b'1 of 4 fields changed', data.data)
            self.assertNotIn(b'supplier@example.com', data.data)
            self.assertNotIn(b'sample-company-profile.pdf', data.data)
        self.assertIn(b'Compare renewal details', new_reviewer.get(case).data)
        self.assertEqual(previous_reviewer.get(route).status_code, 404)
        self.assertEqual(other_owner.get(route).status_code, 404)
        old_case = original.replace('/applications/', '/review/')
        self.assertEqual(new_reviewer.get(old_case + '/documents/licence').status_code, 404)
        # The comparison refuses an inconsistent imported link to another applicant.
        with self.db() as db:
            owner_id = db.execute("SELECT id FROM users WHERE email='other-owner@example.com'").fetchone()[0]
            db.execute('UPDATE applications SET user_id=? WHERE reference=?', (owner_id, original.split('/')[-1]))
        self.assertEqual(new_reviewer.get(route).status_code, 404)
        self.assertEqual(admin.get(route).status_code, 404)


if __name__ == '__main__':
    unittest.main()
