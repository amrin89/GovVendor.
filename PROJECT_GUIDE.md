# GovVendor v1.0 — portfolio demo

A Python, Flask and SQLite learning project for supplier registration.
Independent portfolio demo: fictional details, no government affiliation,
no official registrations and no live government integration.

**Already using GovVendor?** Use [NEXT_STEP.md](NEXT_STEP.md) to update
your current folder to v1.0.
For a fresh installation, start with [START_HERE.md](START_HERE.md).

## Start the demo

Open **Demo walkthrough** from Home or the sidebar. It follows a fictional
supplier through submission, assignment, review, approval and renewal using
the applicant, administrator and reviewer workspaces. Use [DEMO_SCRIPT.md](DEMO_SCRIPT.md)
for a short portfolio recording. The walkthrough is available before sign-in;
case data remains scoped to the existing account permissions.

## Added in milestone 16

- **Compare renewal details** shows the saved renewal and its linked previous
  approval side by side, with changed fields and a change count.
- The comparison covers company name, category, sample licence reference and
  expiry. It uses existing case permissions and does not grant access to the
  previous case's contacts, documents or messages.
- Works on existing renewal records without a database change or new packages.

## Added in milestone 15

- Administrators can browse recorded actions across submitted cases, including
  earlier history on those cases. Applications still in Draft are excluded.
- Events show the actor, role, recorded action and Dubai time. Staff emails
  distinguish accounts with the same display name; applicant account emails
  are not shown as actor details. A case reference opens its full history.
- Search cases, people or action text; combine with an actor role and inclusive
  date range. Pages contain up to 25 entries and preserve the selected filters.
- The log reads existing case events without a database change or new packages.

## Added in milestone 14

- Administrators can see open, unassigned, overdue and due-today case counts.
- The workload table groups cases by reviewer and includes unassigned cases and
  reviewers with zero open cases. Cases waiting for applicant changes count as
  open; the timing counts use Dubai's date and cover Submitted and Under review.
- Counts link to the matching cases in Administration. Its assignment filter
  combines with status, timing, priority and search. The status filter also has
  an Open cases option, covering Submitted, Under review and Changes requested.
- The workload reflects existing assignments and decisions without a database
  change or new packages.

## Added in milestone 13

- The **Approved suppliers** directory is available to administrators.
- One entry appears per approved registration chain. A pending or rejected renewal
  leaves its previous approval listed; an approved renewal replaces it in the directory.
- Search by company name or approval reference, and filter by category and licence status.
- Licence states use Dubai's calendar date: valid (more than 30 days left), expiring
  soon (0–30 days left) and expired (past date). These are based on saved demo data.
- Directory totals are independent of filters. Each result links to its existing
  approval, and historical approvals remain accessible in Administration and Reports.
- The directory reads existing records without a schema change or new packages.

## Added in milestone 12

- Administrators set Normal, High or Urgent priority and an optional target review date.
- The applicant and authorized staff can read the plan on the application page.
- Staff queues show plan details, Overdue reviews / Due today totals and combined
  priority/timing/search/status filters, within each workspace's existing case scope.
- Active cases are listed first, then Urgent / High / Normal priority and earliest
  dated target; undated cases follow dated cases within the same priority.
- Waiting-for-applicant and final cases do not count as overdue. Timing uses
  Dubai's calendar date when pages load, without a scheduled job or outbound email.
- Plan changes are recorded in application activity and notify the applicant and
  currently assigned reviewer, while preserving status, documents and review checks.
- Plans stay with a case through corrections and reassignment. A new renewal has
  its own plan. Completed decisions retain their plan as read-only history.
- Existing records default to Normal with no target date; no plan rows are backfilled.
- Explicitly exclude private Draft cases from reviewer access/queues/reports even
  if an imported record carries a reviewer assignment.
- One new table; no additional Python dependencies.

## Added in milestone 11

- A Messages page for each submitted application, shared by its applicant and
  current reviewer, with read-only administrator access.
- Questions/replies show the sender, role and Dubai time and stay saved across restarts.
- In-app notifications open the conversation directly. No email service is used.
- Sending messages does not change status, documents or saved review checks.
- Messages are available once a reviewer is assigned, in Submitted, Under review
  and Changes requested. Approved/Rejected conversations remain readable but closed.
