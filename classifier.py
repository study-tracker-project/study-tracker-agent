# 기본 STUDY 앱 목록 (추후 수정 필요[06.17]
STUDY_APPS = {
    "idea64.exe", "code.exe", "pycharm64.exe",
    "webstorm64.exe", "datagrip64.exe", "devenv.exe",
    "notion.exe", "obsidian.exe", "winword.exe",
    "excel.exe", "powerpnt.exe"
}

DISTRACT_APPS = {
    "kakaotalk.exe", "discord.exe", "steam.exe",
    "epicgameslauncher.exe", "leagueoflegends.exe"
}

# 기본 NEUTRAL 앱 목록 (집계 제외)
NEUTRAL_APPS = {
    "spotify.exe", "foobar2000.exe",
    "calc.exe", "clock.exe"
}

STUDY_DOMAINS = {
    "github.com", "stackoverflow.com", "inflearn.com",
    "velog.io", "notion.so", "medium.com", "docs.spring.io",
    "developer.mozilla.org", "w3schools.com", "leetcode.com",
    "programmers.co.kr", "acmicpc.net"
}

DISTRACT_DOMAINS = {
    "instagram.com", "youtube.com", "tiktok.com",
    "netflix.com", "twitter.com", "x.com", "facebook.com",
    "twitch.tv"
}


def classify_app(app_name: str, is_idle: bool, study_type: str) -> str:
    if is_idle:
        return "STUDY" if study_type == "OFFLINE" else "IDLE"

    app_lower = app_name.lower()

    if app_lower in STUDY_APPS:
        return "STUDY"
    if app_lower in DISTRACT_APPS:
        return "DISTRACT"
    if app_lower in NEUTRAL_APPS:
        return "NEUTRAL"

    return "NEUTRAL"


def classify_domain(domain: str) -> str:
    domain_lower = domain.lower()

    if domain_lower in STUDY_DOMAINS:
        return "STUDY"
    if domain_lower in DISTRACT_DOMAINS:
        return "DISTRACT"

    return "NEUTRAL"


def extract_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""