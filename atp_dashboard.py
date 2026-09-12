import html
from urllib.parse import parse_qs, urlparse

# Example player data
PLAYERS = [
    {"name": "Novak Djokovic", "country": "Serbia"},
    {"name": "Carlos Alcaraz", "country": "Spain"},
    {"name": "Jannik Sinner", "country": "Italy"},
    {"name": "Daniil Medvedev", "country": "Russia"},
]


def render_dashboard(search_query=""):
    """
    Render the dashboard.

    search_query is untrusted user input, so it MUST be escaped
    before being inserted into HTML.
    """

    # Escape HTML special characters and quotes.
    # quote=True is important because the value is also used
    # inside an HTML attribute.
    safe_search_query = html.escape(search_query, quote=True)

    # Use the ORIGINAL value for application logic.
    if search_query:
        query_lower = search_query.lower()

        filtered_players = [
            player
            for player in PLAYERS
            if query_lower in player["name"].lower()
            or query_lower in player["country"].lower()
        ]
    else:
        filtered_players = PLAYERS

    # Build player rows.
    player_rows = ""

    for player in filtered_players:
        # These values should also be escaped if they can originate
        # from an untrusted source.
        safe_name = html.escape(player["name"], quote=True)
        safe_country = html.escape(player["country"], quote=True)

        player_rows += f"""
        <tr>
            <td>{safe_name}</td>
            <td>{safe_country}</td>
        </tr>
        """

    if search_query:
        search_status = f"""
        <p class="search-status">
            Search results for: {safe_search_query}
        </p>
        """
    else:
        search_status = ""

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ATP Dashboard</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 40px;
            }}

            .search-status {{
                margin: 20px 0;
                padding: 10px;
                background: #f0f0f0;
            }}

            table {{
                border-collapse: collapse;
                width: 100%;
            }}

            th, td {{
                border: 1px solid #ccc;
                padding: 8px;
                text-align: left;
            }}
        </style>
    </head>

    <body>
        <h1>ATP Dashboard</h1>

        <form method="GET" action="/">
            <input
                type="text"
                name="search"
                value="{safe_search_query}"
                placeholder="Search players..."
            >
            <button type="submit">Search</button>
        </form>

        {search_status}

        <table>
            <thead>
                <tr>
                    <th>Player</th>
                    <th>Country</th>
                </tr>
            </thead>

            <tbody>
                {player_rows}
            </tbody>
        </table>
    </body>
    </html>
    """


def get_search_query(path):
    """
    Extract the search query from the URL.
    """
    parsed_url = urlparse(path)
    params = parse_qs(parsed_url.query)

    # parse_qs returns a list for each parameter.
    return params.get("search", [""])[0]