- Reassignment preserves the conversation for the new reviewer and revokes the
  former reviewer's access. Old forms cannot silently send to a different reviewer.
- A send identifier prevents an accidental retry from creating duplicate messages.
- One new table/index, no additional Python dependencies.

## Added in milestone 10

- Reviewers save four manual checks: company/contact details, licence expiry,
  trade licence PDF and company profile PDF.
- Partial progress survives refreshes and restarts. Save the checklist before
  using the separate decision form.
- Approval requires all four saved checks from the current assigned reviewer,
  both current PDFs and the existing licence-date rules. The server enforces
  this even if someone bypasses the disabled button.
- Request changes/reject remain available with a note even if checks are incomplete.
- Resubmitting or changing reviewers clears the current checks. Earlier checklist
  saves remain in the application activity, visible to the applicant and authorized staff.
- Existing approvals are preserved; they are not retroactively marked as checked.
- One new table is created on startup; no extra Python dependencies.

## Added in milestone 9

- Retain a separate copy of each PDF upload as version 1, 2 and so on.
- Document history shows filenames, uploader, time and downloads.
- Current checklists and approval summaries identify the latest file version.
- History/download access follows current applicant, reviewer and administrator permissions.
- Existing current PDFs are seeded as version 1, without altering earlier activity.
- No additional dependencies; one version-history table is added automatically.

## Added in milestone 8

- Notifications inbox for applicant, reviewer and administrator accounts.
- Unread sidebar count, All/Unread filters and 25-item pagination.
- Mark one or all notifications as read; opening an entry marks it as read.
- Submission, assignment and review updates create account-specific notifications.
- Opening an old entry rechecks current case access after reassignment.
- New notifications table added without changing earlier records.
- No extra dependencies, external messaging service or scheduled job.

## Added in milestone 7

- Administrator login and application oversight, excluding private Draft records.
- Create demo reviewer accounts in the administrator workspace.
- Assign Submitted cases and reassign Submitted/Under review cases.
- Reassignment requires a note, returns the case to Submitted, records history,
  and removes the previous reviewer's access.
- Administrator reports and downloads across post-submission records.
- No additional dependencies or schema changes.

## Added in milestone 6

- Reports page for applicant, reviewer and administrator accounts.
- Company/reference search, current status, and inclusive created-date filters.
- Matching-record totals, registration/renewal totals and status breakdown.
- CSV downloads with matching application details and renewal references.
- Report and CSV access follow the same role boundaries as the workspaces.
- No schema change or additional Python dependencies.

## Added in milestone 5

- Start a separate renewal draft from an approved application.
- Company/contact details are copied; the old approval, documents and history are preserved.
- Renewals require a later sample licence expiry and both PDF uploads.
- Repeated clicks open an existing renewal; rejected renewals allow a fresh attempt.
- In-app reminders for current approved sample licences expiring within 30 days or already expired.
- Reviewer and printable-summary context links each renewal to its previous approval.

## Added in milestone 4

- Status totals in both applicant and reviewer workspaces.
- Combined company/reference search and status filters.
- A printable demo approval summary for approved applications, with browser Save as PDF.
- No new Python dependencies; existing records are retained. Milestone 5 adds one renewal-links table automatically.

## What works now

- Home page and responsive applicant workspace, using the blue/green/gold design.
- Account registration, sign in and sign out.
- Hashed passwords and a private workspace per applicant.
- Company registration form with server-side validation and preserved form values on error.
- Draft saving with a unique application reference.
- Viewing and editing your own saved drafts.
- Draft history: creation and update activity.
- Expired sample licence dates are flagged while draft editing remains possible.
- Two sample PDF attachments per application, with a checklist and private downloads.
- Submission requires both documents and a current sample licence expiry.
- Submission locks the details and documents and records the event in the timeline.
- A separate reviewer workspace shows new submissions and the reviewer's assigned cases.
- Reviewers can request corrections with a note, approve, or reject with a reason.
- Applicants can correct details, replace PDFs and resubmit under the same reference.
- SQLite storage that persists across browser refreshes and app restarts.
- CSRF checks, parameterized SQL and ownership checks on the Python routes.

