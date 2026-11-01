# Job Hunt HQ

A personal job-search assistant: it finds jobs, scores how well each one fits you, writes tailored cover letters,
builds your CV, fills in application forms and tracks every reply in Gmail – in one place.

**Built by [Rashid Idle](https://github.com/RIDLE-lab) together with Claude (Anthropic's AI).** Rashid came up
with the idea, decided what it should do and how it should look, tested it on his own job search and steered every
change; the code was written in collaboration with Claude.

## What it does

- **Finds jobs** on Reed, Adzuna and The Talent World, and from LinkedIn and Indeed job-alert emails – within the
  distance you choose of your home town or postcode.
- **Scores every job (0–100) and says why:** job title, skills in the advert, level, salary and location. It flags
  blockers such as "needs fluent German".
- **Writes a tailored cover letter** for each job, plus ready-to-copy answers for common form questions.
- **Create CV:** build a CV step by step (or upload yours and improve it), pick one of three designs, download it as
  PDF or Word, and get a version tailored to each job – reordered, never invented.
- **Fills application forms:** a browser button fills the employer's form and attaches your CV and letter. On your
  own PC, *Apply for me* drives a browser through the whole application and stops for you to press Submit.
- **Tracks every application** from Gmail: acknowledged, pre-screen, assessment, interview, second stage, offer,
  rejected – with next steps grouped by month.
- **Accounts:** invite-only sign-up, each person's data kept completely separate, and a feedback page for the owner.

You always press each employer's **Submit** yourself, after a quick check.

**Built with:** Python, Flask, SQLite, Jinja, Playwright, ReportLab and python-docx, with plain HTML, CSS and
JavaScript. Runs on a Windows PC (`run.bat`) or as a website (Docker – see [HOSTING.md](HOSTING.md)).

---

## 1. Install Python (once)

1. Download Python 3.12 or newer from https://www.python.org/downloads/windows/
2. In the installer, tick **"Add python.exe to PATH"**, then click Install.

## 2. Start the app

Double-click **`run.bat`**. The first time, it installs what it needs, which takes about a minute. Your browser then opens at http://127.0.0.1:5055.

Keep the black window open while you use the app, and close it to stop.

## 3. Add your two browser buttons (the main way to apply)

1. In the app, open **Setup**.
2. Drag both yellow buttons, **Send to Job Hunt HQ** and **Fill this application**, onto your browser's bookmarks bar. Press Ctrl+Shift+B if the bar is hidden.

**Applying for a job then takes four clicks:**

1. On the job advert (LinkedIn, Indeed or any job site), click **Send to Job Hunt HQ**. The app scores the job and writes your cover letter.
2. Click the site's **Apply** button to reach the employer's form, for example Morgan Law, Greenhouse, Lever or Workday.
3. Click **Fill this application**. It:
   - fills your name, email, phone, address, LinkedIn, current job, notice period, salary expectation and right to work
   - fills the message, cover letter and "why…" boxes
   - attaches your CV and a PDF of this job's cover letter
   - outlines everything it filled in **yellow**, and anything you should personalise in **red**
4. Check the form, answer anything left blank, and press the site's **Submit**. Then press **I've submitted – mark as applied** in the blue box, and your tracker updates itself.

**Multi-step forms (Workday and similar):** press **Fill this step** in the blue box on each page. On Workday's "Autofill with Resume" page it uploads your CV for you. Drop-downs like Country or Phone type, and anything else it can't fill, are in **Copy answers** in the blue box: every pre-written answer with a Copy button.

**The real application link:** the first time you use the Fill button on an employer's form, the app saves that address. The job's page in Job Hunt HQ then shows **Application link** with **Open application form**, so next time you can skip LinkedIn.

**A whole search at once:** on a LinkedIn or Indeed search results page (for example "Human Resources", London Area, Past 24 hours), click **Send to Job Hunt HQ** and choose **OK** to send every job in the list, each with its salary and how long ago it was posted. Scroll to the bottom of the list first: LinkedIn only shows the details of jobs you've scrolled past. Cover letters are written when you open a job.

**Notes:**
- **It never presses Submit**, so you always get the final check.
- **The pop-up window:** both buttons briefly open a small Job Hunt HQ window. If your browser blocks it, allow pop-ups for that site.
- **Wrong job?** The Fill button fills for the job you last sent or opened in the app. To change it, use the "Filling for" menu in the blue box.
- **Private key:** the Fill button holds a private key, so no other website can read your details from the app. If you ever share your bookmarks, delete `data\access_token.txt` and drag the button again.
- **Empty advert:** if a site changes its layout and the advert comes through empty, highlight the advert text before clicking Send.
- **Backup:** **Add a job** in the app also accepts a pasted link. Links from SmartRecruiters, Greenhouse and Lever are read from those systems' public job feeds, so they come through complete.

## 4. Apply for me (the robot)

On a job's page in the app, press **Apply for me**. A separate browser window opens (Chrome, or Edge if you don't have Chrome) and the **Apply for me** page in the app shows what it's doing.

