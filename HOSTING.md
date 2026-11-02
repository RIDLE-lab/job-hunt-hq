# Putting Job Hunt HQ online (invite-only website)

Your PC version keeps working exactly as now (`run.bat`). These steps make a second copy that runs as a website, so
people you invite can sign in from anywhere. It uses **Render** (render.com) – everything is done in a web browser.

**Cost:** Render's *Starter* plan (about $7 a month) plus a 1 GB disk (about $0.25 a month). The free plan can't keep
files, so everyone's data would vanish on each restart – don't use it.

**What's different on the website:** *Apply for me* (the robot) only runs on your PC, because it needs a screen for
you to sign in to job sites. On the website everyone uses the **Fill this application** browser button instead.
Everything else – job search, scores, letters, Create CV, Applications, Gmail – works the same.

---

## 1. Put the code on GitHub (private)

1. Go to github.com → **New repository** → name it `job-hunt-hq` → choose **Private** → Create.
2. On the new page, click **uploading an existing file**.
3. Drag in everything from `Documents\JobHuntHQ` **except** `config.yaml`, `credentials.json`, the `data` folder and
   the `.venv` folder. (Those are private; `.gitignore` lists them.)
4. Press **Commit changes**.

## 2. Create the website on Render

1. Sign up at render.com with your GitHub account.
2. **New → Web Service** → pick `job-hunt-hq`. Render sees the `Dockerfile` and uses it.
3. Instance type: **Starter**.
4. **Advanced → Add Disk:** name `data`, mount path `/data`, size 1 GB.
5. **Environment variables** – add these:

   | Name | Value |
   |---|---|
   | `JOBHUNT_SECRET` | a long random string (mash the keyboard – 40+ characters) |
   | `JOBHUNT_SETUP_CODE` | a one-off code you make up, e.g. `blue-kettle-7731` – needed to create the owner account |
   | `JOBHUNT_CONFIG` | `/data/config.yaml` |

6. Press **Create Web Service**. After a few minutes you get an address like `https://job-hunt-hq.onrender.com`.

## 3. Add the server settings (job-site keys)

Your Reed and Adzuna keys (and the optional Claude key for letters) live in `config.yaml`, which isn't on GitHub.
In Render, open the service → **Shell**, and paste:

```
cat > /data/config.yaml <<'END'
sources:
  reed_api_key: "YOUR-REED-KEY"
  adzuna_app_id: "YOUR-ADZUNA-ID"
  adzuna_app_key: "YOUR-ADZUNA-KEY"
app:
  auto_refresh_hours: 6
END
```

(Copy the real values from your own `config.yaml`. If CV-Library gives you a partner API key – ask
partners@cv-library.co.uk – add `cvlibrary_key: "…"` under `sources:` too, and CV-Library jobs are searched as well. Each person's own details, job titles and Gmail are in their
account – not here.) Then press **Manual Deploy → Restart**.

## 4. Move your account across

1. On your **PC**: Job Hunt HQ → your name (top right) → **Account and password** → **Download my data**. You get
   one zip with your jobs, applications, emails, My career, settings, letters and your CV.
2. On the **website**: open the address. You're asked to create the owner account – enter your name, a username and
   password, the set-up code from step 2, and choose the zip under *Moving from your PC?*.
3. Done – it's all there. Remove `JOBHUNT_SETUP_CODE` from Render's environment variables afterwards.

## 5. Invite people

**People** (top menu) → **Make an invite link** → send them the link. Each link works once, for 14 days. They choose
their own username and password, then a short set-up: their details, the jobs they want, and their CV (upload one or
use **Create CV**). Nobody can see anyone else's jobs, applications, emails, CV or settings.

Forgotten password? People → **Reset link** next to their name, and send them that link.

## 6. Gmail on the website

Each person connects their own Gmail in **My settings → Gmail** with a Gmail *app password*
(myaccount.google.com/apppasswords). The `credentials.json` sign-in method only works on the PC.

## Backups

Account → **Download my data** any time. Render also lets you snapshot the disk.

## Security and misuse alerts by email (optional)

The website watches for signs that the Acceptable use rules are being broken (password guessing, made-up assistant
keys, a shared assistant file, bulk automated applications, a used invite link tried again, and reports from people
using it). Every alert is listed on the **People** page. To have them emailed too, add these on Render
(Environment → Add environment variable):

| Key | Value |
|---|---|
| `JOBHUNT_SMTP_HOST` | your mailbox's outgoing (SMTP) server, from your email provider's settings page |
| `JOBHUNT_SMTP_PORT` | `465` (or `587` if your provider says so) |
| `JOBHUNT_SMTP_USER` | the mailbox, e.g. `info@jhhq.co.uk` (defaults to `JOBHUNT_CONTACT`) |
| `JOBHUNT_SMTP_PASSWORD` | that mailbox's password |
| `JOBHUNT_ALERT_TO` | optional – where alerts go (defaults to `JOBHUNT_CONTACT`) |

Each problem is emailed at most once every 6 hours, and security records are deleted after 90 days.