Applications move from **Draft** to **Submitted** to **Under review**. The reviewer
can approve, reject or return the application for corrections. A returned
application can be resubmitted to the same reviewer. These are demo decisions;
GovVendor does not issue official certificates.

## Run locally

From the folder containing app.py:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000. Stop with Ctrl+C. Python must already be installed.
On macOS/Linux, use `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`
and `.venv/bin/python app.py`.

The `instance` folder is created on first run. It contains `govvendor.db` and a
generated session secret. Both are excluded from Git. No accounts, passwords,
database files or applicant records are shipped in the ZIP.

## Understand the files

| File | Purpose |
|---|---|
| `app.py` | Flask routes, account logic, validation, data saving and ownership checks |
| `schema.sql` | Users, cases, documents/versions, activity, reviews, renewals, notifications, checklists, messages and review plans |
| `templates/base.html` | Shared sidebar, header, messages and footer |
| `templates/home.html` | Public home page |
| `templates/auth.html` | Create-account and sign-in forms |
| `templates/dashboard.html` | The applicant's saved drafts |
| `templates/application_form.html` | New-draft and edit-draft form |
| `templates/application.html` | Saved details, status, activity and document checklist |
| `templates/document_history.html` | Saved PDF versions and authorized downloads |
| `templates/notifications.html` | Personal inbox, unread filter and read controls |
| `templates/messages.html` | Application conversations, replies and earlier messages |
| `templates/review_plan*.html` | Shared case plan and queue plan details |
| `templates/admin_*.html` | Administration, reviewer accounts and assignment controls |
| `templates/reports.html` | Filtered reports and CSV download controls |
| `templates/expiry_reminders.html` | In-app sample licence expiry reminders |
| `templates/list_tools.html` | Shared status totals, search and filters |
| `templates/approval_summary.html` | Printable approved application summary |
| `static/summary.css` | A4 print and summary layout |
| `templates/review_*.html` | Reviewer queue and decision form |
| `sample-documents/` | The two fictional PDFs for trying the upload flow |
| `static/style.css` | Desktop and mobile layout |
| `tests/test_govvendor.py` | Request/database checks using unittest |

## Learn one small part first

1. Open `templates/home.html`. Find the main heading and change its wording.
2. Save, restart Python and refresh the browser to see your change.
3. Open `app.py` and find `home()`: it returns that template.
4. Create and edit a draft through the browser.
5. Read `application_form()` to follow validation, an SQL INSERT/UPDATE, commit
   and the redirect to the saved-details page.
6. Read `upload_document()` and `submit_application()` to see how the owner,
   document checklist and status are checked before data is saved.
7. Read `review_action()` to see how reviewer permissions, status changes
   and activity records are handled together.

Do not try to learn the whole file at once. The authentication helpers are
included because applicant records should belong to their account from the start.

## Run the checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Checks use temporary databases and do not modify local application data. They
cover password hashing, account validation, CSRF, private record access,
draft creation/editing, escaped output, file uploads and downloads, submission
requirements, locked records, reviewer permissions and decisions, resubmission,
dashboard search/filter scoping, summary access restrictions, renewals, reminder
boundaries, report date filters, export access and CSV escaping, administrator permissions, staff creation,
assignment/reassignment, notification recipients/read state/pagination/access,
PDF version retention and download access, checklist approval requirements/reset/access,
stale checklist forms, message recipients/access/validation/pagination/retry handling,
review planning permissions, date boundaries, scope, ordering and restart persistence.
These are Flask request/database checks. Browser layout and public deployment
need separate verification.

## Milestones

