"""GovVendor: supplier registrations, sample documents and demo review.

All records are fictional demonstration data. See START_HERE.md before running.
"""
import os
import csv
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from io import BytesIO, StringIO
from pathlib import Path

import click
from flask import (
    Flask, abort, current_app, flash, g, redirect,
    render_template, request, send_file, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
APP_VERSION = '1.0'
DUBAI = timezone(timedelta(hours=4))
CATEGORIES = ('Office supplies', 'IT services', 'Maintenance services', 'Cleaning services', 'Other')
SUPPLIER_LICENCE_STATES = {'valid': 'Valid', 'expiring': 'Expiring soon', 'expired': 'Expired'}
ACTIVITY_ROLES = {'applicant': 'Applicant', 'officer': 'Reviewer', 'administrator': 'Administrator'}
ACTIVITY_PAGE_SIZE = 25
EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
DOCUMENTS = {'licence': 'Sample trade licence', 'profile': 'Sample company profile'}
MAX_PDF_BYTES = 2 * 1024 * 1024
REVIEW_PRIORITIES = ('Normal', 'High', 'Urgent')
REVIEW_TIMING_FILTERS = {'overdue': 'Overdue', 'today': 'Due today', 'upcoming': 'Upcoming', 'no-target': 'No target date'}
ACTIVE_REVIEW_STATUSES = ('Submitted', 'Under review')
OPEN_REVIEW_SQL = "a.status IN ('Submitted', 'Under review', 'Changes requested')"
MESSAGE_MAX_CHARS = 1500
MESSAGE_STATUSES = ('Submitted', 'Under review', 'Changes requested')
REVIEW_CHECKS = {
    'company_details': 'Company and contact details checked',
    'licence_expiry': 'Sample licence expiry checked',
    'licence_document': 'Sample trade licence PDF checked',
    'company_profile': 'Sample company profile PDF checked',
}
EDITABLE_STATUSES = ('Draft', 'Changes requested')
REVIEW_DECISIONS = {'request-changes': 'Changes requested', 'approve': 'Approved', 'reject': 'Rejected'}
STATUSES = ('Draft', 'Submitted', 'Under review', 'Changes requested', 'Approved', 'Rejected')


def now():
    return datetime.now(DUBAI).isoformat(timespec='seconds')


def local_today():
    return datetime.now(DUBAI).date()


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def login_required(view):
    @wraps(view)
    def protected(*args, **kwargs):
        if g.user is None:
            flash('Please sign in to open your workspace.', 'info')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return protected


def role_required(role):
    def decorate(view):
        @wraps(view)
        @login_required
        def protected(*args, **kwargs):
            if g.user['role'] != role:
                abort(403, description='This page is for a different GovVendor role.')
            return view(*args, **kwargs)
        return protected
    return decorate


def owned_application(reference):
    # Only fetch a record belonging to the signed-in user, even if its URL is known.
    row = get_db().execute('SELECT * FROM applications WHERE reference=? AND user_id=?',
                           (reference, g.user['id'])).fetchone()
    if row is None:
        abort(404)
    return row


def reviewable_application(reference):
    # Reviewers may see unassigned submissions and their own assigned cases.
    row = get_db().execute('''SELECT a.*, r.reviewer_id, r.note
        FROM applications a LEFT JOIN application_reviews r ON a.id=r.application_id
        WHERE a.reference=? AND a.status<>'Draft' AND (r.reviewer_id=? OR
          (r.reviewer_id IS NULL AND a.status='Submitted'))''',
                           (reference, g.user['id'])).fetchone()
    if row is None:
        abort(404)
    return row


def admin_application(reference):
    row = get_db().execute('''SELECT a.*,r.reviewer_id,assigned.name AS reviewer_name
        FROM applications a LEFT JOIN application_reviews r ON r.application_id=a.id
        LEFT JOIN users assigned ON assigned.id=r.reviewer_id
        WHERE a.reference=? AND a.status<>'Draft' ''', (reference,)).fetchone()
    if row is None:
        abort(404)
    return row


def accessible_application(reference):
    if g.user['role'] == 'applicant':
        return owned_application(reference)
    if g.user['role'] == 'officer':
        return reviewable_application(reference)
    if g.user['role'] == 'administrator':
        return admin_application(reference)
    abort(403)


def reviewer_accounts():
    return get_db().execute("SELECT id,name,email FROM users WHERE role='officer' ORDER BY name,id").fetchall()


def workspace_endpoint(role):
    return {'officer': 'review_queue', 'administrator': 'admin_dashboard'}.get(role, 'dashboard')


def application_events(application_id):
    return get_db().execute('SELECT * FROM application_events WHERE application_id=? ORDER BY id DESC',
                            (application_id,)).fetchall()


def record_event(application_id, description, timestamp, recipients=()):
    db = get_db()
    event = db.execute('INSERT INTO application_events(application_id,actor_id,description,created_at) VALUES (?,?,?,?)',
                       (application_id, g.user['id'], description, timestamp))
    recipient_ids = set(recipients) - {None, g.user['id']}
    db.executemany('INSERT OR IGNORE INTO notifications(user_id,event_id) VALUES (?,?)',
                   [(user_id, event.lastrowid) for user_id in recipient_ids])
    return event.lastrowid


def submission_recipients(application_id):
    assigned = get_db().execute('SELECT reviewer_id FROM application_reviews WHERE application_id=?',
                                 (application_id,)).fetchone()
    rows = get_db().execute("""SELECT id FROM users WHERE role='administrator' OR
        (role='officer' AND (:assigned IS NULL OR id=:assigned))""",
        {'assigned': assigned['reviewer_id'] if assigned else None}).fetchall()
    return [row['id'] for row in rows]


def notification_target(row):
    role = g.user['role']
    endpoint = None
    if role == 'applicant' and row['owner_id'] == g.user['id']:
        endpoint = 'application_detail'
    elif role == 'administrator' and row['status'] != 'Draft':
        endpoint = 'admin_detail'
    elif role == 'officer' and row['status'] != 'Draft' and (row['reviewer_id'] == g.user['id'] or
                               (row['reviewer_id'] is None and row['status'] == 'Submitted')):
        endpoint = 'review_detail'
    if endpoint:
        if row['is_message']:
            endpoint = 'application_messages'
        return url_for(endpoint, reference=row['reference'])
    return None


def owned_notification(notification_id):
    if notification_id > 9223372036854775807:
        abort(404)
    row = get_db().execute('''SELECT n.id,n.read_at,e.description,e.created_at,
        a.reference,a.status,a.user_id AS owner_id,r.reviewer_id,
        EXISTS(SELECT 1 FROM application_messages m WHERE m.event_id=e.id) AS is_message
        FROM notifications n JOIN application_events e ON e.id=n.event_id
        JOIN applications a ON a.id=e.application_id
        LEFT JOIN application_reviews r ON r.application_id=a.id
        WHERE n.id=? AND n.user_id=?''', (notification_id, g.user['id'])).fetchone()
    if row is None:
        abort(404)
    return row


def attached_documents(application_id):
    return {row['kind']: row for row in get_db().execute(
        '''SELECT d.kind,d.filename,d.uploaded_at,
           (SELECT MAX(v.version) FROM document_versions v
            WHERE v.application_id=d.application_id AND v.kind=d.kind) AS version
           FROM application_documents d WHERE d.application_id=?''', (application_id,))}



def review_checklist(application_id):
    row = get_db().execute('SELECT * FROM review_checklists WHERE application_id=?',
                           (application_id,)).fetchone()
    return row


def checklist_complete(application_id, reviewer_id):
    row = review_checklist(application_id)
    return row is not None and row['reviewer_id'] == reviewer_id and all(row[key] for key in REVIEW_CHECKS)


def renewal_parent(application_id):
    # Limited prior details give the reviewer context without exposing another case.
    return get_db().execute('''SELECT a.reference,a.licence_expiry FROM application_renewals n
        JOIN applications a ON a.id=n.previous_id WHERE n.application_id=?''', (application_id,)).fetchone()


def existing_renewal(application_id):
    return get_db().execute('''SELECT a.reference,a.status FROM application_renewals n
        JOIN applications a ON a.id=n.application_id
        WHERE n.previous_id=? AND a.status<>'Rejected' ORDER BY a.id DESC LIMIT 1''', (application_id,)).fetchone()


def expiry_reminders():
    """Current approved records due within 30 days; historical approvals remain saved."""
    rows = get_db().execute('''SELECT a.id,a.reference,a.company_name,a.licence_expiry FROM applications a
        WHERE a.user_id=? AND a.status='Approved' AND a.licence_expiry<=?
        AND NOT EXISTS (SELECT 1 FROM application_renewals n JOIN applications newer ON newer.id=n.application_id
                        WHERE n.previous_id=a.id AND newer.status='Approved')
        ORDER BY a.licence_expiry,a.id''',
        (g.user['id'], (local_today() + timedelta(days=30)).isoformat())).fetchall()
    return [{'application': row, 'days': (date.fromisoformat(row['licence_expiry']) - local_today()).days,
             'renewal': existing_renewal(row['id'])} for row in rows]



def describe_review_plan(status, priority='Normal', target_date=None):
    days = (date.fromisoformat(target_date) - local_today()).days if target_date else None
    if status == 'Draft':
        timing, label = 'draft', 'Not submitted'
    elif status in ('Approved', 'Rejected'):
        timing, label = 'completed', 'Completed'
    elif status == 'Changes requested':
        timing, label = 'waiting', 'Waiting for applicant'
    elif target_date is None:
        timing, label = 'no-target', 'No target date'
    elif days < 0:
        timing, label = 'overdue', f'Overdue by {-days} day(s)'
    elif days == 0:
        timing, label = 'today', 'Due today'
    else:
        timing, label = 'upcoming', f'Due in {days} day(s)'
    return {'priority': priority, 'target_date': target_date, 'timing': timing, 'label': label}


def review_plan(application):
    row = get_db().execute('SELECT priority,target_date FROM review_plans WHERE application_id=?',
                           (application['id'],)).fetchone()
    return describe_review_plan(application['status'], row['priority'] if row else 'Normal',
                                row['target_date'] if row else None)


def application_list(scope, parameters, statuses):
    """Apply list filters inside a fixed permission scope; counts use the full scope."""
    query = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    open_only = status == 'Open' and g.user['role'] == 'administrator'
    staff = g.user['role'] in ('officer', 'administrator')
    priority = request.args.get('priority', '')
    review_due = request.args.get('review_due', '')
    if (priority and (not staff or priority not in REVIEW_PRIORITIES)) or (review_due and (not staff or review_due not in REVIEW_TIMING_FILTERS)):
        abort(400, description='Choose a listed review priority and review timing filter.')
    if len(query) > 120 or (status and status not in statuses and not open_only):
        abort(400, description='Use a search of up to 120 characters and choose a listed status.')
    db = get_db()
    db.execute('BEGIN')
    source = '''FROM applications a LEFT JOIN application_reviews r ON a.id=r.application_id
        LEFT JOIN application_renewals n ON n.application_id=a.id
        LEFT JOIN applications previous ON previous.id=n.previous_id
        LEFT JOIN users assigned ON assigned.id=r.reviewer_id
        LEFT JOIN review_plans p ON p.application_id=a.id'''
    counts = dict.fromkeys(statuses, 0)
    for row in db.execute(f'SELECT a.status,COUNT(*) AS total {source} WHERE {scope} GROUP BY a.status', parameters):
        counts[row['status']] = row['total']
    review_totals = None
    if staff:
        totals = db.execute(f'''SELECT
            COALESCE(SUM(a.status IN ('Submitted','Under review') AND p.target_date<:today),0) AS overdue,
            COALESCE(SUM(a.status IN ('Submitted','Under review') AND p.target_date=:today),0) AS today
            {source} WHERE {scope}''', {**parameters, 'today': local_today().isoformat()}).fetchone()
        review_totals = dict(totals)
    filters = [scope]
    parameters = dict(parameters)
    if priority:
        filters.append("COALESCE(p.priority,'Normal')=:priority")
        parameters['priority'] = priority
    if review_due:
        filters.append("a.status IN ('Submitted','Under review')")
        parameters['today'] = local_today().isoformat()
        filters.append({'overdue': 'p.target_date<:today', 'today': 'p.target_date=:today',
                        'upcoming': 'p.target_date>:today', 'no-target': 'p.target_date IS NULL'}[review_due])
    if query:
        # INSTR treats %, underscores and quotes as ordinary search characters.
        filters.append('(instr(lower(a.company_name),lower(:q))>0 OR instr(lower(a.reference),lower(:q))>0)')
        parameters['q'] = query
    if open_only:
        filters.append(OPEN_REVIEW_SQL)
    elif status:
        filters.append('a.status=:status')
        parameters['status'] = status
    order = "a.updated_at DESC,a.id DESC"
    if staff:
        order = """CASE WHEN a.status IN ('Submitted','Under review') THEN 0
                    WHEN a.status='Changes requested' THEN 1 ELSE 2 END,
                   CASE COALESCE(p.priority,'Normal') WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 ELSE 2 END,
                   p.target_date IS NULL,p.target_date,a.updated_at DESC,a.id DESC"""
    rows = db.execute(f"""SELECT a.reference,a.company_name,a.category,a.status,a.updated_at,r.reviewer_id,
        previous.reference AS renewal_of,assigned.name AS reviewer_name,
        COALESCE(p.priority,'Normal') AS priority,p.target_date,
        (SELECT COALESCE(MAX(e.id),0) FROM application_events e WHERE e.application_id=a.id) AS revision
        {source} WHERE {' AND '.join(filters)} ORDER BY {order}""", parameters).fetchall()
    rows = [dict(row, plan=describe_review_plan(row['status'],row['priority'],row['target_date'])) for row in rows]
    return {'applications': rows, 'counts': counts, 'total': sum(counts.values()),
            'q': query, 'selected_status': status, 'statuses': statuses, 'staff_planning': staff,
            'priority': priority, 'review_due': review_due, 'review_totals': review_totals,
            'review_priorities': REVIEW_PRIORITIES, 'review_timing_filters': REVIEW_TIMING_FILTERS}


def approved_summary(application, reviewing):
    if application['status'] != 'Approved':
        abort(400, description='A demo approval summary is available after the application is approved.')
    review = get_db().execute('''SELECT u.name,r.note FROM application_reviews r
        JOIN users u ON u.id=r.reviewer_id WHERE r.application_id=?''', (application['id'],)).fetchone()
    return render_template('approval_summary.html', application=application, review=review,
                           documents=attached_documents(application['id']), document_types=DOCUMENTS,
                           reviewing=reviewing, generated_at=now(), renewal=renewal_parent(application['id']))


def application_report():
    """Return the same filtered, authorized rows for the report page and its export."""
    if g.user['role'] == 'officer':
        scope = "a.status<>'Draft' AND (r.reviewer_id=:user_id OR (r.reviewer_id IS NULL AND a.status='Submitted'))"
        statuses = STATUSES[1:]
    elif g.user['role'] == 'administrator':
        scope, statuses = "a.status<>'Draft'", STATUSES[1:]
    elif g.user['role'] == 'applicant':
        scope, statuses = 'a.user_id=:user_id', STATUSES
    else:
        abort(403, description='This account cannot open reports.')
    values = {key: request.args.get(key, '').strip() for key in ('q', 'status', 'from_date', 'to_date')}
    if len(values['q']) > 120 or (values['status'] and values['status'] not in statuses):
        abort(400, description='Use a search of up to 120 characters and choose a listed status.')
    for key in ('from_date', 'to_date'):
        if values[key]:
            try:
                values[key] = date.fromisoformat(values[key]).isoformat()
            except ValueError:
                abort(400, description='Choose a valid creation date.')
    if values['from_date'] and values['to_date'] and values['from_date'] > values['to_date']:
        abort(400, description='The end date must be on or after the start date.')
    filters, parameters = [scope], {'user_id': g.user['id']}
    if values['q']:
        filters.append('(instr(lower(a.company_name),lower(:q))>0 OR instr(lower(a.reference),lower(:q))>0)')
        parameters['q'] = values['q']
    if values['status']:
        filters.append('a.status=:status')
        parameters['status'] = values['status']
    if values['from_date']:
        filters.append('substr(a.created_at,1,10)>=:from_date')
        parameters['from_date'] = values['from_date']
    if values['to_date']:
        filters.append('substr(a.created_at,1,10)<=:to_date')
        parameters['to_date'] = values['to_date']
    rows = get_db().execute(f"""SELECT a.*,previous.reference AS renewal_of
        FROM applications a LEFT JOIN application_reviews r ON r.application_id=a.id
        LEFT JOIN application_renewals n ON n.application_id=a.id
        LEFT JOIN applications previous ON previous.id=n.previous_id
        WHERE {' AND '.join(filters)} ORDER BY a.created_at DESC,a.id DESC""", parameters).fetchall()
    counts = {status: sum(row['status'] == status for row in rows) for status in statuses}
    renewals = sum(row['renewal_of'] is not None for row in rows)
    return {'applications': rows, 'filters': values, 'statuses': statuses, 'counts': counts,
            'total': len(rows), 'renewals': renewals, 'registrations': len(rows) - renewals}


def csv_value(value):
    text = '' if value is None else str(value)
    # Keep text fields from being interpreted as spreadsheet formulas when opened.
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def send_document(application_id, kind):
    document = get_db().execute('SELECT filename,content FROM application_documents WHERE application_id=? AND kind=?',
                                (application_id, kind)).fetchone()
    if document is None:
        abort(404)
    return send_file(BytesIO(document['content']), mimetype='application/pdf',
                     as_attachment=True, download_name=document['filename'])


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=str(ROOT / 'instance' / 'govvendor.db'),
        SECRET_KEY=os.environ.get('GOVVENDOR_SECRET_KEY'),
        CSRF_ENABLED=True,
        MAX_CONTENT_LENGTH=MAX_PDF_BYTES + 64 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)
    instance = Path(app.config['DATABASE']).parent
    instance.mkdir(parents=True, exist_ok=True)
    if not app.config['SECRET_KEY']:
        secret_file = instance / '.session-secret'
        try:
            with secret_file.open('x', encoding='utf-8') as output:
                output.write(secrets.token_hex(32))
            secret_file.chmod(0o600)
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = secret_file.read_text(encoding='utf-8').strip()

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    with app.app_context():
        get_db().executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        # Begin history with each currently saved file; earlier overwritten bytes cannot be recovered.
        get_db().execute('''INSERT OR IGNORE INTO document_versions
            (application_id,kind,version,filename,content,uploaded_at,uploaded_by)
            SELECT d.application_id,d.kind,1,d.filename,d.content,d.uploaded_at,a.user_id
            FROM application_documents d JOIN applications a ON a.id=d.application_id
            WHERE NOT EXISTS (SELECT 1 FROM document_versions v
                WHERE v.application_id=d.application_id AND v.kind=d.kind)''')
        get_db().commit()

    def create_staff_account(email, role, label):
        email = email.strip().lower()
        if len(email) > 254 or not EMAIL.fullmatch(email):
            raise click.ClickException('Enter a valid demo email address.')
        db = get_db()
        if db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
            raise click.ClickException('That email already has an account. Use another demo email with --email.')
        password = click.prompt(f'Choose a demo {label.lower()} password', hide_input=True, confirmation_prompt=True)
        if not 12 <= len(password) <= 128:
            raise click.ClickException('Use a password between 12 and 128 characters.')
        try:
            db.execute("INSERT INTO users(name,email,password_hash,role) VALUES (?,?,?,?)",
                       (f'Demo {label}', email, generate_password_hash(password), role))
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            raise click.ClickException('That email already has an account.') from None
        click.echo(f'Demo {label.lower()} created: {email}')

    @app.cli.command('create-reviewer')
    @click.option('--email', default='reviewer@example.com', show_default=True)
    def create_reviewer(email):
        """Create a local demo reviewer without changing existing accounts."""
        create_staff_account(email, 'officer', 'Reviewer')

    @app.cli.command('create-administrator')
    @click.option('--email', default='admin@example.com', show_default=True)
    def create_administrator(email):
        """Create a local demo administrator without changing existing accounts."""
        create_staff_account(email, 'administrator', 'Administrator')

    def csrf_token():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        return session['csrf']

    @app.before_request
    def load_user_and_check_forms():
        g.user = None
        if session.get('user_id'):
            g.user = get_db().execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if request.method == 'POST' and app.config['CSRF_ENABLED']:
            expected, supplied = session.get('csrf', ''), request.form.get('csrf', '')
            if not expected or not supplied or not secrets.compare_digest(expected.encode(), supplied.encode()):
                abort(400, description='This form expired. Refresh the page and try again.')

    @app.after_request
    def response_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.context_processor
    def template_values():
        unread = get_db().execute('SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL',
                                  (g.user['id'],)).fetchone()[0] if g.user else 0
        return {'csrf_token': csrf_token, 'categories': CATEGORIES,
                'today': local_today().isoformat(), 'unread_notifications': unread, 'app_version': APP_VERSION}

    @app.route('/')
    def home():
        return render_template('home.html')

    @app.get('/demo-walkthrough')
    def demo_walkthrough():
        return render_template('demo_walkthrough.html',
                               workspace=workspace_endpoint(g.user['role']) if g.user else 'login')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            error = None
            if not 2 <= len(name) <= 80:
                error = 'Enter a name between 2 and 80 characters.'
            elif len(email) > 254 or not EMAIL.fullmatch(email):
                error = 'Enter a valid email address.'
            elif not 12 <= len(password) <= 128:
                error = 'Use a password between 12 and 128 characters.'
            if error:
                flash(error, 'error')
                return render_template('auth.html', mode='register'), 400
            db = get_db()
            try:
                result = db.execute('INSERT INTO users(name,email,password_hash) VALUES (?,?,?)',
                                    (name, email, generate_password_hash(password)))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                flash('An account already uses that email. Please sign in instead.', 'error')
                return render_template('auth.html', mode='register'), 409
            session.clear()
            session['user_id'] = result.lastrowid
            session.permanent = True
            flash('Your account is ready. You can start a registration draft.', 'success')
            return redirect(url_for('dashboard'), code=303)
        return render_template('auth.html', mode='register')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form.get('email', '').strip().lower()[:254]
            password = request.form.get('password', '')
            user = get_db().execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            if len(password) <= 128 and user and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session.permanent = True
                return redirect(url_for(workspace_endpoint(user['role'])), code=303)
            flash('The email or password is incorrect.', 'error')
            return render_template('auth.html', mode='login'), 401
        return render_template('auth.html', mode='login')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('home'), code=303)

    @app.route('/dashboard')
    @login_required
    def dashboard():
        if g.user['role'] != 'applicant':
            return redirect(url_for(workspace_endpoint(g.user['role'])))
        context = application_list('a.user_id=:user_id', {'user_id': g.user['id']}, STATUSES)
        return render_template('dashboard.html', list_endpoint='dashboard', reminders=expiry_reminders(), **context)

    @app.get('/notifications')
    @login_required
    def notifications():
        view = request.args.get('view', 'all')
        try:
            page = int(request.args.get('page', '1'))
        except ValueError:
            abort(400, description='Choose a valid notifications page.')
        if view not in ('all', 'unread') or page < 1:
            abort(400, description='Choose All or Unread and a valid page number.')
        db = get_db()
        db.execute('BEGIN')
        condition = 'n.user_id=?' + (' AND n.read_at IS NULL' if view == 'unread' else '')
        total = db.execute(f'SELECT COUNT(*) FROM notifications n WHERE {condition}', (g.user['id'],)).fetchone()[0]
        pages = max(1, (total + 24) // 25)
        if page > pages:
            abort(404)
        rows = db.execute(f'''SELECT n.id,n.read_at,e.description,e.created_at,
            a.reference,a.status,a.user_id AS owner_id,r.reviewer_id,
        EXISTS(SELECT 1 FROM application_messages m WHERE m.event_id=e.id) AS is_message
            FROM notifications n JOIN application_events e ON e.id=n.event_id
            JOIN applications a ON a.id=e.application_id
            LEFT JOIN application_reviews r ON r.application_id=a.id
            WHERE {condition} ORDER BY n.id DESC LIMIT 25 OFFSET ?''',
            (g.user['id'], (page - 1) * 25)).fetchall()
        items = [{'record': row, 'target': notification_target(row)} for row in rows]
        return render_template('notifications.html', notifications=items, total=total, view=view, page=page, pages=pages)

    @app.post('/notifications/<int:notification_id>/read')
    @login_required
    def read_notification(notification_id):
        owned_notification(notification_id)
        db = get_db()
        db.execute('UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=? AND user_id=?',
                   (now(), notification_id, g.user['id']))
        db.commit()
        view = request.form.get('view', 'all')
        return redirect(url_for('notifications', view='unread' if view == 'unread' else 'all'), code=303)

    @app.post('/notifications/read-all')
    @login_required
    def read_all_notifications():
        db = get_db()
        db.execute('UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL', (now(), g.user['id']))
        db.commit()
        flash('Your notifications are marked as read.', 'success')
        return redirect(url_for('notifications'), code=303)

    @app.post('/notifications/<int:notification_id>/open')
    @login_required
    def open_notification(notification_id):
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        notification = owned_notification(notification_id)
        target = notification_target(notification)
        db.execute('UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=? AND user_id=?',
                   (now(), notification_id, g.user['id']))
        db.commit()
        if not target:
            flash('That application is no longer available to your account. The assignment may have changed.', 'info')
        return redirect(target or url_for('notifications'), code=303)

    @app.get('/admin')
    @role_required('administrator')
    def admin_dashboard():
        reviewers = reviewer_accounts()
        selected_reviewer = request.args.get('reviewer', '')
        scope, parameters = "a.status<>'Draft'", {}
        if selected_reviewer == 'unassigned':
            scope += ' AND r.reviewer_id IS NULL'
        elif selected_reviewer:
            reviewer_ids = {str(row['id']): row['id'] for row in reviewers}
            if selected_reviewer not in reviewer_ids:
                abort(400, description='Choose a listed reviewer or Unassigned.')
            scope += ' AND r.reviewer_id=:reviewer_id'
            parameters['reviewer_id'] = reviewer_ids[selected_reviewer]
        context = application_list(scope, parameters, STATUSES[1:])
        return render_template('admin_dashboard.html', list_endpoint='admin_dashboard',
                               reviewer_options=reviewers, selected_reviewer=selected_reviewer, **context)

    @app.get('/admin/workload')
    @role_required('administrator')
    def admin_workload():
        db = get_db()
        db.execute('BEGIN')
        reviewers = reviewer_accounts()
        counts = db.execute(f'''SELECT r.reviewer_id,COUNT(*) AS open_count,
            SUM(a.status='Submitted') AS submitted,SUM(a.status='Under review') AS reviewing,
            SUM(a.status='Changes requested') AS waiting,
            SUM(CASE WHEN a.status IN ('Submitted','Under review') AND p.target_date<:today THEN 1 ELSE 0 END) AS overdue,
            SUM(CASE WHEN a.status IN ('Submitted','Under review') AND p.target_date=:today THEN 1 ELSE 0 END) AS due_today
            FROM applications a LEFT JOIN application_reviews r ON r.application_id=a.id
            LEFT JOIN review_plans p ON p.application_id=a.id
            WHERE {OPEN_REVIEW_SQL} GROUP BY r.reviewer_id''', {'today': local_today().isoformat()}).fetchall()
        by_reviewer = {row['reviewer_id']: dict(row) for row in counts}
        empty = dict.fromkeys(('open_count', 'submitted', 'reviewing', 'waiting', 'overdue', 'due_today'), 0)
        unassigned = by_reviewer.get(None, empty)
        rows = [{'key': 'unassigned', 'name': 'Unassigned', 'email': None, **unassigned}]
        rows.extend({'key': str(row['id']), 'name': row['name'], 'email': row['email'],
                     **by_reviewer.get(row['id'], empty)} for row in reviewers)
        totals = {key: sum(row[key] for row in rows) for key in ('open_count', 'overdue', 'due_today')}
        return render_template('admin_workload.html', rows=rows, totals=totals, unassigned=unassigned['open_count'])

    @app.get('/admin/activity')
    @role_required('administrator')
    def admin_activity():
        values = {key: request.args.get(key, '').strip() for key in ('q', 'role', 'from_date', 'to_date')}
        if len(values['q']) > 120 or (values['role'] and values['role'] not in ACTIVITY_ROLES):
            abort(400, description='Use a search of up to 120 characters and choose a listed actor role.')
        for key in ('from_date', 'to_date'):
            if values[key]:
                try:
                    values[key] = date.fromisoformat(values[key]).isoformat()
                except ValueError:
                    abort(400, description='Choose a valid activity date.')
        if values['from_date'] and values['to_date'] and values['from_date'] > values['to_date']:
            abort(400, description='The end date must be on or after the start date.')
        try:
            page = int(request.args.get('page', '1'))
        except ValueError:
            abort(400, description='Choose a valid activity page.')
        if page < 1:
            abort(400, description='Choose a valid activity page.')

        filters, parameters = ["a.status<>'Draft'"], {}
        if values['q']:
            filters.append('''(instr(lower(a.reference),lower(:q))>0 OR instr(lower(a.company_name),lower(:q))>0
                OR instr(lower(actor.name),lower(:q))>0 OR instr(lower(e.description),lower(:q))>0
                OR (actor.role<>'applicant' AND instr(lower(actor.email),lower(:q))>0))''')
            parameters['q'] = values['q']
        if values['role']:
            filters.append('actor.role=:role')
            parameters['role'] = values['role']
        if values['from_date']:
            filters.append('substr(e.created_at,1,10)>=:from_date')
            parameters['from_date'] = values['from_date']
        if values['to_date']:
            filters.append('substr(e.created_at,1,10)<=:to_date')
            parameters['to_date'] = values['to_date']

        source = f'''FROM application_events e JOIN applications a ON a.id=e.application_id
            JOIN users actor ON actor.id=e.actor_id WHERE {' AND '.join(filters)}'''
        db = get_db()
        db.execute('BEGIN')
        total = db.execute(f'SELECT COUNT(*) {source}', parameters).fetchone()[0]
        pages = max(1, (total + ACTIVITY_PAGE_SIZE - 1) // ACTIVITY_PAGE_SIZE)
        if page > pages:
            abort(404)
        offset = (page - 1) * ACTIVITY_PAGE_SIZE
        events = db.execute(f'''SELECT e.description,e.created_at,a.company_name,a.reference,
            actor.name AS actor_name,actor.role AS actor_role,
            CASE WHEN actor.role<>'applicant' THEN actor.email END AS staff_email
            {source} ORDER BY e.created_at DESC,e.id DESC LIMIT :limit OFFSET :offset''',
                            {**parameters, 'limit': ACTIVITY_PAGE_SIZE, 'offset': offset}).fetchall()
        return render_template('admin_activity.html', events=events, roles=ACTIVITY_ROLES, filters=values,
                               page=page, pages=pages, total=total, offset=offset)

    @app.get('/admin/suppliers')
    @role_required('administrator')
    def admin_suppliers():
        query = request.args.get('q', '').strip()
        category = request.args.get('category', '')
        state = request.args.get('licence', '')
        if len(query) > 120 or (category and category not in CATEGORIES) or (state and state not in SUPPLIER_LICENCE_STATES):
            abort(400, description='Use a search of up to 120 characters and choose listed filters.')

        # A pending or rejected renewal leaves the previous approval in the directory.
        rows = get_db().execute('''SELECT a.reference,a.company_name,a.category,a.licence_expiry
            FROM applications a WHERE a.status='Approved' AND NOT EXISTS (
                SELECT 1 FROM application_renewals r JOIN applications successor ON successor.id=r.application_id
                WHERE r.previous_id=a.id AND successor.status='Approved'
            )''').fetchall()
        today = local_today()
        counts = dict.fromkeys(SUPPLIER_LICENCE_STATES, 0)
        suppliers = []
        needle = query.casefold()
        for row in rows:
            days = (date.fromisoformat(row['licence_expiry']) - today).days
            licence = 'expired' if days < 0 else 'expiring' if days <= 30 else 'valid'
            counts[licence] += 1
            if (not state or licence == state) and (not category or row['category'] == category) and (
                    not needle or needle in row['company_name'].casefold() or needle in row['reference'].casefold()):
                suppliers.append(dict(row, days=days, licence=licence))
        suppliers.sort(key=lambda row: (row['company_name'].casefold(), row['reference']))
        return render_template('admin_suppliers.html', suppliers=suppliers, total=len(rows), counts=counts,
                               licence_states=SUPPLIER_LICENCE_STATES, q=query, selected_category=category,
                               selected_licence=state)

    @app.route('/admin/reviewers', methods=['GET', 'POST'])
    @role_required('administrator')
    def admin_reviewers():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            if not 2 <= len(name) <= 80 or len(email) > 254 or not EMAIL.fullmatch(email) or not 12 <= len(password) <= 128:
                flash('Enter a name of 2–80 characters, a valid demo email and a password of 12–128 characters.', 'error')
                return render_template('admin_reviewers.html', reviewers=reviewer_accounts()), 400
            db = get_db()
            try:
                db.execute("INSERT INTO users(name,email,password_hash,role) VALUES (?,?,?,'officer')",
                           (name, email, generate_password_hash(password)))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                flash('That email already belongs to an account. Choose a different demo email.', 'error')
                return render_template('admin_reviewers.html', reviewers=reviewer_accounts()), 409
            flash(f'Reviewer account created for {name}.', 'success')
            return redirect(url_for('admin_reviewers'), code=303)
        return render_template('admin_reviewers.html', reviewers=reviewer_accounts())

    @app.get('/admin/applications/<reference>')
    @role_required('administrator')
    def admin_detail(reference):
        get_db().execute('BEGIN')
        application = admin_application(reference)
        events = application_events(application['id'])
        return render_template('admin_detail.html', application=application, events=events,
                               plan=review_plan(application), review_priorities=REVIEW_PRIORITIES,
                               revision=events[0]['id'] if events else 0, reviewers=reviewer_accounts(),
                               documents=attached_documents(application['id']), document_types=DOCUMENTS,
                               reviewing=True, editable=False, admin_view=True,
                               renewal=renewal_parent(application['id']))

    @app.get('/admin/applications/<reference>/documents/<kind>')
    @role_required('administrator')
    def admin_document(reference, kind):
        get_db().execute('BEGIN')
        return send_document(admin_application(reference)['id'], kind)

    @app.get('/admin/applications/<reference>/summary')
    @role_required('administrator')
    def admin_summary(reference):
        get_db().execute('BEGIN')
        return approved_summary(admin_application(reference), reviewing=True)

    @app.post('/admin/applications/<reference>/plan')
    @role_required('administrator')
    def save_review_plan(reference):
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        application = admin_application(reference)
        latest = db.execute('SELECT COALESCE(MAX(id),0) FROM application_events WHERE application_id=?',
                            (application['id'],)).fetchone()[0]
        if request.form.get('revision') != str(latest):
            abort(409, description='This application changed. Open it again before saving the review plan.')
        if application['status'] not in ('Submitted', 'Under review', 'Changes requested'):
            abort(400, description='The review plan cannot change after a final decision.')
        priority = request.form.get('priority', '')
        target_date = request.form.get('target_date', '').strip() or None
        if priority not in REVIEW_PRIORITIES:
            abort(400, description='Choose Normal, High or Urgent for the review priority.')
        if target_date:
            try:
                canonical = date.fromisoformat(target_date).isoformat()
            except ValueError:
                abort(400, description='Enter a valid target date in YYYY-MM-DD format, or leave it empty.')
            if canonical != target_date:
                abort(400, description='Enter the target date in YYYY-MM-DD format.')
        previous = review_plan(application)
        if previous['priority'] == priority and previous['target_date'] == target_date:
            db.rollback()
            flash('The review plan is already saved with these choices.', 'info')
            return redirect(url_for('admin_detail', reference=reference), code=303)
        timestamp = now()
        db.execute('''INSERT INTO review_plans(application_id,priority,target_date,updated_by,updated_at)
            VALUES (?,?,?,?,?) ON CONFLICT(application_id) DO UPDATE SET priority=excluded.priority,
            target_date=excluded.target_date,updated_by=excluded.updated_by,updated_at=excluded.updated_at''',
            (application['id'], priority, target_date, g.user['id'], timestamp))
        old_target, new_target = previous['target_date'] or 'no target date', target_date or 'no target date'
        event = f"Administrator updated review plan: {previous['priority']} / {old_target} → {priority} / {new_target}"
        record_event(application['id'], event, timestamp,
                     recipients=(application['user_id'], application['reviewer_id']))
        db.execute('UPDATE applications SET updated_at=? WHERE id=?', (timestamp, application['id']))
        db.commit()
        flash('Review priority and target date saved.', 'success')
        return redirect(url_for('admin_detail', reference=reference), code=303)

    @app.post('/admin/applications/<reference>/assign')
    @role_required('administrator')
    def admin_assign(reference):
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        application = admin_application(reference)
        latest = db.execute('SELECT COALESCE(MAX(id),0) FROM application_events WHERE application_id=?',
                            (application['id'],)).fetchone()[0]
        if request.form.get('revision') != str(latest):
            abort(409, description='This application changed. Open it again before assigning a reviewer.')
        if application['status'] not in ('Submitted', 'Under review'):
            abort(400, description='Assign reviewers to submitted applications or cases under review.')
        reviewer_id = request.form.get('reviewer_id', type=int)
        reviewer = db.execute("SELECT id,name FROM users WHERE id=? AND role='officer'", (reviewer_id,)).fetchone()
        if reviewer is None:
            abort(400, description='Choose an existing reviewer account.')
        note = request.form.get('note', '').strip()
        if len(note) > 300 or (application['reviewer_id'] and application['reviewer_id'] != reviewer_id and not note):
            db.rollback()
            flash('Add a note of up to 300 characters when reassigning a case.', 'error')
            return redirect(url_for('admin_detail', reference=reference), code=303)
        if application['reviewer_id'] == reviewer_id:
            db.rollback()
            flash('This reviewer is already assigned.', 'info')
            return redirect(url_for('admin_detail', reference=reference), code=303)
        db.execute('''INSERT INTO application_reviews(application_id,reviewer_id) VALUES (?,?)
            ON CONFLICT(application_id) DO UPDATE SET reviewer_id=excluded.reviewer_id''',
                   (application['id'], reviewer_id))
        timestamp = now()
        # A replacement reviewer starts their own review rather than inheriting a decision form.
        db.execute('DELETE FROM review_checklists WHERE application_id=?', (application['id'],))
        db.execute("UPDATE applications SET status='Submitted',updated_at=? WHERE id=?", (timestamp, application['id']))
        event = f"Administrator assigned reviewer: {reviewer['name']}"
        if application['reviewer_name']:
            event += f" (previous reviewer: {application['reviewer_name']})"
        if note:
            event += f' — {note}'
        record_event(application['id'], event, timestamp,
                     recipients=(application['user_id'], reviewer_id, application['reviewer_id']))
        db.commit()
        flash('Reviewer assignment saved. The application is ready for the assigned reviewer to start.', 'success')
        return redirect(url_for('admin_detail', reference=reference), code=303)

    @app.get('/reports')
    @login_required
    def reports():
        return render_template('reports.html', **application_report())

    @app.get('/reports.csv')
    @login_required
    def report_csv():
        report = application_report()
        output = StringIO(newline='')
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(['Application reference', 'Record type', 'Previous approval reference', 'Company',
                         'Category', 'Current status', 'Sample licence reference', 'Sample licence expiry',
                         'Contact name', 'Contact email', 'Created (Dubai time)', 'Last updated (Dubai time)'])
        for row in report['applications']:
            writer.writerow([csv_value(value) for value in (
                row['reference'], 'Renewal' if row['renewal_of'] else 'New registration', row['renewal_of'],
                row['company_name'], row['category'], row['status'], row['trade_reference'],
                row['licence_expiry'], row['contact_name'], row['contact_email'], row['created_at'], row['updated_at'])])
        return send_file(BytesIO(output.getvalue().encode('utf-8-sig')), mimetype='text/csv; charset=utf-8',
                         as_attachment=True, download_name=f'govvendor-applications-{local_today().isoformat()}.csv')

    @app.post('/applications/<reference>/renew')
    @role_required('applicant')
    def start_renewal(reference):
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        previous = owned_application(reference)
        if previous['status'] != 'Approved':
            abort(400, description='Start a renewal from an approved application.')
        existing = existing_renewal(previous['id'])
        if existing:
            db.rollback()
            flash('A renewal already exists. Open it to continue.', 'info')
            return redirect(url_for('application_detail', reference=existing['reference']), code=303)
        renewal_reference = 'GV-' + secrets.token_hex(6).upper()
        timestamp = now()
        fields = ('company_name', 'category', 'trade_reference', 'licence_expiry', 'contact_name', 'contact_email')
        new = db.execute('''INSERT INTO applications(reference,user_id,company_name,category,trade_reference,
            licence_expiry,contact_name,contact_email,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (renewal_reference, g.user['id'], *(previous[field] for field in fields), timestamp, timestamp))
        db.execute('INSERT INTO application_renewals(application_id,previous_id) VALUES (?,?)',
                   (new.lastrowid, previous['id']))
        db.execute('INSERT INTO application_events(application_id,actor_id,description,created_at) VALUES (?,?,?,?)',
                   (new.lastrowid, g.user['id'], f"Renewal draft created from {previous['reference']}", timestamp))
        db.commit()
        flash('Renewal draft created. Choose a later licence expiry and upload both sample PDFs again.', 'success')
        return redirect(url_for('application_form', reference=renewal_reference), code=303)

    @app.route('/applications/new', methods=['GET', 'POST'])
    @app.route('/applications/<reference>/edit', methods=['GET', 'POST'])
    @role_required('applicant')
    def application_form(reference=None):
        application = owned_application(reference) if reference else None
        renewal = renewal_parent(application['id']) if application else None
        if application and application['status'] not in EDITABLE_STATUSES:
            abort(400, description='You can edit a draft or an application returned for changes.')
        fields = ('company_name', 'category', 'trade_reference', 'licence_expiry', 'contact_name', 'contact_email')
        defaults = {field: application[field] if application else '' for field in fields}
        if not application:
            defaults.update(contact_name=g.user['name'], contact_email=g.user['email'])
        errors = {}
        values = defaults
        if request.method == 'POST':
            values = {field: request.form.get(field, '').strip() for field in fields}
            values['contact_email'] = values['contact_email'].lower()
            if not 3 <= len(values['company_name']) <= 120:
                errors['company_name'] = 'Use a company name between 3 and 120 characters.'
            if values['category'] not in CATEGORIES:
                errors['category'] = 'Choose a supplier category from the list.'
            if not 3 <= len(values['trade_reference']) <= 60:
                errors['trade_reference'] = 'Enter a fictional reference between 3 and 60 characters.'
            try:
                expiry = date.fromisoformat(values['licence_expiry'])
                values['licence_expiry'] = expiry.isoformat()
                if renewal and values['licence_expiry'] <= renewal['licence_expiry']:
                    errors['licence_expiry'] = f"Choose a date later than {renewal['licence_expiry']} for this renewal."
            except ValueError:
                errors['licence_expiry'] = 'Choose a valid expiry date.'
            if not 2 <= len(values['contact_name']) <= 80:
                errors['contact_name'] = 'Use a contact name between 2 and 80 characters.'
            if len(values['contact_email']) > 254 or not EMAIL.fullmatch(values['contact_email']):
                errors['contact_email'] = 'Enter a valid contact email.'
            if errors:
                return render_template('application_form.html', application=application, values=values, errors=errors,
                                       renewal=renewal), 400
            db = get_db()
            timestamp = now()
            if application:
                updated = db.execute('''UPDATE applications SET company_name=?,category=?,trade_reference=?,licence_expiry=?,
                    contact_name=?,contact_email=?,updated_at=? WHERE id=? AND user_id=? AND status=?''',
                                     (*(values[field] for field in fields), timestamp, application['id'],
                                      g.user['id'], application['status']))
                if not updated.rowcount:
                    db.rollback()
                    abort(400, description='This application has already been submitted.')
                application_id = application['id']
                event = ('Registration details corrected' if application['status'] == 'Changes requested'
                         else 'Registration draft updated')
            else:
                reference = 'GV-' + secrets.token_hex(6).upper()
                result = db.execute('''INSERT INTO applications(reference,user_id,company_name,category,trade_reference,
                    licence_expiry,contact_name,contact_email,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                                    (reference, g.user['id'], *(values[field] for field in fields), timestamp, timestamp))
                application_id = result.lastrowid
                event = 'Registration draft created'
            db.execute('INSERT INTO application_events(application_id,actor_id,description,created_at) VALUES (?,?,?,?)',
                       (application_id, g.user['id'], event, timestamp))
            db.commit()
            flash('Your registration details are saved.', 'success')
            return redirect(url_for('application_detail', reference=reference), code=303)
        return render_template('application_form.html', application=application, values=values, errors=errors, renewal=renewal)

    @app.route('/applications/<reference>')
    @login_required
    def application_detail(reference):
        get_db().execute('BEGIN')
        application = owned_application(reference)
        events = application_events(application['id'])
        expired = application['licence_expiry'] < local_today().isoformat()
        renewal = renewal_parent(application['id'])
        review = get_db().execute('SELECT note FROM application_reviews WHERE application_id=?',
                                  (application['id'],)).fetchone()
        return render_template('application.html', application=application, events=events,
                               plan=review_plan(application),
                               expired=expired, documents=attached_documents(application['id']), document_types=DOCUMENTS,
                               editable=application['status'] in EDITABLE_STATUSES, review=review, reviewing=False,
                               renewal=renewal, child=existing_renewal(application['id']),
                               renewal_date_valid=not renewal or application['licence_expiry'] > renewal['licence_expiry'],
                               expiry_days=(date.fromisoformat(application['licence_expiry']) - local_today()).days)

    @app.get('/applications/<reference>/renewal-comparison')
    @login_required
    def renewal_comparison(reference):
        db = get_db()
        db.execute('BEGIN')
        application = accessible_application(reference)
        # Compare only company and licence fields from the linked approval.
        previous = db.execute('''SELECT a.reference,a.company_name,a.category,a.trade_reference,a.licence_expiry
            FROM application_renewals r JOIN applications a ON a.id=r.previous_id
            WHERE r.application_id=? AND a.user_id=? AND a.status='Approved' ''',
                              (application['id'], application['user_id'])).fetchone()
        if previous is None:
            abort(404)
        fields = (('company_name', 'Company name'), ('category', 'Supplier category'),
                  ('trade_reference', 'Sample licence reference'), ('licence_expiry', 'Sample licence expiry'))
        rows = [{'label': label, 'previous': previous[key], 'current': application[key],
                 'changed': previous[key] != application[key]} for key, label in fields]
        back = {'applicant': 'application_detail', 'officer': 'review_detail', 'administrator': 'admin_detail'}
        return render_template('renewal_comparison.html', application=application, previous=previous,
                               rows=rows, changed=sum(row['changed'] for row in rows),
                               back_endpoint=back[g.user['role']])

    def render_message_page(application, body='', error=None, response_status=200):
        db = get_db()
        assigned = db.execute('''SELECT r.reviewer_id,u.name FROM application_reviews r
            JOIN users u ON u.id=r.reviewer_id WHERE r.application_id=?''', (application['id'],)).fetchone()
        can_send = bool(assigned and application['status'] in MESSAGE_STATUSES and
                        (g.user['role'] == 'applicant' or
                         (g.user['role'] == 'officer' and assigned['reviewer_id'] == g.user['id'])))
        total = db.execute('SELECT COUNT(*) FROM application_messages WHERE application_id=?',
                           (application['id'],)).fetchone()[0]
        pages = max(1, (total + 19) // 20)
        try:
            page = int(request.args.get('page', str(pages))) if request.method == 'GET' else pages
        except ValueError:
            abort(400, description='Choose a valid messages page.')
        if page < 1:
            abort(400, description='Choose a valid messages page.')
        if page > pages:
            abort(404)
        messages = db.execute('''SELECT m.id,m.author_id,m.author_role,m.body,m.created_at,u.name
            FROM application_messages m JOIN users u ON u.id=m.author_id
            WHERE m.application_id=? ORDER BY m.id LIMIT 20 OFFSET ?''',
            (application['id'], (page - 1) * 20)).fetchall()
        endpoint = {'applicant': 'application_detail', 'officer': 'review_detail',
                    'administrator': 'admin_detail'}[g.user['role']]
        return render_template('messages.html', application=application, messages=messages,
                               total=total, page=page, pages=pages, assigned=assigned, can_send=can_send,
                               message_body=body, message_error=error, message_token=secrets.token_hex(16),
                               message_max_chars=MESSAGE_MAX_CHARS,
                               back_url=url_for(endpoint, reference=application['reference'])), response_status

    @app.route('/applications/<reference>/messages', methods=['GET', 'POST'])
    @login_required
    def application_messages(reference):
        db = get_db()
        db.execute('BEGIN IMMEDIATE' if request.method == 'POST' else 'BEGIN')
        application = accessible_application(reference)
        if application['status'] == 'Draft':
            abort(404)
        if request.method == 'GET':
            return render_message_page(application)
        # Administrators can inspect the thread, but cannot speak for either party.
        if g.user['role'] not in ('applicant', 'officer'):
            abort(403, description='Administrators can read this conversation but cannot send messages.')
        body = request.form.get('body', '').strip()
        token = request.form.get('message_token', '')
        if not 1 <= len(body) <= MESSAGE_MAX_CHARS or '\x00' in body:
            return render_message_page(application, body, f'Enter a message between 1 and {MESSAGE_MAX_CHARS} characters without null characters.', 400)
        if not re.fullmatch(r'[0-9a-f]{32}', token):
            return render_message_page(application, body, 'Refresh this page and try sending your message again.', 400)
        previous = db.execute('SELECT application_id,body FROM application_messages WHERE author_id=? AND send_token=?',
                              (g.user['id'], token)).fetchone()
        if previous:
            if previous['application_id'] != application['id'] or previous['body'] != body:
                return render_message_page(application, body, 'That send form was already used. Review this message and send it again.', 409)
            db.rollback()
            flash('This message is already saved; no duplicate was sent.', 'info')
            return redirect(url_for('application_messages', reference=reference, _anchor='conversation-end'), code=303)
        assigned = db.execute('SELECT reviewer_id FROM application_reviews WHERE application_id=?',
                              (application['id'],)).fetchone()
        if application['status'] not in MESSAGE_STATUSES:
            abort(400, description='This conversation is read-only because the application decision is complete.')
        if not assigned:
            abort(400, description='A reviewer must be assigned before sending a message.')
        if request.form.get('reviewer_id') != str(assigned['reviewer_id']):
            return render_message_page(application, body, 'The reviewer assignment changed. Read the conversation and send again to the current reviewer.', 409)
        recipient = assigned['reviewer_id'] if g.user['role'] == 'applicant' else application['user_id']
        timestamp = now()
        actor = 'Applicant' if g.user['role'] == 'applicant' else 'Reviewer'
        event_id = record_event(application['id'], f'{actor} sent an application message', timestamp, recipients=(recipient,))
        db.execute('''INSERT INTO application_messages
            (application_id,author_id,author_role,body,created_at,event_id,send_token) VALUES (?,?,?,?,?,?,?)''',
            (application['id'], g.user['id'], g.user['role'], body, timestamp, event_id, token))
        db.execute('UPDATE applications SET updated_at=? WHERE id=?', (timestamp, application['id']))
        db.commit()
        flash('Message sent. The other account has an in-app notification.', 'success')
        return redirect(url_for('application_messages', reference=reference, _anchor='conversation-end'), code=303)

    @app.get('/applications/<reference>/summary')
    @login_required
    def application_summary(reference):
        get_db().execute('BEGIN')
        return approved_summary(owned_application(reference), reviewing=False)

    @app.post('/applications/<reference>/documents/<kind>')
    @login_required
    def upload_document(reference, kind):
        application = owned_application(reference)
        if kind not in DOCUMENTS:
            abort(404)
        if application['status'] not in EDITABLE_STATUSES:
            abort(400, description='Documents can only be changed in a draft or after changes are requested.')
        upload = request.files.get('document')
        content = upload.stream.read(MAX_PDF_BYTES + 1) if upload else b''
        if len(content) > MAX_PDF_BYTES:
            flash('Choose a PDF no larger than 2 MB.', 'error')
        elif not upload or not upload.filename.lower().endswith('.pdf') or not content.startswith(b'%PDF-') or not content.rstrip().endswith(b'%%EOF'):
            flash('Choose a PDF file. You can use the sample PDFs included with GovVendor.', 'error')
        else:
            # Store the sample bytes with their application. The filename is for display and download only.
            name = (secure_filename(upload.filename[:-4])[:100] or kind) + '.pdf'
            db = get_db()
            db.execute('BEGIN IMMEDIATE')
            application = owned_application(reference)
            if application['status'] not in EDITABLE_STATUSES:
                abort(400, description='Documents cannot be changed at this stage.')
            timestamp = now()
            db.execute('''INSERT INTO application_documents(application_id,kind,filename,content,uploaded_at)
                VALUES (?,?,?,?,?) ON CONFLICT(application_id,kind) DO UPDATE SET
                filename=excluded.filename, content=excluded.content, uploaded_at=excluded.uploaded_at''',
                       (application['id'], kind, name, content, timestamp))
            version = db.execute('''SELECT COALESCE(MAX(version),0)+1 FROM document_versions
                WHERE application_id=? AND kind=?''', (application['id'], kind)).fetchone()[0]
            db.execute('''INSERT INTO document_versions
                (application_id,kind,version,filename,content,uploaded_at,uploaded_by)
                VALUES (?,?,?,?,?,?,?)''',
                (application['id'], kind, version, name, content, timestamp, g.user['id']))
            db.execute('UPDATE applications SET updated_at=? WHERE id=?', (timestamp, application['id']))
            db.execute('INSERT INTO application_events(application_id,actor_id,description,created_at) VALUES (?,?,?,?)',
                       (application['id'], g.user['id'], f'{DOCUMENTS[kind]} attached (version {version})', timestamp))
            db.commit()
            flash(f'{DOCUMENTS[kind]} attached.', 'success')
        return redirect(url_for('application_detail', reference=reference), code=303)

    @app.get('/documents/<reference>/<kind>/history')
    @login_required
    def document_history(reference, kind):
        get_db().execute('BEGIN')
        application = accessible_application(reference)
        if kind not in DOCUMENTS:
            abort(404)
        versions = get_db().execute('''SELECT v.version,v.filename,v.uploaded_at,u.name AS uploader
            FROM document_versions v JOIN users u ON u.id=v.uploaded_by
            WHERE v.application_id=? AND v.kind=? ORDER BY v.version DESC''',
            (application['id'], kind)).fetchall()
        if not versions:
            abort(404)
        endpoint = {'applicant': 'application_detail', 'officer': 'review_detail',
                    'administrator': 'admin_detail'}[g.user['role']]
        return render_template('document_history.html', application=application, kind=kind,
                               label=DOCUMENTS[kind], versions=versions, back_endpoint=endpoint)

    @app.get('/documents/<reference>/<kind>/versions/<int:version>')
    @login_required
    def download_version(reference, kind, version):
        get_db().execute('BEGIN')
        application = accessible_application(reference)
        if kind not in DOCUMENTS or version > 9223372036854775807:
            abort(404)
        document = get_db().execute('''SELECT filename,content FROM document_versions
            WHERE application_id=? AND kind=? AND version=?''', (application['id'], kind, version)).fetchone()
        if document is None:
            abort(404)
        return send_file(BytesIO(document['content']), mimetype='application/pdf', as_attachment=True,
                         download_name=f"{Path(document['filename']).stem}-v{version}.pdf")

    @app.get('/applications/<reference>/documents/<kind>')
    @login_required
    def download_document(reference, kind):
        application = owned_application(reference)
        return send_document(application['id'], kind)

    @app.post('/applications/<reference>/submit')
    @login_required
    def submit_application(reference):
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        application = owned_application(reference)
        if application['status'] not in EDITABLE_STATUSES:
            abort(400, description='This application is not open for submission.')
        document_count = db.execute('SELECT COUNT(*) FROM application_documents WHERE application_id=?',
                                    (application['id'],)).fetchone()[0]
        renewal = renewal_parent(application['id'])
        if renewal and application['licence_expiry'] <= renewal['licence_expiry']:
            db.rollback()
            flash(f"Choose a renewal expiry date later than {renewal['licence_expiry']} before submitting.", 'error')
        elif document_count != len(DOCUMENTS) or application['licence_expiry'] < local_today().isoformat():
            db.rollback()
            flash('Attach both sample PDFs and check the licence expiry date before submitting.', 'error')
        else:
            timestamp = now()
            event = ('Application resubmitted for demo review' if application['status'] == 'Changes requested'
                     else 'Application submitted for demo review')
            db.execute("UPDATE applications SET status='Submitted',updated_at=? WHERE id=?",
                       (timestamp, application['id']))
            # Corrections may change any details or files; the next review must check them again.
            db.execute('DELETE FROM review_checklists WHERE application_id=?', (application['id'],))
            record_event(application['id'], event, timestamp, recipients=submission_recipients(application['id']))
            db.commit()
            flash('Application submitted in GovVendor.', 'success')
        return redirect(url_for('application_detail', reference=reference), code=303)

    @app.get('/review')
    @role_required('officer')
    def review_queue():
        context = application_list("a.status<>'Draft' AND (r.reviewer_id=:user_id OR (r.reviewer_id IS NULL AND a.status='Submitted'))",
                                   {'user_id': g.user['id']}, STATUSES[1:])
        return render_template('review_queue.html', list_endpoint='review_queue', **context)

    @app.get('/review/<reference>/summary')
    @role_required('officer')
    def review_summary(reference):
        get_db().execute('BEGIN')
        return approved_summary(reviewable_application(reference), reviewing=True)

    @app.get('/review/<reference>')
    @role_required('officer')
    def review_detail(reference):
        get_db().execute('BEGIN')
        application = reviewable_application(reference)
        events = application_events(application['id'])
        checklist = review_checklist(application['id'])
        checked_count = sum(checklist[key] for key in REVIEW_CHECKS) if checklist else 0
        return render_template('review_detail.html', application=application, plan=review_plan(application),
                               checklist=checklist, review_checks=REVIEW_CHECKS, checked_count=checked_count,
                               checklist_ready=checklist_complete(application['id'], g.user['id']),
                               events=events, revision=events[0]['id'] if events else 0,
                               has_reviewed=any(event['actor_id'] == g.user['id'] and
                                                event['description'] == 'Reviewer started the review' for event in events),
                               documents=attached_documents(application['id']), document_types=DOCUMENTS,
                               reviewing=True, editable=False, renewal=renewal_parent(application['id']))

    @app.get('/review/<reference>/documents/<kind>')
    @role_required('officer')
    def review_document(reference, kind):
        get_db().execute('BEGIN')
        application = reviewable_application(reference)
        return send_document(application['id'], kind)

    @app.post('/review/<reference>/checklist')
    @role_required('officer')
    def save_review_checklist(reference):
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        application = reviewable_application(reference)
        latest = db.execute('SELECT COALESCE(MAX(id),0) FROM application_events WHERE application_id=?',
                            (application['id'],)).fetchone()[0]
        if request.form.get('revision') != str(latest):
            abort(409, description='This application changed. Open it again before saving the checklist.')
        if application['status'] != 'Under review' or application['reviewer_id'] != g.user['id']:
            abort(400, description='Start your assigned review before saving its checklist.')
        selected = request.form.getlist('checks')
        if len(selected) != len(set(selected)) or any(key not in REVIEW_CHECKS for key in selected):
            abort(400, description='Choose only the listed review checks.')
        values = {key: int(key in selected) for key in REVIEW_CHECKS}
        previous = review_checklist(application['id'])
        if previous and previous['reviewer_id'] == g.user['id'] and all(previous[key] == value for key, value in values.items()):
            db.rollback()
            flash('The checklist is already saved with these choices.', 'info')
            return redirect(url_for('review_detail', reference=reference), code=303)
        timestamp = now()
        db.execute('''INSERT INTO review_checklists
            (application_id,reviewer_id,company_details,licence_expiry,licence_document,company_profile,saved_at)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(application_id) DO UPDATE SET
            reviewer_id=excluded.reviewer_id,company_details=excluded.company_details,
            licence_expiry=excluded.licence_expiry,licence_document=excluded.licence_document,
            company_profile=excluded.company_profile,saved_at=excluded.saved_at''',
            (application['id'], g.user['id'], *values.values(), timestamp))
        labels = '; '.join(REVIEW_CHECKS[key] for key in REVIEW_CHECKS if values[key]) or 'None'
        record_event(application['id'], f'Reviewer saved checklist ({sum(values.values())} of {len(REVIEW_CHECKS)}): {labels}', timestamp)
        db.execute('UPDATE applications SET updated_at=? WHERE id=?', (timestamp, application['id']))
        db.commit()
        flash(f'Checklist saved: {sum(values.values())} of {len(REVIEW_CHECKS)} checked.', 'success')
        return redirect(url_for('review_detail', reference=reference), code=303)

    @app.post('/review/<reference>')
    @role_required('officer')
    def review_action(reference):
        action = request.form.get('action', '')
        note = request.form.get('note', '').strip()
        db = get_db()
        db.execute('BEGIN IMMEDIATE')
        application = reviewable_application(reference)
        target = url_for('review_detail', reference=reference)
        latest_event = db.execute('SELECT COALESCE(MAX(id),0) FROM application_events WHERE application_id=?',
                                  (application['id'],)).fetchone()[0]
        if request.form.get('revision') != str(latest_event):
            abort(409, description='This application changed. Open it again before making a decision.')

        if action == 'start' and application['status'] == 'Submitted':
            db.execute('INSERT INTO application_reviews(application_id,reviewer_id) VALUES (?,?) '
                       'ON CONFLICT(application_id) DO NOTHING', (application['id'], g.user['id']))
            status, event = 'Under review', 'Reviewer started the review'
        elif action in REVIEW_DECISIONS and application['status'] == 'Under review' and application['reviewer_id'] == g.user['id']:
            renewal = renewal_parent(application['id'])
            if action == 'approve' and (application['licence_expiry'] < local_today().isoformat()
                                       or (renewal and application['licence_expiry'] <= renewal['licence_expiry'])):
                db.rollback()
                flash('The sample licence date needs correcting. Request changes before approving.', 'error')
                return redirect(target, code=303)
            if action == 'approve' and (not checklist_complete(application['id'], g.user['id']) or
                    db.execute('SELECT COUNT(*) FROM application_documents WHERE application_id=?',
                               (application['id'],)).fetchone()[0] != len(DOCUMENTS)):
                db.rollback()
                flash('Check the current details and both PDFs, then save all four review checks before approving.', 'error')
                return redirect(target, code=303)
            if len(note) > 800 or (action != 'approve' and not note):
                db.rollback()
                flash('Add a note for the applicant (up to 800 characters) when requesting changes or rejecting.', 'error')
                return redirect(target, code=303)
            status = REVIEW_DECISIONS[action]
            event = f'Reviewer decision: {status}' + (f' — {note}' if note else '')
            db.execute('UPDATE application_reviews SET note=? WHERE application_id=?', (note, application['id']))
        else:
            abort(400, description='That review action is not available at this stage.')

        timestamp = now()
        db.execute('UPDATE applications SET status=?,updated_at=? WHERE id=?', (status, timestamp, application['id']))
        record_event(application['id'], event, timestamp, recipients=(application['user_id'],))
        db.commit()
        flash(f'Application status: {status}.', 'success')
        return redirect(target, code=303)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    def error_page(error):
        return render_template('error.html', error=error), error.code

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000, debug=False)
