# Administrator setup and reviewer assignments

Use this guide after installing GovVendor. Stop the app with Ctrl+C before running the account command.

## 1. Create your administrator account once

In the VS Code terminal for your existing GovVendor folder, run:

```powershell
.\.venv\Scripts\python.exe -m flask --app app create-administrator
```

Choose a new demo password of at least **12 characters**, press Enter, then type it again and press Enter. The characters do not appear while you type.

You should see **Demo administrator created: admin@example.com**.

If that email already belongs to another account, use a different demo email:

```powershell
.\.venv\Scripts\python.exe -m flask --app app create-administrator --email admin2@example.com
```

This command does not change any existing applicant or reviewer account.

## 2. Start GovVendor and sign in

```powershell
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000. Sign out of whichever account is currently open, then sign in with **admin@example.com** and your new demo password.

You should land on **Application administration**. The sidebar has **Administration**, **Reviewer accounts** and **Reports**.

## 3. Create a second reviewer through the app

1. Click **Reviewer accounts**.
2. Enter:
   - Reviewer name: **Demo Reviewer Two**
   - Demo email: **reviewer2@example.com**
   - Demo password: choose a demo password of at least 12 characters.
3. Click **Create reviewer account**.

Your earlier reviewer still exists. The new reviewer has a separate login and queue. No email is sent.

## 4. Assign a submitted application

1. Click **Administration**.
2. Open an application with status **Submitted**.
3. Under **Reviewer assignment**, choose **Demo Reviewer Two**.
4. You can add the note **Assigned to reviewer two for this demonstration**.
5. Click **Save assignment**.

The status stays **Submitted** until the selected reviewer clicks **Start review**.

If every existing application is Approved or Rejected, sign in as an applicant, create and submit a new fictional application, then return to the administrator account.

## 5. Verify the reviewer queue

1. Open a separate InPrivate/Incognito window, or sign out of the current account.
2. Sign in as **reviewer2@example.com**.
3. Open the assigned application and click **Start review**.
4. Check the company details and current PDFs, tick the four review checks and click **Save checklist**. All four saved checks are required for **Approve**. You can still request changes or reject with a note.

Assigned cases are visible to their assigned reviewer. Unassigned submissions are available for a reviewer to start. Applicants still see only their own applications.

## 6. Try reassigning a case

1. As administrator, open a **Submitted** or **Under review** application.
2. Choose a different reviewer and add a short reason, such as **Reassigned for the demo shift**.
3. Click **Save assignment**.

The application returns to **Submitted**. The new reviewer starts their own review with an empty checklist. Earlier checklist saves remain in activity. The previous reviewer loses access, and the applicant can read the assignment history and note in **Application activity**.

You cannot reassign an Approved or Rejected application. For **Changes requested**, wait until the applicant resubmits.

## What each role does

| Account | Main actions |
|---|---|
| Applicant | Prepare drafts, upload PDFs, submit, correct and renew |
| Reviewer | Review assigned/new submissions and record decisions |
| Administrator | Create reviewers, assign/reassign cases, inspect submitted records and view reports |

Administrators do not see private Draft applications, edit applicant data or make reviewer decisions. Their reports include applications after submission across the reviewer team. All records remain fictional demonstrations.

## 7. Set a review priority and target date

1. Sign in as **admin@example.com** and open a Submitted or Under review application.
2. Find **Review plan** near the top.
3. Choose **Normal**, **High** or **Urgent**.
4. Choose an optional **Target review date** and click **Save review plan**.
5. The applicant and assigned reviewer receive an in-app notification.

Changes requested cases can also have their plan adjusted, but they remain
Waiting for applicant and are excluded from overdue counts until resubmission.
Approved/Rejected plans are read-only. Reassignment preserves the case priority
and date; the new reviewer starts with the existing plan and an empty checklist.

Staff queues show Overdue reviews and Due today totals. Select a card or use
Review priority / Review timing filters alongside search and status. These timing
filters include only Submitted and Under review. Priority/date sorting puts
Urgent cases first within the active group, then High and Normal. Use Overdue
when you specifically want past-target cases regardless of priority.

## 8. Find approved suppliers

Use **Approved suppliers** in the sidebar to find the latest approval in each
registration chain. Search by company or approval reference and combine the
category and licence filters. An approved renewal replaces its previous approval
in the directory; **Administration** still holds the full case history.

## 9. Check reviewer workload

Use **Reviewer workload** in the sidebar to see open cases by reviewer and cases
waiting for assignment. Click a reviewer's **View cases** link or one of their
timing counts to open the matching list in Administration. Cases with
**Changes requested** count as open but are excluded from review timing totals.

## 10. Find case activity

Open **Activity log** to see recorded actions across submitted cases. Search for
a company, case reference, actor or action, and narrow by actor role and Dubai
date. Select the case reference to open the original case. Applications still
in Draft remain private.

## 11. Compare renewal details

Open a submitted renewal and choose **Compare renewal details**. The comparison
shows which saved company and sample licence fields differ from the linked
previous approval. Use **Back to renewal** to return to the case.
