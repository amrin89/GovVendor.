# Start GovVendor on your Windows computer

Use this guide to set up GovVendor for the first time. Use the separate portfolio folder to keep your existing app and saved records intact.
After setup, choose **Demo walkthrough** in the app. ADMIN_GUIDE.md explains how to create the demonstration staff accounts.

## 1. Extract the download

1. Download `GovVendor-Portfolio.zip`.
2. Open Downloads in Windows File Explorer.
3. Right-click the ZIP and choose **Extract All**.
4. Open the extracted **GovVendor-Portfolio** folder containing
   `app.py`, `schema.sql`, `templates`, `static` and `requirements.txt`.

## 2. Open the project in VS Code

1. Open VS Code.
2. Choose **File > Open Folder**.
3. Select the extracted **GovVendor-Portfolio** folder and click **Select Folder**.
4. Choose **Terminal > New Terminal**.
5. Check that the terminal path ends in `GovVendor-Portfolio`.

If CivicDesk or ParkBook is still running on port 5000, go to its terminal and
press **Ctrl+C** before starting GovVendor. Keep GovVendor in its own project folder.

## 3. Run three commands, one at a time

Create a Python environment:

```powershell
py -3 -m venv .venv
```

Install Flask:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the app:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000** in your browser. The page should say:
**Gulf Trading LLC. A clear path to registration.**

Keep the terminal open while using the app. Press Ctrl+C to stop it.
On later visits you only need to run the third command.

## 4. Create a demonstration account

Click **Create your account** and enter:

| Field | Example |
|---|---|
| Name | Demo Applicant |
| Email | applicant@example.com |
| Password | Choose a demo password of at least 12 characters |

No email is sent. Use fictional information and a password you do not use elsewhere.
Do not expect a confirmation email or password recovery in this first version.

## 5. Save your first company registration draft

Click **New registration** and enter:

| Field | Example |
|---|---|
| Company name | Gulf Trading LLC |
| Supplier category | Office supplies |
| Fictional trade licence reference | DEMO-LIC-104 |
| Sample licence expiry | Choose a date at least one year ahead |
| Contact name | Demo Applicant |
| Contact email | supplier@example.com |

Click **Save registration draft**. You should see the saved details, a reference
beginning with **GV-**, a **Draft** badge and an activity entry.

## 6. Check your progress

1. Refresh the page: the details should remain.
2. Click **Edit draft**, change the company name and save.
3. Open **My applications**: the updated company should appear once.
4. Stop and restart the app: your saved draft should remain.
5. Sign out. A signed-out browser should be directed to sign in before viewing drafts.

## 7. Submit and try the reviewer workspace

Open the saved draft. In **Document checklist**, upload
`sample-trade-licence.pdf` and `sample-company-profile.pdf` in their matching
rows. The files are in **sample-documents**. Click **Upload PDF** separately for
each file, then **Submit for demo review**. Follow the reviewer account and
review steps in [PROJECT_GUIDE.md](PROJECT_GUIDE.md#create-a-reviewer-on-a-fresh-installation).

## If something goes wrong

- **TemplateNotFound:** make sure `templates` is beside `app.py`, outside `.venv`.
- **No module named flask:** run the install command using `.venv\Scripts\python.exe`.
- **Address already in use:** stop the other local Flask app using Ctrl+C.
- **Form expired:** refresh the page, then try again.
- **Page not updating after editing Python or HTML:** save the file, stop Python,
  run the third command again and refresh. CSS changes may need Ctrl+F5.

If an error remains, keep the final lines of the VS Code terminal available for
troubleshooting. They are more useful than the browser's generic error message.
