import os
import subprocess
from openai import OpenAI

# Setup new OpenAI client (API >= 1.0)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Get last 10 commit messages
commit_log = subprocess.check_output(
    ["git", "log", "-n", "10", "--pretty=format:%s"]
).decode("utf-8")

prompt = f"""
You are an expert release note writer.
Summarize the following commit messages into a clear, user-friendly changelog entry:

{commit_log}
"""

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": prompt}]
)

summary = response.choices[0].message.content

# Write output to CHANGELOG.md (append mode)
with open("CHANGELOG.md", "a") as f:
    f.write("\n## New release\n")
    f.write(summary)

print("✅ CHANGELOG.md updated successfully!")