1. **Complete — Accounts and drafts:** company form, saved draft, reference and editing.
2. **Complete — Attach and submit:** sample PDF uploads, document checklist and submission.
3. **Complete — Reviewer workflow:** assignment by starting a review, decisions, notes, corrections and resubmission.
4. **Complete — Dashboard and summary:** status totals, search, status filters and printable demo approval summaries.
5. **Complete — Renewals:** linked renewal drafts and in-app sample licence expiry reminders.
6. **Complete — Reports:** filtered application reporting and CSV exports.
7. **Complete — Administration:** reviewer accounts, assignments and oversight.
8. **Complete — Notifications:** personal inboxes and workflow updates.
9. **Complete — Document history:** numbered PDF versions and historical downloads.
10. **Complete — Review checklist:** saved checks, progress and approval requirements.
11. **Complete — Application messages:** saved conversations and reply notifications.
12. **Complete — Review planning:** priorities, target dates, timing totals and queue filters.
13. **Complete — Approved suppliers:** latest approvals, licence expiry and directory filters.
14. **Complete — Reviewer workload:** case counts by assignment, timing and linked case lists.
15. **Complete — Activity log:** searchable cross-case history with actor and date filters.
16. **Complete — Renewal comparison:** saved changes next to the previous approval.
17. **v1.0 — Portfolio release:** demo walkthrough, Windows setup and recording script.

Possible later additions include
email delivery, an Arabic interface and AI-assisted summaries.

## Scope

This version listens only on your own computer and is for learning with fictional
data. It has not been assessed as a production supplier-registration service.
Public deployment would require further work, including HTTPS/secure cookie
configuration, login rate limiting, account verification/recovery, monitoring,
backups and an appropriate approach to real applicant data.

The illustrative licence fields are not an official government document checklist.
The app does not check a live licence registry, send emails or issue permits.
Uploads are limited to demonstration PDFs of at most 2 MB each. The app checks
the extension and PDF markers; it does not inspect PDF content for malware.
Documents are stored in SQLite. The owner, an authorized reviewer and an
administrator with access to the submitted case can download them.

## AI assistance and interview honesty

This project was generated with AI assistance. Use it to learn, make changes
and test the behaviour. In interviews, explain which parts you worked through
and demonstrate the code you understand. This ZIP includes milestones 1–17.

## Create a reviewer on a fresh installation

Existing reviewer accounts still work. If this is a new installation, stop the
app and run:

```powershell
.\.venv\Scripts\python.exe -m flask --app app create-reviewer
```

Enter a demo password of 12–128 characters twice. The reviewer email defaults to
**reviewer@example.com**. Use `--email another-reviewer@example.com` to choose a
different demo account. Existing accounts are never promoted or overwritten.
Start the app again and sign in with that reviewer in a separate browser session.

Review flow: **Submitted → Start review → Under review → Save checklist → Approve / Request changes /
Reject**. Changes requested reopen details and document uploads for the owner.
After the owner resubmits, the assigned reviewer can resume the review unless
an administrator reassigns the case.

Summary PDFs are created through the browser print dialog, not automatically
downloaded or issued by a government system.

## Renewal behaviour

A renewal is a new application record linked to an existing approved one.
The applicant owns both records; documents are not copied. Saving/submitting
requires a sample expiry later than the previous approved expiry. Reviewers
see the previous reference and expiry when checking the renewal. The comparison
adds the previous company name, category and sample licence reference without
granting access to the earlier case's documents, contacts or messages.

The original approval is immutable and remains in history. Only the latest
approved renewal in a chain contributes licence expiry reminders. Pending
renewals keep the existing licence reminder visible. Reminders use the Dubai
calendar date and a 30-day window. They are displayed during dashboard requests;
there is no background scheduler or outbound message service.

Renewal creation uses a SQLite write transaction and returns an existing
non-rejected renewal if one already exists. A rejected renewal remains saved
and allows another attempt from the earlier approval.

## Report and export behaviour

Reports and CSV use the same server-side filtering function. Date filters use
the stored Dubai-local creation date and include the entire start/end dates.
Counts reflect current status among matching records, not historical decision
counts within a period. Each application/renewal is a separate record.

Applicants see their own applications only. Reviewers see unassigned submissions
and their own assigned cases, matching their review queue. Administrators see post-submission records across reviewers, excluding Draft
applications. CSV downloads require the same signed-in role and permission scope. Passwords, document bytes, session
secrets and reviewer notes are not included in CSVs.

