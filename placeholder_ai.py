import random

# 1️⃣ Simple rule-based generator (works immediately)
POSITIVE_TEMPLATES = [
    "✨ {name}, you're doing great!",
    "🌟 Sending {vibe} vibes your way",
    "💫 Hope your {time} is wonderful",
    "🌻 You matter more than you know",
    "🕊️ Peace and positivity to you"
]

VIBES = ["good", "great", "awesome", "calm", "happy"]
TIMES = ["day", "morning", "afternoon", "evening"]


def generate_simple(name: str = "Friend") -> str:
    """Generate a positive placeholder using rules (no AI)"""
    template = random.choice(POSITIVE_TEMPLATES)
    return template.format(
        name=name,
        vibe=random.choice(VIBES),
        time=random.choice(TIMES)
    )


# 2️⃣ AI Generator Stub (swap in real model later)
def generate_ai(prompt: str, model_path: str = None) -> str:
    """
    Generate a positive placeholder using a local AI model.
    If model_path is None or model not installed, falls back to simple generator.
    """
    try:
        # This block only runs if user installs llama-cpp-python
        from llama_cpp import Llama

        if not model_path:
            # Default tiny model (you can change this)
            model_path = "models/tiny-llama-128M.Q4_K_M.gguf"

        # Load model (cached after first run)
        llm = Llama(model_path=model_path, n_ctx=512, verbose=False)

        # Simple prompt engineering
        prompt_text = f"Convert this message into one short, warm, positive phrase (max 10 words): '{prompt}'\nPhrase:"
        output = llm(prompt_text, max_tokens=30, stop=["\n"], echo=False)
        phrase = output['choices'][0]['text'].strip()

        return phrase if phrase else generate_simple()

    except ImportError:
        # llama-cpp-python not installed → fallback
        return generate_simple()
    except Exception:
        # Model load failed → fallback
        return generate_simple()


# 3️⃣ Unified generator (call this from your app)
def generate_placeholder(message: str, use_ai: bool = False, name: str = "Friend") -> str:
    if use_ai:
        return generate_ai(message)
    return generate_simple(name)