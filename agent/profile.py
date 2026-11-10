"""A person's taste, kept out of the code: folders, time zone, currency, what they care about.

The defaults here are neutral. To make the agent yours, copy `profile.example.toml` to
`profile.toml` (gitignored) and edit it. Unknown keys are refused, so a typo cannot silently do
nothing.
"""

import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agent.schemas import Category

MAX_PREFERENCES = 20
MAX_PREFERENCE_CHARS = (
    300  # these lines go into the classifier prompt, so keep them short
)
DEFAULT_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Times in the digest and "same day" matching use this zone (an IANA name).
    timezone: str = "UTC"
    # Currency code -> symbol; a currency not listed is shown by its code ("CHF 20.00").
    currency_symbols: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_SYMBOLS)
    )
    # Your own Gmail folders the agent may learn sender rules from: folder -> category.
    learn_from_folders: dict[str, Category] = Field(default_factory=dict)
    # Your existing labels to file a category into, in order of preference. Anything not listed
    # falls back to an Agent/... label.
    file_into: dict[Category, list[str]] = Field(default_factory=dict)
    # Short plain-English lines about what you care about; added to the classifier prompt.
    preferences: list[str] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown timezone {value!r}") from error
        return value

    @field_validator("currency_symbols")
    @classmethod
    def _short_symbols(cls, value: dict[str, str]) -> dict[str, str]:
        for code, symbol in value.items():
            if not (len(code) == 3 and code.isalpha() and code.isupper()):
                raise ValueError(
                    f"currency code {code!r} must be three capital letters"
                )
            if not 1 <= len(symbol) <= 3:
                raise ValueError(f"symbol for {code} must be 1 to 3 characters")
        return value

    @field_validator("preferences")
    @classmethod
    def _sane_preferences(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_PREFERENCES:
            raise ValueError(f"at most {MAX_PREFERENCES} preference lines")
        cleaned = [line.strip() for line in value]
        for line in cleaned:
            if not line or len(line) > MAX_PREFERENCE_CHARS:
                raise ValueError(
                    f"each preference line must be 1 to {MAX_PREFERENCE_CHARS} characters"
                )
        return cleaned


def parse_profile(text: str, source: str) -> Profile:
    """A Profile from TOML text. `source` names where it came from, for error messages."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{source} is not valid TOML: {error}") from error
    try:
        return Profile(**data)
    except ValidationError as error:
        raise ValueError(f"{source} is not a valid profile: {error}") from error


def load_profile(path: Path) -> Profile:
    """The profile in `path`, or the neutral default when the file does not exist."""
    if not path.exists():
        return Profile()
    return parse_profile(path.read_text(), path.name)
