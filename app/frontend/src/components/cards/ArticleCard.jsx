import React from "react";
import dayjs from "dayjs";

const CATEGORY_LABELS = {
  // NEWS_CATEGORIES
  corporate_reputation: "🏢 Corporate Reputation",
  product_service:      "📦 Product & Service",
  leadership:           "👔 Leadership",
  financial_performance: "💹 Financial Performance",
  legal_regulatory:     "⚖️ Legal & Regulatory",
  esg:                  "🌱 ESG / Sustainability",
  competition:          "🎯 Competition",
  general:              "💬 General",

  // REVIEW_CATEGORIES
  performance:          "⚡ Performance",
  ui_ux:                "🎨 UI / UX",
  features:             "🔧 Features",
  ads_monetization:     "💰 Ads & Monetization",
  support:              "🛟 Support",
  security_privacy:     "🔒 Security & Privacy",

  // SOCIAL_CATEGORIES
  brand_mention:        "📣 Brand Mention",
  sentiment_opinion:    "💬 Sentiment / Opinion",
  complaint:            "😤 Complaint",
  praise:               "👏 Praise",
  question:             "❓ Question",
  viral_trend:          "🔥 Viral / Trend",
};

function ArticleCard({
  title,
  source_name,
  sentiment_label,
  sentiment_score,
  primary_category,
  emotion,
  sentiment_confidence,
  emotion_confidence,
  url,
  published_at,
  renderSentimentIcon,
}) {
  const normalizedSentiment = (sentiment_label || "neutral").toLowerCase();
  const normalizedScore = typeof sentiment_score === "number"
    ? sentiment_score
    : sentiment_score !== undefined && sentiment_score !== null && sentiment_score !== ""
      ? Number(sentiment_score)
      : null;
  const displaySentimentConfidence =
    sentiment_confidence !== undefined && sentiment_confidence !== null && sentiment_confidence !== ""
      ? sentiment_confidence
      : normalizedScore !== null && !Number.isNaN(normalizedScore)
        ? Math.abs(normalizedScore)
        : 0;
  const displayEmotion = emotion || "indifference";
  const displayEmotionConfidence =
    emotion_confidence !== undefined && emotion_confidence !== null && emotion_confidence !== ""
      ? emotion_confidence
      : 0.5;

  // Card background based on sentiment
  let bgColor = "#f5f5f5";
  if (normalizedSentiment === "positive") bgColor = "#d4f7d4";
  if (normalizedSentiment === "negative") bgColor = "#ffd6d6";
  if (normalizedSentiment === "neutral")  bgColor = "#f0f0f0";
  if (normalizedSentiment === "mixed")    bgColor = "#fff3cd";

  // Score badge color
  const score = normalizedScore !== null && !Number.isNaN(normalizedScore) ? normalizedScore : null;
  const scoreColor =
    score === null ? "#888"
    : score > 0.1  ? "#1a7a3c"
    : score < -0.1 ? "#c0392b"
    :                "#666";

  const categoryLabel = CATEGORY_LABELS[primary_category] || null;

  // Always show extra classifier details for all sources (NewsAPI, Reddit, YouTube)
  const extraDetails = (
    <div style={{
      display: "flex",
      flexWrap: "wrap",
      gap: 16,
      marginBottom: 8,
      marginTop: 2,
      alignItems: "center",
    }}>
      <span style={{
        background: "#f5f5f5",
        color: "#232946",
        borderRadius: 14,
        padding: "2px 10px",
        fontSize: 12,
        fontWeight: 500,
        border: "1px solid #e0e0e0",
      }}>
        <strong>Sentiment:</strong> {normalizedSentiment}
      </span>
      <span style={{
        background: "#f5f5f5",
        color: "#1a7a3c",
        borderRadius: 14,
        padding: "2px 10px",
        fontSize: 12,
        fontWeight: 500,
        border: "1px solid #e0e0e0",
      }}>
        <strong>Sentiment Confidence:</strong> {
          typeof displaySentimentConfidence === "number"
            ? displaySentimentConfidence.toFixed(3)
            : displaySentimentConfidence
        }
      </span>
      <span style={{
        background: "#eebbc3",
        color: "#232946",
        borderRadius: 14,
        padding: "2px 10px",
        fontSize: 12,
        fontWeight: 500,
        border: "1px solid #e0e0e0",
      }}>
        <strong>Emotion:</strong> {displayEmotion}
      </span>
      <span style={{
        background: "#eebbc3",
        color: "#232946",
        borderRadius: 14,
        padding: "2px 10px",
        fontSize: 12,
        fontWeight: 500,
        border: "1px solid #e0e0e0",
      }}>
        <strong>Emotion Confidence:</strong> {
          typeof displayEmotionConfidence === "number"
            ? displayEmotionConfidence.toFixed(2)
            : displayEmotionConfidence
        }
      </span>
    </div>
  );

  const content = (
    <>
      {/* Top row: sentiment icon/label + score badge */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 8 }}>
        <span style={{ fontWeight: 700, fontSize: 13, minWidth: 0 }}>
          {renderSentimentIcon
            ? <span style={{ verticalAlign: "middle", marginRight: 6 }}>{renderSentimentIcon}</span>
            : null}
          <strong>[{normalizedSentiment.toUpperCase()}]</strong>
        </span>

        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
          {score !== null && (
            <span style={{
              fontWeight: 700,
              fontSize: 15,
              color: scoreColor,
              background: "#fff",
              border: `1.5px solid ${scoreColor}`,
              borderRadius: 6,
              padding: "2px 10px",
              lineHeight: 1.2,
              whiteSpace: "nowrap",
            }}>
              {score > 0 ? `+${score.toFixed(2)}` : score.toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {/* Title */}
      <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 6, lineHeight: 1.4 }}>
        {title}
      </div>

      {/* Category pill(s) */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        {categoryLabel && (
          <span style={{
            background: "#232946",
            color: "#fff",
            borderRadius: 20,
            padding: "2px 10px",
            fontSize: 12,
            fontWeight: 500,
          }}>
            {categoryLabel}
          </span>
        )}
      </div>

      {/* Extra classifier details row */}
      {extraDetails}

      {/* Source + Date */}
      <div style={{ fontSize: 13, color: "#555" }}>
        <span>Source: {source_name}</span>
        {published_at && (
          <span style={{ color: "#888", marginLeft: 12 }}>
            {dayjs(published_at).format("YYYY-MM-DD HH:mm")}
          </span>
        )}
      </div>
    </>
  );

  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
      <div style={{
        background: bgColor,
        border: "1px solid #ddd",
        borderRadius: 10,
        padding: 16,
        marginBottom: 14,
        transition: "box-shadow 0.2s",
        boxShadow: "0 2px 8px #eaeaea",
      }}
        onMouseEnter={e => e.currentTarget.style.boxShadow = "0 4px 16px #ccc"}
        onMouseLeave={e => e.currentTarget.style.boxShadow = "0 2px 8px #eaeaea"}
      >
        {content}
      </div>
    </a>
  ) : (
    <div style={{
      background: bgColor,
      border: "1px solid #ddd",
      borderRadius: 10,
      padding: 16,
      marginBottom: 14,
    }}>
      {content}
    </div>
  );
}

export default ArticleCard;
