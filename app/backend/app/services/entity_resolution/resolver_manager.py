from .llm_entity_resolver import groq_resolve
from .wikipedia_resolver import wikipedia_resolve
from .entity_cache import get_cached_entity, set_cached_entity

def resolve_brand(query):
    cached = get_cached_entity(query)
    if cached:
        print(f"[ENTITY RESOLUTION] Cache hit for '{query}': {cached}")
        # Only accept if description or entity_name does NOT indicate animal, music, or ambiguous
        desc = (cached.get('description') or '').lower()
        name = (cached.get('entity_name') or '').lower()
        # List of forbidden/ambiguous terms
        forbidden = ["animal", "cat", "puma concolor", "black pumas", "singer", "band", "music", "song"]
        if any(term in desc or term in name for term in forbidden):
            print(f"[ENTITY RESOLUTION] Cache result rejected for '{query}' due to forbidden terms.")
        else:
            return cached

    # Always use both LLM and Wikipedia for every brand
    llm_result = None
    wiki_result = None
    try:
        print(f"[ENTITY RESOLUTION] Using Groq LLM for '{query}'")
        llm_result = groq_resolve(query)
        print(f"[ENTITY RESOLUTION][DEBUG] LLM result for '{query}': {llm_result}")
    except Exception as e:
        print(f"[ENTITY RESOLUTION] Groq failed for '{query}': {e}")

    try:
        print(f"[ENTITY RESOLUTION] Using Wikipedia for '{query}'")
        wiki_result = wikipedia_resolve(query)
        print(f"[ENTITY RESOLUTION][DEBUG] Wikipedia result for '{query}': {wiki_result}")
    except Exception as e:
        print(f"[ENTITY RESOLUTION] Wikipedia failed for '{query}': {e}")

    # Accept Wikipedia result only if the top result's title or summary contains the brand name (case-insensitive, exact match)
    def is_wiki_match(wiki, brand):
        if not wiki:
            return False
        brand_lc = brand.lower()
        title_lc = wiki.get("entity_name", "").lower()
        summary_lc = wiki.get("description", "").lower()
        return brand_lc in title_lc or brand_lc in summary_lc

    if wiki_result and is_wiki_match(wiki_result, query):
        print(f"[ENTITY RESOLUTION] Wikipedia result accepted for '{query}'")
        set_cached_entity(query, wiki_result)
        return wiki_result
    elif llm_result:
        print(f"[ENTITY RESOLUTION] LLM result accepted for '{query}'")
        set_cached_entity(query, llm_result)
        return llm_result
    else:
        print(f"[ENTITY RESOLUTION] No valid result for '{query}'")
        return {"entity_name": query, "description": "", "industry": "unknown", "search_terms": [query], "ignore_terms": []}
