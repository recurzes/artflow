# Roles
ROLE_UNVERIFIED = "Unverified"
ROLE_VERIFIED_USER = "Verified User"
ROLE_VERIFIED_ARTIST = "Verified Artist"
ROLE_MODERATOR = "Moderator"
ROLE_18_VERIFIED = "18+ Verified"

# Core / transaction channels
CHANNEL_RULES_AND_TOS = "rules-and-tos"
CHANNEL_BOT_COMMANDS = "bot-commands"
CHANNEL_VERIFICATION_QUEUE = "verification-queue"
CHANNEL_ARTIST_DIRECTORY = "artist-directory"
CHANNEL_COMMISSIONS_OPEN = "commissions-open"
CHANNEL_COMPLETED_WORKS = "completed-works"
CHANNEL_REVIEWS = "reviews"
CHANNEL_ADMIN_LOGS = "admin-logs"
CHANNEL_AGE_CHECK = "age-check"

# Showcase
CHANNEL_SHOWCASE_ANIME = "showcase-anime"
CHANNEL_SHOWCASE_CHIBI = "showcase-chibi"
CHANNEL_SHOWCASE_VTUBER = "showcase-vtuber"
CHANNEL_SHOWCASE_PORTRAITS = "showcase-portraits"
CHANNEL_SHOWCASE_GENERAL = "showcase-general"
CHANNEL_NSFW_SHOWCASE = "nsfw-showcase"

SHOWCASE_CHANNEL_NAMES: tuple[str, ...] = (
    CHANNEL_SHOWCASE_ANIME,
    CHANNEL_SHOWCASE_CHIBI,
    CHANNEL_SHOWCASE_VTUBER,
    CHANNEL_SHOWCASE_PORTRAITS,
    CHANNEL_SHOWCASE_GENERAL,
    CHANNEL_NSFW_SHOWCASE,
)

# Slash
SHOWCASE_BY_SLUG: dict[str, str] = {
    "anime": CHANNEL_SHOWCASE_ANIME,
    "chibi": CHANNEL_SHOWCASE_CHIBI,
    "vtuber": CHANNEL_SHOWCASE_VTUBER,
    "portraits": CHANNEL_SHOWCASE_PORTRAITS,
    "general": CHANNEL_SHOWCASE_GENERAL,
    "nsfw": CHANNEL_NSFW_SHOWCASE,
}

CATEGORY_CORE = "ArtFlow — Core"
CATEGORY_SHOWCASE = "ArtFlow — Showcase"
CATEGORY_RECORDS = "ArtFlow — Records"
# Commission tickets get their own categories: Discord allows 50 channels per
# category, so these overflow into "<name> 2", "<name> 3", ...
CATEGORY_TICKETS = "ArtFlow — Tickets"
CATEGORY_CLOSED_TICKETS = "ArtFlow — Closed Tickets"