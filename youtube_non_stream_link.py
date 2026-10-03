#!/usr/bin/env python3
"""
Standalone YouTube live stream extractor.

Generates an M3U playlist from youtubelinks.xml without requiring Streamlink.

The extraction process follows the same general approach as the working
Streamlink YouTube plugin:

    YouTube channel/live page
        |
        +--> handle consent redirect if required
        |
        +--> resolve current live video ID
        |
        +--> YouTube InnerTube player API
        |
        +--> streamingData.hlsManifestUrl
        |
        +--> M3U playlist

Requirements:
    pip install requests

Streamlink is NOT required.
"""

import html
import json
import logging
import re
import xml.etree.ElementTree as ET

import requests


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_XML = "youtubelinks.xml"
OUTPUT_M3U = "youtube_output.m3u"

DEFAULT_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) "
    "Gecko/20100101 Firefox/157.0"
)

# Same InnerTube client configuration used by youtube.py
ANDROID_CLIENT = {
    "clientName": "ANDROID",
    "clientVersion": "21.08.266",
    "platform": "DESKTOP",
    "clientScreen": "EMBED",
    "clientFormFactor": "UNKNOWN_FORM_FACTOR",
    "browserName": "Chrome",
    "hl": "en",
    "gl": "US",
}


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ============================================================
# XML
# ============================================================

