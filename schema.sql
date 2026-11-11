PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'applicant' CHECK(role IN ('applicant','officer','administrator'))
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    reference TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    company_name TEXT NOT NULL,
    category TEXT NOT NULL,
    trade_reference TEXT NOT NULL,
    licence_expiry TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    contact_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft'
      CHECK(status IN ('Draft','Submitted','Under review','Changes requested','Approved','Rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS applications_by_user ON applications(user_id,id);

CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    actor_id INTEGER NOT NULL REFERENCES users(id),
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS application_events_by_application ON application_events(application_id,id);

CREATE TABLE IF NOT EXISTS application_documents (
    application_id INTEGER NOT NULL REFERENCES applications(id),
    kind TEXT NOT NULL CHECK(kind IN ('licence','profile')),
    filename TEXT NOT NULL,
    content BLOB NOT NULL CHECK(length(content) BETWEEN 1 AND 2097152),
    uploaded_at TEXT NOT NULL,
    PRIMARY KEY(application_id, kind)
);

CREATE TABLE IF NOT EXISTS application_reviews (
    application_id INTEGER PRIMARY KEY REFERENCES applications(id),
    reviewer_id INTEGER NOT NULL REFERENCES users(id),
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS application_renewals (
    application_id INTEGER PRIMARY KEY REFERENCES applications(id),
    previous_id INTEGER NOT NULL REFERENCES applications(id),
    CHECK(application_id <> previous_id)
);
CREATE INDEX IF NOT EXISTS renewal_previous ON application_renewals(previous_id);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_id INTEGER NOT NULL REFERENCES application_events(id),
    read_at TEXT,
    UNIQUE(user_id,event_id)
);
CREATE INDEX IF NOT EXISTS notifications_by_recipient ON notifications(user_id,read_at,id);

CREATE TABLE IF NOT EXISTS document_versions (
    application_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('licence','profile')),
    version INTEGER NOT NULL CHECK(version > 0),
    filename TEXT NOT NULL,
    content BLOB NOT NULL CHECK(length(content) BETWEEN 1 AND 2097152),
    uploaded_at TEXT NOT NULL,
    uploaded_by INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY(application_id,kind,version),
    FOREIGN KEY(application_id,kind) REFERENCES application_documents(application_id,kind)
);

-- The saved checklist belongs to the current reviewer and current submission.
-- Resubmission/reassignment clears it; earlier saves remain in application_events.
CREATE TABLE IF NOT EXISTS review_checklists (
    application_id INTEGER PRIMARY KEY REFERENCES applications(id),
    reviewer_id INTEGER NOT NULL REFERENCES users(id),
    company_details INTEGER NOT NULL CHECK(company_details IN (0,1)),
    licence_expiry INTEGER NOT NULL CHECK(licence_expiry IN (0,1)),
    licence_document INTEGER NOT NULL CHECK(licence_document IN (0,1)),
    company_profile INTEGER NOT NULL CHECK(company_profile IN (0,1)),
    saved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS application_messages (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    author_id INTEGER NOT NULL REFERENCES users(id),
    author_role TEXT NOT NULL CHECK(author_role IN ('applicant','officer')),
    body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 1500),
    created_at TEXT NOT NULL,
    event_id INTEGER NOT NULL UNIQUE REFERENCES application_events(id),
    send_token TEXT NOT NULL CHECK(length(send_token)=32),
    UNIQUE(author_id,send_token)
);
CREATE INDEX IF NOT EXISTS messages_by_application ON application_messages(application_id,id);

CREATE TABLE IF NOT EXISTS review_plans (
    application_id INTEGER PRIMARY KEY REFERENCES applications(id),
    priority TEXT NOT NULL CHECK(priority IN ('Normal','High','Urgent')),
    target_date TEXT CHECK(target_date IS NULL OR length(target_date)=10),
    updated_by INTEGER NOT NULL REFERENCES users(id),
    updated_at TEXT NOT NULL
);
