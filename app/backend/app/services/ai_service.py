import os
from transformers import pipeline

# 1. Map paths relative to this service file location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_ROOT = os.path.abspath(os.path.join(BASE_DIR, "../../../ai_pipeline/models"))

BART_PATH = os.path.join(MODELS_ROOT, "bart-large-mnli")
MINILM_PATH = os.path.join(MODELS_ROOT, "ms-marco-MiniLM-L-6-v2")

# 2. Initialize pipelines locally (No internet required after download)
print("🤖 Loading local AI models into memory...")
relevance_filter = pipeline("text-classification", model=MINILM_PATH, tokenizer=MINILM_PATH)
zero_shot_classifier = pipeline("zero-shot-classification", model=BART_PATH, tokenizer=BART_PATH)

def process_scraped_article(query: str, title: str, description: str):
    """
    Step 1: Check relevance. Step 2: Categorize topic.
    """
    # Cross-encoders expect a specific string structure for classification: "query <sep> document"
    text_to_score = f"{query} [SEP] {title} {description}"
    
    # MiniLM check
    filter_result = relevance_filter(text_to_score)[0]
    # Note: ms-marco cross-encoder outputs can require sigmoid normalization if scores exceed 0-1,
    # but the generic transformer pipeline maps its logit to a score.
    
    if filter_result['score'] < 0.7:
        return {"status": "ignored", "reason": f"Low relevance score: {filter_result['score']}"}

    # BART topic categorization
    labels = ["pricing", "feature announcement", "hiring", "funding", "acquisition", "layoff", "comparison", "irrelevant"]
    full_text = f"{title}. {description}"
    
    classification = zero_shot_classifier(full_text, candidate_labels=labels)
    
    return {
        "status": "processed",
        "relevance_score": filter_result['score'],
        "top_category": classification['labels'][0],
        "category_confidence": classification['scores'][0]
    }