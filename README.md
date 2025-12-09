# ADC Daily Results Automation

Automated daily scraping of DartsAtlas tournament results for the Amateur Darts Circuit, with email distribution to regional directors.

## How It Works

1. **GitHub Actions** runs the scraper daily at 8:00 AM UK time
2. **Scraper** collects results from all 11 UK regions from dartsatlas.com
3. **Email** sends results to regional directors with attached text files

## Setup Instructions

### 1. Create GitHub Repository

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/adc-daily.git
git push -u origin main
```

### 2. Configure GitHub Secrets

Go to your repository → Settings → Secrets and variables → Actions → New repository secret

Add the following secrets:

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `SMTP_SERVER` | Email server | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USERNAME` | Your email login | `scott@example.com` |
| `SMTP_PASSWORD` | Email password or App Password | `your-app-password` |
| `EMAIL_FROM` | Sender address | `ADC Results <scott@example.com>` |
| `EMAIL_TO` | Recipients (comma-separated) | `claire@email.com,simon@email.com` |

### 3. Gmail Setup (if using Gmail)

If you're using Gmail, you'll need to create an **App Password**:

1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable 2-Factor Authentication if not already enabled
3. Go to "App passwords" 
4. Create a new app password for "Mail"
5. Use this 16-character password as `SMTP_PASSWORD`

### 4. Test the Workflow

You can manually trigger the workflow to test:

1. Go to Actions tab in your repository
2. Select "Daily DartsAtlas Results"
3. Click "Run workflow"

## Regional Directors

| Region | Director |
|--------|----------|
| Scotland | Claire Louise |
| Wales | Hywel Llewellyn |
| Ireland | John O'Toole |
| Northern Ireland | James Mulvaney |
| North East | Andrew Fletcher |
| Yorkshire & Humber | Adam Mould |
| North West | Paul Hale |
| Midlands | Karl Coleman |
| South West | Simon Rimington |
| South East & London | TBC |
| East of England | TBC |

## Files

- `dartsatlas_daily_results.py` - Main scraper script
- `send_results_email.py` - Email distribution script
- `.github/workflows/daily-results.yml` - GitHub Actions workflow
- `requirements.txt` - Python dependencies

## Environment Variables (for local testing)

```bash
export DA_SLEEP=1.0          # Delay between requests (seconds)
export DA_MAX_EVENTS=0       # 0 = no limit
export DA_FORCE_MIRROR=false # Use mirror proxy if direct fails
```

## Output

The scraper produces:
- **CSV file**: `dartsatlas_results_YYYY-MM-DD.csv` with all data
- **Social text files**: `social_RegionName_YYYY-MM-DD.txt` for each region with results

## Troubleshooting

### No results found
- Check if there were actual tournaments on the target date
- Try running manually with a specific date: `python dartsatlas_daily_results.py --date 2025-01-15`

### Email not sending
- Verify all secrets are correctly set
- For Gmail, ensure App Password is used (not your regular password)
- Check the workflow logs in GitHub Actions

### 403 Errors from DartsAtlas
- The scraper automatically falls back to a mirror proxy (jina.ai)
- If issues persist, try increasing `DA_SLEEP` value
