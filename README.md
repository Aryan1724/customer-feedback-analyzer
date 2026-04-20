# 📊 Customer Feedback Analyzer

AI-powered consulting deliverable that turns raw customer reviews into a McKinsey-style briefing — executive summary, priority matrix, and ranked recommendations — in under three minutes.

---

## ✨ Features

- **Executive Summary** — auto-generated consulting-style paragraph covering sentiment health, the biggest risk, and the biggest opportunity.
- **KPI Scorecard** — total reviews, % negative sentiment, and the top issue at a glance.
- **Sentiment Donut** — Strongly Positive / Neutral / Strongly Negative breakdown.
- **Issue Frequency Bar Chart** — the five core operational buckets ranked by mentions.
- **Priority Matrix (2×2)** — Impact vs Frequency with labeled quadrants: Quick Wins, Major Problems, Low Priority, Monitor. Bubble size = severity.
- **Sentiment Trend** — monthly line chart when a date column is available.
- **Ranked Recommendations** — 3–5 actions with quantitative references, ordered by impact.
- **Verbatim Evidence** — 2 real customer quotes per major issue.
- **CSV Export** — one-click download of the full analysis summary.

---

## 🛠️ Tech Stack

| Layer | Tool |
| --- | --- |
| UI | Streamlit |
| LLM | Anthropic Claude (via `anthropic` Python SDK) |
| Data | Pandas |
| Viz | Plotly |
| Config | python-dotenv |

---

## 🚀 Setup (Local)

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd customer-feedback-analyzer

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your API key
cp .env.example .env
# then edit .env and paste your Anthropic key

# 5. Run
streamlit run app.py
```

The app launches at `http://localhost:8501`.

---

## ☁️ Deploy on Streamlit Cloud

1. Push this repo (without `.env`) to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app** → select your repo → `app.py`.
3. Open **Settings → Secrets** and paste:
```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
```
4. Click **Deploy**. The public URL is your live demo link for your resume.

---

## 📂 Recommended Kaggle Datasets

Try the app against any of these free, well-structured review datasets:

1. **Amazon Fine Food Reviews** — 568K+ reviews with text, score, date.
   https://www.kaggle.com/datasets/snap/amazon-fine-food-reviews
2. **Trip Advisor Hotel Reviews** — 20K hotel reviews with ratings.
   https://www.kaggle.com/datasets/andrewmvd/trip-advisor-hotel-reviews
3. **Women's E-Commerce Clothing Reviews** — 23K reviews with department, rating, recommendation flag.
   https://www.kaggle.com/datasets/nicapotato/womens-ecommerce-clothing-reviews

After downloading, upload the CSV directly in the app and pick the review-text column.

---
---
