"""
Customer Feedback Analyzer
AI-powered consulting-style insights from customer reviews using Anthropic's Claude.
"""

import os
import json
import time
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.express as px
from anthropic import Anthropic
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

st.set_page_config(
    page_title="Customer Feedback Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Swap to "claude-opus-4-5" for deeper analysis or "claude-haiku-4-5" for speed/cost
MODEL = "claude-sonnet-4-5"
BATCH_SIZE = 50
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, multiplied by attempt number

ISSUE_BUCKETS = ["Delivery", "Quality", "Pricing", "Support", "Packaging"]

# ---------------------------------------------------------------------------
# Claude client
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_client() -> Anthropic:
    """Return an authenticated Anthropic client (from env or Streamlit secrets)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets["ANTHROPIC_API_KEY"]
        except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
            api_key = None
    if not api_key:
        st.error(
            "ANTHROPIC_API_KEY not found. Add it to a `.env` file locally "
            "or to Streamlit Secrets when deploying."
        )
        st.stop()
    return Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Prompts — strict JSON-only outputs
# ---------------------------------------------------------------------------
BATCH_PROMPT = f"""You are a senior management consultant analyzing customer reviews for a Fortune 500 client.

Analyze the following customer reviews and return STRICTLY VALID JSON — no markdown, no code fences, no commentary, no text outside the JSON object.

Classify each review as exactly one of: "positive", "neutral", "negative".
Categorize recurring issues using ONLY these buckets: {", ".join(ISSUE_BUCKETS)}. Ignore any issue that doesn't fit.

Return this exact schema:
{{
  "sentiment": {{"positive": <int>, "neutral": <int>, "negative": <int>}},
  "per_review_sentiment": ["positive"|"neutral"|"negative", ... one entry per review in order],
  "issues": [
    {{
      "name": "<Delivery|Quality|Pricing|Support|Packaging>",
      "frequency": <int — count of reviews in this batch mentioning the issue>,
      "impact": <float 1-10 — business impact if left unresolved>,
      "severity": <float 1-10 — how severe a single mention tends to be>,
      "quotes": ["<short verbatim snippet>", "<short verbatim snippet>"]
    }}
  ]
}}

Rules:
- sentiment counts must sum to the exact number of reviews in the batch
- per_review_sentiment length must equal the number of reviews
- Include only issue buckets that actually appear; omit empty ones
- Quotes must be verbatim excerpts (≤ 25 words each), no paraphrasing
Return ONLY the JSON object.

REVIEWS:
"""

SYNTHESIS_PROMPT = """You are a senior McKinsey consultant preparing a final executive briefing from aggregated customer-review analytics.

Given the aggregated data below, return STRICTLY VALID JSON — no markdown, no code fences, no commentary — matching this schema exactly:

{
  "summary": "<2–4 sentence executive summary in consulting tone. Must explicitly cover: (a) overall sentiment health with a % figure, (b) the single biggest risk, (c) the single biggest opportunity.>",
  "recommendations": [
    "<Recommendation 1 — highest impact. Must include at least one specific number or % drawn from the data.>",
    "<Recommendation 2>",
    "<Recommendation 3>",
    "<Recommendation 4 (optional)>",
    "<Recommendation 5 (optional)>"
  ]
}

Produce 3–5 recommendations ranked strictly by business impact (highest first). Be specific, quantitative, and actionable. Return ONLY the JSON.

AGGREGATED DATA:
"""


# ---------------------------------------------------------------------------
# Claude helpers
# ---------------------------------------------------------------------------
def _strip_fences(text: str) -> str:
    """Remove accidental ```json fences if the model adds them."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text[3:]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def call_claude(client: Anthropic, prompt: str, max_tokens: int = 4096) -> dict:
    """Call Claude with retry + JSON parsing."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            return json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            last_error = f"Invalid JSON from model: {e}"
        except Exception as e:  # network / rate-limit / auth / etc.
            last_error = f"{type(e).__name__}: {e}"
        time.sleep(RETRY_BACKOFF * attempt)
    raise RuntimeError(f"Claude API failed after {MAX_RETRIES} retries — {last_error}")


def analyze_batch(client: Anthropic, reviews: list) -> dict:
    numbered = "\n".join(f"{i+1}. {r[:600]}" for i, r in enumerate(reviews))
    return call_claude(client, BATCH_PROMPT + numbered)


def aggregate_results(batches: list, total_reviews: int) -> dict:
    """Merge per-batch JSONs into a single aggregated report."""
    sentiment = {"positive": 0, "neutral": 0, "negative": 0}
    issues_map = {}

    for b in batches:
        s = b.get("sentiment", {}) or {}
        for k in sentiment:
            sentiment[k] += int(s.get(k, 0) or 0)

        for issue in b.get("issues", []) or []:
            name = issue.get("name")
            if name not in ISSUE_BUCKETS:
                continue
            slot = issues_map.setdefault(
                name,
                {"name": name, "frequency": 0, "impact_sum": 0.0,
                 "severity_sum": 0.0, "n": 0, "quotes": []},
            )
            slot["frequency"] += int(issue.get("frequency", 0) or 0)
            slot["impact_sum"] += float(issue.get("impact", 0) or 0)
            slot["severity_sum"] += float(issue.get("severity", 0) or 0)
            slot["n"] += 1
            quotes = issue.get("quotes", []) or []
            slot["quotes"].extend([q for q in quotes if isinstance(q, str) and q.strip()])

    issues = []
    for name, d in issues_map.items():
        n = max(d["n"], 1)
        issues.append({
            "name": name,
            "frequency": d["frequency"],
            "impact": round(d["impact_sum"] / n, 2),
            "severity": round(d["severity_sum"] / n, 2),
            "quotes": list(dict.fromkeys(d["quotes"]))[:6],  # dedupe, cap
        })
    issues.sort(key=lambda x: x["frequency"], reverse=True)

    return {
        "total_reviews": total_reviews,
        "sentiment": sentiment,
        "issues": issues,
    }


def synthesize(client: Anthropic, aggregated: dict) -> dict:
    compact = {
        "total_reviews": aggregated["total_reviews"],
        "sentiment": aggregated["sentiment"],
        "issues": [
            {"name": i["name"], "frequency": i["frequency"],
             "impact": i["impact"], "severity": i["severity"]}
            for i in aggregated["issues"]
        ],
    }
    return call_claude(client, SYNTHESIS_PROMPT + json.dumps(compact, indent=2))


def run_analysis(client: Anthropic, df_sample: pd.DataFrame, review_col: str) -> dict:
    """End-to-end pipeline with progress reporting."""
    reviews_series = df_sample[review_col].fillna("").astype(str)
    valid_idx = [i for i, r in enumerate(reviews_series.tolist()) if r.strip()]
    reviews = [reviews_series.iloc[i] for i in valid_idx]

    if not reviews:
        raise RuntimeError("No non-empty reviews found in the selected column.")

    batches, batch_idx_map = [], []
    for i in range(0, len(reviews), BATCH_SIZE):
        batches.append(reviews[i:i + BATCH_SIZE])
        batch_idx_map.append(valid_idx[i:i + BATCH_SIZE])

    progress = st.progress(0.0, text=f"Analyzing 0/{len(batches)} batches…")
    batch_results = []
    per_review_sentiment = [None] * len(df_sample)

    for i, (batch, idx_slice) in enumerate(zip(batches, batch_idx_map)):
        try:
            result = analyze_batch(client, batch)
            batch_results.append(result)
            prs = result.get("per_review_sentiment", []) or []
            for j, sent in enumerate(prs):
                if j < len(idx_slice) and isinstance(sent, str):
                    per_review_sentiment[idx_slice[j]] = sent.lower().strip()
        except Exception as e:
            st.warning(f"Batch {i+1}/{len(batches)} failed — {e}")
        progress.progress((i + 1) / len(batches),
                          text=f"Analyzing {i+1}/{len(batches)} batches…")

    progress.empty()

    if not batch_results:
        raise RuntimeError("All batches failed — check your API key, network, and quota.")

    aggregated = aggregate_results(batch_results, len(reviews))
    synth = synthesize(client, aggregated)
    aggregated["summary"] = synth.get("summary", "")
    aggregated["recommendations"] = synth.get("recommendations", []) or []
    aggregated["per_review_sentiment"] = per_review_sentiment
    return aggregated


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("📊 Customer Feedback Analyzer")
st.caption("AI-powered consulting-style insights from unstructured customer reviews — powered by Anthropic Claude")

with st.sidebar:
    st.header("⚙️ Configuration")
    uploaded = st.file_uploader("Upload Customer Reviews CSV", type=["csv"])
    st.markdown("---")
    st.markdown("**Model**")
    st.code(MODEL, language="text")
    st.markdown("**Batch size**")
    st.code(str(BATCH_SIZE), language="text")
    st.markdown("---")
    st.caption(
        "This tool batches reviews, calls Claude for structured extraction, "
        "and synthesizes a McKinsey-style briefing."
    )

if uploaded is None:
    st.info("👈 Upload a CSV to begin. It should contain a column of customer review text.")
    with st.expander("📋 Expected CSV format"):
        st.markdown(
            "- At least one column with free-text customer reviews\n"
            "- Optional: a date column for trend analysis\n"
            "- Recommended: 100–5,000 rows for a meaningful deliverable"
        )
    st.stop()

# -------- Load data --------
try:
    df = pd.read_csv(uploaded)
except Exception as e:
    st.error(f"Could not read CSV: {e}")
    st.stop()

if df.empty:
    st.error("The uploaded CSV is empty.")
    st.stop()

st.success(f"✅ Loaded **{len(df):,}** rows · **{len(df.columns)}** columns")
with st.expander("🔍 Preview data"):
    st.dataframe(df.head(10), use_container_width=True)

# -------- Column selectors --------
c1, c2, c3 = st.columns([2, 2, 3])

with c1:
    # Best-effort default: pick a likely review column
    text_like = [c for c in df.columns
                 if df[c].dtype == object and df[c].astype(str).str.len().mean() > 30]
    default_idx = list(df.columns).index(text_like[0]) if text_like else 0
    review_col = st.selectbox("Review column", df.columns, index=default_idx)

with c2:
    date_options = ["(none)"] + list(df.columns)
    date_col_sel = st.selectbox("Date column (optional)", date_options)
    date_col = None if date_col_sel == "(none)" else date_col_sel

with c3:
    n_rows = len(df)
    if n_rows < 100:
        sample_size = n_rows
        st.write(f"**Sample size:** {n_rows} (full dataset — below 100-row minimum)")
    else:
        max_sample = min(500, n_rows)
        sample_size = st.slider(
            "Sample size",
            min_value=100,
            max_value=max_sample,
            value=min(200, max_sample),
            step=50,
            help="Reviews are randomly sampled from your dataset for analysis.",
        )

# -------- Build working sample --------
if len(df) > sample_size:
    df_sample = df.sample(n=sample_size, random_state=42).reset_index(drop=True)
    st.caption(f"📌 Analyzing a random sample of **{sample_size:,}** reviews out of **{len(df):,}** total rows.")
else:
    df_sample = df.reset_index(drop=True)
    st.caption(f"📌 Dataset smaller than sample size — analyzing the full **{len(df):,}** reviews.")

# -------- Run button --------
run = st.button("🚀 Run Analysis", type="primary", use_container_width=True)

if run:
    client = get_client()
    try:
        with st.spinner("Calling Claude API — this may take a minute for large samples…"):
            result = run_analysis(client, df_sample, review_col)
        st.session_state.update({
            "result": result,
            "df_sample": df_sample,
            "review_col": review_col,
            "date_col": date_col,
        })
    except Exception as e:
        st.error(f"Something went wrong: {e}")
        st.stop()

# ---------------------------------------------------------------------------
# Render results
# ---------------------------------------------------------------------------
if "result" in st.session_state:
    result = st.session_state["result"]
    df_sample = st.session_state["df_sample"]
    review_col = st.session_state["review_col"]
    date_col = st.session_state["date_col"]

    sentiment = result["sentiment"]
    issues = result["issues"]
    total = result["total_reviews"]
    total_sent = max(sum(sentiment.values()), 1)
    pct_neg = sentiment["negative"] / total_sent * 100
    pct_pos = sentiment["positive"] / total_sent * 100
    top_issue = issues[0]["name"] if issues else "—"

    # Executive Summary
    st.markdown("## 📝 Executive Summary")
    st.info(result.get("summary") or "No executive summary was returned.")

    # KPI Cards
    st.markdown("## 📊 Key Performance Indicators")
    k1, k2, k3 = st.columns(3)
    k1.metric("Total Reviews Analyzed", f"{total:,}")
    k2.metric("% Negative Sentiment", f"{pct_neg:.1f}%",
              delta=f"{pct_pos - pct_neg:+.1f}% net", delta_color="inverse")
    k3.metric("Top Issue", top_issue,
              delta=f"{issues[0]['frequency']} mentions" if issues else None)

    # Charts row
    st.markdown("## 📈 Sentiment & Issue Distribution")
    ch1, ch2 = st.columns(2)

    with ch1:
        donut_df = pd.DataFrame({
            "Sentiment": ["Strongly Positive", "Neutral", "Strongly Negative"],
            "Count": [sentiment["positive"], sentiment["neutral"], sentiment["negative"]],
        })
        fig_donut = px.pie(
            donut_df, names="Sentiment", values="Count", hole=0.55,
            color="Sentiment",
            color_discrete_map={
                "Strongly Positive": "#10B981",
                "Neutral": "#9CA3AF",
                "Strongly Negative": "#EF4444",
            },
            title="Sentiment Breakdown",
        )
        fig_donut.update_traces(textinfo="percent+label")
        fig_donut.update_layout(showlegend=True, height=420)
        st.plotly_chart(fig_donut, use_container_width=True)

    with ch2:
        if issues:
            issue_df = pd.DataFrame(issues).sort_values("frequency")
            fig_bar = px.bar(
                issue_df, x="frequency", y="name", orientation="h",
                labels={"frequency": "Mentions", "name": "Issue"},
                title="Issue Frequency",
                color="frequency", color_continuous_scale="Reds",
            )
            fig_bar.update_layout(showlegend=False, coloraxis_showscale=False, height=420)
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.caption("No issues surfaced.")

    # Priority Matrix
    st.markdown("## 🎯 Priority Matrix")
    st.caption("X = frequency · Y = business impact · bubble size = severity · quadrants defined by medians.")
    if issues:
        mdf = pd.DataFrame(issues)
        x_mid = float(mdf["frequency"].median())
        y_mid = 5.5  # fixed midpoint on the 1–10 impact scale
        x_max = max(float(mdf["frequency"].max()), x_mid * 2)

        fig_matrix = px.scatter(
            mdf, x="frequency", y="impact", size="severity", text="name",
            size_max=70,
            color="severity", color_continuous_scale="Reds",
            labels={"frequency": "Issue Frequency →", "impact": "Business Impact →"},
            title="Issue Priority Matrix",
        )
        fig_matrix.update_traces(textposition="top center")
        fig_matrix.add_vline(x=x_mid, line_dash="dash", line_color="gray")
        fig_matrix.add_hline(y=y_mid, line_dash="dash", line_color="gray")

        quadrant_labels = [
            (x_mid * 0.5,      9.6, "Quick Wins",     "#059669"),   # low freq, high impact
            (x_max * 0.92,     9.6, "Major Problems", "#DC2626"),   # high freq, high impact
            (x_mid * 0.5,      1.4, "Low Priority",   "#6B7280"),   # low freq, low impact
            (x_max * 0.92,     1.4, "Monitor",        "#F59E0B"),   # high freq, low impact
        ]
        for x, y, label, color in quadrant_labels:
            fig_matrix.add_annotation(
                x=x, y=y, text=f"<b>{label}</b>",
                showarrow=False, font=dict(color=color, size=13),
                bgcolor="rgba(255,255,255,0.75)", borderpad=3,
            )

        fig_matrix.update_layout(yaxis=dict(range=[0, 10.5]), height=520)
        st.plotly_chart(fig_matrix, use_container_width=True)
    else:
        st.caption("No issues available for matrix.")

    # Sentiment trend (conditional)
    if date_col:
        st.markdown("## 📅 Sentiment Trend Over Time")
        try:
            tdf = df_sample.copy()
            tdf["_sentiment"] = result.get("per_review_sentiment", [None] * len(tdf))
            tdf["_date"] = pd.to_datetime(tdf[date_col], errors="coerce")
            tdf = tdf.dropna(subset=["_date", "_sentiment"])

            if not tdf.empty:
                tdf["_month"] = tdf["_date"].dt.to_period("M").dt.to_timestamp()
                monthly = (
                    tdf.groupby(["_month", "_sentiment"]).size()
                       .unstack(fill_value=0)
                       .reset_index()
                )
                for col in ("positive", "neutral", "negative"):
                    if col not in monthly.columns:
                        monthly[col] = 0

                long_df = monthly.melt(
                    id_vars="_month",
                    value_vars=["positive", "neutral", "negative"],
                    var_name="Sentiment", value_name="Count",
                )

                fig_trend = px.line(
                    long_df, x="_month", y="Count", color="Sentiment",
                    markers=True,
                    color_discrete_map={
                        "positive": "#10B981",
                        "neutral": "#9CA3AF",
                        "negative": "#EF4444",
                    },
                    title="Monthly Sentiment Volume",
                    labels={"_month": "Month"},
                )
                fig_trend.update_layout(height=420)
                st.plotly_chart(fig_trend, use_container_width=True)
            else:
                st.caption("No valid dates parsed from the selected column.")
        except Exception as e:
            st.caption(f"Could not build trend: {e}")

    # Recommendations
    st.markdown("## 💡 Strategic Recommendations")
    st.caption("Ranked by business impact (highest first).")
    recs = result.get("recommendations", [])
    if recs:
        for i, rec in enumerate(recs, 1):
            with st.expander(f"**Recommendation {i}**", expanded=(i == 1)):
                st.markdown(rec)
    else:
        st.info("No recommendations returned.")

    # Verbatim Evidence
    st.markdown("## 🗣️ Verbatim Evidence")
    st.caption("Real customer quotes supporting the top issues.")
    for issue in issues[:5]:
        header = (f"**{issue['name']}** · {issue['frequency']} mentions · "
                  f"impact {issue['impact']}/10 · severity {issue['severity']}/10")
        with st.expander(header):
            quotes = issue.get("quotes", [])[:2]
            if quotes:
                for q in quotes:
                    st.markdown(f"> _{q}_")
            else:
                st.caption("No verbatim quotes captured for this issue.")

    # Download
    st.markdown("## 📥 Export")
    rows = [
        {"metric": "Total Reviews", "value": total},
        {"metric": "% Positive", "value": round(pct_pos, 1)},
        {"metric": "% Neutral", "value": round(sentiment["neutral"] / total_sent * 100, 1)},
        {"metric": "% Negative", "value": round(pct_neg, 1)},
        {"metric": "Executive Summary", "value": result.get("summary", "")},
    ]
    for issue in issues:
        rows.append({
            "metric": f"Issue: {issue['name']}",
            "value": (f"frequency={issue['frequency']}; "
                      f"impact={issue['impact']}; severity={issue['severity']}"),
        })
    for i, rec in enumerate(recs, 1):
        rows.append({"metric": f"Recommendation {i}", "value": rec})

    out_df = pd.DataFrame(rows)
    csv_bytes = out_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "📥 Download Analysis Summary (CSV)",
        data=csv_bytes,
        file_name=f"feedback_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        use_container_width=True,
    )