Exports use Python's csv module with quoted fields and UTF-8 with a byte-order
mark for common spreadsheet software. Formula-like text gets a leading
apostrophe. These are live exports; later changes can produce different results
with the same filters. Zero-result exports contain the column headings.

## Administrator setup and role boundaries

Follow the administrator creation command in [ADMIN_GUIDE.md](ADMIN_GUIDE.md).
The default email is **admin@example.com**; choose the password interactively.
The command rejects existing emails rather than changing an existing role.
Public registration always creates applicants; the administrator reviewer form
always creates officers, regardless of any extra role fields in a request.

Administrators can view post-submission applications, documents, approval
summaries and reports. They cannot see private Draft records or use reviewer
decision endpoints. They can create reviewers and manage assignments for
Submitted or Under review applications. Approved/Rejected records are final;
Changes requested records must be resubmitted before reassignment.

Assignment uses a SQLite write transaction and compares the submitted activity
revision with the current one. A stale form cannot overwrite a newer review or
assignment. Reassignment updates the existing reviewer link, returns the
application to Submitted, and appends an actor/time/note entry to its history.
Former reviewers immediately lose case, document and summary access. Selecting
the already assigned reviewer makes no change.

## In-app notification behaviour

Notifications reference immutable activity entries and a recipient account.
They are inserted in the same transaction as a submission, review action or
assignment. A unique recipient/event constraint prevents duplicate deliveries
for an event. The actor does not receive their own event notification.

Submission notifies administrators and either the assigned reviewer or all
current reviewers for an unassigned case. Starting a review and recording a
decision notify the applicant. Assignment notifies the applicant and the
new/previous reviewers. Draft saving, document replacement and renewal draft
creation do not notify staff.

All inbox queries and read updates are scoped to the signed-in account.
Opening an entry uses a POST with CSRF and constructs its destination on the
server after checking current permissions. Stale reviewer notifications remain
as history but do not restore access to reassigned cases. Reading a notification
does not alter application status or activity history.

Notifications are generated only for actions after installing this milestone.
Existing history is not backfilled. There is no outbound email, push service,
polling or background scheduler. Refreshing a page loads current unread counts.
The existing computed licence expiry reminders remain separate.

## Document history behaviour

On startup, each existing current PDF is copied into a version-1 history row
only if that document has no version records yet. Migration does not modify
the original PDF, application, activity or notification records, and repeated
startup does not create duplicate versions. Previously overwritten files from
older milestones are not recoverable.

Uploads use the existing SQLite write transaction. Updating the current
document, inserting the next numbered historical copy and logging activity
commit together. Historical records are append-only through the app. Viewing
history does not restore or change the active file. Each renewal/application
and each document kind has its own sequence.

Current document bytes remain in application_documents for compatibility;
document_versions retains the historical copies. This duplicates the current
PDF in a small learning database and storage grows with uploads. Each upload
is still limited to 2 MB. No version files or database are shipped in the ZIP.

History and version download endpoints load the current account and check
current application access on every request. An administrator cannot read a
private Draft; an applicant cannot read another applicant's files; a former
reviewer cannot access versions after reassignment. Downloads are attachments
with a version suffix and no-store headers.

## Review checklist behaviour

The four checks are manual confirmations by the assigned reviewer, not automated
validation of PDF contents or a live government licence check. The reviewer
opens the current files, ticks the items they have checked and clicks **Save
checklist**. Ticking without saving does not enable approval. The saved count
is based on database values, not temporary browser checkbox state.

Only the assigned reviewer can save while the case is Under review. Each save
uses CSRF protection, a SQLite write transaction and the current activity revision.
An outdated form receives a conflict response instead of overwriting newer work.
Saving unchanged choices does not create another event. Saves do not generate
notifications or change application status. The activity records the saved items,
actor and time; those entries are visible to the applicant and authorized staff.

Resubmission and reviewer reassignment delete the current checklist in the same
transaction as the workflow change. The next review starts unchecked, including
when the same reviewer resumes after corrections. A no-op assignment to the same
reviewer preserves progress. Renewal applications have their own separate checks.
Historical checklist save events remain in the timeline after a reset.

