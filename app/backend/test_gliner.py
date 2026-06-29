from gliner import GLiNER

print("Loading GLiNER...")

model = GLiNER.from_pretrained(
    "urchade/gliner_medium-v2.1",
    local_files_only=True
)

print("SUCCESS")