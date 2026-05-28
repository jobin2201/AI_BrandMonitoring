"""
Reputation Intelligence — Streamlit Application
Business-grade dashboard for reviews, news, and reputation monitoring.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
from collections import Counter, defaultdict
import json
import os

import config
from dataset import fetch_all_data, search_google_play_apps, search_apple_app_store_apps
from classifier import ReviewClassifier


# ═══════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════

st.set_page_config(
    page_title="Reputation Intelligence",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for business look
st.markdown("""
<style>
    .main-header { font-size: 2.2rem; font-weight: 700; color: #1f2937; }
    .sub-header { font-size: 1.1rem; color: #6b7280; margin-bottom: 1rem; }
    .metric-card { background: #f9fafb; padding: 1rem; border-radius: 0.5rem; border-left: 4px solid #3b82f6; color: #1f2937; }
    .alert-critical { background: #fef2f2; border-left: 4px solid #dc2626; padding: 1rem; border-radius: 0.5rem; color: #1f2937; }
    .alert-warning { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 1rem; border-radius: 0.5rem; color: #1f2937; }
    .alert-safe { background: #ecfdf5; border-left: 4px solid #10b981; padding: 1rem; border-radius: 0.5rem; color: #1f2937; }
    .alert-critical b, .alert-warning b, .alert-safe b, .metric-card b { color: #111827; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 10px 20px; font-weight: 500; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════

if "classified_data" not in st.session_state:
    st.session_state.classified_data = []
if "raw_data" not in st.session_state:
    st.session_state.raw_data = []
if "last_run" not in st.session_state:
    st.session_state.last_run = None
if "classifier" not in st.session_state:
    st.session_state.classifier = None
if "ai_summary" not in st.session_state:
    st.session_state.ai_summary = None


# ═══════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ═══════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 🛡️ Reputation Intelligence")
    st.markdown("---")

    page = st.radio(
        "Navigate",
        [
            "🏠 Executive Dashboard",
            "📱 App Reviews",
            "📰 News Intelligence",
            "⭐ Review Platforms",
            "📋 All Items",
            "📊 Deep Analytics",
            "⚠️ Crisis Monitor",
        ],
        index=0
    )

    st.markdown("---")
    st.markdown("### ⚙️ Global Settings")

    today = date.today()
    default_start = today - timedelta(days=30)
    raw_range = st.date_input(
        "Analysis Date Range",
        value=(default_start, today),
        max_value=today,
        key="global_date_range",
        help="Only reviews/articles published in this range will be analyzed.",
    )
    # date_input can return a single date while the user is mid-selection
    if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
        start_date, end_date = raw_range
    else:
        start_date, end_date = default_start, today

    sentiment_threshold = st.slider("Crisis Threshold (score)", -1.0, 0.0, -0.3, step=0.05, key="global_threshold")

    st.markdown("---")
    if st.session_state.classified_data:
        st.caption(f"💾 {len(st.session_state.classified_data)} items in session")
        if st.button("🗑️ Clear all data", use_container_width=True):
            st.session_state.classified_data = []
            st.session_state.raw_data = []
            st.session_state.last_run = None
            st.session_state.ai_summary = None
            st.rerun()

    st.markdown("---")
    st.markdown("**v2.0** | Business Edition")


# ═══════════════════════════════════════════════════════
# CACHED RESOURCES
# ═══════════════════════════════════════════════════════

@st.cache_resource(show_spinner="Loading AI Models...")
def get_classifier():
    return ReviewClassifier()


@st.cache_data(ttl=300, show_spinner=False)
def cached_google_play_search(query: str):
    """Cache search results for 5 minutes so retyping doesn't re-hit the API."""
    return search_google_play_apps(query, limit=6)


@st.cache_data(ttl=300, show_spinner=False)
def cached_apple_search(query: str):
    """Cache iTunes search results for 5 minutes."""
    return search_apple_app_store_apps(query, limit=6)


# ═══════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════

def get_category_label(cat_key):
    return config.CATEGORY_LABELS.get(cat_key, (cat_key.replace("_", " ").title(), ""))[0]

def get_category_desc(cat_key):
    return config.CATEGORY_LABELS.get(cat_key, ("", ""))[1]

def in_date_range(item, start, end):
    """Return True if the item's publication date falls in [start, end] (inclusive)."""
    item_date = None
    if item.get("days_ago") is not None:
        try:
            item_date = date.today() - timedelta(days=int(item["days_ago"]))
        except (TypeError, ValueError):
            item_date = None
    elif item.get("date") is not None:
        d = item["date"]
        if isinstance(d, datetime):
            item_date = d.date()
        elif isinstance(d, date):
            item_date = d
        elif isinstance(d, str):
            try:
                item_date = datetime.fromisoformat(d.replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                item_date = None
    if item_date is None:
        return True  # include if we can't determine date
    return start <= item_date <= end

def calculate_metrics(data):
    """Calculate core metrics from classified data."""
    if not data:
        return {}
    total = len(data)
    avg_score = sum(r["sentiment_score"] for r in data) / total
    pos = len([r for r in data if r["sentiment"] == "positive"])
    neg = len([r for r in data if r["sentiment"] == "negative"])
    neu = total - pos - neg

    # Platform breakdown
    platforms = Counter(r["platform"] for r in data)

    # Category scores
    cat_scores = defaultdict(list)
    for r in data:
        cat_scores[r["primary_category"]].append(r["sentiment_score"])

    cat_avgs = {k: sum(v)/len(v) for k, v in cat_scores.items() if len(v) > 0}
    problem_cats = sorted([(k, v) for k, v in cat_avgs.items() if v < -0.1], key=lambda x: x[1])
    strong_cats = sorted([(k, v) for k, v in cat_avgs.items() if v > 0.1], key=lambda x: x[1], reverse=True)

    # Emotions
    emotions = Counter(r["emotion"] for r in data if r.get("emotion"))

    # Crisis count
    crisis_items = [r for r in data if r["sentiment_score"] <= sentiment_threshold]

    return {
        "total": total,
        "avg_score": avg_score,
        "positive_count": pos,
        "negative_count": neg,
        "neutral_count": neu,
        "positive_pct": (pos/total)*100,
        "negative_pct": (neg/total)*100,
        "platforms": dict(platforms),
        "category_scores": cat_avgs,
        "problem_categories": problem_cats,
        "strong_categories": strong_cats,
        "emotions": dict(emotions),
        "crisis_count": len(crisis_items),
        "crisis_items": crisis_items,
    }

def render_summary_card(metrics):
    """Render the executive summary card."""
    if not metrics:
        st.info("No data analyzed yet. Go to a data source page to fetch and analyze.")
        return

    avg = metrics["avg_score"]
    neg_pct = metrics["negative_pct"]

    if avg < -0.3 or neg_pct > 50:
        status_color = "#dc2626"
        status_bg = "#fef2f2"
        status_text = "🔴 CRITICAL"
    elif avg < -0.1 or neg_pct > 30:
        status_color = "#f59e0b"
        status_bg = "#fffbeb"
        status_text = "🟠 WARNING"
    elif avg < 0.1:
        status_color = "#3b82f6"
        status_bg = "#eff6ff"
        status_text = "🔵 MONITOR"
    else:
        status_color = "#10b981"
        status_bg = "#ecfdf5"
        status_text = "🟢 HEALTHY"

    st.markdown(f"""
    <div style="background: {status_bg}; border-left: 5px solid {status_color}; 
                padding: 1.2rem; border-radius: 0.75rem; margin-bottom: 1.5rem;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <div style="font-size: 1.5rem; font-weight: 700; color: #1f2937;">
                    {status_text}
                </div>
                <div style="color: #4b5563; margin-top: 0.3rem;">
                    Average Sentiment: <b>{avg:.2f}</b> &nbsp;|&nbsp; 
                    Negative: <b>{neg_pct:.1f}%</b> &nbsp;|&nbsp;
                    Crisis Items: <b>{metrics['crisis_count']}</b>
                </div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 2rem; font-weight: 700; color: {status_color};">
                    {metrics['total']}
                </div>
                <div style="font-size: 0.85rem; color: #6b7280;">Items Analyzed</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_ai_summary(data):
    """Render the AI executive summary section with generate/regenerate button."""
    st.subheader("🤖 AI Executive Summary")

    top_l, top_r = st.columns([5, 1])
    with top_l:
        st.caption("LLM-generated strategic narrative across every item in this session.")
    with top_r:
        summary = st.session_state.get("ai_summary")
        btn_label = "🔄 Regenerate" if summary else "✨ Generate"
        if st.button(btn_label, use_container_width=True, key="ai_summary_btn"):
            with st.spinner("Generating AI summary…"):
                clf = get_classifier()
                # Detect mode by checking whether any item uses a news category
                news_cats = set(config.NEWS_CATEGORIES.keys())
                mode = "news" if any(
                    r.get("primary_category") in news_cats for r in data
                ) else "reviews"
                st.session_state.ai_summary = clf.generate_overall_summary(data, mode=mode)
                st.rerun()

    summary = st.session_state.get("ai_summary")
    if not summary:
        st.info("Click **✨ Generate** above to create an AI executive summary based on your current data.")
        return

    # Staleness hint
    based_on = summary.get("_based_on")
    if based_on and based_on != len(data):
        st.warning(
            f"⚠️ This summary was generated when there were **{based_on}** items. "
            f"You now have **{len(data)}** — regenerate to refresh."
        )

    # Status banner
    status_map = {
        "healthy":  ("#10b981", "#ecfdf5", "🟢 HEALTHY"),
        "monitor":  ("#3b82f6", "#eff6ff", "🔵 MONITOR"),
        "warning":  ("#f59e0b", "#fffbeb", "🟠 WARNING"),
        "critical": ("#dc2626", "#fef2f2", "🔴 CRITICAL"),
    }
    color, bg, status_label = status_map.get(
        summary.get("overall_status", "monitor"), status_map["monitor"]
    )

    st.markdown(f"""
    <div style="background:{bg}; border-left:5px solid {color}; padding:1.2rem;
                border-radius:0.75rem; margin: 0.5rem 0 1rem 0;">
        <div style="font-size:0.85rem; font-weight:600; color:{color}; margin-bottom:0.4rem;">
            {status_label}
        </div>
        <div style="font-size:1.05rem; color:#1f2937; line-height:1.5;">
            {summary.get("headline", "")}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Strengths + Concerns row
    s_col, c_col = st.columns(2)
    with s_col:
        with st.container(border=True):
            st.markdown("##### ✅ Key Strengths")
            strengths = summary.get("key_strengths", [])
            if strengths:
                for s in strengths:
                    st.markdown(f"- {s}")
            else:
                st.caption("_None identified._")
    with c_col:
        with st.container(border=True):
            st.markdown("##### ⚠️ Key Concerns")
            concerns = summary.get("key_concerns", [])
            if concerns:
                for s in concerns:
                    st.markdown(f"- {s}")
            else:
                st.caption("_None identified._")

    # Patterns + Recommendations row
    p_col, r_col = st.columns(2)
    with p_col:
        with st.container(border=True):
            st.markdown("##### 📈 Patterns & Themes")
            patterns = summary.get("patterns", [])
            if patterns:
                for s in patterns:
                    st.markdown(f"- {s}")
            else:
                st.caption("_None identified._")
    with r_col:
        with st.container(border=True):
            st.markdown("##### 🎯 Recommendations")
            recs = summary.get("recommendations", [])
            if recs:
                for s in recs:
                    st.markdown(f"- {s}")
            else:
                st.caption("_None._")

    # Narrative paragraphs
    drawbacks = summary.get("drawbacks_narrative")
    improvements = summary.get("improvements_narrative")
    if drawbacks or improvements:
        st.markdown("")
        n_col1, n_col2 = st.columns(2)
        with n_col1:
            with st.container(border=True):
                st.markdown("##### 📝 What's holding it back")
                if drawbacks:
                    st.write(drawbacks)
                else:
                    st.caption("_No narrative generated._")
        with n_col2:
            with st.container(border=True):
                st.markdown("##### 🚀 How to improve")
                if improvements:
                    st.write(improvements)
                else:
                    st.caption("_No narrative generated._")


# ═══════════════════════════════════════════════════════
# PAGE 1: EXECUTIVE DASHBOARD
# ═══════════════════════════════════════════════════════

def page_dashboard():
    st.markdown('<div class="main-header">🏠 Executive Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Real-time reputation overview across all channels</div>', unsafe_allow_html=True)

    data = st.session_state.classified_data

    if not data:
        st.info("👈 Fetch data from **App Reviews**, **News Intelligence**, or **Review Platforms** to see the dashboard.")
        return

    metrics = calculate_metrics(data)
    render_summary_card(metrics)

    # AI Executive Summary (LLM-generated narrative)
    render_ai_summary(data)
    st.divider()

    # KPI Row
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Items", metrics["total"])
    c2.metric("Avg Score", f"{metrics['avg_score']:.2f}")
    c3.metric("Positive", f"{metrics['positive_pct']:.1f}%")
    c4.metric("Negative", f"{metrics['negative_pct']:.1f}%")
    c5.metric("Crisis Alerts", metrics["crisis_count"], delta=None)

    st.divider()

    # Charts Row
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📊 Sentiment Distribution")
        sent_df = pd.DataFrame({
            "Sentiment": ["Positive", "Neutral", "Negative"],
            "Count": [metrics["positive_count"], metrics["neutral_count"], metrics["negative_count"]]
        })
        fig = px.pie(sent_df, values="Count", names="Sentiment",
                     color="Sentiment",
                     color_discrete_map={"Positive": "#10b981", "Neutral": "#6b7280", "Negative": "#dc2626"})
        fig.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("📡 Platform Breakdown")
        if metrics["platforms"]:
            plat_df = pd.DataFrame(list(metrics["platforms"].items()), columns=["Platform", "Count"])
            fig = px.bar(plat_df, x="Platform", y="Count", color="Count",
                         color_continuous_scale="Blues")
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Category Performance
    st.subheader("📂 Category Performance")
    if metrics["category_scores"]:
        cat_df = pd.DataFrame([
            {"Category": get_category_label(k), "Score": v, "Count": len([r for r in data if r["primary_category"] == k])}
            for k, v in metrics["category_scores"].items()
        ])
        cat_df = cat_df.sort_values("Score")
        fig = px.bar(cat_df, x="Score", y="Category", orientation="h",
                     color="Score", color_continuous_scale=["#dc2626", "#f59e0b", "#10b981"])
        fig.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

    # Problem & Strength Cards
    prob_col, strong_col = st.columns(2)
    with prob_col:
        st.subheader("❌ Top Concerns")
        if metrics["problem_categories"]:
            for cat, score in metrics["problem_categories"][:3]:
                st.markdown(f"""
                <div class="alert-warning">
                    <b>{get_category_label(cat)}</b><br/>
                    Score: {score:.2f} | {len([r for r in data if r['primary_category']==cat])} mentions
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown('<div class="alert-safe">No significant concerns detected.</div>', unsafe_allow_html=True)

    with strong_col:
        st.subheader("✅ Top Strengths")
        if metrics["strong_categories"]:
            for cat, score in metrics["strong_categories"][:3]:
                st.markdown(f"""
                <div class="alert-safe">
                    <b>{get_category_label(cat)}</b><br/>
                    Score: {score:.2f} | {len([r for r in data if r['primary_category']==cat])} mentions
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown('<div class="alert-warning">No standout strengths detected.</div>', unsafe_allow_html=True)

    # Recent Activity Table
    st.divider()
    st.subheader("📋 Recent Activity")
    df = pd.DataFrame(data)
    df["category"] = df["primary_category"].apply(get_category_label)
    display_cols = ["title" if "title" in df.columns else "id", "platform", "category", "sentiment", "sentiment_score", "emotion", "days_ago"]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(df[display_cols].sort_values("sentiment_score"), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════
# PAGE 2: APP REVIEWS
# ═══════════════════════════════════════════════════════

def page_app_reviews():
    st.markdown('<div class="main-header">📱 App Store Reviews</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Analyze Google Play and Apple App Store reviews</div>', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["Google Play", "Apple App Store"])

    with tab1:
        st.caption("Type an **app name** (e.g. `WhatsApp`, `Spotify`) — or paste a **package ID** directly (e.g. `com.spotify.music`).")

        col1, col2 = st.columns([3, 1])
        with col1:
            gp_query = st.text_input(
                "App name or package ID",
                value="Google Maps",
                key="gp_query",
                placeholder="WhatsApp, Spotify, com.spotify.music ...",
            )
        with col2:
            gp_count = st.number_input("Max Reviews", 10, 500, 100, key="gp_count")

        selected_pkg = None
        selected_title = None
        query_stripped = (gp_query or "").strip()

        # Heuristic: dotted, no spaces → user typed a package ID directly
        looks_like_pkg = (
            "." in query_stripped
            and " " not in query_stripped
            and not query_stripped.endswith(".")
        )

        if not query_stripped:
            st.info("Enter an app name or package ID above to begin.")
        elif looks_like_pkg:
            selected_pkg = query_stripped
            selected_title = query_stripped
            st.success(f"📦 Using package ID directly: `{selected_pkg}`")
        else:
            with st.spinner(f"Searching Google Play for '{query_stripped}'..."):
                matches = cached_google_play_search(query_stripped)

            if not matches:
                st.warning(
                    f"No apps found matching **'{query_stripped}'**. "
                    "Try a different spelling, or paste a package ID directly."
                )
            else:
                # Build labels for the picker
                labels = []
                label_to_match = {}
                for m in matches:
                    score_str = f" · ⭐{m['score']:.1f}" if m.get("score") else ""
                    installs_str = f" · {m['installs']}" if m.get("installs") else ""
                    label = f"{m['title']} — {m['developer']}{score_str}{installs_str}"
                    labels.append(label)
                    label_to_match[label] = m

                choice = st.selectbox(
                    f"Found {len(matches)} match{'es' if len(matches)!=1 else ''} — pick one:",
                    labels,
                    key="gp_choice",
                )
                chosen = label_to_match[choice]
                selected_pkg = chosen["appId"]
                selected_title = chosen["title"]

                # Preview the chosen app with its icon
                pcol1, pcol2 = st.columns([1, 6])
                with pcol1:
                    if chosen.get("icon"):
                        st.image(chosen["icon"], width=64)
                with pcol2:
                    st.markdown(
                        f"**Will analyze:** {selected_title}  \n"
                        f"`{selected_pkg}` · by {chosen.get('developer','Unknown')}"
                    )

        if st.button(
            "🔍 Analyze Google Play",
            type="primary",
            key="gp_btn",
            disabled=not selected_pkg,
        ):
            with st.spinner(f"Fetching and analyzing reviews for {selected_title}..."):
                clf = get_classifier()
                raw = fetch_all_data({
                    "google_play": {
                        "app_id": selected_pkg,
                        "enabled": True,
                        "max_reviews": gp_count,
                    }
                })
                if raw:
                    recent = [r for r in raw if in_date_range(r, start_date, end_date)]
                    if recent:
                        results = clf.classify_batch(recent, mode="reviews")
                        results = clf.cluster_by_category(results)
                        st.session_state.classified_data.extend(results)
                        st.session_state.raw_data.extend(raw)
                        st.success(
                            f"✅ Analyzed {len(results)} reviews for {selected_title} "
                            f"(out of {len(raw)} fetched, between {start_date} and {end_date})"
                        )
                        st.info("👉 Open **📋 All Items** in the sidebar to read every review.")
                        st.rerun()
                    else:
                        st.warning(
                            f"Fetched {len(raw)} reviews but none were published between "
                            f"{start_date} and {end_date}. Try widening the date range or "
                            f"increasing Max Reviews."
                        )
                else:
                    st.error("Failed to fetch reviews.")

    with tab2:
        st.caption("Type an **app name** (e.g. `WhatsApp`, `Instagram`) — or paste a **numeric Apple ID** directly (e.g. `585027354`).")

        col1, col2 = st.columns([3, 1])
        with col1:
            ios_query = st.text_input(
                "App name or Apple ID",
                value="WhatsApp",
                key="ios_query",
                placeholder="WhatsApp, Instagram, 585027354 ...",
            )
        with col2:
            ios_count = st.number_input("Max Reviews", 10, 500, 100, key="ios_count")

        selected_ios_id = None
        selected_ios_title = None
        ios_query_stripped = (ios_query or "").strip()

        # Heuristic: Apple App IDs are purely numeric
        looks_like_id = ios_query_stripped.isdigit()

        if not ios_query_stripped:
            st.info("Enter an app name or Apple ID above to begin.")
        elif looks_like_id:
            selected_ios_id = ios_query_stripped
            selected_ios_title = f"App ID {ios_query_stripped}"
            st.success(f"📦 Using Apple ID directly: `{selected_ios_id}`")
        else:
            with st.spinner(f"Searching Apple App Store for '{ios_query_stripped}'..."):
                matches = cached_apple_search(ios_query_stripped)

            if not matches:
                st.warning(
                    f"No apps found matching **'{ios_query_stripped}'**. "
                    "Try a different spelling, or paste a numeric Apple ID directly."
                )
            else:
                labels = []
                label_to_match = {}
                for m in matches:
                    score_str = f" · ⭐{m['score']:.1f}" if m.get("score") else ""
                    count_str = f" · {m['ratings_count']:,} ratings" if m.get("ratings_count") else ""
                    label = f"{m['title']} — {m['developer']}{score_str}{count_str}"
                    labels.append(label)
                    label_to_match[label] = m

                choice = st.selectbox(
                    f"Found {len(matches)} match{'es' if len(matches)!=1 else ''} — pick one:",
                    labels,
                    key="ios_choice",
                )
                chosen = label_to_match[choice]
                selected_ios_id = chosen["appId"]
                selected_ios_title = chosen["title"]

                pcol1, pcol2 = st.columns([1, 6])
                with pcol1:
                    if chosen.get("icon"):
                        st.image(chosen["icon"], width=64)
                with pcol2:
                    st.markdown(
                        f"**Will analyze:** {selected_ios_title}  \n"
                        f"`{selected_ios_id}` · by {chosen.get('developer','Unknown')}"
                    )

        if st.button(
            "🔍 Analyze Apple App Store",
            type="primary",
            key="ios_btn",
            disabled=not selected_ios_id,
        ):
            with st.spinner(f"Fetching and analyzing reviews for {selected_ios_title}..."):
                clf = get_classifier()
                raw = fetch_all_data({
                    "apple_app_store": {"app_id": selected_ios_id, "enabled": True, "max_reviews": ios_count}
                })
                if raw:
                    recent = [r for r in raw if in_date_range(r, start_date, end_date)]
                    if recent:
                        results = clf.classify_batch(recent, mode="reviews")
                        results = clf.cluster_by_category(results)
                        st.session_state.classified_data.extend(results)
                        st.session_state.raw_data.extend(raw)
                        st.success(
                            f"✅ Analyzed {len(results)} reviews for {selected_ios_title} "
                            f"(out of {len(raw)} fetched, between {start_date} and {end_date})"
                        )
                        st.info("👉 Open **📋 All Items** in the sidebar to read every review.")
                        st.rerun()
                    else:
                        st.warning(
                            f"Fetched {len(raw)} reviews but none were published between "
                            f"{start_date} and {end_date}. Try widening the date range or "
                            f"increasing Max Reviews."
                        )
                else:
                    st.error("Failed to fetch reviews.")


# ═══════════════════════════════════════════════════════
# PAGE 3: NEWS INTELLIGENCE
# ═══════════════════════════════════════════════════════

def page_news():
    st.markdown('<div class="main-header">📰 News Intelligence</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Monitor news articles via RSS feeds, Google News search, or direct URL scraping</div>', unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["RSS Feeds", "🔎 Google News Search", "Single URL"])

    with tab1:
        st.markdown("### 📡 RSS Feed Sources")
        st.caption("Select default feeds or add your own")

        use_defaults = st.checkbox("Use default business/tech feeds", value=True)
        custom_feeds = st.text_area("Custom RSS URLs (one per line)", "", height=80)

        feed_urls = []
        if use_defaults:
            feed_urls.extend(config.DEFAULT_RSS_FEEDS)
        if custom_feeds.strip():
            feed_urls.extend([u.strip() for u in custom_feeds.split("\n") if u.strip()])

        max_per_feed = st.slider("Articles per feed", 1, 20, 5)

        if st.button("📥 Fetch & Analyze RSS", type="primary"):
            if not feed_urls:
                st.warning("Please select or enter at least one RSS feed.")
            else:
                with st.spinner("Fetching and analyzing news articles..."):
                    clf = get_classifier()
                    raw = fetch_all_data({
                        "news_rss": {"feed_urls": feed_urls, "enabled": True, "max_per_feed": max_per_feed}
                    })
                    if raw:
                        results = clf.classify_batch(raw, mode="news")
                        results = clf.cluster_by_category(results)
                        st.session_state.classified_data.extend(results)
                        st.session_state.raw_data.extend(raw)
                        st.success(f"✅ Analyzed {len(results)} news articles from {len(feed_urls)} source(s)")
                        st.info("👉 Open **📋 All Items** in the sidebar to read every article.")
                        st.rerun()
                    else:
                        st.error("Failed to fetch news articles.")

    with tab2:
        st.markdown("### 🔎 Search Google News")
        st.caption("Searches Google News (RSS first, GNews package as fallback). No API key needed.")

        gn_query = st.text_input(
            "Search query",
            placeholder="e.g. Tesla earnings, Reliance Industries, OpenAI",
            key="gnews_query",
        )

        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            gn_country = st.selectbox(
                "Country",
                ["US", "IN", "GB", "AU", "CA", "DE", "FR", "JP", "SG", "AE"],
                index=1,  # default IN since you're in Hyderabad
                key="gnews_country",
            )
        with col_b:
            gn_language = st.selectbox(
                "Language",
                ["en", "hi", "fr", "de", "es", "pt", "it", "ja", "zh"],
                index=0,
                key="gnews_lang",
            )
        with col_c:
            gn_period = st.selectbox(
                "Time window",
                ["1h", "12h", "1d", "7d", "1m"],
                index=3,
                key="gnews_period",
            )
        with col_d:
            gn_max = st.slider("Max articles", 5, 50, 20, key="gnews_max")

        if st.button("📥 Fetch & Analyze Google News", type="primary", key="gnews_btn"):
            if not gn_query.strip():
                st.warning("Please enter a search query.")
            else:
                with st.spinner(f"Searching Google News for '{gn_query}'..."):
                    clf = get_classifier()
                    raw = fetch_all_data({
                        "google_news": {
                            "enabled": True,
                            "query": gn_query,
                            "max_results": gn_max,
                            "language": gn_language,
                            "country": gn_country,
                            "period": gn_period,
                        }
                    })
                    if raw:
                        results = clf.classify_batch(raw, mode="news")
                        results = clf.cluster_by_category(results)
                        st.session_state.classified_data.extend(results)
                        st.session_state.raw_data.extend(raw)
                        st.success(f"✅ Analyzed {len(results)} articles for '{gn_query}'")
                        st.info("👉 Open **📋 All Items** in the sidebar to read every article.")
                        st.rerun()
                    else:
                        st.error("No articles found. Try a different query, country, or longer time window.")

    with tab3:
        news_url = st.text_input("News Article URL", placeholder="https://www.bbc.com/news/...", key="news_url")

        if st.button("🔍 Scrape & Analyze URL", type="primary"):
            if not news_url.startswith("http"):
                st.warning("Please enter a valid URL starting with http:// or https://")
            else:
                with st.spinner("Scraping and analyzing article..."):
                    clf = get_classifier()
                    raw = fetch_all_data({
                        "news_url": {"url": news_url, "enabled": True}
                    })
                    if raw:
                        results = clf.classify_batch(raw, mode="news")
                        results = clf.cluster_by_category(results)
                        st.session_state.classified_data.extend(results)
                        st.session_state.raw_data.extend(raw)
                        st.success(f"✅ Analyzed article: {raw[0].get('title', 'Untitled')}")
                        st.info("👉 Open **📋 All Items** in the sidebar to read it.")
                        st.rerun()
                    else:
                        st.error("Failed to scrape article. The site may block scrapers.")


# ═══════════════════════════════════════════════════════
# PAGE 4: REVIEW PLATFORMS
# ═══════════════════════════════════════════════════════

def page_review_platforms():
    st.markdown('<div class="main-header">⭐ Review Platforms</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Google Business, Yelp, TripAdvisor, Trustpilot, Glassdoor</div>', unsafe_allow_html=True)

    platforms = {
        "google_business": ("Google Business", "place_id", "ChIJ..."),
        "yelp": ("Yelp", "business_alias", "gary-danko-san-francisco"),
        "tripadvisor": ("TripAdvisor", "location_url", "https://www.tripadvisor.com/..."),
        "trustpilot": ("Trustpilot", "business_domain", "example.com"),
        "glassdoor": ("Glassdoor", "company_name", "Google"),
    }

    for key, (label, input_key, placeholder) in platforms.items():
        with st.expander(f"⭐ {label}", expanded=False):
            col1, col2 = st.columns([3, 1])
            with col1:
                user_input = st.text_input(f"{label} {input_key.replace('_', ' ').title()}", placeholder=placeholder, key=f"{key}_input")
            with col2:
                max_items = st.number_input("Max", 10, 200, 50, key=f"{key}_max")

            if st.button(f"Analyze {label}", key=f"{key}_btn"):
                cfg = {"enabled": True, "max_reviews": max_items, input_key: user_input}
                if key == "glassdoor":
                    cfg["employer_id"] = st.text_input("Employer ID (optional)", key=f"{key}_emp")

                with st.spinner(f"Fetching {label} data..."):
                    clf = get_classifier()
                    raw = fetch_all_data({key: cfg})
                    if raw:
                        results = clf.classify_batch(raw, mode="reviews")
                        results = clf.cluster_by_category(results)
                        st.session_state.classified_data.extend(results)
                        st.session_state.raw_data.extend(raw)
                        st.success(f"✅ Analyzed {len(results)} {label} items")
                        st.info("👉 Open **📋 All Items** in the sidebar to read every review.")
                        st.rerun()
                    else:
                        st.error(f"Failed to fetch {label} data. Check your input and API keys in config.py.")


# ═══════════════════════════════════════════════════════
# PAGE 5: DEEP ANALYTICS
# ═══════════════════════════════════════════════════════

def page_analytics():
    st.markdown('<div class="main-header">📊 Deep Analytics</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Narrative tracking, emotion analysis, and trend detection</div>', unsafe_allow_html=True)

    data = st.session_state.classified_data
    if not data:
        st.info("Analyze data first to unlock analytics.")
        return

    metrics = calculate_metrics(data)

    tab1, tab2, tab3 = st.tabs(["Emotions", "Aspects", "Narrative Tracking"])

    with tab1:
        st.subheader("😊 Emotion Distribution")
        if metrics["emotions"]:
            emo_df = pd.DataFrame(list(metrics["emotions"].items()), columns=["Emotion", "Count"])
            fig = px.bar(emo_df, x="Emotion", y="Count", color="Emotion",
                         color_discrete_sequence=px.colors.qualitative.Set2)
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Emotion vs Sentiment Heatmap")
        heatmap_data = defaultdict(lambda: defaultdict(int))
        for r in data:
            heatmap_data[r["sentiment"]][r["emotion"]] += 1
        heatmap_df = pd.DataFrame(heatmap_data).fillna(0).astype(int)
        fig = px.imshow(heatmap_df, text_auto=True, aspect="auto",
                        color_continuous_scale="RdYlGn")
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("🔍 Aspect Sentiment Heatmap")
        aspect_matrix = defaultdict(lambda: defaultdict(list))
        for r in data:
            for aspect, score in r.get("aspect_sentiments", {}).items():
                aspect_matrix[get_category_label(aspect)][r["sentiment"]].append(score)

        aspect_summary = []
        for aspect, sentiments in aspect_matrix.items():
            for sent, scores in sentiments.items():
                aspect_summary.append({
                    "Aspect": aspect,
                    "Sentiment": sent,
                    "Avg Score": sum(scores)/len(scores),
                    "Count": len(scores)
                })

        if aspect_summary:
            asp_df = pd.DataFrame(aspect_summary)
            fig = px.density_heatmap(asp_df, x="Sentiment", y="Aspect", z="Count",
                                     color_continuous_scale="Blues")
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Aspect Scores by Category")
        aspect_scores = defaultdict(list)
        for r in data:
            for aspect, score in r.get("aspect_sentiments", {}).items():
                aspect_scores[get_category_label(aspect)].append(score)

        if aspect_scores:
            asp_avg = [{"Aspect": k, "Score": sum(v)/len(v)} for k, v in aspect_scores.items()]
            asp_avg_df = pd.DataFrame(asp_avg).sort_values("Score")
            fig = px.bar(asp_avg_df, x="Score", y="Aspect", orientation="h",
                         color="Score", color_continuous_scale=["#dc2626", "#fbbf24", "#10b981"])
            fig.update_layout(yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.subheader("📈 Narrative Tracking")
        st.caption("Topic clusters and trending narratives")

        # Group by category
        cat_groups = defaultdict(list)
        for r in data:
            cat_groups[r["primary_category"]].append(r)

        for cat, items in sorted(cat_groups.items(), key=lambda x: len(x[1]), reverse=True)[:6]:
            label = get_category_label(cat)
            avg_score = sum(r["sentiment_score"] for r in items) / len(items)
            color = "#10b981" if avg_score > 0.1 else "#dc2626" if avg_score < -0.1 else "#f59e0b"

            with st.expander(f"{label} — {len(items)} items (avg: {avg_score:.2f})"):
                # Sample quotes
                neg_samples = [r for r in items if r["sentiment"] == "negative"][:2]
                pos_samples = [r for r in items if r["sentiment"] == "positive"][:2]

                if neg_samples:
                    st.markdown("**🔴 Negative Narratives:**")
                    for r in neg_samples:
                        text = r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"]
                        st.markdown(f"> _{text}_")
                        st.caption(f"Score: {r['sentiment_score']:.2f} | {r.get('platform', 'unknown')}")

                if pos_samples:
                    st.markdown("**🟢 Positive Narratives:**")
                    for r in pos_samples:
                        text = r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"]
                        st.markdown(f"> _{text}_")
                        st.caption(f"Score: {r['sentiment_score']:.2f} | {r.get('platform', 'unknown')}")

    # Export
    st.divider()
    st.subheader("💾 Export Data")
    df = pd.DataFrame(data)
    csv = df.to_csv(index=False).encode('utf-8')
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("⬇️ Download CSV", csv, "reputation_intelligence.csv", "text/csv")
    with col2:
        json_str = json.dumps(data, indent=2, default=str)
        st.download_button("⬇️ Download JSON", json_str, "reputation_intelligence.json", "application/json")


# ═══════════════════════════════════════════════════════
# PAGE 6: CRISIS MONITOR
# ═══════════════════════════════════════════════════════

def page_crisis():
    st.markdown('<div class="main-header">⚠️ Crisis Monitor</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Real-time alerts for negative sentiment spikes and reputation threats</div>', unsafe_allow_html=True)

    data = st.session_state.classified_data
    if not data:
        st.info("No data available. Analyze sources first.")
        return

    metrics = calculate_metrics(data)

    # Crisis Overview
    st.subheader("🚨 Crisis Overview")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Crisis Items", metrics["crisis_count"])
    c2.metric("Crisis Rate", f"{(metrics['crisis_count']/metrics['total']*100):.1f}%")
    c3.metric("Worst Score", f"{min(r['sentiment_score'] for r in data):.2f}")

    # Crisis threshold config
    threshold = st.slider("Alert Threshold (sentiment score)", -1.0, 0.0, -0.3, step=0.05)

    # Filter crisis items
    crisis_items = [r for r in data if r["sentiment_score"] <= threshold]

    if crisis_items:
        st.error(f"🚨 {len(crisis_items)} items exceed the crisis threshold!")

        # Severity breakdown
        critical = [r for r in crisis_items if r["sentiment_score"] <= -0.6]
        high = [r for r in crisis_items if -0.6 < r["sentiment_score"] <= -0.4]
        medium = [r for r in crisis_items if -0.4 < r["sentiment_score"] <= -0.2]

        cols = st.columns(3)
        with cols[0]:
            st.markdown(f"""
            <div class="alert-critical">
                <b>🔴 CRITICAL</b><br/>{len(critical)} items<br/>Score ≤ -0.6
            </div>
            """, unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f"""
            <div class="alert-warning">
                <b>🟠 HIGH</b><br/>{len(high)} items<br/>Score -0.6 to -0.4
            </div>
            """, unsafe_allow_html=True)
        with cols[2]:
            st.markdown(f"""
            <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 1rem; border-radius: 0.5rem; color: #1f2937;">
                <b style="color:#111827;">🟡 MEDIUM</b><br/>{len(medium)} items<br/>Score -0.4 to -0.2
            </div>
            """, unsafe_allow_html=True)

        st.divider()

        # Crisis table
        st.subheader("📋 Crisis Items Detail")
        crisis_df = pd.DataFrame(crisis_items)
        crisis_df["category"] = crisis_df["primary_category"].apply(get_category_label)
        crisis_df["severity"] = crisis_df["sentiment_score"].apply(
            lambda x: "🔴 Critical" if x <= -0.6 else "🟠 High" if x <= -0.4 else "🟡 Medium"
        )

        display_cols = ["severity", "platform", "category", "sentiment_score", "emotion", "text", "days_ago"]
        display_cols = [c for c in display_cols if c in crisis_df.columns]
        st.dataframe(
            crisis_df[display_cols].sort_values("sentiment_score"),
            use_container_width=True,
            hide_index=True
        )

        # Platform breakdown of crises
        st.subheader("📡 Crisis by Platform")
        crisis_plat = Counter(r["platform"] for r in crisis_items)
        plat_df = pd.DataFrame(list(crisis_plat.items()), columns=["Platform", "Crisis Count"])
        fig = px.bar(plat_df, x="Platform", y="Crisis Count", color="Crisis Count",
                     color_continuous_scale="Reds")
        st.plotly_chart(fig, use_container_width=True)

    else:
        st.markdown('<div class="alert-safe">✅ No items exceed the current crisis threshold. Reputation is stable.</div>', unsafe_allow_html=True)

    # ESG / Legal Monitoring (filter view)
    st.divider()
    st.subheader("⚖️ ESG & Legal Monitoring")
    esg_items = [r for r in data if r["primary_category"] in ["esg", "legal_regulatory"]]
    if esg_items:
        esg_df = pd.DataFrame(esg_items)
        esg_df["category"] = esg_df["primary_category"].apply(get_category_label)
        st.dataframe(esg_df[["category", "sentiment", "sentiment_score", "text", "source" if "source" in esg_df.columns else "platform"]],
                     use_container_width=True, hide_index=True)
    else:
        st.info("No ESG or Legal items detected in current dataset.")


# ═══════════════════════════════════════════════════════
# PAGE 7: ALL ITEMS — browse every fetched review/article
# ═══════════════════════════════════════════════════════

def page_all_items():
    st.markdown('<div class="main-header">📋 All Items</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Browse, search, and filter every review and article you have analyzed</div>', unsafe_allow_html=True)

    data = st.session_state.classified_data
    if not data:
        st.info("No items yet. Fetch data from **App Reviews**, **News Intelligence**, or **Review Platforms** first.")
        return

    # ── Filter row ──
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        platforms = sorted({r.get("platform", "unknown") for r in data})
        sel_platforms = st.multiselect("Platform", platforms, default=platforms, key="ai_platforms")
    with col2:
        sentiments = ["positive", "neutral", "negative"]
        sel_sentiments = st.multiselect("Sentiment", sentiments, default=sentiments, key="ai_sentiments")
    with col3:
        categories = sorted({r.get("primary_category", "general") for r in data})
        sel_categories = st.multiselect(
            "Category", categories,
            default=categories,
            format_func=get_category_label,
            key="ai_categories",
        )
    with col4:
        emotions = sorted({r.get("emotion", "indifference") for r in data})
        sel_emotions = st.multiselect("Emotion", emotions, default=emotions, key="ai_emotions")

    search = st.text_input("🔍 Search text", placeholder="Type to filter by keyword...", key="ai_search")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        sort_by = st.selectbox(
            "Sort by",
            ["Most recent", "Worst sentiment", "Best sentiment", "Most helpful"],
            key="ai_sort",
        )
    with col_b:
        score_min, score_max = st.slider(
            "Sentiment score range", -1.0, 1.0, (-1.0, 1.0), step=0.05, key="ai_score_range"
        )
    with col_c:
        per_page = st.selectbox("Items per page", [10, 25, 50, 100], index=1, key="ai_per_page")

    # ── Apply filters ──
    filtered = [
        r for r in data
        if r.get("platform", "unknown") in sel_platforms
        and r.get("sentiment", "neutral") in sel_sentiments
        and r.get("primary_category", "general") in sel_categories
        and r.get("emotion", "indifference") in sel_emotions
        and score_min <= r.get("sentiment_score", 0) <= score_max
        and (not search or search.lower() in r.get("text", "").lower()
             or search.lower() in str(r.get("title", "")).lower())
    ]

    # ── Sort ──
    if sort_by == "Most recent":
        filtered.sort(key=lambda r: r.get("days_ago", 999))
    elif sort_by == "Worst sentiment":
        filtered.sort(key=lambda r: r.get("sentiment_score", 0))
    elif sort_by == "Best sentiment":
        filtered.sort(key=lambda r: r.get("sentiment_score", 0), reverse=True)
    elif sort_by == "Most helpful":
        filtered.sort(key=lambda r: r.get("helpful_count", 0), reverse=True)

    st.caption(f"Showing **{len(filtered)}** of {len(data)} total items")

    if not filtered:
        st.warning("No items match these filters. Try widening the criteria.")
        return

    # ── Reset page if filters changed ──
    filter_signature = (
        tuple(sel_platforms), tuple(sel_sentiments), tuple(sel_categories),
        tuple(sel_emotions), search, score_min, score_max, per_page, sort_by,
    )
    if st.session_state.get("ai_filter_sig") != filter_signature:
        st.session_state.ai_filter_sig = filter_signature
        st.session_state.ai_page = 0

    if "ai_page" not in st.session_state:
        st.session_state.ai_page = 0

    total_pages = max(1, (len(filtered) + per_page - 1) // per_page)
    st.session_state.ai_page = min(st.session_state.ai_page, total_pages - 1)

    # ── Pagination controls ──
    pc1, pc2, pc3 = st.columns([1, 2, 1])
    with pc1:
        if st.button("⬅️ Previous", disabled=st.session_state.ai_page == 0, key="ai_prev"):
            st.session_state.ai_page -= 1
            st.rerun()
    with pc2:
        st.markdown(
            f"<div style='text-align:center; padding-top:0.5rem; color:#4b5563;'>"
            f"Page <b>{st.session_state.ai_page + 1}</b> of <b>{total_pages}</b></div>",
            unsafe_allow_html=True,
        )
    with pc3:
        if st.button("Next ➡️", disabled=st.session_state.ai_page >= total_pages - 1, key="ai_next"):
            st.session_state.ai_page += 1
            st.rerun()

    start = st.session_state.ai_page * per_page
    end = start + per_page
    page_items = filtered[start:end]

    st.divider()

    # ── Render each item as a card ──
    for idx, r in enumerate(page_items):
        score = r.get("sentiment_score", 0)
        sentiment = r.get("sentiment", "neutral")

        if sentiment == "positive":
            badge = "🟢 Positive"
        elif sentiment == "negative":
            badge = "🔴 Negative"
        else:
            badge = "⚪ Neutral"

        with st.container(border=True):
            top1, top2 = st.columns([4, 1])
            with top1:
                cat_label = get_category_label(r.get("primary_category", "general"))
                st.markdown(
                    f"**{badge}** &nbsp;·&nbsp; `{r.get('platform','unknown')}` "
                    f"&nbsp;·&nbsp; {cat_label}"
                )
                if r.get("title"):
                    st.markdown(f"**{r['title']}**")
                st.write(r.get("text", "_(no text)_"))

                meta = []
                if r.get("author"):
                    meta.append(f"👤 {r['author']}")
                if r.get("rating") is not None:
                    meta.append(f"⭐ {r['rating']}/5")
                meta.append(f"😶 {r.get('emotion','indifference')}")
                if r.get("days_ago") is not None:
                    meta.append(f"📅 {r['days_ago']}d ago")
                if r.get("helpful_count"):
                    meta.append(f"👍 {r['helpful_count']}")
                if r.get("source"):
                    meta.append(f"🔗 {r['source']}")
                st.caption(" &nbsp;·&nbsp; ".join(meta))

            with top2:
                color = "#10b981" if score > 0.1 else "#dc2626" if score < -0.1 else "#6b7280"
                st.markdown(
                    f"<div style='text-align:center; padding-top:0.4rem;'>"
                    f"<div style='font-size:1.6rem; font-weight:700; color:{color};'>{score:+.2f}</div>"
                    f"<div style='font-size:0.75rem; color:#6b7280;'>sentiment score</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            aspects = r.get("aspect_sentiments", {}) or {}
            if aspects:
                with st.expander(f"🔍 Aspect breakdown ({len(aspects)} aspect{'s' if len(aspects)!=1 else ''})"):
                    for a, s in sorted(aspects.items(), key=lambda x: x[1]):
                        bar_color = "🟢" if s > 0.1 else "🔴" if s < -0.1 else "⚪"
                        st.markdown(f"{bar_color} **{get_category_label(a)}**: `{s:+.2f}`")

    st.divider()

    # ── Export filtered set ──
    st.subheader("💾 Export Filtered Items")
    df = pd.DataFrame(filtered)
    csv = df.to_csv(index=False).encode("utf-8")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ Download CSV",
            csv,
            "items_filtered.csv",
            "text/csv",
            use_container_width=True,
        )
    with c2:
        json_str = json.dumps(filtered, indent=2, default=str)
        st.download_button(
            "⬇️ Download JSON",
            json_str,
            "items_filtered.json",
            "application/json",
            use_container_width=True,
        )


# ═══════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════

if page == "🏠 Executive Dashboard":
    page_dashboard()
elif page == "📱 App Reviews":
    page_app_reviews()
elif page == "📰 News Intelligence":
    page_news()
elif page == "⭐ Review Platforms":
    page_review_platforms()
elif page == "📋 All Items":
    page_all_items()
elif page == "📊 Deep Analytics":
    page_analytics()
elif page == "⚠️ Crisis Monitor":
    page_crisis()