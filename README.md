# Email Agent

**An AI agent that reads your inbox so you don't have to.**

The email agent helps you keep your inbox clean. It reads your inbox, tells you which emails need
your attention and what to do about them, and labels them, learning your labelling style as it goes.
Newsletters become short summaries instead of an unread pile, promotions move to the bin only after
your approval, and bills and payments are pulled out. Everything arrives in a
single digest.

## Features

- **Knows what matters:** Emails from real people and anything with a deadline come first, each with
  the action it needs.
- **Summaries you can skim:** One line per newsletter and per important email; promotions and
  notifications collapse into a single line each.
- **Labels everything:** Each email gets one of your existing labels when one fits, or a dedicated
  label when none does. Labelled emails move out of your inbox, so it stays clear.
- **Takes a second look when unsure:** Uncertain emails are re-read in full before being left for
  your review.
- **Asks before it clears:** Promotions are listed with a short summary each, and only the ones you
  leave ticked move to the bin, where they stay recoverable for 30 days.
- **Understands your money:** Reads the biller, amount and due date from bills, matches payments to
  the bills they settle, flags what is due soon, and exports it all to a Google Sheet for downstream
  use such as expense tracking.
- **Adapts to you:** Follows the way you file your emails as it changes, and takes plain-English
  preferences such as *"delivery updates matter to me"*.
- **Keeps what matters in sight:** Important, unclear and starred emails always stay in your inbox.

<p align="center">
  <img src="docs/digest-sample.png" alt="A sample digest (invented data)" width="460">
  <br><sub>A sample digest, rendered from invented data.</sub>
</p>

## Architecture

### The agent

The LangGraph workflow. Solid steps run today, wired exactly as in the code; dashed steps are on the
roadmap.

```mermaid
graph TD;
    start([start]) --> fetch
    fetch --> prefilter
    fetch -.-> learn["learn from your corrections"]:::planned
    learn -.-> memory[("memory:<br/>rules and corrections")]:::planned
    memory -.-> prefilter
    prefilter --> classify
    classify --> propose
    classify -->|unsure| reread["re-read the full email<br/>(retry limit)"]
    reread --> classify
    propose -->|bills or payments found| extract
    propose -->|nothing to extract| finish([end of graph])
    extract --> finish
    finish --> digest["build and send the digest"]
    digest --> approval{{"wait for your approval<br/>(paused and saved)"}}
    approval -->|ticked emails| bin["move ticked promotions to the bin"]
    approval -->|keep all| done([done])
    bin --> done
    classDef planned stroke-dasharray: 5 5
```

| Step | What it does |
|---|---|
| **fetch** | Reads the new emails for the configured window. |
| **prefilter** | Settles what it can without AI: emails you have already filed, and senders it has learned. |
| **classify** | Sorts the rest into categories with Azure OpenAI; uncertain answers get a second look before being set aside for review. |
| **re-read** | Gives uncertain emails a second look using their full text, within a retry limit. |
| **propose** | Chooses a label for each email. |
| **extract** | Runs only when bills or payments were found, and reads out amounts, dates and payees. |
| **learn** *(planned)* | Notices emails you moved to a different label and remembers them for future runs. |
| **approval** | Pauses until you choose, on a private page linked from the digest, which promotions go. |
| **bin** | Moves only the emails you ticked to the bin, where they stay recoverable for 30 days. |

After the graph, the digest is assembled, labels are applied, bills are exported, and the digest is
sent. When there is something to clear, a small approval graph then pauses, its state saved, until you
answer. On the roadmap, every step's progress is saved, so a long run resumes where it stopped.

### In the cloud

```mermaid
flowchart LR
    trigger["⏰ Scheduled trigger"] --> func["Azure Functions<br/>runs the LangGraph agent"]
    kv["🔐 Azure Key Vault<br/>secrets"] -. "references" .-> func
    func -- "redacted text" --> aoai["Azure OpenAI"]
    func -- "read, label, send digest" --> mail[("Mailbox")]
    func -- "export bills" --> sheet[("Google Sheets")]
    func -- "logs" --> logs["Application Insights"]
    func -- "paused approvals" --> db[("Azure DocumentDB")]
    owner -- "approves from the digest" --> func
    logs --> alert["Alert rule"] --> owner["📧 Owner"]
```

## Inside the agent: LangGraph and LangChain

**LangGraph** runs the workflow. Every step reads from and writes to one typed, shared state, which
keeps each step small and independently testable. A conditional edge skips extraction entirely when
there is nothing to extract, and every step streams its progress, so a slow or stalled run shows
exactly where it is. Clearing promotions uses an interrupt: the run pauses at the approval step, its
state is checkpointed to a database, and your choice resumes it exactly where it stopped. Uncertain
emails loop back for a second look within a retry limit.

**LangChain** handles every conversation with the model. Prompts are templates, with your personal
preferences filled in safely at run time. Every answer is forced into a typed schema and validated
with Pydantic, and each answer is matched back to its email by id, never by position. Emails travel
in batches with a cap on parallel requests, which keeps runs fast, cheap and inside rate limits, and
an email the model refuses is retried on its own without failing the rest.

## Safety and privacy

- **Redaction before the model:** Account, card, phone and ID numbers, one-time codes and link paths
  are masked locally; amounts and dates are kept.
- **Prompt-injection defences:** Email text is treated as untrusted data, links written by the model
  are dropped, every email link in the digest points back to your own mailbox, and all text is escaped.
- **Secrets stay secret:** They live in Key Vault, and errors are logged without their message text.
- **No training on your emails:** Azure OpenAI does not use your emails to train or improve its models.
- **Nothing is cleared without you:** Clean-up links are signed and expire, opening one changes
  nothing, and only the emails you tick move to the bin.

## Preferences and Configurations

Two optional files hold your personal settings. Without them the agent uses neutral defaults.

- **`profile.toml`** (start from [`profile.example.toml`](profile.example.toml)): time zone, currency,
  which of your folders to learn from, where each category should be filed, and your preferences.
- **`digest.toml`**: the digest's sections, their order, and how each one is shown.

## Getting started

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), a Google Cloud OAuth client with the
Gmail and Sheets APIs enabled, and an Azure OpenAI deployment.

```bash
uv sync                                       # install
uv run pytest                                 # run the tests
uv run python scripts/daily_run.py            # preview the digest, change nothing
uv run python scripts/daily_run.py --apply    # run it for real
bash scripts/deploy.sh                        # deploy to Azure Functions
```

## Roadmap

- **Approve more before it acts:** The same pause-and-approve step extends to adding a new label or
  sender rule, and to sending a drafted reply.
- **Learns from your corrections:** Move an email to a different label, and the next run remembers.
  *(long-term memory)*
- **Picks up where it left off:** Large backlogs resume from the last processed email after any
  interruption. *(durable execution)*
- **Chat with your inbox:** Ask "which bills are due this week?" and follow up in the same conversation.
- **Reply drafting:** An assistant that checks your calendar, past emails and bills log, drafts a
  reply, and waits for your approval.
- **Specialist agents:** Bills, newsletters and other categories each get a dedicated agent,
  coordinated by a supervisor.
- **Faster digests:** Each section is summarized in parallel and merged into one digest.
- **Evaluation and tracing** with LangSmith.
