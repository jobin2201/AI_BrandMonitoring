from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()

def analyse(text):
    scores = analyzer.polarity_scores(text)
    pos = scores["pos"]
    neg = scores["neg"]
    compound = scores["compound"]

    # Mixed sentiment detection
    if pos > 0.2 and neg > 0.2:
        label = "mixed"
    elif compound > 0.05:
        label = "positive"
    elif compound < -0.05:
        label = "negative"
    else:
        label = "neutral"

    return {
        "compound": compound,
        "label": label,
        "scores": scores
    }
