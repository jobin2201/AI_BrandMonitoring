from transformers import utils
import os

cache_dir = utils.default_cache_path
model_folder = os.path.join(cache_dir, "models--facebook--bart-large-mnli")

if os.path.exists(model_folder):
    print(f"✅ Already installed at: {model_folder}")
else:
    print("❌ Not found in cache.")
