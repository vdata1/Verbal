import json
import rstr


# Load named regex dictionary
with open("valid_regex_named.json", "r", encoding="utf-8") as f:
    regex_dict = json.load(f)

output = {}

for key, pattern in regex_dict.items():
    samples = []
    try:
        for _ in range(10):
            samples.append(rstr.xeger(pattern))
    except Exception as e:
        samples = [f"Error generating samples: {e}"]
    output[key] = samples  # Use the same key from input

# Save generated samples to JSON
with open("string_samples.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print("Generated samples saved to string_samples.json")
