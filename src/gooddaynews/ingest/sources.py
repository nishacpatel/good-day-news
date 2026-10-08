"""Source registry: read config/sources.yaml and keep the sources table in sync."""

from dataclasses import dataclass

from gooddaynews.settings import load_yaml

FETCHERS = ("news", "science", "official")


@dataclass(frozen=True)
class Source:
    name: str
    domain: str
    feed_url: str
    fetcher: str
    country: str
    credibility: int
    primary: bool = False
    active: bool = True
    id: int | None = None


def load_sources(fetcher: str | None = None) -> list[Source]:
    """Active sources from the YAML registry, optionally only one fetcher's list."""
    sources = [Source(**s) for s in load_yaml("sources.yaml")["sources"]]
    for s in sources:
        if s.fetcher not in FETCHERS:
            raise ValueError(f"{s.name}: unknown fetcher {s.fetcher!r}")
        if not 1 <= s.credibility <= 5:
            raise ValueError(f"{s.name}: credibility must be 1-5")
    return [s for s in sources if s.active and (fetcher is None or s.fetcher == fetcher)]


def sync_sources(conn, sources: list[Source]) -> list[Source]:
    """Upsert sources by domain and return them with their database ids."""
    synced = []
    for s in sources:
        rows = conn.run(
            """
            insert into sources (name, domain, feed_url, fetcher, country, credibility, is_primary, active)
            values (:name, :domain, :feed_url, :fetcher, :country, :credibility, :primary, :active)
            on conflict (domain) do update set
                name = excluded.name, feed_url = excluded.feed_url, fetcher = excluded.fetcher,
                country = excluded.country, credibility = excluded.credibility,
                is_primary = excluded.is_primary, active = excluded.active
            returning id
            """,
            name=s.name, domain=s.domain, feed_url=s.feed_url, fetcher=s.fetcher,
            country=s.country, credibility=s.credibility, primary=s.primary, active=s.active,
        )
        synced.append(Source(**{**s.__dict__, "id": rows[0][0]}))
    return synced