**What it does by itself:**
- Clicks **Apply** (on Workday it picks "Autofill with Resume" or "Use My Last Application").
- Fills your details, uploads your CV and cover letter, and types City-style fields and picks them from their list.
- Answers the usual questions from your details: right to work (Yes), sponsorship (No), country, phone type, notice period, salary.
- Presses **Next** / **Save and Continue** until the final page.

**When it stops and asks you** (on the Apply for me page, with a notification if it's in the background):
- **Sign in or create an account:** do it in the robot's window, then press **Continue**. The window keeps its own sign-ins, so each site only asks once. It never types passwords.
- **"I'm not a robot" checks:** tick it yourself, then **Continue**.
- **Questions it can't answer**, such as "How did you hear about us?", "Do you have a driving licence?", equality monitoring and privacy agreements. It shows each one with a suggested answer where it has one. Your answers are remembered for later applications unless you untick **Remember**.
- **The final page:** it never presses Submit. Check the application in the window and submit it yourself. It notices the "thank you for applying" page and marks the job as applied, or you can press **I've submitted**.

**Your career details:** the **My career** page holds your work history, education, skills and languages, taken from your CV. The robot uses them on "My Experience" pages: it adds a Work Experience row per job and fills title, company, location, dates and description, adds your qualifications (picking the right degree level) and types your skills into the Skills box. Keep it up to date when you change jobs or finish a qualification; it's saved in `data\career.json`. The same page lists every answer the robot remembers, so you can change or delete any of them.

**Taking over:** press **Pause – I'll take over** any time, do what you like in the window, then **Continue**.

If it gets stuck on a page, it says so. Sort it out in the window and press **Continue**, or finish by hand. The Fill button and Copy answers work in that window too.

**Where it works:** the employer's own application pages (Workday, SmartRecruiters, Greenhouse, Lever, Morgan Law and similar). It never runs on LinkedIn, Indeed, Reed or other job boards, whose rules ban automated applying. If a job only has a job-board link, open the advert, click its Apply button, and press **Fill this application** once on the employer's page. The app saves that link, and **Apply for me** works from then on.

**Optional AI answers:** with an Anthropic API key in `config.yaml` (see section 8), it suggests answers to written questions like "Describe a time you…" from your CV. You always see these before they're entered. It never suggests answers to personal or equality questions.

## 5. Job sources

**The Talent World** (thetalentworld.co.uk) is switched on already. Each refresh reads its newest HR jobs from the site's public sitemap, pausing a second between pages as the site asks. Jobs that are too far away or too senior are filtered out, as with every source. Turn it off with `talentworld: false` in `config.yaml`.

### Optional: free Reed and Adzuna keys (more jobs)

Open **`config.yaml`** in Notepad. It's created on first run, copied from `config.example.yaml`.

| Source | Where to get it | Put it in config.yaml |
|---|---|---|
| Reed | https://www.reed.co.uk/developers/jobseeker – sign in, then "Get API key" | `reed_api_key` |
| Adzuna | https://developer.adzuna.com/signup – shows an *Application ID* and *Application Key* | `adzuna_app_id`, `adzuna_app_key` |

In the same file you can change the job titles to search, locations, distance, minimum salary and words to exclude. Then press **Refresh now** in the app.

## Job emails and automatic refresh

While the app is open it looks for new jobs every 3 hours by itself (change `app: auto_refresh_hours` in `config.yaml`; 0 turns it off). Each refresh can email you the new jobs it found, best match first, with your match % and a link to each advert.

To switch the emails on (about 3 minutes):
1. Your Google account needs **2-Step Verification** on: https://myaccount.google.com/signinoptions/twosv
2. Go to https://myaccount.google.com/apppasswords, type a name such as "Job Hunt HQ" and press **Create**. Google shows a 16-letter code. Copy it. (It only lets this app send email from your account; you can delete it there any time.)
3. Open `config.yaml` in Notepad. Under `email:`, set `enabled: true` and paste the code between the quotes after `gmail_app_password:`. Save.
4. Close the black window, run `run.bat` again, open **Setup** and press **Send me a test email**.

Only jobs scoring at least `min_score` (50 = Good fit) are emailed, at most 20 per email. Jobs you send in yourself with the browser button aren't emailed, since you've already seen them.

## 6. Connect Gmail (reads replies and LinkedIn alerts)

**Easiest way:** if you've set up the Gmail app password for job emails (above), set `gmail: enabled: true` in `config.yaml` and you're done – the app reads your mail with the same code. It only reads: it never deletes or moves anything and leaves unread mail unread.

**Then turn on job alerts** so new jobs arrive by themselves: on a LinkedIn search (for example Human Resources, London Area) switch on **Get job alerts for this search** and choose daily emails; on Indeed, **Get new jobs for this search by email**. Each refresh adds those jobs, scores them, and the job email tells you about the good ones.

The other way below uses Google Cloud instead of an app password.

The app gets **read-only** access. It can't send, delete or change anything.

1. Go to https://console.cloud.google.com/ and create a project (for example "Job Hunt HQ").
2. **APIs & Services → Library**: search for **Gmail API** and click **Enable**.
3. **APIs & Services → OAuth consent screen** (also called *Google Auth Platform*):
   - User type **External**. App name "Job Hunt HQ". Use your Gmail for the support and contact emails.
   - Under **Audience**, add yourself (your Gmail address) as a test user.
   - Then click **Publish app** so its status is **In production**. If you skip this, Google signs you out every 7 days.
4. **Credentials → Create credentials → OAuth client ID**, application type **Desktop app**. Download the JSON file.
5. Rename that file to **`credentials.json`** and put it in this folder, next to `app.py`.
6. In `config.yaml`, set `gmail: enabled: true`.
7. Press **Refresh now**. A Google sign-in page opens. You'll see "Google hasn't verified this app"; that's expected, because it's your own private app. Click **Advanced → Go to Job Hunt HQ → Continue**.

**LinkedIn and Indeed jobs:** neither site offers a jobs API to job seekers, and both ban scraping, so the app uses their job-alert emails instead.
- **LinkedIn:** search a job title, turn on **Set alert**, and choose daily emails.
- **Indeed** (uk.indeed.com, signed in with your Gmail): search, for example, "HR Advisor" near Southend-on-Sea, then turn on **Get new jobs for this search by email**.

Each alert email adds its jobs to your dashboard automatically, with a link back to the advert. For any other job, use **Add a job** and paste the link and the advert text.

## 7. Refresh automatically every morning (optional)

1. Press **Refresh now** in the app once first, so you're already signed in to Google.
2. Open **Task Scheduler** from the Start menu, then **Create Basic Task…**
3. Name it "Job Hunt HQ refresh". Choose **Daily**, at a time like 08:00.
4. Choose **Start a program** and browse to **`run_daily.bat`** in this folder.
5. Finish. Each run's results are logged in `data\refresh.log`.

## 8. Better cover letters (optional)

By default, letters are built from evidence paragraphs taken from your CV, choosing the ones that best match the advert. This is free and needs no internet.

For letters fully written around each advert, create a key at https://console.anthropic.com/ and paste it into `ai: anthropic_api_key`. This is billed per use, typically a few pence per letter, and is separate from your Claude subscription.

**Always read a letter before you send it.**

---

### Daily use

1. Open the app and press **Refresh now**, or let the morning task do it.
2. Go through **Jobs to review** from the highest score down. Open a job, then:
   **Write cover letter → Open application → attach CV and letter → Submit → I've applied**.
3. Look at **Needs your attention** for interviews and screening calls. Any status can be changed by hand from the Applications table.

### Your data

Everything is stored in `data\jobhunt.db` on your PC. To start again, close the app and delete that file.

### Files

```
app.py              the dashboard (Flask)
jobhunt/sources.py  Reed and Adzuna
jobhunt/fetch_page.py  reads a job from a pasted link
static/bookmarklet.js  the Send to Job Hunt HQ button
static/fill.js      the Fill this application button
static/fill_core.js form filling, shared by the Fill button and the robot
jobhunt/agent.py    Apply for me (the robot browser)
jobhunt/answers.py  answers to form questions (remembered, from your details, or Claude)
templates/robot.html  the Apply for me page
templates/bridge.html  passes details from the app to the Fill button
jobhunt/matcher.py  fit scoring
jobhunt/letters.py  cover letters
jobhunt/classify.py email sorting and LinkedIn alert reading
jobhunt/gmail_sync.py  Gmail (read-only)
jobhunt/refresh.py  one refresh (also used by run_daily.bat)
jobhunt/seed.py     optional starter list of applications
tests/test_core.py  checks: python tests/test_core.py
```

## Credits

Created by Rashid Idle with Claude by Anthropic. Licensed under the MIT Licence – see [LICENSE](LICENSE).
