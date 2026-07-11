# Ship it — get Themes Agent live on GitHub (~5 min)

## Step 0 — remove the stray `.git` folder (one time)
An empty `.git` shell got left in this folder and must be deleted first.
- **Easy way:** open this folder in File Explorer → View → tick **Hidden items** → delete the `.git` folder.
- **Or PowerShell:** the command block below deletes it for you.

## Path A — PowerShell (fastest if you have Git installed)
Open **PowerShell**, paste this whole block:

```powershell
cd "$env:USERPROFILE\OneDrive - Smith Point Capital, LLC\Desktop\Themes Agent"
Remove-Item -Recurse -Force .git -ErrorAction SilentlyContinue
git init
git add -A
git commit -m "Themes Agent: fund + tailwind intelligence dashboard"
git branch -M main
```

Then create the GitHub repo and push. If you have the GitHub CLI (`gh`):
```powershell
gh auth login          # first time only; pick GitHub.com > HTTPS > login in browser
gh repo create themes-agent --public --source=. --push
```
No `gh`? Create an empty repo at https://github.com/new named **themes-agent** (no README), then:
```powershell
git remote add origin https://github.com/<your-username>/themes-agent.git
git push -u origin main
```

## Path B — GitHub Desktop (no terminal)
1. Delete the `.git` folder (Step 0).
2. GitHub Desktop → **File → Add local repository →** pick this folder → click **create a repository** → **Publish repository**.

## Turn on the autonomy (both in the repo's Settings)
1. **Settings → Actions → General → Workflow permissions → Read and write permissions → Save.**
2. **Settings → Pages → Source: Deploy from a branch → `main` / (root) → Save.**
   Your live dashboard: `https://<your-username>.github.io/themes-agent/`
3. **Actions tab → "Update Themes Agent dashboard" → Run workflow** to test now. It scrapes the web, rebuilds, commits; the site updates in ~1 minute. After this it runs itself every Monday.

## Public vs private
GitHub Pages is **free on public repos**. If you make the repo **private**, the live `github.io` site needs a paid plan (GitHub Pro/Team) — otherwise everything still works, you'd just open `index.html` locally instead of via the URL. All data here comes from public sources, so a public repo is fine for a trial; you can switch it to private later in Settings.
