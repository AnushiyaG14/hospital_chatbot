import re

def redact_pii(data):
    redacted = {}
    mapping = {}
    
    for key, value in data.items():
        if key in ["name", "email", "phone", "address"]:
            redacted_value = f"[REDACTED_{key.upper()}]"
            redacted[key] = redacted_value
            mapping[redacted_value] = value
        else:
            redacted[key] = value  # keep non-PII fields as-is

    return redacted, mapping


def unredact_pii(text, mapping):
    for tag, val in mapping.items():
        text = text.replace(tag, val)
    return text