Existing Approved/Rejected records are not changed and no checks are fabricated
for earlier decisions. Existing Under review cases start with an empty checklist.
Request changes and rejection still require an applicant-visible note but do not
require a completed checklist. Approval additionally rechecks the licence expiry,
renewal expiry rule and presence of both current documents on the server.

## Application message behaviour

The applicant and assigned reviewer can send messages while an application is
Submitted, Under review or Changes requested. Messages begin only after reviewer
assignment (including self-assignment by Start review). There is no conversation
page for a private Draft. Administrators can read post-submission conversations
but cannot send as either party. Approved and Rejected threads remain readable,
with new sends blocked on the server. Renewals have separate conversations.

All requests reuse current case-access checks. A new assigned reviewer can read
the full prior thread; the former reviewer immediately loses access. The page
explains this audience. A hidden reviewer identifier records whom the sender saw;
if assignment changed, sending returns a conflict with the text retained for review.
Old notification links also recheck current access. No message contents are copied
into activity descriptions or notification text; the thread holds the contents.

Messages accept 1–1500 characters after trimming outer whitespace, as escaped
plain text, including Unicode and line breaks. The server rejects null characters.
There are no message attachments, editing, deletion, email, push or live polling.
Each page shows at most 20 messages in send order; the default is the latest page.
Refresh to see new replies. Reading Messages directly does not mark inbox entries
as read; the existing notification open/read controls manage that state.

Sending uses CSRF, server-controlled author/role, a SQLite write transaction, and
a unique author/send-token constraint. An identical retry redirects to the saved
conversation without a second message, activity entry or notification. Reusing the
same token for different text or another case is a conflict. The message, activity
entry and one notification for the other party commit together.

Messaging updates the application's latest-activity time, but does not change its
status, current documents or saved checklist. As with other application activity,
it makes an already-open review/assignment decision form stale; reload that form
before deciding. A question does not substitute for a formal Request changes decision.
Existing review notes are not converted to messages and old records are preserved.

## Review priority and target-date behaviour

Administrators can update a plan while a case is Submitted, Under review or
Changes requested. Priority is Normal, High or Urgent, with an optional calendar
date. Canonical YYYY-MM-DD dates are validated server-side. Past dates are allowed
for managing an existing backlog; an empty date clears the target. Applicants and
reviewers can read their accessible case plan, but cannot change it. A target is
an administrative planning date for this demo, not a live government service promise.

Only Submitted and Under review are active for timing. A target earlier than
Dubai's current calendar date is overdue; today is Due today; a later date is
upcoming. An active undated case is No target date. Changes requested is Waiting
for applicant, even if its saved target is in the past. Approved/Rejected is
Completed and read-only. These labels and counts are computed on page loads;
refreshing generates no activity or notifications. Historical completion timing
and service-level performance metrics are not calculated.

Staff queues keep the existing reviewer/admin case permissions. Timing totals
cover the full authorized active scope, independent of list filters, just as the
status totals cover the full workspace. Timing filters always select only active
cases; combining Approved with Overdue therefore produces no matching rows.
Normal priority also matches older cases with no saved plan row. Applicant list
ordering and the existing creation-date Reports/CSV filters are unchanged.

Staff ordering is active cases, waiting cases, then final cases. Within each group,
Urgent comes before High and Normal, then earlier target dates before later dates,
then undated cases; the previous newest-activity ordering breaks ties. A lower
priority overdue case can therefore follow a higher priority future-dated case.
Use the Overdue filter when the due date is the main concern.

Plan writes use CSRF, an administrator role check, a SQLite write transaction and
the current activity revision. Stale forms cannot overwrite newer work. Unchanged
choices create no row/event/notification. Real changes atomically save the plan,
update latest activity time, record old/new choices and notify the owner and current
reviewer (if any). The plan and its history are visible to the applicant. No message
contents, private notes, passwords or document bytes enter those notifications.

Changing a plan does not change workflow status or reset review checks. As with
messages and other activity, already-open decision/assignment forms must refresh
before their revision can be accepted. Corrections, resubmission and reassignment
preserve the plan, while the existing checklist reset rules still apply. A new
renewal starts with default Normal/no target, rather than copying the old plan.