def parse_xml(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()

    channels = []

    for ch in root.findall("channel"):
        channels.append({
            "name": ch.findtext("channel-name", "").strip(),
            "tvg-id": ch.findtext("tvg-id", "").strip(),
            "tvg-name": ch.findtext("tvg-name", "").strip(),
            "tvg-logo": ch.findtext("tvg-logo", "").strip(),
            "group-title": ch.findtext(
                "group-title",
                "General",
            ).strip(),
            "youtube-url": ch.findtext(
                "youtube-url",
                "",
            ).strip(),
        })

    return channels


# ============================================================
# VIDEO ID EXTRACTION
# ============================================================

def extract_video_id_from_url(url):
    """
    Extract an 11-character YouTube video ID from a URL.
    """

    if not url:
        return None

    patterns = [
        r"(?:[?&]v=|/live/|/embed/|/v/|youtu\.be/)"
        r"([A-Za-z0-9_-]{11})(?:[?&#/]|$)",

        r"/shorts/"
        r"([A-Za-z0-9_-]{11})(?:[?&#/]|$)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            url,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return None


def extract_canonical_video_id(page):
    """
    Find a canonical YouTube watch URL.

    The working Streamlink plugin validates the canonical link and extracts
    the video ID from it. We deliberately search more flexibly here because
    the ordering of rel/href attributes can change.
    """

    if not page:
        return None

    page = html.unescape(page)
    page = page.replace("\\/", "/")

    # --------------------------------------------------------
    # First: actual canonical <link>
    # --------------------------------------------------------

    link_tags = re.findall(
        r"<link\b[^>]*>",
        page,
        re.IGNORECASE,
    )

    for tag in link_tags:

        if not re.search(
            r'\brel\s*=\s*["\']canonical["\']',
            tag,
            re.IGNORECASE,
        ):
            continue

        match = re.search(
            r'\bhref\s*=\s*["\']([^"\']+)["\']',
            tag,
            re.IGNORECASE,
        )

        if not match:
            continue

        href = match.group(1)

        video_id = extract_video_id_from_url(
            href
        )

        if video_id:
            return video_id

    # --------------------------------------------------------
    # Second: any YouTube watch URL in page
    # --------------------------------------------------------

    match = re.search(
        r'https?://(?:www\.)?youtube\.com/watch\?v='
        r'([A-Za-z0-9_-]{11})',
        page,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    # --------------------------------------------------------
    # Third: escaped watch URL
    # --------------------------------------------------------

    match = re.search(
        r'https?:\\/\\/(?:www\.)?youtube\.com\\/watch\?v='
        r'([A-Za-z0-9_-]{11})',
        page,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# JAVASCRIPT JSON EXTRACTION
# ============================================================

def extract_json_assignment(page, variable_name):
    """
    Extract a JavaScript object assigned to a variable such as:

        var ytInitialData = {...};

    or:

        var ytInitialPlayerResponse = {...};
    """

    if not page:
        return None

    pattern = re.compile(
        rf"(?:var\s+)?{re.escape(variable_name)}"
        rf"\s*=\s*",
        re.IGNORECASE,
    )

    match = pattern.search(page)

    if not match:
        return None

    start = page.find(
        "{",
        match.end(),
    )

    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for i in range(
        start,
        len(page),
    ):

        char = page[i]

        if in_string:

            if escaped:
                escaped = False

            elif char == "\\":
                escaped = True

            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            depth += 1

        elif char == "}":

            depth -= 1

            if depth == 0:

                raw_json = page[
                    start:i + 1
                ]

                try:
                    return json.loads(
                        raw_json
                    )

                except json.JSONDecodeError:
                    return None

    return None


def find_video_id_in_player_response(page):
    """
    Look specifically inside ytInitialPlayerResponse.
    """

    data = extract_json_assignment(
        page,
        "ytInitialPlayerResponse",
    )

    if not isinstance(data, dict):
        return None

    video_details = data.get(
        "videoDetails"
    )

    if not isinstance(
        video_details,
        dict,
    ):
        return None

    video_id = video_details.get(
        "videoId"
    )

    if (
        isinstance(video_id, str)
        and re.fullmatch(
            r"[A-Za-z0-9_-]{11}",
            video_id,
        )
    ):
        return video_id

    return None


def find_video_id_in_initial_data(page):
    """
    Search ytInitialData.

    This follows the same renderer types used by youtube.py:

        videoRenderer
        gridVideoRenderer
    """

    data = extract_json_assignment(
        page,
        "ytInitialData",
    )

    if not isinstance(data, dict):
        return None

    def walk(value):

        if isinstance(
            value,
            dict,
        ):

            for renderer_name in (
                "videoRenderer",
                "gridVideoRenderer",
            ):

                renderer = value.get(
                    renderer_name
                )

                if isinstance(
                    renderer,
                    dict,
                ):

                    video_id = renderer.get(
                        "videoId"
                    )

                    if (
                        isinstance(
                            video_id,
                            str,
                        )
                        and re.fullmatch(
                            r"[A-Za-z0-9_-]{11}",
                            video_id,
                        )
                    ):
                        yield video_id

            for child in value.values():
                yield from walk(child)

        elif isinstance(
            value,
            list,
        ):

            for child in value:
                yield from walk(child)

    for video_id in walk(data):
        return video_id

    return None


def find_generic_video_id(page):
    """
    Last-resort search.

    This is deliberately performed after the more reliable methods above.
    """

    if not page:
        return None

    patterns = [
        r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"',
        r"'videoId'\s*:\s*'([A-Za-z0-9_-]{11})'",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page,
        )

        if match:
            return match.group(1)

    return None


# ============================================================
# CONSENT HANDLING
# ============================================================

def extract_consent_form(page):
    """
    Extract the consent form action and hidden fields.

    This mirrors the behaviour of youtube.py's _get_res():

        if final URL == consent.youtube.com
            -> locate form
            -> submit hidden fields
            -> continue with YouTube response
    """

    if not page:
        return None, {}

    # Find consent form.
    form_match = re.search(
        r"<form\b([^>]*)>(.*?)</form>",
        page,
        re.IGNORECASE | re.DOTALL,
    )

    if not form_match:
        return None, {}

    form_attributes = form_match.group(1)
    form_body = form_match.group(2)

    action_match = re.search(
        r'\baction\s*=\s*["\']([^"\']+)["\']',
        form_attributes,
        re.IGNORECASE,
    )

    if not action_match:
        return None, {}

    action = html.unescape(
        action_match.group(1)
    )

    if action.startswith("/"):
        action = (
            "https://consent.youtube.com"
            + action
        )

    fields = {}

    for input_match in re.finditer(
        r"<input\b([^>]*)>",
        form_body,
        re.IGNORECASE | re.DOTALL,
    ):

        attributes = input_match.group(1)

        name_match = re.search(
            r'\bname\s*=\s*["\']([^"\']+)["\']',
            attributes,
            re.IGNORECASE,
        )

        if not name_match:
            continue

        value_match = re.search(
            r'\bvalue\s*=\s*["\']([^"\']*)["\']',
            attributes,
            re.IGNORECASE,
        )

        name = html.unescape(
            name_match.group(1)
        )

        value = ""

        if value_match:
            value = html.unescape(
                value_match.group(1)
            )

        fields[name] = value

    return action, fields


def handle_consent(
    session,
    response,
):
    """
    If YouTube redirected us to consent.youtube.com, submit the consent
    form and return the resulting YouTube response.
    """

    if response is None:
        return None

    current_url = response.url.lower()

    if "consent.youtube.com" not in current_url:
        return response

    logging.info(
        "YouTube consent page detected - "
        "submitting consent form"
    )

    action, fields = extract_consent_form(
        response.text
    )

    if not action:
        logging.warning(
            "Could not find YouTube consent form"
        )

        return response

    try:

        consent_response = session.post(
            action,
            data=fields,
            headers={
                "Referer": response.url,
            },
            timeout=30,
            allow_redirects=True,
        )

        consent_response.raise_for_status()

        logging.info(
            "YouTube consent handled successfully"
        )

        return consent_response

    except requests.RequestException as exc:

        logging.warning(
            f"Failed to submit YouTube consent: {exc}"
        )

        return response


# ============================================================
# HTTP
# ============================================================

def fetch_youtube_page(
    session,
    url,
):
    """
    Fetch a YouTube page and handle consent redirects.
    """

    try:

        response = session.get(
            url,
            timeout=30,
            allow_redirects=True,
        )

        response.raise_for_status()

    except requests.RequestException as exc:

        logging.error(
            f"Failed to fetch page: {exc}"
        )

        return None

    # This is the important behaviour copied from youtube.py.
    response = handle_consent(
        session,
        response,
    )

    return response


# ============================================================
# PAGE -> VIDEO ID
# ============================================================

def get_video_id_and_page(
    session,
    url,
):
    """
    Resolve a YouTube URL into:

        video_id, page_html
    """

    # --------------------------------------------------------
    # Direct video URL
    # --------------------------------------------------------

    video_id = extract_video_id_from_url(
        url
    )

    if video_id:

        logging.info(
            f"Extracted video ID from URL: {video_id}"
        )

        watch_url = (
            "https://www.youtube.com/watch?v="
            + video_id
        )

        response = fetch_youtube_page(
            session,
            watch_url,
        )

        if response is not None:
            return video_id, response.text

        return video_id, None

    # --------------------------------------------------------
    # Channel / live page
    # --------------------------------------------------------

    logging.info(
        f"Navigating to: {url}"
    )

    response = fetch_youtube_page(
        session,
        url,
    )

    if response is None:
        return None, None

    page = response.text

    logging.debug(
        f"Final YouTube page URL: {response.url}"
    )

    # --------------------------------------------------------
    # 1. Did YouTube redirect us directly to a video?
    # --------------------------------------------------------

    video_id = extract_video_id_from_url(
        response.url
    )

    if video_id:

        logging.info(
            f"Resolved redirected URL to video ID: "
            f"{video_id}"
        )

        return video_id, page

    # --------------------------------------------------------
    # 2. Canonical watch URL
    #
    # This is the method the working youtube.py relies on
    # through _schema_canonical().
    # --------------------------------------------------------

    video_id = extract_canonical_video_id(
        page
    )

    if video_id:

        logging.info(
            f"Resolved canonical URL to video ID: "
            f"{video_id}"
        )

        return video_id, page

    # --------------------------------------------------------
    # 3. ytInitialPlayerResponse
    # --------------------------------------------------------

    video_id = find_video_id_in_player_response(
        page
    )

    if video_id:

        logging.info(
            f"Resolved ytInitialPlayerResponse to "
            f"video ID: {video_id}"
        )

        return video_id, page

    # --------------------------------------------------------
    # 4. ytInitialData
    # --------------------------------------------------------

    video_id = find_video_id_in_initial_data(
        page
    )

    if video_id:

        logging.info(
            f"Resolved ytInitialData to video ID: "
            f"{video_id}"
        )

        return video_id, page

    # --------------------------------------------------------
    # 5. Generic videoId search
    # --------------------------------------------------------

    video_id = find_generic_video_id(
        page
    )

    if video_id:

        logging.info(
            f"Resolved generic videoId to: "
            f"{video_id}"
        )

        return video_id, page

    # --------------------------------------------------------
    # Nothing found
    # --------------------------------------------------------

    logging.warning(
        "Could not resolve a live video ID "
        "from channel page"
    )

    return None, page


# ============================================================
# API KEY / VISITOR DATA
# ============================================================

def extract_api_key(page):
    """
    Extract the current INNERTUBE_API_KEY.

    Same approach as youtube.py, with its public key as fallback.
    """

    if page:

        match = re.search(
            r"""["']INNERTUBE_API_KEY["']\s*:\s*["']([^"']+)["']""",
            page,
        )

        if match:
            return match.group(1)

    return DEFAULT_API_KEY


def extract_visitor_data(page):
    """
    Extract visitorData if YouTube supplied it.
    """

    if not page:
        return None

    patterns = [
        r"""["']visitorData["']\s*:\s*["']([^"']+)["']""",
        r"""["']VISITOR_DATA["']\s*:\s*["']([^"']+)["']""",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page,
        )

        if match:
            return match.group(1)

    return None


# ============================================================
# INNERTUBE PLAYER API
# ============================================================

def call_player_api(
    session,
    video_id,
    api_key,
    visitor_data=None,
):
    """
    Call YouTube's InnerTube player endpoint.

    This uses the same client context as youtube.py.
    """

    player_url = (
        "https://www.youtube.com/youtubei/v1/player"
    )

    client = dict(
        ANDROID_CLIENT
    )

    if visitor_data:
        client["visitorData"] = visitor_data

    payload = {
        "videoId": video_id,
        "contentCheckOk": True,
        "racyCheckOk": True,
        "context": {
            "client": client,
            "user": {
                "lockedSafetyMode": "false",
            },
            "request": {
                "useSsl": "true",
            },
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Origin": "https://www.youtube.com",
        "Referer": (
            "https://www.youtube.com/watch?v="
            + video_id
        ),
        "User-Agent": session.headers.get(
            "User-Agent",
            USER_AGENT,
        ),
    }

    try:

        response = session.post(
            player_url,
            params={
                "key": api_key,
            },
            json=payload,
            headers=headers,
            timeout=30,
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException as exc:

        logging.warning(
            f"Player API request failed: {exc}"
        )

    except ValueError as exc:

        logging.warning(
            f"Player API returned invalid JSON: {exc}"
        )

    return None


# ============================================================
# HLS EXTRACTION
# ============================================================

def extract_hls_from_response(data):
    """
    Extract streamingData.hlsManifestUrl.
    """

    if not isinstance(
        data,
        dict,
    ):
        return None

    playability = (
        data.get(
            "playabilityStatus"
        )
        or {}
    )

    status = playability.get(
        "status"
    )

    reason = playability.get(
        "reason"
    )

    if status and status not in (
        "OK",
        "LIVE_STREAM_OFFLINE",
    ):

        logging.warning(
            f"Playability status: {status}"
            + (
                f" - {reason}"
                if reason
                else ""
            )
        )

        return None

    streaming = (
        data.get(
            "streamingData"
        )
        or {}
    )

    # --------------------------------------------------------
    # Normal live HLS manifest
    # --------------------------------------------------------

    hls = streaming.get(
        "hlsManifestUrl"
    )

    if hls:
        return hls

    # --------------------------------------------------------
    # Fallback hlsFormats
    # --------------------------------------------------------

    for fmt in (
        streaming.get(
            "hlsFormats"
        )
        or []
    ):

        if not isinstance(
            fmt,
            dict,
        ):
            continue

        url = fmt.get(
            "url"
        )

        if not url:
            continue

        if (
            ".m3u8" in url.lower()
            or "manifest" in url.lower()
        ):
            return url

    return None


# ============================================================
# MAIN STREAM EXTRACTION
# ============================================================

def extract_youtube_stream(
    youtube_url,
):
    """
    Resolve a YouTube URL to an HLS stream URL.
    """

    session = requests.Session()

    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Encoding": (
            "gzip, deflate"
        ),
        "Connection": "keep-alive",
    })

    video_id, page = get_video_id_and_page(
        session,
        youtube_url,
    )

    if not video_id:

        logging.warning(
            "No video ID found"
        )

        return None

    logging.info(
        f"Using video ID: {video_id}"
    )

    # --------------------------------------------------------
    # API key
    # --------------------------------------------------------

    api_key = extract_api_key(
        page
    )

    if api_key == DEFAULT_API_KEY:

        logging.debug(
            "Using default InnerTube API key"
        )

    else:

        logging.debug(
            "Using API key extracted from page"
        )

    # --------------------------------------------------------
    # Visitor data
    # --------------------------------------------------------

    visitor_data = extract_visitor_data(
        page
    )

    if visitor_data:

        logging.debug(
            "Visitor data found"
        )

    # --------------------------------------------------------
    # Player API
    # --------------------------------------------------------

    data = call_player_api(
        session,
        video_id,
        api_key,
        visitor_data,
    )

    if not data:

        logging.warning(
            "No player API response"
        )

        return None

    # --------------------------------------------------------
    # HLS
    # --------------------------------------------------------

    hls = extract_hls_from_response(
        data
    )

    if hls:

        logging.info(
            "HLS retrieved successfully"
        )

        return hls

    logging.warning(
        "No HLS stream found"
    )

    return None


# ============================================================
# M3U
# ============================================================

def main():

    try:

        channels = parse_xml(
            INPUT_XML
        )

    except Exception as exc:

        logging.error(
            f"Failed to parse {INPUT_XML}: {exc}"
        )

        return

    exported = 0

    with open(
        OUTPUT_M3U,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as playlist:

        playlist.write(
            "#EXTM3U\n"
        )

        for channel in channels:

            logging.info(
                f"--- Processing: "
                f"{channel['name']} ---"
            )

            youtube_url = channel[
                "youtube-url"
            ]

            if not youtube_url:

                logging.warning(
                    f"No YouTube URL configured "
                    f"for {channel['name']}"
                )

                continue

            hls = extract_youtube_stream(
                youtube_url
            )

            if not hls:

                logging.warning(
                    f"Failed to find stream for "
                    f"{channel['name']}"
                )

                continue

            playlist.write(
                f'#EXTINF:-1 '
                f'tvg-id="{channel["tvg-id"]}" '
                f'tvg-name="{channel["tvg-name"]}" '
                f'tvg-logo="{channel["tvg-logo"]}" '
                f'group-title="{channel["group-title"]}",'
                f'{channel["name"]}\n'
            )

            playlist.write(
                f"{hls}\n"
            )

            exported += 1

            logging.info(
                f"Successfully exported "
                f"{channel['name']}"
            )

    logging.info(
        f"Playlist saved: {OUTPUT_M3U} "
        f"({exported}/{len(channels)} channels exported)"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()