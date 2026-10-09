# Deployment

| Part | Where | Cost |
|---|---|---|
| Web app (Streamlit) | Streamlit Community Cloud, deployed from GitHub | Free |
| Database | Supabase (already set up) | Free tier |
| Scheduled pipeline: fetch, process, briefings, emails | GitHub Actions (`.github/workflows/pipeline.yml`) | Free for public repos; private repos get 2,000 minutes a month |
| AI | Gemini API | Free tier |

## 1. Database connection string that works from the cloud

GitHub Actions and Streamlit Cloud reach the internet over IPv4. Supabase's *direct* connection is IPv6-only on the
free tier, so the cloud needs the **Session pooler** string.

1. Supabase → Project Settings → Database → **Reset database password**. The old one was shared during development.
2. Connect → Connection string → **Session pooler**. It looks like
   `postgresql://postgres.<project-ref>:<password>@aws-<n>-<region>.pooler.supabase.com:5432/postgres`.
   Put the new password in it.
3. Put that string in `.env` as `DATABASE_URL` and check it locally:
   `.venv\Scripts\python scripts\init_db.py` should list the tables.

## 2. GitHub repository

The code is pushed to GitHub (`git push`). Secrets are never committed: `.env` and `eval/results/` are git-ignored.

Add these under the repository's **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `DATABASE_URL` | the Session pooler string from step 1 |
| `GEMINI_API_KEY` | your Gemini key |
| `APP_URL` | the Streamlit app address from step 3 (add it after deploying) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | optional, for real notification emails (Gmail: `smtp.gmail.com`, `465`, your address, an App Password) |

Without the SMTP secrets, notification emails aren't sent; the run log still records them.

Then **Actions → News pipeline → Run workflow → full** to test it once.

## 3. Streamlit Community Cloud

1. Sign in at share.streamlit.io with GitHub.
2. **Create app** → choose the repository, branch `main`, main file `streamlit_app.py`.
3. **Advanced settings**: Python **3.12**. In **Secrets**, paste (TOML format):

   ```toml
   DATABASE_URL = "postgresql://postgres.<project-ref>:<password>@aws-<n>-<region>.pooler.supabase.com:5432/postgres"
   GEMINI_API_KEY = "..."
   APP_URL = "https://<your-app>.streamlit.app"
   ```

   Streamlit makes these available to the app as environment variables, which is how the code reads its settings.
4. Deploy, then copy the app address into the `APP_URL` secret on GitHub too (for email links).

## 4. Check it works

- Open the app, sign in on **My preferences** with an email, and save. Today's Briefing should appear.
- Ask a question on **Ask AI**.
- GitHub → Actions: the **News pipeline** runs four times a day (full) and hourly (briefings). Each run's log shows
  what was fetched, kept and sent. `run_log` in Supabase keeps the same counts.

## Known limits

- **Free-tier quotas**: about 1,000 embeddings a day caps how much news is processed; the pipeline pauses and resumes
  on the next run when a quota is reached.
- **Sleeping app**: Streamlit Cloud puts apps to sleep after a period without visitors; the first visit wakes it (about
  30 seconds).
- **Demo sign-in**: email only, no password. Add Supabase Auth before real users.
- **Schedules** run in UTC and can start a few minutes late.
