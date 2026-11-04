"""Read-only: print the user's Gmail label names as a tree (no message content, no writes).

Run:  uv run python scripts/list_labels.py
Used to design the label resolver against the real label hierarchy.
"""

from googleapiclient.discovery import build
from phase0_check import get_credentials


def main() -> None:
    gmail = build("gmail", "v1", credentials=get_credentials())
    labels = gmail.users().labels().list(userId="me").execute()["labels"]
    names = sorted(x["name"] for x in labels if x["type"] == "user")
    for name in names:
        depth = name.count("/")
        print(f"{'  ' * depth}{name.rpartition('/')[2]}   [{name}]")
    print(f"\n{len(names)} user labels")


if __name__ == "__main__":
    main()
