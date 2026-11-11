# Publish GovVendor as a portfolio project

## 1. Use this clean source folder

Extract **GovVendor-Portfolio.zip** into a separate folder and open the folder containing `app.py` and `README.md` in VS Code. This bundle includes the **Gulf Trading LLC** heading and charcoal sidebar. Your current GovVendor installation and local demo records can stay in their existing folder.

## 2. Prepare the first commit

If this is a new repository, run these commands in the terminal opened in the extracted folder:

```powershell
git init -b main
git add .
git status --short
```

Check that the staged files contain the source, templates, static assets, tests, guides and sample PDFs. Do not publish `instance/`, `.venv/`, database files, credentials or real supplier documents. The included `.gitignore` excludes the local database and environment folders if you run the app before committing.

Then commit the files:

```powershell
git commit -m "Add GovVendor portfolio demo"
```

If you already have a GovVendor repository, use its existing clone instead of initializing another repository. Review its current changes before copying any files into it.

## 3. Add your GitHub repository

Create an empty GitHub repository named **GovVendor**. Copy its HTTPS repository URL, replace the example URL below, and run:

```powershell
git remote add origin https://github.com/YOUR-USERNAME/GovVendor.git
git push -u origin main
```

Open the repository after the push and confirm that the README renders and that `app.py`, `templates/` and `sample-documents/` are visible. Share the repository link when it is ready for recruiters. The repository shares the source code; the app is run locally using the README instructions.

## Suggested project description

> A Flask and SQLite supplier-registration demo with applicant, reviewer and administrator workspaces, document review, approval and renewal tracking.

## Optional demo media

Use **Demo walkthrough** and `DEMO_SCRIPT.md` to record a short walkthrough. Three useful screenshots are the homepage, the reviewer checklist and the renewal comparison. Use only fictional records and keep passwords out of the recording.
