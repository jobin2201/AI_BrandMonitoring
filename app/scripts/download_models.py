# Save this file as: app/scripts/download_models.py
import os
from transformers import AutoTokenizer, AutoModelForSequenceClassification

def download_local_model(model_name, folder_name):
    # Resolves path relative to app/scripts/ up to app/ai_pipeline/models/
    base_script_dir = os.path.dirname(os.path.abspath(__file__))
    local_dir = os.path.abspath(os.path.join(base_script_dir, f"../ai_pipeline/models/{folder_name}"))
    
    print(f"\n📥 Downloading {model_name} to local folder:\n👉 {local_dir}...")
    
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    
    tokenizer.save_pretrained(local_dir)
    model.save_pretrained(local_dir)
    print(f"✅ Successfully saved {model_name} locally!")

if __name__ == "__main__":
    # 1. Download BART for zero-shot topic tagging
    download_local_model("facebook/bart-large-mnli", "bart-large-mnli")
    
    # 2. Download MiniLM Cross-Encoder for fast relevance filtering
    download_local_model("cross-encoder/ms-marco-MiniLM-L-6-v2", "ms-marco-MiniLM-L-6-v2")
    
    print("\n🎉 All models downloaded and organized successfully!")