"""
Usage:
  Interactive mode (add one by one):
    python add_questions.py

  Add a single question directly:
    python add_questions.py "What is the capital of France?" "Paris"

  Import from a text file:
    python add_questions.py --file questions.txt

Text file format (one pair per two lines, blank line between):
    What is the capital of France?
    Paris

    Who is the king of Varrock?
    King Roald
"""

import json
import os
import sys

QUESTIONS_FILE = os.path.join(os.path.dirname(__file__), "questions.json")


def load():
    if not os.path.exists(QUESTIONS_FILE):
        return {"command": "", "current_index": 0, "questions": []}
    with open(QUESTIONS_FILE, "r") as f:
        return json.load(f)


def save(data):
    with open(QUESTIONS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def add_entry(data, question, answer):
    data["questions"].append({"question": question, "answer": answer})


def print_list(data):
    questions = data.get("questions", [])
    if not questions:
        print("  (no questions yet)")
        return
    for i, q in enumerate(questions):
        marker = ">" if i == data.get("current_index", 0) else " "
        print(f"  {marker} [{i+1}] {q['question']}  ||{q['answer']}||")


# ── Single question via arguments ─────────────────────────────────────────────
if len(sys.argv) == 3 and sys.argv[1] != "--file":
    data = load()
    add_entry(data, sys.argv[1].strip(), sys.argv[2].strip())
    save(data)
    print(f"Added: {sys.argv[1]}")
    sys.exit()

# ── Import from file ──────────────────────────────────────────────────────────
if len(sys.argv) == 3 and sys.argv[1] == "--file":
    path = sys.argv[2]
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f.readlines()]

    data = load()
    added = 0
    i = 0
    while i < len(lines):
        # skip blank lines
        if not lines[i].strip():
            i += 1
            continue
        question = lines[i].strip()
        i += 1
        # skip blank lines between question and answer
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            print(f"Warning: question without answer skipped: {question}")
            break
        answer = lines[i].strip()
        i += 1
        add_entry(data, question, answer)
        added += 1

    save(data)
    print(f"Imported {added} question(s).")
    print_list(data)
    sys.exit()

# ── Interactive mode ──────────────────────────────────────────────────────────
print("=== Question Adder ===")
print("Type a question and answer. Leave question blank to stop.\n")

data = load()
added = 0

while True:
    question = input("Question: ").strip()
    if not question:
        break
    answer = input("Answer:   ").strip()
    if not answer:
        print("Answer cannot be empty, skipping.\n")
        continue
    add_entry(data, question, answer)
    added += 1
    print(f"  ✓ Added\n")

save(data)
print(f"\nDone! Added {added} question(s). Total: {len(data['questions'])}")
print("\nCurrent list:")
print_list(data)
